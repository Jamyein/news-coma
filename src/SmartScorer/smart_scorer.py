"""SmartScorer - 1-Pass AI 新闻评分核心协调器"""

import logging
from typing import List, Dict
from datetime import datetime
from collections import defaultdict

from src.models import NewsItem, AIConfig
from .batch_provider import BatchProvider
from .prompt_engine import PromptEngine
from .result_processor import ResultProcessor

logger = logging.getLogger(__name__)


class SmartScorer:
    """智能评分器 - 1-pass完成分类+评分+筛选"""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.batch_provider = BatchProvider(config)
        self.prompt_engine = PromptEngine(config)
        self.result_processor = ResultProcessor()
        self._stats = {
            'total_processed': 0,
            'total_api_calls': 0,
            'avg_processing_time': 0.0,
            'success_rate': 1.0
        }
        logger.info(f"SmartScorer初始化完成 (batch_size={config.batch_size})")
    
    async def score_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """1-pass评分入口"""
        if not items:
            return []
        
        start_time = datetime.now()
        logger.info(f"SmartScorer开始处理 {len(items)} 条新闻")
        
        batches = self._create_batches(items)
        scored_items = await self._process_batches(batches)
        final_items = self._select_top_items(scored_items)
        
        duration = (datetime.now() - start_time).total_seconds()
        self._update_stats(len(items), len(final_items), duration)
        
        logger.info(f"SmartScorer完成: {len(items)} → {len(final_items)} 条 ({duration:.1f}s)")
        return final_items
    
    def _create_batches(self, items: List[NewsItem]) -> List[List[NewsItem]]:
        """将新闻分批处理"""
        return [
            items[i:i + self.config.batch_size]
            for i in range(0, len(items), self.config.batch_size)
        ]

    async def _process_batches(self, batches: List[List[NewsItem]]) -> List[NewsItem]:
        """批量处理"""
        all_scored = []
        for batch in batches:
            prompt = self.prompt_engine.build_1pass_prompt(batch)
            response = await self.batch_provider.call_batch_api(prompt)
            scored_batch = self.result_processor.parse_1pass_response(batch, response)
            all_scored.extend(scored_batch)
        return all_scored

    def _select_top_items(self, items: List[NewsItem]) -> List[NewsItem]:
        """筛选Top新闻（按分数+多样性）"""
        sorted_items = sorted(items, key=lambda x: x.ai_score or 0, reverse=True)
        return self._ensure_diversity(sorted_items)
    
    def _ensure_diversity(self, items: List[NewsItem]) -> List[NewsItem]:
        """确保分类多样性"""
        if not items:
            return []

        max_items = self.config.max_output_items

        # 按分类分组
        by_category = defaultdict(list)
        for item in items:
            category = getattr(item, 'ai_category', '未分类')
            by_category[category].append(item)

        # 策略：每个分类先取1条，然后补充高分新闻
        selected = []
        for cat_items in by_category.values():
            if cat_items and len(selected) < max_items:
                selected.append(cat_items[0])

        for item in items:
            if item not in selected and len(selected) < max_items:
                selected.append(item)

        selected.sort(key=lambda x: x.ai_score or 0, reverse=True)
        return selected
    
    def _update_stats(self, input_count: int, output_count: int, duration: float):
        """更新统计信息"""
        self._stats['total_processed'] += input_count
        provider_stats = self.batch_provider.get_stats()
        self._stats['total_api_calls'] = provider_stats.get('api_call_count', 0)

        if self._stats['total_processed'] > 0:
            current_avg = self._stats['avg_processing_time']
            self._stats['avg_processing_time'] = (
                current_avg * (self._stats['total_processed'] - input_count) + duration
            ) / self._stats['total_processed']

    def get_stats(self) -> Dict:
        return self._stats.copy()

