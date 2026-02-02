"""
速率限制器 - 简单的异步令牌桶实现

从原 ai_scorer.py 的 SimpleRateLimiter 类提取，使其独立可复用
"""
import asyncio
import time
from typing import Optional


class SimpleRateLimiter:
    """
    简单的异步令牌桶速率限制器
    
    用于控制API调用频率，支持多个LLM提供商的速率限制
    """
    
    def __init__(
        self, 
        max_requests: int = 60, 
        time_window: float = 60.0,
        timeout: float = 120.0
    ):
        """
        初始化速率限制器
        
        Args:
            max_requests: 在time_window内的最大请求数
            time_window: 时间窗口（秒）
            timeout: 获取令牌的最大等待时间（秒）
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.timeout = timeout
        
        # 令牌桶状态
        self.tokens = float(max_requests)
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """
        获取一个令牌，必要时等待
        
        Returns:
            bool: 是否成功获取令牌
            
        Raises:
            TimeoutError: 等待超时
        """
        async with self.lock:
            start_time = time.time()
            
            # 补充令牌
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(
                float(self.max_requests),
                self.tokens + elapsed * (self.max_requests / self.time_window)
            )
            self.last_update = now
            
            # 如果没有令牌，等待
            while self.tokens < 1:
                now = time.time()
                elapsed = now - self.last_update
                
                # 补充令牌
                self.tokens = min(
                    float(self.max_requests),
                    self.tokens + elapsed * (self.max_requests / self.time_window)
                )
                self.last_update = now
                
                if self.tokens < 1:
                    # 计算等待时间
                    wait_time = self.time_window / self.max_requests
                    
                    # 检查是否超时
                    if time.time() - start_time + wait_time > self.timeout:
                        raise TimeoutError(
                            f"速率限制等待超时（>{self.timeout}秒）"
                        )
                    
                    # 释放锁，让其他任务有机会执行
                    self.lock.release()
                    try:
                        await asyncio.sleep(wait_time)
                    finally:
                        await self.lock.acquire()
                
                # 更新状态
                now = time.time()
                elapsed = now - self.last_update
                self.tokens = min(
                    float(self.max_requests),
                    self.tokens + elapsed * (self.max_requests / self.time_window)
                )
                self.last_update = now
            
            # 消耗一个令牌
            self.tokens -= 1
            self.last_update = time.time()
            
            return True
    
    def get_available_tokens(self) -> float:
        """
        获取当前可用的令牌数
        
        Returns:
            float: 可用令牌数
        """
        now = time.time()
        elapsed = now - self.last_update
        
        available = self.tokens + elapsed * (self.max_requests / self.time_window)
        return min(float(self.max_requests), available)
    
    def reset(self):
        """重置速率限制器"""
        self.tokens = float(self.max_requests)
        self.last_update = time.time()


class AdaptiveRateLimiter:
    """
    自适应速率限制器
    
    根据API响应动态调整速率限制
    """
    
    def __init__(
        self,
        initial_max_requests: int = 60,
        time_window: float = 60.0,
        backoff_factor: float = 0.8,
        recovery_factor: float = 1.1
    ):
        """
        初始化自适应速率限制器
        
        Args:
            initial_max_requests: 初始最大请求数
            time_window: 时间窗口（秒）
            backoff_factor: 退避因子（遇到错误时降低速率）
            recovery_factor: 恢复因子（成功时逐渐恢复速率）
        """
        self.base_limiter = SimpleRateLimiter(initial_max_requests, time_window)
        self.current_max_requests = initial_max_requests
        self.backoff_factor = backoff_factor
        self.recovery_factor = recovery_factor
        
        # 统计
        self.success_count = 0
        self.error_count = 0
    
    async def acquire(self) -> bool:
        """获取令牌"""
        success = await self.base_limiter.acquire()
        
        if success:
            self.success_count += 1
            # 逐渐恢复速率
            if self.current_max_requests < self.base_limiter.max_requests:
                self.current_max_requests = min(
                    self.base_limiter.max_requests,
                    self.current_max_requests * self.recovery_factor
                )
        else:
            self.error_count += 1
        
        return success
    
    def on_error(self):
        """当API调用出错时调用，降低速率"""
        self.error_count += 1
        self.current_max_requests = max(
            1,  # 最小1个请求
            int(self.current_max_requests * self.backoff_factor)
        )
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'current_rate': self.current_max_requests,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'success_rate': (
                self.success_count / (self.success_count + self.error_count)
                if (self.success_count + self.error_count) > 0 else 0
            )
        }
