"""
深度分析Prompt模板模块
负责构建用于深度分析的Prompt，支持单条和批量分析

该模块与ai_scorer.py中的评分Prompt不同，专注于：
1. 使用全文内容而非RSS摘要
2. 输出结构化分析结果而非分数
3. 关注6个维度：核心观点、关键论据、影响预测、情感倾向、可信度评分、时间戳
"""

from typing import List, Optional
from datetime import datetime
import json

# 尝试相对导入，如果失败则尝试绝对导入
try:
    from ..models import NewsItem
except (ImportError, ValueError):
    try:
        from src.models import NewsItem
    except ImportError:
        # 最后尝试当前目录导入
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from models import NewsItem


# 分析维度定义
ANALYSIS_DIMENSIONS = {
    "core_insight": {
        "name": "核心观点",
        "description": "新闻的核心主旨和关键信息，100字以内",
        "max_length": 100
    },
    "key_arguments": {
        "name": "关键论据",
        "description": "支撑核心观点的3-5个要点",
        "min_count": 3,
        "max_count": 5
    },
    "impact_forecast": {
        "name": "影响预测",
        "description": "对未来可能产生的影响和趋势分析，200字以内",
        "max_length": 200
    },
    "sentiment": {
        "name": "情感倾向",
        "description": "新闻内容的情感色彩",
        "allowed_values": ["positive", "neutral", "negative"]
    },
    "credibility_score": {
        "name": "可信度评分",
        "description": "新闻可信度评估，0-10分",
        "min_value": 0,
        "max_value": 10
    },
    "analysis_timestamp": {
        "name": "分析时间戳",
        "description": "分析完成的时间，ISO 8601格式"
    }
}


def build_deep_analysis_prompt(news_item: NewsItem) -> str:
    """
    构建单条新闻深度分析Prompt
    
    参数:
        news_item: NewsItem对象，包含新闻信息
    
    返回:
        str: 深度分析Prompt字符串
    """
    # 获取新闻主要内容（优先使用全文内容，其次摘要）
    content = news_item.full_content or news_item.summary or ""
    
    # 根据新闻类别调整分析重点
    category_hint = _get_category_hint(news_item)
    
    prompt = f"""
你是一位资深新闻分析师，擅长深度解读和结构化分析。请对以下新闻进行深度分析。

【新闻基本信息】
标题: {news_item.translated_title or news_item.title}
来源: {news_item.source}
发布时间: {news_item.published_at.strftime('%Y-%m-%d %H:%M') if hasattr(news_item.published_at, 'strftime') else str(news_item.published_at)}
原始分类: {news_item.category}
AI预分类: {news_item.ai_category if hasattr(news_item, 'ai_category') else 'N/A'}

{category_hint}

【新闻全文内容】
{_truncate_content(content, max_length=8000)}

【分析维度说明】
请从以下6个维度进行深度分析：

1. 核心观点 (core_insight)
   - 提炼新闻的核心主旨和关键信息
   - 字数限制：100字以内
   - 要点：是什么、为什么重要、对谁有影响

2. 关键论据 (key_arguments)
   - 列出3-5个支撑核心观点的关键论据
   - 每个论据应简明扼要
   - 按重要程度排序，最重要的放在前面

3. 影响预测 (impact_forecast)
   - 分析新闻可能产生的影响和未来趋势
   - 字数限制：200字以内
   - 包括：短期影响、长期影响、潜在风险、机会

4. 情感倾向 (sentiment)
   - 判断新闻内容的情感色彩
   - 选项：positive (积极/利好), neutral (中性/客观), negative (消极/利空)
   - 依据：用词倾向、语调、观点表达

5. 可信度评分 (credibility_score)
   - 评估新闻的可信度，0-10分
   - 评分标准：
     9-10分：权威来源、数据详实、逻辑严谨、多方验证
     7-8分：可靠来源、逻辑清晰、有数据支撑
     5-6分：来源一般、信息基本可信、逻辑合理
     3-4分：来源存疑、信息不完整、逻辑有漏洞
     0-2分：来源不可靠、信息存疑、逻辑混乱

6. 分析时间戳 (analysis_timestamp)
   - 使用ISO 8601格式：YYYY-MM-DDTHH:MM:SSZ
   - 示例：2024-01-15T10:30:00Z

【JSON输出格式】
请严格按照以下JSON格式返回分析结果，不要添加任何解释或额外文本：

{{
    "core_insight": "核心观点文字...",
    "key_arguments": ["论据1", "论据2", "论据3"],
    "impact_forecast": "影响预测文字...",
    "sentiment": "positive|neutral|negative",
    "credibility_score": 8.5,
    "analysis_timestamp": "2024-01-15T10:30:00Z"
}}

【注意事项】
1. 所有输出必须使用纯JSON格式，不要包含markdown代码块
2. 确保键名完全匹配上述格式，不要使用中文键名
3. 数组元素使用双引号包裹
4. credibility_score可以是小数，保留一位小数
5. 如果信息不足无法完成某维度分析，请给出合理推断，不要留空
"""
    
    return prompt.strip()


