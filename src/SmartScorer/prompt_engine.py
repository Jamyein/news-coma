"""
PromptEngine - 1-Pass Prompt生成引擎

生成1-pass专用的Prompt，合并分类和评分任务
目标代码量: ~150行
"""

import logging
from typing import List, Dict
from src.models import NewsItem, AIConfig

logger = logging.getLogger(__name__)


class PromptEngine:
    """
    1-Pass Prompt生成引擎
    
    职责:
    1. 生成1-pass评分Prompt（分类+评分+总结）
    2. 合并多个任务到单次API调用
    3. 优化Prompt以提升输出质量
    """
    
    def __init__(self, config: AIConfig):
        """初始化Prompt引擎"""
        self.config = config
        self.scoring_criteria = config.scoring_criteria
        
        logger.info("PromptEngine初始化完成")
    
    def build_1pass_prompt(self, items: List[NewsItem]) -> str:
        """
        构建1-pass评分Prompt
        
        单次API调用完成:
        - 新闻分类（财经/科技/社会政治）
        - 5维度评分
        - 中文总结
        
        Args:
            items: 待评分的新闻列表
            
        Returns:
            str: 完整的Prompt文本
        """
        # 构建新闻块
        news_blocks = []
        for i, item in enumerate(items, 1):
            news_block = self._format_news_item(item, i)
            news_blocks.append(news_block)
        
        # 构建完整Prompt
        prompt = f"""请对以下 {len(items)} 条新闻进行专业评估。

{chr(10).join(news_blocks)}

【任务要求】
对每条新闻完成以下评估：

1. **分类判断**：确定新闻主要属于哪个领域
   - 财经：金融、经济、市场、投资相关
   - 科技：技术创新、AI、互联网、科研相关
   - 社会政治：政策、法律、国际关系、社会事件

2. **5维度评分**（1-10分）：
   - 重要性：对领域的重要程度（权重{self.scoring_criteria.importance*100:.0f}%）
   - 时效性：新闻的新鲜度和相关性（权重{self.scoring_criteria.timeliness*100:.0f}%）
   - 技术深度：内容的专业程度（权重{self.scoring_criteria.technical_depth*100:.0f}%）
   - 受众广度：影响的人群范围（权重{self.scoring_criteria.audience_breadth*100:.0f}%）
   - 实用性：对读者的实际价值（权重{self.scoring_criteria.practicality*100:.0f}%）

3. **总分计算**：加权平均分（保留1位小数）

4. **中文总结**：用2-3句话概括核心内容

【输出格式】
请严格返回JSON数组，每个元素包含：
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
}}

【注意事项】
- category必须是"财经"、"科技"或"社会政治"之一
- category_confidence表示分类置信度（0-1）
- 所有分数必须是1-10的整数
- total_score计算：各维度分数 × 权重后求和
- 总结必须是中文，简洁明了"""
        
        return prompt
    
    def _format_news_item(self, item: NewsItem, index: int) -> str:
        """
        格式化单条新闻
        
        Args:
            item: 新闻项
            index: 序号
            
        Returns:
            str: 格式化后的新闻文本
        """
        # 截取摘要（避免过长）
        summary = item.summary[:300] if item.summary else "无摘要"
        
        return f"""【新闻 {index}】
标题: {item.title}
来源: {item.source}
摘要: {summary}"""
    
    def build_simple_prompt(self, items: List[NewsItem]) -> str:
        """
        构建简化版Prompt（用于快速测试）
        
        Args:
            items: 待评分的新闻列表
            
        Returns:
            str: 简化Prompt文本
        """
        news_text = "\n".join([
            f"{i}. {item.title} ({item.source})"
            for i, item in enumerate(items, 1)
        ])
        
        return f"""请对以下新闻进行分类和评分（1-10分）：

{news_text}

返回JSON数组格式：
[{{"news_index": 1, "category": "科技", "total_score": 8.5}}]"""
    
    def estimate_tokens(self, items: List[NewsItem]) -> int:
        """
        估算Prompt所需token数
        
        Args:
            items: 新闻列表
            
        Returns:
            int: 估算的token数
        """
        # 简单估算：每个字符约0.5个token（中文）
        total_chars = sum(
            len(item.title) + len(item.summary[:300])
            for item in items
        )
        
        # 基础Prompt约500 token，每条新闻约200 token
        estimated = 500 + len(items) * 200 + total_chars // 2
        
        return min(estimated, 8000)  # 上限8000
