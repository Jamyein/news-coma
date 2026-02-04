"""
AdaptiveBatchProcessor - 智能动态批处理器

基于相似度分组和成功率历史的动态批处理优化
"""
import logging
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict
from datetime import datetime
from dataclasses import dataclass, field
import re

from src.models import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class BatchContext:
    """批处理上下文信息"""
    pass_number: int = 1  # Pass 1 或 Pass 2
    category: str = ""  # 新闻分类
    priority_mode: str = "balanced"  # priority | balanced | similarity
    total_items: int = 0  # 总项目数
    time_window_hours: Optional[int] = None  # 时间窗口


@dataclass
class BatchHistoryEntry:
    """批处理历史记录"""
    batch_size: int
    success: bool
    items_processed: int
    timestamp: datetime
    error_type: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


class AdaptiveBatchProcessor:
    """
    自适应批处理器
    
    核心特性：
    1. 动态批大小调整：基于历史成功率自适应调整批大小（10-25）
    2. 相似度分组：将相似新闻合并处理以减少API调用
    3. 优先级感知：高优先级项目优先处理
    4. 上下文感知：考虑处理上下文（Pass阶段、分类等）
    
    目标：在保持质量的同时最小化API调用次数
    """
    
    def __init__(
        self,
        min_size: int = 8,
        max_size: int = 25,
        target_success_rate: float = 0.85,
        history_window: int = 50
    ):
        """
        初始化自适应批处理器
        
        Args:
            min_size: 最小批大小
            max_size: 最大批大小
            target_success_rate: 目标成功率（用于动态调整）
            history_window: 历史记录窗口大小
        """
        self.min_size = max(5, min_size)  # 至少5
        self.max_size = min(50, max_size)  # 最多50
        self.target_success_rate = max(0.5, min(0.95, target_success_rate))
        self.history_window = history_window
        
        # 当前批大小（初始为中间值）
        self.current_batch_size = (self.min_size + self.max_size) // 2
        
        # 批处理历史记录
        self._batch_history: List[BatchHistoryEntry] = []
        
        # 统计信息
        self._stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'failed_batches': 0,
            'total_items_processed': 0,
            'avg_batch_size': 0.0,
            'similarity_groups_used': 0
        }
        
        logger.info(
            f"AdaptiveBatchProcessor 初始化: "
            f"min={self.min_size}, max={self.max_size}, "
            f"target_success={self.target_success_rate:.2f}"
        )
    
    def create_optimized_batches(
        self,
        items: List[NewsItem],
        context: Optional[BatchContext] = None
    ) -> List[List[NewsItem]]:
        """
        创建优化的批次列表
        
        Args:
            items: 新闻项列表
            context: 批处理上下文
            
        Returns:
            List[List[NewsItem]]: 优化后的批次列表
        """
        if not items:
            logger.debug("空输入，返回空批次列表")
            return []
        
        if context is None:
            context = BatchContext(total_items=len(items))
        else:
            context.total_items = len(items)
        
        logger.info(
            f"🎯 创建优化批次: {len(items)} 条新闻 "
            f"(Pass {context.pass_number}, 当前批大小: {self.current_batch_size})"
        )
        
        # 1. 优先级排序
        sorted_items = self._priority_sort(items, context)
        
        # 2. 智能分组
        batches = self._intelligent_grouping(
            sorted_items,
            target_size=self.current_batch_size,
            context=context
        )
        
        # 3. 更新统计
        self._stats['total_batches'] += len(batches)
        self._stats['total_items_processed'] += len(items)
        if len(batches) > 0:
            self._stats['avg_batch_size'] = (
                self._stats['avg_batch_size'] * 
                (self._stats['total_batches'] - len(batches)) +
                sum(len(batch) for batch in batches) / len(batches)
            ) / self._stats['total_batches']
        
        logger.info(
            f"✅ 创建批次完成: {len(batches)} 个批次 "
            f"(平均 {len(items)/len(batches):.1f} 条/批次)"
        )
        
        return batches
    
    def _priority_sort(
        self,
        items: List[NewsItem],
        context: BatchContext
    ) -> List[NewsItem]:
        """
        基于优先级对新闻项排序
        
        Args:
            items: 新闻项列表
            context: 批处理上下文
            
        Returns:
            List[NewsItem]: 排序后的新闻项列表
        """
        if context.priority_mode == "priority":
            # 高优先级项目优先：基于评分和紧急性
            def priority_score(item: NewsItem) -> float:
                score = 0.0
                
                # 已有评分的项目优先
                if item.ai_score is not None:
                    score += item.ai_score
                
                # 紧急关键词提升优先级
                urgent_keywords = ['breaking', '紧急', '突发', 'breaking news']
                if any(kw in item.title.lower() for kw in urgent_keywords):
                    score += 5.0
                
                # 知名媒体源提升优先级
                high_priority_sources = ['reuters', 'bloomberg', 'wsj', 'ft', '新华', '人民网']
                if any(src in item.source.lower() for src in high_priority_sources):
                    score += 2.0
                
                return score
            
            sorted_items = sorted(items, key=priority_score, reverse=True)
            logger.debug("🔥 使用优先级排序")
        
        elif context.priority_mode == "similarity":
            # 相似度分组模式：先按分类分组
            category_groups = defaultdict(list)
            for item in items:
                cat = getattr(item, 'pre_category', item.category)
                category_groups[cat].append(item)
            
            # 在每个分类内按时间排序
            sorted_items = []
            for cat in sorted(category_groups.keys()):
                cat_items = sorted(
                    category_groups[cat],
                    key=lambda x: x.published_at,
                    reverse=True
                )
                sorted_items.extend(cat_items)
            
            logger.debug(f"🔗 使用相似度排序: {len(category_groups)} 个分类")
        
        else:  # balanced
            # 平衡模式：按时间排序，保持新闻的时间顺序
            sorted_items = sorted(items, key=lambda x: x.published_at, reverse=True)
            logger.debug("⚖️ 使用平衡排序（时间顺序）")
        
        return sorted_items
    
    def _intelligent_grouping(
        self,
        items: List[NewsItem],
        target_size: int,
        context: BatchContext
    ) -> List[List[NewsItem]]:
        """
        智能分组：结合相似度和目标批大小
        
        Args:
            items: 新闻项列表
            target_size: 目标批大小
            context: 批处理上下文
            
        Returns:
            List[List[NewsItem]]: 分组后的批次列表
        """
        batches: List[List[NewsItem]] = []
        
        if not items:
            return batches
        
        # 如果项目数量小于目标批大小，直接返回单批次
        if len(items) <= target_size:
            batches.append(items)
            return batches
        
        # 策略1: 相似度分组（优先）
        if context.priority_mode == "similarity":
            batches = self._similarity_based_grouping(
                items, target_size, context
            )
            self._stats['similarity_groups_used'] += len(batches)
        else:
            # 策略2: 混合分组（相似度 + 大小控制）
            batches = self._hybrid_grouping(items, target_size, context)
        
        # 确保所有项目都被分组
        if len(sum(batches, [])) != len(items):
            logger.warning(
                f"分组异常: 输入{len(items)}条, 输出{len(sum(batches, []))}条"
            )
        
        return batches
    
    def _similarity_based_grouping(
        self,
        items: List[NewsItem],
        target_size: int,
        context: BatchContext
    ) -> List[List[NewsItem]]:
        """
        基于相似度的分组
        
        将相似新闻合并到同一批次中
        
        Args:
            items: 新闻项列表
            target_size: 目标批大小
            context: 批处理上下文
            
        Returns:
            List[List[NewsItem]]: 分组后的批次列表
        """
        batches: List[List[NewsItem]] = []
        remaining_items = items.copy()
        
        similarity_threshold = 0.7  # 相似度阈值
        
        while remaining_items:
            # 取第一个未分配的项目
            current_item = remaining_items[0]
            current_batch = [current_item]
            remaining_items = remaining_items[1:]
            
            # 寻找相似项目
            i = 0
            while i < len(remaining_items) and len(current_batch) < target_size:
                candidate_item = remaining_items[i]
                similarity = self._calculate_similarity(current_item, candidate_item)
                
                if similarity >= similarity_threshold:
                    current_batch.append(candidate_item)
                    remaining_items.pop(i)
                    # 不增加i，因为项目被移除了
                else:
                    i += 1
            
            # 如果批次太小，添加非相似项目以接近目标大小
            while remaining_items and len(current_batch) < max(self.min_size, target_size // 2):
                current_batch.append(remaining_items.pop(0))
            
            batches.append(current_batch)
        
        logger.debug(
            f"🔗 相似度分组: {len(batches)} 个批次 "
            f"(阈值: {similarity_threshold})"
        )
        
        return batches
    
    def _hybrid_grouping(
        self,
        items: List[NewsItem],
        target_size: int,
        context: BatchContext
    ) -> List[List[NewsItem]]:
        """
        混合分组策略
        
        结合相似度分组和固定大小分组的优点
        
        Args:
            items: 新闻项列表
            target_size: 目标批大小
            context: 批处理上下文
            
        Returns:
            List[List[NewsItem]]: 分组后的批次列表
        """
        batches: List[List[NewsItem]] = []
        
        # 首先按分类分组
        category_groups = defaultdict(list)
        for item in items:
            cat = getattr(item, 'pre_category', item.category)
            category_groups[cat].append(item)
        
        # 对每个分类进行智能分批
        for category, cat_items in category_groups.items():
            if len(cat_items) <= target_size:
                # 小分类直接作为一个批次
                batches.append(cat_items)
            else:
                # 大分类分割为多个批次
                # 策略：先尝试相似度分组，再按大小分割
                similar_groups = self._find_similarity_clusters(cat_items)
                
                for group in similar_groups:
                    if len(group) <= target_size:
                        batches.append(group)
                    else:
                        # 分割大组
                        for i in range(0, len(group), target_size):
                            batch = group[i:i + target_size]
                            if batch:
                                batches.append(batch)
        
        logger.debug(
            f"🎯 混合分组: {len(batches)} 个批次 "
            f"(分类数: {len(category_groups)})"
        )
        
        return batches
    
    def _find_similarity_clusters(
        self,
        items: List[NewsItem]
    ) -> List[List[NewsItem]]:
        """
        发现相似度聚类
        
        使用贪心算法将相似项目聚类在一起
        
        Args:
            items: 新闻项列表
            
        Returns:
            List[List[NewsItem]]: 聚类结果
        """
        if not items:
            return []
        
        clusters = []
        unassigned = items.copy()
        similarity_threshold = 0.6  # 聚类相似度阈值
        
        while unassigned:
            # 创建新聚类
            cluster = [unassigned.pop(0)]
            
            # 尝试将相似项目加入聚类
            changed = True
            while changed and unassigned:
                changed = False
                i = 0
                while i < len(unassigned):
                    # 检查是否与聚类中的任何项目相似
                    is_similar = any(
                        self._calculate_similarity(cluster_item, unassigned[i]) >= similarity_threshold
                        for cluster_item in cluster
                    )
                    
                    if is_similar:
                        cluster.append(unassigned.pop(i))
                        changed = True
                    else:
                        i += 1
            
            clusters.append(cluster)
        
        return clusters
    
    def _calculate_similarity(
        self,
        item1: NewsItem,
        item2: NewsItem
    ) -> float:
        """
        计算两个新闻项的相似度
        
        基于多个维度的相似度计算：
        1. 标题相似度（关键词重叠）
        2. 来源相似度
        3. 分类相似度
        4. 时间相似度
        
        Args:
            item1: 新闻项1
            item2: 新闻项2
            
        Returns:
            float: 相似度分数（0-1）
        """
        similarity_score = 0.0
        
        # 1. 标题相似度（最重要）
        title_sim = self._calculate_title_similarity(item1.title, item2.title)
        similarity_score += title_sim * 0.6
        
        # 2. 来源相似度
        source_sim = self._calculate_source_similarity(item1.source, item2.source)
        similarity_score += source_sim * 0.2
        
        # 3. 分类相似度
        category_sim = self._calculate_category_similarity(item1, item2)
        similarity_score += category_sim * 0.15
        
        # 4. 时间相似度（同一新闻事件通常在同一时间窗口内）
        time_sim = self._calculate_time_similarity(item1.published_at, item2.published_at)
        similarity_score += time_sim * 0.05
        
        return min(1.0, similarity_score)
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算标题相似度（基于关键词重叠）
        
        Args:
            title1: 标题1
            title2: 标题2
            
        Returns:
            float: 相似度（0-1）
        """
        # 移除标点符号并小写
        title1_clean = re.sub(r'[^\w\s]', '', title1.lower())
        title2_clean = re.sub(r'[^\w\s]', '', title2.lower())
        
        # 分词
        words1 = set(title1_clean.split())
        words2 = set(title2_clean.split())
        
        if not words1 or not words2:
            return 0.0
        
        # Jaccard相似度
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        jaccard = intersection / union if union > 0 else 0.0
        
        # 对完全相同或高度相似的标题给予额外加分
        if title1_clean == title2_clean:
            return 1.0
        
        # 检查是否包含（一个标题包含另一个）
        if title1_clean in title2_clean or title2_clean in title1_clean:
            return 0.9
        
        return jaccard
    
    def _calculate_source_similarity(self, source1: str, source2: str) -> float:
        """
        计算来源相似度
        
        Args:
            source1: 来源1
            source2: 来源2
            
        Returns:
            float: 相似度（0-1）
        """
        source1_lower = source1.lower()
        source2_lower = source2.lower()
        
        if source1_lower == source2_lower:
            return 1.0
        
        # 检查是否包含相同域名
        if source1_lower in source2_lower or source2_lower in source1_lower:
            return 0.8
        
        return 0.0
    
    def _calculate_category_similarity(self, item1: NewsItem, item2: NewsItem) -> float:
        """
        计算分类相似度
        
        Args:
            item1: 新闻项1
            item2: 新闻项2
            
        Returns:
            float: 相似度（0-1）
        """
        # 使用预分类（如果有）或原始分类
        cat1 = getattr(item1, 'pre_category', item1.category)
        cat2 = getattr(item2, 'pre_category', item2.category)
        
        if cat1 == cat2:
            return 1.0
        
        # 检查是否相关分类
        related_pairs = [
            ('财经', '科技'),  # 金融科技
            ('社会政治', '财经'),  # 政策影响金融
            ('科技', '社会政治'),  # 科技政策
        ]
        
        for pair in related_pairs:
            if (cat1 in pair[0] and cat2 in pair[1]) or (cat2 in pair[0] and cat1 in pair[1]):
                return 0.5
        
        return 0.0
    
    def _calculate_time_similarity(
        self,
        time1: datetime,
        time2: datetime
    ) -> float:
        """
        计算时间相似度
        
        Args:
            time1: 时间1
            time2: 时间2
            
        Returns:
            float: 相似度（0-1）
        """
        # 计算时间差（小时）
        time_diff = abs((time1 - time2).total_seconds()) / 3600
        
        # 24小时内的新闻可能是同一事件
        if time_diff < 24:
            return 1.0 - (time_diff / 24)
        elif time_diff < 72:
            return 0.5 * (1 - (time_diff - 24) / 48)
        else:
            return 0.0
    
    def record_batch_result(
        self,
        batch_size: int,
        success: bool,
        items_processed: int,
        error_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        记录批处理结果
        
        Args:
            batch_size: 批大小
            success: 是否成功
            items_processed: 处理的项目数
            error_type: 错误类型（如果有）
            context: 上下文信息
        """
        entry = BatchHistoryEntry(
            batch_size=batch_size,
            success=success,
            items_processed=items_processed,
            timestamp=datetime.now(),
            error_type=error_type,
            context=context or {}
        )
        
        self._batch_history.append(entry)
        
        # 更新统计
        self._stats['total_batches'] += 1
        if success:
            self._stats['successful_batches'] += 1
        else:
            self._stats['failed_batches'] += 1
        
        # 保持历史窗口大小
        if len(self._batch_history) > self.history_window:
            self._batch_history.pop(0)
        
        # 触发动态调整
        self._dynamic_batch_size_adjustment()
    
    def _dynamic_batch_size_adjustment(self):
        """
        基于历史记录动态调整批大小
        
        调整策略：
        1. 计算最近的成功率
        2. 如果成功率高于目标，增加批大小
        3. 如果成功率低于目标，减少批大小
        4. 调整幅度基于偏差程度
        """
        if len(self._batch_history) < 10:
            # 历史记录不足，不调整
            return
        
        # 计算最近的成功率
        recent_history = self._batch_history[-20:]  # 最近20次
        success_count = sum(1 for entry in recent_history if entry.success)
        current_success_rate = success_count / len(recent_history)
        
        old_batch_size = self.current_batch_size
        
        if current_success_rate > self.target_success_rate:
            # 成功率高，可以增加批大小
            adjustment_factor = min(
                0.2,
                (current_success_rate - self.target_success_rate) * 2
            )
            new_batch_size = int(
                self.current_batch_size * (1 + adjustment_factor)
            )
            self.current_batch_size = min(new_batch_size, self.max_size)
        
        elif current_success_rate < self.target_success_rate:
            # 成功率低，减少批大小
            adjustment_factor = min(
            0.3,
                (self.target_success_rate - current_success_rate) * 3
            )
            new_batch_size = int(
                self.current_batch_size * (1 - adjustment_factor)
            )
            self.current_batch_size = max(new_batch_size, self.min_size)
        
        if self.current_batch_size != old_batch_size:
            logger.info(
                f"📊 批大小动态调整: {old_batch_size} -> {self.current_batch_size} "
                f"(成功率: {current_success_rate:.2%}, 目标: {self.target_success_rate:.2%})"
            )
    
    def get_current_batch_size(self) -> int:
        """
        获取当前批大小
        
        Returns:
            int: 当前批大小
        """
        return self.current_batch_size
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息字典
        """
        # 计算当前成功率
        if self._batch_history:
            recent_history = self._batch_history[-20:]
            success_count = sum(1 for entry in recent_history if entry.success)
            current_success_rate = success_count / len(recent_history)
        else:
            current_success_rate = 0.0
        
        return {
            'current_batch_size': self.current_batch_size,
            'min_size': self.min_size,
            'max_size': self.max_size,
            'target_success_rate': self.target_success_rate,
            'current_success_rate': current_success_rate,
            'total_batches': self._stats['total_batches'],
            'successful_batches': self._stats['successful_batches'],
            'failed_batches': self._stats['failed_batches'],
            'total_items_processed': self._stats['total_items_processed'],
            'avg_batch_size': self._stats['avg_batch_size'],
            'similarity_groups_used': self._stats['similarity_groups_used'],
            'history_size': len(self._batch_history)
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self._batch_history.clear()
        self._stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'failed_batches': 0,
            'total_items_processed': 0,
            'avg_batch_size': 0.0,
            'similarity_groups_used': 0
        }
        self.current_batch_size = (self.min_size + self.max_size) // 2
        logger.info("🔄 统计信息已重置")
