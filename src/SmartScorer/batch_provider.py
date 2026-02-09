"""BatchProvider - 1-Pass 批量API管理"""

import asyncio
import json
import logging
from typing import Any
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

        # 主提供商客户端
        self._client = AsyncOpenAI(
            api_key=self.provider_config.api_key,
            base_url=self.provider_config.base_url
        )
        self.model = self.provider_config.model
        self.api_call_count = 0
        self._prompt_engine = None  # 延迟加载PromptEngine
        
        # Fallback 客户端缓存
        self._fallback_clients: dict[str, AsyncOpenAI] = {}

        logger.info(f"BatchProvider初始化: {self.provider_name} ({self.model})")

    @property
    def client(self) -> AsyncOpenAI:
        """获取主提供商客户端"""
        return self._client

    def _get_fallback_client(self, provider_name: str) -> AsyncOpenAI:
        """
        获取或创建 fallback 客户端（带缓存）
        
        Args:
            provider_name: 提供商名称
            
        Returns:
            AsyncOpenAI 客户端实例
            
        Raises:
            ValueError: 如果提供商配置不存在
        """
        if provider_name not in self._fallback_clients:
            config = self.config.providers_config.get(provider_name)
            if not config:
                raise ValueError(f"未找到 fallback 提供商配置: {provider_name}")
            
            self._fallback_clients[provider_name] = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url
            )
            logger.debug(f"创建 fallback 客户端: {provider_name}")
        
        return self._fallback_clients[provider_name]

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
        max_tokens: int | None = None,
        temperature: float | None = None,
        timeout: int | None = None
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
        max_tokens: int | None = None,
        temperature: float | None = None
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

    def _get_sub_batch_size(self, original_size: int) -> int:
        """根据fallback链动态计算子批次大小
        
        策略:
        1. 尝试使用fallback链中第一个可用提供商的batch_size
        2. 如果fallback链都不可用，使用主提供商的batch_size
        3. 确保不超过原批次大小
        
        Args:
            original_size: 原批次大小
            
        Returns:
            int: 计算后的子批次大小
        """
        sub_batch_size = None
        
        # 策略1: 使用fallback链中第一个可用提供商的batch_size
        if self.config.fallback_enabled and self.config.fallback_chain:
            for fallback_name in self.config.fallback_chain:
                if fallback_name in self.config.providers_config:
                    fallback_config = self.config.providers_config[fallback_name]
                    sub_batch_size = getattr(fallback_config, 'batch_size', None)
                    if sub_batch_size:
                        logger.debug(f"使用fallback提供商 '{fallback_name}' 的batch_size: {sub_batch_size}")
                        break
        
        # 策略A(保底): 使用主提供商的batch_size
        if sub_batch_size is None:
            sub_batch_size = getattr(self.provider_config, 'batch_size', 5)
            logger.debug(f"fallback链不可用，使用主提供商batch_size: {sub_batch_size}")
        
        # 确保不超过原批次大小，且至少为1
        sub_batch_size = min(sub_batch_size, original_size)
        sub_batch_size = max(1, sub_batch_size)
        
        return sub_batch_size

    async def _retry_with_smaller_batches(
        self,
        items: list[NewsItem],
        prompt_template: str,
        max_tokens: int | None = None,
        temperature: float | None = None
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
        # 计算子批次大小（基于fallback提供商限制）
        original_size = len(items)
        sub_batch_size = self._get_sub_batch_size(original_size)

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
                # 子批次触发内容过滤，使用fallback提供商处理
                logger.warning(f"子批次 {sub_batch_id} (大小={len(sub_items)}) 触发内容过滤，尝试fallback提供商")
                try:
                    # 使用带fallback的API调用处理该子批次
                    fallback_response = await self.call_with_fallback(sub_prompt, max_tokens, temperature)
                    
                    # 解析fallback结果
                    fallback_results = json.loads(fallback_response)
                    if not isinstance(fallback_results, list):
                        if isinstance(fallback_results, dict) and 'results' in fallback_results:
                            fallback_results = fallback_results['results']
                        else:
                            raise ValueError(f"Unexpected response format: {type(fallback_results)}")
                    
                    # 调整news_index为全局索引
                    for j, result in enumerate(fallback_results):
                        if 'news_index' in result:
                            result['news_index'] = i + j + 1
                    
                    all_results.extend(fallback_results)
                    logger.info(f"子批次 {sub_batch_id} fallback处理成功: {len(fallback_results)}条")
                    
                except Exception as fallback_error:
                    logger.error(f"子批次 {sub_batch_id} fallback处理失败: {fallback_error}")
                    # 所有fallback都失败，添加默认结果
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
                            "summary": f"fallback失败: {str(fallback_error)[:30]}"
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

    def _create_default_results_response(
        self,
        items: list[NewsItem],
        reason: str = "处理失败"
    ) -> str:
        """
        创建默认分数响应
        
        当所有处理方式都失败时，返回默认低分结果
        """
        results = []
        for idx, item in enumerate(items, 1):
            results.append({
                "news_index": idx,
                "chinese_title": item.title,
                "category": "社会政治",
                "category_confidence": 0.5,
                "importance": 3,
                "timeliness": 3,
                "technical_depth": 3,
                "audience_breadth": 3,
                "practicality": 3,
                "total_score": 3.0,
                "summary": f"[{reason}: 使用默认分数]"
            })
        
        return json.dumps({"results": results})

    async def call_batch_api_with_fallback(
        self,
        prompt: str,
        items: list[NewsItem],
        prompt_template: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None
    ) -> str:
        """
        调用批量API，支持fallback处理
        
        简化流程:
        1. 尝试主提供商批量调用
        2. 失败 ContentFilterError → 拆小批次重试
        3. 子批次失败 → 使用call_with_fallback批量调用fallback链
        4. 所有fallback失败 → 返回默认分数
        
        Args:
            prompt: 完整prompt（包含所有新闻）
            items: 新闻项列表
            prompt_template: 评分标准说明（用于fallback）
            max_tokens: 最大token数
            temperature: 温度参数
            
        Returns:
            str: API响应或fallback结果的JSON字符串
        """
        try:
            # 1. 首先尝试正常批次调用
            logger.debug(f"尝试主提供商批次调用: {self.provider_name}")
            return await self.call_batch_api(prompt, max_tokens, temperature)
            
        except ContentFilterError as e:
            # 明确的内容过滤错误
            logger.warning(
                f"主提供商 {self.provider_name} 触发内容过滤 "
                f"(错误码: {e.error_code})，尝试批次细分重试"
            )

            # 2. 尝试减小批次规模重试
            if len(items) > self.config.min_batch_size_for_subdivision:
                try:
                    return await self._retry_with_smaller_batches(
                        items, prompt_template, max_tokens, temperature
                    )
                except Exception as retry_error:
                    logger.warning(f"批次细分重试失败: {retry_error}")
            else:
                logger.info(f"批次已较小(≤{self.config.min_batch_size_for_subdivision}条)，尝试fallback提供商")

            # 3. 尝试fallback链（批量调用）
            try:
                logger.info("尝试fallback提供商批量调用")
                return await self.call_with_fallback(prompt, max_tokens, temperature)
            except Exception as fallback_error:
                logger.error(f"所有fallback提供商均失败: {fallback_error}")
                # 4. 返回默认分数
                return self._create_default_results_response(
                    items, 
                    "内容过滤且所有fallback失败"
                )
            
        except Exception as e:
            # 检查是否为内容过滤错误
            if self._is_content_filter_error(e):
                logger.warning(
                    f"主提供商 {self.provider_name} 触发内容过滤，"
                    f"尝试fallback提供商: {str(e)[:100]}"
                )
                
                try:
                    return await self.call_with_fallback(prompt, max_tokens, temperature)
                except Exception as fallback_error:
                    logger.error(f"Fallback失败: {fallback_error}")
                    return self._create_default_results_response(
                        items,
                        "内容过滤且fallback失败"
                    )
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
        max_tokens: int | None = None,
        temperature: float | None = None
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
        # 使用缓存的客户端
        client = self._get_fallback_client(provider_name)
        config = self.config.providers_config[provider_name]

        logger.info(f"使用提供商 {provider_name} (模型: {config.model})")

        return await self._make_request(
            client=client,
            model=config.model,
            prompt=prompt,
            max_tokens=max_tokens or config.max_tokens,
            temperature=temperature or config.temperature,
            timeout=self.config.timeout_seconds
        )
    
    def get_stats(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "api_call_count": self.api_call_count
        }

    def reset_stats(self):
        self.api_call_count = 0
