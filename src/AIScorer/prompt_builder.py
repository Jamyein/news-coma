"""
Prompt构建器 - 统一Prompt构建

解决原 ai_scorer.py 中5处重复的Prompt构建逻辑（181行重复代码）
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from src.models import NewsItem


@dataclass
class PromptTemplate:
    """Prompt模板配置"""
    name: str                      # 模板名称
    system_role: str               # 系统角色
    task_description: str          # 任务描述
    include_dimensions: bool       # 是否包含维度描述
    max_content_length: int        # 最大内容长度
    include_full_content: bool     # 是否包含全文
    output_format: str             # 输出格式说明


class PromptBuilder:
    """
    Prompt构建器
    
    提供统一的Prompt构建功能，支持多种任务类型
    替代原代码中5处重复的Prompt构建：
    - 行号263-394 (_build_batch_prompt)
    - 行号657-701 (_build_prompt)
    - 行号1393-1478 (_build_deep_analysis_prompt)
    - 行号1725-1787 (_build_single_deep_analysis_prompt)
    - 各 _pass1_*_screen 方法中的Prompt构建
    """
    
    # 维度名称映射
    DIMENSION_MAP = {
        # 标准维度
        'importance': '重要性(行业影响)',
        'timeliness': '时效性',
        'technical_depth': '技术深度',
        'audience_breadth': '受众广度',
        'practicality': '实用性',
        
        # 财经维度
        'market_impact': '市场影响',
        'investment_value': '投资价值',
        
        # 科技维度
        'innovation': '技术创新',
        
        # 社会政治维度
        'policy_impact': '政策影响',
        'public_attention': '公众关注度',
        
        # 通用维度
        'depth': '深度',
        'influence': '影响力',
        'quality': '质量',
    }
    
    # 预定义模板
    TEMPLATES = {
        'batch_scoring': PromptTemplate(
            name='batch_scoring',
            system_role='资深科技新闻编辑',
            task_description='请对以下新闻进行批量评分和分析',
            include_dimensions=True,
            max_content_length=400,
            include_full_content=False,
            output_format='JSON数组'
        ),
        
        'single_scoring': PromptTemplate(
            name='single_scoring',
            system_role='资深新闻编辑',
            task_description='请对以下新闻进行评分和分析',
            include_dimensions=True,
            max_content_length=500,
            include_full_content=False,
            output_format='JSON对象'
        ),
        
        'deep_analysis': PromptTemplate(
            name='deep_analysis',
            system_role='资深新闻分析师',
            task_description='请对以下已评分新闻进行深度分析',
            include_dimensions=False,
            max_content_length=5000,
            include_full_content=True,
            output_format='JSON数组'
        ),
        
        'quick_screening': PromptTemplate(
            name='quick_screening',
            system_role='快速评分助手',
            task_description='请对以下新闻进行快速预筛',
            include_dimensions=False,
            max_content_length=200,
            include_full_content=False,
            output_format='JSON数组'
        ),
    }
    
    def __init__(self, config):
        """
        初始化Prompt构建器
        
        Args:
            config: AI配置对象
        """
        self.config = config
    
    # ==================== 维度描述构建 ====================
    
    def build_dimension_descriptions(
        self, 
        criteria: Dict[str, float],
        category: str = 'general'
    ) -> List[str]:
        """
        构建维度描述列表
        
        Args:
            criteria: 评分权重配置
            category: 新闻分类（用于选择维度映射）
            
        Returns:
            List[str]: 维度描述列表
        """
        dimension_map = self._get_dimension_map_for_category(category)
        
        descriptions = []
        for key, weight in criteria.items():
            desc = dimension_map.get(key, key)
            descriptions.append(f"- {desc}: {int(weight * 100)}%")
        
        return descriptions
    
    def _get_dimension_map_for_category(self, category: str) -> Dict[str, str]:
        """根据分类获取维度映射"""
        if not category or category == 'general':
            return self.DIMENSION_MAP
        
        category_lower = category.lower()
        
        if '财经' in category_lower or 'finance' in category_lower:
            return {
                'importance': '市场影响',
                'timeliness': '时效性',
                'technical_depth': '投资价值',
                'audience_breadth': '受众广度',
                'practicality': '深度',
                'market_impact': '市场影响',
                'investment_value': '投资价值',
                'depth': '深度',
            }
        elif '科技' in category_lower or 'tech' in category_lower:
            return {
                'importance': '技术创新',
                'timeliness': '时效性',
                'technical_depth': '实用性',
                'audience_breadth': '影响力',
                'practicality': '深度',
                'innovation': '技术创新',
                'practicality': '实用性',
                'influence': '影响力',
                'depth': '深度',
            }
        elif '政治' in category_lower or 'politics' in category_lower:
            return {
                'importance': '政策影响',
                'timeliness': '时效性',
                'technical_depth': '公众关注度',
                'audience_breadth': '深度',
                'practicality': '受众广度',
                'policy_impact': '政策影响',
                'public_attention': '公众关注度',
                'depth': '深度',
            }
        
        return self.DIMENSION_MAP
    
    # ==================== 新闻区块构建 ====================
    
    def build_news_sections(
        self,
        items: List[NewsItem],
        max_length: int = 400,
        include_full_content: bool = False
    ) -> List[str]:
        """
        构建新闻内容区块列表
        
        Args:
            items: 新闻项列表
            max_length: 内容最大长度
            include_full_content: 是否包含全文
            
        Returns:
            List[str]: 新闻区块列表
        """
        sections = []
        
        for i, item in enumerate(items, 1):
            section = self._build_single_news_section(
                i, item, max_length, include_full_content
            )
            sections.append(section)
        
        return sections
    
    def _build_single_news_section(
        self,
        index: int,
        item: NewsItem,
        max_length: int,
        include_full_content: bool
    ) -> str:
        """构建单条新闻的区块"""
        # 获取内容
        if include_full_content and item.full_content:
            content = item.full_content[:max_length]
            content_label = "新闻全文"
        elif item.summary:
            content = item.summary[:max_length]
            content_label = "摘要"
        else:
            content = 'N/A'
            content_label = "摘要"
        
        # 构建AI评分信息（如果有）
        ai_info = ""
        if hasattr(item, 'ai_score') and item.ai_score:
            ai_info = f"AI评分: {item.ai_score}\n"
            if hasattr(item, 'ai_summary') and item.ai_summary:
                ai_summary = item.ai_summary[:200] if len(item.ai_summary) > 200 else item.ai_summary
                ai_info += f"AI摘要: {ai_summary}\n"
        
        return f"""
