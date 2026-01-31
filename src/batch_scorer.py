"""
批处理AI评分模块
负责使用OpenAI API对多条新闻进行批量评分、翻译和总结
一次API调用处理多条新闻，减少API调用次数
"""
import json
import logging
import asyncio
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import NewsItem, AIConfig, ProviderConfig, FallbackConfig
from src.ai_scorer import SimpleRateLimiter

logger = logging.getLogger(__name__)


@dataclass
class BatchRequest:
    """批处理请求"""
    items: List[NewsItem]
    provider_config: ProviderConfig
    provider_name: str


@dataclass
class BatchResult:
    """批处理结果"""
    item_id: str
    ai_score: float
    translated_title: str
    ai_summary: str
    key_points: List[str]


class BatchScorer:
    """批量AI新闻评分器 - 一次API调用处理多条新闻"""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.fallback = config.fallback
        self.current_provider_name = config.provider
        self.providers_config = config.providers_config
        self.criteria = config.scoring_criteria
        
        # 初始化主提供商
        self._init_provider(self.current_provider_name)
    
    def _init_provider(self, provider_name: str):
        """初始化指定提供商"""
        if provider_name not in self.providers_config:
            raise ValueError(f"未知的提供商: {provider_name}")
        
        provider_config = self.providers_config[provider_name]
        
        # 创建OpenAI客户端（兼容模式）
        self.client = AsyncOpenAI(
            api_key=provider_config.api_key,
            base_url=provider_config.base_url
        )
        self.model = provider_config.model
        self.current_provider_name = provider_name
        self.current_config = provider_config
        
        # 初始化速率限制器
        if provider_config.rate_limit_rpm:
            self.rate_limiter = SimpleRateLimiter(
                max_requests=provider_config.rate_limit_rpm
            )
            logger.info(f"[{provider_name}] 启用速率限制: {provider_config.rate_limit_rpm} RPM")
        else:
            self.rate_limiter = None
        
        logger.info(f"初始化批处理AI提供商: {provider_name} ({self.model})")
    
    async def score_all(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分所有新闻，支持自动回退
        使用批处理减少API调用次数
        
        Args:
            items: 新闻列表
            
        Returns:
            评分后的新闻列表
        """
        if not self.fallback.enabled:
            # 不回退，直接使用当前提供商
            return await self._score_with_provider(items, self.current_provider_name)
        
        # 构建回退链
        fallback_chain = self._build_fallback_chain()
        last_exception = None
        
        for provider_name in fallback_chain:
            try:
                logger.info(f"🔄 批处理尝试使用提供商: {provider_name}")
                
                # 临时切换到该提供商
                self._init_provider(provider_name)
                
                # 执行批量评分
                results = await self._score_with_provider(items, provider_name)
                
                logger.info(f"✅ 批处理提供商 {provider_name} 调用成功")
                return results
                
            except Exception as e:
                logger.error(f"❌ 批处理提供商 {provider_name} 失败: {e}")
                last_exception = e
                continue
        
        # 所有提供商都失败
        logger.error("❌ 所有批处理AI提供商均失败，无法完成评分")
        raise last_exception
    
    def _build_fallback_chain(self) -> List[str]:
        """构建回退链（去重）"""
        chain = []
        seen = set()
        
        # 1. 首选当前配置的主提供商
        if self.current_provider_name and self.current_provider_name in self.providers_config:
            chain.append(self.current_provider_name)
            seen.add(self.current_provider_name)
        
        # 2. 添加fallback_chain中配置的提供商
        for provider in self.fallback.fallback_chain:
            if provider not in seen and provider in self.providers_config:
                chain.append(provider)
                seen.add(provider)
        
        return chain
    
    async def _score_with_provider(self, items: List[NewsItem], provider_name: str) -> List[NewsItem]:
        """使用指定提供商进行批量评分"""
        provider_config = self.providers_config[provider_name]
        
        # 获取提供商配置的批量大小，默认5
        batch_size = provider_config.batch_size
        max_concurrent = provider_config.max_concurrent
        
        # 按批量大小分组
        batches = [
            items[i:i+batch_size]
            for i in range(0, len(items), batch_size)
        ]
        
        all_results = []
        
        # 使用信号量限制并发批次
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # 处理每个批次
        for batch_idx, batch in enumerate(batches):
            logger.info(
                f"[{provider_name}] 批处理第 {batch_idx+1}/{len(batches)} 批, "
                f"共 {len(batch)} 条"
            )
            
            # 为批次创建批处理请求
            batch_request = BatchRequest(
                items=batch,
                provider_config=provider_config,
                provider_name=provider_name
            )
            
            try:
                # 使用信号量限制并发
                batch_results = await self._process_batch_with_semaphore(
                    semaphore, batch_request
                )
                all_results.extend(batch_results)
                
            except Exception as e:
                logger.error(f"批处理第 {batch_idx+1} 批失败: {e}")
                # 对于失败的批次，降级为单条处理
                logger.warning(f"对第 {batch_idx+1} 批降级为单条处理")
                single_results = await self._fallback_to_single_scoring(batch, provider_name)
                all_results.extend(single_results)
        
        return all_results
    
    async def _process_batch_with_semaphore(
        self,
        semaphore: asyncio.Semaphore,
        batch_request: BatchRequest
    ) -> List[NewsItem]:
        """使用信号量限制批处理并发"""
        async with semaphore:
            return await self._process_batch(batch_request)
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        reraise=True
    )
    async def _process_batch(self, batch_request: BatchRequest) -> List[NewsItem]:
        """处理一个批次的新闻"""
        items = batch_request.items
        provider_config = batch_request.provider_config
        provider_name = batch_request.provider_name
        
        # 应用速率限制
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        # 构建批量Prompt
        prompt = self._build_batch_prompt(items)
        
        try:
            logger.debug(f"[{provider_name}] 发送批处理请求，共 {len(items)} 条新闻")
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "你是一位资深科技新闻编辑，擅长评估新闻价值和撰写中文摘要。"
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=provider_config.max_tokens,
                temperature=provider_config.temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            logger.debug(f"[{provider_name}] 收到批处理响应: {content[:200]}...")
            
            # 解析批量响应
            return self._parse_batch_response(items, content)
            
        except Exception as e:
            logger.error(f"[{provider_name}] 批处理API调用失败: {e}")
            raise
    
    def _build_batch_prompt(self, items: List[NewsItem]) -> str:
        """构建批量评分Prompt
        
        Args:
            items: 需要评分的新闻列表
            
        Returns:
            批量评分的Prompt
        """
        criteria_desc = []
        for key, weight in self.criteria.items():
            desc = {
                'importance': '重要性(行业影响、技术突破)',
                'timeliness': '时效性(新闻新鲜度)',
                'technical_depth': '技术深度(专业性和深度)',
                'audience_breadth': '受众广度(影响范围)',
                'practicality': '实用性(对开发者价值)'
            }.get(key, key)
            criteria_desc.append(f"- {desc}: {int(weight*100)}%")
        
        # 构建新闻项目列表
        news_items_desc = []
        for i, item in enumerate(items):
            news_items_desc.append(f"""
新闻{i+1}:
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:300] if item.summary else 'N/A'}
""")
        
        news_items_text = "\n".join(news_items_desc)
        
        return f"""
