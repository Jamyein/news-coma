"""
RSS订阅文件生成模块
负责基于Markdown文件生成RSS feed.xml文件
"""
import logging
import os
import re
from datetime import datetime
from typing import List, Dict
from xml.sax.saxutils import escape
from pathlib import Path

logger = logging.getLogger(__name__)


class RSSGenerator:
    """基于Markdown文件的RSS订阅文件生成器"""
    
    def __init__(self, feed_path: str = "feed.xml", archive_dir: str = "archive", 
                 docs_dir: str = "docs", max_items: int = 50):
        self.feed_path = Path(feed_path)
        self.archive_dir = Path(archive_dir)
        self.docs_dir = Path(docs_dir)
        self.max_items = max_items
    
    def generate(self) -> str:
        """
        基于Markdown文件生成RSS feed.xml
        
        Returns:
            生成的RSS XML字符串
        """
        # 收集所有Markdown文件
        markdown_files = self._collect_markdown_files()
        
        # 解析文件信息
        file_infos = []
        for file_path in markdown_files:
            try:
                file_info = self._parse_markdown_file(file_path)
                if file_info:
                    file_infos.append(file_info)
            except Exception as e:
                logger.warning(f"解析Markdown文件失败 {file_path}: {e}")
        
        # 按日期排序(最新的在前)
        file_infos.sort(key=lambda x: x.get('date', datetime.min), reverse=True)
        
        # 限制数量
        file_infos = file_infos[:self.max_items]
        
        # 生成XML
        rss_xml = self._build_rss_xml(file_infos)
        
        # 写入文件
        self.feed_path.write_text(rss_xml, encoding='utf-8')
        logger.info(f"已更新RSS feed: {self.feed_path} ({len(file_infos)} 个文件)")
        
        return rss_xml
    
    def _collect_markdown_files(self) -> List[Path]:
        """收集archive和docs目录中的所有Markdown文件"""
        markdown_files = []
        
        # 收集archive目录中的文件
        if self.archive_dir.exists():
            for file_path in self.archive_dir.glob("*.md"):
                markdown_files.append(file_path)
        
        # 收集docs目录中的文件(latest.md)
        if self.docs_dir.exists():
            latest_file = self.docs_dir / "latest.md"
            if latest_file.exists():
                markdown_files.append(latest_file)
        
        logger.info(f"找到 {len(markdown_files)} 个Markdown文件")
        return markdown_files
    
    def _parse_markdown_file(self, file_path: Path) -> Dict:
        """解析Markdown文件，提取信息"""
        if not file_path.exists():
            return None
        
        content = file_path.read_text(encoding='utf-8')
        
        # 提取日期
        date_match = None
        if file_path.name == "latest.md":
            # latest.md: 从更新时间提取日期
            date_match = re.search(r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日', content)
        else:
            # 归档文件: 从文件名提取日期 (YYYY-MM-DD.md)
            date_match = re.match(r'(\d{4})-(\d{2})-(\d{2})\.md$', file_path.name)
        
        file_date = None
        if date_match:
            if file_path.name == "latest.md":
                year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                file_date = datetime(year, month, day)
            else:
                year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                file_date = datetime(year, month, day)
        
        # 提取新闻数量
        news_count = 0
        count_match = re.search(r'本期精选\s*\*\*(\d+)\*\*\s*条', content)
        if count_match:
            news_count = int(count_match.group(1))
        
        # 构建标题
        if file_date:
            title = f"{file_date.strftime('%Y年%m月%d日')} 新闻汇总"
        else:
            title = f"{file_path.stem} 新闻汇总"
        
        # 构建链接
        repo_url = os.getenv('GITHUB_REPOSITORY', 'username/news')
        username, repo = repo_url.split('/') if '/' in repo_url else ('username', 'news')
        
        # 将Windows路径转换为POSIX路径用于URL
        file_path_posix = str(file_path).replace('\\', '/')
        
        if file_path.name == "latest.md":
            # latest.md 使用GitHub Pages URL
            link = f"https://{username}.github.io/{repo}/"
        else:
            # 归档文件使用GitHub raw URL
            link = f"https://raw.githubusercontent.com/{username}/{repo}/main/{file_path_posix}"
        
        # 构建描述
        description = f"本期精选 {news_count} 条高质量科技新闻"
        
        # 使用文件修改时间作为发布时间
        pub_date = datetime.fromtimestamp(file_path.stat().st_mtime)
        
        # 使用文件路径作为唯一guid（POSIX格式）
        guid = file_path_posix
        
        return {
            'title': title,
            'link': link,
            'description': description,
            'date': file_date or pub_date,
            'pub_date': self._format_rfc822(pub_date),
            'guid': guid,
            'file_path': str(file_path),
            'news_count': news_count
        }
    
    def _build_rss_xml(self, file_infos: List[Dict]) -> str:
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
        for file_info in file_infos:
            items_xml.append(self._build_item_xml(file_info))
        
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
    
    def _build_item_xml(self, file_info: Dict) -> str:
        """构建单个item XML"""
        title = escape(file_info.get('title', ''))
        link = file_info.get('link', '')
        description = escape(file_info.get('description', ''))
        pub_date = file_info.get('pub_date', '')
        guid = escape(file_info.get('guid', ''))
        
        return f"""
    <item>
        <title>{title}</title>
        <link>{link}</link>
        <description>{description}</description>
        <pubDate>{pub_date}</pubDate>
        <guid>{guid}</guid>
        <category>科技新闻</category>
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
