"""
历史数据管理模块
负责管理已处理的新闻URL、统计数据和AI评分缓存
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Set, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class HistoryManager:
    """历史数据管理器 - 扩展AI评分缓存功能"""
    
    def __init__(self, history_path: str = "data/history.json"):
        self.history_path = Path(history_path)
        self._data = self._load()

        # 确保run_metrics字段存在
        if "run_metrics" not in self._data:
            self._data["run_metrics"] = []
        # 确保RSS源最后获取时间字段存在（增量获取支持）
        if "source_last_fetch" not in self._data:
            self._data["source_last_fetch"] = {}
    
    def _load(self) -> Dict[str, Any]:
        """加载历史数据"""
        if self.history_path.exists():
            try:
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载历史数据失败: {e}")
        
        # 返回默认结构
        return {
            "last_run": None,
            "stats": {
                "total_runs": 0,
                "total_news_processed": 0,
                "avg_news_per_run": 0
            },
            "source_stats": {},
            "run_metrics": [],
            "source_last_fetch": {}  # RSS源最后获取时间（增量获取支持）
        }
    
    def save(self):
        """保存历史数据"""
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史数据失败: {e}")
    
    # ==================== 原有统计功能 ====================
    
    def update_stats(
        self, 
        run_time: datetime, 
        news_count: int, 
        source_stats: Dict[str, int],
        **kwargs
    ):
        """
        更新统计信息 - 扩展支持详细运行指标
        
        Args:
            run_time: 运行时间
            news_count: 新闻数量
            source_stats: 源统计
            **kwargs: 额外的运行指标(api_calls, cache_hits, duration等)
        """
        stats = self._data["stats"]
        stats["total_runs"] += 1
        stats["total_news_processed"] += news_count
        
        # 计算平均值
        if stats["total_runs"] > 0:
            stats["avg_news_per_run"] = round(
                stats["total_news_processed"] / stats["total_runs"], 1
            )
        
        # 更新源统计
        if "source_stats" not in self._data:
            self._data["source_stats"] = {}
        
        for source, count in source_stats.items():
            if source not in self._data["source_stats"]:
                self._data["source_stats"][source] = {"fetched": 0, "selected": 0}
            self._data["source_stats"][source]["fetched"] += count
        
        self._data["last_run"] = run_time.isoformat()
        
        # 记录本次运行的详细指标(新增)
        run_metric = {
            "run_time": run_time.isoformat(),
            "news_count": news_count,
            "api_calls": kwargs.get("api_calls", 0),
            "cache_hits": kwargs.get("cache_hits", 0),
            "cache_misses": kwargs.get("cache_misses", 0),
            "duration_seconds": kwargs.get("duration_seconds", 0),
            "avg_score": kwargs.get("avg_score", 0),
        }
        
        if "run_metrics" not in self._data:
            self._data["run_metrics"] = []
        
        self._data["run_metrics"].append(run_metric)
        
        # 只保留最近100次运行的详细指标
        if len(self._data["run_metrics"]) > 100:
            self._data["run_metrics"] = self._data["run_metrics"][-100:]
    
    def update_source_selected(self, source_name: str, count: int):
        """更新源选中统计"""
        if "source_stats" not in self._data:
            self._data["source_stats"] = {}
        
        if source_name not in self._data["source_stats"]:
            self._data["source_stats"][source_name] = {"fetched": 0, "selected": 0}
        self._data["source_stats"][source_name]["selected"] += count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._data["stats"]
    
    # ==================== 性能报告功能 ====================
    
    def get_performance_report(self) -> Dict[str, Any]:
        """获取性能报告（简化版）"""
        metrics = self._data.get("run_metrics", [])
        if not metrics:
            return {"message": "暂无运行数据"}
        
        # 取最近10次运行数据
        recent = metrics[-10:]
        n = len(recent)
        
        total_api = sum(m.get("api_calls", 0) for m in recent)
        total_duration = sum(m.get("duration_seconds", 0) for m in recent)
        
        return {
            "recent_runs": n,
            "avg_api_calls": total_api / n if n > 0 else 0,
            "avg_duration": total_duration / n if n > 0 else 0,
            "total_runs": self._data["stats"]["total_runs"],
        }
    
    def clear_old_entries(self, keep_days: int = 30):
        """清理旧的历史记录(可选)"""
        # 这里可以实现定期清理逻辑
        pass
    
    # ==================== RSS源最后获取时间 (增量获取支持) ====================
    
    def get_source_last_fetch(self, source_name: str) -> Optional[datetime]:
        """获取指定RSS源的最后获取时间"""
        last_fetch_str = self._data.get("source_last_fetch", {}).get(source_name)
        if last_fetch_str:
            try:
                return datetime.fromisoformat(last_fetch_str)
            except ValueError:
                pass
        return None
    
    def update_source_last_fetch(self, source_name: str, fetch_time: datetime):
        """更新指定RSS源的最后获取时间"""
        self._data.setdefault("source_last_fetch", {})[source_name] = fetch_time.isoformat()
    
    def get_fallback_last_fetch(self) -> Optional[datetime]:
        """获取fallback最后获取时间（向后兼容）"""
        last_run = self._data.get("last_run")
        if last_run:
            try:
                return datetime.fromisoformat(last_run)
            except ValueError:
                pass
        return None
