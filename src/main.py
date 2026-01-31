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
from src.ai_scorer import AIScorer
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
        # 初始化HistoryManager，带AI评分缓存(24小时TTL)
        cache_ttl = getattr(self.config.ai_config, 'cache_ttl_hours', 24)
        self.history = HistoryManager(cache_ttl_hours=cache_ttl)
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
            "cache_hits": 0,
            "cache_misses": 0,
            "duplicates_removed": 0,
            "semantic_duplicates": 0,
        }
        
        try:
            # 1. 初始化各模块
            self._init_modules()
            
            # 2. 获取RSS新闻
            news_items = self._fetch_news()
            if not news_items:
                logger.warning("未获取到任何新闻")
                return False
            
            # 记录去重前数量
            run_metrics["duplicates_removed"] = 0  # 将在后续步骤中计算
            
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
            max_items=self.config.output_config.max_feed_items
        )
        
        logger.info(f"✓ 已加载 {len(self.config.rss_sources)} 个RSS源")
        ai_config = self.config.ai_config
        current_provider = ai_config.provider
        provider_config = ai_config.providers_config[current_provider]
        logger.info(f"✓ AI模型: {current_provider} ({provider_config.model})")
    
    def _fetch_news(self) -> List[NewsItem]:
        """获取新闻"""
        logger.info("📡 开始获取RSS新闻...")
        
        items = self.fetcher.fetch_all()
        
        # 过滤已处理的URL
        processed = self.history.get_processed_urls()
        new_items = [item for item in items if item.link not in processed]
        
        logger.info(f"✓ 获取 {len(items)} 条，其中新内容 {len(new_items)} 条")
        
        return new_items if new_items else items  # 如果没有新内容，使用全部
    
    async def _score_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """AI评分 (集成缓存检查)"""
        logger.info(f"🤖 开始AI评分(共 {len(items)} 条)...")
        
        # 分离已缓存和未缓存的项目
        cached_items = []
        uncached_items = []
        
        for item in items:
            self.history.record_cache_lookup()  # 记录查询
            cached_data = self.history.get_ai_score_from_cache(item)
            
            if cached_data:
                # 缓存命中，填充数据
                item.ai_score = cached_data['ai_score']
                item.translated_title = cached_data['translated_title']
                item.ai_summary = cached_data['ai_summary']
                item.key_points = cached_data['key_points'] if cached_data['key_points'] else []
                cached_items.append(item)
            else:
                # 缓存未命中，需要评分
                uncached_items.append(item)
        
        cache_stats = self.history.get_cache_stats()
        logger.info(f"💾 缓存命中: {len(cached_items)} 条 (命中率: {cache_stats['hit_rate_percent']}), 需评分: {len(uncached_items)} 条")
        
        # 只对未缓存的项目评分
        if uncached_items:
            scored_uncached = await self.scorer.score_all(uncached_items)
            
            # 缓存新评分结果
            for item in scored_uncached:
                self.history.save_ai_score_to_cache(item)
            
            # 合并结果
            scored_items = cached_items + scored_uncached
        else:
            scored_items = cached_items
            logger.info("✅ 全部来自缓存，无需API调用")
        
        # 过滤低于阈值的
        threshold = self.config.filter_config.min_score_threshold
        filtered = [item for item in scored_items if (item.ai_score or 0) >= threshold]
        
        logger.info(f"✓ 评分完成: {len(scored_items)}条，≥{threshold}分: {len(filtered)}条")
        
        return filtered
    
    def _select_top_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """选择Top N新闻（按三板块4:3:3比例分配）"""
        if not items:
            return []

        # 按 ai_category 分组
        finance_items = [item for item in items if item.ai_category == "财经"]
        tech_items = [item for item in items if item.ai_category == "科技"]
        politics_items = [item for item in items if item.ai_category == "社会政治"]

        # 计算精选总数
        total_count = len(items)
        if total_count <= 100:
            max_count = 10
        elif total_count <= 200:
            max_count = 20
        else:
            max_count = 30

        # 按 4:3:3 比例分配
        finance_count = max(int(max_count * 0.4), 3)  # 最少3条
        tech_count = max(int(max_count * 0.3), 2)       # 最少2条
        politics_count = max(int(max_count * 0.3), 2)   # 最少2条

        # 调整配额（如果某板块新闻不足，分配给其他板块）
        # 从财经开始调整
        if len(finance_items) < finance_count:
            extra = finance_count - len(finance_items)
            finance_count = len(finance_items)
            tech_count += extra // 2
            politics_count += extra - extra // 2

        if len(tech_items) < tech_count:
            extra = tech_count - len(tech_items)
            tech_count = len(tech_items)
            politics_count += extra

        if len(politics_items) < politics_count:
            extra = politics_count - len(politics_items)
            politics_count = len(politics_items)
            # 多余的配额分配给财经
            finance_count = min(finance_count + extra, len(finance_items))

        # 各自板块内按AI评分排序并选取
        def sort_by_score(item_list):
            return sorted(item_list, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)

        selected_finance = sort_by_score(finance_items)[:finance_count]
        selected_tech = sort_by_score(tech_items)[:tech_count]
        selected_politics = sort_by_score(politics_items)[:politics_count]

        # 合并所有选中新闻
        top_items = selected_finance + selected_tech + selected_politics

        # 记录各板块选取情况
        logger.info(f"📊 三板块选取: 财经 {len(selected_finance)}条 | 科技 {len(selected_tech)}条 | 社会政治 {len(selected_politics)}条")
        logger.info(f"📋 从 {total_count} 条中精选 Top {len(top_items)} 条新闻")

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
        
        # 记录已处理的URL
        for item in all_items:
            self.history.add_processed(item.link)
        
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
            logger.info(f"   缓存命中率: {report['cache_stats']['hit_rate_percent']}")
            logger.info(f"   平均时长: {report['avg_duration_seconds']:.1f} 秒")
            logger.info(f"   估算成本: {report['estimated_cost_per_run_usd']}/运行")


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
