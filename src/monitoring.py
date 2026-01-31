"""
性能监控与指标收集系统
用于RSS新闻聚合项目的性能监控，量化优化前后的性能指标
"""
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Dict, List, Optional, Callable, Any, Union
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class StageType(Enum):
    """性能监控阶段类型"""
    RSS_FETCH = "rss_fetch"
    AI_SCORING = "ai_scoring"
    GENERATE_OUTPUT = "generate_output"
    CACHE_LOOKUP = "cache_lookup"
    API_CALL = "api_call"
    CUSTOM = "custom"


@dataclass
class StageMetrics:
    """阶段性能指标"""
    name: str
    duration: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool = True
    error_message: Optional[str] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['stage_type'] = self.name
        return data


@dataclass
class CounterMetrics:
    """计数器指标"""
    api_calls: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    errors: int = 0
    news_items_processed: int = 0
    
    def increment(self, counter_name: str, value: int = 1):
        """增加计数器值"""
        if hasattr(self, counter_name):
            current = getattr(self, counter_name)
            setattr(self, counter_name, current + value)


class StageTimer:
    """阶段计时器，支持高精度计时"""
    
    def __init__(self, name: str, stage_type: StageType = StageType.CUSTOM):
        self.name = name
        self.stage_type = stage_type
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.duration: Optional[float] = None
        self.error: Optional[str] = None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end()
        if exc_val is not None:
            self.error = str(exc_val)
            return False
        return True
    
    async def __aenter__(self):
        self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.end()
        if exc_val is not None:
            self.error = str(exc_val)
            return False
        return True
    
    def start(self):
        """开始计时"""
        self.start_time = time.perf_counter()
        self.end_time = None
        self.duration = None
        self.error = None
    
    def end(self):
        """结束计时"""
        if self.start_time is not None:
            self.end_time = time.perf_counter()
            self.duration = self.end_time - self.start_time
    
    def get_metrics(self) -> StageMetrics:
        """获取阶段指标"""
        return StageMetrics(
            name=self.name,
            duration=self.duration or 0.0,
            start_time=self.start_time or 0.0,
            end_time=self.end_time or 0.0,
            success=self.error is None,
            error_message=self.error,
            custom_data={'stage_type': self.stage_type.value}
        )


