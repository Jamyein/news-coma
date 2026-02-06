"""
A/B测试桥接层 - 同时运行2-pass和1-pass进行对比测试

用于验证1-pass方案的性能和质量
"""

import asyncio
import logging
from typing import List, Dict, Tuple
from datetime import datetime
from dataclasses import dataclass, field

from src.models import NewsItem
from src.AIScorer import AIScorer
from src.SmartScorer import SmartScorer
from src.config import Config

logger = logging.getLogger(__name__)


@dataclass
class ABTestResult:
    """A/B测试结果"""
    method: str                      # 方法名称 (2-pass / 1-pass)
    items: List[NewsItem]            # 评分结果
    duration_seconds: float          # 处理时间
    api_calls: int                   # API调用次数
    errors: List[str] = field(default_factory=list)


class ABTestBridge:
    """
    A/B测试桥接器
    
    职责:
    1. 同时运行2-pass和1-pass评分
    2. 收集性能对比数据
    3. 生成对比报告
    4. 验证1-pass质量
    """
    
    def __init__(self):
        """初始化A/B测试桥接器"""
        self.config = Config()
        self.results = {
            "2pass": None,
            "1pass": None
        }
        
        logger.info("A/B测试桥接器初始化完成")
    
    async def run_comparison(self, items: List[NewsItem]) -> Dict:
        """
        运行A/B对比测试
        
        同时运行2-pass和1-pass，对比性能和质量
        
        Args:
            items: 待评分的新闻列表
            
        Returns:
            Dict: 对比结果报告
        """
        logger.info("=" * 60)
        logger.info("🧪 启动A/B测试对比")
        logger.info("=" * 60)
        
        # 复制新闻项，避免相互影响
        items_2pass = self._clone_items(items)
        items_1pass = self._clone_items(items)
        
        # 运行2-pass
        logger.info("\n[2-Pass] 开始评分...")
        result_2pass = await self._run_2pass(items_2pass)
        
        # 运行1-pass
        logger.info("\n[1-Pass] 开始评分...")
        result_1pass = await self._run_1pass(items_1pass)
        
        # 生成对比报告
        report = self._generate_report(result_2pass, result_1pass)
        
        # 输出报告
        self._print_report(report)
        
        return report
    
    async def _run_2pass(self, items: List[NewsItem]) -> ABTestResult:
        """运行2-pass评分"""
        start_time = datetime.now()
        
        try:
            scorer = AIScorer(config=self.config.ai_config)
            scored_items = await scorer.score_all(items)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ABTestResult(
                method="2-pass",
                items=scored_items,
                duration_seconds=duration,
                api_calls=scorer.get_api_call_count()
            )
        except Exception as e:
            logger.error(f"2-pass评分失败: {e}")
            return ABTestResult(
                method="2-pass",
                items=[],
                duration_seconds=0,
                api_calls=0,
                errors=[str(e)]
            )
    
    async def _run_1pass(self, items: List[NewsItem]) -> ABTestResult:
        """运行1-pass评分"""
        start_time = datetime.now()
        
        try:
            scorer = SmartScorer(config=self.config.one_pass_config)
            scored_items = await scorer.score_news(items)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ABTestResult(
                method="1-pass",
                items=scored_items,
                duration_seconds=duration,
                api_calls=scorer.batch_provider.get_stats().get('api_call_count', 0)
            )
        except Exception as e:
            logger.error(f"1-pass评分失败: {e}")
            return ABTestResult(
                method="1-pass",
                items=[],
                duration_seconds=0,
                api_calls=0,
                errors=[str(e)]
            )
    
    def _clone_items(self, items: List[NewsItem]) -> List[NewsItem]:
        """克隆新闻项（深拷贝）"""
        from copy import deepcopy
        return deepcopy(items)
    
    def _generate_report(
        self,
        result_2pass: ABTestResult,
        result_1pass: ABTestResult
    ) -> Dict:
        """生成对比报告"""
        
        # 性能对比
        perf_2pass = {
            "duration_seconds": result_2pass.duration_seconds,
            "api_calls": result_2pass.api_calls,
            "output_count": len(result_2pass.items)
        }
        
        perf_1pass = {
            "duration_seconds": result_1pass.duration_seconds,
            "api_calls": result_1pass.api_calls,
            "output_count": len(result_1pass.items)
        }
        
        # 质量对比
        quality_2pass = self._calculate_quality(result_2pass.items)
        quality_1pass = self._calculate_quality(result_1pass.items)
        
        # 计算改进百分比
        if perf_2pass["duration_seconds"] > 0:
            time_improvement = (
                (perf_2pass["duration_seconds"] - perf_1pass["duration_seconds"])
                / perf_2pass["duration_seconds"] * 100
            )
        else:
            time_improvement = 0
        
        if perf_2pass["api_calls"] > 0:
            api_improvement = (
                (perf_2pass["api_calls"] - perf_1pass["api_calls"])
                / perf_2pass["api_calls"] * 100
            )
        else:
            api_improvement = 0
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "input_count": len(result_2pass.items) + len(result_1pass.items),
            
            "performance": {
                "2pass": perf_2pass,
                "1pass": perf_1pass,
                "improvement": {
                    "time_percent": round(time_improvement, 1),
                    "api_percent": round(api_improvement, 1)
                }
            },
            
            "quality": {
                "2pass": quality_2pass,
                "1pass": quality_1pass,
                "difference": {
                    "avg_score_diff": round(quality_2pass["avg_score"] - quality_1pass["avg_score"], 2),
                    "category_distribution_diff": self._calculate_category_diff(
                        quality_2pass["category_distribution"],
                        quality_1pass["category_distribution"]
                    )
                }
            },
            
            "errors": {
                "2pass": result_2pass.errors,
                "1pass": result_1pass.errors
            }
        }
        
        return report
    
    def _calculate_quality(self, items: List[NewsItem]) -> Dict:
        """计算质量指标"""
        if not items:
            return {
                "avg_score": 0,
                "category_distribution": {}
            }
        
        # 平均分数
        scores = [item.ai_score for item in items if item.ai_score is not None]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # 分类分布
        category_dist = {}
        for item in items:
            category = getattr(item, 'ai_category', '未分类')
            category_dist[category] = category_dist.get(category, 0) + 1
        
        return {
            "avg_score": round(avg_score, 2),
            "category_distribution": category_dist
        }
    
    def _calculate_category_diff(self, dist_2pass: Dict, dist_1pass: Dict) -> Dict:
        """计算分类分布差异"""
        all_categories = set(dist_2pass.keys()) | set(dist_1pass.keys())
        diff = {}
        
        for category in all_categories:
            count_2pass = dist_2pass.get(category, 0)
            count_1pass = dist_1pass.get(category, 0)
            diff[category] = count_2pass - count_1pass
        
        return diff
    
    def _print_report(self, report: Dict):
        """打印对比报告"""
        logger.info("\n" + "=" * 60)
        logger.info("📊 A/B测试对比报告")
        logger.info("=" * 60)
        
        # 性能对比
        perf = report["performance"]
        logger.info("\n⚡ 性能对比:")
        logger.info(f"  处理时间: 2-pass={perf['2pass']['duration_seconds']:.1f}s, "
                   f"1-pass={perf['1pass']['duration_seconds']:.1f}s "
                   f"(提升{perf['improvement']['time_percent']:.1f}%)")
        logger.info(f"  API调用: 2-pass={perf['2pass']['api_calls']}, "
                   f"1-pass={perf['1pass']['api_calls']} "
                   f"(减少{perf['improvement']['api_percent']:.1f}%)")
        
        # 质量对比
        quality = report["quality"]
        logger.info("\n📈 质量对比:")
        logger.info(f"  平均分数: 2-pass={quality['2pass']['avg_score']}, "
                   f"1-pass={quality['1pass']['avg_score']} "
                   f"(差异{quality['difference']['avg_score_diff']})")
        logger.info(f"  分类分布(2-pass): {quality['2pass']['category_distribution']}")
        logger.info(f"  分类分布(1-pass): {quality['1pass']['category_distribution']}")
        
        # 结论
        logger.info("\n✅ 结论:")
        if perf['improvement']['time_percent'] > 50:
            logger.info(f"  ✓ 1-pass处理时间显著优于2-pass (提升{perf['improvement']['time_percent']:.1f}%)")
        if perf['improvement']['api_percent'] > 40:
            logger.info(f"  ✓ 1-pass API调用显著少于2-pass (减少{perf['improvement']['api_percent']:.1f}%)")
        if abs(quality['difference']['avg_score_diff']) < 1.0:
            logger.info(f"  ✓ 1-pass质量与2-pass相当 (分数差异{quality['difference']['avg_score_diff']})")
        
        logger.info("=" * 60)


# 快速测试入口
async def run_ab_test(items: List[NewsItem]) -> Dict:
    """
    快速运行A/B测试
    
    用法:
        from src.ab_test_bridge import run_ab_test
        report = await run_ab_test(news_items)
    """
    bridge = ABTestBridge()
    return await bridge.run_comparison(items)
