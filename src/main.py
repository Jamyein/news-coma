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
from typing import List, Optional

from src.config import Config
from src.models import NewsItem
from src.rss_fetcher import RSSFetcher
from src.ai_scorer import AIScorer
from src.markdown_generator import MarkdownGenerator
from src.rss_generator import RSSGenerator
from src.history_manager import HistoryManager
from src.monitoring import create_monitor, StageType, PerformanceMonitor

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
    
    def __init__(self, enable_monitoring: bool = True):
        self.config = Config()
        self.history = HistoryManager()
        self.fetcher = None
        self.scorer = None
        self.markdown_gen = None
        self.rss_gen = None
        self.monitor = None
        
        # 初始化性能监控器
        if enable_monitoring:
            self.monitor = create_monitor(
                output_dir="metrics",
                enable_logging=True,
                auto_save=True
            )
    
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
        
        try:
            # 开始性能监控
            if self.monitor:
                self.monitor.start()
            
            try:
                # 1. 初始化各模块
                self._init_modules()
                
                # 2. 获取RSS新闻
                news_items = self._fetch_news()
                if not news_items:
                    logger.warning("未获取到任何新闻")
                    return False
                
                # 3. AI评分和翻译
                scored_items = await self._score_news(news_items)
                
                # 4. 筛选Top N
                top_items = self._select_top_news(scored_items)
                
                # 5. 生成输出文件
                self._generate_outputs(top_items)
                
                # 6. 更新历史统计
                self._update_stats(start_time, news_items, top_items)
                
            except Exception as e:
                # 记录错误
                if self.monitor:
                    self.monitor.increment('errors')
                raise
            
            finally:
                # 结束性能监控
                if self.monitor:
                    self.monitor.end()
                    # 打印性能摘要
                    self._print_performance_summary()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
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
        
        self.scorer = AIScorer(
            config=self.config.ai_config,
            monitor=self.monitor  # 传递监控器
        )
        
        self.markdown_gen = MarkdownGenerator(
            output_dir="docs",
            archive_dir="archive"
        )
        
        self.rss_gen = RSSGenerator(
            feed_path="feed.xml",
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
        
        # 使用监控器记录RSS抓取阶段
        stage_context = None
        if self.monitor:
            stage_context = self.monitor.stage('rss_fetch', StageType.RSS_FETCH)
            stage_context.__enter__()
        
        try:
            items = self.fetcher.fetch_all()
            
            # 过滤已处理的URL
            processed = self.history.get_processed_urls()
            new_items = [item for item in items if item.link not in processed]
            
            logger.info(f"✓ 获取 {len(items)} 条，其中新内容 {len(new_items)} 条")
            
            return new_items if new_items else items  # 如果没有新内容，使用全部
        
        finally:
            if stage_context:
                stage_context.__exit__(None, None, None)
    
    async def _score_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """AI评分"""
        logger.info(f"🤖 开始AI评分(共 {len(items)} 条)...")
        
        scored_items = await self.scorer.score_all(items)
        
        # 过滤低于阈值的
        threshold = self.config.filter_config.min_score_threshold
        filtered = [item for item in scored_items if (item.ai_score or 0) >= threshold]
        
        logger.info(f"✓ 评分完成: {len(scored_items)}条，≥{threshold}分: {len(filtered)}条")
        
        return filtered
    
    def _select_top_news(self, items: List[NewsItem]) -> List[NewsItem]:
        """选择Top N新闻"""
        # 按AI评分排序
        sorted_items = sorted(
            items, 
            key=lambda x: (x.ai_score or 0, x.published_at), 
            reverse=True
        )
        
        # 取前N条
        max_count = self.config.output_config.max_news_count
        top_items = sorted_items[:max_count]
        
        logger.info(f"📋 精选Top {len(top_items)} 条新闻")
        
        return top_items
    
    def _generate_outputs(self, items: List[NewsItem]):
        """生成输出文件"""
        logger.info("📝 生成输出文件...")
        
        # 使用监控器记录输出生成阶段
        stage_context = None
        if self.monitor:
            stage_context = self.monitor.stage('generate_output', StageType.GENERATE_OUTPUT)
            stage_context.__enter__()
        
        try:
            now = datetime.now()
            
            # 生成Markdown
            latest_path, archive_path = self.markdown_gen.generate(items, now)
            logger.info(f"✓ Markdown: {latest_path}")
            
            # 生成RSS
            self.rss_gen.generate(items)
            logger.info(f"✓ RSS feed: feed.xml")
        
        finally:
            if stage_context:
                stage_context.__exit__(None, None, None)
    
    def _update_stats(self, run_time: datetime, all_items: List[NewsItem], 
                      selected_items: List[NewsItem]):
        """更新统计数据"""
        # 源统计
        source_stats = {}
        for item in all_items:
            source_stats[item.source] = source_stats.get(item.source, 0) + 1
        
        # 更新历史
        self.history.update_stats(run_time, len(all_items), source_stats)
        
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
    
    def _print_performance_summary(self):
        """打印性能监控摘要"""
        if not self.monitor:
            return
        
        try:
            report = self.monitor.generate_report()
            
            logger.info("=" * 50)
            logger.info("📊 性能监控摘要")
            logger.info("=" * 50)
            logger.info(f"总耗时: {report['summary']['total_duration']:.2f}秒")
            logger.info(f"处理新闻: {report['summary']['news_items_processed']}条")
            logger.info(f"API调用: {report['summary']['total_api_calls']}次")
            
            if report['summary']['total_tokens'] > 0:
                logger.info(f"Token使用: {report['summary']['total_tokens']:,}")
            
            if report['summary']['cache_hits'] > 0 or report['summary']['cache_misses'] > 0:
                hit_rate = report['summary']['cache_hit_rate']
                hits = report['summary']['cache_hits']
                misses = report['summary']['cache_misses']
                logger.info(f"缓存命中率: {hit_rate:.1f}% (命中: {hits}, 未命中: {misses})")
            
            # 计算效率指标
            efficiency = report['efficiency']
            if efficiency['items_per_second'] > 0:
                logger.info(f"处理速度: {efficiency['items_per_second']:.2f}条/秒")
            
            if efficiency['api_calls_per_item'] > 0:
                logger.info(f"每新闻API调用: {efficiency['api_calls_per_item']:.3f}")
            
            # 阶段耗时详情
            if report['stages']:
                logger.info(f"\n阶段耗时详情:")
                for name, data in report['stages'].items():
                    duration = data['total_duration']
                    logger.info(f"  {name}: {duration:.3f}秒 ({data['count']}次)")
            
            logger.info("=" * 50)
            
        except Exception as e:
            logger.warning(f"性能摘要生成失败: {e}")
 
if __name__ == "__main__":
    asyncio.run(main())
