"""
错误处理器 - 统一错误处理和默认值设置

解决原 ai_scorer.py 中7处重复的错误处理逻辑（34行重复代码）
"""
from typing import List, Dict, Any
from src.models import NewsItem


class ErrorHandler:
    """
    统一错误处理器
    
    集中管理所有错误处理逻辑，统一设置默认值
    替代原代码中7处重复的错误处理代码
    """
    
    # 错误消息映射
    ERROR_MESSAGES = {
        'json_decode': "JSON解析失败",
        'parse_failed': "解析失败",
        'no_response': "批处理解析失败",
        'api_error': "API调用失败",
        'single_fail': "单条处理失败",
        'batch_fail': "批量处理失败",
        'deep_analysis_fail': "深度分析失败",
        'general': "处理失败",
    }
    
    # 错误类型常量
    JSON_DECODE = 'json_decode'
    PARSE_FAILED = 'parse_failed'
    NO_RESPONSE = 'no_response'
    API_ERROR = 'api_error'
    SINGLE_FAIL = 'single_fail'
    BATCH_FAIL = 'batch_fail'
    DEEP_ANALYSIS_FAIL = 'deep_analysis_fail'
    GENERAL = 'general'
    
    @classmethod
    def apply_default_values(
        cls, 
        item: NewsItem, 
        error_type: str = 'general'
    ) -> NewsItem:
        """
        统一设置默认值
        
        替代原代码中7处重复的错误处理代码：
        - 行号248-251, 554-559, 568-573, 578-583, 602-605, 728-731, 735-738
        
        Args:
            item: 新闻项
            error_type: 错误类型
            
        Returns:
            NewsItem: 设置了默认值的新闻项
        """
        message = cls.ERROR_MESSAGES.get(error_type, cls.ERROR_MESSAGES['general'])
        
        item.ai_score = 5.0
        item.translated_title = item.title
        item.ai_summary = message
        item.key_points = []
        
        # 如果新闻项支持ai_category_confidence，则设置
        if hasattr(item, 'ai_category_confidence'):
            item.ai_category_confidence = 0.0
        
        return item
    
    @classmethod
    def apply_batch_defaults(
        cls,
        items: List[NewsItem],
        error_type: str = 'general'
    ) -> List[NewsItem]:
        """
        批量应用默认值
        
        Args:
            items: 新闻项列表
            error_type: 错误类型
            
        Returns:
            List[NewsItem]: 设置了默认值的新闻项列表
        """
        return [cls.apply_default_values(item, error_type) for item in items]
    
    @classmethod
    def handle_exception(
        cls,
        item: NewsItem,
        exception: Exception,
        error_type: str = 'general',
        logger=None
    ) -> NewsItem:
        """
        处理异常并应用默认值
        
        Args:
            item: 新闻项
            exception: 异常对象
            error_type: 错误类型
            logger: 日志记录器（可选）
            
        Returns:
            NewsItem: 设置了默认值的新闻项
        """
        if logger:
            logger.error(f"处理异常: {exception}")
        
        return cls.apply_default_values(item, error_type)
    
    @classmethod
    def create_error_response(
        cls,
        items: List[NewsItem],
        error_type: str = 'general',
        logger=None
    ) -> List[NewsItem]:
        """
        创建错误响应（批量）
        
        Args:
            items: 新闻项列表
            error_type: 错误类型
            logger: 日志记录器（可选）
            
        Returns:
            List[NewsItem]: 设置了默认值的新闻项列表
        """
        if logger:
            logger.error(f"批量处理失败，使用默认值，错误类型: {error_type}")
        
        return cls.apply_batch_defaults(items, error_type)
    
    @staticmethod
    def log_error(
        context: str,
        error: Exception,
        logger=None,
        level: str = 'error'
    ):
        """
        记录错误日志
        
        Args:
            context: 错误上下文
            error: 异常对象
            logger: 日志记录器
            level: 日志级别
        """
        message = f"[{context}] {type(error).__name__}: {error}"
        
        if logger:
            if level == 'error':
                logger.error(message)
            elif level == 'warning':
                logger.warning(message)
            else:
                logger.info(message)
        else:
            print(message)


class ErrorSeverity:
    """错误严重级别"""
    
    CRITICAL = 'critical'  # 需要立即处理
    HIGH = 'high'          # 影响主要功能
    MEDIUM = 'medium'      # 影响部分功能
    LOW = 'low'            # 可忽略


class ErrorCategory:
    """错误类别"""
    
    JSON_PARSE = 'json_parse'
    API_CALL = 'api_call'
    VALIDATION = 'validation'
    NETWORK = 'network'
    UNKNOWN = 'unknown'


class StructuredError:
    """
    结构化错误信息
    
    提供更详细的错误信息，便于追踪和调试
    """
    
    def __init__(
        self,
        message: str,
        severity: str = ErrorSeverity.MEDIUM,
        category: str = ErrorCategory.UNKNOWN,
        context: Dict[str, Any] = None,
        original_exception: Exception = None
    ):
        self.message = message
        self.severity = severity
        self.category = category
        self.context = context or {}
        self.original_exception = original_exception
        self.timestamp = __import__('datetime').datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'message': self.message,
            'severity': self.severity,
            'category': self.category,
            'context': self.context,
            'timestamp': self.timestamp.isoformat(),
            'original_exception': (
                str(self.original_exception) 
                if self.original_exception else None
            )
        }
    
    def log(self, logger=None):
        """记录错误日志"""
        ErrorHandler.log_error(
            context=f"{self.category}[{self.severity}]",
            error=self.message,
            logger=logger
        )
