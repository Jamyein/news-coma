"""PromptEngine - 1-Pass Prompt生成引擎"""

import logging
from src.models import NewsItem, AIConfig

logger = logging.getLogger(__name__)


class PromptEngine:
    """1-Pass Prompt生成引擎"""

    def __init__(self, config: AIConfig):
        self.config = config
        self.scoring_criteria = config.scoring_criteria
        logger.info("PromptEngine初始化完成")
    
    def build_1pass_prompt(self, items: list[NewsItem]) -> str:
        """构建1-pass评分Prompt"""
        news_blocks = [self._format_news_item(item, i) for i, item in enumerate(items, 1)]
        sc = self.scoring_criteria

        return f"""请对以下 {len(items)} 条新闻进行专业评估。

{chr(10).join(news_blocks)}

【任务要求】
对每条新闻完成以下3项评估：

1. **中文标题生成**：将新闻原标题转换为高质量中文标题
   要求：
   - 目标读者：中国中文读者
   - 长度：12-25个中文字符
   - 风格：新闻标题风格，简洁有力，信息完整
   - 内容：保留原标题核心信息（主体、动作、结果），删除无关修饰词
   - 翻译规范：英文公司名可保留原文（如Amazon、Nvidia），但需补充中文说明

   【中文标题示例】
   ✅ 原标题："It's existential: How Big Tech found itself in a $650 billion spending spiral"
      → 中文标题："大科技公司陷入6500亿美元AI支出漩涡，市场担忧投资回报"
   ✅ 原标题："Benchmark raises $225M in special funds to double down on Cerebras"
      → 中文标题："Benchmark资本筹集2.25亿美元专投Cerebras，对标Nvidia"
   ✅ 原标题："Tech wreck signals a market reset"
      → 中文标题："科技股崩盘预示市场重置，加密货币等投机资产遭抛售"

2. **分类判断**：根据以下标准选择最合适的分类

   【财经】判断标准（符合任一即可）：
   - 涉及公司财报、盈利、营收、股价、市值、IPO、融资、并购
   - 涉及货币政策、利率、汇率、外汇储备、金融监管政策
   - 涉及股票市场、商品价格、大宗商品、期货交易
   - 涉及金融机构、银行、保险、证券业务
   - 涉及宏观经济数据（GDP、通胀、就业等）
   
   典型示例：
   ✅ "标普500企业利润增长" → 财经
   ✅ "丹诺医药港股IPO" → 财经
   ✅ "央行虚拟货币监管通知" → 财经（金融监管）
   ✅ "华润三九净利润34.22亿元" → 财经（财报）
   
   【科技】判断标准（符合任一即可）：
   - 涉及 AI、机器学习、大模型、算法、技术创新
   - 科技公司（SpaceX、OpenAI、苹果等）的技术产品/服务
   - 新技术发布、技术突破、研发进展
   - 涉及网络安全、漏洞、技术架构
   - 涉及新能源技术、电池技术、自动驾驶
   
   典型示例：
   ✅ "Claude Code AI智能体" → 科技
   ✅ "SpaceX火星计划推迟" → 科技
   ✅ "苹果CarPlay接入AI" → 科技
   
   【社会政治】判断标准（符合任一即可）：
   - 涉及政治人物言行、选举、政府决策
   - 涉及社会事件、公共政策（非金融类）、法律法规
   - 涉及国际关系、地缘政治、贸易摩擦
   - 涉及社会民生、教育、医疗政策（非商业类）
   
   典型示例：
   ✅ "特朗普言论引发争议" → 社会政治
   ✅ "美国通过新的教育法案" → 社会政治
   
   边界案例说明：
   ⚠️ "央行虚拟货币监管" → 财经（金融监管属于财经范畴）
   ⚠️ "FDA打击假药" → 财经（市场监管，影响医药行业）

2. **5维度评分**（1-10分）：
   - 重要性（权重{sc.importance*100:.0f}%）：对行业/市场/社会的影响程度
   - 时效性（权重{sc.timeliness*100:.0f}%）：新闻的及时性和当前相关性
   - 技术深度（权重{sc.technical_depth*100:.0f}%）：技术内容的深度和专业性
   - 受众广度（权重{sc.audience_breadth*100:.0f}%）：影响的人群范围
   - 实用性（权重{sc.practicality*100:.0f}%）：对读者的实际参考价值

    3. **总分**：加权平均分（保留1位小数）

3. **详细摘要**：严格按照4句话结构生成，必须包含具体事实和数据：
    
    【强制四句结构】
    第1句（核心事件）：谁在什么时候做了什么，使用完整主谓宾结构
    第2句（数据支撑）：包含至少1个具体数字（金额、百分比、时间）和1个公司/产品名称
    第3句（影响分析）：对行业、市场、用户的具体实际影响，禁止空洞评价性语言
    第4句（展望/分析）：引用专家观点或分析未来趋势，如无则分析当前状况或潜在后果
    
    【质量要求】
    - 总字数80-200字，信息密度高
    - 至少包含3个具体名词或专有名词
    - 至少进行1项具体的因果分析
    
    【禁止使用的模板化表达】
    - ❌ "对...有重要影响"
    - ❌ "具有很高的时效性"
    - ❌ "值得关注"
    - ❌ "体现了..."
    - ❌ "对...有重要意义"
    - ❌ "时效性强"
    - ❌ "受众广度高"
    
    【摘要优化示例对比】
    ❌ 不足示例："大科技公司花费6500亿美元，市场对此表示不满。"
       → 问题：只有2句话，缺少数据支撑和影响分析
    
    ✅ 优质示例："美国四大科技巨头（亚马逊、谷歌、微软、Meta）2026年计划投入6500亿美元发展AI，规模创历史新高。
       这一支出相当于美国GDP的2.5%，与上世纪曼哈顿计划等国家级投资项目规模相当。
       巨额投入可能导致AI芯片、高端人才等关键资源出现全球性短缺，同时加速行业垄断格局形成。
       华尔街分析师警告，若投资回报不及预期，可能引发科技股估值大规模调整，冲击整个市场信心。"

【输出格式】JSON数组，每条新闻一个对象：
{{
  "news_index": 1,
  "chinese_title": "中文新闻标题（12-25字，简洁有力）",
  "category": "财经|科技|社会政治",
  "category_confidence": 0.95,
  "importance": 8,
  "timeliness": 9,
  "technical_depth": 7,
  "audience_breadth": 6,
  "practicality": 7,
  "total_score": 7.5,
  "summary": "严格按照4句话结构生成的摘要，包含核心事件、数据支撑、影响分析和展望分析..."
}}

【重要提醒】
- 必须生成中文标题chinese_title，这是最重要的输出字段之一
- 摘要必须严格按照4句话结构，每句都要有实质内容
- 严禁使用模板化、空洞的表述"""
    
    def _format_news_item(self, item: NewsItem, index: int) -> str:
        """格式化单条新闻"""
        summary = item.summary[:300] if item.summary else "无摘要"
        return f"【新闻 {index}】\n标题: {item.title}\n来源: {item.source}\n摘要: {summary}"