class MetricsCollector:
    """指标收集器，支持线程安全操作"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._counters = CounterMetrics()
        self._stages: Dict[str, List[StageMetrics]] = {}
        self._custom_metrics: Dict[str, Any] = {}
    
    def increment_counter(self, name: str, value: int = 1):
        """增加计数器值"""
        with self._lock:
            self._counters.increment(name, value)
    
    def add_stage_metrics(self, stage_metrics: StageMetrics):
        """添加阶段指标"""
        with self._lock:
            if stage_metrics.name not in self._stages:
                self._stages[stage_metrics.name] = []
            self._stages[stage_metrics.name].append(stage_metrics)
    
    def set_custom_metric(self, name: str, value: Any):
        """设置自定义指标"""
        with self._lock:
            self._custom_metrics[name] = value
    
    def get_counters(self) -> CounterMetrics:
        """获取计数器指标"""
        with self._lock:
            return self._counters
    
    def get_stages(self) -> Dict[str, List[StageMetrics]]:
        """获取所有阶段指标"""
        with self._lock:
            return self._stages.copy()
    
    def get_custom_metrics(self) -> Dict[str, Any]:
        """获取自定义指标"""
        with self._lock:
            return self._custom_metrics.copy()
    
    def clear(self):
        """清空所有指标"""
        with self._lock:
            self._counters = CounterMetrics()
            self._stages = {}
            self._custom_metrics = {}


class PerformanceMonitor:
    """性能监控器 - 主入口"""
    
    def __init__(
        self,
        output_dir: Union[str, Path] = "metrics",
        enable_logging: bool = True,
        auto_save: bool = True,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        初始化性能监控器
        
        Args:
            output_dir: 输出目录
            enable_logging: 是否启用日志
            auto_save: 是否自动保存报告
            callback: 实时监控回调函数
        """
        self.output_dir = Path(output_dir)
        self.enable_logging = enable_logging
        self.auto_save = auto_save
        self.callback = callback
        
        # 创建目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "history").mkdir(parents=True, exist_ok=True)
        
        # 初始化指标收集器
        self.collector = MetricsCollector()
        
        # 运行状态
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._is_running = False
        
        if enable_logging:
            logger.info(f"性能监控器初始化完成，输出目录: {self.output_dir}")
    
    def start(self):
        """开始监控"""
        self._start_time = time.perf_counter()
        self._end_time = None
        self._is_running = True
        
        if self.enable_logging:
            logger.info("🔍 性能监控开始")
        
        return self
    
    def end(self):
        """结束监控"""
        if not self._is_running:
            return
        
        self._end_time = time.perf_counter()
        self._is_running = False
        
        if self.enable_logging:
            total_duration = self._end_time - self._start_time
            logger.info(f"🔚 性能监控结束，总耗时: {total_duration:.2f}s")
        
        # 自动保存报告
        if self.auto_save:
            self.save_report()
    
    @contextmanager
    def stage(self, name: str, stage_type: StageType = StageType.CUSTOM):
        """
        阶段计时上下文管理器
        
        用法:
            with monitor.stage('ai_scoring'):
                await scorer.score_all(items)
        
        Args:
            name: 阶段名称
            stage_type: 阶段类型
        """
        timer = StageTimer(name, stage_type)
        
        try:
            timer.start()
            if self.enable_logging:
                logger.debug(f"⏱️ 开始阶段: {name}")
            
            yield self
            
            timer.end()
            if self.enable_logging:
                logger.debug(f"✅ 结束阶段: {name}, 耗时: {timer.duration:.2f}s")
            
            # 收集指标
            self.collector.add_stage_metrics(timer.get_metrics())
            
        except Exception as e:
            timer.error = str(e)
            timer.end()
            
            # 收集错误指标
            self.collector.add_stage_metrics(timer.get_metrics())
            self.collector.increment_counter('errors')
            
            if self.enable_logging:
                logger.error(f"❌ 阶段失败: {name}, 错误: {e}")
            
            raise
    
    async def astage(self, name: str, stage_type: StageType = StageType.CUSTOM):
        """异步阶段计时器"""
        timer = StageTimer(name, stage_type)
        
        try:
            timer.start()
            if self.enable_logging:
                logger.debug(f"⏱️ 开始阶段(异步): {name}")
            
            yield self
            
            timer.end()
            if self.enable_logging:
                logger.debug(f"✅ 结束阶段(异步): {name}, 耗时: {timer.duration:.2f}s")
            
            # 收集指标
            self.collector.add_stage_metrics(timer.get_metrics())
            
        except Exception as e:
            timer.error = str(e)
            timer.end()
            
            # 收集错误指标
            self.collector.add_stage_metrics(timer.get_metrics())
            self.collector.increment_counter('errors')
            
            if self.enable_logging:
                logger.error(f"❌ 阶段失败(异步): {name}, 错误: {e}")
            
            raise
    
    def increment(self, counter: str, value: int = 1):
        """
        增加计数器
        
        Args:
            counter: 计数器名称
            value: 增加值
        """
        self.collector.increment_counter(counter, value)
        
        # 触发回调
        if self.callback:
            self._trigger_callback({
                'type': 'counter_update',
                'counter': counter,
                'value': value,
                'timestamp': datetime.now().isoformat()
            })
    
    def record_api_call(self, tokens_input: int = 0, tokens_output: int = 0):
        """
        记录API调用
        
        Args:
            tokens_input: 输入token数
            tokens_output: 输出token数
        """
        self.increment('api_calls')
        if tokens_input > 0:
            self.increment('tokens_input', tokens_input)
        if tokens_output > 0:
            self.increment('tokens_output', tokens_output)
    
    def record_cache_hit(self):
        """记录缓存命中"""
        self.increment('cache_hits')
    
    def record_cache_miss(self):
        """记录缓存未命中"""
        self.increment('cache_misses')
    
    def set_custom_metric(self, name: str, value: Any):
        """
        设置自定义指标
        
        Args:
            name: 指标名称
            value: 指标值
        """
        self.collector.set_custom_metric(name, value)
        
        # 触发回调
        if self.callback:
            self._trigger_callback({
                'type': 'custom_metric',
                'name': name,
                'value': value,
                'timestamp': datetime.now().isoformat()
            })
    
    def generate_report(self) -> Dict[str, Any]:
        """
        生成完整性能报告
        
        Returns:
            包含所有性能指标的字典
        """
        # 获取指标数据
        counters = self.collector.get_counters()
        stages = self.collector.get_stages()
        custom_metrics = self.collector.get_custom_metrics()
        
        # 计算总耗时
        total_duration = 0.0
        if self._start_time and self._end_time:
            total_duration = self._end_time - self._start_time
        
        # 聚合阶段数据
        stage_summary = {}
        for stage_name, stage_list in stages.items():
            if stage_list:
                total_stage_duration = sum(s.duration for s in stage_list)
                avg_duration = total_stage_duration / len(stage_list)
                success_rate = sum(1 for s in stage_list if s.success) / len(stage_list) * 100
                
                stage_summary[stage_name] = {
                    'count': len(stage_list),
                    'total_duration': round(total_stage_duration, 3),
                    'avg_duration': round(avg_duration, 3),
                    'min_duration': round(min(s.duration for s in stage_list), 3),
                    'max_duration': round(max(s.duration for s in stage_list), 3),
                    'success_rate': round(success_rate, 1)
                }
        
        # 计算缓存命中率
        total_cache_operations = counters.cache_hits + counters.cache_misses
        cache_hit_rate = 0.0
        if total_cache_operations > 0:
            cache_hit_rate = counters.cache_hits / total_cache_operations
        
        # 计算效率指标
        api_calls_per_item = 0.0
        if counters.news_items_processed > 0:
            api_calls_per_item = counters.api_calls / counters.news_items_processed
        
        tokens_per_api_call = 0.0
        if counters.api_calls > 0:
            tokens_per_api_call = (counters.tokens_input + counters.tokens_output) / counters.api_calls
        
        # 构建报告
        report = {
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'start_time': datetime.fromtimestamp(self._start_time).isoformat() if self._start_time else None,
                'end_time': datetime.fromtimestamp(self._end_time).isoformat() if self._end_time else None,
                'total_duration': round(total_duration, 3)
            },
            'summary': {
                'total_duration': round(total_duration, 3),
                'total_stages': len(stages),
                'total_api_calls': counters.api_calls,
                'total_tokens': counters.tokens_input + counters.tokens_output,
                'tokens_input': counters.tokens_input,
                'tokens_output': counters.tokens_output,
                'cache_hit_rate': round(cache_hit_rate * 100, 2),
                'total_cache_operations': total_cache_operations,
                'cache_hits': counters.cache_hits,
                'cache_misses': counters.cache_misses,
                'error_count': counters.errors,
                'news_items_processed': counters.news_items_processed
            },
            'efficiency': {
                'api_calls_per_item': round(api_calls_per_item, 3),
                'tokens_per_api_call': round(tokens_per_api_call, 2),
                'items_per_second': round(counters.news_items_processed / total_duration, 2) if total_duration > 0 else 0,
                'tokens_per_second': round((counters.tokens_input + counters.tokens_output) / total_duration, 2) if total_duration > 0 else 0
            },
            'stages': stage_summary,
            'custom_metrics': custom_metrics
        }
        
        # 触发回调
        if self.callback:
            self._trigger_callback({
                'type': 'report_generated',
                'report': report,
                'timestamp': datetime.now().isoformat()
            })
        
        return report
    
    def save_report(self, filename: Optional[str] = None) -> Path:
        """
        保存报告到文件
        
        Args:
            filename: 自定义文件名，如不指定则使用时间戳
            
        Returns:
            保存的文件路径
        """
        report = self.generate_report()
        
        # 生成文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{timestamp}.json"
        
        # 保存历史报告
        history_path = self.output_dir / "history" / filename
        history_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 同时保存为当前报告
        latest_path = self.output_dir / "performance.json"
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        # 更新趋势数据
        self._update_trends(report)
        
        if self.enable_logging:
            logger.info(f"📊 性能报告已保存: {history_path}")
        
        return history_path
    
    def compare_with_history(self, history_file: Optional[str] = None) -> Dict[str, Any]:
        """
        与历史报告对比
        
        Args:
            history_file: 历史报告文件路径，如不指定则查找最近的
            
        Returns:
            对比结果
        """
        if history_file is None:
            # 查找最近的历史报告
            history_dir = self.output_dir / "history"
            if history_dir.exists():
                files = sorted(history_dir.glob("*.json"), reverse=True)
                if len(files) > 1:
                    history_file = files[1]  # 倒数第二个(最新的是当前)
        
        if not history_file or not Path(history_file).exists():
            return {"error": "未找到可对比的历史报告文件"}
        
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception as e:
            return {"error": f"历史报告读取失败: {e}"}
        
        current = self.generate_report()
        
        comparison = {
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'current_report': current['metadata']['timestamp'],
                'compared_with': Path(history_file).name,
                'comparison_date': history['metadata']['timestamp']
            },
            'improvements': {},
            'regressions': {},
            'unchanged': {}
        }
        
        # 对比关键指标
        metrics_to_compare = [
            ('total_duration', '总耗时', 's', 'lower'),
            ('api_calls_per_item', '每新闻API调用数', '', 'lower'),
            ('cache_hit_rate', '缓存命中率', '%', 'higher'),
            ('items_per_second', '每秒处理新闻数', '个/s', 'higher')
        ]
        
        for key, label, unit, better in metrics_to_compare:
            curr_val = None
            hist_val = None
            
            # 从不同位置获取值
            if key in current['summary']:
                curr_val = current['summary'][key]
                hist_val = history['summary'].get(key, 0)
            elif key in current['efficiency']:
                curr_val = current['efficiency'][key]
                hist_val = history['efficiency'].get(key, 0)
            
            if curr_val is None or hist_val is None:
                continue
            
            if curr_val == hist_val:
                comparison['unchanged'][key] = {
                    'label': label,
                    'value': f"{curr_val}{unit}",
                    'description': f"{label}保持不变"
                }
            elif better == 'lower' and curr_val < hist_val:
                improvement = ((hist_val - curr_val) / hist_val * 100) if hist_val > 0 else 0
                comparison['improvements'][key] = {
                    'label': label,
                    'before': f"{hist_val}{unit}",
                    'after': f"{curr_val}{unit}",
                    'improvement': f"{improvement:.1f}%",
                    'description': f"{label}降低{improvement:.1f}%，性能提升"
                }
            elif better == 'higher' and curr_val > hist_val:
                improvement = ((curr_val - hist_val) / hist_val * 100) if hist_val > 0 else 0
                comparison['improvements'][key] = {
                    'label': label,
                    'before': f"{hist_val}{unit}",
                    'after': f"{curr_val}{unit}",
                    'improvement': f"{improvement:.1f}%",
                    'description': f"{label}提升{improvement:.1f}%，性能提升"
                }
            else:
                if better == 'lower':
                    regression = ((curr_val - hist_val) / hist_val * 100) if hist_val > 0 else 0
                    description = f"{label}增加{regression:.1f}%，性能下降"
                else:
                    regression = ((hist_val - curr_val) / hist_val * 100) if hist_val > 0 else 0
                    description = f"{label}降低{regression:.1f}%，性能下降"
                
                comparison['regressions'][key] = {
                    'label': label,
                    'before': f"{hist_val}{unit}",
                    'after': f"{curr_val}{unit}",
                    'regression': f"{regression:.1f}%",
                    'description': description
                }
        
        # 添加趋势分析
        if self._load_trends():
            trends = self._load_trends()
            comparison['trend_analysis'] = self._analyze_trends(trends)
        
        return comparison
    
    def _trigger_callback(self, data: Dict[str, Any]):
        """触发回调函数"""
        try:
            if self.callback:
                self.callback(data)
        except Exception as e:
            logger.warning(f"性能监控回调函数执行失败: {e}")
    
    def _update_trends(self, report: Dict[str, Any]):
        """更新趋势数据"""
        trends_path = self.output_dir / "trends.json"
        
        try:
            if trends_path.exists():
                with open(trends_path, 'r', encoding='utf-8') as f:
                    trends = json.load(f)
            else:
                trends = {
                    'records': [],
                    'summary': {
                        'total_runs': 0,
                        'average_duration': 0,
                        'best_duration': float('inf'),
                        'worst_duration': 0
                    }
                }
            
            # 添加新记录
            trends['records'].append({
                'timestamp': report['metadata']['timestamp'],
                'total_duration': report['summary']['total_duration'],
                'api_calls': report['summary']['total_api_calls'],
                'cache_hit_rate': report['summary']['cache_hit_rate'],
                'news_items': report['summary']['news_items_processed']
            })
            
            # 限制记录数量
            max_records = 100
            if len(trends['records']) > max_records:
                trends['records'] = trends['records'][-max_records:]
            
            # 更新摘要
            durations = [r['total_duration'] for r in trends['records']]
            trends['summary'] = {
                'total_runs': len(trends['records']),
                'average_duration': round(sum(durations) / len(durations), 3) if durations else 0,
                'best_duration': round(min(durations), 3) if durations else 0,
                'worst_duration': round(max(durations), 3) if durations else 0,
                'improvement_rate': self._calculate_improvement_rate(trends['records'])
            }
            
            # 保存趋势数据
            with open(trends_path, 'w', encoding='utf-8') as f:
                json.dump(trends, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.warning(f"趋势数据更新失败: {e}")
    
    def _load_trends(self) -> Optional[Dict[str, Any]]:
        """加载趋势数据"""
        trends_path = self.output_dir / "trends.json"
        
        if not trends_path.exists():
            return None
        
        try:
            with open(trends_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"趋势数据加载失败: {e}")
            return None
    
    def _analyze_trends(self, trends: Dict[str, Any]) -> Dict[str, Any]:
        """分析趋势数据"""
        if not trends or 'records' not in trends or len(trends['records']) < 2:
            return {'has_enough_data': False}
        
        records = trends['records']
        
        # 计算最近的5次运行的平均值
        recent_count = min(5, len(records))
        recent_records = records[-recent_count:]
        older_records = records[-recent_count*2:-recent_count] if len(records) >= recent_count*2 else []
        
        recent_avg = {
            'duration': sum(r['total_duration'] for r in recent_records) / recent_count,
            'api_calls': sum(r['api_calls'] for r in recent_records) / recent_count,
            'cache_hit_rate': sum(r['cache_hit_rate'] for r in recent_records) / recent_count
        }
        
        analysis = {
            'has_enough_data': True,
            'recent_performance': {
                'duration': round(recent_avg['duration'], 3),
                'api_calls': round(recent_avg['api_calls'], 1),
                'cache_hit_rate': round(recent_avg['cache_hit_rate'], 2)
            }
        }
        
        # 如果有更早的数据，计算变化趋势
        if older_records:
            older_avg = {
                'duration': sum(r['total_duration'] for r in older_records) / len(older_records),
                'api_calls': sum(r['api_calls'] for r in older_records) / len(older_records),
                'cache_hit_rate': sum(r['cache_hit_rate'] for r in older_records) / len(older_records)
            }
            
            changes = {}
            for key in ['duration', 'api_calls', 'cache_hit_rate']:
                if older_avg[key] > 0:
                    change_pct = ((recent_avg[key] - older_avg[key]) / older_avg[key]) * 100
                    changes[key] = round(change_pct, 1)
            
            analysis['trend_changes'] = changes
            
            # 判断趋势方向
            trend_direction = []
            if changes.get('duration', 0) < -5:
                trend_direction.append('性能提升（耗时减少）')
            elif changes.get('duration', 0) > 5:
                trend_direction.append('性能下降（耗时增加）')
            
            if changes.get('cache_hit_rate', 0) > 5:
                trend_direction.append('缓存效率提升')
            elif changes.get('cache_hit_rate', 0) < -5:
                trend_direction.append('缓存效率下降')
            
            if trend_direction:
                analysis['trend_summary'] = '; '.join(trend_direction)
        
        return analysis
    
    def _calculate_improvement_rate(self, records: List[Dict[str, Any]]) -> float:
        """计算改进率"""
        if len(records) < 2:
            return 0.0
        
        # 计算最近5次运行相比最早的5次运行的改进率
        recent_count = min(5, len(records))
        recent_avg = sum(r['total_duration'] for r in records[-recent_count:]) / recent_count
        
        older_count = min(5, len(records) - recent_count)
        if older_count == 0:
            return 0.0
        
        older_avg = sum(r['total_duration'] for r in records[:older_count]) / older_count
        
        if older_avg > 0:
            return round(((older_avg - recent_avg) / older_avg) * 100, 1)
        
        return 0.0


# 便捷函数
def create_monitor(
    output_dir: str = "metrics",
    enable_logging: bool = True,
    auto_save: bool = True,
    callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> PerformanceMonitor:
    """
    工厂函数，创建监控器实例
    
    Args:
        output_dir: 输出目录
        enable_logging: 是否启用日志
        auto_save: 是否自动保存
        callback: 回调函数
    
    Returns:
        PerformanceMonitor实例
    """
    return PerformanceMonitor(
        output_dir=output_dir,
        enable_logging=enable_logging,
        auto_save=auto_save,
        callback=callback
    )


# 使用示例和异步支持验证
if __name__ == "__main__":
    import asyncio
    
    # 回调函数示例
    def monitor_callback(data: Dict[str, Any]):
        """实时监控回调函数"""
        event_type = data.get('type', 'unknown')
        if event_type == 'counter_update':
            print(f"[实时监控] 计数器更新: {data.get('counter')} += {data.get('value')}")
        elif event_type == 'stage_completed':
            print(f"[实时监控] 阶段完成: {data.get('stage_name')}, 耗时: {data.get('duration', 0):.2f}s")
        elif event_type == 'report_generated':
            print(f"[实时监控] 报告生成完成")
    
    async def example_sync():
        """同步使用示例"""
        print("="*60)
        print("同步性能监控示例")
        print("="*60)
        
        # 创建监控器
        monitor = create_monitor(
            output_dir="metrics_example",
            enable_logging=True,
            auto_save=False,
            callback=monitor_callback
        )
        
        # 开始监控
        monitor.start()
        
        # 模拟各个阶段
        with monitor.stage('rss_fetch', StageType.RSS_FETCH):
            time.sleep(0.1)  # 模拟RSS抓取
            monitor.increment('news_items_processed', 50)
            monitor.record_api_call(1000, 200)
        
        with monitor.stage('ai_scoring', StageType.AI_SCORING):
            time.sleep(0.3)  # 模拟AI评分
            monitor.increment('api_calls', 25)
            monitor.record_api_call(50000, 15000)
            monitor.record_cache_hit()
            monitor.record_cache_hit()
            monitor.record_cache_miss()
            monitor.record_cache_miss()
            monitor.record_cache_miss()
        
        with monitor.stage('generate_output', StageType.GENERATE_OUTPUT):
            time.sleep(0.05)  # 模拟输出生成
        
        # 设置自定义指标
        monitor.set_custom_metric('total_news_sources', 15)
        monitor.set_custom_metric('avg_score', 7.8)
        
        # 结束监控
        monitor.end()
        
        # 生成并保存报告
        report = monitor.generate_report()
        report_path = monitor.save_report("example_report.json")
        print(f"📊 报告已保存: {report_path}")
        
        # 打印报告摘要
        print("\n性能报告摘要:")
        print(f"总耗时: {report['summary']['total_duration']:.2f}s")
        print(f"API调用: {report['summary']['total_api_calls']}次")
        print(f"Token使用: {report['summary']['total_tokens']:,}")
        print(f"缓存命中率: {report['summary']['cache_hit_rate']:.1f}%")
        print(f"处理新闻数: {report['summary']['news_items_processed']}条")
        
        # 效率指标
        print(f"\n效率指标:")
        print(f"每新闻API调用: {report['efficiency']['api_calls_per_item']:.3f}")
        print(f"每API调用Token: {report['efficiency']['tokens_per_api_call']:.0f}")
        print(f"每秒处理新闻: {report['efficiency']['items_per_second']:.2f}条/s")
        
        # 阶段详情
        print(f"\n阶段详情:")
        for name, data in report['stages'].items():
            print(f"  {name}: {data['total_duration']:.3f}s (平均{data['avg_duration']:.3f}s)")
    
    async def example_async():
        """异步使用示例"""
        print("\n" + "="*60)
        print("异步性能监控示例")
        print("="*60)
        
        # 创建监控器
        monitor = create_monitor(
            output_dir="metrics_example_async",
            enable_logging=True,
            auto_save=False
        )
        
        # 开始监控
        monitor.start()
        
        # 模拟异步阶段
        async with monitor.astage('async_processing') as m:
            await asyncio.sleep(0.2)
            m.increment('api_calls', 10)
            m.record_api_call(20000, 5000)
            m.record_cache_hit()
            m.record_cache_miss()
        
        # 多任务并发示例
        async def process_item(item_id: int):
            """模拟单个新闻处理"""
            async with monitor.astage('item_processing') as m:
                await asyncio.sleep(0.02)  # 模拟处理时间
                m.increment('news_items_processed')
                if item_id % 3 == 0:  # 1/3命中率
                    m.record_cache_hit()
                else:
                    m.record_cache_miss()
                m.record_api_call(500, 200)
        
        # 并发处理10个新闻
        tasks = [process_item(i) for i in range(10)]
        await asyncio.gather(*tasks)
        
        # 结束监控
        monitor.end()
        
        # 生成报告
        report = monitor.generate_report()
        
        # 打印摘要
        print(f"异步处理完成:")
        print(f"总耗时: {report['summary']['total_duration']:.2f}s")
        print(f"处理新闻: {report['summary']['news_items_processed']}条")
        print(f"缓存命中: {report['summary']['cache_hits']}次")
        print(f"缓存未命中: {report['summary']['cache_misses']}次")
        
        # 历史对比示例
        print("\n历史对比示例:")
        comparison = monitor.compare_with_history()
        if 'error' in comparison:
            print(f"无历史数据可对比: {comparison['error']}")
        else:
            if comparison.get('improvements'):
                print("改进的指标:")
                for key, data in comparison['improvements'].items():
                    print(f"  {data['label']}: {data['before']} → {data['after']} ({data['improvement']})")
            
            if comparison.get('regressions'):
                print("下降的指标:")
                for key, data in comparison['regressions'].items():
                    print(f"  {data['label']}: {data['before']} → {data['after']}")
            
            if comparison.get('unchanged'):
                print(f"保持不变的指标: {len(comparison['unchanged'])}项")
    
    async def main():
        """主函数"""
        await example_sync()
        await example_async()
        
        print("\n" + "="*60)
        print("性能监控系统验证完成")
        print("="*60)
        
        # 验证线程安全
        print("\n线程安全测试:")
        monitor = create_monitor(enable_logging=False)
        monitor.start()
        
        def worker(worker_id: int, iterations: int = 100):
            """多线程工作函数"""
            for i in range(iterations):
                with monitor.stage(f'worker_{worker_id}_task_{i}'):
                    time.sleep(0.001)
                monitor.increment('news_items_processed')
                if i % 5 == 0:
                    monitor.record_cache_hit()
                else:
                    monitor.record_cache_miss()
        
        # 创建多个线程同时更新指标
        threads = []
        for worker_id in range(5):
            t = threading.Thread(target=worker, args=(worker_id, 20))
            threads.append(t)
            t.start()
        
        # 等待所有线程完成
        for t in threads:
            t.join()
        
        monitor.end()
        
        # 检查计数器一致性
        report = monitor.generate_report()
        expected_items = 5 * 20  # 5个工人 * 20次迭代
        actual_items = report['summary']['news_items_processed']
        
        if actual_items == expected_items:
            print(f"✅ 线程安全测试通过: 预期{expected_items}，实际{actual_items}")
        else:
            print(f"❌ 线程安全测试失败: 预期{expected_items}，实际{actual_items}")
        
        print(f"总阶段数: {report['summary']['total_stages']}")
    
    # 运行示例
    asyncio.run(main())