"""
支持流水线架构的主程序入口
协调各模块完成RSS新闻聚合流程，使用异步流水线
"""
import os
import sys

# Add project root to sys.path to allow imports from src package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import asyncio
from datetime import datetime
from typing import List, Optional, AsyncIterator

from src.config import Config
from src.models import NewsItem, RSSSource
from src.rss_fetcher import RSSFetcher
from src.batch_scorer import BatchScorer
from src.ai_cache import AICache
from src.markdown_generator import MarkdownGenerator
from src.rss_generator import RSSGenerator
from src.history_manager import HistoryManager
from src.monitoring import create_monitor, StageType, PerformanceMonitor
from src.pipeline import AsyncPipeline, PipelineConfig
from src.stages import create_default_pipeline_stages

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class RSSPipelineAggregator:
    """RSS新闻聚合器主类（流水线版本）"""
    
    def __init__(self, enable_monitoring: bool = True, use_pipeline: bool = True):
        self.config = Config()
        self.history = HistoryManager()
        self.use_pipeline = use_pipeline
        
        # 基础组件
        self.fetcher = None
        self.scorer = None
        self.ai_cache = None
        self.markdown_gen = None
        self.rss_gen = None
        
        # 性能监控器
        self.monitor = None
        if enable_monitoring:
            self.monitor = create_monitor(
                output_dir="metrics",
                enable_logging=True,
                auto_save=True
            )
        
        # 流水线
        self.pipeline = None
        if use_pipeline:
            self._init_pipeline()
    
    def _init_pipeline(self):
        """初始化流水线"""
        logger.info("初始化异步流水线...")
        
        # 创建流水线配置
        pipeline_config = PipelineConfig(
            max_queue_size=100,
            timeout=300.0,  # 5分钟超时
            stop_on_critical_error=True
        )
        
        # 创建流水线实例
        self.pipeline = AsyncPipeline(
            config=pipeline_config,
            monitor=self.monitor
        )
        
        logger.info("✓ 流水线初始化完成")
    
    async def run(self) -> bool:
        """
        执行完整的新闻聚合流程
        
        Returns:
            是否成功
        """
        start_time = datetime.now()
        logger.info("=" * 60)
        logger.info(f"🚀 RSS新闻聚合开始（流水线模式） - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)
        
        try:
            # 开始性能监控
            if self.monitor:
                self.monitor.start()
            
            try:
                # 1. 初始化各模块
                self._init_modules()
                
                if self.use_pipeline:
                    # 2. 使用流水线处理
                    success = await self._run_with_pipeline()
                else:
                    # 2. 传统方式处理
                    success = await self._run_traditional()
                
                if not success:
                    return False
                
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
            
            logger.info("=" * 60)
            logger.info(f"✅ RSS新闻聚合完成 - 耗时: {duration:.1f}秒")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 执行失败: {e}", exc_info=True)
            return False
    
    def _init_modules(self):
        """初始化各模块"""
        logger.info("初始化模块...")
        
        # RSS抓取器
        self.fetcher = RSSFetcher(
            sources=self.config.rss_sources,
            output_config=self.config.output_config,
            filter_config=self.config.filter_config
        )
        
        # AI批处理评分器
        self.scorer = BatchScorer(
            config=self.config.ai_config
        )
        
        # AI缓存
        self.ai_cache = AICache()
        
        # 输出生成器
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
        
        # 如果使用流水线，添加阶段
        if self.use_pipeline and self.pipeline:
            self._add_pipeline_stages()
    
    def _add_pipeline_stages(self):
        """向流水线添加阶段"""
        # 创建默认阶段
        stages = create_default_pipeline_stages(
            config=self.config,
            history=self.history,
            fetcher=self.fetcher,
            scorer=self.scorer,
            cache=self.ai_cache
        )
        
        # 添加到流水线
        for stage in stages:
            self.pipeline.add_stage(stage)
        
        logger.info(f"✓ 流水线已添加 {len(stages)} 个阶段")
    
    async def _run_with_pipeline(self) -> bool:
        """使用流水线运行"""
        logger.info("🚀 启动异步流水线处理...")
        
        try:
            # 创建RSS源迭代器
            async def rss_source_iterator() -> AsyncIterator[RSSSource]:
                """RSS源异步迭代器"""
                for source in self.config.rss_sources:
                    if source.enabled:
                        logger.debug(f"向流水线提供源: {source.name}")
                        yield source
                        await asyncio.sleep(0.1)  # 小延迟避免阻塞
            
            # 运行流水线
            results = []
            async for result in self.pipeline.run(rss_source_iterator()):
                results.append(result)
                logger.debug(f"流水线产出结果: {result.get('item_count', 0)} 条新闻")
            
            # 处理结果
            if results:
                final_result = results[-1]  # 最后一个结果是生成阶段的输出
                item_count = final_result.get('item_count', 0)
                
                if item_count > 0:
                    # 更新统计
                    self._update_pipeline_stats(results)
                    logger.info(f"✅ 流水线处理完成: 生成 {item_count} 条新闻")
                    return True
                else:
                    logger.warning("⚠️ 流水线处理完成但未生成新闻")
                    return False
            else:
                logger.warning("⚠️ 流水线未产出任何结果")
                return False
            
        except Exception as e:
            logger.error(f"❌ 流水线运行失败: {e}", exc_info=True)
            return False
    
    async def _run_traditional(self) -> bool:
        """传统方式运行（不使用流水线）"""
        logger.info("🔄 使用传统方式处理...")
        
        try:
            # 1. 获取RSS新闻
            with self.monitor.stage('rss_fetch', StageType.RSS_FETCH):
                all_items = self.fetcher.fetch_all()
                # 过滤已处理的URL
                processed = self.history.get_processed_urls()
                news_items = [item for item in all_items if item.link not in processed]
            
            if not news_items:
                logger.warning("未获取到任何新闻")
                return False
            
            logger.info(f"📡 获取 {len(news_items)} 条新闻")
            
            # 2. AI评分和翻译
            with self.monitor.stage('ai_scoring', StageType.AI_SCORING):
                scored_items = await self.scorer.score_all(news_items)
            
            logger.info(f"🤖 AI评分完成: {len(scored_items)} 条")
            
            # 3. 筛选Top N
            threshold = self.config.filter_config.min_score_threshold
            filtered_items = [
                item for item in scored_items 
                if (item.ai_score or 0) >= threshold
            ]
            
            sorted_items = sorted(
                filtered_items,
                key=lambda x: (x.ai_score or 0, x.published_at),
                reverse=True
            )
            
            max_count = self.config.output_config.max_news_count
            top_items = sorted_items[:max_count]
            
            logger.info(f"📋 精选Top {len(top_items)} 条新闻")
            
            # 4. 生成输出文件
            with self.monitor.stage('generate_output', StageType.GENERATE_OUTPUT):
                now = datetime.now()
                latest_path, archive_path = self.markdown_gen.generate(top_items, now)
                self.rss_gen.generate(top_items)
            
            logger.info(f"📝 输出生成完成: Markdown={latest_path}, RSS=feed.xml")
            
            # 5. 更新统计
            self._update_traditional_stats(news_items, top_items)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 传统方式处理失败: {e}", exc_info=True)
            return False
    
    def _update_pipeline_stats(self, results: List[dict]):
        """更新流水线模式的统计"""
        # 从结果中提取信息
        total_processed = 0
        generated_items = 0
        
        for result in results:
            if isinstance(result, dict):
                item_count = result.get('item_count', 0)
                if 'generated_at' in result:  # 生成阶段的结果
                    generated_items = item_count
                total_processed += item_count
        
        # 更新历史
        run_time = datetime.now()
        
        # 简单的源统计（这里简化处理）
        source_stats = {source.name: 1 for source in self.config.rss_sources if source.enabled}
        
        self.history.update_stats(run_time, total_processed, source_stats)
        
        # 保存
        self.history.save()
        
        # 输出统计
        stats = self.history.get_stats()
        logger.info(f"📈 总运行次数: {stats['total_runs']}")
        logger.info(f"📈 总处理新闻: {stats['total_news_processed']}")
        logger.info(f"📈 平均每期: {stats['avg_news_per_run']}")
        
        # 打印流水线统计
        if self.pipeline:
            self.pipeline.print_stats_summary()
    
    def _update_traditional_stats(self, all_items: List[NewsItem], selected_items: List[NewsItem]):
        """更新传统模式的统计"""
        # 源统计
        source_stats = {}
        for item in all_items:
            source_stats[item.source] = source_stats.get(item.source, 0) + 1
        
        # 更新历史
        run_time = datetime.now()
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
            
            logger.info("=" * 60)
            logger.info("📊 性能监控摘要")
            logger.info("=" * 60)
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
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.warning(f"性能摘要生成失败: {e}")


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='RSS新闻聚合器（流水线版本）')
    parser.add_argument('--no-pipeline', action='store_true', 
                       help='不使用流水线，使用传统方式')
    parser.add_argument('--no-monitor', action='store_true',
                       help='禁用性能监控')
    
    args = parser.parse_args()
    
    # 创建聚合器
    aggregator = RSSPipelineAggregator(
        enable_monitoring=not args.no_monitor,
        use_pipeline=not args.no_pipeline
    )
    
    # 运行
    success = await aggregator.run()
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)