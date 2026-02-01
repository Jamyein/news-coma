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
    
    # AI分类字段（新增）
    ai_category: str = ""  # 分类结果："财经" | "科技" | "社会政治"
    ai_category_confidence: float = 0.0  # 分类置信度 0-1
    
    # 预分类字段（新增，用于Pass 1差异化评分）
    pre_category: str = ""  # 预分类结果："财经" | "科技" | "社会政治" | ""
    pre_category_confidence: float = 0.0  # 预分类置信度
    
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
    max_tokens: int = 2000
    temperature: float = 0.3
    rate_limit_rpm: Optional[int] = None
    batch_size: int = 5
    max_concurrent: int = 3


@dataclass
class FallbackConfig:
    """自动回退配置"""
    enabled: bool = False
    max_retries_per_provider: int = 2
    fallback_chain: List[str] = field(default_factory=list)


@dataclass
class AIConfig:
    """AI配置（支持多提供商）"""
    provider: str                                    # 当前使用的提供商名称
    providers_config: Dict[str, ProviderConfig]      # 所有提供商配置
    fallback: FallbackConfig                         # 回退配置
    scoring_criteria: Dict[str, float]
    retry_attempts: int = 3
    cache_ttl_hours: int = 24                        # AI评分缓存有效期(小时)
    use_true_batch: bool = True                      # 是否启用真批处理
    true_batch_size: int = 10                        # 真批处理每批数量
    use_2pass: bool = True                           # 是否启用2-Pass评分
    pass1_threshold: float = 7.0                     # Pass 1预筛阈值
    pass1_max_items: int = 40                        # Pass 1最大保留数量
    
    # 三大板块差异化评分配置（新增）
    pass1_threshold_finance: float = 5.5             # 财经新闻阈值
    pass1_threshold_tech: float = 6.0                # 科技新闻阈值
    pass1_threshold_politics: float = 5.5            # 社会政治新闻阈值
    pass1_use_category_specific: bool = True         # 启用三大板块差异化评分
    
    # 板块配额配置（固定比例 40%:30%:30%）
    category_quota_finance: float = 0.40             # 财经配额 40%
    category_quota_tech: float = 0.30                # 科技配额 30%
    category_quota_politics: float = 0.30            # 社会政治配额 30%


@dataclass
class OutputConfig:
    """输出配置"""
    max_news_count: int
    max_feed_items: int
    archive_days: int
    time_window_days: int
    use_smart_switch: bool = True  # 是否启用智能切换（首次用archive，后续用latest）


@dataclass
class FilterConfig:
    """过滤配置"""
    min_score_threshold: float
    dedup_similarity: float
    blocked_keywords: List[str]
    use_semantic_dedup: bool = True                 # 是否启用TF-IDF语义去重
    semantic_similarity: float = 0.85               # 语义相似度阈值
