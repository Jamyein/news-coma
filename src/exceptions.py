"""
自定义异常模块
"""


class ContentFilterError(Exception):
    """
    内容安全过滤错误
    
    当AI提供商返回内容过滤错误时抛出，如智谱AI的错误码1301
    
    Attributes:
        message: 错误消息
        error_code: 提供商错误码
        provider: 提供商名称
        error_data: 原始错误数据
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: str = None, 
        provider: str = None,
        error_data: dict = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.provider = provider
        self.error_data = error_data or {}
        
    def __str__(self):
        parts = [self.args[0] if self.args else "内容过滤错误"]
        if self.error_code:
            parts.append(f"错误码: {self.error_code}")
        if self.provider:
            parts.append(f"提供商: {self.provider}")
        return " | ".join(parts)


class APIError(Exception):
    """通用API错误"""
    pass


class RateLimitError(APIError):
    """速率限制错误"""
    pass


class TimeoutError(APIError):
    """超时错误"""
    pass
