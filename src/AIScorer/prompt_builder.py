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
        "key_points": ["要点1", "要点2", "要点3"],
        "impact_forecast": "分析该新闻可能产生的影响，以整段话形式输出（100字以内）"
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
9. impact_forecast分析新闻可能产生的影响，以整段话形式输出（100字以内）
10. 确保返回的是合法JSON数组，不要有其他文字说明
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
    
    # ==================== 分类特定总结Prompt ====================
    
    def build_category_specific_summary_prompt(
        self,
        item: NewsItem,
        category: str
    ) -> str:
        """
        构建分类特定总结Prompt
        
        根据新闻分类选择对应的总结模板：
        - 财经: 核心事实→关键细节→影响意义
        - 科技: 技术突破→应用场景→产业影响  
        - 社会政治: 核心事件→各方反应→潜在影响
        
        Args:
            item: 新闻项
            category: 新闻分类（财经/科技/社会政治/其他）
            
        Returns:
            str: 分类特定总结Prompt
        """
        if category == '财经':
            return self._build_finance_summary_prompt(item)
        elif category == '科技':
            return self._build_tech_summary_prompt(item)
        elif category == '社会政治':
            return self._build_politics_summary_prompt(item)
        else:
            return self._build_general_summary_prompt(item)
    
    def _build_finance_summary_prompt(self, item: NewsItem) -> str:
        """构建财经新闻总结Prompt"""
        few_shot_examples = self._get_finance_few_shot_examples()
        
        return f"""你是资深财经分析师，请对以下新闻进行深度分析并生成结构化的中文总结。

【新闻信息】
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:300] if item.summary else 'N/A'}

【总结要求】
1. 严格遵循三段式结构：
   a) 核心事实(50-70字): 核心事件、关键数据、市场反应
   b) 关键细节(80-100字): 具体数据、相关方反应、背景分析
   c) 影响意义(50-70字): 市场影响、投资启示、政策含义

2. 内容重点：
   - 突出具体数据和指标(股价、利率、GDP等)
   - 分析市场逻辑和因果关系
   - 评估投资价值和风险
   - 考虑政策环境因素

3. 质量控制：
   - 检查数据准确性(如有歧义注明)
   - 确保逻辑连贯性
   - 保持中文专业术语准确性
   - 避免主观臆断，基于事实分析

{few_shot_examples}

【输出格式】
请返回JSON格式:
{{
    "chinese_summary": "严格按照三段式结构的完整总结(200字左右)"
}}
"""
    
    def _build_tech_summary_prompt(self, item: NewsItem) -> str:
        """构建科技新闻总结Prompt"""
        few_shot_examples = self._get_tech_few_shot_examples()
        
        return f"""你是资深科技分析师，请对以下科技新闻进行深度分析并生成结构化的中文总结。

【新闻信息】
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:300] if item.summary else 'N/A'}

【总结要求】
1. 严格遵循三段式结构：
   a) 技术突破(50-70字): 核心技术、创新点、技术参数
   b) 应用场景(80-100字): 具体应用、潜在价值、商业化路径
   c) 产业影响(50-70字): 行业影响、竞争格局、发展趋势

2. 内容重点：
   - 准确描述技术原理和实现方式
   - 分析技术的实际应用价值和限制
   - 评估商业化前景和时间表
   - 考虑产业链影响和生态系统建设

3. 质量控制：
   - 技术描述需准确无歧义
   - 区分技术成熟度(实验室/小规模/量产)
   - 注明技术来源(论文/专利/产品发布)
   - 避免过度乐观的技术炒作

{few_shot_examples}

【输出格式】
请返回JSON格式:
{{
    "chinese_summary": "严格按照三段式结构的完整总结(200字左右)"
}}
"""
    
    def _build_politics_summary_prompt(self, item: NewsItem) -> str:
        """构建社会政治新闻总结Prompt"""
        few_shot_examples = self._get_politics_few_shot_examples()
        
        return f"""你是资深政治分析师，请对以下社会政治新闻进行深度分析并生成结构化的中文总结。

【新闻信息】
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:300] if item.summary else 'N/A'}

【总结要求】
1. 严格遵循三段式结构：
   a) 核心事件(50-70字): 主要事件、关键方、发生背景
   b) 各方反应(80-100字): 政府表态、民众反应、国际回应
   c) 潜在影响(50-70字): 社会影响、政策调整、国际关系

2. 内容重点：
   - 明确事件的性质和严重程度
   - 分析各利益相关方的立场和动机
   - 评估事件的短期和长期影响
   - 考虑历史背景和地缘政治因素

3. 质量控制：
   - 事实核查避免谣言传播
   - 平衡各方观点报道
   - 区分事实陈述和评论分析
   - 注意敏感信息的处理方式

{few_shot_examples}

【输出格式】
请返回JSON格式:
{{
    "chinese_summary": "严格按照三段式结构的完整总结(200字左右)"
}}
"""
    
    def _build_general_summary_prompt(self, item: NewsItem) -> str:
        """构建通用总结Prompt（分类不明确时使用）"""
        return f"""你是资深新闻编辑，请对以下新闻进行深度分析并生成中文总结。

【新闻信息】
标题: {item.title}
来源: {item.source}
分类: {item.category}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:300] if item.summary else 'N/A'}

【总结要求】
请生成200字左右的中文总结，要求：
1. 准确传达新闻核心内容
2. 突出重要事实和关键数据
3. 分析新闻的影响和意义
4. 语言简洁专业，适合中文读者

【输出格式】
请返回JSON格式:
{{
    "chinese_summary": "中文总结内容(200字左右)"
}}
"""
    
    # ==================== Few-Shot示例 ====================
    
    def _get_finance_few_shot_examples(self) -> str:
        """获取财经新闻Few-Shot示例"""
        return """【Few-Shot示例】

示例1:
标题: 美联储维持利率不变但暗示年内可能降息
总结:
a) 核心事实: 美联储宣布维持基准利率在5.25%-5.5%区间不变，符合市场预期。会议声明删除"进一步紧缩"措辞，暗示政策转向。
b) 关键细节: 点阵图显示官员预计年内降息75个基点，较12月预期更鸽派。通胀预测下调至2.4%，经济增速预期上调。鲍威尔称降息时机将取决于数据。
c) 影响意义: 决议公布后美股上涨，美债收益率回落。市场预计首次降息在6月，全年降息三次。降低融资成本有利企业盈利，但需关注通胀反弹风险。

示例2:
标题: 中国央行下调存款准备金率50个基点释放1万亿元流动性
总结:
a) 核心事实: 中国人民银行宣布下调金融机构存款准备金率0.5个百分点至7.4%，释放长期资金约1万亿元。这是年内首次降准，旨在支持实体经济。
b) 关键细节: 央行表示降准目的是保持流动性合理充裕，支持信贷合理增长。操作后金融机构加权平均存款准备金率降至7.4%。一季度GDP增长5.3%，但3月PMI回落至50.8。
c) 影响意义: 降准有助降低银行负债成本，推动LPR下行。利好银行股和地产板块，缓解房企流动性压力。需关注资金是否有效流入实体经济而非空转。"""
    
    def _get_tech_few_shot_examples(self) -> str:
        """获取科技新闻Few-Shot示例"""
        return """【Few-Shot示例】

示例1:
标题: OpenAI发布GPT-4o，实现多模态实时交互能力
总结:
a) 技术突破: OpenAI推出GPT-4o模型，实现文本、图像、音频的端到端多模态理解。响应延迟降至232ms，接近人类对话速度。免费开放大部分功能。
b) 应用场景: 支持实时视频对话、屏幕共享分析、文档多模态处理。教育领域可实现个性化辅导，企业客服提升效率。API定价为输入$5/百万token，输出$15/百万token。
c) 产业影响: 大幅降低AI应用门槛，可能冲击现有语音和图像识别公司。推动多模态AI标准化，加速AI助手普及。需关注数据隐私和内容审核挑战。

示例2:
标题: 特斯拉发布Optimus Gen 2人形机器人，行走速度提升30%
总结:
a) 技术突破: 特斯拉推出第二代Optimus人形机器人，行走速度提升30%达到0.6米/秒。手指升级为11自由度，可精细操作工具。颈部增加2自由度，改善视野。
b) 应用场景: 目标应用于制造业重复性工作、物流分拣、家庭服务。马斯克预计3-5年内可量产，单价低于2万美元。已在其工厂进行测试。
c) 产业影响: 推动人形机器人产业化，可能重塑制造业劳动力结构。产业链涉及伺服电机、传感器、AI芯片。技术难点在于稳定性和安全性，商业化仍需时间验证。"""
    
    def _get_politics_few_shot_examples(self) -> str:
        """获取社会政治新闻Few-Shot示例"""
        return """【Few-Shot示例】

示例1:
标题: 欧洲议会通过《人工智能法案》，确立全球最严格AI监管框架
总结:
a) 核心事件: 欧洲议会以523票赞成、46票反对通过《人工智能法案》，确立分级风险监管体系。禁止社会评分、情绪识别等高风险应用，违规企业最高罚款全球营业额6%。
b) 各方反应: 欧盟委员会称法案平衡创新与安全。科技公司担忧合规成本过高，可能影响欧洲AI竞争力。隐私组织欢迎加强监管，公民社会组织要求更严格执法。
c) 潜在影响: 法案为全球AI监管树立标杆，可能被其他地区效仿。推动AI伦理标准化，增加企业合规成本。可能减缓欧洲AI创新速度，但提升技术可信度。

示例2:
标题: 美国众议院通过TikTok剥离法案，要求字节跳动限期出售
总结:
a) 核心事件: 美国众议院以352票赞成、65票反对通过法案，要求字节跳动在165天内剥离TikTok美国业务，否则将面临禁令。法案基于国家安全和数据隐私担忧。
b) 各方反应: 白宫表示支持法案。TikTok称违反言论自由，将提起法律诉讼。部分议员担忧影响中小企业营销渠道。中国外交部批评美国滥用国家安全概念。
c) 潜在影响: 可能导致TikTok退出美国市场，影响1.7亿美国用户。重塑社交媒体竞争格局，利好Meta、YouTube等平台。加剧中美科技脱钩趋势，影响双边投资环境。"""
    
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
    
    def build_pass2_scoring_prompt(
        self,
        items: List[NewsItem],
        category_map: Dict[int, str] = None
    ) -> str:
        """
        构建Pass2评分Prompt（支持分类特定总结）
        
        根据新闻分类动态选择总结模板：
        - 财经类：核心事实→关键细节→影响意义
        - 科技类：技术突破→应用场景→产业影响
        - 社会政治类：核心事件→各方反应→潜在影响
        
        Args:
            items: 新闻项列表
            category_map: 新闻索引到分类的映射 {1: '财经', 2: '科技', ...}
            
        Returns:
            str: Pass2评分Prompt
        """
        # 构建新闻区块（包含分类信息）
        news_sections = self._build_pass2_news_sections(items, category_map)
        
        # 构建分类特定总结要求
        summary_requirements = self._build_pass2_summary_requirements()
        
        return f"""你是资深新闻分析师，请对以下新闻进行批量深度评分和中文总结。

{summary_requirements}

【新闻列表】
{''.join(news_sections)}

【输出格式】
请返回JSON数组格式：
[
    {{
        "news_index": 1,
        "category": "财经",
        "category_confidence": 0.85,
        "market_impact": 8,
        "investment_value": 7,
        "timeliness": 9,
        "depth": 6,
        "audience_breadth": 7,
        "total_score": 7.5,
        "chinese_title": "翻译成中文的标题",
        "chinese_summary": "严格按照分类特定三段式结构的中文总结(200字左右)",
        "key_points": ["要点1", "要点2", "要点3"],
        "impact_forecast": "分析该新闻可能产生的影响（100字以内）"
    }},
    ...
]

【重要说明】
1. news_index必须对应新闻列表中的序号(从1开始)
2. category只能是"财经"、"科技"或"社会政治"之一
3. chinese_summary必须严格按照对应分类的三段式结构生成
4. 评分字段根据category自动选择对应的5个维度
5. total_score根据对应板块的权重自动计算
6. 确保返回的是合法JSON数组，不要有其他文字说明"""
    
    def _build_pass2_news_sections(
        self,
        items: List[NewsItem],
        category_map: Dict[int, str] = None
    ) -> List[str]:
        """构建Pass2新闻区块（包含分类信息）"""
        sections = []
        for i, item in enumerate(items, 1):
            # 确定分类
            if category_map and i in category_map:
                assigned_category = category_map[i]
            else:
                # 从新闻项中提取分类
                category = getattr(item, 'ai_category', None) or \
                          getattr(item, 'pre_category', None) or \
                          getattr(item, 'category', '未分类')
                assigned_category = self._standardize_category_for_pass2(category)
            
            section = f"""
--- 新闻{i} [{assigned_category}] ---
标题: {item.title}
来源: {item.source}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M')}
摘要: {item.summary[:400] if item.summary else 'N/A'}
"""
            sections.append(section)
        return sections
    
    def _standardize_category_for_pass2(self, category: str) -> str:
        """为Pass2标准化分类"""
        if not category:
            return '未分类'
        
        category_lower = str(category).lower()
        
        # 财经类
        if any(kw in category_lower for kw in ['财经', 'finance', '经济', '投资', '股票', '市场', '金融']):
            return '财经'
        # 科技类
        elif any(kw in category_lower for kw in ['科技', 'tech', '技术', 'ai', '人工智能', '创新']):
            return '科技'
        # 社会政治类
        elif any(kw in category_lower for kw in ['政治', 'politics', '社会', '政策', '国际', '外交']):
            return '社会政治'
        else:
            return '社会政治'  # 默认分类
    
    def _build_pass2_summary_requirements(self) -> str:
        """构建Pass2总结要求"""
        return """【中文总结要求】
根据每条新闻的分类，严格按照对应的三段式结构生成中文总结：

一、财经类新闻（三段式）：
a) 核心事实(50-70字): 核心事件、关键数据、市场反应
b) 关键细节(80-100字): 具体数据、相关方反应、背景分析
c) 影响意义(50-70字): 市场影响、投资启示、政策含义
重点：突出数据指标、分析市场逻辑、评估投资价值

二、科技类新闻（三段式）：
a) 技术突破(50-70字): 核心技术、创新点、技术参数
b) 应用场景(80-100字): 具体应用、潜在价值、商业化路径
c) 产业影响(50-70字): 行业影响、竞争格局、发展趋势
重点：准确描述技术、分析应用价值、评估商业化前景

三、社会政治类新闻（三段式）：
a) 核心事件(50-70字): 主要事件、关键方、发生背景
b) 各方反应(80-100字): 政府表态、民众反应、国际回应
c) 潜在影响(50-70字): 社会影响、政策调整、国际关系
重点：明确事件性质、平衡各方观点、评估短期长期影响"""
    
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

    def build_pass1_ai_classification_prompt(self, items: List[NewsItem]) -> str:
        """
        构建Pass1 AI智能分类+打分Prompt

        要求AI在一次调用中完成：
        1. 判断每条新闻的分类（财经/科技/社会政治）
        2. 给出total分数（0-10）
        3. 返回分类置信度

        Args:
            items: 新闻项列表

        Returns:
            str: 分类+打分Prompt
        """
        # 构建新闻块
        news_blocks = []
        for i, item in enumerate(items, 1):
            news_blocks.append(
                f"【新闻{i}】\n"
                f"标题: {item.title}\n"
                f"来源: {item.source}\n"
                f"摘要: {item.summary[:250] if item.summary else 'N/A'}\n"
            )

        return f"""你是一位资深新闻编辑，请对以下新闻进行批量分类和价值评分。

【分类标准】
将每条新闻归类为以下三类之一：

1. 财经：金融市场、投资、经济政策、企业财报、货币政策、房地产、宏观经济等
2. 科技：技术创新、AI/人工智能、芯片、软件、互联网、科研突破、科技产品等
3. 社会政治：政府政策、国际关系、社会事件、法律法规、选举、环境、公共安全等

【分类优先级规则】
当新闻内容涉及多个领域时，按以下优先级判断：

- 标题含以下词时优先归"财经"：财报、业绩、营收、利润、股价、股市、投资、GDP、通胀、利率、央行、美联储、房地产、房价
- 标题含以下词时优先归"科技"：AI、人工智能、芯片、半导体、算法、技术突破、软件、互联网、创新、科技、GPT、大模型
- 标题含以下词时优先归"社会政治"：政策、法案、法律、选举、投票、外交、国际、政府、监管、气候、环境、疫情、公共卫生

【评分标准】0-10分制
- 8-10分：重大新闻，行业影响力强，必读
- 6-7分：重要新闻，有参考价值
- 4-5分：普通新闻，信息价值一般
- 0-3分：低价值新闻

{''.join(news_blocks)}

【输出格式】
请返回JSON数组，每个元素包含：
{{
    "news_index": 1,              // 新闻序号（从1开始）
    "category": "财经",           // 分类，只能是"财经"、"科技"或"社会政治"
    "category_confidence": 0.85,  // 分类置信度（0-1之间）
    "total": 7.5                  // 总体评分（0-10之间）
}}

示例输出：
[
    {{"news_index": 1, "category": "财经", "category_confidence": 0.92, "total": 8.0}},
    {{"news_index": 2, "category": "科技", "category_confidence": 0.88, "total": 7.5}},
    {{"news_index": 3, "category": "社会政治", "category_confidence": 0.75, "total": 6.5}}
]

重要说明：
1. category字段只能是"财经"、"科技"或"社会政治"三者之一
2. category_confidence表示你对分类判断的信心程度（0-1之间，1表示完全确定）
3. total为总体评分（0-10之间，支持一位小数）
4. 确保返回的是合法JSON数组，不要包含任何其他文字说明或markdown代码块标记
5. 所有{len(items)}条新闻都必须返回结果
"""
