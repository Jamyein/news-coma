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
    
    # Pass2阶段影响预测（新增）
    impact_forecast: Optional[str] = None  # 影响预测文本
    
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
    
    # 板块配额配置（固定比例40%:30%:30%）
    category_quota_finance: float = 0.40             # 财经配额40%
    category_quota_tech: float = 0.30                # 科技配额30%
    category_quota_politics: float = 0.30            # 社会政治配额30%
    
    # 并行批处理配置（新增）
    use_parallel_batches: bool = False              # 是否启用并行批处理
    max_parallel_batches: int = 3                   # 最大并行批次
    
    # 超时控制配置（新增）
    batch_timeout_seconds: int = 120                # 批次超时时间（秒）
    timeout_fallback_strategy: str = "single"       # 超时降级策略

    # 板块最低保障配置（新增）
    category_min_guarantee: Dict[str, int] = field(default_factory=lambda: {
        'finance': 3,
        'tech': 2,
        'politics': 2
    })

    # 流式JSON解析配置（新增）
    use_streaming_json_parser: bool = True          # 启用流式JSON解析，边接收边解析，解决截断问题
    streaming_json_priority: bool = True            # 优先使用流式JSON解析（失败时自动降级到传统方式）
    streaming_json_buffer_size: int = 4096          # 流式解析缓冲区大小（字节）
    streaming_json_max_depth: int = 10              # 最大JSON嵌套深度


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


# ==================== 1-Pass 简化配置模型 ====================

@dataclass
class OnePassProviderConfig:
    """1-Pass LLM提供商配置（简化版）"""
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 4000
    temperature: float = 0.3
    batch_size: int = 10
    max_concurrent: int = 3


@dataclass
class OnePassScoringCriteria:
    """1-Pass 评分标准"""
    importance: float = 0.30      # 重要性
    timeliness: float = 0.20    # 时效性
    technical_depth: float = 0.20  # 技术深度
    audience_breadth: float = 0.15  # 受众广度
    practicality: float = 0.15    # 实用性


@dataclass
class OnePassAIConfig:
    """1-Pass AI配置（简化版 - 8项核心配置）"""
    # 核心配置（5项）
    provider: str = "zhipu"                    # 当前提供商
    providers_config: Dict[str, OnePassProviderConfig] = field(default_factory=dict)
    
    # 性能配置（3项）
    batch_size: int = 10                       # 批次大小
    max_concurrent: int = 3                    # 最大并发批次
    timeout_seconds: int = 90                  # 超时时间
    
    # 筛选配置（2项）
    max_output_items: int = 30                 # 最大输出新闻数
    diversity_weight: float = 0.3              # 多样性权重
    
    # 评分标准
    scoring_criteria: OnePassScoringCriteria = field(default_factory=OnePassScoringCriteria)
    
    # 回退配置（简化）
    fallback_enabled: bool = True
    fallback_chain: List[str] = field(default_factory=lambda: ["deepseek", "gemini"])
