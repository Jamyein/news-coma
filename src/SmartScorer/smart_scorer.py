"""SmartScorer - 1-Pass AI 新闻评分核心协调器"""

import asyncio
import logging
from typing import List, Dict
from datetime import datetime
from collections import defaultdict

from src.models import NewsItem, AIConfig
from src.exceptions import ContentFilterError
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
        self.result_processor = ResultProcessor(config)
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

    async def _process_single_batch(
        self,
        batch: List[NewsItem],
        batch_id: str
    ) -> List[NewsItem]:
        """处理单个批次（用于并行）

        Args:
            batch: 新闻批次
            batch_id: 批次标识（用于日志）

        Returns:
            评分后的新闻批次，失败时返回带默认分数的批次
        """
        try:
            logger.info(f"处理批次 {batch_id}: {len(batch)} 条新闻")
            prompt = self.prompt_engine.build_1pass_prompt(batch)

            # 使用支持fallback的新API
            response = await self.batch_provider.call_batch_api_with_fallback(
                prompt=prompt,
                items=batch,
                prompt_template=None,  # 会从prompt自动提取
                max_tokens=None,  # 使用配置默认值
                temperature=None
            )

            scored_batch = self.result_processor.parse_1pass_response(batch, response)
            logger.info(f"批次 {batch_id} 处理完成: {len(scored_batch)} 条")
            return scored_batch

        except ContentFilterError as e:
            logger.error(f"批次 {batch_id} 内容过滤且Gemini fallback失败: {e}")
            # 为整个批次赋予默认低分
            for item in batch:
                item.ai_score = self.config.default_score_on_error
                item.ai_category = "社会政治"
                item.ai_summary = f"内容过滤fallback失败: {str(e)[:self.config.max_error_message_length]}"
            return batch

        except Exception as e:
            logger.error(f"批次 {batch_id} 处理失败: {e}")
            # 为整个批次赋予默认低分
            for item in batch:
                item.ai_score = self.config.default_score_on_error
                item.ai_category = "社会政治"
                item.ai_summary = f"处理失败: {str(e)[:self.config.max_error_message_length]}"
            return batch

    async def _process_batches(self, batches: List[List[NewsItem]]) -> List[NewsItem]:
        """并行批量处理

        使用 asyncio.gather() 实现真正的并行处理，
        使用信号量控制并发数避免API过载。

        Args:
            batches: 新闻批次列表

        Returns:
            所有批次的评分结果
        """
        if not batches:
            return []

        total_batches = len(batches)

        # 限制并发数，避免API过载（使用配置的 max_concurrent，最大5）
        max_concurrent = min(getattr(self.config, 'max_concurrent', 3), 5)

        # 如果只有1个批次或禁用并行，使用串行处理
        if total_batches == 1 or max_concurrent == 1:
            logger.info(f"串行处理 {total_batches} 个批次")
            all_scored = []
            for batch_idx, batch in enumerate(batches, 1):
                batch_id = f"{batch_idx}/{total_batches}"
                scored = await self._process_single_batch(batch, batch_id)
                all_scored.extend(scored)
            logger.info(f"串行处理完成: 共 {len(all_scored)} 条")
            return all_scored

        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(batch_idx: int, batch: List[NewsItem]) -> List[NewsItem]:
            """带信号量控制的批次处理"""
            async with semaphore:
                batch_id = f"{batch_idx}/{total_batches}"
                return await self._process_single_batch(batch, batch_id)

        logger.info(f"🚀 并行处理 {total_batches} 个批次 (并发: {max_concurrent})")

        # 并行执行所有批次
        tasks = [
            process_with_semaphore(batch_idx, batch)
            for batch_idx, batch in enumerate(batches, 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并结果，处理异常
        all_scored = []
        exception_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                exception_count += 1
                logger.error(f"❌ 批次 {i+1}/{total_batches} 处理异常: {result}")
                # 使用默认分数（_process_single_batch内部已经处理）
                all_scored.extend(batches[i])
            else:
                all_scored.extend(result)

        success_count = total_batches - exception_count
        logger.info(f"✅ 并行处理完成: 成功 {success_count}/{total_batches} 批次, 失败 {exception_count} 批次, 共 {len(all_scored)} 条")

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

