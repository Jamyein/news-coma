"""
分批处理器 - 处理大批量新闻的分批API调用

解决单次API调用无法处理大量新闻的问题
"""

import logging
from typing import List, Dict, Any, Callable, TypeVar
import asyncio

logger = logging.getLogger(__name__)

T = TypeVar('T')


class BatchProcessor:
    """
    分批处理器
    
    将大批量数据分批处理，并合并结果
    
    特性：
    1. 自动分批：超过阈值自动分批次处理
    2. 索引映射：自动调整批次内索引到全局索引
    3. 失败重试：单批失败自动重试
    4. 进度日志：记录处理进度和统计信息
    """
    
    # 默认配置
    DEFAULT_BATCH_SIZE = 100  # 每批最大数量
    DEFAULT_MAX_RETRIES = 2   # 单批最大重试次数
    DEFAULT_RETRY_DELAY = 1.0  # 重试间隔（秒）
    
    def __init__(
        self,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        index_key: str = 'news_index'  # 结果中索引字段名
    ):
        """
        初始化分批处理器
        
        Args:
            batch_size: 每批最大处理数量
            max_retries: 单批失败重试次数
            retry_delay: 重试间隔（秒）
            index_key: 结果字典中索引字段的名称
        """
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.index_key = index_key
        
        # 统计信息
        self.stats = {
            'total_items': 0,
            'total_batches': 0,
            'successful_batches': 0,
            'failed_batches': 0,
            'retried_batches': 0,
            'total_results': 0,
            'missing_results': 0
        }
    
    async def process(
        self,
        items: List[T],
        process_func: Callable[[List[T]], List[Dict]],
        description: str = "处理"
    ) -> List[Dict]:
        """
        分批处理数据
        
        Args:
            items: 待处理的数据列表
            process_func: 处理函数，接收一批数据，返回结果列表
            description: 处理描述（用于日志）
            
        Returns:
            List[Dict]: 合并后的所有结果
            
        Raises:
            RuntimeError: 当批次处理失败且重试耗尽时
        """
        if not items:
            return []
        
        self.stats['total_items'] = len(items)
        
        # 如果数量在阈值内，直接处理
        if len(items) <= self.batch_size:
            logger.info(f"{description}: 数量{len(items)}在单批阈值内，直接处理")
            results = await self._process_single_batch(items, process_func, 1, 1)
            return results
        
        # 超过阈值，分批处理
        logger.info(f"🔄 {description}: 数量({len(items)})超过单批阈值({self.batch_size})，启动分批处理...")
        
        # 分批
        batches = [items[i:i+self.batch_size] for i in range(0, len(items), self.batch_size)]
        self.stats['total_batches'] = len(batches)
        
        all_results = []
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"  {description} - 第{batch_idx}/{len(batches)}批 ({len(batch)}条)...")
            
            # 处理单批（带重试）
            try:
                batch_results = await self._process_single_batch(
                    batch, process_func, batch_idx, len(batches)
                )
                self.stats['successful_batches'] += 1
            except Exception as e:
                logger.error(f"  ❌ 第{batch_idx}批处理失败（已重试{self.max_retries}次）: {e}")
                self.stats['failed_batches'] += 1
                # 失败时填充默认值
                batch_results = self._generate_default_results(batch, batch_idx)
            
            # 索引调整：将批次内索引映射到全局索引
            offset = (batch_idx - 1) * self.batch_size
            for result in batch_results:
                if self.index_key in result:
                    result[self.index_key] = result[self.index_key] + offset
            
            all_results.extend(batch_results)
            
            # 检查批次完整性
            expected_count = len(batch)
            actual_count = len(batch_results)
            if actual_count < expected_count:
                logger.warning(f"  ⚠️ 第{batch_idx}批结果不完整: {actual_count}/{expected_count}")
                self.stats['missing_results'] += (expected_count - actual_count)
        
        # 记录统计信息
        self.stats['total_results'] = len(all_results)
        success_rate = (self.stats['successful_batches'] / self.stats['total_batches'] * 100) if self.stats['total_batches'] > 0 else 0
        
        logger.info(f"✅ {description}完成统计:")
        logger.info(f"   - 总新闻数: {self.stats['total_items']}")
        logger.info(f"   - 分批数: {self.stats['total_batches']}")
        logger.info(f"   - 成功批次: {self.stats['successful_batches']} ({success_rate:.1f}%)")
        logger.info(f"   - 失败批次: {self.stats['failed_batches']}")
        logger.info(f"   - 重试次数: {self.stats['retried_batches']}")
        logger.info(f"   - 总结果数: {self.stats['total_results']}/{self.stats['total_items']}")
        
        return all_results
    
    async def _process_single_batch(
        self,
        batch: List[T],
        process_func: Callable[[List[T]], List[Dict]],
        batch_idx: int,
        total_batches: int
    ) -> List[Dict]:
        """
        处理单批次（带重试机制）
        
        Args:
            batch: 批次数据
            process_func: 处理函数
            batch_idx: 当前批次索引
            total_batches: 总批次数
            
        Returns:
            List[Dict]: 批次处理结果
            
        Raises:
            Exception: 重试耗尽后抛出最后一次异常
        """
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"    第{batch_idx}批第{attempt}次重试...")
                    self.stats['retried_batches'] += 1
                    await asyncio.sleep(self.retry_delay * attempt)  # 递增延迟
                
                # 执行处理
                results = await process_func(batch)
                
                # 验证结果
                if not isinstance(results, list):
                    raise ValueError(f"处理函数返回类型错误: {type(results)}, 期望list")
                
                return results
                
            except Exception as e:
                last_error = e
                logger.warning(f"    第{batch_idx}批处理失败(尝试{attempt+1}/{self.max_retries+1}): {e}")
                continue
        
        # 所有重试失败
        logger.error(f"    ❌ 第{batch_idx}批处理失败，已重试{self.max_retries}次")
        raise last_error
    
    def _generate_default_results(self, batch: List[T], batch_idx: int) -> List[Dict]:
        """
        生成默认结果（当批次处理完全失败时使用）
        
        Args:
            batch: 批次数据
            batch_idx: 批次索引
            
        Returns:
            List[Dict]: 默认结果列表
        """
        offset = (batch_idx - 1) * self.batch_size
        defaults = []
        
        for i, item in enumerate(batch, 1):
            defaults.append({
                self.index_key: i + offset,
                'category': '社会政治',
                'category_confidence': 0.5,
                'total': 5.0,
                '_default': True,  # 标记为默认值
                '_error': 'batch_processing_failed'
            })
        
        return defaults
    
    def get_stats(self) -> Dict[str, Any]:
        """获取处理统计信息"""
        return self.stats.copy()
    
    def reset_stats(self):
        """重置统计信息"""
        self.stats = {
            'total_items': 0,
            'total_batches': 0,
            'successful_batches': 0,
            'failed_batches': 0,
            'retried_batches': 0,
            'total_results': 0,
            'missing_results': 0
        }
