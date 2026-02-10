"""
News Coma 项目常量定义

集中管理魔法字符串、默认值和配置常量
"""
from dataclasses import dataclass
from enum import Enum


class NewsCategory(str, Enum):
    """新闻分类枚举"""
    FINANCE = "财经"
    TECH = "科技"
    SOCIAL = "社会政治"
    OTHER = "其他"
    
    @classmethod
    def get_default(cls) -> "NewsCategory":
        """获取默认分类"""
        return cls.SOCIAL


@dataclass(frozen=True)
class DefaultScores:
    """
    默认评分常量
    
    当API调用失败或内容被过滤时使用这些默认值
    """
    CATEGORY = "社会政治"
    CONFIDENCE = 0.5
    IMPORTANCE = 3
    TIMELINESS = 3
    TECHNICAL_DEPTH = 3
    AUDIENCE_BREADTH = 3
    PRACTICALITY = 3
    TOTAL_SCORE = 3.0
    
    @classmethod
    def to_dict(cls, index: int, reason: str = "") -> dict:
        """生成默认分数字典"""
        summary = f"[处理失败: {reason[:50]}]" if reason else "[处理失败给予默认分]"
        return {
            "news_index": index,
            "chinese_title": None,
            "category": cls.CATEGORY,
            "category_confidence": cls.CONFIDENCE,
            "importance": cls.IMPORTANCE,
            "timeliness": cls.TIMELINESS,
            "technical_depth": cls.TECHNICAL_DEPTH,
            "audience_breadth": cls.AUDIENCE_BREADTH,
            "practicality": cls.PRACTICALITY,
            "total_score": cls.TOTAL_SCORE,
            "summary": summary
        }


# 有效分类集合（用于验证）
VALID_CATEGORIES = {cat.value for cat in NewsCategory}


# 文件路径常量
class Paths:
    """文件路径常量"""
    DEFAULT_OUTPUT_DIR = "docs"
    DEFAULT_ARCHIVE_DIR = "archive"
    DEFAULT_FEED_PATH = "feed.xml"
    DEFAULT_HISTORY_PATH = "data/history.json"
    DEFAULT_CONFIG_PATH = "config.yaml"


# 评分权重常量（应与 config.yaml 保持一致）
class ScoringWeights:
    """评分权重常量"""
    IMPORTANCE = 0.30
    TIMELINESS = 0.20
    TECHNICAL_DEPTH = 0.20
    AUDIENCE_BREADTH = 0.15
    PRACTICALITY = 0.15
    
    @classmethod
    def validate(cls) -> bool:
        """验证权重总和为1.0"""
        total = (
            cls.IMPORTANCE + cls.TIMELINESS + cls.TECHNICAL_DEPTH +
            cls.AUDIENCE_BREADTH + cls.PRACTICALITY
        )
        return abs(total - 1.0) < 0.001


# 默认配置值
class Defaults:
    """默认配置值"""
    # AI 配置
    BATCH_SIZE = 10
    MAX_CONCURRENT = 3
    TIMEOUT_SECONDS = 90
    MAX_OUTPUT_ITEMS = 30
    MAX_RETRIES = 2
    RETRY_DELAY = 1.0
    
    # 评分配置
    MIN_SCORE_THRESHOLD = 6.0
    DEFAULT_SCORE_ON_ERROR = 3.0
    DEFAULT_SCORE_ON_PARSE_ERROR = 5.0
    DEFAULT_DIMENSION_SCORE = 5
    MAX_ERROR_MESSAGE_LENGTH = 50
    
    # 去重配置
    DEDUP_SIMILARITY = 0.85
    SEMANTIC_SIMILARITY = 0.85
    MAX_CONTENT_LENGTH = 5000
    
    # RSS 配置
    TIME_WINDOW_DAYS = 1
    MAX_FEED_ITEMS = 50


