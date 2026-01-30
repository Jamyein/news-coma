"""
RSS获取模块
负责从多个RSS源获取新闻并解析
"""
import hashlib
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import List

import feedparser
from dateutil import parser as date_parser

from src.models import NewsItem, RSSSource, OutputConfig, FilterConfig

logger = logging.getLogger(__name__)

# 设置全局socket超时，防止RSS获取阻塞（10秒）
socket.setdefaulttimeout(10)


class RSSFetcher:
    """RSS获取器"""
    
    def __init__(self, sources: List[RSSSource], output_config: OutputConfig, 
                 filter_config: FilterConfig):
        self.sources = sources
        self.output_config = output_config
        self.filter_config = filter_config
        self.time_window = timedelta(days=output_config.time_window_days)
    
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
                    logger.info(f"成功从 {source.name} 获取 {len(items)} 条新闻")
                except Exception as e:
                    logger.error(f"从 {source.name} 获取失败: {e}")
        
        # 去重
        unique_items = self._deduplicate(all_items)
        
        # 按发布时间排序(最新的在前)
        unique_items.sort(key=lambda x: x.published_at, reverse=True)
        
        logger.info(f"去重后共有 {len(unique_items)} 条新闻")
        return unique_items
    
    def _fetch_single(self, source: RSSSource) -> List[NewsItem]:
        """获取单个RSS源的新闻"""
        items = []
        
        try:
            # 解析RSS feed
            feed = feedparser.parse(source.url)
            
            if feed.bozo:  # 解析警告
                logger.warning(f"{source.name} RSS解析警告: {feed.bozo_exception}")
            
            # 获取当前时间窗口
            cutoff_time = datetime.now() - self.time_window
            
            for entry in feed.entries:
                try:
                    item = self._parse_entry(entry, source)
                    
                    # 只保留时间窗口内的新闻
                    if item.published_at > cutoff_time:
                        items.append(item)
                    
                except Exception as e:
                    logger.warning(f"解析条目失败: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"获取RSS源 {source.name} 失败: {e}")
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
        """去重(基于URL和标题相似度)"""
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
    
    def _title_similarity(self, title1: str, title2: str) -> float:
        """计算两个标题的相似度(基于Levenshtein距离)"""
        # 简单的相似度计算
        title1 = title1.lower().strip()
        title2 = title2.lower().strip()
        
        if title1 == title2:
            return 1.0
        
        # 计算Levenshtein距离
        len1, len2 = len(title1), len(title2)
        if len1 == 0 or len2 == 0:
            return 0.0
        
        # 使用简单的编辑距离
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
        import re
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
