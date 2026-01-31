"""
RSS订阅文件生成模块
负责生成和更新RSS feed.xml文件
"""
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict
from xml.sax.saxutils import escape
from pathlib import Path

from src.models import NewsItem

logger = logging.getLogger(__name__)


class RSSGenerator:
    """RSS订阅文件生成器"""
    
    def __init__(self, feed_path: str = "feed.xml", max_items: int = 50):
        self.feed_path = Path(feed_path)
        self.max_items = max_items
    
    def generate(self, items: List[NewsItem]) -> str:
        """
        生成RSS feed.xml
        
        Args:
            items: 新闻列表
            
        Returns:
            生成的RSS XML字符串
        """
        # 读取现有feed(如果有)
        existing_items = self._load_existing_feed()
        
        # 合并新旧条目
        merged_items = self._merge_items(items, existing_items)
        
        # 限制数量
        merged_items = merged_items[:self.max_items]
        
        # 生成XML
        rss_xml = self._build_rss_xml(merged_items)
        
        # 写入文件
        self.feed_path.write_text(rss_xml, encoding='utf-8')
        logger.info(f"已更新RSS feed: {self.feed_path} ({len(merged_items)} 条)")
        
        return rss_xml
    
    def _load_existing_feed(self) -> List[Dict]:
        """从现有feed.xml加载条目"""
        items = []
        
        if not self.feed_path.exists():
            return items
        
        try:
            tree = ET.parse(self.feed_path)
            root = tree.getroot()
            channel = root.find('channel')
            
            if channel is not None:
                for item_elem in channel.findall('item'):
                    item = {
                        'title': self._get_text(item_elem, 'title'),
                        'link': self._get_text(item_elem, 'link'),
                        'description': self._get_text(item_elem, 'description'),
                        'pub_date': self._get_text(item_elem, 'pubDate'),
                        'guid': self._get_text(item_elem, 'guid'),
                        'category': self._get_text(item_elem, 'category')
                    }
                    items.append(item)
                    
        except Exception as e:
            logger.warning(f"读取现有feed失败: {e}")
        
        return items
    
    def _get_text(self, elem: ET.Element, tag: str) -> str:
        """安全获取XML元素文本"""
        child = elem.find(tag)
        return child.text if child is not None else ""
    
    def _merge_items(self, new_items: List[NewsItem], existing: List[Dict]) -> List[Dict]:
        """合并新旧条目，去重"""
        # 新条目转换为dict格式
        new_dicts = []
        seen_guids = set()
        
        for item in new_items:
            guid = item.link
            if guid not in seen_guids:
                seen_guids.add(guid)
                new_dicts.append({
                    'title': item.translated_title or item.title,
                    'link': item.link,
                    'description': item.ai_summary or '',
                    'pub_date': self._format_rfc822(item.published_at),
                    'guid': guid,
                    'category': item.category
                })
        
        # 合并现有条目(排除重复的)
        for existing_item in existing:
            if existing_item['guid'] not in seen_guids:
                seen_guids.add(existing_item['guid'])
                new_dicts.append(existing_item)
        
        return new_dicts
    
    def _build_rss_xml(self, items: List[Dict]) -> str:
        """构建RSS 2.0 XML"""
        now = datetime.utcnow()
        build_date = self._format_rfc822(now)
        
        # 获取GitHub仓库信息(从环境变量或配置文件)
        repo_url = os.getenv('GITHUB_REPOSITORY', 'username/news')
        username, repo = repo_url.split('/') if '/' in repo_url else ('username', 'news')
        
        feed_url = f"https://{username}.github.io/{repo}/feed.xml"
        project_url = f"https://github.com/{username}/{repo}"
        
        # 构建items XML
        items_xml = []
        for item in items:
            items_xml.append(self._build_item_xml(item))
        
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
    <title>科技新闻精选</title>
    <link>{project_url}</link>
    <description>由 AI 筛选的高质量科技新闻聚合，每6小时自动更新</description>
    <language>zh-CN</language>
    <lastBuildDate>{build_date}</lastBuildDate>
    <pubDate>{build_date}</pubDate>
    <atom:link href="{feed_url}" rel="self" type="application/rss+xml" />
    <image>
        <url>https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png</url>
        <title>科技新闻精选</title>
        <link>{project_url}</link>
    </image>
{''.join(items_xml)}
</channel>
</rss>"""
        
        return rss
    
    def _build_item_xml(self, item: Dict) -> str:
        """构建单个item XML"""
        title = escape(item.get('title', ''))
        link = item.get('link', '')
        description = escape(item.get('description', ''))
        pub_date = item.get('pub_date', '')
        guid = item.get('guid', link)
        category = escape(item.get('category', '科技'))
        
        return f"""
    <item>
        <title>{title}</title>
        <link>{link}</link>
        <description>{description}</description>
        <pubDate>{pub_date}</pubDate>
        <guid isPermaLink="true">{guid}</guid>
        <category>{category}</category>
    </item>"""
    
    def _format_rfc822(self, dt: datetime) -> str:
        """格式化为RFC822日期格式"""
        # 使用英文月份缩写
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        day_name = days[dt.weekday()]
        month_name = months[dt.month - 1]
        
        return f"{day_name}, {dt.day:02d} {month_name} {dt.year} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} GMT"