--- 新闻{index} ---
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
原文链接: {getattr(item, 'link', 'N/A')}
{ai_info}{content_label}: {content}
"""
    
    # ==================== Prompt构建主方法 ====================
    
    def build_prompt(
        self,
        template_name: str,
        items: List[NewsItem],
        criteria: Dict[str, float] = None,
        category: str = 'general',
        custom_context: Dict = None
    ) -> str:
        """
        构建Prompt（统一入口）
        
        Args:
            template_name: 模板名称
            items: 新闻项列表
            criteria: 评分权重配置
            category: 新闻分类
            custom_context: 自定义上下文
            
        Returns:
            str: 构建好的Prompt
        """
        template = self.TEMPLATES.get(template_name)
        
        if not template:
            raise ValueError(f"Unknown template: {template_name}")
        
        # 获取配置
        config_criteria = criteria or getattr(self.config, 'scoring_criteria', {})
        
        # 构建各个部分
        parts = []
        
        # 1. 系统角色和任务描述
        parts.append(f"你是一位{template.system_role}。{template.task_description}。\n")
        
        # 2. 维度描述
        if template.include_dimensions:
            dimensions = self.build_dimension_descriptions(config_criteria, category)
            parts.append(self._build_dimension_section(dimensions, category))
        
        # 3. 新闻列表
        news_sections = self.build_news_sections(
            items, 
            template.max_content_length,
            template.include_full_content
        )
        parts.append(f"新闻列表:\n{''.join(news_sections)}\n")
        
        # 4. 输出格式
        parts.append(self._build_output_format_section(template_name, category))
        
        # 5. 重要说明
        parts.append(self._build_important_notes_section(template_name))
        
        return ''.join(parts)
    
    def _build_dimension_section(
        self, 
        dimensions: List[str], 
        category: str
    ) -> str:
        """构建维度描述区域"""
        title = "评分维度（1-10分制）"
        
        if category and category != 'general':
            title += f"（{category}新闻）"
        
        return f"""
{title}：
{chr(10).join(dimensions)}

