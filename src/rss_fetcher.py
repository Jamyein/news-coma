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
from typing import Optional

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
        sources: list[RSSSource], 
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
    
    def fetch_all(self) -> list[NewsItem]:
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
    
    def _fetch_single(self, source: RSSSource, last_fetch_time: Optional[datetime] = None) -> List[NewsItem]:
        """
        获取单个RSS源的新闻（支持基于时间节点的增量获取）
        
        Args:
            source: RSS源配置
            last_fetch_time: 上次获取时间，如果为None则使用time_window_days作为fallback
        
        Returns:
            新闻列表
        """
        items = []
        
        try:
            # 解析RSS feed
            feed = feedparser.parse(source.url)
            
            if feed.bozo:  # 解析警告
                logger.warning(f"⚠️ {source.name} RSS解析警告: {feed.bozo_exception}")
            
            # 确定时间过滤阈值
            if last_fetch_time:
                # 使用上次获取时间（增量模式）
                cutoff_time = last_fetch_time
                logger.info(f"⏰ {source.name} 使用增量获取，上次时间: {cutoff_time}")
            else:
                # Fallback: 使用time_window_days（全量模式）
                cutoff_time = datetime.now() - self.time_window
                logger.info(f"⏰ {source.name} 使用全量获取，时间窗口: {self.output_config.time_window_days}天")
            
            for entry in feed.entries:
                try:
                    item = self._parse_entry(entry, source)
                    
                    # 时间过滤：只保留 cutoff_time 之后的新闻
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
                logger.debug(f"⚠️ {source.name} 条目发布时间解析失败，使用当前时间")
                pass
        
        # 边界情况处理：检查时间戳是否在未来
        if published > datetime.now():
            logger.warning(
                f"⚠️ {source.name} 条目时间在未来: {published}，使用当前时间"
            )
            published = datetime.now()
        
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
        纯语义去重 - 简化架构
        去掉低效的Levenshtein字符级去重，保留URL精确去重 + TF-IDF语义去重
        优势：更好的中文支持、更高的去重准确率、更简洁的代码
        """
        import time
        start_time = time.time()
        
        if len(items) <= 1:
            return items
        
        # 步骤1：URL精确去重（快速、轻量、必要）
        seen_urls = set()
        unique_by_url = []
        url_duplicates = 0
        
        for item in items:
            if item.link in seen_urls:
                url_duplicates += 1
                continue
            seen_urls.add(item.link)
            unique_by_url.append(item)
        
        if url_duplicates > 0:
            logger.debug(f"🔗 URL去重移除 {url_duplicates} 条")
        
        # 步骤2：语义去重（核心逻辑 - 使用TF-IDF向量化 + 余弦相似度）
        if len(unique_by_url) > 1:
            logger.info(f"🔍 语义去重: {len(unique_by_url)} 条")
            
            # 确保启用语义去重
            if not self._semantic_dedup_enabled:
                logger.warning("语义去重被禁用，启用临时向量化器")
                self._semantic_dedup_enabled = True
            
            final_items = self._semantic_deduplicate(unique_by_url)
        else:
            final_items = unique_by_url
        
        # 性能监控
        elapsed = time.time() - start_time
        total_removed = len(items) - len(final_items)
        logger.info(
            f"✅ 去重完成: {len(items)}条 → {len(final_items)}条 "
            f"(移除{total_removed}条, 耗时{elapsed:.2f}秒)"
        )
        
        return final_items
    
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
