"""
历史数据管理模块
负责管理已处理的新闻URL、统计数据和AI评分缓存
"""
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Set, Dict, Any, Optional
from pathlib import Path

from src.models import NewsItem

logger = logging.getLogger(__name__)


class HistoryManager:
    """历史数据管理器 - 扩展AI评分缓存功能"""
    
    def __init__(self, history_path: str = "data/history.json", cache_ttl_hours: int = 24):
        self.history_path = Path(history_path)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._data = self._load()
        
        # 确保AI缓存字段存在
        if "ai_cache" not in self._data:
            self._data["ai_cache"] = {}
        if "cache_hits" not in self._data:
            self._data["cache_hits"] = 0
        if "cache_lookups" not in self._data:
            self._data["cache_lookups"] = 0
        if "run_metrics" not in self._data:
            self._data["run_metrics"] = []
    
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
            "source_stats": {},
            "ai_cache": {},
            "cache_hits": 0,
            "cache_lookups": 0,
            "run_metrics": []
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
    
    # ==================== AI评分缓存功能 (新增) ====================
    
    def _generate_content_fingerprint(self, item: NewsItem) -> str:
        """
        生成新闻内容指纹 (用于缓存键)
        使用标题+摘要前200字符+来源生成MD5哈希
        """
        content = f"{item.title}:{item.summary[:200]}:{item.source}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]
    
    def get_ai_score_from_cache(self, item: NewsItem) -> Optional[Dict[str, Any]]:
        """
        从缓存获取AI评分结果
        
        Args:
            item: 新闻条目
            
        Returns:
            如果缓存命中且未过期，返回包含ai_score等字段的字典
            否则返回None
        """
        fingerprint = self._generate_content_fingerprint(item)
        cached = self._data["ai_cache"].get(fingerprint)
        
        if not cached:
            return None
        
        # 检查是否过期
        try:
            cached_time = datetime.fromisoformat(cached.get('cached_at', '2000-01-01T00:00:00'))
            if datetime.now() - cached_time > self.cache_ttl:
                # 过期，删除缓存
                del self._data["ai_cache"][fingerprint]
                return None
        except (ValueError, KeyError):
            # 时间格式错误，视为过期
            del self._data["ai_cache"][fingerprint]
            return None
        
        self._data["cache_hits"] = self._data.get("cache_hits", 0) + 1
        logger.debug(f"AI缓存命中: {item.title[:50]}...")
        return cached
    
    def save_ai_score_to_cache(self, item: NewsItem) -> bool:
        """
        缓存AI评分结果
        
        Args:
            item: 已评分的新闻条目
            
        Returns:
            是否成功缓存
        """
        if item.ai_score is None:
            return False
        
        fingerprint = self._generate_content_fingerprint(item)
        self._data["ai_cache"][fingerprint] = {
            'ai_score': item.ai_score,
            'translated_title': item.translated_title,
            'ai_summary': item.ai_summary,
            'key_points': item.key_points if item.key_points else [],
            'cached_at': datetime.now().isoformat(),
            'source': item.source
        }
        return True
    
    def record_cache_lookup(self):
        """记录缓存查询次数"""
        self._data["cache_lookups"] = self._data.get("cache_lookups", 0) + 1
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total = len(self._data.get("ai_cache", {}))
        hits = self._data.get("cache_hits", 0)
        lookups = self._data.get("cache_lookups", 1)
        
        # 计算过期条目
        expired = 0
        now = datetime.now()
        for fingerprint, cached in list(self._data.get("ai_cache", {}).items()):
            try:
                cached_time = datetime.fromisoformat(cached.get('cached_at', '2000-01-01T00:00:00'))
                if now - cached_time > self.cache_ttl:
                    expired += 1
            except:
                expired += 1
        
        return {
            'total_cached': total,
            'expired_entries': expired,
            'cache_hits': hits,
            'cache_lookups': lookups,
            'hit_rate': hits / max(lookups, 1),
            'hit_rate_percent': f"{hits / max(lookups, 1) * 100:.1f}%"
        }
    
    def clear_expired_cache(self) -> int:
        """清理过期的AI评分缓存"""
        now = datetime.now()
        expired_keys = []
        
        for fingerprint, cached in list(self._data.get("ai_cache", {}).items()):
            try:
                cached_time = datetime.fromisoformat(cached.get('cached_at', '2000-01-01T00:00:00'))
                if now - cached_time > self.cache_ttl:
                    expired_keys.append(fingerprint)
            except:
                expired_keys.append(fingerprint)
        
        for key in expired_keys:
            del self._data["ai_cache"][key]
        
        if expired_keys:
            logger.info(f"清理 {len(expired_keys)} 条过期AI缓存")
        
        return len(expired_keys)
    
    # ==================== 原有统计功能 (保持不变) ====================
    
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
            "duplicates_removed": kwargs.get("duplicates_removed", 0),
            "semantic_duplicates": kwargs.get("semantic_duplicates", 0),
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
    
    def get_processed_urls(self) -> Set[str]:
        """获取已处理URL集合"""
        return set(self._data.get("processed_urls", []))
    
    # ==================== 性能报告功能 (新增) ====================
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        获取性能报告
        
        Returns:
            包含最近运行指标的字典
        """
        metrics = self._data.get("run_metrics", [])
        
        if not metrics:
            return {"message": "暂无运行数据", "total_runs": self._data["stats"]["total_runs"]}
        
        # 使用最近10次运行数据
        recent_metrics = metrics[-10:]
        
        total_api_calls = sum(m.get("api_calls", 0) for m in recent_metrics)
        total_cache_hits = sum(m.get("cache_hits", 0) for m in recent_metrics)
        total_cache_lookups = sum(m.get("cache_hits", 0) + m.get("cache_misses", 0) for m in recent_metrics)
        total_duration = sum(m.get("duration_seconds", 0) for m in recent_metrics)
        total_duplicates = sum(m.get("duplicates_removed", 0) for m in recent_metrics)
        
        n = len(recent_metrics)
        
        # 估算成本 (基于平均token数)
        # 单次API调用成本约$0.0002-0.001 (取决于模型和token数)
        avg_cost_per_call = 0.0005  # 保守估算
        estimated_cost = total_api_calls * avg_cost_per_call
        
        return {
            "recent_runs": n,
            "avg_api_calls_per_run": total_api_calls / n,
            "avg_cache_hit_rate": total_cache_hits / max(total_cache_lookups, 1),
            "avg_duration_seconds": total_duration / n,
            "total_duplicates_removed": total_duplicates,
            "estimated_cost_per_run": estimated_cost / n,
            "estimated_cost_per_run_usd": f"${estimated_cost / n:.4f}",
            "cache_stats": self.get_cache_stats(),
            "total_runs_all_time": self._data["stats"]["total_runs"],
            "total_news_processed_all_time": self._data["stats"]["total_news_processed"],
        }
    
    def clear_old_entries(self, keep_days: int = 30):
        """清理旧的历史记录(可选)"""
        # 这里可以实现定期清理逻辑
        pass
