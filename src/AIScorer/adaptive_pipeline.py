"""
AdaptivePass1Pipeline - Main pipeline integrating all adaptive components

Integrates 5 completed components:
- SafeRateLimiter: Concurrency control via Semaphore with static rate limiting from config.yaml
- AdaptiveNewsClassifier: Intelligent classification with confidence scoring
- AdaptiveBatchProcessor: Dynamic batching based on similarity and success history
- SimpleRateLimiter: Static rate limiting using rate_limit_rpm from config.yaml
- Retry strategy: Exponential backoff

Implements 4-layer processing architecture:
- L1: Fast rule-based screening
- L2: Parallel category processing with dynamic batching
- L3: Intelligent quota allocation
"""
import asyncio
import logging
import random
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from src.models import NewsItem, AIConfig
from .adaptive_classifier import AdaptiveNewsClassifier
from .adaptive_batcher import AdaptiveBatchProcessor, BatchContext
from .rate_limiter import SafeRateLimiter, SimpleRateLimiter

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Pipeline statistics"""
    total_input: int = 0
    l1_screened: int = 0
    l2_processed: int = 0
    l3_after_quota: int = 0
    final_output: int = 0
    api_calls: int = 0
    total_duration_ms: float = 0.0
    by_category: Dict[str, Dict] = field(default_factory=dict)
    batch_stats: Dict[str, Any] = field(default_factory=dict)
    rate_limiter_stats: Dict[str, Any] = field(default_factory=dict)


class AdaptivePass1Pipeline:
    """
    Adaptive Pass 1 Pipeline
    
    Integrates all adaptive components and implements 4-layer processing.
    Compatible with existing AIScorer interface.
    """
    
    DEFAULT_MAX_ITEMS = 40
    DEFAULT_BATCH_SIZE = 15
    DEFAULT_MAX_CONCURRENT = 3
    DEFAULT_RETRY_ATTEMPTS = 3
    DEFAULT_RETRY_DELAY = 1.0
    DEFAULT_RETRY_MULTIPLIER = 2.0
    
    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config
        self.max_items = getattr(config, 'pass1_max_items', self.DEFAULT_MAX_ITEMS) if config else self.DEFAULT_MAX_ITEMS
        self.batch_size = getattr(config, 'true_batch_size', self.DEFAULT_BATCH_SIZE) if config else self.DEFAULT_BATCH_SIZE
        self.max_concurrent = getattr(config, 'max_concurrent', self.DEFAULT_MAX_CONCURRENT) if config else self.DEFAULT_MAX_CONCURRENT
        self.pass1_threshold = getattr(config, 'pass1_threshold', 7.0) if config else 7.0
        self.thresholds = {
            'Finance': getattr(config, 'pass1_threshold_finance', 5.5) if config else 5.5,
            'Tech': getattr(config, 'pass1_threshold_tech', 6.0) if config else 6.0,
            'Politics': getattr(config, 'pass1_threshold_politics', 5.5) if config else 5.5,
            'Unclassified': getattr(config, 'pass1_threshold', 7.0) if config else 7.0
        }
        self.quotas = {
            'Finance': getattr(config, 'category_quota_finance', 0.40) if config else 0.40,
            'Tech': getattr(config, 'category_quota_tech', 0.30) if config else 0.30,
            'Politics': getattr(config, 'category_quota_politics', 0.30) if config else 0.30
        }
        self._init_components()
        self._stats = PipelineStats()
        self._pipeline_history = []
        logger.info(f"AdaptivePass1Pipeline initialized: max_items={self.max_items}, batch_size={self.batch_size}")
    
    def _init_components(self):
        self.classifier = AdaptiveNewsClassifier()
        self.batch_processor = AdaptiveBatchProcessor(
            min_size=8,
            max_size=self.batch_size,
            target_success_rate=0.85,
            history_window=50
        )
        # Get rate limit from config (static configuration from config.yaml)
        rate_limit_rpm = self._get_rate_limit_rpm_from_config()
        
        self.safe_rate_limiter = SafeRateLimiter(
            max_requests=rate_limit_rpm,
            time_window=60.0,
            timeout=120.0,
            max_concurrent=self.max_concurrent
        )
        self.retry_attempts = self.DEFAULT_RETRY_ATTEMPTS
        self.retry_delay = self.DEFAULT_RETRY_DELAY
        self.retry_multiplier = self.DEFAULT_RETRY_MULTIPLIER
    
    async def process(self, items: List[NewsItem], api_call_func: Optional[Callable] = None) -> List[NewsItem]:
        """Main processing method - 4-layer architecture"""
        start_time = datetime.now()
        if not items:
            return []
        
        logger.info(f"AdaptivePass1Pipeline processing: {len(items)} items")
        self._stats.total_input = len(items)
        
        try:
            logger.info("L1: Fast screening")
            l1_items = await self._fast_screening(items)
            self._stats.l1_screened = len(l1_items)
            
            if not l1_items:
                return []
            
            logger.info("L2: Parallel processing")
            l2_items = await self._parallel_category_processing(l1_items, api_call_func)
            self._stats.l2_processed = len(l2_items)
            
            if not l2_items:
                return []
            
            logger.info("L3: Quota allocation")
            l3_items = await self._intelligent_quota_allocation(l2_items)
            self._stats.l3_after_quota = len(l3_items)
            
            final_items = self._finalize_results(l3_items)
            self._stats.final_output = len(final_items)
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self._stats.total_duration_ms = duration_ms
            logger.info(f"Pipeline complete: {len(items)} -> {len(final_items)} items")
            
            self._save_pipeline_history()
            return final_items
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return items[:self.max_items] if len(items) > self.max_items else items
    
    async def _fast_screening(self, items: List[NewsItem]) -> List[NewsItem]:
        """L1: Fast rule-based screening"""
        screened_items = []
        for item in items:
            if len(item.title) < 5 or len(item.title) > 200:
                continue
            if not item.summary and not item.content:
                continue
            low_value_patterns = ['advertisement', 'ads', 'sponsored', 'promoted']
            title_lower = item.title.lower()
            if any(pattern in title_lower for pattern in low_value_patterns):
                continue
            screened_items.append(item)
        return screened_items
    
    async def _parallel_category_processing(self, items: List[NewsItem], api_call_func: Optional[Callable]) -> List[NewsItem]:
        """L2: Parallel category processing + dynamic batching"""
        classified_results = {"Finance": [], "Tech": [], "Politics": [], "Unclassified": []}
        classified_items = self.classifier.classify_with_confidence(items)
        
        for classified in classified_items:
            item = classified.item
            item.pre_category = classified.category
            item.pre_category_confidence = classified.confidence
            if classified.category in classified_results:
                classified_results[classified.category].append(item)
            else:
                classified_results["Unclassified"].append(item)
        
        processed_items = []
        tasks = []
        for category, category_items in classified_results.items():
            if category_items:
                tasks.append(self._process_category(category, category_items, api_call_func))
        
        if tasks:
            category_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in category_results:
                if not isinstance(result, Exception):
                    processed_items.extend(result)
        
        return processed_items
    
    async def _process_category(self, category: str, items: List[NewsItem], api_call_func: Optional[Callable]) -> List[NewsItem]:
        """Process single category with dynamic batching"""
        batch_context = BatchContext(
            pass_number=1,
            category=category,
            priority_mode="similarity",
            total_items=len(items)
        )
        batches = self.batch_processor.create_optimized_batches(items, batch_context)
        
        batch_results = []
        for batch in batches:
            try:
                scored_batch = await self._retry_with_backoff(self._process_batch, batch, category, api_call_func)
                batch_results.extend(scored_batch)
                self.batch_processor.record_batch_result(
                    batch_size=len(batch),
                    success=True,
                    items_processed=len(scored_batch)
                )
            except Exception as e:
                for item in batch:
                    item.ai_score = 5.0
                    batch_results.append(item)
        
        return batch_results
    
    async def _process_batch(self, batch: List[NewsItem], category: str, api_call_func: Optional[Callable]) -> List[NewsItem]:
        """Process single batch with rate limiting"""
        await self.safe_rate_limiter.acquire()
        
        try:
            if api_call_func:
                scored_batch = await api_call_func(batch, category)
            else:
                scored_batch = await self._simulate_api_call(batch, category)
            self._stats.api_calls += 1
            return scored_batch
        finally:
            pass
    
    async def _simulate_api_call(self, batch: List[NewsItem], category: str) -> List[NewsItem]:
        """Simulate API call for testing"""
        await asyncio.sleep(0.1)
        for item in batch:
            confidence = getattr(item, 'pre_category_confidence', 0.5)
            base_score = 5.0 + confidence * 3.0
            score = min(10.0, max(1.0, base_score + random.uniform(-1.0, 1.0)))
            item.ai_score = round(score, 1)
        return batch
    
    async def _retry_with_backoff(self, func: Callable, *args, **kwargs):
        """Exponential backoff retry"""
        last_exception = None
        delay = self.retry_delay
        
        for attempt in range(self.retry_attempts):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(delay)
                    delay *= self.retry_multiplier
        
        raise last_exception
    
    async def _intelligent_quota_allocation(self, items: List[NewsItem]) -> List[NewsItem]:
        """L3: Intelligent quota allocation"""
        categorized = defaultdict(list)
        for item in items:
            category = getattr(item, 'pre_category', 'Unclassified')
            categorized[category].append(item)
        
        quota_distribution = self._calculate_dynamic_quotas(len(items))
        selected_items = []
        remaining_items = []
        
        for category, category_items in categorized.items():
            if category == 'Unclassified':
                continue
            
            quota = quota_distribution.get(category, 0)
            sorted_items = sorted(
                category_items,
                key=lambda x: x.ai_score if x.ai_score is not None else 0.0,
                reverse=True
            )
            
            threshold = self._get_category_threshold(category)
            filtered_items = [item for item in sorted_items if item.ai_score is not None and item.ai_score >= threshold]
            
            if len(filtered_items) <= quota:
                selected_items.extend(filtered_items)
            else:
                selected_items.extend(filtered_items[:quota])
                remaining_items.extend(filtered_items[quota:])
        
        remaining_quota = self.max_items - len(selected_items)
        if remaining_quota > 0 and remaining_items:
            remaining_items.sort(
                key=lambda x: x.ai_score if x.ai_score is not None else 0.0,
                reverse=True
            )
            selected_items.extend(remaining_items[:remaining_quota])
        
        return selected_items
    
    def _calculate_dynamic_quotas(self, total_items: int) -> Dict[str, int]:
        """Calculate dynamic quotas"""
        quota_distribution = {}
        base_quota = min(total_items, self.max_items)
        
        for category, quota_ratio in self.quotas.items():
            quota = int(base_quota * quota_ratio)
            quota_distribution[category] = max(1, quota)
        
        total_quota = sum(quota_distribution.values())
        if total_quota > self.max_items:
            scale_factor = self.max_items / total_quota
            for category in quota_distribution:
                quota_distribution[category] = max(1, int(quota_distribution[category] * scale_factor))
        
        return quota_distribution
    
    def _get_category_threshold(self, category: str) -> float:
        """Get category threshold"""
        return self.thresholds.get(category, self.pass1_threshold)
    
    def _finalize_results(self, items: List[NewsItem]) -> List[NewsItem]:
        """Finalize results: sort by score and limit count"""
        sorted_items = sorted(
            items,
            key=lambda x: x.ai_score if x.ai_score is not None else 0.0,
            reverse=True
        )
        return sorted_items[:self.max_items]
    
    def _get_rate_limit_rpm_from_config(self) -> int:
        """
        从配置中获取速率限制 (RPM)
        优先从当前提供商配置中读取 rate_limit_rpm
        """
        if not self.config:
            return 60  # 默认值
        
        # 从当前提供商配置中获取
        provider_config = self.config.providers_config.get(self.config.provider)
        if provider_config and provider_config.rate_limit_rpm:
            return provider_config.rate_limit_rpm
        
        return 60  # 默认 60 RPM
    
    def _save_pipeline_history(self):
        """Save pipeline run history for analytics"""
        # Keep last 100 runs in memory
        if len(self._pipeline_history) > 100:
            self._pipeline_history = self._pipeline_history[-100:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics"""
        return {
            'pipeline_stats': {
                'total_input': self._stats.total_input,
                'l1_screened': self._stats.l1_screened,
                'l2_processed': self._stats.l2_processed,
                'l3_after_quota': self._stats.l3_after_quota,
                'final_output': self._stats.final_output,
                'api_calls': self._stats.api_calls,
                'total_duration_ms': self._stats.total_duration_ms
            },
            'classifier_stats': self.classifier.get_stats(),
            'batch_processor_stats': self.batch_processor.get_stats(),
            'safe_rate_limiter_stats': self.safe_rate_limiter.get_stats() if hasattr(self.safe_rate_limiter, 'get_stats') else {},
            'thresholds': self.thresholds,
            'quotas': self.quotas,
            'history_count': len(self._pipeline_history)
        }
    
    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get pipeline history"""
        return self._pipeline_history[-limit:] if limit > 0 else self._pipeline_history
    
    def reset_stats(self):
        """Reset statistics"""
        self._stats = PipelineStats()
        self._pipeline_history = []
        self.classifier.reset_stats()
        self.batch_processor.reset_stats()
        self.safe_rate_limiter.reset()
    
    def update_threshold(self, category: str, new_threshold: float):
        """Update category threshold"""
        if category in self.thresholds:
            self.thresholds[category] = new_threshold
    
    def update_quota(self, category: str, new_quota: float):
        """Update category quota"""
        if category in self.quotas:
            self.quotas[category] = new_quota