def build_batch_deep_analysis_prompt(news_items: List[NewsItem]) -> str:
    """
    构建批量新闻深度分析Prompt
    
    参数:
        news_items: NewsItem对象列表
    
    返回:
        str: 批量深度分析Prompt字符串
    """
    if not news_items:
        raise ValueError("新闻列表不能为空")
    
    # 构建新闻列表部分
    news_sections = []
    for i, item in enumerate(news_items, 1):
        # 获取新闻主要内容
        content = item.full_content or item.summary or ""
        
        news_sections.append(f"""
--- 新闻{i} ---
ID: {item.id}
标题: {item.translated_title or item.title}
来源: {item.source}
发布时间: {item.published_at.strftime('%Y-%m-%d %H:%M') if hasattr(item.published_at, 'strftime') else str(item.published_at)}
分类: {item.category}
AI预分类: {item.ai_category if hasattr(item, 'ai_category') else 'N/A'}
AI预分类置信度: {item.ai_category_confidence if hasattr(item, 'ai_category_confidence') else 0.0}

内容摘要:
{_truncate_content(content, max_length=2000)}
""")
    
    prompt = f"""
你是一位资深新闻分析师，擅长对多篇新闻进行批量深度分析。

【任务说明】
请对以下{len(news_items)}条新闻进行批量深度分析，为每条新闻生成独立分析结果。

【新闻列表】
{''.join(news_sections)}

【分析维度说明】
请为每条新闻从以下6个维度进行深度分析：

1. 核心观点 (core_insight)
   - 提炼新闻的核心主旨和关键信息
   - 字数限制：100字以内

2. 关键论据 (key_arguments)
   - 列出3-5个支撑核心观点的关键论据
   - 每个论据应简明扼要

3. 影响预测 (impact_forecast)
   - 分析新闻可能产生的影响和未来趋势
   - 字数限制：200字以内

4. 情感倾向 (sentiment)
   - 判断新闻内容的情感色彩
   - 选项：positive (积极/利好), neutral (中性/客观), negative (消极/利空)

5. 可信度评分 (credibility_score)
   - 评估新闻的可信度，0-10分
   - 评分标准：权威性、数据支撑、逻辑严谨性、多方验证

6. 分析时间戳 (analysis_timestamp)
   - 使用ISO 8601格式：YYYY-MM-DDTHH:MM:SSZ

【JSON输出格式】
请严格按照以下JSON数组格式返回分析结果，不要添加任何解释或额外文本：
[
    {{
        "news_index": 1,
        "core_insight": "核心观点文字...",
        "key_arguments": ["论据1", "论据2", "论据3"],
        "impact_forecast": "影响预测文字...",
        "sentiment": "positive|neutral|negative",
        "credibility_score": 8.5,
        "analysis_timestamp": "2024-01-15T10:30:00Z"
    }},
    {{
        "news_index": 2,
        "core_insight": "核心观点文字...",
        "key_arguments": ["论据1", "论据2", "论据3"],
        "impact_forecast": "影响预测文字...",
        "sentiment": "positive|neutral|negative",
        "credibility_score": 7.0,
        "analysis_timestamp": "2024-01-15T10:30:00Z"
    }},
    ...
]

【重要说明】
1. news_index必须对应新闻列表中的序号(从1开始)
2. 确保返回的是合法的JSON数组
3. 所有新闻的分析结果必须包含在同一个数组中
4. 如果某条新闻信息不足，请基于已有信息给出合理分析
5. 不要遗漏任何一条新闻
6. 分析时间戳应反映当前分析时间，建议使用当前实际时间

【批量分析优势】
- 可以对比不同新闻的观点和影响
- 可以发现不同新闻之间的关联性
- 可以整体评估新闻话题的热度和趋势
"""
    
    return prompt.strip()


def _truncate_content(content: str, max_length: int = 8000) -> str:
    """
    截断内容，避免Prompt过长
    
    参数:
        content: 原始内容
        max_length: 最大长度
    
    返回:
        str: 截断后的内容
    """
    if not content:
        return "（内容为空）"
    
    if len(content) <= max_length:
        return content
    
    # 截断到最大长度，并添加提示
    return content[:max_length] + f"\n\n[内容过长，已截断，原长度：{len(content)} 字符]"


