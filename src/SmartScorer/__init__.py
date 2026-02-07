"""
SmartScorer - 1-Pass AI 新闻评分系统

将原有的2-pass评分系统重构为1-pass，大幅减少API调用和代码复杂度。

架构:
- smart_scorer.py: 核心协调器
- batch_provider.py: 批量API管理
- prompt_engine.py: Prompt生成
- result_processor.py: 结果解析
"""

from .smart_scorer import SmartScorer
from .batch_provider import BatchProvider
from .prompt_engine import PromptEngine
from .result_processor import ResultProcessor

__version__ = "1.0.0"
__all__ = ["SmartScorer", "BatchProvider", "PromptEngine", "ResultProcessor"]