"""
    
    def _build_output_format_section(
        self, 
        template_name: str,
        category: str
    ) -> str:
        """构建输出格式区域"""
        if template_name == 'batch_scoring':
            return self._build_batch_output_format(category)
        elif template_name == 'deep_analysis':
            return self._build_deep_analysis_output_format()
        elif template_name == 'single_scoring':
            return self._build_single_output_format()
        elif template_name == 'quick_screening':
            return self._build_quick_screening_output_format()
        
        return ""
    
    def _build_batch_output_format(self, category: str) -> str:
        """构建批量评分的输出格式"""
        return """
【返回JSON数组格式】
[
    {
        "news_index": 1,
        "category": "财经",
        "category_confidence": 0.85,
        "market_impact": 8,
        "investment_value": 7,
        "timeliness": 9,
        "depth": 6,
        "audience_breadth": 0,
        "total_score": 7.5,
        "chinese_title": "翻译成中文的标题",
        "chinese_summary": "200字左右的中文总结",
        "key_points": ["要点1", "要点2", "要点3"]
    },
    ...
]

【重要说明】
1. news_index必须对应新闻列表中的序号(从1开始)
2. category只能是"财经"、"科技"或"社会政治"之一
3. category_confidence是分类置信度，范围0-1
4. 评分字段根据category自动选择对应的5个维度
5. total_score根据对应板块的权重自动计算
6. chinese_title要准确传达原意，适合中文读者
7. chinese_summary要突出核心价值和影响
8. key_points列出3-5个关键要点
9. 确保返回的是合法JSON数组，不要有其他文字说明
"""
    
    def _build_single_output_format(self) -> str:
        """构建单条评分的输出格式"""
        return """
请按以下JSON格式返回(不要添加markdown代码块标记)：
{
    "importance": 8,
    "timeliness": 9,
    "technical_depth": 7,
    "audience_breadth": 6,
    "practicality": 8,
    "total_score": 7.5,
    "chinese_title": "翻译成中文的标题",
    "chinese_summary": "200字左右的中文总结",
    "key_points": ["要点1", "要点2", "要点3"]
}

注意：
1. total_score根据权重自动计算
2. chinese_title要准确传达原意，适合中文读者
3. chinese_summary要突出核心价值和影响
4. key_points列出3-5个关键要点
"""
    
    def _build_deep_analysis_output_format(self) -> str:
        """构建深度分析的输出格式"""
        return """
【返回JSON数组格式】
[
    {
        "news_index": 1,
        "core_insight": "核心观点总结，100字以内...",
        "key_arguments": ["论据1", "论据2", "论据3", "论据4"],
        "impact_forecast": "影响预测，200字以内...",
        "sentiment": "positive/neutral/negative",
        "credibility_score": 7.5
    },
    ...
]

【重要说明】
1. news_index必须对应新闻列表中的序号(从1开始)
2. core_insight要精炼准确，抓住新闻本质
3. key_arguments应该是具体事实或数据
4. impact_forecast要基于事实进行分析
5. sentiment必须严格选择positive、neutral或negative之一
6. credibility_score考虑信息来源权威性、内容一致性
7. 确保返回的是合法JSON数组
"""
    
    def _build_quick_screening_output_format(self) -> str:
        """构建快速预筛的输出格式"""
        return """
请返回JSON数组格式:
[{"news_index": 1, "total": 7.5}, ...]