def _get_category_hint(news_item: NewsItem) -> str:
    """
    根据新闻类别获取分析重点提示
    
    参数:
        news_item: 新闻对象
    
    返回:
        str: 类别特定的分析提示
    """
    category = news_item.ai_category or news_item.category or ""
    category_lower = category.lower()
    
    if "财经" in category_lower or "finance" in category_lower or "经济" in category_lower:
        return """
【财经新闻分析重点】
- 核心观点：关注市场影响、经济数据、政策变化
- 关键论据：数据支撑、政策细节、市场反应
- 影响预测：经济影响、市场走势、投资机会
- 情感倾向：市场情绪、政策取向、经济预期
- 可信度：数据来源、官方声明、市场验证
"""
    elif "科技" in category_lower or "tech" in category_lower or "技术" in category_lower:
        return """
【科技新闻分析重点】
- 核心观点：技术突破、创新应用、行业影响
- 关键论据：技术细节、创新点、应用场景
- 影响预测：技术发展、产业变革、社会影响
- 情感倾向：技术评价、应用前景、行业态度
- 可信度：技术验证、专家观点、实际案例
"""
    elif "社会政治" in category_lower or "政治" in category_lower or "社会" in category_lower:
        return """
【社会政治新闻分析重点】
- 核心观点：政策变化、社会事件、国际关系
- 关键论据：政策内容、事件背景、各方立场
- 影响预测：政策影响、社会反应、国际影响
- 情感倾向：舆论导向、政策取向、民意反应
- 可信度：官方声明、多方验证、事实核查
"""
    else:
        return """
【通用新闻分析重点】
- 核心观点：事件本质、关键信息、核心价值
- 关键论据：事实依据、逻辑链条、证据支撑
- 影响预测：可能后果、发展趋势、潜在影响
- 情感倾向：内容基调、观点倾向、情绪表达
- 可信度：来源权威、事实核查、逻辑严密
"""


def format_analysis_result(analysis: dict) -> str:
    """
    格式化深度分析结果为可读字符串
    
    参数:
        analysis: 深度分析结果字典
    
    返回:
        str: 格式化后的字符串
    """
    if not analysis:
        return "（分析结果为空）"
    
    # 获取情感倾向的中文描述
    sentiment_map = {
        "positive": "积极/利好",
        "neutral": "中性/客观",
        "negative": "消极/利空"
    }
    sentiment = analysis.get("sentiment", "neutral")
    sentiment_cn = sentiment_map.get(sentiment, sentiment)
    
    # 格式化时间戳
    timestamp = analysis.get("analysis_timestamp", "")
    if timestamp:
        try:
            # 尝试解析ISO格式时间
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp_formatted = dt.strftime("%Y年%m月%d日 %H:%M")
        except:
            timestamp_formatted = timestamp
    
    result = f"""
【深度分析结果】

核心观点:
{analysis.get('core_insight', '（未提供）')}

关键论据:
{chr(10).join(f'  • {arg}' for arg in analysis.get('key_arguments', [])) if analysis.get('key_arguments') else '  （未提供）'}

影响预测:
{analysis.get('impact_forecast', '（未提供）')}

情感倾向: {sentiment_cn}
可信度评分: {analysis.get('credibility_score', 'N/A')}/10
分析时间: {timestamp_formatted if 'timestamp_formatted' in locals() else timestamp}
"""
    
    return result.strip()


# 示例使用
if __name__ == "__main__":
    # 示例NewsItem对象
    example_news = NewsItem(
        id="example-123",
        title="Example News Title",
        link="https://example.com",
        source="Example Source",
        category="科技",
        published_at=datetime.now(),
        summary="This is an example summary of a technology news article.",
        content="Full content would go here...",
        full_content="This is the full content extracted from the article using trafilatura or similar tools. It contains the complete text of the news article for deep analysis.",
        translated_title="示例新闻标题",
        ai_category="科技",
        ai_category_confidence=0.85
    )
    
    # 测试单条新闻分析Prompt
    print("=== 单条新闻深度分析Prompt示例 ===")
    print(build_deep_analysis_prompt(example_news))
    print("\n" + "="*80 + "\n")
    
    # 测试批量新闻分析Prompt（使用同一个示例）
    print("=== 批量新闻深度分析Prompt示例 ===")
    print(build_batch_deep_analysis_prompt([example_news, example_news]))
    print("\n" + "="*80 + "\n")
    
    # 测试分析结果格式化
    example_analysis = {
        "core_insight": "这是一条关于人工智能技术突破的新闻，展示了新的算法在图像识别方面的显著进步。",
        "key_arguments": ["算法准确率提升了15%", "处理速度加快了30%", "能耗降低了20%"],
        "impact_forecast": "这项技术将推动计算机视觉领域的进步，可能在未来3-5年内广泛应用于安防、医疗和自动驾驶领域。",
        "sentiment": "positive",
        "credibility_score": 8.5,
        "analysis_timestamp": "2024-01-15T10:30:00Z"
    }
    
    print("=== 分析结果格式化示例 ===")
    print(format_analysis_result(example_analysis))