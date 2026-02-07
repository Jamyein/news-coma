"""
主程序入口
协调各模块完成RSS新闻聚合流程 (1-Pass版本)
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
from src.SmartScorer import SmartScorer
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
    """RSS新闻聚合器主类 (1-Pass版本)"""
    
    def __init__(self):
        self.config = Config()
        self.history = HistoryManager()
        self.fetcher = None
        self.scorer = None
        self.markdown_gen = None
        self.rss_gen = None
    
    async def run(self) -> bool:
        """
        执行完整的新闻聚合流程
        
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

            # 3. AI评分
            scored_items = await self._score_news(news_items)
            
            # 4. 筛选Top N
            top_items = self._select_top_news(scored_items)
            
            # 5. 生成输出文件
            self._generate_outputs(top_items)
            
            # 计算持续时间
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            run_metrics["duration_seconds"] = duration
            
            # 记录API调用次数
            provider_stats = self.scorer.batch_provider.get_stats()
            run_metrics["api_calls"] = provider_stats.get('api_call_count', 0)
            
            # 6. 更新历史统计
            self._update_stats(start_time, news_items, top_items, run_metrics)
            
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
        
        # 使用1-Pass SmartScorer
        self.scorer = SmartScorer(config=self.config.ai_config)
        
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
        
        # 显示配置信息
        ai_config = self.config.ai_config
        provider_config = ai_config.providers_config.get(ai_config.provider)
        if provider_config:
            logger.info(f"✓ AI模型: {ai_config.provider} ({provider_config.model})")
    
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
        scored_items = await self.scorer.score_news(items)

        # 过滤低于阈值的
        threshold = self.config.filter_config.min_score_threshold
        filtered = [item for item in scored_items if (item.ai_score or 0) >= threshold]

        logger.info(f"✓ 评分完成: {len(scored_items)}条，≥{threshold}分: {len(filtered)}条")

        return filtered
    
    def _select_top_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        选择Top N新闻
        
        策略：
        1. 按分数排序
        2. 确保分类多样性
        3. 返回前N条
        """
        if not items:
            return []
        
        # 按评分排序
        sorted_items = sorted(items, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)
        
        # 按分类分组
        by_category = {}
        for item in sorted_items:
            category = getattr(item, 'ai_category', '未分类')
            by_category.setdefault(category, []).append(item)
        
        # 简单多样性策略：每个分类至少选1条
        selected = []
        max_items = self.config.output_config.max_news_count
        
        # 先选每个分类的第一条
        for category, cat_items in by_category.items():
            if cat_items and len(selected) < max_items:
                selected.append(cat_items[0])
        
        # 补充剩余的高分新闻
        for item in sorted_items:
            if item not in selected and len(selected) < max_items:
                selected.append(item)
        
        # 按分数重新排序
        selected.sort(key=lambda x: x.ai_score or 0, reverse=True)
        
        # 记录统计
        category_counts = {}
        for item in selected:
            cat = getattr(item, 'ai_category', '未分类')
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        logger.info(f"📊 分类分布: {category_counts}")
        logger.info(f"📋 从 {len(items)} 条中精选 Top {len(selected)} 条新闻")

        return selected
    
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
        """更新统计数据"""
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
        
        # 更新历史
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
    aggregator = RSSAggregator()
    success = await aggregator.run()
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