只需返回JSON，不要其他解释。
"""
    
    def _build_important_notes_section(self, template_name: str) -> str:
        """构建重要说明区域"""
        if template_name == 'quick_screening':
            return ""
        
        return """
【任务要求】
请认真评估每条新闻的价值，确保评分客观准确。
"""
    
    # ==================== 便捷方法 ====================
    
    def build_scoring_prompt(
        self, 
        items: List[NewsItem],
        category: str = 'general'
    ) -> str:
        """构建批量评分Prompt"""
        return self.build_prompt(
            'batch_scoring',
            items,
            category=category
        )
    
    def build_deep_analysis_prompt(
        self, 
        items: List[NewsItem]
    ) -> str:
        """构建深度分析Prompt"""
        return self.build_prompt('deep_analysis', items)
    
    def build_single_scoring_prompt(
        self, 
        item: NewsItem
    ) -> str:
        """构建单条评分Prompt"""
        return self.build_prompt(
            'single_scoring',
            [item]
        )
    
    def build_quick_screening_prompt(
        self, 
        items: List[NewsItem],
        category: str = 'general'
    ) -> str:
        """构建快速预筛Prompt"""
        return self.build_prompt(
            'quick_screening',
            items,
            category=category
        )
    
    # ==================== Pass1 专用方法 ====================
    
    def build_pass1_prompt(self, category: str) -> str:
        """
        构建Pass1快速预筛Prompt模板
        
        Args:
            category: 新闻分类（财经/科技/社会政治）
            
        Returns:
            str: Prompt模板
        """
        templates = {
            '财经': """快速评估这条财经新闻的价值(0-10分)。

评估标准（针对财经新闻优化）：
- 市场影响(40%): 对股市/债市/汇市的影响程度
- 投资价值(30%): 对投资决策的参考价值
- 时效性(20%): 新闻的及时性和新鲜度
- 深度(10%): 分析的深度和专业性

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"market_impact": 8, "investment_value": 7, "timeliness": 9, "depth": 6, "total": 7.5}}
不要其他解释。""",
            
            '科技': """快速评估这条科技新闻的价值(0-10分)。

评估标准（针对科技新闻优化）：
- 技术创新(40%): 技术突破和创新程度
- 实用性(30%): 实际应用价值和可行性
- 影响力(20%): 对行业和社会的影响
- 深度(10%): 技术解读的专业深度

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"innovation": 8, "practicality": 7, "influence": 8, "depth": 6, "total": 7.5}}
不要其他解释。""",
            
            '社会政治': """快速评估这条社会政治新闻的价值(0-10分)。

评估标准（针对社会政治新闻优化）：
- 政策影响(40%): 对政策制定和执行的影响
- 公众关注度(30%): 社会关注度和讨论热度
- 时效性(20%): 新闻及时性和紧迫性
- 深度(10%): 背景分析深入程度

新闻标题: {title}
来源: {source}
摘要: {summary}

只需返回JSON格式: {{"policy_impact": 8, "public_attention": 7, "timeliness": 9, "depth": 6, "total": 7.5}}
不要其他解释。""",
        }
        
        return templates.get(category, templates['财经'])
    
    def build_pass1_batch_prompt(
        self, 
        items: List[NewsItem],
        category: str
    ) -> str:
        """
        构建Pass1批量Prompt
        
        Args:
            items: 新闻项列表
            category: 新闻分类
            
        Returns:
            str: 批量Prompt
        """
        template = self.build_pass1_prompt(category)
        
        # 构建新闻块
        news_blocks = []
        for i, item in enumerate(items, 1):
            news_blocks.append(f"新闻{i}:\n标题: {item.title}\n来源: {item.source}\n摘要: {item.summary[:200]}\n")
        
        news_section = "\n".join(news_blocks)
        
        return f"""请对以下新闻进行批量快速评分：

{news_section}

{template}

请返回JSON数组格式:
[{{"news_index": 1, "total": 7.5}}, ...]
"""
