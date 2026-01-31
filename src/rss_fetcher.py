"""
RSS获取模块
负责从多个RSS源获取新闻并解析
新增：语义去重(Semantic Deduplication)支持
"""
import hashlib
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List, Optional

import feedparser
from dateutil import parser as date_parser

from src.models import NewsItem, RSSSource, OutputConfig, FilterConfig

logger = logging.getLogger(__name__)

# 设置全局socket超时，防止RSS获取阻塞（10秒）
socket.setdefaulttimeout(10)


class RSSFetcher:
    """RSS获取器 - 支持语义去重"""
    
    def __init__(
        self, 
        sources: List[RSSSource], 
        output_config: OutputConfig, 
        filter_config: FilterConfig
    ):
        self.sources = sources
        self.output_config = output_config
        self.filter_config = filter_config
        self.time_window = timedelta(days=output_config.time_window_days)
        
        # 轻量级语义去重配置 (TF-IDF版，GitHub Actions友好，~10MB内存)
        self._semantic_dedup_enabled = getattr(filter_config, 'use_semantic_dedup', True)
        self._semantic_threshold = getattr(filter_config, 'semantic_similarity', 0.85)
        
        # TF-IDF向量化器 (轻量级替代sentence-transformers)
        self._vectorizer = None
        
        # 统计信息
        self.semantic_duplicates_removed = 0
    
    def _get_vectorizer(self):
        """延迟初始化TF-IDF向量化器 (轻量级，GitHub Actions友好)"""
        if self._vectorizer is None and self._semantic_dedup_enabled:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                
                logger.info("📦 初始化TF-IDF向量化器(轻量级，~10MB)...")
                # 轻量级配置，内存友好
                self._vectorizer = TfidfVectorizer(
                    max_features=500,       # 限制特征数，节省内存
                    ngram_range=(1, 2),     # 单词和双词组合
                    stop_words='english',   # 移除英文停用词
                    min_df=1,               # 最少出现1次
                    max_df=0.95,            # 忽略过于常见的词
                    lowercase=True,
                    strip_accents='unicode'
                )
                logger.info("✓ TF-IDF向量化器初始化完成 (~10MB)")
            except Exception as e:
                logger.error(f"❌ 向量化器初始化失败，禁用语义去重: {e}")
                self._semantic_dedup_enabled = False
        
        return self._vectorizer
    
    def fetch_all(self) -> List[NewsItem]:
        """
        从所有源获取新闻
        
        Returns:
            去重后的新闻列表(按发布时间倒序)
        """
        all_items = []
        
        # 使用线程池并行获取
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_source = {
                executor.submit(self._fetch_single, source): source 
                for source in self.sources
            }
            
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    items = future.result(timeout=30)
                    all_items.extend(items)
                    logger.info(f"✓ 成功从 {source.name} 获取 {len(items)} 条新闻")
                except Exception as e:
                    logger.error(f"❌ 从 {source.name} 获取失败: {e}")
        
        # 去重
        unique_items = self._deduplicate(all_items)
        
        # 按发布时间排序(最新的在前)
        unique_items.sort(key=lambda x: x.published_at, reverse=True)
        
        logger.info(
            f"📊 获取完成: 原始 {len(all_items)} 条 → "
            f"去重后 {len(unique_items)} 条 "
            f"(语义去重 {self.semantic_duplicates_removed} 条)"
        )
        return unique_items
    
    def _fetch_single(self, source: RSSSource) -> List[NewsItem]:
        """获取单个RSS源的新闻"""
        items = []
        
        try:
            # 解析RSS feed
            feed = feedparser.parse(source.url)
            
            if feed.bozo:  # 解析警告
                logger.warning(f"⚠️ {source.name} RSS解析警告: {feed.bozo_exception}")
            
            # 获取当前时间窗口
            cutoff_time = datetime.now() - self.time_window
            
            for entry in feed.entries:
                try:
                    item = self._parse_entry(entry, source)
                    
                    # 只保留时间窗口内的新闻
                    if item.published_at > cutoff_time:
                        items.append(item)
                    
                except Exception as e:
                    logger.warning(f"⚠️ 解析条目失败: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ 获取RSS源 {source.name} 失败: {e}")
            raise
        
        return items
    
    def _parse_entry(self, entry, source: RSSSource) -> NewsItem:
        """将feedparser entry解析为NewsItem"""
        # 获取标题
        title = entry.get('title', '无标题').strip()
        
        # 获取链接
        link = entry.get('link', '')
        if not link and 'links' in entry:
            for l in entry.links:
                if l.get('type') == 'text/html':
                    link = l.get('href', '')
                    break
        
        # 获取发布时间
        published = datetime.now()
        if 'published_parsed' in entry:
            published = datetime(*entry.published_parsed[:6])
        elif 'updated_parsed' in entry:
            published = datetime(*entry.updated_parsed[:6])
        elif 'published' in entry:
            try:
                published = date_parser.parse(entry.published)
            except:
                pass
        
        # 获取摘要/内容
        summary = entry.get('summary', '') or entry.get('description', '')
        content = entry.get('content', [{}])[0].get('value', '') if 'content' in entry else ''
        
        # 生成唯一ID
        id_hash = hashlib.md5(f"{link}:{title}".encode()).hexdigest()[:12]
        
        return NewsItem(
            id=id_hash,
            title=title,
            link=link,
            source=source.name,
            category=source.category,
            published_at=published,
            summary=self._clean_html(summary),
            content=self._clean_html(content)
        )
    
    def _deduplicate(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        去重 - 两阶段去重策略
        阶段1: URL + Levenshtein (快速去重)
        阶段2: 语义相似度 (精准去重，可选)
        """
        # 阶段1: 快速去重
        unique_items = self._fast_dedup(items)
        
        # 阶段2: 语义去重 (如果启用)
        if self._semantic_dedup_enabled and len(unique_items) > 1:
            logger.info(f"🔍 启动语义去重检查: {len(unique_items)} 条")
            unique_items = self._semantic_deduplicate(unique_items)
        
        return unique_items
    
    def _fast_dedup(self, items: List[NewsItem]) -> List[NewsItem]:
        """快速去重 - 基于URL和Levenshtein距离"""
        seen_urls = set()
        seen_titles = []
        unique_items = []
        
        threshold = self.filter_config.dedup_similarity
        
        for item in items:
            # URL去重
            if item.link in seen_urls:
                continue
            
            # 标题相似度去重
            is_duplicate = False
            for seen_title in seen_titles:
                similarity = self._title_similarity(item.title, seen_title)
                if similarity >= threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                seen_urls.add(item.link)
                seen_titles.append(item.title)
                unique_items.append(item)
        
        return unique_items
    
    def _semantic_deduplicate(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        轻量级语义去重 - 使用TF-IDF (GitHub Actions友好，~10MB内存)
        识别语义相似但表述不同的标题
        """
        vectorizer = self._get_vectorizer()
        if vectorizer is None:
            return items
        
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            
            # 准备文本 (标题 + 摘要前100字)
            texts = []
            for item in items:
                text = f"{item.title} {item.summary[:100]}"
                texts.append(text.lower())
            
            # TF-IDF编码 (内存友好)
            logger.info(f"🧮 TF-IDF编码 {len(texts)} 条新闻...")
            tfidf_matrix = vectorizer.fit_transform(texts)
            
            # 计算相似度矩阵
            similarity_matrix = cosine_similarity(tfidf_matrix)
            
            # 聚类去重
            unique_items = []
            processed_indices = set()
            semantic_duplicates = 0
            
            for i, item in enumerate(items):
                if i in processed_indices:
                    continue
                
                # 找到所有语义相似的新闻
                similar_indices = [
                    j for j in range(len(items))
                    if similarity_matrix[i][j] > self._semantic_threshold
                    and j != i and j not in processed_indices
                ]
                
                if similar_indices:
                    logger.debug(
                        f"🎯 TF-IDF去重: '{item.title[:40]}...' "
                        f"与 {len(similar_indices)} 条相似"
                    )
                    semantic_duplicates += len(similar_indices)
                
                # 保留第一条，标记其余为重复
                unique_items.append(item)
                processed_indices.add(i)
                processed_indices.update(similar_indices)
            
            self.semantic_duplicates_removed = semantic_duplicates
            
            logger.info(
                f"✓ TF-IDF语义去重完成: {len(items)} → {len(unique_items)} 条 "
                f"(去除 {semantic_duplicates} 条语义重复)"
            )
            
            return unique_items
            
        except Exception as e:
            logger.error(f"❌ TF-IDF语义去重失败: {e}")
            return items  # 失败时返回原始列表
    
    def _title_similarity(self, title1: str, title2: str) -> float:
        """计算两个标题的相似度(基于Levenshtein距离)"""
        title1 = title1.lower().strip()
        title2 = title2.lower().strip()
        
        if title1 == title2:
            return 1.0
        
        len1, len2 = len(title1), len(title2)
        if len1 == 0 or len2 == 0:
            return 0.0
        
        max_len = max(len1, len2)
        distance = self._levenshtein_distance(title1, title2)
        similarity = 1 - (distance / max_len)
        
        return similarity
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算Levenshtein编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def _clean_html(self, html: str) -> str:
        """简单清理HTML标签"""
        if not html:
            return ""
        # 移除script和style标签及其内容
        html = re.sub(r'<(script|style)[^>]*>[^<]*</\1>', '', html, flags=re.DOTALL)
        # 移除所有HTML标签
        html = re.sub(r'<[^>]+>', '', html)
        # 解码HTML实体
        html = html.replace('&lt;', '<').replace('&gt;', '>')
        html = html.replace('&amp;', '&').replace('&quot;', '"')
        html = html.replace('&#39;', "'").replace('&nbsp;', ' ')
        return html.strip()
    
    def get_stats(self) -> dict:
        """获取去重统计"""
        return {
            "semantic_dedup_enabled": self._semantic_dedup_enabled,
            "semantic_threshold": self._semantic_threshold,
            "semantic_duplicates_removed": self.semantic_duplicates_removed
        }
