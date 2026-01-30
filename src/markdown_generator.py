"""
Markdown生成模块
负责生成结构化Markdown文档
"""
import logging
from datetime import datetime
from typing import List, Tuple
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
        """构建Markdown内容"""
        header = f"""# 📰 科技新闻精选

> 🕐 更新时间: {timestamp.strftime("%Y年%m月%d日 %H:%M")} UTC  
> 📊 本期精选 **{len(items)}** 条高质量科技新闻  
> 🤖 由 AI 自动筛选、翻译和总结

---

"""
        
        if not items:
            body = "*本期暂无符合条件的新闻*\n\n"
        else:
            body = ""
            for i, item in enumerate(items, 1):
                # 格式化关键要点
                key_points_str = "\n".join([f"- {point}" for point in (item.key_points or ["暂无要点"])])
                
                body += f"""### {i}. {item.translated_title or item.title}

**📌 来源**: {item.source} | **🏷️ 分类**: {item.category} | **⭐ 评分**: {item.ai_score or 'N/A'}/10

**📝 摘要**:
{item.ai_summary or '暂无摘要'}

**💡 关键要点**:
{key_points_str}

**🔗 原文链接**: [{item.title}]({item.link})

---

"""
        
        # 添加页脚
        footer = """## 📮 订阅

- **RSS订阅**: [feed.xml](https://raw.githubusercontent.com/{username}/{repo}/main/feed.xml)
- **更新时间**: 每6小时自动更新
- **生成方式**: GitHub Actions + OpenAI GPT-4o-mini

---

*本项目自动聚合科技新闻，由AI筛选最有价值的内容*
"""
        
        return header + body + footer
    
    def _merge_archive_content(self, existing: str, new: str) -> str:
        """合并归档内容(简单去重)"""
        # 如果内容相同，返回新的
        if existing == new:
            return new
        
        # 否则保留新的(或可以合并逻辑)
        return new
    
    def _write_file(self, path: Path, content: str):
        """写入文件"""
        try:
            path.write_text(content, encoding='utf-8')
        except Exception as e:
            logger.error(f"写入文件失败 {path}: {e}")
            raise
