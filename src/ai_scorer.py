"""
AI评分模块
负责使用OpenAI API对新闻进行评分、翻译和总结
支持14家国内外LLM提供商，自动回退
"""
import json
import logging
import asyncio
import time
from typing import List, Dict

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.models import NewsItem, AIConfig, ProviderConfig, FallbackConfig

logger = logging.getLogger(__name__)


class SimpleRateLimiter:
    """
    简单的异步令牌桶速率限制器
    """
    
    def __init__(self, max_requests: int = 60, time_window: float = 60.0):
        self.max_requests = max_requests
        self.time_window = time_window
        self.tokens = float(max_requests)
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    async def acquire(self, timeout: float = 120.0):
        """获取一个令牌，必要时等待"""
        async with self.lock:
            start_time = time.time()
            
            while self.tokens < 1:
                now = time.time()
                elapsed = now - self.last_update
                
                # 补充令牌
                self.tokens = min(
                    float(self.max_requests),
                    self.tokens + elapsed * (self.max_requests / self.time_window)
                )
                self.last_update = now
                
                if self.tokens < 1:
                    # 需要等待
                    wait_time = self.time_window / self.max_requests
                    
                    if time.time() - start_time + wait_time > timeout:
                        raise TimeoutError(f"速率限制等待超时（>{timeout}秒）")
                    
                    # 短暂释放锁让其他任务有机会执行
                    self.lock.release()
                    try:
                        await asyncio.sleep(wait_time)
                    finally:
                        await self.lock.acquire()
            
            self.tokens -= 1
            self.last_update = time.time()


class AIScorer:
    """AI新闻评分器 - 支持14家LLM提供商和自动回退"""
    
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
        
        logger.info(f"初始化AI提供商: {provider_name} ({self.model})")
    
    async def score_all(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分所有新闻，支持自动回退
        """
        if not self.fallback.enabled:
            # 不回退，直接使用当前提供商
            return await self._score_with_provider(items, self.current_provider_name)
        
        # 构建回退链
        fallback_chain = self._build_fallback_chain()
        last_exception = None
        
        for provider_name in fallback_chain:
            try:
                logger.info(f"🔄 尝试使用提供商: {provider_name}")
                
                # 临时切换到该提供商
                self._init_provider(provider_name)
                
                # 执行评分
                results = await self._score_with_provider(items, provider_name)
                
                logger.info(f"✅ 提供商 {provider_name} 调用成功")
                return results
                
            except Exception as e:
                logger.error(f"❌ 提供商 {provider_name} 失败: {e}")
                last_exception = e
                continue
        
        # 所有提供商都失败
        logger.error("❌ 所有AI提供商均失败，无法完成评分")
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
        """使用指定提供商评分"""
        provider_config = self.providers_config[provider_name]
        
        # 使用当前提供商的配置
        semaphore = asyncio.Semaphore(provider_config.max_concurrent)
        batch_size = provider_config.batch_size
        
        # 分批处理
        batches = [
            items[i:i+batch_size] 
            for i in range(0, len(items), batch_size)
        ]
        
        all_results = []
        
        for batch_idx, batch in enumerate(batches):
            logger.info(
                f"[{provider_name}] 处理第 {batch_idx+1}/{len(batches)} 批, "
                f"共 {len(batch)} 条"
            )
            
            tasks = []
            for item in batch:
                task = self._score_single_with_semaphore(semaphore, item, provider_config)
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for item, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[{provider_name}] 评分失败: {item.title[:50]}... "
                        f"错误: {result}"
                    )
                    item.ai_score = 5.0
                    item.translated_title = item.title
                    item.ai_summary = "评分失败"
                    item.key_points = []
                    all_results.append(item)
                else:
                    all_results.append(result)
        
        return all_results
    
    async def _score_single_with_semaphore(
        self, 
        semaphore: asyncio.Semaphore, 
        item: NewsItem,
        provider_config: ProviderConfig
    ) -> NewsItem:
        """使用信号量限制并发"""
        async with semaphore:
            return await self._score_single(item, provider_config)
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        reraise=True
    )
    async def _score_single(self, item: NewsItem, provider_config: ProviderConfig) -> NewsItem:
        """单条新闻评分"""
        # 应用速率限制
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        prompt = self._build_prompt(item)
        
        try:
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
            return self._parse_response(item, content)
            
        except Exception as e:
            logger.error(f"API调用失败 ({self.current_provider_name}): {e}")
            raise
    
    def _build_prompt(self, item: NewsItem) -> str:
        """构建评分Prompt"""
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
        
        return f"""
你是一位资深科技新闻编辑。请对以下新闻进行评分和分析。

评分维度（1-10分制）：
{chr(10).join(criteria_desc)}

新闻信息：
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:500] if item.summary else 'N/A'}

请按以下JSON格式返回(不要添加markdown代码块标记)：
{{
    "importance": 8,
    "timeliness": 9,
    "technical_depth": 7,
    "audience_breadth": 6,
    "practicality": 8,
    "total_score": 7.5,
    "chinese_title": "翻译成中文的标题",
    "chinese_summary": "200字左右的中文总结",
    "key_points": ["要点1", "要点2", "要点3"]
}}

注意：
1. total_score根据权重自动计算: importance×{self.criteria.get('importance', 0.3)} + timeliness×{self.criteria.get('timeliness', 0.2)} + technical_depth×{self.criteria.get('technical_depth', 0.2)} + audience_breadth×{self.criteria.get('audience_breadth', 0.15)} + practicality×{self.criteria.get('practicality', 0.15)}
2. chinese_title要准确传达原意，适合中文读者
3. chinese_summary要突出核心价值和影响
4. key_points列出3-5个关键要点
"""
    
    def _parse_response(self, item: NewsItem, content: str) -> NewsItem:
        """解析AI响应"""
        try:
            data = json.loads(content)
            
            # 计算加权总分
            total_score = (
                data.get('importance', 5) * self.criteria.get('importance', 0.3) +
                data.get('timeliness', 5) * self.criteria.get('timeliness', 0.2) +
                data.get('technical_depth', 5) * self.criteria.get('technical_depth', 0.2) +
                data.get('audience_breadth', 5) * self.criteria.get('audience_breadth', 0.15) +
                data.get('practicality', 5) * self.criteria.get('practicality', 0.15)
            )
            
            item.ai_score = round(total_score, 1)
            item.translated_title = data.get('chinese_title', item.title)
            item.ai_summary = data.get('chinese_summary', '')
            item.key_points = data.get('key_points', [])
            
            return item
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {content[:200]}... 错误: {e}")
            item.ai_score = 5.0
            item.translated_title = item.title
            item.ai_summary = "解析失败"
            item.key_points = []
            return item
        except Exception as e:
            logger.error(f"响应解析失败: {e}")
            item.ai_score = 5.0
            item.translated_title = item.title
            item.ai_summary = "解析失败"
            item.key_points = []
            return item