# 日志消息模板
class LogMessages:
    """日志消息模板"""
    # RSS 获取
    FETCH_START = "📡 开始获取RSS新闻..."
    FETCH_SUCCESS = "✓ {source}: 获取 {count} 条"
    FETCH_INCREMENTAL = "✓ {source}: 增量获取 {count} 条 (上次: {last_fetch})"
    FETCH_FULL = "✓ {source}: 全量获取 {count} 条"
    FETCH_ERROR = "❌ 获取 {source} 失败: {error}"
    
    # AI 评分
    AI_SCORE_START = "🤖 开始AI评分(共 {count} 条)..."
    BATCH_PROCESS = "处理批次 {batch_id}: {count} 条新闻"
    BATCH_COMPLETE = "批次 {batch_id} 处理完成: {count} 条"
    BATCH_RETRY = "批次 {batch_id} 第 {attempt} 次尝试失败，{delay:.1f}秒后重试"
    BATCH_RETRY_EXHAUSTED = "批次 {batch_id} 重试耗尽"
    APPLY_DEFAULT_SCORES = "已为批次应用默认分数 ({count} 条): {reason}"
    
    # 多样性选择
    DIVERSITY_STAGE1 = "📊 混合方案-第一阶段(固定保障): {counts}, 共{total}条"
    DIVERSITY_STAGE2 = "📊 混合方案-第二阶段(比例分配): {counts}, 实际分配{total}条"
    DIVERSITY_STAGE3 = "📊 混合方案-第三阶段(轮询补充): {count}条"
    FINAL_DISTRIBUTION = "📊 最终分类分布: {distribution}"
    
    # Fallback
    CONTENT_FILTER_TRIGGERED = "主提供商 {provider} 触发内容过滤 (错误码: {code})"
    FALLBACK_ATTEMPT = "尝试fallback提供商: {provider}"
    FALLBACK_FAILED = "回退提供商 {provider} 失败: {error}"
    FALLBACK_SUCCESS = "Fallback处理成功: {provider}"


# 错误消息
class ErrorMessages:
    """错误消息常量"""
    CONFIG_NOT_FOUND = "配置文件不存在: {path}"
    PROVIDER_NOT_FOUND = "未找到提供商配置: {provider}"
    API_TIMEOUT = "API调用超时 ({timeout}s)"
    API_ERROR = "API调用失败: {error}"
    CONTENT_FILTER = "内容过滤错误 (提供商: {provider}, 错误码: {code})"
    FALLBACK_EXHAUSTED = "所有fallback提供商均失败"
    INVALID_RESPONSE_FORMAT = "响应格式错误: {detail}"
    PARSE_ERROR = "解析失败: {error}"


# 提示词模板（Prompt 片段）
class PromptTemplates:
    """提示词模板常量"""
    SYSTEM_PROMPT = (
        "你是一位资深新闻编辑，擅长评估新闻价值和撰写中文摘要。"
        "请对每条新闻进行分类和评分，返回JSON数组格式。"
    )
    
    SCORING_DIMENSIONS = """
请按以下5维度评分（1-10分）：
  1. 重要性（权重30%）
  2. 时效性（权重20%）
  3. 技术深度（权重20%）
  4. 受众广度（权重15%）
  5. 实用性（权重15%）

计算加权总分并给出中文总结。
"""


# 验证所有常量
def validate_constants() -> list[str]:
    """
    验证所有常量定义的正确性
    
    Returns:
        错误消息列表，空列表表示验证通过
    """
    errors = []
    
    # 验证权重
    if not ScoringWeights.validate():
        errors.append("评分权重总和不等于1.0")
    
    # 验证分类
    if len(VALID_CATEGORIES) != len(NewsCategory):
        errors.append("VALID_CATEGORIES 与 NewsCategory 不一致")
    
    return errors


if __name__ == "__main__":
    # 运行验证
    errors = validate_constants()
    if errors:
        print("常量验证失败:")
        for error in errors:
            print(f"  - {error}")
        exit(1)
    else:
        print("✓ 所有常量验证通过")
