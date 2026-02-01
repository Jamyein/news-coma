"""
AI评分模块
负责使用OpenAI API对新闻进行评分、翻译和总结
支持14家国内外LLM提供商，自动回退
新增：真批处理(True Batching)支持，大幅降低API成本
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
    """AI新闻评分器 - 支持14家LLM提供商、自动回退、真批处理"""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.fallback = config.fallback
        self.current_provider_name = config.provider
        self.providers_config = config.providers_config
        self.criteria = config.scoring_criteria
        
        # 真批处理配置
        self.use_true_batch = getattr(config, 'use_true_batch', True)
        self.true_batch_size = getattr(config, 'true_batch_size', 10)
        
        # 2-Pass评分配置
        self.use_2pass = getattr(config, 'use_2pass', True)
        self.pass1_threshold = getattr(config, 'pass1_threshold', 7.0)
        self.pass1_max_items = getattr(config, 'pass1_max_items', 40)
        
        # 三大板块差异化评分配置
        self.pass1_threshold_finance = getattr(config, 'pass1_threshold_finance', 5.5)
        self.pass1_threshold_tech = getattr(config, 'pass1_threshold_tech', 6.0)
        self.pass1_threshold_politics = getattr(config, 'pass1_threshold_politics', 5.5)
        self.pass1_use_category_specific = getattr(config, 'pass1_use_category_specific', True)
        
        # 板块配额配置
        self.category_quota_finance = getattr(config, 'category_quota_finance', 0.40)
        self.category_quota_tech = getattr(config, 'category_quota_tech', 0.30)
        self.category_quota_politics = getattr(config, 'category_quota_politics', 0.30)
        
        # API调用计数(用于监控)
        self.api_call_count = 0
        
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
        
        batch_mode = "真批处理" if self.use_true_batch else "单条处理"
        logger.info(f"初始化AI提供商: {provider_name} ({self.model}) - {batch_mode}")
    
    async def score_all(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分所有新闻，支持2-Pass评分、自动回退和真批处理
        """
        if not items:
            return []
        
        # 根据配置选择评分模式
        if self.use_2pass and len(items) > 10:
            logger.info(f"🎯 使用2-Pass评分: {len(items)} 条新闻")
            return await self._score_all_2pass(items)
        
        # 标准评分流程
        if not self.fallback.enabled:
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
        """
        使用指定提供商评分
        支持真批处理(True Batching) - 一次API调用处理多条新闻
        """
        provider_config = self.providers_config[provider_name]
        
        if self.use_true_batch:
            # 真批处理模式：一次API调用处理多条
            batch_size = self.true_batch_size
            logger.info(f"[{provider_name}] 使用真批处理: 每批{batch_size}条")
        else:
            # 传统模式：并发单条处理
            batch_size = provider_config.batch_size
            semaphore = asyncio.Semaphore(provider_config.max_concurrent)
        
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
            
            if self.use_true_batch:
                # 真批处理：一次API调用处理整批
                try:
                    results = await self._score_batch_api(batch, provider_config)
                    all_results.extend(results)
                    self.api_call_count += 1
                except Exception as e:
                    logger.error(f"真批处理失败，降级为单条处理: {e}")
                    # 降级：逐条处理
                    results = await self._score_batch_single(batch, provider_config)
                    all_results.extend(results)
            else:
                # 传统模式：并发单条处理
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
                        self.api_call_count += 1  # 失败也算一次调用尝试
                    else:
                        all_results.append(result)
                        self.api_call_count += 1
        
        logger.info(f"[{provider_name}] 评分完成: {len(all_results)}条, API调用: {self.api_call_count}次")
        return all_results
    
    # ==================== 真批处理功能 (新增) ====================
    
    def _build_batch_prompt(self, items: List[NewsItem]) -> str:
        """
        构建批量评分Prompt
        支持一次评估多条新闻，返回JSON数组
        """
        criteria_desc = []
        for key, weight in self.criteria.items():
            desc = {
                'importance': '重要性(行业影响)',
                'timeliness': '时效性',
                'technical_depth': '技术深度',
                'audience_breadth': '受众广度',
                'practicality': '实用性'
            }.get(key, key)
            criteria_desc.append(f"- {desc}: {int(weight*100)}%")
        
        # 构建新闻列表
        news_sections = []
        for i, item in enumerate(items, 1):
            news_sections.append(f"""
--- 新闻{i} ---
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:400] if item.summary else 'N/A'}
""")
        
        return f"""
你是一位资深科技新闻编辑。请对以下{len(items)}条科技新闻进行批量评分和分析。

【核心任务】
1. 新闻分类：将每条新闻分类到三板块之一
2. 按板块评分：根据所属板块使用对应的评分标准

【三板块分类标准】
- 财经板块：涉及金融市场、经济数据、企业财务、投资理财等
- 科技板块：涉及技术创新、产品研发、IT行业、人工智能等  
- 社会政治板块：涉及政策法规、社会事件、国际关系、公共事务等

【按板块评分标准】
- 财经新闻（5维度）：
  * 市场影响(40%)：对股市、债市、汇市等的影响程度
  * 投资价值(30%)：对投资决策的参考价值
  * 时效性(20%)：新闻的及时性和新鲜度
  * 深度(10%)：分析的深度和专业性
  * 受众广度(0%)：财经新闻此项权重为0

- 科技新闻（5维度）：
  * 技术创新(40%)：技术突破和创新程度
  * 实用性(30%)：实际应用价值和可行性
  * 影响力(20%)：对行业和社会的影响
  * 深度(10%)：技术解读的专业深度
  * 受众广度(0%)：科技新闻此项权重为0

- 社会政治新闻（5维度）：
  * 政策影响(40%)：对政策制定和执行的影响
  * 公众关注度(30%)：社会关注度和讨论热度
  * 时效性(20%)：新闻的及时性和紧迫性
  * 深度(10%)：背景分析的深入程度
  * 受众广度(0%)：社会政治新闻此项权重为0

【评分维度（1-10分制）】
{chr(10).join(criteria_desc)}

新闻列表:
{''.join(news_sections)}

【返回JSON数组格式】
[
    {{
        "news_index": 1,
        "category": "财经",
        "category_confidence": 0.85,
        "market_impact": 8,
        "investment_value": 7,
        "timeliness": 9,
        "depth": 6,
        "audience_breadth": 0,
        "total_score": 7.5,
        "chinese_title": "翻译成中文的标题",
        "chinese_summary": "200字左右的中文总结",
        "key_points": ["要点1", "要点2", "要点3"]
    }},
    {{
        "news_index": 2,
        "category": "科技",
        "category_confidence": 0.90,
        "innovation": 9,
        "practicality": 7,
        "influence": 8,
        "depth": 6,
        "audience_breadth": 0,
        "total_score": 8.0,
        "chinese_title": "翻译成中文的标题",
        "chinese_summary": "200字左右的中文总结",
        "key_points": ["要点1", "要点2", "要点3"]
    }},
    {{
        "news_index": 3,
        "category": "社会政治",
        "category_confidence": 0.75,
        "policy_impact": 7,
        "public_attention": 8,
        "timeliness": 9,
        "depth": 5,
        "audience_breadth": 0,
        "total_score": 7.4,
        "chinese_title": "翻译成中文的标题",
        "chinese_summary": "200字左右的中文总结",
        "key_points": ["要点1", "要点2", "要点3"]
    }},
    ...
]

【重要说明】
1. news_index必须对应新闻列表中的序号(从1开始)
2. category只能是"财经"、"科技"或"社会政治"之一
3. category_confidence是分类置信度，范围0-1
4. 评分字段根据category自动选择对应的5个维度：
   - 财经新闻: market_impact, investment_value, timeliness, depth, audience_breadth
   - 科技新闻: innovation, practicality, influence, depth, audience_breadth
   - 社会政治新闻: policy_impact, public_attention, timeliness, depth, audience_breadth
5. total_score根据对应板块的权重自动计算：
   - 财经: market_impact×0.4 + investment_value×0.3 + timeliness×0.2 + depth×0.1
   - 科技: innovation×0.4 + practicality×0.3 + influence×0.2 + depth×0.1
   - 社会政治: policy_impact×0.4 + public_attention×0.3 + timeliness×0.2 + depth×0.1
6. chinese_title要准确传达原意，适合中文读者
7. chinese_summary要突出核心价值和影响
8. key_points列出3-5个关键要点
9. 确保返回的是合法JSON数组，不要有其他文字说明
"""
    
    async def _score_batch_api(
        self, 
        items: List[NewsItem], 
        provider_config: ProviderConfig
    ) -> List[NewsItem]:
        """
        真批处理API调用
        一次API调用处理多条新闻，大幅降低API成本
        """
        if not items:
            return []
        
        # 应用速率限制
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        prompt = self._build_batch_prompt(items)
        
        try:
            # 增加token限制以容纳批处理内容
            # 估算：每条新闻约500 tokens，加上Prompt约1000 tokens
            estimated_tokens = 1000 + len(items) * 500
            max_tokens = min(estimated_tokens, 8000)  # 上限8000
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "你是一位资深新闻编辑和筛选员，擅长评估新闻价值和撰写中文摘要。你必须严格返回JSON数组格式。"
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=provider_config.temperature,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            return self._parse_batch_response(items, content)
            
        except Exception as e:
            logger.error(f"真批处理API调用失败: {e}")
            raise  # 抛出异常，让上层处理降级
    
    def _parse_batch_response(
        self, 
        items: List[NewsItem], 
        content: str
    ) -> List[NewsItem]:
        """
        解析批处理响应
        将JSON数组映射回新闻条目
        """
        try:
            # 清理可能的markdown标记
            content = content.strip()
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]
            content = content.strip()
            
            data = json.loads(content)
            
            # 处理可能的对象包装(某些模型会包装数组)
            if isinstance(data, dict):
                # 寻找数组字段
                for key, value in data.items():
                    if isinstance(value, list):
                        data = value
                        break
            
            if not isinstance(data, list):
                raise ValueError(f"期望JSON数组，得到: {type(data)}")
            
            # 映射结果到新闻条目
            results = []
            processed_indices = set()
            
            for item_data in data:
                try:
                    index = item_data.get('news_index', 0) - 1
                    if 0 <= index < len(items) and index not in processed_indices:
                        item = items[index]
                        
                        # 获取AI分类结果
                        category = item_data.get('category', '')
                        category_confidence = item_data.get('category_confidence', 0.0)
                        
                        # 存储分类信息到NewsItem
                        item.ai_category = category  # 使用AI分类结果
                        item.ai_category_confidence = category_confidence
                        
                        # 优先使用AI计算的total_score，如果不存在则自己计算
                        if 'total_score' in item_data:
                            # 使用AI计算的分数
                            total_score = float(item_data['total_score'])
                        else:
                            # 根据分类使用不同的权重计算分数
                            category = category.lower()
                            if '财经' in category:
                                # 财经新闻权重：市场影响40%，投资价值30%，时效性20%，深度10%，受众广度0%
                                total_score = (
                                    item_data.get('market_impact', 5) * 0.4 +
                                    item_data.get('investment_value', 5) * 0.3 +
                                    item_data.get('timeliness', 5) * 0.2 +
                                    item_data.get('depth', 5) * 0.1 +
                                    item_data.get('audience_breadth', 0) * 0.0
                                )
                            elif '科技' in category:
                                # 科技新闻权重：技术创新40%，实用性30%，影响力20%，深度10%，受众广度0%
                                total_score = (
                                    item_data.get('innovation', 5) * 0.4 +
                                    item_data.get('practicality', 5) * 0.3 +
                                    item_data.get('influence', 5) * 0.2 +
                                    item_data.get('depth', 5) * 0.1 +
                                    item_data.get('audience_breadth', 0) * 0.0
                                )
                            elif '社会政治' in category or '政治' in category:
                                # 社会政治新闻权重：政策影响40%，公众关注度30%，时效性20%，深度10%，受众广度0%
                                total_score = (
                                    item_data.get('policy_impact', 5) * 0.4 +
                                    item_data.get('public_attention', 5) * 0.3 +
                                    item_data.get('timeliness', 5) * 0.2 +
                                    item_data.get('depth', 5) * 0.1 +
                                    item_data.get('audience_breadth', 0) * 0.0
                                )
                            else:
                                # 未分类新闻使用通用权重
                                total_score = (
                                    item_data.get('importance', 5) * self.criteria.get('importance', 0.3) +
                                    item_data.get('timeliness', 5) * self.criteria.get('timeliness', 0.2) +
                                    item_data.get('technical_depth', 5) * self.criteria.get('technical_depth', 0.2) +
                                    item_data.get('audience_breadth', 5) * self.criteria.get('audience_breadth', 0.15) +
                                    item_data.get('practicality', 5) * self.criteria.get('practicality', 0.15)
                                )
                        
                        item.ai_score = round(total_score, 1)
                        item.translated_title = item_data.get('chinese_title', item.title)
                        item.ai_summary = item_data.get('chinese_summary', '')
                        item.key_points = item_data.get('key_points', [])
                        if not item.key_points:
                            item.key_points = []
                        
                        results.append(item)
                        processed_indices.add(index)
                        
                except Exception as e:
                    logger.error(f"解析单条结果失败: {e}")
                    continue
            
            # 处理未返回结果的条目(填充默认值)
            for i, item in enumerate(items):
                if i not in processed_indices:
                    logger.warning(f"批处理未返回结果[{i}]: {item.title[:50]}...")
                    item.ai_score = 5.0
                    item.translated_title = item.title
                    item.ai_summary = "批处理解析失败"
                    item.key_points = []
                    # 保持原始分类信息
                    item.ai_category_confidence = 0.0
                    results.append(item)
            
            logger.info(f"批处理解析成功: {len(results)}/{len(items)} 条")
            return results
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {content[:500]}... 错误: {e}")
            # 返回默认值
            for item in items:
                item.ai_score = 5.0
                item.translated_title = item.title
                item.ai_summary = "JSON解析失败"
                item.key_points = []
                item.ai_category_confidence = 0.0
            return items
        except Exception as e:
            logger.error(f"批处理响应解析失败: {e}")
            # 返回默认值
            for item in items:
                item.ai_score = 5.0
                item.translated_title = item.title
                item.ai_summary = "解析失败"
                item.key_points = []
                item.ai_category_confidence = 0.0
            return items
    
    async def _score_batch_single(
        self, 
        items: List[NewsItem], 
        provider_config: ProviderConfig
    ) -> List[NewsItem]:
        """
        降级为单条处理(当真批处理失败时)
        """
        results = []
        for item in items:
            try:
                scored = await self._score_single(item, provider_config)
                results.append(scored)
                self.api_call_count += 1
            except Exception as e:
                logger.error(f"单条处理也失败: {e}")
                item.ai_score = 5.0
                item.translated_title = item.title
                item.ai_summary = "处理失败"
                item.key_points = []
                results.append(item)
                self.api_call_count += 1
        return results
    
    # ==================== 原有单条处理功能 (保持不变) ====================
    
    async def _score_single_with_semaphore(
        self, 
        semaphore: asyncio.Semaphore, 
        item: NewsItem,
        provider_config: ProviderConfig
    ) -> NewsItem:
        """使用信号量限制并发(传统模式)"""
        async with semaphore:
            return await self._score_single(item, provider_config)
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5),
        reraise=True
    )
    async def _score_single(self, item: NewsItem, provider_config: ProviderConfig) -> NewsItem:
        """单条新闻评分(传统模式，用于降级)"""
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
                        "content": "你是一位资深新闻编辑，擅长评估新闻价值和撰写中文摘要。"
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
        """构建单条评分Prompt(传统模式)"""
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
你是一位资深新闻编辑。请对以下新闻进行评分和分析。

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
        """解析单条AI响应(传统模式)"""
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
            if not item.key_points:
                item.key_points = []
            
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
    
    def get_api_call_count(self) -> int:
        """获取API调用计数(用于监控)"""
        return self.api_call_count
    
    def reset_api_call_count(self):
        """重置API调用计数"""
        self.api_call_count = 0
    
    # ==================== 2-Pass评分功能 (Phase 2新增) ====================
    
    async def _score_all_2pass(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        2-Pass评分策略
        Pass 1: 快速预筛 → 识别高分潜力股
        Pass 2: 深度分析 → 重磅新闻深度解读
        """
        logger.info(f"🎯 启动2-Pass评分: {len(items)} 条新闻")
        
        # Pass 1: 快速预筛
        logger.info("🥇 Pass 1: 快速预筛...")
        pre_screen_items = await self._pass1_pre_screen(items)
        
        if not pre_screen_items:
            logger.warning("预筛后无新闻通过，返回原始列表")
            return items
        
        # Pass 2: 深度分析
        logger.info(f"🥈 Pass 2: 深度分析 {len(pre_screen_items)} 条...")
        final_items = await self._pass2_deep_analysis(pre_screen_items)
        
        return final_items
    
    async def _pass1_pre_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Pass 1: 按板块差异化快速预筛
        根据新闻分类使用不同的评分标准和阈值
        """
        # 如果未启用差异化评分，使用传统方法
        if not self.pass1_use_category_specific:
            return await self._pass1_pre_screen_legacy(items)
        
        # 1. 预分类：基于来源和关键词快速分类
        categorized_items = self._pre_categorize_items(items)
        
        # 2. 按板块分别进行快速评分
        all_scored_items = []
        
        # 处理财经新闻
        if categorized_items["财经"]:
            finance_passed = await self._pass1_finance_screen(categorized_items["财经"])
            all_scored_items.extend(finance_passed)
        
        # 处理科技新闻
        if categorized_items["科技"]:
            tech_passed = await self._pass1_tech_screen(categorized_items["科技"])
            all_scored_items.extend(tech_passed)
        
        # 处理社会政治新闻
        if categorized_items["社会政治"]:
            politics_passed = await self._pass1_politics_screen(categorized_items["社会政治"])
            all_scored_items.extend(politics_passed)
        
        # 处理未分类新闻（使用默认阈值）
        if categorized_items["未分类"]:
            uncategorized_passed = await self._pass1_generic_screen(categorized_items["未分类"])
            all_scored_items.extend(uncategorized_passed)
        
        # 3. 按分数排序，限制数量
        all_scored_items.sort(key=lambda x: x.ai_score, reverse=True)
        passed_items = all_scored_items[:self.pass1_max_items]
        
        # 4. 记录日志
        self._log_pass1_results(categorized_items, passed_items)
        
        return passed_items
        
        scored_items = []
        
        # 批量快速评分
        batch_size = min(self.true_batch_size, len(items))
        for i in range(0, len(items), batch_size):
            batch = items[i:i+batch_size]
            
            # 构建批量Prompt
            batch_prompt = "请对以下新闻进行批量快速评分:\n\n"
            for idx, item in enumerate(batch, 1):
                batch_prompt += f"新闻{idx}:\n"
                batch_prompt += f"标题: {item.title}\n"
                batch_prompt += f"来源: {item.source}\n"
                batch_prompt += f"摘要: {item.summary[:200]}\n\n"
            
            batch_prompt += """
请返回JSON数组格式:
[{"news_index": 1, "impact": 8, "quality": 7, "total": 7.5}, ...]
"""
            
            try:
                # 应用速率限制
                if self.rate_limiter:
                    await self.rate_limiter.acquire()
                
                # 调用API进行快速评分
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "快速评分助手，只返回JSON"},
                        {"role": "user", "content": batch_prompt}
                    ],
                    max_tokens=500,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                
                self.api_call_count += 1
                
                content = response.choices[0].message.content
                data = json.loads(content)
                
                # 处理数组或对象包装
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, list):
                            data = value
                            break
                
                # 映射评分结果
                if isinstance(data, list):
                    for item_data in data:
                        idx = item_data.get('news_index', 0) - 1
                        if 0 <= idx < len(batch):
                            item = batch[idx]
                            item.ai_score = item_data.get('total', 5.0)
                            scored_items.append(item)
                
            except Exception as e:
                logger.error(f"Pass 1快速评分失败: {e}")
                # 失败时给所有条目默认分数
                for item in batch:
                    item.ai_score = 5.0
                    scored_items.append(item)
        
        # 保留≥阈值的新闻
        threshold = self.pass1_threshold
        passed_items = [item for item in scored_items if item.ai_score >= threshold]
        
        # 限制数量
        if len(passed_items) > self.pass1_max_items:
            passed_items = sorted(
                passed_items,
                key=lambda x: x.ai_score,
                reverse=True
            )[:self.pass1_max_items]
        
        logger.info(
            f"预筛结果: {len(passed_items)}/{len(items)} 条通过 "
            f"(阈值≥{threshold}, 上限{self.pass1_max_items})"
        )
        return passed_items
    
    async def _pass2_deep_analysis(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Pass 2: 深度分析
        对预筛通过的新闻进行完整的5维度评分
        """
        # 使用标准真批处理流程
        if not self.fallback.enabled:
            return await self._score_with_provider(items, self.current_provider_name)
        
        # 构建回退链
        fallback_chain = self._build_fallback_chain()
        last_exception = None
        
        for provider_name in fallback_chain:
            try:
                logger.info(f"🔄 Pass 2尝试使用提供商: {provider_name}")
                self._init_provider(provider_name)
                results = await self._score_with_provider(items, provider_name)
                logger.info(f"✅ Pass 2提供商 {provider_name} 调用成功")
                return results
            except Exception as e:
                logger.error(f"❌ Pass 2提供商 {provider_name} 失败: {e}")
                last_exception = e
                continue
        
        logger.error("❌ Pass 2所有AI提供商均失败")
        raise last_exception
    
    # ==================== 三大板块差异化 Pass 1 方法 ====================
    
    def _pre_categorize_items(self, items: List[NewsItem]) -> Dict[str, List[NewsItem]]:
        """
        预分类：基于来源和关键词快速将新闻分为三大板块
        
        返回: {"财经": [], "科技": [], "社会政治": [], "未分类": []}
        """
        categorized = {
            "财经": [],
            "科技": [],
            "社会政治": [],
            "未分类": []
        }
        
        # 财经来源关键词
        finance_sources = [
            "wsj 经济", "wsj 市场", "financial times", "bloomberg", 
            "cnbc", "marketwatch", "ft.com", "华尔街见闻", 
            "东方财富", "财新", "经济观察", "36氪", "香港經濟日報",
            "the economist", "bbc business", "wsj 全球经济"
        ]
        
        # 科技来源关键词
        tech_sources = [
            "the verge", "techcrunch", "hacker news", "github blog",
            "arstechnica", "wired", "engadget", "36氪", "华尔街见闻"
        ]
        
        # 社会政治来源关键词
        politics_sources = [
            "bbc", "the guardian", "politico", "wsj 时政",
            "reuters", "associated press", "ap news", "36氪", "华尔街见闻"
        ]
        
        # 财经标题关键词
        finance_keywords = [
            "股票", "股市", "投资", "银行", "利率", "通胀", "财报", "earnings", 
            "stock", "investment", "market", "economy", "economic", "finance",
            "financial", "business", "company", "corporate", "profit", "revenue",
            "dollar", "yuan", "currency", "trade", "export", "import", "gdp",
            "央行", "美联储", "利率决议", "货币政策", "财政政策", "经济数据"
        ]
        
        # 科技标题关键词
        tech_keywords = [
            "ai", "artificial intelligence", "机器学习", "芯片", "软件", "app", 
            "tech", "technology", "digital", "computer", "internet", "web",
            "mobile", "phone", "smartphone", "device", "hardware", "software",
            "algorithm", "data", "cloud", "cybersecurity", "hack", "security",
            "startup", "innovation", "research", "development", "engineering",
            "人工智能", "机器学习", "深度学习", "神经网络", "算法", "大数据",
            "云计算", "区块链", "物联网", "5g", "芯片", "半导体", "处理器"
        ]
        
        # 社会政治标题关键词
        politics_keywords = [
            "政策", "选举", "政府", "特朗普", "拜登", "election", "policy", 
            "government", "political", "politics", "law", "regulation", "bill",
            "congress", "senate", "house", "parliament", "minister", "president",
            "prime minister", "diplomacy", "foreign", "international", "war",
            "peace", "conflict", "security", "defense", "military", "army",
            "environment", "climate", "energy", "health", "education", "welfare",
            "社会", "政治", "政策", "法规", "法律", "选举", "政府", "国会",
            "议会", "外交", "国际", "战争", "和平", "安全", "国防", "军事",
            "环境", "气候", "能源", "健康", "教育", "福利"
        ]
        
        for item in items:
            source_lower = item.source.lower()
            title_lower = item.title.lower()
            
            # 检查来源
            category_found = False
            
            # 检查财经来源
            if any(s in source_lower for s in finance_sources):
                item.pre_category = "财经"
                item.pre_category_confidence = 0.8  # 来源匹配，置信度高
                categorized["财经"].append(item)
                category_found = True
            
            # 检查科技来源
            elif any(s in source_lower for s in tech_sources):
                item.pre_category = "科技"
                item.pre_category_confidence = 0.8
                categorized["科技"].append(item)
                category_found = True
            
            # 检查社会政治来源
            elif any(s in source_lower for s in politics_sources):
                item.pre_category = "社会政治"
                item.pre_category_confidence = 0.8
                categorized["社会政治"].append(item)
                category_found = True
            
            # 如果来源未匹配，检查标题关键词
            if not category_found:
                # 检查财经关键词
                finance_match_count = sum(1 for k in finance_keywords if k in title_lower)
                tech_match_count = sum(1 for k in tech_keywords if k in title_lower)
                politics_match_count = sum(1 for k in politics_keywords if k in title_lower)
                
                # 选择匹配最多的类别
                max_count = max(finance_match_count, tech_match_count, politics_match_count)
                
                if max_count > 0:
                    if max_count == finance_match_count:
                        item.pre_category = "财经"
                        item.pre_category_confidence = 0.6  # 关键词匹配，置信度中等
                        categorized["财经"].append(item)
                    elif max_count == tech_match_count:
                        item.pre_category = "科技"
                        item.pre_category_confidence = 0.6
                        categorized["科技"].append(item)
                    elif max_count == politics_match_count:
                        item.pre_category = "社会政治"
                        item.pre_category_confidence = 0.6
                        categorized["社会政治"].append(item)
                else:
                    # 未匹配任何关键词
                    item.pre_category = ""
                    item.pre_category_confidence = 0.0
                    categorized["未分类"].append(item)
        
        return categorized
    
    async def _pass1_finance_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        财经新闻 Pass 1 快速预筛
        针对财经新闻特点优化的快速评分
        """
        prompt_template = """
快速评估这条财经新闻的价值(0-10分)。

评估标准（针对财经新闻优化）:
- 市场影响(40%): 对股市/债市/汇市的影响程度，重大政策、企业财报、市场波动等
- 投资价值(30%): 对投资决策的参考价值，是否能指导投资行为
- 时效性(20%): 新闻的及时性和新鲜度，市场反应时间
- 深度(10%): 分析的深度和专业性，数据支撑和逻辑性

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"market_impact": 8, "investment_value": 7, "timeliness": 9, "depth": 6, "total": 7.5}}
不要其他解释。
"""
        return await self._pass1_screen_with_prompt(items, prompt_template, self.pass1_threshold_finance)
    
    async def _pass1_tech_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        科技新闻 Pass 1 快速预筛
        针对科技新闻特点优化的快速评分
        """
        prompt_template = """
快速评估这条科技新闻的价值(0-10分)。

评估标准（针对科技新闻优化）:
- 技术创新(40%): 技术突破和创新程度，是否是重大技术进展
- 实用性(30%): 实际应用价值和可行性，落地可能性
- 影响力(20%): 对行业和社会的影响范围，关注度和传播度
- 深度(10%): 技术解读的专业深度，技术细节和原理阐述

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"innovation": 8, "practicality": 7, "impact": 9, "depth": 6, "total": 7.5}}
不要其他解释。
"""
        return await self._pass1_screen_with_prompt(items, prompt_template, self.pass1_threshold_tech)
    
    async def _pass1_politics_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        社会政治新闻 Pass 1 快速预筛
        针对社会政治新闻特点优化的快速评分
        """
        prompt_template = """
快速评估这条社会政治新闻的价值(0-10分)。

评估标准（针对社会政治新闻优化）:
- 政策影响(40%): 对政策制定和执行的影响程度，政策变化和法规调整
- 公众关注度(30%): 社会关注度和讨论热度，媒体报道和舆论反响
- 时效性(20%): 新闻及时性和紧迫性，事件发展速度和最新进展
- 深度(10%): 背景分析深入程度，历史脉络和多方观点

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"policy_impact": 8, "public_attention": 7, "timeliness": 9, "depth": 6, "total": 7.5}}
不要其他解释。
"""
        return await self._pass1_screen_with_prompt(items, prompt_template, self.pass1_threshold_politics)
    
    async def _pass1_generic_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        未分类新闻 Pass 1 通用预筛
        使用通用标准
        """
        prompt_template = """
