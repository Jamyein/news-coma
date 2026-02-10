"""SmartScorer - 1-Pass AI 新闻评分核心协调器"""

import asyncio
import logging
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
        
        # 重试配置
        self._max_retries = getattr(config, 'max_retries', 2)
        self._retry_delay = getattr(config, 'retry_delay', 1.0)
        
        self._stats = {
            'total_processed': 0,
            'total_api_calls': 0,
            'avg_processing_time': 0.0,
            'success_rate': 1.0
        }
        logger.info(f"SmartScorer初始化完成 (batch_size={config.batch_size}, max_retries={self._max_retries})")
    
    async def score_news(self, items: list[NewsItem]) -> list[NewsItem]:
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
    
    def _create_batches(self, items: list[NewsItem]) -> list[list[NewsItem]]:
        """将新闻分批处理"""
        return [
            items[i:i + self.config.batch_size]
            for i in range(0, len(items), self.config.batch_size)
        ]

    async def _process_single_batch(
        self,
        batch: list[NewsItem],
        batch_id: str
    ) -> list[NewsItem]:
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
            return self._apply_default_scores(batch, str(e))

    async def _process_single_batch_with_retry(
        self,
        batch: list[NewsItem],
        batch_id: str,
        max_retries: int | None = None
    ) -> list[NewsItem]:
        """
        带重试的批次处理
        
        Args:
            batch: 新闻批次
            batch_id: 批次标识
            max_retries: 最大重试次数（默认使用配置值）
        
        Returns:
            评分后的新闻列表，失败时应用默认分数
        """
        max_retries = max_retries or self._max_retries
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return await self._process_single_batch(batch, batch_id)
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = self._retry_delay * (2 ** attempt)  # 指数退避
                    logger.warning(
                        f"批次 {batch_id} 第 {attempt + 1} 次尝试失败，"
                        f"{delay:.1f}秒后重试: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"批次 {batch_id} 重试耗尽: {e}")
        
        # 所有重试失败，应用默认分数
        return self._apply_default_scores(batch, str(last_exception))

    def _apply_default_scores(
        self,
        batch: list[NewsItem],
        reason: str = "unknown"
    ) -> list[NewsItem]:
        """为批次应用默认分数"""
        default_score = getattr(self.config, 'default_score_on_error', 3.0)
        max_error_len = getattr(self.config, 'max_error_message_length', 50)
        
        for item in batch:
            item.ai_score = default_score
            item.ai_category = "社会政治"
            item.ai_category_confidence = 0.5
            item.ai_summary = f"[评分失败: {reason[:max_error_len]}]"
            item.translated_title = item.title  # 保留原标题
        
        logger.warning(f"已为批次应用默认分数 ({len(batch)} 条): {reason[:max_error_len]}")
        return batch

    async def _process_batches(self, batches: list[list[NewsItem]]) -> list[NewsItem]:
        """
        并行批量处理（带重试）
        
        使用 asyncio.gather() 实现真正的并行处理，
        使用信号量控制并发数避免API过载。
        每个批次都有独立的重试机制。

        Args:
            batches: 新闻批次列表

        Returns:
            所有批次的评分结果
        """
        if not batches:
            return []

        total_batches = len(batches)
        max_concurrent = min(getattr(self.config, 'max_concurrent', 3), 5)

        # 如果只有1个批次或禁用并行，使用串行处理
        if total_batches == 1 or max_concurrent == 1:
            logger.info(f"串行处理 {total_batches} 个批次")
            all_scored = []
            for batch_idx, batch in enumerate(batches, 1):
                batch_id = f"{batch_idx}/{total_batches}"
                scored = await self._process_single_batch_with_retry(batch, batch_id)
                all_scored.extend(scored)
            logger.info(f"串行处理完成: 共 {len(all_scored)} 条")
            return all_scored

        # 使用信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(batch_idx: int, batch: list[NewsItem]) -> list[NewsItem]:
            """带信号量控制的批次处理（带重试）"""
            async with semaphore:
                batch_id = f"{batch_idx}/{total_batches}"
                return await self._process_single_batch_with_retry(batch, batch_id)

        logger.info(f"🚀 并行处理 {total_batches} 个批次 (并发: {max_concurrent}, 每批次最大重试: {self._max_retries})")

        # 并行执行所有批次
        tasks = [
            process_with_semaphore(batch_idx, batch)
            for batch_idx, batch in enumerate(batches, 1)
        ]
        
        # 使用 return_exceptions=False，因为重试逻辑已处理异常
        results = await asyncio.gather(*tasks)

        # 合并结果
        all_scored = []
        for result in results:
            all_scored.extend(result)

        logger.info(f"✅ 并行处理完成: 共 {len(all_scored)} 条")

        return all_scored

    def _select_top_items(self, items: list[NewsItem]) -> list[NewsItem]:
        """筛选Top新闻（按分数+时间+多样性）"""
        # 按AI评分降序，评分相同时按发布时间降序（新的在前）
        sorted_items = sorted(items, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)
        return self._ensure_diversity(sorted_items)
    
    def _ensure_diversity(self, items: list[NewsItem]) -> list[NewsItem]:
        """确保分类多样性（混合方案）"""
        if not items:
            return []

        max_items = self.config.max_output_items

        # 按分类分组
        by_category = defaultdict(list)
        for item in items:
            category = getattr(item, 'ai_category', '未分类')
            by_category[category].append(item)

        # 根据配置选择算法
        if self.config.use_fixed_proportion and self.config.category_fixed_targets:
            return self._ensure_diversity_mixed(items, by_category, max_items)
        else:
            return self._ensure_diversity_original(items, by_category, max_items)

    def _ensure_diversity_mixed(
        self,
        items: list[NewsItem],
        by_category: dict[str, list[NewsItem]],
        max_items: int
    ) -> list[NewsItem]:
        """
        混合方案：固定保障 + 比例分配 + 轮询补充
        """
        fixed_targets = self.config.category_fixed_targets
        guarantees = self.config.category_min_guarantee or {}

        selected = []
        selected_by_category = defaultdict(int)

        # 第一阶段：固定保障（4:3:3）
        fixed_counts = {}
        for category, target in fixed_targets.items():
            cat_items = by_category.get(category, [])
            actual_count = min(target, len(cat_items))
            fixed_counts[category] = actual_count
            for item in cat_items[:actual_count]:
                selected.append(item)
                selected_by_category[category] += 1

        stage1_count = len(selected)
        logger.info(f"📊 混合方案-第一阶段(固定保障): {dict(fixed_counts)}, 共{stage1_count}条")

        # 第二阶段：按比例分配剩余名额
        remaining_slots = max_items - stage1_count

        if remaining_slots > 0:
            # 计算各分类剩余可用新闻数和比例
            remaining_by_category = {}
            total_remaining = 0

            for category in fixed_targets.keys():
                cat_items = by_category.get(category, [])
                already_selected = selected_by_category[category]
                remaining = len(cat_items) - already_selected
                if remaining > 0:
                    remaining_by_category[category] = remaining
                    total_remaining += remaining

            if total_remaining > 0:
                proportion_counts = {}
                for category, remaining_count in remaining_by_category.items():
                    proportion = remaining_count / total_remaining
                    allocated = min(int(proportion * remaining_slots), remaining_count)
                    proportion_counts[category] = allocated

                stage2_selected = 0
                for category, allocated in proportion_counts.items():
                    cat_items = by_category.get(category, [])
                    already_selected = selected_by_category[category]
                    for item in cat_items[already_selected:already_selected + allocated]:
                        selected.append(item)
                        selected_by_category[category] += 1
                    stage2_selected += allocated

                logger.info(f"📊 混合方案-第二阶段(比例分配): {proportion_counts}, 实际分配{stage2_selected}条")

        # 第三阶段：轮询补充（如仍有剩余）
        stage3_count = 0
        while len(selected) < max_items:
            added = False
            for category in fixed_targets.keys():
                if len(selected) >= max_items:
                    break
                cat_items = by_category.get(category, [])
                already_selected = selected_by_category[category]
                if already_selected < len(cat_items):
                    item = cat_items[already_selected]
                    selected.append(item)
                    selected_by_category[category] += 1
                    added = True
                    stage3_count += 1
            if not added:
                break

        if stage3_count > 0:
            logger.info(f"📊 混合方案-第三阶段(轮询补充): {stage3_count}条")

        # 记录最终分类分布
        final_distribution = {}
        for item in selected:
            category = getattr(item, 'ai_category', '未分类')
            final_distribution[category] = final_distribution.get(category, 0) + 1
        logger.info(f"📊 最终分类分布(混合方案): {final_distribution}")

        # 最终按评分排序（共同排序逻辑）
        return self._sort_by_score(selected)

    def _ensure_diversity_original(
        self,
        items: list[NewsItem],
        by_category: dict[str, list[NewsItem]],
        max_items: int
    ) -> list[NewsItem]:
        """
        原有算法（向后兼容）
        """
        guarantees = self.config.category_min_guarantee

        # 如果未配置保障，使用默认策略：每分类至少1条
        if not guarantees:
            guarantees = {cat: 1 for cat in by_category.keys() if cat != '未分类'}

        # 按比例缩减保障数（当总数超过max_items时）
        total_guarantee = sum(guarantees.values())
        if total_guarantee > max_items:
            scale = max_items / total_guarantee
            adjusted_guarantees = {
                cat: max(1, int(count * scale))
                for cat, count in guarantees.items()
            }
            logger.warning(f"保障总数({total_guarantee})超过上限({max_items})，已按比例缩减至: {adjusted_guarantees}")
        else:
            adjusted_guarantees = guarantees

        # 从各分类取保障数量
        selected = []
        for category, min_count in adjusted_guarantees.items():
            cat_items = by_category.get(category, [])
            for item in cat_items[:min_count]:
                if len(selected) < max_items:
                    selected.append(item)

        # 补充剩余名额（按评分从高到低）
        for item in items:
            if item not in selected and len(selected) < max_items:
                selected.append(item)

        # 最终按评分排序
        return self._sort_by_score(selected)

    def _sort_by_score(self, items: list[NewsItem]) -> list[NewsItem]:
        """按AI评分降序排序（共同排序逻辑）"""
        return sorted(items, key=lambda x: x.ai_score or 0, reverse=True)

    
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

    def get_stats(self) -> dict:
        return self._stats.copy()

    def select_top_items(
        self,
        items: list[NewsItem],
        min_threshold: float = 0.0,
        max_items: int | None = None
    ) -> list[NewsItem]:
        """
        统一的选择Top新闻接口（对外暴露）
        
        Args:
            items: 新闻列表
            min_threshold: 最低评分阈值
            max_items: 最大返回数量（默认使用配置值）
            
        Returns:
            筛选后的Top新闻列表
        """
        if not items:
            return []
        
        max_items = max_items or self.config.max_output_items
        
        # 过滤低于阈值的
        filtered = [item for item in items if (item.ai_score or 0) >= min_threshold]
        
        if not filtered:
            return []
        
        # 按AI评分降序，评分相同时按发布时间降序
        sorted_items = sorted(filtered, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)
        
        # 应用多样性选择
        selected = self._ensure_diversity(sorted_items)
        
        # 记录统计
        category_counts = {}
        for item in selected:
            cat = getattr(item, 'ai_category', '未分类')
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        logger.info(f"📊 分类分布: {category_counts}")
        logger.info(f"📋 从 {len(filtered)} 条中精选 Top {len(selected)} 条新闻")
        
        return selected

