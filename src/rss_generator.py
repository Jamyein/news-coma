"""
RSS订阅文件生成模块
负责基于Markdown文件生成RSS feed.xml文件
"""
import logging
import os
import re
from datetime import datetime

from xml.sax.saxutils import escape
from pathlib import Path

logger = logging.getLogger(__name__)


class RSSGenerator:
    """基于Markdown文件的RSS订阅文件生成器"""
    
    def __init__(self, feed_path: str = "feed.xml", archive_dir: str = "archive", 
                 docs_dir: str = "docs", max_items: int = 50, use_smart_switch: bool = True):
        self.feed_path = Path(feed_path)
        self.archive_dir = Path(archive_dir)
        self.docs_dir = Path(docs_dir)
        self.max_items = max_items
        self.use_smart_switch = use_smart_switch
    
    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        将Markdown文本转换为HTML
        
        Args:
            markdown_text: Markdown格式的文本
            
        Returns:
            HTML格式的文本
        """
        if not markdown_text:
            return ""
        
        html = markdown_text

        # 1. 转换一级标题 (# → <h1>)
        html = re.sub(r'^#\s+(.+?)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # 2. 转换二级标题 (## → <h2>)
        html = re.sub(r'^##\s+(.+?)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)

        # 3. 转换三级标题 (### → <h3>)
        html = re.sub(r'^###\s+(.+?)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        
        # 2. 转换粗体 (** → <strong>)
        html = re.sub(r'\*\*([^*]+?)\*\*', r'<strong>\1</strong>', html)
        
        # 4. 转换引用块 (> → <blockquote>)
        def replace_quote(match):
            quote_content = match.group(1)
            return f'<blockquote>{quote_content}</blockquote>'
        html = re.sub(r'^>\s+(.+?)$', replace_quote, html, flags=re.MULTILINE)

        # 5. 转换链接 ([文本](URL) → <a>)
        def replace_link(match):
            link_text = match.group(1)
            url = match.group(2)
            return f'<a href="{url}">{link_text}</a>'
        html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', replace_link, html)

        # 6. 转换列表 (- → <ul><li>)
        lines = html.split('\n')
        result_lines = []
        in_list = False
        list_items = []
        
        for line in lines:
            stripped = line.strip()
            list_match = re.match(r'^[-\*]\s+(.+)$', stripped)
            
            if list_match:
                if not in_list:
                    in_list = True
                    list_items = []
                item_text = list_match.group(1)
                list_items.append(f'<li>{item_text}</li>')
            else:
                if in_list:
                    result_lines.append('<ul>')
                    result_lines.extend(list_items)
                    result_lines.append('</ul>')
                    in_list = False
                    list_items = []
                result_lines.append(line)
        
        if in_list:
            result_lines.append('<ul>')
            result_lines.extend(list_items)
            result_lines.append('</ul>')
        
        html = '\n'.join(result_lines)

        # 7. 转换分隔线 (--- → <hr/>)
        html = re.sub(r'^---\s*$', '<hr/>', html, flags=re.MULTILINE)

        # 8. 包裹段落
        lines = html.split('\n')
        result_lines = []
        current_para = []
        
        for line in lines:
            stripped = line.strip()
            
            if not stripped or (stripped.startswith('<') and stripped.endswith('>')):
                if current_para:
                    para_text = ' '.join(current_para)
                    if para_text:
                        result_lines.append(f'<p>{para_text}</p>')
                    current_para = []
                if stripped:
                    result_lines.append(line)
            else:
                current_para.append(stripped)
        
        if current_para:
            para_text = ' '.join(current_para)
            if para_text:
                result_lines.append(f'<p>{para_text}</p>')
        
        html = '\n'.join(result_lines)
        
        return html.strip()
    
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
        # 记录智能切换统计信息
        if self.use_smart_switch:
            self._log_smart_switch_stats(file_infos)
        
        logger.info(f"已更新RSS feed: {self.feed_path} ({len(file_infos)} 个文件)")
        
        return rss_xml
    
    def get_required_source(self, now: datetime = None) -> str:
        """
        获取RSS生成所需的数据源类型（供main.py在生成前协调）
        
        逻辑：
        - 当天首次运行（archive不存在）：返回 'archive'
        - 当天后续运行（archive已存在）：返回 'latest'
        
        Args:
            now: 可选，指定检测时间，默认为当前时间
            
        Returns:
            'archive' 或 'latest'
        """
        if now is None:
            now = datetime.now()
        
        date = now.date()
        archive_filename = date.strftime("%Y-%m-%d") + ".md"
        archive_path = self.archive_dir / archive_filename
        
        if archive_path.exists():
            return 'latest'
        else:
            return 'archive'
    
    def _log_smart_switch_stats(self, file_infos: list[dict]):
        """记录智能切换的统计信息"""
        try:
            latest_count = 0
            archive_count = 0
            
            for file_info in file_infos:
                file_path = file_info.get('file_path', '')
                if file_path.endswith('latest.md'):
                    latest_count += 1
                else:
                    archive_count += 1
            
            logger.info(f"智能切换统计: {archive_count}个archive文件, {latest_count}个latest文件")
            
            # 记录具体文件信息
            if latest_count > 0:
                logger.info("本次使用了latest.md文件（未找到对应archive文件）")
            
        except Exception as e:
            logger.error(f"记录智能切换统计失败: {e}")
    
    def _collect_markdown_files(self) -> list[Path]:
        """收集archive和docs目录中的所有Markdown文件，支持智能切换逻辑"""
        markdown_files = []
        
        # 收集archive目录中的文件
        if self.archive_dir.exists():
            for file_path in self.archive_dir.glob("*.md"):
                markdown_files.append(file_path)
        
        # 处理latest.md文件（智能切换逻辑）
        if self.docs_dir.exists():
            latest_file = self.docs_dir / "latest.md"
            
            if latest_file.exists():
                if self.use_smart_switch:
                    # 智能切换逻辑：检查是否有对应日期的archive文件
                    try:
                        # 从latest.md中提取日期
                        latest_date = self._extract_date_from_latest(latest_file)
                        if latest_date:
                            # 构建对应的archive文件名
                            archive_filename = latest_date.strftime("%Y-%m-%d") + ".md"
                            archive_file = self.archive_dir / archive_filename
                            
                            if archive_file.exists():
                                # 如果archive文件存在，使用latest.md（增量更新模式）
                                logger.info(f"智能切换：检测到archive文件 {archive_filename} 已存在，使用latest.md（增量更新模式）")
                                markdown_files.append(latest_file)
                            else:
                                # 如果archive文件不存在，使用archive文件（首次运行）
                                logger.info(f"智能切换：未找到对应archive文件，首次运行，使用archive文件")
                                if archive_file not in markdown_files:
                                    markdown_files.append(archive_file)
                        else:
                            # 无法从latest.md提取日期，使用latest.md
                            logger.warning(f"无法从latest.md提取日期，使用latest.md")
                            markdown_files.append(latest_file)
                    except Exception as e:
                        # 智能切换失败，使用latest.md
                        logger.error(f"智能切换失败: {e}，使用latest.md")
                        markdown_files.append(latest_file)
                else:
                    # 不使用智能切换，直接添加latest.md
                    markdown_files.append(latest_file)
        
        # 日志记录
        if self.use_smart_switch:
            logger.info(f"智能切换模式：找到 {len(markdown_files)} 个Markdown文件")
        else:
            logger.info(f"传统模式：找到 {len(markdown_files)} 个Markdown文件")
            
        return markdown_files
    
    def _extract_date_from_latest(self, latest_file: Path) -> datetime:
        """从latest.md文件中提取日期"""
        try:
            content = latest_file.read_text(encoding='utf-8')
            
            # 模式1：从"更新时间:"中提取日期
            date_match = re.search(r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日', content)
            if date_match:
                year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                return datetime(year, month, day)
            
            # 模式2：从标题中提取日期
            title_match = re.search(r'#\s*(\d{4})年(\d{2})月(\d{2})日', content)
            if title_match:
                year, month, day = int(title_match.group(1)), int(title_match.group(2)), int(title_match.group(3))
                return datetime(year, month, day)
            
            # 模式3：从文件名中尝试提取（如果使用日期格式命名的软链接）
            filename_match = re.match(r'(\d{4})-(\d{2})-(\d{2})\.md$', latest_file.name)
            if filename_match:
                year, month, day = int(filename_match.group(1)), int(filename_match.group(2)), int(filename_match.group(3))
                return datetime(year, month, day)
                
            logger.warning(f"无法从latest.md中提取日期: {latest_file}")
            return None
            
        except Exception as e:
            logger.error(f"从latest.md提取日期失败: {e}")
            return None
    
    def _extract_datetime_from_latest(self, content: str) -> datetime:
        """从latest.md内容中提取完整的日期时间（含时分）
        
        Args:
            content: latest.md的文件内容
            
        Returns:
            包含年月日时分信息的datetime对象，如果无法提取则返回None
        """
        try:
            # 模式：从"更新时间:"中提取完整日期时间
            # 匹配格式：2026年02月05日 20:46
            match = re.search(r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', content)
            if match:
                year, month, day, hour, minute = map(int, match.groups())
                return datetime(year, month, day, hour, minute)
            
            # 备选：仅提取日期（不含时分）
            match = re.search(r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日', content)
            if match:
                year, month, day = map(int, match.groups())
                return datetime(year, month, day)
                
            return None
            
        except Exception as e:
            logger.error(f"从latest.md提取完整日期时间失败: {e}")
            return None
    
    def _parse_markdown_file(self, file_path: Path) -> dict:
        """解析Markdown文件，提取信息"""
        if not file_path.exists():
            return None
        
        content = file_path.read_text(encoding='utf-8')
        
        # 提取日期（使用增强的日期提取逻辑）
        file_date = self._extract_date_from_file(file_path, content)
        
        # 提取新闻数量
        news_count = 0
        count_match = re.search(r'本期精选\s*\*\*(\d+)\*\*\s*条', content)
        if count_match:
            news_count = int(count_match.group(1))
        
        # 构建标题
        if file_path.name == "latest.md":
            # latest.md：标题包含时分信息（增量更新模式）
            pub_time = self._extract_datetime_from_latest(content)
            if pub_time:
                title = f"{pub_time.strftime('%Y年%m月%d日 %H:%M')} 新闻汇总"
            elif file_date:
                title = f"{file_date.strftime('%Y年%m月%d日')} 新闻汇总"
            else:
                title = f"{file_path.stem} 新闻汇总"
        elif file_date:
            # archive文件：标题只显示日期
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
            'news_count': news_count,
            'full_content': content  # 添加完整Markdown内容
        }
    
    def _extract_date_from_file(self, file_path: Path, content: str) -> datetime:
        """从文件内容中提取日期"""
        try:
            if file_path.name == "latest.md":
                # latest.md: 尝试多种模式提取日期
                patterns = [
                    # 完整日期时间
                    (r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})', 5),
                    # 仅日期
                    (r'更新时间:\s*(\d{4})年(\d{2})月(\d{2})日', 3),
                    (r'#\s*(\d{4})年(\d{2})月(\d{2})日', 3),
                ]
                
                for pattern, group_count in patterns:
                    match = re.search(pattern, content)
                    if match:
                        nums = [int(match.group(i)) for i in range(1, group_count + 1)]
                        if group_count == 5:
                            return datetime(*nums)
                        return datetime(*nums)
                
                logger.warning(f"无法从latest.md提取日期: {file_path}")
                
            else:
                # 归档文件: 从文件名提取日期 (YYYY-MM-DD.md)
                match = re.match(r'(\d{4})-(\d{2})-(\d{2})\.md$', file_path.name)
                if match:
                    return datetime(*[int(x) for x in match.groups()])
            
            return None
            
        except Exception as e:
            logger.error(f"从文件提取日期失败 {file_path}: {e}")
            return None
    
    def _build_rss_xml(self, file_infos: list[dict]) -> str:
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
    
    def _build_item_xml(self, file_info: dict) -> str:
        """构建单个item XML（支持三板块分类）"""
        title = escape(file_info.get('title', ''))
        link = file_info.get('link', '')
        description = escape(file_info.get('description', ''))
        pub_date = file_info.get('pub_date', '')
        guid = escape(file_info.get('guid', ''))

        # 获取分类信息（从新闻列表中提取，默认为综合）
        category = file_info.get('category', '综合新闻')

        # 获取完整内容并转换为HTML
        full_content = file_info.get('full_content', '')

        # 删除重复的订阅部分（从## 订阅开始到文件结束）
        subscription_pattern = r'##\s*📮\s*订阅.*$'
        full_content = re.sub(subscription_pattern, '', full_content, flags=re.DOTALL)

        # 替换占位符
        repo_url = os.getenv('GITHUB_REPOSITORY', 'username/news')
        username, repo = repo_url.split('/') if '/' in repo_url else ('username', 'news')
        full_content = full_content.replace('{username}', username)
        full_content = full_content.replace('{repo}', repo)

        # 转换为HTML
        if full_content:
            html_content = self._markdown_to_html(full_content)
            content_encoded = f"<![CDATA[{html_content}]]>"
        else:
            content_encoded = ""

        return f"""
    <item>
        <title>{title}</title>
        <link>{link}</link>
        <description>{description}</description>
        <pubDate>{pub_date}</pubDate>
        <guid>{guid}</guid>
        <category>{category}</category>
        <content:encoded>{content_encoded}</content:encoded>
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