快速评估这条新闻的价值(0-10分)。

评估标准:
- 重要性(40%): 新闻的重要程度和影响力
- 时效性(30%): 新闻的及时性和新鲜度
- 质量(30%): 内容质量和信息密度

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"importance": 8, "timeliness": 7, "quality": 7, "total": 7.4}}
不要其他解释。
"""
        return await self._pass1_screen_with_prompt(items, prompt_template, self.pass1_threshold)
    
    async def _pass1_screen_with_prompt(
        self, 
        items: List[NewsItem], 
        prompt_template: str,
        threshold: float
    ) -> List[NewsItem]:
        """
        通用的 Pass 1 筛查方法，使用指定的 prompt 模板
        """
        scored_items = []
        
        # 批量处理
        batch_size = min(self.true_batch_size, len(items))
        for i in range(0, len(items), batch_size):
            batch = items[i:i+batch_size]
            
            # 构建批量 Prompt
            batch_prompt = "请对以下新闻进行批量快速评分:\n\n"
            for idx, item in enumerate(batch, 1):
                batch_prompt += f"新闻{idx}:\n"
                batch_prompt += f"标题: {item.title}\n"
                batch_prompt += f"来源: {item.source}\n"
                batch_prompt += f"摘要: {item.summary[:200]}\n\n"
            
            batch_prompt += """
