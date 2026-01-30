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


@dataclass
class OutputConfig:
    """输出配置"""
    max_news_count: int
    max_feed_items: int
    archive_days: int
    time_window_days: int


@dataclass
class FilterConfig:
    """过滤配置"""
    min_score_threshold: float
    dedup_similarity: float
    blocked_keywords: List[str]
