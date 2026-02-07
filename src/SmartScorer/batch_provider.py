"""BatchProvider - 1-Pass 批量API管理"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from openai import AsyncOpenAI, RateLimitError

from src.models import AIConfig, NewsItem
from src.exceptions import ContentFilterError

logger = logging.getLogger(__name__)


class BatchProvider:
    """批量API提供商管理器"""

    SYSTEM_PROMPT = (
        "你是一位资深新闻编辑，擅长评估新闻价值和撰写中文摘要。"
        "请对每条新闻进行分类和评分，返回JSON数组格式。"
    )

    def __init__(self, config: AIConfig):
        self.config = config
        self.provider_name = config.provider
        self.provider_config = config.providers_config.get(config.provider)

        if not self.provider_config:
            raise ValueError(f"未找到提供商配置: {config.provider}")

        self.client = AsyncOpenAI(
            api_key=self.provider_config.api_key,
            base_url=self.provider_config.base_url
        )
        self.model = self.provider_config.model
        self.api_call_count = 0
        self._prompt_engine = None  # 延迟加载PromptEngine

        logger.info(f"BatchProvider初始化: {self.provider_name} ({self.model})")

    @property
    def prompt_engine(self):
        """延迟加载 PromptEngine 实例"""
        if self._prompt_engine is None:
            from .prompt_engine import PromptEngine
            self._prompt_engine = PromptEngine(self.config)
        return self._prompt_engine

    async def _make_request(
        self,
        client: AsyncOpenAI,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        timeout: int
    ) -> str:
        """统一的核心API请求方法

        所有API请求都通过此方法发送，确保一致性。

        Args:
            client: OpenAI客户端实例
            model: 模型名称
            prompt: 用户提示词
            max_tokens: 最大token数
            temperature: 温度参数
            timeout: 超时时间(秒)

        Returns:
            API响应内容字符串

        Raises:
            asyncio.TimeoutError: 请求超时
            Exception: API调用失败
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"}
                ),
                timeout=timeout
            )

            return response.choices[0].message.content

        except asyncio.TimeoutError:
            logger.error(f"API调用超时 ({timeout}s)")
            raise
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            raise

    def _is_content_filter_error(self, error: Exception) -> bool:
        """检测是否为内容过滤错误（智谱AI错误码1301）"""
        error_str = str(error)
        # 智谱AI错误码1301 + contentFilter
        if "1301" in error_str and "contentFilter" in error_str:
            logger.warning(f"检测到智谱AI内容过滤: {error_str[:100]}")
            return True
        # OpenAI内容过滤
        if "content_filter" in error_str.lower():
            logger.warning(f"检测到内容过滤: {error_str[:100]}")
            return True
        return False

    def _extract_error_details(self, error: Exception) -> dict:
        """从错误中提取详细信息"""
        error_str = str(error)
        details = {
            "error_code": None,
            "provider": self.provider_name,
            "error_data": {}
        }
        
        # 尝试提取智谱AI错误码
        if "1301" in error_str:
            details["error_code"] = "1301"
        
        return details

    async def call_batch_api(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None
    ) -> str:
        """调用批量评分API（简化版）

        使用统一的 _make_request 方法发送请求。

        Args:
            prompt: 构建好的提示词
            max_tokens: 最大token数（默认使用配置值）
            temperature: 温度参数（默认使用配置值）
            timeout: 超时时间（默认使用配置值）

        Returns:
            API响应JSON字符串

        Raises:
            asyncio.TimeoutError: 请求超时
            Exception: API调用失败
        """
        max_tokens = max_tokens or self.provider_config.max_tokens
        temperature = temperature or self.provider_config.temperature
        timeout = timeout or self.config.timeout_seconds

        try:
            logger.debug(f"调用API: {self.provider_name}, timeout={timeout}s")
            self.api_call_count += 1

            return await self._make_request(
                client=self.client,
                model=self.model,
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout
            )

        except RateLimitError as e:
            logger.warning(f"速率限制: {e}")
            raise
        except Exception as e:
            # 检查是否为内容过滤错误
            if self._is_content_filter_error(e):
                error_details = self._extract_error_details(e)
                raise ContentFilterError(
                    message=str(e),
                    error_code=error_details["error_code"],
                    provider=error_details["provider"],
                    error_data=error_details["error_data"]
                )
            raise
    
    async def call_with_fallback(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """带自动回退的API调用"""
        try:
            return await self.call_batch_api(prompt, max_tokens, temperature)
        except Exception as e:
            logger.warning(f"主提供商 {self.provider_name} 失败: {e}")

        if not self.config.fallback_enabled:
            raise Exception("回退未启用，主提供商失败")

        for fallback_name in self.config.fallback_chain:
            if fallback_name not in self.config.providers_config:
                continue

            try:
                logger.info(f"尝试回退提供商: {fallback_name}")
                return await self._call_provider(
                    fallback_name, prompt, max_tokens, temperature
                )
            except Exception as e:
                logger.warning(f"回退提供商 {fallback_name} 失败: {e}")

        raise Exception("所有提供商均失败")

    async def _call_single_with_gemini(
        self,
        item: NewsItem,
        prompt_template: str
    ) -> dict:
        """
        使用Gemini单条处理新闻
        
        当批次触发内容过滤时，使用gemini逐条处理
        
        Args:
            item: 新闻项
            prompt_template: 原始prompt模板
            
        Returns:
            dict: 评分结果
        """
        if "gemini" not in self.config.providers_config:
            logger.error("Gemini未配置，无法进行单条fallback")
            raise ContentFilterError("Gemini未配置", provider="gemini")
        
        gemini_config = self.config.providers_config["gemini"]
        gemini_client = AsyncOpenAI(
            api_key=gemini_config.api_key,
            base_url=gemini_config.base_url
        )
        
        # 构建单条新闻的prompt
        summary = item.summary[:300] if item.summary else "无摘要"
        single_prompt = f"""请对以下新闻进行专业评估。

【新闻】
标题: {item.title}
来源: {item.source}
摘要: {summary}

{prompt_template}

【输出格式】JSON对象：
{{
  "category": "财经|科技|社会政治",
  "category_confidence": 0.95,
  "importance": 8,
  "timeliness": 9,
  "technical_depth": 7,
  "audience_breadth": 6,
  "practicality": 7,
  "total_score": 7.5,
  "summary": "中文总结..."
}}"""
        
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": single_prompt}
        ]
        
        try:
            response = await asyncio.wait_for(
                gemini_client.chat.completions.create(
                    model=gemini_config.model,
                    messages=messages,
                    max_tokens=gemini_config.max_tokens,
                    temperature=gemini_config.temperature,
                    response_format={"type": "json_object"}
                ),
                timeout=self.config.timeout_seconds
            )

            content = response.choices[0].message.content
            result = json.loads(content)

            # 处理Gemini返回数组的情况（当response_format为json_object时，有时返回[{...}])
            if isinstance(result, list):
                if len(result) > 0 and isinstance(result[0], dict):
                    result = result[0]
                else:
                    raise ValueError(f"Unexpected list format in response: {result}")
            elif not isinstance(result, dict):
                raise ValueError(f"Unexpected response type: {type(result)}, content: {content[:200]}")

            logger.debug(f"Gemini单条处理成功: {item.id}")

            # 标准化返回格式，添加news_index
            result["news_index"] = 1
            return result

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Gemini单条处理失败 {item.id}: {e}")
            # 返回默认低分结果
            return {
                "news_index": 1,
                "category": "社会政治",
                "category_confidence": 0.5,
                "importance": 3,
                "timeliness": 3,
                "technical_depth": 3,
                "audience_breadth": 3,
                "practicality": 3,
                "total_score": 3.0,
                "summary": f"Gemini处理失败: {str(e)[:50]}"
            }

    async def _retry_with_smaller_batches(
        self,
        items: List[NewsItem],
        prompt_template: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        将批次拆分为更小的子批次重试

        当主提供商触发内容过滤时，尝试减小批次规模后重试，
        以降低触发内容过滤的概率。

        Args:
            items: 原批次的新闻列表
            prompt_template: 评分标准说明
            max_tokens: 最大token数
            temperature: 温度参数

        Returns:
            str: 合并后的JSON结果字符串

        Raises:
            ContentFilterError: 子批次仍然触发内容过滤
            Exception: 其他API错误
        """
        # 计算子批次大小（至少2条，最多原批次的1/2）
        original_size = len(items)
        sub_batch_size = max(2, min(5, original_size // 2))

        logger.info(
            f"批次细分重试: 原批次{original_size}条 → 子批次{sub_batch_size}条"
        )

        all_results = []

        # 分批重试
        for i in range(0, original_size, sub_batch_size):
            sub_items = items[i:i + sub_batch_size]
            sub_batch_id = f"{i//sub_batch_size + 1}/{(original_size + sub_batch_size - 1)//sub_batch_size}"

            logger.debug(f"处理子批次 {sub_batch_id}: {len(sub_items)}条")

            try:
                # 构建子批次prompt
                sub_prompt = self.prompt_engine.build_1pass_prompt(sub_items)

                # 使用主提供商调用
                sub_response = await self.call_batch_api(
                    sub_prompt, max_tokens, temperature
                )

                # 解析子批次结果
                sub_results = json.loads(sub_response)
                if not isinstance(sub_results, list):
                    if isinstance(sub_results, dict) and 'results' in sub_results:
                        sub_results = sub_results['results']
                    else:
                        raise ValueError(f"Unexpected response format: {type(sub_results)}")

                # 调整news_index为全局索引
                for j, result in enumerate(sub_results):
                    if 'news_index' in result:
                        result['news_index'] = i + j + 1

                all_results.extend(sub_results)
                logger.debug(f"子批次 {sub_batch_id} 成功: {len(sub_results)}条结果")

            except ContentFilterError:
                # 子批次仍然触发内容过滤，记录日志并继续处理其他子批次
                logger.warning(f"子批次 {sub_batch_id} 仍触发内容过滤，跳过")
                # 为子批次添加默认结果
                for j, item in enumerate(sub_items):
                    all_results.append({
                        "news_index": i + j + 1,
                        "category": "社会政治",
                        "category_confidence": 0.5,
                        "importance": 3,
                        "timeliness": 3,
                        "technical_depth": 3,
                        "audience_breadth": 3,
                        "practicality": 3,
                        "total_score": 3.0,
                        "summary": "内容过滤，使用默认分"
                    })
                continue
            except Exception as e:
                # 其他错误，记录并继续
                logger.error(f"子批次 {sub_batch_id} 处理失败: {e}")
                # 为子批次添加默认结果
                for j, item in enumerate(sub_items):
                    all_results.append({
                        "news_index": i + j + 1,
                        "category": "社会政治",
                        "category_confidence": 0.5,
                        "importance": 3,
                        "timeliness": 3,
                        "technical_depth": 3,
                        "audience_breadth": 3,
                        "practicality": 3,
                        "total_score": 3.0,
                        "summary": f"处理失败: {str(e)[:30]}"
                    })
                continue

        if not all_results:
            raise ContentFilterError("所有子批次均触发内容过滤", provider=self.provider_name)

        logger.info(f"批次细分重试完成: {len(all_results)}/{original_size}条成功")

        # 返回JSON字符串格式
        return json.dumps({"results": all_results})

    async def _fallback_batch_with_gemini(
        self,
        items: List[NewsItem],
        prompt_template: str
    ) -> str:
        """
        使用Gemini逐条处理整个批次
        
        Args:
            items: 新闻批次
            prompt_template: 评分标准说明
            
        Returns:
            str: JSON数组字符串
        """
        logger.info(f"开始使用Gemini逐条处理 {len(items)} 条新闻")
        
        results = []
        for idx, item in enumerate(items, 1):
            try:
                result = await self._call_single_with_gemini(
                    item, prompt_template
                )
                # 更新news_index为实际索引
                result["news_index"] = idx
                results.append(result)
                logger.debug(f"Gemini处理进度: {idx}/{len(items)}")
            except Exception as e:
                logger.error(f"Gemini处理单条失败 {item.id}: {e}")
                # 添加默认结果
                results.append({
                    "news_index": idx,
                    "category": "社会政治",
                    "category_confidence": 0.5,
                    "importance": 3,
                    "timeliness": 3,
                    "technical_depth": 3,
                    "audience_breadth": 3,
                    "practicality": 3,
                    "total_score": 3.0,
                    "summary": "处理失败给予默认分"
                })
        
        logger.info(f"Gemini逐条处理完成: {len(results)} 条")
        
        # 返回JSON数组字符串
        return json.dumps({"results": results})

    async def call_batch_api_with_fallback(
        self,
        prompt: str,
        items: List[NewsItem],
        prompt_template: str = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        调用批量API，支持内容过滤fallback到Gemini单条处理
        
        Args:
            prompt: 完整prompt（包含所有新闻）
            items: 新闻项列表
            prompt_template: 评分标准说明（用于单条fallback）
            max_tokens: 最大token数
            temperature: 温度参数
            
        Returns:
            str: API响应或fallback结果的JSON字符串
        """
        try:
            # 首先尝试正常批次调用
            logger.debug(f"尝试主提供商批次调用: {self.provider_name}")
            return await self.call_batch_api(prompt, max_tokens, temperature)
            
        except ContentFilterError as e:
            # 明确的内容过滤错误
            logger.warning(
                f"主提供商 {self.provider_name} 触发内容过滤 "
                f"(错误码: {e.error_code})，尝试批次细分重试"
            )

            # 策略1: 先尝试减小批次规模重试
            if len(items) > self.config.min_batch_size_for_subdivision:
                try:
                    return await self._retry_with_smaller_batches(
                        items, prompt_template, max_tokens, temperature
                    )
                except Exception as retry_error:
                    logger.warning(f"批次细分重试失败: {retry_error}，切换到Gemini")
            else:
                logger.info(f"批次已较小(≤{self.config.min_batch_size_for_subdivision}条)，直接切换到Gemini处理")

            # 提取prompt中的评分标准说明
            if prompt_template is None:
                # 从原始prompt中提取评分标准部分
                prompt_template = self._extract_scoring_criteria(prompt)

            # 使用Gemini逐条处理（带速率限制）
            return await self._fallback_batch_with_gemini(items, prompt_template)
            
        except Exception as e:
            # 检查是否为内容过滤错误
            if self._is_content_filter_error(e):
                logger.warning(
                    f"主提供商 {self.provider_name} 触发内容过滤，"
                    f"切换到Gemini单条处理: {str(e)[:100]}"
                )
                
                if prompt_template is None:
                    prompt_template = self._extract_scoring_criteria(prompt)
                
                return await self._fallback_batch_with_gemini(items, prompt_template)
            else:
                # 非内容过滤错误，重新抛出
                raise

    def _extract_scoring_criteria(self, prompt: str) -> str:
        """
        从完整prompt中提取评分标准说明
        
        Args:
            prompt: 完整prompt字符串
            
        Returns:
            str: 评分标准说明部分
        """
        # 提取任务要求和评分维度说明
        import re
        
        # 查找评分相关的段落
        scoring_sections = []
        
        # 匹配5维度评分说明
        dimensions_pattern = r"([\d一二三四五]\s*\*\*[^*]+\*\*[^\n]+)"
        dimensions = re.findall(dimensions_pattern, prompt)
        if dimensions:
            scoring_sections.extend(dimensions)
        
        # 匹配权重说明
        weight_pattern = r"（权重[^）]+）"
        weights = re.findall(weight_pattern, prompt)
        
        # 构建评分标准说明
        if scoring_sections:
            return (
                "请按以下5维度评分（1-10分）：\n" +
                "\n".join(f"  {s}" for s in scoring_sections[:5]) +
                "\n\n计算加权总分并给出中文总结。"
            )
        
        # 默认评分说明
        return (
            "请按以下5维度评分（1-10分）：\n"
            "  1. 重要性（权重30%）\n"
            "  2. 时效性（权重20%）\n"
            "  3. 技术深度（权重20%）\n"
            "  4. 受众广度（权重15%）\n"
            "  5. 实用性（权重15%）\n"
            "\n计算加权总分并给出中文总结。"
        )

    async def _call_provider(
        self,
        provider_name: str,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """调用指定提供商（简化版）

        使用统一的 _make_request 方法发送请求。
        动态创建客户端并发送请求到指定的回退提供商。

        Args:
            provider_name: 提供商名称（如 'deepseek', 'gemini'）
            prompt: 用户提示词
            max_tokens: 最大token数
            temperature: 温度参数

        Returns:
            API响应JSON字符串

        Raises:
            KeyError: 提供商配置不存在
            Exception: API调用失败
        """
        config = self.config.providers_config[provider_name]

        # 动态创建客户端
        client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url
        )

        logger.info(f"使用提供商 {provider_name} (模型: {config.model})")

        return await self._make_request(
            client=client,
            model=config.model,
            prompt=prompt,
            max_tokens=max_tokens or config.max_tokens,
            temperature=temperature or config.temperature,
            timeout=self.config.timeout_seconds
        )
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "api_call_count": self.api_call_count
        }

    def reset_stats(self):
        self.api_call_count = 0
