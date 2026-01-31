"""
异步流水线处理器
将RSS新闻处理流程(Fetch → Preprocess → AI Score → Generate)并行化
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, AsyncIterator, Dict
from contextlib import asynccontextmanager

from src.models import NewsItem
from src.monitoring import PerformanceMonitor, StageType

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """流水线异常"""
    pass


@dataclass
class PipelineConfig:
    """流水线配置"""
    max_queue_size: int = 100  # 每个队列最大大小
    timeout: Optional[float] = None  # 任务超时时间
    stop_on_critical_error: bool = True  # 关键错误时停止流水线


class PipelineStage(ABC):
    """流水线阶段基类"""
    
    def __init__(self, name: str, concurrency: int = 3,
                 error_policy: str = 'skip'):
        self.name = name
        self.concurrency = concurrency
        self.error_policy = error_policy  # 'skip', 'retry', 'stop'
        self.errors: List[Exception] = []
    
    @abstractmethod
    async def process(self, item: Any) -> Any:
        """处理单个项"""
        pass
    
    def record_error(self, error: Exception):
        """记录错误"""
        self.errors.append(error)
        logger.warning(f"阶段 {self.name} 记录错误: {error}")
    
    def get_error_count(self) -> int:
        """获取错误数量"""
        return len(self.errors)
    
    def clear_errors(self):
        """清空错误记录"""
        self.errors.clear()


@dataclass
class PipelineStats:
    """流水线统计信息"""
    stage_name: str
    processed_count: int = 0
    error_count: int = 0
    total_duration: float = 0.0
    throughput: float = 0.0  # 项/秒
    avg_processing_time: float = 0.0
    
    def update(self, duration: float, success: bool = True):
        """更新统计"""
        self.processed_count += 1
        if not success:
            self.error_count += 1
        self.total_duration += duration
        
        # 重新计算平均值和吞吐量
        if self.processed_count > 0:
            self.avg_processing_time = self.total_duration / self.processed_count
        if self.total_duration > 0:
            self.throughput = self.processed_count / self.total_duration


class AsyncPipeline:
    """异步流水线处理器"""
    
    def __init__(self, config: Optional[PipelineConfig] = None,
                 monitor: Optional[PerformanceMonitor] = None):
        """
        初始化异步流水线
        
        Args:
            config: 流水线配置
            monitor: 性能监控器
        """
        self.config = config or PipelineConfig()
        self.monitor = monitor
        
        self.stages: List[PipelineStage] = []
        self.stage_tasks: List[asyncio.Task] = []
        self.queues: List[asyncio.Queue] = []
        self.stage_stats: Dict[str, PipelineStats] = {}
        
        self._running = False
        self._stop_event = asyncio.Event()
        self._exception: Optional[Exception] = None
    
    def add_stage(self, stage: PipelineStage) -> 'AsyncPipeline':
        """
        添加处理阶段，支持链式调用
        
        Args:
            stage: 流水线阶段实例
            
        Returns:
            self (支持链式调用)
        """
        self.stages.append(stage)
        self.stage_stats[stage.name] = PipelineStats(stage_name=stage.name)
        
        # 创建有界队列作为阶段间缓冲区
        queue_size = self.config.max_queue_size
        if self.stages:
            # 后续阶段使用独立队列
            self.queues.append(asyncio.Queue(maxsize=queue_size))
        
        logger.debug(f"添加阶段: {stage.name} (并发度: {stage.concurrency})")
        return self
    
    async def run(self, source: AsyncIterator[Any]) -> AsyncIterator[Any]:
        """
        运行流水线
        
        Args:
            source: 数据源异步迭代器
            
        Yields:
            处理完成的结果
        """
        if not self.stages:
            raise PipelineError("流水线至少需要一个阶段")
        
        self._running = True
        self._stop_event.clear()
        self._exception = None
        
        try:
            # 启动所有阶段的任务
            await self._start_stage_tasks()
            
            # 向第一个队列推送数据
            try:
                async for item in source:
                    if not self._running:
                        break
                    
                    # 检查是否发生异常
                    if self._exception:
                        logger.error(f"流水线发生异常: {self._exception}")
                        break
                    
                    # 使用超时防止阻塞
                    try:
                        await asyncio.wait_for(
                            self.queues[0].put(item),
                            timeout=self.config.timeout
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"向阶段 {self.stages[0].name} 输入队列写入超时")
                        continue
                    
            except Exception as e:
                logger.error(f"数据源读取失败: {e}")
                self._exception = e
                raise
            
            finally:
                # 发送结束信号
                for queue in self.queues:
                    try:
                        await queue.put(None)
                    except Exception as e:
                        logger.warning(f"发送结束信号失败: {e}")
                
                # 等待所有阶段任务完成
                await self._wait_stage_tasks()
        
        except Exception as e:
            logger.error(f"流水线运行失败: {e}")
            raise
        
        finally:
            self._running = False
            
            # 从最后一个队列产出结果
            if self.queues:
                while not self.queues[-1].empty():
                    item = await self.queues[-1].get()
                    if item is None:
                        break
                    yield item
    
    async def _start_stage_tasks(self):
        """启动所有阶段任务"""
        self.stage_tasks = []
        
        for i, stage in enumerate(self.stages):
            input_queue = self.queues[i] if i > 0 else None
            output_queue = self.queues[i] if i < len(self.queues) else None
            
            # 为最后一个阶段创建一个特殊的输出队列
            if i == len(self.stages) - 1:
                output_queue = asyncio.Queue(maxsize=self.config.max_queue_size)
                self.queues.append(output_queue)
            
            task = asyncio.create_task(
                self._run_stage(stage, input_queue, output_queue),
                name=f"stage_{stage.name}"
            )
            task.add_done_callback(self._stage_task_done_callback)
            self.stage_tasks.append(task)
    
    async def _run_stage(self, stage: PipelineStage,
                        input_queue: Optional[asyncio.Queue],
                        output_queue: Optional[asyncio.Queue]):
        """运行单个阶段"""
        if input_queue is None:
            # 第一个阶段应该从source接收数据
            return
        
        semaphore = asyncio.Semaphore(stage.concurrency)
        stage_name = stage.name
        
        logger.debug(f"阶段 {stage_name} 开始运行")
        
        while self._running and not self._stop_event.is_set():
            try:
                # 从输入队列获取数据（带超时）
                item = await asyncio.wait_for(
                    input_queue.get(),
                    timeout=1.0  # 定期检查停止事件
                )
                
                if item is None:
                    # 收到结束信号，传递给下一阶段
                    if output_queue:
                        await output_queue.put(None)
                    break
                
                # 使用信号量限制并发处理
                processed_item = await self._process_with_semaphore(
                    stage, item, semaphore, stage_name
                )
                
                if processed_item is not None and output_queue:
                    # 将处理结果放入输出队列
                    await output_queue.put(processed_item)
                
                # 标记任务完成
                input_queue.task_done()
                
            except asyncio.TimeoutError:
                # 超时检查，继续循环
                continue
            
            except asyncio.CancelledError:
                logger.debug(f"阶段 {stage_name} 任务被取消")
                break
            
            except Exception as e:
                logger.error(f"阶段 {stage_name} 处理失败: {e}")
                
                # 根据错误策略处理
                if stage.error_policy == 'stop':
                    self._exception = e
                    self._stop_event.set()
                    break
                elif stage.error_policy == 'retry':
                    # 记录错误但继续处理
                    stage.record_error(e)
                else:  # 'skip'
                    stage.record_error(e)
                    # 标记任务完成（跳过此项）
                    if input_queue:
                        input_queue.task_done()
        
        logger.debug(f"阶段 {stage_name} 运行结束")
    
    async def _process_with_semaphore(self, stage: PipelineStage, item: Any,
                                     semaphore: asyncio.Semaphore, stage_name: str) -> Any:
        """使用信号量限制并发处理"""
        async with semaphore:
            try:
                # 性能监控
                if self.monitor:
                    start_time = asyncio.get_event_loop().time()
                    
                    async with self.monitor.astage(stage_name):
                        result = await stage.process(item)
                    
                    end_time = asyncio.get_event_loop().time()
                    duration = end_time - start_time
                else:
                    start_time = asyncio.get_event_loop().time()
                    result = await stage.process(item)
                    end_time = asyncio.get_event_loop().time()
                    duration = end_time - start_time
                
                # 更新统计
                stats = self.stage_stats[stage_name]
                stats.update(duration, success=True)
                
                return result
                
            except Exception as e:
                # 更新错误统计
                stats = self.stage_stats[stage_name]
                stats.update(0.0, success=False)
                
                # 根据错误策略处理
                if stage.error_policy == 'stop':
                    raise
                elif stage.error_policy == 'retry':
                    logger.warning(f"阶段 {stage_name} 处理失败，将重试: {e}")
                    # 这里可以添加重试逻辑
                    raise
                else:  # 'skip'
                    logger.warning(f"阶段 {stage_name} 处理失败，跳过此项: {e}")
                    stage.record_error(e)
                    return None
    
    def _stage_task_done_callback(self, task: asyncio.Task):
        """阶段任务完成回调"""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"阶段任务异常: {e}")
            if not self._exception:
                self._exception = e
            self._stop_event.set()
    
    async def _wait_stage_tasks(self):
        """等待所有阶段任务完成"""
        if self.stage_tasks:
            # 等待所有任务完成或取消
            done, pending = await asyncio.wait(
                self.stage_tasks,
                timeout=self.config.timeout
            )
            
            # 取消仍在运行的任务
            for task in pending:
                task.cancel()
            
            # 等待取消的任务完成
            if pending:
                await asyncio.wait(pending, timeout=1.0)
    
    def stop(self):
        """停止流水线"""
        self._running = False
        self._stop_event.set()
        
        # 取消所有任务
        for task in self.stage_tasks:
            if not task.done():
                task.cancel()
    
    def get_stats(self) -> Dict[str, PipelineStats]:
        """获取所有阶段统计信息"""
        return self.stage_stats.copy()
    
    def get_total_processed_count(self) -> int:
        """获取总处理项数"""
        total = 0
        for stats in self.stage_stats.values():
            total += stats.processed_count
        return total
    
    def get_total_error_count(self) -> int:
        """获取总错误数"""
        total = 0
        for stage in self.stages:
            total += stage.get_error_count()
        return total
    
    def print_stats_summary(self):
        """打印统计摘要"""
        logger.info("=" * 60)
        logger.info("📊 流水线性能统计摘要")
        logger.info("=" * 60)
        
        for stage_name, stats in self.stage_stats.items():
            logger.info(f"阶段: {stage_name}")
            logger.info(f"  处理数量: {stats.processed_count}")
            logger.info(f"  错误数量: {stats.error_count}")
            logger.info(f"  总耗时: {stats.total_duration:.2f}s")
            logger.info(f"  平均处理时间: {stats.avg_processing_time*1000:.1f}ms")
            logger.info(f"  吞吐量: {stats.throughput:.2f}项/秒")
            logger.info("-" * 40)
        
        logger.info(f"总处理项数: {self.get_total_processed_count()}")
        logger.info(f"总错误数: {self.get_total_error_count()}")
        logger.info("=" * 60)


# 便捷装饰器
def pipeline_stage(name: str, concurrency: int = 3, error_policy: str = 'skip'):
    """
    流水线阶段装饰器
    
    Args:
        name: 阶段名称
        concurrency: 并发度
        error_policy: 错误策略 ('skip', 'retry', 'stop')
    
    Returns:
        装饰器函数
    """
    def decorator(func):
        class DecoratedStage(PipelineStage):
            def __init__(self):
                super().__init__(name, concurrency, error_policy)
            
            async def process(self, item):
                return await func(item)
        
        return DecoratedStage()
    return decorator