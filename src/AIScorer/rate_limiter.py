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


class SafeRateLimiter(SimpleRateLimiter):
    """
    线程安全的速率限制器，带请求队列管理
    
    扩展SimpleRateLimiter，添加：
    - 并发控制（通过Semaphore限制最大并发数）
    - 请求队列管理（防止令牌不足时的请求堆积）
    - 防止429错误，通过正确控制并发API调用
    """
    
    def __init__(
        self,
        max_requests: int = 60,
        time_window: float = 60.0,
        timeout: float = 120.0,
        max_concurrent: int = 3
    ):
        """
        初始化安全速率限制器
        
        Args:
            max_requests: 在time_window内的最大请求数
            time_window: 时间窗口（秒）
            timeout: 获取令牌的最大等待时间（秒）
            max_concurrent: 最大并发请求数（默认3）
        """
        super().__init__(max_requests, time_window, timeout)
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.request_queue: asyncio.Queue[asyncio.Future] = asyncio.Queue()
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def _start_queue_processor(self):
        """启动队列处理器任务"""
        if self._queue_processor_task is None or self._queue_processor_task.done():
            self._running = True
            self._queue_processor_task = asyncio.create_task(self._process_queue())
    
    async def _stop_queue_processor(self):
        """停止队列处理器任务"""
        self._running = False
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
    
    async def _process_queue(self):
        """
        处理请求队列的后台任务
        
        持续从队列中获取待处理的Future，并尝试为其分配令牌
        """
        while self._running:
            try:
                # 等待队列中有请求或超时
                future = await asyncio.wait_for(
                    self.request_queue.get(),
                    timeout=0.1
                )
                
                # 尝试从父类获取令牌
                try:
                    success = await super().acquire()
                    if success and not future.done():
                        future.set_result(True)
                except TimeoutError as e:
                    if not future.done():
                        future.set_exception(e)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
                
            except asyncio.TimeoutError:
                # 队列为空，继续循环
                continue
            except asyncio.CancelledError:
                # 任务被取消，退出循环
                break
    
    async def _acquire_with_queue(self) -> bool:
        """
        使用队列管理获取令牌
        
        Returns:
            bool: 是否成功获取令牌
            
        Raises:
            TimeoutError: 等待超时
        """
        # 检查是否有可用令牌，避免队列堆积
        if self.get_available_tokens() < 1:
            # 令牌不足，等待直到有令牌可用
            wait_time = self.time_window / self.max_requests
            await asyncio.sleep(wait_time)
        
        # 创建Future用于等待结果
        future = asyncio.get_event_loop().create_future()
        
        # 将请求放入队列
        self.request_queue.put_nowait(future)
        
        # 启动队列处理器（如果尚未启动）
        await self._start_queue_processor()
        
        # 等待Future完成（获取令牌或超时）
        try:
            result = await asyncio.wait_for(future, timeout=self.timeout)
            return result
        except asyncio.TimeoutError as e:
            # 超时，尝试取消Future
            if not future.done():
                future.cancel()
            raise TimeoutError(
                f"速率限制等待超时（>{self.timeout}秒）"
            ) from e
    
    async def acquire(self) -> bool:
        """
        获取一个令牌，带有并发控制和队列管理
        
        Returns:
            bool: 是否成功获取令牌
            
        Raises:
            TimeoutError: 等待超时
        """
        # 使用Semaphore控制并发数
        async with self.semaphore:
            # 使用队列管理令牌获取
            return await self._acquire_with_queue()
    
    def get_queue_size(self) -> int:
        """
        获取当前队列中的请求数
        
        Returns:
            int: 队列中的请求数
        """
        return self.request_queue.qsize()
    
    def get_concurrent_count(self) -> int:
        """
        获取当前并发使用的令牌数
        
        Returns:
            int: 当前并发请求数
        """
        return self.max_concurrent - self.semaphore._value
    
    def __del__(self):
        """清理资源"""
        if hasattr(self, '_running'):
            self._running = False
        if hasattr(self, '_queue_processor_task') and self._queue_processor_task:
            if not self._queue_processor_task.done():
                self._queue_processor_task.cancel()


