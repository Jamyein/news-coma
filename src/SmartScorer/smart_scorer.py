"""
SmartScorer - 1-Pass AI 新闻评分核心协调器

职责:
1. 协调各组件完成1-pass评分流程
2. 智能分批处理
3. 智能筛选和排序

简化后的工作流程:
RSS新闻 → 智能分批 → 批量评分(1次API) → 智能筛选 → 输出

代码目标: 300行以内
"""

import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from src.models import NewsItem
from .batch_provider import BatchProvider
from .prompt_engine import PromptEngine
from .result_processor import ResultProcessor

logger = logging.getLogger(__name__)


class SmartScorer:
    """
    智能评分器 - 1-pass完成分类+评分+筛选
    
    重构目标:
    - 代码量: ~300行 (原1862行)
    - API调用: 1次/批 (原2次/批)
    - 配置项: 8项核心配置
    """
    
    def __init__(self, config: 'OnePassAIConfig'):
        """
        初始化智能评分器
        
        Args:
            config: 1-pass AI配置对象
        """
        self.config = config
        
        # 初始化核心组件
        self.batch_provider = BatchProvider(config)
        self.prompt_engine = PromptEngine(config)
        self.result_processor = ResultProcessor()
        
        # 统计信息
        self._stats = {
            'total_processed': 0,
            'total_api_calls': 0,
            'avg_processing_time': 0.0,
            'success_rate': 1.0
        }
        
        logger.info(f"SmartScorer初始化完成 (batch_size={config.batch_size})")
    
    async def score_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        1-pass评分入口
        
        核心流程:
        1. 智能分批 - 根据新闻特征自动分组
        2. 批量评分 - 1次API调用完成分类+评分
        3. 智能筛选 - 分数+多样性双重筛选
        
        Args:
            items: 待评分的新闻列表
            
        Returns:
            List[NewsItem]: 评分后的新闻列表
        """
        if not items:
            return []
        
        start_time = datetime.now()
        logger.info(f"SmartScorer开始处理 {len(items)} 条新闻")
        
        # 1. 智能分批
        batches = self._create_smart_batches(items)
        
        # 2. 批量评分 (1-pass)
        scored_items = await self._process_batches(batches)
        
        # 3. 智能筛选
        final_items = self._smart_selection(scored_items)
        
        # 更新统计
        duration = (datetime.now() - start_time).total_seconds()
        self._update_stats(len(items), len(final_items), duration)
        
        logger.info(f"SmartScorer完成: {len(items)} → {len(final_items)} 条 ({duration:.1f}s)")
        return final_items
    
    def _create_smart_batches(self, items: List[NewsItem]) -> List[List[NewsItem]]:
        """
        基于新闻特征智能分批
        
        简单分批策略（可扩展为智能分批）
        """
        batches = []
        for i in range(0, len(items), self.config.batch_size):
            batches.append(items[i:i+self.config.batch_size])
        return batches
    
    async def _process_batches(self, batches: List[List[NewsItem]]) -> List[NewsItem]:
        """批量处理 (1-pass: 分类+评分+总结 一次完成)"""
        all_scored = []
        
        for batch in batches:
            # 1-pass: 单次API调用完成所有任务
            prompt = self.prompt_engine.build_1pass_prompt(batch)
            response = await self.batch_provider.call_batch_api(prompt)
            
            # 解析结果
            scored_batch = self.result_processor.parse_1pass_response(batch, response)
            all_scored.extend(scored_batch)
        
        return all_scored
    
    def _smart_selection(self, items: List[NewsItem]) -> List[NewsItem]:
        """智能筛选：分数 + 多样性"""
        # 按分数排序
        sorted_items = sorted(items, key=lambda x: x.ai_score or 0, reverse=True)
        
        # 确保分类多样性
        return self._ensure_diversity(sorted_items)
    
    def _ensure_diversity(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        确保分类多样性
        
        策略：
        1. 按分数排序
        2. 优先选择不同分类的新闻
        3. 确保每个分类都有代表
        """
        if not items:
            return []
        
        max_items = self.config.max_output_items
        diversity_weight = self.config.diversity_weight
        
        # 按分类分组
        by_category = defaultdict(list)
        for item in items:
            category = getattr(item, 'ai_category', '未分类')
            by_category[category].append(item)
        
        # 简单策略：先取每个分类的前几名，然后补充高分新闻
        selected = []
        
        # 每个分类至少取1条（如果存在）
        for category, cat_items in by_category.items():
            if cat_items and len(selected) < max_items:
                selected.append(cat_items[0])
        
        # 补充剩余的高分新闻
        for item in items:
            if item not in selected and len(selected) < max_items:
                selected.append(item)
        
        # 按分数重新排序
        selected.sort(key=lambda x: x.ai_score or 0, reverse=True)
        
        return selected
    
    def _update_stats(self, input_count: int, output_count: int, duration: float):
        """更新统计信息"""
        self._stats['total_processed'] += input_count
        
        # 更新API调用次数
        provider_stats = self.batch_provider.get_stats()
        self._stats['total_api_calls'] = provider_stats.get('api_call_count', 0)
        
        # 更新平均处理时间
        if self._stats['total_processed'] > 0:
            current_avg = self._stats['avg_processing_time']
            new_avg = (current_avg * (self._stats['total_processed'] - input_count) + duration) / self._stats['total_processed']
            self._stats['avg_processing_time'] = new_avg
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self._stats.copy()

