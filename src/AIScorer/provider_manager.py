"""
提供商管理器 - LLM提供商管理和API调用

管理14家LLM提供商的初始化、切换、回退逻辑
"""
import asyncio
import logging
import time
from typing import List, Callable, Any, Optional
from openai import AsyncOpenAI, RateLimitError
from tenacity import (
    retry, stop_after_attempt, wait_random_exponential,
    retry_if_exception_type, before_sleep_log
)

from src.models import NewsItem, AIConfig, ProviderConfig
from .rate_limiter import SimpleRateLimiter
from .error_handler import ErrorHandler

logger = logging.getLogger(__name__)


def _split_into_batches(items: list, batch_size: int) -> list:
    """
    将列表分割成多个批次

    Args:
        items: 待分割的列表
        batch_size: 每批大小

    Returns:
        list: 分割后的批次列表
    """
    return [items[i:i+batch_size] for i in range(0, len(items), batch_size)]


class ProviderManager:
    """
    LLM提供商管理器
    
    管理14家LLM提供商的初始化、切换、回退逻辑
    提供统一的API调用接口
    """
    
    def __init__(self, config: AIConfig):
        """
        初始化提供商管理器
        
        Args:
            config: AI配置对象
        """
        self.config = config
        self.fallback = config.fallback
        self.providers_config = config.providers_config
        
        # 当前提供商状态
        self._init_provider(config.provider)
        
        # API调用计数
        self.api_call_count = 0
    
    def _init_provider(self, provider_name: str):
        """
        初始化指定提供商
        
        Args:
            provider_name: 提供商名称
            
        Raises:
            ValueError: 提供商不存在
        """
        if provider_name not in self.providers_config:
            raise ValueError(f"未知的提供商: {provider_name}")
        
        provider_config = self.providers_config[provider_name]
        
        # 创建OpenAI客户端（兼容模式）
        self.client = AsyncOpenAI(
            api_key=provider_config.api_key,
            base_url=provider_config.base_url
        )
        self.model = provider_config.model
        self.current_provider_name = provider_name
        self.current_config = provider_config
        
        # 初始化速率限制器
        if provider_config.rate_limit_rpm:
            self.rate_limiter = SimpleRateLimiter(
                max_requests=provider_config.rate_limit_rpm
            )
            logger.info(
                f"[{provider_name}] 启用速率限制: "
                f"{provider_config.rate_limit_rpm} RPM"
            )
        else:
            self.rate_limiter = None
        
        logger.info(
            f"初始化AI提供商: {provider_name} "
            f"({self.model})"
        )
    
    def build_fallback_chain(self) -> List[str]:
        """
        构建回退链（去重）
        
        Returns:
            List[str]: 提供商名称列表
        """
        chain = []
        seen = set()
        
        # 1. 首选当前配置的主提供商
        if (self.current_provider_name and 
            self.current_provider_name in self.providers_config):
            chain.append(self.current_provider_name)
            seen.add(self.current_provider_name)
        
        # 2. 添加fallback_chain中配置的提供商
        for provider in self.fallback.fallback_chain:
            if (provider not in seen and 
                provider in self.providers_config):
                chain.append(provider)
                seen.add(provider)
        
        return chain
    
    async def execute_with_fallback(
        self,
        operation_name: str,
        operation_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        带自动回退的执行
        
        Args:
            operation_name: 操作名称（用于日志）
            operation_func: 操作函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 操作结果
            
        Raises:
            Exception: 所有提供商都失败时抛出最后一个异常
        """
        if not self.fallback.enabled:
            return await operation_func(*args, **kwargs)
        
        fallback_chain = self.build_fallback_chain()
        last_exception = None
        
        for provider_name in fallback_chain:
            try:
                logger.info(
                    f"🔄 尝试使用提供商: {provider_name} "
                    f"({operation_name})"
                )
                self._init_provider(provider_name)
                result = await operation_func(*args, **kwargs)
                logger.info(f"✅ 提供商 {provider_name} 调用成功")
                return result
                
            except Exception as e:
                logger.error(
                    f"❌ 提供商 {provider_name} 失败: {e}"
                )
                last_exception = e
                continue
        
        logger.error(
            f"❌ 所有AI提供商均失败 ({operation_name})"
        )
        raise last_exception
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=5, max=30),
        retry=retry_if_exception_type(RateLimitError),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def call_api(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3,
        system_message: str = None,
        is_json: bool = True
    ) -> str:
        """
        调用API（统一接口）
        
        Args:
            prompt: 用户Prompt
            max_tokens: 最大生成token数
            temperature: 温度参数
            system_message: 系统消息（可选）
            is_json: 是否需要JSON响应
            
        Returns:
            str: AI生成的响应内容
        """
        # 应用速率限制
        if self.rate_limiter:
            await self.rate_limiter.acquire()
        
        # 构建消息
        messages = []
        
        if system_message:
            messages.append({
                "role": "system",
                "content": system_message
            })
        else:
            messages.append({
                "role": "system",
                "content": "你是一位资深新闻编辑和筛选员，擅长评估新闻价值和撰写中文摘要。"
            })
        
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        # 构建响应格式
        response_format = {"type": "json_object"} if is_json else None
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format=response_format
            )
            
            self.api_call_count += 1
            
            return response.choices[0].message.content
            
        except Exception as e:
            # Special handling for 429 errors (rate limit)
            if hasattr(e, 'status') and e.status == 429:
                logger.warning(
                    f"⚠️ 收到429速率限制错误 ({self.current_provider_name})，"
                    f"额外等待10秒后重试"
                )
                await asyncio.sleep(10)
            
            ErrorHandler.log_error(
                context=f"API调用 ({self.current_provider_name})",
                error=e,
                logger=logger
            )
            raise
    
    async def call_batch_api(
        self,
        prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.3
    ) -> str:
        """
        调用批量评分API
        
        Args:
            prompt: 批量评分Prompt
            max_tokens: 最大生成token数
            temperature: 温度参数
            
        Returns:
            str: AI生成的响应内容
        """
        return await self.call_api(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_message=(
                "你是一位资深新闻编辑和筛选员，擅长评估新闻价值"
                "和撰写中文摘要。你必须严格返回JSON数组格式。"
            ),
            is_json=True
        )
    
    async def call_deep_analysis_api(
        self,
        prompt: str,
        max_tokens: int = 10000,
        temperature: float = 0.3
    ) -> str:
        """
        调用深度分析API
        
        Args:
            prompt: 深度分析Prompt
            max_tokens: 最大生成token数
            temperature: 温度参数
            
        Returns:
            str: AI生成的响应内容
        """
        return await self.call_api(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_message=(
                "你是一位资深新闻分析师，擅长多维度深度分析。"
                "你必须严格返回JSON数组格式，不要添加任何其他文字。"
            ),
            is_json=True
        )
    
    async def call_single_scoring_api(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.3
    ) -> str:
        """
        调用单条评分API
        
        Args:
            prompt: 单条评分Prompt
            max_tokens: 最大生成token数
            temperature: 温度参数
            
        Returns:
            str: AI生成的响应内容
        """
        return await self.call_api(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_message="你是一位资深新闻编辑，擅长评估新闻价值和撰写中文摘要。",
            is_json=True
        )
    
    def get_provider_info(self) -> dict:
        """
        获取当前提供商信息
        
        Returns:
            dict: 提供商信息
        """
        return {
            'name': self.current_provider_name,
            'model': self.model,
            'base_url': self.current_config.base_url,
            'temperature': self.current_config.temperature,
            'max_tokens': getattr(self.current_config, 'max_tokens', 1000),
        }
    
    def get_api_call_count(self) -> int:
        """
        获取API调用计数
        
        Returns:
            int: 调用次数
        """
        return self.api_call_count
    
    def reset_api_call_count(self):
        """重置API调用计数"""
        self.api_call_count = 0
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            dict: 统计信息
        """
        return {
            'api_call_count': self.api_call_count,
            'current_provider': self.current_provider_name,
            'current_model': self.model,
            'fallback_enabled': self.fallback.enabled,
            'fallback_chain': self.build_fallback_chain(),
        }
    
    def is_provider_available(self, provider_name: str) -> bool:
        """
        检查提供商是否可用
        
        Args:
            provider_name: 提供商名称
            
        Returns:
            bool: 是否可用
        """
        return provider_name in self.providers_config
    
    def get_available_providers(self) -> List[str]:
        """
        获取可用的提供商列表
        
        Returns:
            List[str]: 提供商名称列表
        """
        return list(self.providers_config.keys())
    
    async def switch_provider(self, provider_name: str):
        """
        切换提供商
        
        Args:
            provider_name: 提供商名称
            
        Raises:
            ValueError: 提供商不存在
        """
        if not self.is_provider_available(provider_name):
            raise ValueError(f"提供商不可用: {provider_name}")
        
        self._init_provider(provider_name)
        logger.info(f"切换到提供商: {provider_name}")
    
    async def test_provider(self, provider_name: str) -> bool:
        """
        测试提供商是否可用

        Args:
            provider_name: 提供商名称

        Returns:
            bool: 是否可用
        """
        try:
            original_provider = self.current_provider_name
            self._init_provider(provider_name)

            # 发送一个简单的测试请求
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "test"}
                ],
                max_tokens=5
            )

            # 恢复原来的提供商
            self._init_provider(original_provider)

            return True

        except Exception as e:
            logger.error(f"测试提供商 {provider_name} 失败: {e}")
            return False

    # ==================== 真批处理方法 ====================

    async def _process_batch_with_fallback(
        self,
        batch: List[NewsItem],
        batch_index: int,
        total_batches: int,
        call_batch_api_func: Callable,
        **api_kwargs
    ) -> tuple:
        """
        处理单个批次的API调用（带回退机制）

        Args:
            batch: 当前批次的新闻项列表
            batch_index: 批次索引（从1开始）
            total_batches: 总批次数
            call_batch_api_func: 批量API调用函数
            **api_kwargs: 传递给API调用函数的额外参数

        Returns:
            tuple: (批次索引, API响应内容或None, 异常或None)
        """
        try:
            logger.info(
                f"📦 处理批次 {batch_index}/{total_batches} "
                f"({len(batch)} 条新闻)"
            )

            # 调用批量API
            response = await call_batch_api_func(**api_kwargs)
            self.api_call_count += 1

            return (batch_index, response, None)

        except Exception as e:
            logger.warning(
                f"⚠️ 批次 {batch_index}/{total_batches} API调用失败: {e}"
            )
            return (batch_index, None, e)

    async def execute_batch_with_fallback(
        self,
        items: List[NewsItem],
        batch_size: int,
        call_batch_api_func: Callable,
        fallback_single_func: Callable = None,
        default_score: float = 5.0,
        **api_kwargs
    ) -> tuple:
        """
        执行带真批处理和回退的批量API调用

        降级策略：
        1. 首选：批量API调用（按batch_size分批）
        2. 降级1：单条API调用
        3. 降级2：使用默认分数

        Args:
            items: 新闻项列表
            batch_size: 每批大小
            call_batch_api_func: 批量API调用函数
            fallback_single_func: 单条处理函数（可选）
            default_score: 默认分数
            **api_kwargs: 传递给API调用函数的额外参数

        Returns:
            tuple: (results: List[dict], api_call_count: int)
        """
        if not items:
            return [], 0

        original_count = len(items)
        logger.info(f"🚀 开始真批处理: {original_count} 条新闻")

        # 1. 分割成批次
        batches = _split_into_batches(items, batch_size)
        total_batches = len(batches)
        logger.info(f"📦 分割为 {total_batches} 个批次 (每批 ≤{batch_size})")

        # 2. 尝试批量处理
        batch_results = {}
        batch_failures = []

        for batch in batches:
            batch_idx = batches.index(batch) + 1
            batch_idx_outcome, response, error = (
                await self._process_batch_with_fallback(
                    batch=batch,
                    batch_index=batch_idx,
                    total_batches=total_batches,
                    call_batch_api_func=call_batch_api_func,
                    prompt=api_kwargs.get('prompt'),
                    max_tokens=api_kwargs.get('max_tokens', 8000),
                    temperature=api_kwargs.get('temperature', 0.3)
                )
            )

            if response:
                batch_results[batch_idx_outcome] = response
            else:
                batch_failures.append((batch_idx_outcome, batch, error))

        # 3. 如果有失败的批次，尝试回退
        if batch_failures:
            logger.warning(
                f"⚠️ {len(batch_failures)}/{total_batches} 批次失败，尝试回退..."
            )

            for batch_idx, batch, error in batch_failures:
                if fallback_single_func:
                    # 降级1：单条处理
                    logger.info(
                        f"🔄 批次 {batch_idx} 降级为单条处理 "
                        f"({len(batch)} 条)"
                    )

                    for item in batch:
                        try:
                            result = await fallback_single_func(
                                item=item,
                                **api_kwargs
                            )
                            if result:
                                item.ai_score = result.get('score', default_score)
                            else:
                                item.ai_score = default_score
                        except Exception as e:
                            logger.error(
                                f"❌ 单条处理失败: {e}，使用默认分数"
                            )
                            item.ai_score = default_score
                else:
                    # 降级2：使用默认分数
                    logger.warning(
                        f"⚠️ 批次 {batch_idx} 使用默认分数 {default_score}"
                    )
                    for item in batch:
                        item.ai_score = default_score

        # 4. 合并结果
        all_results = []
        for batch_idx in range(1, total_batches + 1):
            if batch_idx in batch_results:
                all_results.append(batch_results[batch_idx])

        total_api_calls = self.api_call_count

        logger.info(
            f"✅ 真批处理完成: {original_count} 条 → "
            f"{len(all_results)} 批成功, {total_api_calls} 次API调用"
        )

        return all_results, total_api_calls