class AdaptiveRateLimiter(SimpleRateLimiter):
    """
    Context-aware adaptive rate limiter with PID control
    
    Extends SimpleRateLimiter to provide intelligent rate limiting that:
    - Uses PID control for smooth rate adjustments

    - Adapts based on success rate, errors, system load, and request priority
    - Auto-tunes PID parameters based on performance metrics
    - Provides context-aware rate limiting for different request types
    """
    
    def __init__(
        self,
        max_requests: int = 60,
        time_window: float = 60.0,
        target_success_rate: float = 0.90,
        min_rate: int = 5,
        max_rate: Optional[int] = None,
        # PID parameters
        kp: float = 10.0,
        ki: float = 0.1,
        kd: float = 0.0,
        # Adjustment weights
        error_weight: float = 2.0,
        load_weight: float = 0.5,
        priority_weight: float = 0.3
    ):
        """
        Initialize adaptive rate limiter with PID control
        
        Args:
            max_requests: Initial maximum requests per time_window
            time_window: Time window in seconds
            target_success_rate: Target success rate (0.0-1.0)
            min_rate: Minimum allowed requests per time_window
            max_rate: Maximum allowed requests per time_window (None for no limit)
            kp: Proportional gain for PID controller
            ki: Integral gain for PID controller
            kd: Derivative gain for PID controller
            error_weight: Weight for error-based rate adjustment
            load_weight: Weight for load-based rate adjustment
            priority_weight: Weight for priority-based rate adjustment
        """
        super().__init__(max_requests, time_window)
        
        # Rate limits
        self.initial_max_requests = max_requests
        self.current_rate = float(max_requests)
        self.min_rate = float(min_rate)
        self.max_rate = float(max_rate) if max_rate else float(max_requests * 2)
        self.target_success_rate = target_success_rate
        
        # PID controller state
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_error = 0.0
        
        # Adjustment weights
        self.error_weight = error_weight
        self.load_weight = load_weight
        self.priority_weight = priority_weight
        
        # Performance tracking
        self.request_history = []
        self.error_history = []
        self.success_count = 0
        self.error_count = 0
        self.total_requests = 0
        
        # Auto-tuning state
        self.performance_history = []
        self.auto_tuning_enabled = True
        self.last_tuning_time = time.time()
        
        # Lock for thread-safe operations
        self.history_lock = asyncio.Lock()
    
    async def acquire_with_context(self, context: dict) -> bool:
        """
        Acquire token with context-aware adaptive rate limiting
        
        Args:
            context: Dictionary containing context information:
                - 'priority': float (0.0-1.0, higher is more important)
                - 'load': float (0.0-1.0, current system load)
                - 'provider': str (provider name)
        
        Returns:
            bool: True if token acquired successfully
        
        Raises:
            TimeoutError: If waiting for token times out
        """
        # Calculate context-based rate adjustment
        priority = context.get('priority', 0.5)
        load = context.get('load', 0.0)
        
        # Apply context-aware adjustment
        priority_adjustment = self._calculate_priority_adjustment(priority)
        load_adjustment = self._calculate_load_adjustment(load)
        
        # Temporarily adjust rate based on context
        original_rate = self.current_rate
        adjusted_rate = original_rate * priority_adjustment * load_adjustment
        adjusted_rate = max(self.min_rate, min(self.max_rate, adjusted_rate))
        
        # Update effective rate temporarily
        self.current_rate = adjusted_rate
        
        try:
            # Acquire token with adjusted rate
            success = await self.acquire()
            return success
        finally:
            # Restore original rate for next calculation
            self.current_rate = original_rate
    
    async def acquire(self) -> bool:
        """
        Acquire token with rate adjustment based on performance
        
        Returns:
            bool: True if token acquired successfully
        
        Raises:
            TimeoutError: If waiting for token times out
        """
        # Use adaptive rate in parent class
        self.max_requests = int(self.current_rate)
        
        # Call parent acquire method
        success = await super().acquire()
        
        if success:
            # Track request
            await self._track_request(success=True)
            
            # Auto-tune if enabled and enough history
            if self.auto_tuning_enabled:
                await self._check_auto_tuning()
        else:
            await self._track_request(success=False)
        
        return success
    
    def calculate_optimal_rate(self, current_success_rate: float) -> float:
        """
        Calculate optimal rate using PID control
        
        Args:
            current_success_rate: Current success rate (0.0-1.0)
        
        Returns:
            float: Optimal rate adjustment factor
        """
        # Calculate error (difference from target)
        error = self.target_success_rate - current_success_rate
        
        # PID calculation
        proportional = self.kp * error
        
        # Update integral term with anti-windup
        self.integral += error
        integral_term = self.ki * self.integral
        # Anti-windup: clamp integral
        integral_term = max(-10.0, min(10.0, integral_term))
        
        # Derivative term
        derivative = self.kd * (error - self.last_error)
        self.last_error = error
        
        # Calculate rate adjustment
        adjustment = proportional + integral_term + derivative
        
        # Apply adjustment to current rate
        new_rate = self.current_rate + adjustment
        
        # Clamp to bounds
        new_rate = max(self.min_rate, min(self.max_rate, new_rate))
        
        # Update current rate
        self.current_rate = new_rate
        
        return new_rate
    
    def _calculate_error_adjustment(self, recent_errors: list) -> float:
        """
        Calculate error-based rate adjustment
        
        Args:
            recent_errors: List of recent error timestamps/counters
        
        Returns:
            float: Adjustment factor (0.0-1.0 where 1.0 means no adjustment)
        """
        if not recent_errors:
            return 1.0
        
        error_count = len(recent_errors)
        error_rate = error_count / max(1, self.total_requests)
        
        # If error rate is high, reduce rate significantly
        if error_rate > 0.1:  # More than 10% errors
            return 1.0 - min(0.9, error_rate * self.error_weight)
        elif error_rate > 0.05:  # 5-10% errors
            return 1.0 - min(0.5, error_rate * self.error_weight * 0.5)
        
        return 1.0
    
    def _calculate_load_adjustment(self, current_load: float) -> float:
        """
        Calculate load-based rate adjustment
        
        Args:
            current_load: Current system load (0.0-1.0)
        
        Returns:
            float: Adjustment factor (0.5-1.0)
        """
        # Higher load -> lower rate
        if current_load > 0.8:  # Very high load
            return 0.5
        elif current_load > 0.6:  # High load
            return 0.7
        elif current_load > 0.4:  # Medium load
            return 0.85
        
        return 1.0
    
    def _calculate_priority_adjustment(self, priority: float) -> float:
        """
        Calculate priority-based rate adjustment
        
        Args:
            priority: Request priority (0.0-1.0, higher is more important)
        
        Returns:
            float: Adjustment factor (0.8-1.2)
        """
        # Higher priority -> slight rate boost
        # Lower priority -> slight rate reduction
        if priority > 0.8:  # Very high priority
            return 1.2
        elif priority > 0.6:  # High priority
            return 1.1
        elif priority < 0.3:  # Low priority
            return 0.8
        elif priority < 0.5:  # Medium-low priority
            return 0.9
        
        return 1.0
    
    async def adaptive_tuning(self, performance_metrics: dict) -> dict:
        """
        Auto-tune PID parameters based on performance metrics
        
        Args:
            performance_metrics: Dictionary containing:
                - 'success_rate': float
                - 'latency_ms': float
                - 'error_rate': float
                - 'stability_score': float
        
        Returns:
            dict: Updated PID parameters and metrics
        """
        success_rate = performance_metrics.get('success_rate', 0.0)
        latency_ms = performance_metrics.get('latency_ms', 0)
        error_rate = performance_metrics.get('error_rate', 0.0)
        stability = performance_metrics.get('stability_score', 0.5)
        
        # Store performance history
        self.performance_history.append({
            'timestamp': time.time(),
            'metrics': performance_metrics.copy()
        })
        
        # Keep only last 100 entries
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
        
        # Adjust PID parameters based on performance
        if len(self.performance_history) >= 10:
            # Calculate trends
            recent_rates = [
                h['metrics']['success_rate']
                for h in self.performance_history[-10:]
            ]
            rate_variance = sum(
                (r - sum(recent_rates) / len(recent_rates)) ** 2
                for r in recent_rates
            ) / len(recent_rates)
            
            # If highly unstable (oscillating), reduce gains
            if rate_variance > 0.05 and stability < 0.5:
                self.kp = max(2.0, self.kp * 0.9)
                self.ki = max(0.01, self.ki * 0.95)
                self.kd = min(1.0, self.kd + 0.1)
            
            # If too slow to respond to errors, increase gains
            elif error_rate > 0.1 and success_rate < self.target_success_rate:
                self.kp = min(20.0, self.kp * 1.1)
                self.ki = min(1.0, self.ki * 1.1)
            
            # If response is good but slow, adjust derivative
            elif stability > 0.8 and latency_ms > 1000:
                self.kd = max(0.0, self.kd - 0.05)
        
        # Apply optimal rate calculation
        optimal_rate = self.calculate_optimal_rate(success_rate)
        
        return {
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'optimal_rate': optimal_rate,
            'current_rate': self.current_rate
        }
    
    async def _track_request(self, success: bool):
        """
        Track request result for performance monitoring
        
        Args:
            success: Whether the request was successful
        """
        async with self.history_lock:
            self.total_requests += 1
            
            if success:
                self.success_count += 1
                self.request_history.append({
                    'timestamp': time.time(),
                    'success': True
                })
            else:
                self.error_count += 1
                self.error_history.append(time.time())
                self.request_history.append({
                    'timestamp': time.time(),
                    'success': False
                })
            
            # Keep only last 1000 entries
            if len(self.request_history) > 1000:
                self.request_history = self.request_history[-1000:]
            if len(self.error_history) > 1000:
                self.error_history = self.error_history[-1000:]
            
            # Periodically adjust rate based on performance
            if self.total_requests % 10 == 0:
                current_success_rate = self._get_success_rate()
                self.calculate_optimal_rate(current_success_rate)
    
    async def _check_auto_tuning(self):
        """
        Check if auto-tuning should be performed
        """
        now = time.time()
        
        # Auto-tune every 60 seconds or every 100 requests
        if (now - self.last_tuning_time > 60 and 
            len(self.performance_history) > 0):
            
            performance_metrics = {
                'success_rate': self._get_success_rate(),
                'error_rate': self._get_error_rate(),
                'latency_ms': 0,  # Would need latency tracking
                'stability_score': self._get_stability_score()
            }
            
            await self.adaptive_tuning(performance_metrics)
            self.last_tuning_time = now
    
    def _get_success_rate(self) -> float:
        """Calculate current success rate"""
        total = self.success_count + self.error_count
        return self.success_count / total if total > 0 else 1.0
    
    def _get_error_rate(self) -> float:
        """Calculate current error rate"""
        total = self.success_count + self.error_count
        return self.error_count / total if total > 0 else 0.0
    
    def _get_stability_score(self) -> float:
        """
        Calculate stability score based on rate variance
        
        Returns:
            float: Stability score (0.0-1.0, higher is more stable)
        """
        if len(self.performance_history) < 5:
            return 0.5
        
        recent_rates = [
            h['metrics'].get('success_rate', 0.0)
            for h in self.performance_history[-5:]
        ]
        
        avg_rate = sum(recent_rates) / len(recent_rates)
        variance = sum((r - avg_rate) ** 2 for r in recent_rates) / len(recent_rates)
        
        # Lower variance = higher stability
        stability = max(0.0, 1.0 - variance * 10)
        return stability
    
    def get_stats(self) -> dict:
        """
        Get comprehensive statistics about the rate limiter
        
        Returns:
            dict: Statistics including rate, success rate, PID state, etc.
        """
        return {
            'current_rate': self.current_rate,
            'initial_rate': self.initial_max_requests,
            'min_rate': self.min_rate,
            'max_rate': self.max_rate,
            'target_success_rate': self.target_success_rate,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'total_requests': self.total_requests,
            'success_rate': self._get_success_rate(),
            'error_rate': self._get_error_rate(),
            'pid': {
                'kp': self.kp,
                'ki': self.ki,
                'kd': self.kd,
                'integral': self.integral,
                'last_error': self.last_error
            },
            'stability_score': self._get_stability_score(),
            'auto_tuning_enabled': self.auto_tuning_enabled
        }
    
    def on_error(self, error_type: Optional[str] = None):
        """
        Handle API error and adjust rate accordingly
        
        Args:
            error_type: Type of error (e.g., '429', 'timeout', etc.)
        """
        async def _handle_error():
            await self._track_request(success=False)
            
            # Extra penalty for rate limit errors
            if error_type == '429':
                self.current_rate = max(
                    self.min_rate,
                    self.current_rate * 0.5
                )
            else:
                self.current_rate = max(
                    self.min_rate,
                    self.current_rate * 0.8
                )
        
        # Run async handler
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_handle_error())
            else:
                # If event loop not running, just update synchronously
                self.error_count += 1
                self.total_requests += 1
                if error_type == '429':
                    self.current_rate = max(
                        self.min_rate,
                        self.current_rate * 0.5
                    )
                else:
                    self.current_rate = max(
                        self.min_rate,
                        self.current_rate * 0.8
                    )
        except RuntimeError:
            # Fallback to synchronous update
            self.error_count += 1
            self.total_requests += 1
            self.current_rate = max(
                self.min_rate,
                self.current_rate * 0.8
            )
    
    def reset(self):
        """Reset the rate limiter to initial state"""
        super().reset()
        self.current_rate = float(self.initial_max_requests)
        self.integral = 0.0
        self.last_error = 0.0
        self.success_count = 0
        self.error_count = 0
        self.total_requests = 0
        self.request_history = []
        self.error_history = []
        self.performance_history = []
