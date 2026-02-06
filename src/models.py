"""
数据模型模块
集中定义所有数据类，解决循环依赖问题
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict


@dataclass
class NewsItem:
    """标准化新闻条目"""
    id: str
    title: str
    link: str
    source: str
    category: str
    published_at: datetime
    summary: str = ""
    content: str = ""
    
    # AI评分后填充的字段
    ai_score: Optional[float] = None
    ai_summary: Optional[str] = None
    translated_title: Optional[str] = None
    key_points: List[str] = field(default_factory=list)
    
    # AI分类字段
    ai_category: str = ""  # 分类结果："财经" | "科技" | "社会政治"
    ai_category_confidence: float = 0.0  # 分类置信度 0-1
    
    def __post_init__(self):
        """初始化后处理"""
        if isinstance(self.published_at, str):
            from dateutil import parser as date_parser
            self.published_at = date_parser.parse(self.published_at)


@dataclass
class RSSSource:
    """RSS源配置"""
    name: str
    url: str
    weight: float = 1.0
    category: str = "未分类"
    enabled: bool = True


@dataclass
class ProviderConfig:
    """LLM提供商配置"""
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 4000
    temperature: float = 0.3
    batch_size: int = 10
    max_concurrent: int = 3


@dataclass
class ScoringCriteria:
    """评分标准"""
    importance: float = 0.30      # 重要性
    timeliness: float = 0.20      # 时效性
    technical_depth: float = 0.20  # 技术深度
    audience_breadth: float = 0.15  # 受众广度
    practicality: float = 0.15    # 实用性


@dataclass
class AIConfig:
    """AI配置（1-Pass简化版）"""
    # 核心配置（2项）
    provider: str = "zhipu"
    providers_config: Dict[str, ProviderConfig] = field(default_factory=dict)
    
    # 性能配置（4项）
    batch_size: int = 10           # 批次大小
    max_concurrent: int = 3        # 最大并发批次
    timeout_seconds: int = 90      # 超时时间
    max_output_items: int = 30     # 最大输出新闻数
    
    # 筛选配置（1项）
    diversity_weight: float = 0.3  # 多样性权重
    
    # 评分标准
    scoring_criteria: ScoringCriteria = field(default_factory=ScoringCriteria)
    
    # 回退配置（简化）
    fallback_enabled: bool = True
    fallback_chain: List[str] = field(default_factory=lambda: ["deepseek", "gemini"])


@dataclass
class OutputConfig:
    """输出配置"""
    max_news_count: int = 30
    max_feed_items: int = 50
    archive_days: int = 30
    time_window_days: int = 1
    use_smart_switch: bool = True  # 是否启用智能切换


@dataclass
class FilterConfig:
    """过滤配置"""
    min_score_threshold: float = 6.0
    dedup_similarity: float = 0.85
    blocked_keywords: List[str] = field(default_factory=list)
    use_semantic_dedup: bool = True  # 是否启用TF-IDF语义去重
    semantic_similarity: float = 0.85  # 语义相似度阈值
