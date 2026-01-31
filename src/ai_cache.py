"""
AI评分缓存模块
实现智能缓存管理，减少重复API调用
"""
import hashlib
import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import os

from src.models import NewsItem

logger = logging.getLogger(__name__)


class AICache:
    """AI评分缓存管理器"""
    
    def __init__(
        self, 
        cache_dir: str = ".cache/ai_scores", 
        max_size: int = 10000,
        max_age_days: int = 30
    ):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录路径
            max_size: 最大缓存条目数
            max_age_days: 缓存最大有效期（天）
        """
        self.cache_dir = Path(cache_dir)
        self.max_size = max_size
        self.max_age_days = max_age_days
        
        # 缓存统计
        self._hits = 0
        self._misses = 0
        
        # 缓存索引（内存加速）
        self._index: Dict[str, Dict[str, Any]] = {}  # cache_key -> {path, accessed_at, created_at}
        
        # 线程池用于文件IO操作
        self._executor = ThreadPoolExecutor(max_workers=2)
        
        # 初始化缓存目录
        self._ensure_cache_dir()
        
        # 加载现有缓存索引
        self._load_index()
        
        logger.info(f"AICache初始化完成: 目录={self.cache_dir}, 最大条目={max_size}, 有效期={max_age_days}天")
    
    def _ensure_cache_dir(self) -> None:
        """确保缓存目录存在"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_key(self, item: NewsItem) -> str:
        """
        生成缓存键
        
        基于标题和前200字符摘要的MD5哈希
        """
        content = f"{item.title}{item.summary[:200]}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"
    
    def _load_index(self) -> None:
        """加载缓存索引"""
        index_path = self.cache_dir / "index.json"
        
        if not index_path.exists():
            self._index = {}
            return
        
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)
            
            logger.debug(f"加载缓存索引: {len(self._index)} 个条目")
            
        except Exception as e:
            logger.warning(f"加载缓存索引失败: {e}")
            self._index = {}
    
    def _save_index(self) -> None:
        """保存缓存索引"""
        index_path = self.cache_dir / "index.json"
        
        try:
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"保存缓存索引: {len(self._index)} 个条目")
            
        except Exception as e:
            logger.error(f"保存缓存索引失败: {e}")
    
    def _load_cache_file(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """加载单个缓存文件"""
        cache_path = self._get_cache_path(cache_key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
            
        except Exception as e:
            logger.warning(f"加载缓存文件失败: {cache_path}, 错误: {e}")
            return None
    
    def _save_cache_file(self, cache_key: str, data: Dict[str, Any]) -> None:
        """保存缓存文件"""
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"保存缓存文件失败: {cache_path}, 错误: {e}")
    
    def _update_index_access(self, cache_key: str) -> None:
        """更新索引访问时间"""
        if cache_key in self._index:
            self._index[cache_key]['accessed_at'] = datetime.now().isoformat()
    
    def _add_to_index(self, cache_key: str) -> None:
        """添加新条目到索引"""
        now = datetime.now().isoformat()
        self._index[cache_key] = {
            'path': f"{cache_key}.json",
            'accessed_at': now,
            'created_at': now
        }
        
        # 检查是否需要淘汰（在保存索引前）
        if len(self._index) > self.max_size:
            self._evict_lru()
        
        # 保存索引
        self._save_index()
    
    def _evict_lru(self) -> None:
        """执行LRU淘汰"""
        if not self._index:
            return
        
        # 按访问时间排序，淘汰最旧的
        sorted_items = sorted(
            self._index.items(),
            key=lambda x: x[1]['accessed_at']
        )
        
        # 淘汰前10%（但至少1个）
        num_to_evict = max(1, len(self._index) // 10)
        
        for cache_key, _ in sorted_items[:num_to_evict]:
            self._remove_cache_item(cache_key)
            logger.debug(f"LRU淘汰: {cache_key}")
        
        logger.info(f"LRU淘汰完成: 移除了 {num_to_evict} 个条目")
    
    def _remove_cache_item(self, cache_key: str) -> None:
        """移除缓存条目"""
        # 从索引中删除
        if cache_key in self._index:
            del self._index[cache_key]
        
        # 删除文件
        cache_path = self._get_cache_path(cache_key)
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception as e:
                logger.warning(f"删除缓存文件失败: {cache_path}, 错误: {e}")
    
    def get(self, item: NewsItem) -> Optional[NewsItem]:
        """
        获取缓存的评分结果
        
        Args:
            item: 新闻条目
            
        Returns:
            如果找到缓存，返回完整的NewsItem，否则返回None
        """
        cache_key = self._get_cache_key(item)
        
        # 检查索引
        if cache_key not in self._index:
            self._misses += 1
            return None
        
        # 检查缓存是否过期
        index_entry = self._index[cache_key]
        created_at = datetime.fromisoformat(index_entry['created_at'])
        if datetime.now() - created_at > timedelta(days=self.max_age_days):
            self._misses += 1
            self._remove_cache_item(cache_key)
            return None
        
        # 加载缓存数据
        cache_data = self._load_cache_file(cache_key)
        if not cache_data:
            self._misses += 1
            self._remove_cache_item(cache_key)
            return None
        
        # 更新访问时间
        self._update_index_access(cache_key)
        self._hits += 1
        
        # 创建带缓存数据的NewsItem副本
        cached_item = NewsItem(
            id=item.id,
            title=item.title,
            link=item.link,
            source=item.source,
            category=item.category,
            published_at=item.published_at,
            summary=item.summary,
            content=item.content
        )
        
        # 填充AI评分字段
        cached_item.ai_score = cache_data.get('ai_score')
        cached_item.ai_summary = cache_data.get('ai_summary')
        cached_item.translated_title = cache_data.get('translated_title')
        cached_item.key_points = cache_data.get('key_points', [])
        
        logger.debug(f"缓存命中: {cache_key} ({item.title[:50]}...)")
        return cached_item
    
    def set(self, item: NewsItem) -> None:
        """
        保存评分结果到缓存
        
        Args:
            item: 包含AI评分结果的新闻条目
        """
        if not item.ai_score:
            logger.debug(f"跳过缓存（无AI评分）: {item.title[:50]}...")
            return
        
        cache_key = self._get_cache_key(item)
        
        # 准备缓存数据
        cache_data = {
            'ai_score': item.ai_score,
            'ai_summary': item.ai_summary,
            'translated_title': item.translated_title,
            'key_points': item.key_points,
            'cached_at': datetime.now().isoformat(),
            'source_title': item.title,
            'source_summary': item.summary[:500] if item.summary else ''
        }
        
        # 保存缓存文件
        self._save_cache_file(cache_key, cache_data)
        
        # 更新索引
        if cache_key not in self._index:
            self._add_to_index(cache_key)
        else:
            self._update_index_access(cache_key)
        
        # 定期保存索引（每100次操作）
        if (self._hits + self._misses) % 100 == 0:
            self._save_index()
        
        logger.debug(f"缓存保存: {cache_key} ({item.title[:50]}...)")
    
    async def set_async(self, item: NewsItem) -> None:
        """异步保存到缓存"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, lambda: self.set(item))
    
    async def get_async(self, item: NewsItem) -> Optional[NewsItem]:
        """异步获取缓存"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, lambda: self.get(item))
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_operations = self._hits + self._misses
        hit_rate = self._hits / total_operations if total_operations > 0 else 0
        
        return {
            'size': len(self._index),
            'hits': self._hits,
            'misses': self._misses,
            'hit_rate': round(hit_rate * 100, 2),
            'max_size': self.max_size,
            'max_age_days': self.max_age_days
        }
    
    def cleanup(self, max_age_days: Optional[int] = None) -> int:
        """
        清理过期缓存
        
        Args:
            max_age_days: 覆盖默认的最大有效期
            
        Returns:
            清理的条目数
        """
        cleanup_days = max_age_days or self.max_age_days
        cutoff_date = datetime.now() - timedelta(days=cleanup_days)
        
        removed_count = 0
        
        # 找出过期的条目
        to_remove = []
        for cache_key, entry in self._index.items():
            created_at = datetime.fromisoformat(entry['created_at'])
            if created_at < cutoff_date:
                to_remove.append(cache_key)
        
        # 移除过期条目
        for cache_key in to_remove:
            self._remove_cache_item(cache_key)
            removed_count += 1
        
        if removed_count > 0:
            self._save_index()
            logger.info(f"缓存清理完成: 移除了 {removed_count} 个过期条目（>{cleanup_days}天）")
        
        return removed_count
    
    def clear_all(self) -> int:
        """清除所有缓存，返回清除的条目数"""
        count = len(self._index)
        
        # 删除所有缓存文件
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                if cache_file.name != "index.json":
                    cache_file.unlink()
            except Exception as e:
                logger.warning(f"删除缓存文件失败: {cache_file}, 错误: {e}")
        
        # 清空索引
        self._index.clear()
        self._save_index()
        
        # 重置统计
        self._hits = 0
        self._misses = 0
        
        logger.info(f"缓存已全部清除: {count} 个条目")
        return count
    
    def __del__(self):
        """析构函数，清理资源"""
        self._executor.shutdown(wait=False)
        self._save_index()
    
    def __len__(self) -> int:
        """返回缓存条目数"""
        return len(self._index)