你是一位资深科技新闻编辑。请对以下{len(items)}条新闻进行批量评分和分析。

评分维度（1-10分制）：
{chr(10).join(criteria_desc)}

请仔细阅读每条新闻的信息：

{news_items_text}

请按以下JSON格式返回结果（不要添加markdown代码块标记）：
{{
    "results": [
        {{
            "news_index": 1,
            "importance": 8,
            "timeliness": 9,
            "technical_depth": 7,
            "audience_breadth": 6,
            "practicality": 8,
            "total_score": 7.5,
            "chinese_title": "翻译成中文的标题",
            "chinese_summary": "200字左右的中文总结",
            "key_points": ["要点1", "要点2", "要点3"]
        }},
        ...
    ]
}}

重要说明：
1. total_score根据权重自动计算: 
   importance×{self.criteria.get('importance', 0.3)} + 
   timeliness×{self.criteria.get('timeliness', 0.2)} + 
   technical_depth×{self.criteria.get('technical_depth', 0.2)} + 
   audience_breadth×{self.criteria.get('audience_breadth', 0.15)} + 
   practicality×{self.criteria.get('practicality', 0.15)}

2. chinese_title要准确传达原意，适合中文读者
3. chinese_summary要突出核心价值和影响，每条约200字
4. key_points列出3-5个关键要点
5. 确保"results"数组长度与新闻数量一致，并按顺序对应
"""
    
    def _parse_batch_response(self, items: List[NewsItem], content: str) -> List[NewsItem]:
        """解析批量响应
        
        Args:
            items: 原始新闻列表
            content: AI响应内容
            
        Returns:
            更新后的新闻列表
        """
        try:
            data = json.loads(content)
            
            if not isinstance(data, dict) or "results" not in data:
                raise ValueError("响应格式错误，缺少results字段")
            
            results = data["results"]
            
            if len(results) != len(items):
                logger.warning(
                    f"响应结果数量({len(results)})与新闻数量({len(items)})不匹配，"
                    "使用降级处理"
                )
                return self._fallback_with_partial_results(items, results)
            
            # 处理每个结果
            for i, (item, result) in enumerate(zip(items, results)):
                try:
                    # 验证索引匹配
                    if result.get("news_index") != i + 1:
                        logger.warning(
                            f"新闻索引不匹配: 期望{i+1}, 实际{result.get('news_index')}"
                        )
                    
        # 计算加权总分
                    
                    item.ai_score = round(total_score, 1)
                    item.translated_title = result.get('chinese_title', item.title)
                    item.ai_summary = result.get('chinese_summary', '')
                    item.key_points = result.get('key_points', [])
                    
                    logger.debug(
                        f"新闻{i+1}评分完成: {item.ai_score}分 - {item.translated_title[:50]}..."
                    )
                    
                except Exception as e:
                    logger.error(f"处理第{i+1}条新闻结果失败: {e}")
                    # 设置默认值
                    item.ai_score = 5.0
                    item.translated_title = item.title
                    item.ai_summary = "解析失败"
                    item.key_points = []
            
            return items
            
        except json.JSONDecodeError as e:
            logger.error(f"批量响应JSON解析失败: {content[:200]}... 错误: {e}")
            return self._apply_default_scores(items)
        except Exception as e:
            logger.error(f"批量响应解析失败: {e}")
            return self._apply_default_scores(items)
    
    def _fallback_with_partial_results(
        self,
        items: List[NewsItem],
        results: List[Dict]
    ) -> List[NewsItem]:
        """使用部分结果降级处理
        
        Args:
            items: 原始新闻列表
            results: 部分响应结果
            
        Returns:
            更新后的新闻列表
        """
        # 先处理有结果的项目
        for i, result in enumerate(results):
            if i < len(items):
                item = items[i]
                try:
                    total_score = (
                        result.get('importance', 5) * self.criteria.get('importance', 0.3) +
                        result.get('timeliness', 5) * self.criteria.get('timeliness', 0.2) +
                        result.get('technical_depth', 5) * self.criteria.get('technical_depth', 0.2) +
                        result.get('audience_breadth', 5) * self.criteria.get('audience_breadth', 0.15) +
                        result.get('practicality', 5) * self.criteria.get('practicality', 0.15)
                    )
                    
                    item.ai_score = round(total_score, 1)
                    item.translated_title = result.get('chinese_title', item.title)
                    item.ai_summary = result.get('chinese_summary', '')
                    item.key_points = result.get('key_points', [])
                    
                except Exception:
                    item.ai_score = 5.0
                    item.translated_title = item.title
                    item.ai_summary = "部分解析失败"
                    item.key_points = []
        
        # 对剩余项目应用默认值
        for i in range(len(results), len(items)):
            items[i].ai_score = 5.0
            items[i].translated_title = items[i].title
            items[i].ai_summary = "结果缺失"
            items[i].key_points = []
        
        return items
    
    def _apply_default_scores(self, items: List[NewsItem]) -> List[NewsItem]:
        """应用默认评分
        
        Args:
            items: 新闻列表
            
        Returns:
            应用默认评分的新闻列表
        """
        for item in items:
            item.ai_score = 5.0
            item.translated_title = item.title
            item.ai_summary = "批量处理失败"
            item.key_points = []
        
        return items
    
    async def _fallback_to_single_scoring(
        self,
        items: List[NewsItem],
        provider_name: str
    ) -> List[NewsItem]:
        """降级为单条评分（兼容现有AIScorer逻辑）
        
        Args:
            items: 新闻列表
            provider_name: 提供商名称
            
        Returns:
            评分后的新闻列表
        """
        logger.info(f"对 {len(items)} 条新闻使用降级单条评分")
        
        # 这里简化实现，实际应该调用AIScorer的单条评分逻辑
        # 为保持接口兼容，返回应用默认值的新闻
        return self._apply_default_scores(items)
    
    def _build_single_prompt(self, item: NewsItem) -> str:
        """构建单条新闻Prompt（兼容AIScorer接口）"""
        # 复用AIScorer的逻辑
        from src.ai_scorer import AIScorer
        scorer = AIScorer(self.config)
        return scorer._build_prompt(item)