请返回JSON数组格式:
[{"news_index": 1, "total": 7.5}, ...]
"""
            
            try:
                # 应用速率限制
                if self.rate_limiter:
                    await self.rate_limiter.acquire()
                
                # 调用API进行快速评分
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "快速评分助手，只返回JSON"},
                        {"role": "user", "content": batch_prompt}
                    ],
                    max_tokens=500,
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                
                self.api_call_count += 1
                
                content = response.choices[0].message.content
                data = json.loads(content)
                
                # 处理数组或对象包装
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, list):
                            data = value
                            break
                
                # 映射评分结果
                if isinstance(data, list):
                    for item_data in data:
                        idx = item_data.get('news_index', 0) - 1
                        if 0 <= idx < len(batch):
                            item = batch[idx]
                            item.ai_score = item_data.get('total', 5.0)
                            scored_items.append(item)
                
            except Exception as e:
                logger.error(f"Pass 1快速评分失败: {e}")
                # 失败时给所有条目默认分数
                for item in batch:
                    item.ai_score = 5.0
                    scored_items.append(item)
        
        # 按分类保留≥阈值的新闻
        passed_items = [item for item in scored_items if item.ai_score >= threshold]
        
        return passed_items
    
    async def _pass1_pre_screen_legacy(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        传统 Pass 1 快速预筛（向后兼容）
        使用简化Prompt，只评估2个维度，快速过滤低价值新闻
        """
        # 构建简化Prompt模板
        prompt_template = """
快速评估这条科技新闻对开发者的价值(0-10分)。

评估标准:
- 影响力(行业影响+受众范围): 0-10分
- 质量(技术深度+实用性+时效性): 0-10分

新闻: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"impact": 8, "quality": 7, "total": 7.5}}
不要其他解释。
"""
        return await self._pass1_screen_with_prompt(items, prompt_template, self.pass1_threshold)
    
    def _log_pass1_results(self, categorized_items: Dict[str, List[NewsItem]], passed_items: List[NewsItem]) -> None:
        """
        记录 Pass 1 结果日志
        """
        total_input = sum(len(items) for items in categorized_items.values())
        total_passed = len(passed_items)
        
        logger.info(f"🎯 Pass 1 差异化预筛完成:")
        logger.info(f"   输入: {total_input}条新闻")
        
        for category, items in categorized_items.items():
            if items:
                passed_count = sum(1 for item in passed_items if item.pre_category == category)
                threshold = getattr(self, f"pass1_threshold_{category.lower()}", self.pass1_threshold)
                logger.info(f"   {category}: {len(items)}条 → {passed_count}条通过 (阈值≥{threshold})")
        
        logger.info(f"   总计: {total_passed}/{total_input}条通过 (上限{self.pass1_max_items}条)")
