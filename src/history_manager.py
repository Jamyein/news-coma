"""
历史数据管理模块
负责管理已处理的新闻URL和统计数据
"""
import json
import logging
from datetime import datetime
from typing import List, Set, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class HistoryManager:
    """历史数据管理器"""
    
    def __init__(self, history_path: str = "data/history.json"):
        self.history_path = Path(history_path)
        self._data = self._load()
    
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
            "processed_urls": [],
            "stats": {
                "total_runs": 0,
                "total_news_processed": 0,
                "avg_news_per_run": 0
            },
            "source_stats": {}
        }
    
    def save(self):
        """保存历史数据"""
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存历史数据失败: {e}")
    
    def is_processed(self, url: str) -> bool:
        """检查URL是否已处理"""
        return url in self._data.get("processed_urls", [])
    
    def add_processed(self, url: str):
        """添加已处理URL"""
        if url not in self._data["processed_urls"]:
            self._data["processed_urls"].append(url)
            # 限制历史记录数量(保留最近1000条)
            if len(self._data["processed_urls"]) > 1000:
                self._data["processed_urls"] = self._data["processed_urls"][-1000:]
    
    def update_stats(self, run_time: datetime, news_count: int, source_stats: Dict[str, int]):
        """更新统计信息"""
        stats = self._data["stats"]
        stats["total_runs"] += 1
        stats["total_news_processed"] += news_count
        
        # 计算平均值
        if stats["total_runs"] > 0:
            stats["avg_news_per_run"] = round(
                stats["total_news_processed"] / stats["total_runs"], 1
            )
        
        # 更新源统计
        for source, count in source_stats.items():
            if source not in self._data["source_stats"]:
                self._data["source_stats"][source] = {"fetched": 0, "selected": 0}
            self._data["source_stats"][source]["fetched"] += count
        
        self._data["last_run"] = run_time.isoformat()
    
    def update_source_selected(self, source_name: str, count: int):
        """更新源选中统计"""
        if source_name not in self._data["source_stats"]:
            self._data["source_stats"][source_name] = {"fetched": 0, "selected": 0}
        self._data["source_stats"][source_name]["selected"] += count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._data["stats"]
    
    def get_processed_urls(self) -> Set[str]:
        """获取已处理URL集合"""
        return set(self._data.get("processed_urls", []))
    
    def clear_old_entries(self, keep_days: int = 30):
        """清理旧的历史记录(可选)"""
        # 这里可以实现定期清理逻辑
        pass
