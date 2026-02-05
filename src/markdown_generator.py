"""
Markdown生成模块
负责生成结构化Markdown文档
"""
import logging
from datetime import datetime
from typing import List, Tuple, Dict
from pathlib import Path

from src.models import NewsItem

logger = logging.getLogger(__name__)


class MarkdownGenerator:
    """Markdown生成器"""
    
    def __init__(self, output_dir: str = "docs", archive_dir: str = "archive"):
        self.output_dir = Path(output_dir)
        self.archive_dir = Path(archive_dir)
        
        # 确保目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, items: List[NewsItem], timestamp: datetime) -> Tuple[str, str]:
        """
        生成Markdown文件
        
        Args:
            items: 新闻列表(已排序)
            timestamp: 生成时间戳
            
        Returns:
            (latest_path, archive_path)
        """
        content = self._build_content(items, timestamp)
        
        # 更新latest.md
        latest_path = self.output_dir / "latest.md"
        self._write_file(latest_path, content)
        logger.info(f"已更新: {latest_path}")
        
        # 创建归档
        archive_filename = timestamp.strftime("%Y-%m-%d") + ".md"
        archive_path = self.archive_dir / archive_filename
        
        # 如果归档文件已存在，追加到现有内容
        if archive_path.exists():
            existing_content = archive_path.read_text(encoding='utf-8')
            # 合并内容(去重)
            content = self._merge_archive_content(existing_content, content)
        
        self._write_file(archive_path, content)
        logger.info(f"已归档: {archive_path}")
        
        return str(latest_path), str(archive_path)
    
    def _build_content(self, items: List[NewsItem], timestamp: datetime) -> str:
        """构建Markdown内容（三板块分区布局）"""
        from datetime import timedelta
        beijing_time = timestamp + timedelta(hours=8)

        # 按 ai_category 分组
        finance_items = [item for item in items if item.ai_category == "财经"]
        tech_items = [item for item in items if item.ai_category == "科技"]
        politics_items = [item for item in items if item.ai_category == "社会政治"]

        # 计算各板块精选数量
        total_count = len(items)

        header = f"""# 📰 新闻精选

> 🕐 更新时间: {beijing_time.strftime("%Y年%m月%d日 %H:%M")}
> 📊 本期精选 **{total_count}** 条高质量新闻
> 🤖 由 AI 自动分类、筛选、翻译和总结

---

"""

        # 构建三板块内容
        body = ""

        # 财经板块
        body += self._build_section("💰 财经新闻", finance_items, "财经")

        # 科技板块
        body += self._build_section("🔬 科技新闻", tech_items, "科技")

        # 社会政治板块
        body += self._build_section("🏛️ 社会政治", politics_items, "社会政治")

        # 页脚
        footer = """## 📮 订阅

- **RSS订阅**: [feed.xml](https://{username}.github.io/{repo}/feed.xml)

---

*本项目自动聚合新闻，由AI智能分类筛选最有价值的内容*
"""

        return header + body + footer

    def _build_section(self, title: str, items: List[NewsItem], category: str) -> str:
        """构建单个板块的内容"""
        if not items:
            return f"""## {title} (0条)

*暂无{category}板块新闻*

---

"""

        # 按AI评分排序
        sorted_items = sorted(items, key=lambda x: (x.ai_score or 0, x.published_at), reverse=True)

        section = f"""## {title} ({len(items)}条)

精选 **{len(sorted_items)}** 条{category}新闻

"""

        for i, item in enumerate(sorted_items, 1):
            key_points_str = "\n".join([f"- {point}" for point in (item.key_points or ["暂无要点"])])

            section += f"""### {i}. {item.translated_title or item.title}

**📌 来源**: {item.source} | **🏏️ AI分类**: {item.ai_category} | **⭐ 评分**: {item.ai_score or 'N/A'}/10

**📝 摘要**:
{item.ai_summary or '暂无摘要'}

**💡 关键要点**:
{key_points_str}

**🔗 原文链接**: [{item.title}]({item.link})

---

"""

        return section
    

    def _merge_archive_content(self, existing: str, new: str) -> str:
        """
        合并归档内容，基于链接去重
        
        解析现有和新内容中的新闻条目，基于链接URL去重，
        合并后重新编号，保持Markdown格式
        """
        import re

        # 边界情况：内容为空或相同
        if not existing:
            return new
        if existing == new:
            return new

        try:
            # 解析条目：返回 {url: (title, full_entry_content)}
            def parse_entries(content: str) -> dict:
                entries = {}
                # 匹配条目：从 ### N. 开始到 --- 结束
                # 使用非贪婪匹配，直到遇到下一个 ### 或文件结束
                entry_pattern = r'###\s+\d+\.\s+(.*?)(?=###\s+\d+\.\s+|\Z)'
                # 链接模式：**🔗 原文链接**: [标题](URL)
                link_pattern = r'\*\*🔗 原文链接\*\*:\s*\[.*?\]\((.+?)\)'

                for match in re.finditer(entry_pattern, content, re.DOTALL):
                    entry_content = match.group(0)
                    # 提取链接
                    link_match = re.search(link_pattern, entry_content)
                    if link_match:
                        url = link_match.group(1)
                        # 提取标题（第一行）
                        title_match = re.match(r'###\s+\d+\.\s+(.+?)\n', entry_content)
                        title = title_match.group(1) if title_match else ""
                        entries[url] = (title, entry_content)
                return entries

            # 提取header（第一个 ### 之前的内容）
            def extract_header(content: str) -> str:
                first_entry_match = re.search(r'###\s+\d+\.', content)
                if first_entry_match:
                    return content[:first_entry_match.start()]
                return ""

            # 提取footer（最后一个 --- 之后的内容）
            def extract_footer(content: str) -> str:
                # 查找订阅部分（通常是最后一部分）
                footer_match = re.search(r'##\s+📮\s+订阅', content)
                if footer_match:
                    return content[footer_match.start():]
                return ""

            # 解析现有和新内容的条目
            existing_entries = parse_entries(existing)
            new_entries = parse_entries(new)

            # 合并条目：新条目覆盖或追加（保留最新）
            merged_entries = {**existing_entries, **new_entries}

            # 如果没有解析到任何条目，使用保守策略
            if not merged_entries:
                return existing + '\n\n' + new

            # 提取header和footer（使用新内容的header和footer）
            header = extract_header(new)
            footer = extract_footer(new)

            # 重新生成条目内容，重新编号
            body_parts = []
            for idx, (url, (title, entry_content)) in enumerate(merged_entries.items(), 1):
                # 替换条目编号
                renumbered_entry = re.sub(
                    r'^###\s+\d+\.\s+',
                    f'### {idx}. ',
                    entry_content,
                    count=1
                )
                body_parts.append(renumbered_entry)

            # 组装最终内容
            result = header + ''.join(body_parts)
            if footer:
                # 移除body末尾的---（如果有），然后添加footer
                result = result.rstrip()
                if result.endswith('---'):
                    result = result[:-3].rstrip()
                result = result + '\n\n' + footer

            return result

        except Exception as e:
            # 解析失败，保守策略：直接追加
            logger.warning(f"合并归档内容时解析失败，使用保守追加策略: {e}")
            return existing + '\n\n---\n\n' + new
    
    def _write_file(self, path: Path, content: str):
        """写入文件"""
        try:
            path.write_text(content, encoding='utf-8')
        except Exception as e:
            logger.error(f"写入文件失败 {path}: {e}")
            raise
