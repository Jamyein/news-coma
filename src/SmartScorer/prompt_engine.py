"""PromptEngine - 1-Pass Prompt生成引擎"""

import logging
from typing import List
from src.models import NewsItem, AIConfig

logger = logging.getLogger(__name__)


class PromptEngine:
    """1-Pass Prompt生成引擎"""

    def __init__(self, config: AIConfig):
        self.config = config
        self.scoring_criteria = config.scoring_criteria
        logger.info("PromptEngine初始化完成")
    
    def build_1pass_prompt(self, items: List[NewsItem]) -> str:
        """构建1-pass评分Prompt"""
        news_blocks = [self._format_news_item(item, i) for i, item in enumerate(items, 1)]
        sc = self.scoring_criteria

        return f"""请对以下 {len(items)} 条新闻进行专业评估。

{chr(10).join(news_blocks)}

【任务要求】
对每条新闻完成以下评估：

1. **分类判断**：财经/科技/社会政治
2. **5维度评分**（1-10分）：
   - 重要性（权重{sc.importance*100:.0f}%）
   - 时效性（权重{sc.timeliness*100:.0f}%）
   - 技术深度（权重{sc.technical_depth*100:.0f}%）
   - 受众广度（权重{sc.audience_breadth*100:.0f}%）
   - 实用性（权重{sc.practicality*100:.0f}%）
3. **总分**：加权平均分（保留1位小数）
4. **中文总结**：2-3句话概括

【输出格式】JSON数组：
{{
  "news_index": 1,
  "category": "财经|科技|社会政治",
  "category_confidence": 0.95,
  "importance": 8,
  "timeliness": 9,
  "technical_depth": 7,
  "audience_breadth": 6,
  "practicality": 7,
  "total_score": 7.5,
  "summary": "中文总结..."
}}"""
    
    def _format_news_item(self, item: NewsItem, index: int) -> str:
        """格式化单条新闻"""
        summary = item.summary[:300] if item.summary else "无摘要"
        return f"【新闻 {index}】\n标题: {item.title}\n来源: {item.source}\n摘要: {summary}"
