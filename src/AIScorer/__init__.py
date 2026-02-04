"""
AIScorer 模块 - AI新闻评分系统

扁平化结构，所有组件在同一目录下

文件结构:
├── __init__.py              # 包初始化
├── ai_scorer.py            # 主协调者类
├── provider_manager.py     # LLM提供商管理
├── prompt_builder.py       # Prompt构建
├── response_parser.py      # 响应解析
├── error_handler.py        # 错误处理
├── scoring_strategy.py     # 评分策略
├── category_classifier.py  # 分类器
└── rate_limiter.py         # 速率限制器
"""

# 使用相对导入
from .ai_scorer import AIScorer
from .provider_manager import ProviderManager
from .prompt_builder import PromptBuilder
from .response_parser import ResponseParser
from .error_handler import ErrorHandler
from .scoring_strategy import (
    BaseScoringStrategy,
    FinanceScoringStrategy,
    TechnologyScoringStrategy,
    PoliticsScoringStrategy,
    GenericScoringStrategy,
    ScoringStrategyFactory,
    ScoringDimension
)
from .category_classifier import CategoryClassifier
from .adaptive_classifier import AdaptiveNewsClassifier, ClassifiedItem
from .rate_limiter import SimpleRateLimiter, AdaptiveRateLimiter
from .adaptive_batcher import AdaptiveBatchProcessor, BatchContext, BatchHistoryEntry

__all__ = [
    # 主类
    'AIScorer',
    
    # 组件类
    'ProviderManager',
    'PromptBuilder',
    'ResponseParser',
    'ErrorHandler',
    'CategoryClassifier',
    'AdaptiveNewsClassifier',
    'ClassifiedItem',
    'SimpleRateLimiter',
    'AdaptiveRateLimiter',
    
    # 离散优化类
    'AdaptiveBatchProcessor',
    'BatchContext',
    'BatchHistoryEntry',
    
    # 策略类
    'BaseScoringStrategy',
    'FinanceScoringStrategy',
    'TechnologyScoringStrategy',
    'PoliticsScoringStrategy',
    'GenericScoringStrategy',
    'ScoringStrategyFactory',
    'ScoringDimension',
]

__version__ = '2.0.0'
__author__ = 'News Coma Team'
