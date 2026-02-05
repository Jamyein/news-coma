"""
主程序入口
协调各模块完成RSS新闻聚合流程
"""
import os
import sys

# Add project root to sys.path to allow imports from src package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import asyncio
from datetime import datetime
from typing import List

from src.config import Config
from src.models import NewsItem
from src.rss_fetcher import RSSFetcher
from src.AIScorer import AIScorer
from src.markdown_generator import MarkdownGenerator
from src.rss_generator import RSSGenerator
from src.history_manager import HistoryManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class RSSAggregator:
    """RSS新闻聚合器主类"""
    
    def __init__(self):
        self.config = Config()
        self.history = HistoryManager()
        self.fetcher = None
        self.scorer = None
        self.markdown_gen = None
        self.rss_gen = None
    
    async def run(self) -> bool:
        """
        执行完整的新闻聚合流程 (带详细指标收集)
        
        Returns:
            是否成功
        """
        start_time = datetime.now()
        logger.info("=" * 50)
        logger.info(f"🚀 RSS新闻聚合开始 - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 50)
        
        # 初始化运行指标
        run_metrics = {
            "api_calls": 0,
        }
        
        try:
            # 1. 初始化各模块
            self._init_modules()
            
            # 2. 获取RSS新闻
            news_items = self._fetch_news()
            if not news_items:
                logger.warning("未获取到任何新闻")
                return False

            # 3. AI评分和翻译 (集成缓存)
            scored_items = await self._score_news(news_items)
            
            # 4. 筛选Top N
            top_items = self._select_top_news(scored_items)
            
            # 5. 生成输出文件
            self._generate_outputs(top_items)
            
            # 计算持续时间
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            run_metrics["duration_seconds"] = duration
            
            # 记录API调用次数 (从AIScorer获取)
            run_metrics["api_calls"] = self.scorer.get_api_call_count()
            
            # 6. 更新历史统计 (带详细指标)
            self._update_stats(start_time, news_items, top_items, run_metrics)
            
            # 重置API调用计数
            self.scorer.reset_api_call_count()
            
            logger.info("=" * 50)
            logger.info(f"✅ RSS新闻聚合完成 - 耗时: {duration:.1f}秒")
            logger.info(f"📊 本次处理: {len(news_items)}条 → 精选: {len(top_items)}条")
            logger.info("=" * 50)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 执行失败: {e}", exc_info=True)
            return False
    
    def _init_modules(self):
        """初始化各模块"""
        logger.info("初始化模块...")
        
        self.fetcher = RSSFetcher(
            sources=self.config.rss_sources,
            output_config=self.config.output_config,
            filter_config=self.config.filter_config
        )
        
        self.scorer = AIScorer(config=self.config.ai_config)
        
        self.markdown_gen = MarkdownGenerator(
            output_dir="docs",
            archive_dir="archive"
        )
        
        self.rss_gen = RSSGenerator(
            feed_path="feed.xml",
            archive_dir="archive",
            docs_dir="docs",
            max_items=self.config.output_config.max_feed_items,
            use_smart_switch=self.config.output_config.use_smart_switch
        )
        
        logger.info(f"✓ 已加载 {len(self.config.rss_sources)} 个RSS源")
        ai_config = self.config.ai_config
        current_provider = ai_config.provider
        provider_config = ai_config.providers_config[current_provider]
        logger.info(f"✓ AI模型: {current_provider} ({provider_config.model})")
    
    def _fetch_news(self) -> List[NewsItem]:
        """
        获取新闻（支持基于时间节点的增量获取）
        """
        logger.info("📡 开始获取RSS新闻...")
        
        all_items = []
        source_stats = {}
        
        for source in self.config.rss_sources:
            if not source.enabled:
                continue
            
            # 获取该源的最后获取时间
            last_fetch = self.history.get_source_last_fetch(source.name)
            
            # 如果该源没有记录，尝试使用fallback
            if not last_fetch:
                last_fetch = self.history.get_fallback_last_fetch()
                if last_fetch:
                    logger.info(f"⏰ {source.name} 使用全局fallback时间: {last_fetch}")
            
            try:
                # 获取该源的新闻（传入last_fetch实现增量获取）
                items = self.fetcher._fetch_single(source, last_fetch)
                all_items.extend(items)
                source_stats[source.name] = len(items)
                
                # 更新该源的最后获取时间（使用当前时间）
                self.history.update_source_last_fetch(source.name, datetime.now())
                
                if last_fetch:
                    logger.info(
                        f"✓ {source.name}: 增量获取 {len(items)} 条 "
                        f"(上次: {last_fetch.strftime('%m-%d %H:%M')})"
                    )
                else:
                    logger.info(f"✓ {source.name}: 全量获取 {len(items)} 条")
                    
            except Exception as e:
                logger.error(f"❌ 获取 {source.name} 失败: {e}")
                # 失败时不更新时间戳，下次会重试
                continue
        
        logger.info(f"📊 总计: 获取 {len(all_items)} 条")
        logger.info(f"📊 各源统计: {source_stats}")
        
        return all_items
    
    async def _score_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """AI评分"""
        logger.info(f"🤖 开始AI评分(共 {len(items)} 条)...")

        # 对所有项目进行评分
        scored_items = await self.scorer.score_all(items)

        # 过滤低于阈值的
        threshold = self.config.filter_config.min_score_threshold
        filtered = [item for item in scored_items if (item.ai_score or 0) >= threshold]

        logger.info(f"✓ 评分完成: {len(scored_items)}条，≥{threshold}分: {len(filtered)}条")

        return filtered
    
    def _select_top_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """选择Top N新闻（按三板块4:3:3固定比例分配）"""
        if not items:
            return []

        # 按 ai_category 分组
        finance_items = [item for item in items if item.ai_category == "财经"]
        tech_items = [item for item in items if item.ai_category == "科技"]
        politics_items = [item for item in items if item.ai_category == "社会政治"]
        
        # 未分类新闻单独处理
        uncategorized_items = [item for item in items if item.ai_category not in ["财经", "科技", "社会政治"]]

        # 固定总数：30条（根据配置）
        max_count = self.config.output_config.max_news_count  # 从配置读取，默认为30
        
        # 固定比例分配：财经40%，科技30%，社会政治30%
        target_finance_count = int(max_count * self.config.ai_config.category_quota_finance)  # 12条
        target_tech_count = int(max_count * self.config.ai_config.category_quota_tech)        # 9条
        target_politics_count = int(max_count * self.config.ai_config.category_quota_politics)  # 9条
        
        # 实际可选取数量（不能超过实际可用数量）
        actual_finance_count = min(target_finance_count, len(finance_items))
        actual_tech_count = min(target_tech_count, len(tech_items))
        actual_politics_count = min(target_politics_count, len(politics_items))
        
        # 计算剩余配额
        remaining_quota = max_count - (actual_finance_count + actual_tech_count + actual_politics_count)
        
        # 如果某板块新闻不足，按优先级重新分配配额
        # 优先级：财经 > 科技 > 社会政治 > 未分类
        if remaining_quota > 0:
            # 首先尝试补充财经
            if actual_finance_count < target_finance_count:
                can_add = min(remaining_quota, target_finance_count - actual_finance_count)
                actual_finance_count += can_add
                remaining_quota -= can_add
            
            # 然后尝试补充科技
            if remaining_quota > 0 and actual_tech_count < target_tech_count:
                can_add = min(remaining_quota, target_tech_count - actual_tech_count)
                actual_tech_count += can_add
                remaining_quota -= can_add
            
            # 然后尝试补充社会政治
            if remaining_quota > 0 and actual_politics_count < target_politics_count:
                can_add = min(remaining_quota, target_politics_count - actual_politics_count)
                actual_politics_count += can_add
                remaining_quota -= can_add
            
            # 最后用未分类新闻填充剩余配额
            if remaining_quota > 0 and uncategorized_items:
                # 从未分类新闻中选取评分最高的
                uncategorized_sorted = sorted(uncategorized_items, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)
                extra_from_uncategorized = min(remaining_quota, len(uncategorized_sorted))
                # 将这些未分类新闻标记为"未分类"板块
                for item in uncategorized_sorted[:extra_from_uncategorized]:
                    item.ai_category = "未分类"
                uncategorized_selected = uncategorized_sorted[:extra_from_uncategorized]
                remaining_quota -= extra_from_uncategorized
            else:
                uncategorized_selected = []

        # 各自板块内按AI评分排序并选取
        def sort_by_score(item_list):
            return sorted(item_list, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)

        selected_finance = sort_by_score(finance_items)[:actual_finance_count]
        selected_tech = sort_by_score(tech_items)[:actual_tech_count]
        selected_politics = sort_by_score(politics_items)[:actual_politics_count]
        
        # 合并所有选中新闻
        if 'uncategorized_selected' in locals():
            top_items = selected_finance + selected_tech + selected_politics + uncategorized_selected
        else:
            top_items = selected_finance + selected_tech + selected_politics

        # 记录各板块选取情况
        logger.info(f"📊 三板块选取: 财经 {len(selected_finance)}/{target_finance_count}条 | 科技 {len(selected_tech)}/{target_tech_count}条 | 社会政治 {len(selected_politics)}/{target_politics_count}条")
        if 'uncategorized_selected' in locals() and uncategorized_selected:
            logger.info(f"📊 补充未分类新闻: {len(uncategorized_selected)}条")
        logger.info(f"📋 从 {len(items)} 条中精选 Top {len(top_items)} 条新闻 (目标: {max_count}条)")

        return top_items
    
    def _generate_outputs(self, items: List[NewsItem]):
        """生成输出文件"""
        logger.info("📝 生成输出文件...")
        
        now = datetime.now()
        
        # 生成Markdown
        latest_path, archive_path = self.markdown_gen.generate(items, now)
        logger.info(f"✓ Markdown: {latest_path}")
        
        # 生成RSS
        self.rss_gen.generate()
        logger.info(f"✓ RSS feed: feed.xml")
    
    def _update_stats(self, run_time: datetime, all_items: List[NewsItem], 
                      selected_items: List[NewsItem],
                      run_metrics: dict = None):
        """更新统计数据 (扩展支持详细运行指标)"""
        # 源统计
        source_stats = {}
        for item in all_items:
            source_stats[item.source] = source_stats.get(item.source, 0) + 1
        
        # 计算平均评分
        avg_score = 0
        if selected_items:
            scores = [item.ai_score for item in selected_items if item.ai_score is not None]
            if scores:
                avg_score = sum(scores) / len(scores)
        
        # 准备详细指标
        metrics = run_metrics or {}
        metrics['avg_score'] = avg_score
        
        # 更新历史 (带详细指标)
        self.history.update_stats(run_time, len(all_items), source_stats, **metrics)
        
        # 更新源选中统计
        for item in selected_items:
            self.history.update_source_selected(item.source, 1)
        
        # 保存
        self.history.save()
        
        # 输出统计
        stats = self.history.get_stats()
        logger.info(f"📈 总运行次数: {stats['total_runs']}")
        logger.info(f"📈 总处理新闻: {stats['total_news_processed']}")
        logger.info(f"📈 平均每期: {stats['avg_news_per_run']}")

        # 输出性能报告
        report = self.history.get_performance_report()
        if 'recent_runs' in report:
            logger.info("📊 性能报告(最近10次平均):")
            logger.info(f"   API调用: {report['avg_api_calls_per_run']:.1f} 次/运行")
            logger.info(f"   平均时长: {report['avg_duration_seconds']:.1f} 秒")


async def main():
    """主入口函数"""
    # 创建聚合器并运行
    # API key validation is now handled in Config class based on selected provider
    aggregator = RSSAggregator()
    success = await aggregator.run()
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
