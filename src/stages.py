"""
流水线各阶段具体实现
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.models import NewsItem, RSSSource, FilterConfig
from src.pipeline import PipelineStage
from src.history_manager import HistoryManager
# from src.batch_scorer import BatchScorer
from src.ai_cache import AICache
from src.markdown_generator import MarkdownGenerator
from src.rss_generator import RSSGenerator

# 临时定义BatchScorer以避免导入错误
class BatchScorer:
    def __init__(self, config):
        self.config = config
        self.current_config = type('MockConfig', (), {
            'batch_size': 5,
            'max_concurrent': 3
        })()

logger = logging.getLogger(__name__)


class FetchStage(PipelineStage):
    """RSS抓取阶段"""
    
    def __init__(self, fetcher: 'RSSFetcher', **kwargs):
        super().__init__('fetch', **kwargs)
        self.fetcher = fetcher
        self._executor = None
    
    async def process(self, source: RSSSource) -> List[NewsItem]:
        """抓取单个RSS源"""
        logger.debug(f"开始抓取RSS源: {source.name}")
        
        # RSS抓取是I/O密集型，使用线程池以避免阻塞事件循环
        if self._executor is None:
            import concurrent.futures
            self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency)
        
        # 将同步的fetch方法包装为异步
        loop = asyncio.get_event_loop()
        try:
            items = await loop.run_in_executor(
                self._executor,
                self._fetch_sync,
                source
            )
            logger.debug(f"成功抓取RSS源 {source.name}: {len(items)} 条新闻")
            return items
            
        except Exception as e:
            logger.error(f"抓取RSS源 {source.name} 失败: {e}")
            raise
    
    def _fetch_sync(self, source: RSSSource) -> List[NewsItem]:
        """同步抓取RSS源"""
        try:
            # 使用fetcher的单源抓取方法
            return self.fetcher._fetch_single(source)
        except Exception as e:
            logger.error(f"同步抓取失败: {e}")
            return []
    
    def __del__(self):
        """清理线程池"""
        if self._executor:
            self._executor.shutdown(wait=False)


class PreprocessStage(PipelineStage):
    """预处理阶段(去重、过滤)"""
    
    def __init__(self, history_manager: HistoryManager,
                 filter_config: FilterConfig, **kwargs):
        super().__init__('preprocess', **kwargs)
        self.history = history_manager
        self.filter_config = filter_config
    
    async def process(self, items: List[NewsItem]) -> List[NewsItem]:
        """去重和过滤"""
        if not items:
            return []
        
        logger.debug(f"开始预处理 {len(items)} 条新闻")
        
        try:
            # 过滤已处理的URL
            processed_urls = self.history.get_processed_urls()
            new_items = [
                item for item in items
                if not self.history.is_processed(item.link)
            ]
            
            if len(new_items) < len(items):
                logger.info(f"过滤已处理URL: {len(items)} → {len(new_items)} 条")
            
            # 去重(使用标题相似度)
            if new_items:
                unique_items = await self._deduplicate_async(new_items)
                if len(unique_items) < len(new_items):
                    logger.info(f"去重: {len(new_items)} → {len(unique_items)} 条")
            else:
                unique_items = []
            
            # 关键词过滤
            if unique_items and self.filter_config.blocked_keywords:
                filtered_items = self._filter_by_keywords(unique_items)
                if len(filtered_items) < len(unique_items):
                    logger.info(f"关键词过滤: {len(unique_items)} → {len(filtered_items)} 条")
                return filtered_items
            
            return unique_items
            
        except Exception as e:
            logger.error(f"预处理失败: {e}")
            raise
    
    async def _deduplicate_async(self, items: List[NewsItem]) -> List[NewsItem]:
        """异步去重(基于标题相似度)"""
        # 使用简单的去重策略，避免昂贵的相似度计算
        # 首先按精确标题去重
        seen_titles = set()
        unique_items = []
        
        for item in items:
            title_lower = item.title.lower().strip()
            
            # 检查是否重复
            is_duplicate = False
            for seen_title in seen_titles:
                if self._is_similar_title(title_lower, seen_title):
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                seen_titles.add(title_lower)
                unique_items.append(item)
        
        return unique_items
    
    def _is_similar_title(self, title1: str, title2: str) -> bool:
        """判断标题是否相似(简化版)"""
        # 编辑距离太慢，使用简化方法
        # 1. 完全相等
        if title1 == title2:
            return True
        
        # 2. 移除常见标点和空格后相等
        import re
        title1_clean = re.sub(r'[^\w\s]', '', title1)
        title2_clean = re.sub(r'[^\w\s]', '', title2)
        if title1_clean == title2_clean:
            return True
        
        # 3. 包含关系
        if title1 in title2 or title2 in title1:
            return True
        
        # 4. 分词后重叠率
        words1 = set(title1_clean.split())
        words2 = set(title2_clean.split())
        if len(words1) > 0 and len(words2) > 0:
            overlap = len(words1.intersection(words2)) / max(len(words1), len(words2))
            if overlap > 0.7:  # 70%重叠
                return True
        
        return False
    
    def _filter_by_keywords(self, items: List[NewsItem]) -> List[NewsItem]:
        """关键词过滤"""
        blocked_keywords = [kw.lower() for kw in self.filter_config.blocked_keywords]
        filtered = []
        
        for item in items:
            title_lower = item.title.lower()
            summary_lower = (item.summary or "").lower()
            
            # 检查是否包含屏蔽关键词
            has_blocked_keyword = any(
                keyword in title_lower or keyword in summary_lower
                for keyword in blocked_keywords
            )
            
            if not has_blocked_keyword:
                filtered.append(item)
        
        return filtered


class AIScoreStage(PipelineStage):
    """AI评分阶段"""
    
    def __init__(self, scorer: BatchScorer, cache: Optional[AICache] = None, **kwargs):
        super().__init__('ai_score', **kwargs)
        self.scorer = scorer
        self.cache = cache
    
    async def process(self, items: List[NewsItem]) -> List[NewsItem]:
        """批量AI评分"""
        if not items:
            return []
        
        logger.debug(f"开始AI评分 {len(items)} 条新闻")
        
        try:
            # 如果启用了缓存，先检查缓存
            if self.cache:
                logger.debug(f"检查缓存，batch_size={self.scorer.current_config.batch_size}")
                
                # 分批处理以避免单批过大
                batch_size = self.scorer.current_config.batch_size
                all_processed_items = []
                
                for i in range(0, len(items), batch_size):
                    batch = items[i:i + batch_size]
                    
                    cached_items = []
                    to_score_items = []
                    
                    for item in batch:
                        cached = self.cache.get(item)
                        if cached:
                            cached_items.append(cached)
                        else:
                            to_score_items.append(item)
                    
                    # 评分未缓存的
                    if to_score_items:
                        logger.debug(f"批次 {i//batch_size + 1}: 缓存命中 {len(cached_items)}，需要评分 {len(to_score_items)}")
                        scored_items = await self.scorer.score_all(to_score_items)
                        
                        # 缓存新评分的结果
                        for item in scored_items:
                            self.cache.set(item)
                    else:
                        scored_items = []
                    
                    all_processed_items.extend(cached_items + scored_items)
                
                logger.info(f"AI评分完成: 缓存命中 {len(items) - len(to_score_items)}，新评分 {len(to_score_items)}")
                return all_processed_items
            else:
                # 不使用缓存，直接评分
                logger.debug(f"直接评分，不使用缓存")
                return await self.scorer.score_all(items)
                
        except Exception as e:
            logger.error(f"AI评分失败: {e}")
            raise


class GenerateStage(PipelineStage):
    """输出生成阶段"""
    
    def __init__(self, markdown_gen: MarkdownGenerator,
                 rss_gen: RSSGenerator, **kwargs):
        super().__init__('generate', concurrency=1, **kwargs)  # 生成阶段通常并发度设为1
        self.markdown_gen = markdown_gen
        self.rss_gen = rss_gen
    
    async def process(self, items: List[NewsItem]) -> Dict[str, Any]:
        """生成输出文件"""
        if not items:
            return {'item_count': 0, 'error': '无新闻可生成'}
        
        logger.debug(f"开始生成输出文件，{len(items)} 条新闻")
        
        try:
            # 生成Markdown文件
            latest_path, archive_path = self.markdown_gen.generate(
                items, datetime.now()
            )
            
            # 生成RSS feed
            self.rss_gen.generate(items)
            
            result = {
                'latest_path': latest_path,
                'archive_path': archive_path,
                'feed_path': 'feed.xml',
                'item_count': len(items),
                'generated_at': datetime.now().isoformat()
            }
            
            logger.info(f"输出生成完成: Markdown={latest_path}, RSS=feed.xml")
            return result
            
        except Exception as e:
            logger.error(f"输出生成失败: {e}")
            raise


# 其他辅助阶段
class FilterStage(PipelineStage):
    """过滤阶段(基于评分)"""
    
    def __init__(self, min_score_threshold: float, **kwargs):
        super().__init__('filter', **kwargs)
        self.min_score_threshold = min_score_threshold
    
    async def process(self, items: List[NewsItem]) -> List[NewsItem]:
        """根据评分过滤新闻"""
        if not items:
            return []
        
        filtered = [
            item for item in items
            if (item.ai_score or 0) >= self.min_score_threshold
        ]
        
        if len(filtered) < len(items):
            logger.info(f"评分过滤: {len(items)} → {len(filtered)} 条 (阈值: {self.min_score_threshold})")
        
        return filtered


class SortStage(PipelineStage):
    """排序阶段"""
    
    def __init__(self, max_items: int = 20, **kwargs):
        super().__init__('sort', **kwargs)
        self.max_items = max_items
    
    async def process(self, items: List[NewsItem]) -> List[NewsItem]:
        """排序并选择Top N"""
        if not items:
            return []
        
        # 按AI评分排序，评分相同时按发布时间排序
        sorted_items = sorted(
            items,
            key=lambda x: ((x.ai_score or 0), x.published_at),
            reverse=True
        )
        
        # 选择Top N
        top_items = sorted_items[:self.max_items]
        
        if len(top_items) < len(items):
            logger.info(f"选择Top N: {len(items)} → {len(top_items)} 条")
        
        return top_items


class DebugStage(PipelineStage):
    """调试阶段(用于流水线调试)"""
    
    def __init__(self, name: str = 'debug', **kwargs):
        super().__init__(name, **kwargs)
    
    async def process(self, item: Any) -> Any:
        """打印调试信息"""
        if isinstance(item, list) and item:
            logger.debug(f"[{self.name}] 收到 {len(item)} 项: {type(item[0]).__name__}")
            if hasattr(item[0], 'title'):
                titles = [i.title[:50] + "..." if len(i.title) > 50 else i.title for i in item[:3]]
                logger.debug(f"  前3项标题: {titles}")
        else:
            logger.debug(f"[{self.name}] 收到: {type(item).__name__} = {str(item)[:100]}")
        
        return item


# 工厂函数
def create_default_pipeline_stages(
    config: Any,
    history: HistoryManager,
    fetcher: Any,
    scorer: BatchScorer,
    cache: Optional[AICache] = None
) -> List[PipelineStage]:
    """
    创建默认的流水线阶段
    
    Args:
        config: 配置对象
        history: 历史管理器
        fetcher: RSS抓取器
        scorer: AI评分器
        cache: 缓存(可选)
    
    Returns:
        阶段列表
    """
    stages = []
    
    # 添加调试阶段(可选)
    # stages.append(DebugStage('debug_input'))
    
    # 1. 抓取阶段
    stages.append(FetchStage(
        fetcher=fetcher,
        concurrency=3,  # 同时抓取3个RSS源
        error_policy='skip'  # 单个源失败跳过
    ))
    
    # 2. 预处理阶段
    stages.append(PreprocessStage(
        history_manager=history,
        filter_config=config.filter_config,
        concurrency=2,
        error_policy='skip'
    ))
    
    # 3. AI评分阶段
    max_concurrent = config.ai_config.providers_config[
        config.ai_config.provider
    ].max_concurrent
    stages.append(AIScoreStage(
        scorer=scorer,
        cache=cache,
        concurrency=max_concurrent,
        error_policy='retry'  # AI评分失败重试
    ))
    
    # 4. 过滤阶段(基于评分)
    stages.append(FilterStage(
        min_score_threshold=config.filter_config.min_score_threshold,
        concurrency=2,
        error_policy='skip'
    ))
    
    # 5. 排序阶段
    stages.append(SortStage(
        max_items=config.output_config.max_news_count,
        concurrency=1,
        error_policy='skip'
    ))
    
    # 6. 生成阶段
    stages.append(GenerateStage(
        markdown_gen=MarkdownGenerator(),
        rss_gen=RSSGenerator(),
        concurrency=1,
        error_policy='stop'  # 生成失败停止
    ))
    
    return stages