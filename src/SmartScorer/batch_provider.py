"""BatchProvider - 1-Pass 批量API管理"""

import asyncio
import logging
from typing import Dict, Optional, Any
from openai import AsyncOpenAI, RateLimitError

from src.models import AIConfig

logger = logging.getLogger(__name__)


class BatchProvider:
    """批量API提供商管理器"""

    SYSTEM_PROMPT = (
        "你是一位资深新闻编辑，擅长评估新闻价值和撰写中文摘要。"
        "请对每条新闻进行分类和评分，返回JSON数组格式。"
    )

    def __init__(self, config: AIConfig):
        self.config = config
        self.provider_name = config.provider
        self.provider_config = config.providers_config.get(config.provider)

        if not self.provider_config:
            raise ValueError(f"未找到提供商配置: {config.provider}")

        self.client = AsyncOpenAI(
            api_key=self.provider_config.api_key,
            base_url=self.provider_config.base_url
        )
        self.model = self.provider_config.model
        self.api_call_count = 0

        logger.info(f"BatchProvider初始化: {self.provider_name} ({self.model})")
    
    async def call_batch_api(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None
    ) -> str:
        """调用批量评分API"""
        max_tokens = max_tokens or self.provider_config.max_tokens
        temperature = temperature or self.provider_config.temperature
        timeout = timeout or self.config.timeout_seconds

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        try:
            logger.debug(f"调用API: {self.provider_name}, timeout={timeout}s")

            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"}
                ),
                timeout=timeout
            )

            self.api_call_count += 1
            return response.choices[0].message.content

        except asyncio.TimeoutError:
            logger.error(f"API调用超时 ({timeout}s)")
            raise
        except RateLimitError as e:
            logger.warning(f"速率限制: {e}")
            raise
        except Exception as e:
            logger.error(f"API调用失败: {e}")
            raise
    
    async def call_with_fallback(
        self,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """带自动回退的API调用"""
        try:
            return await self.call_batch_api(prompt, max_tokens, temperature)
        except Exception as e:
            logger.warning(f"主提供商 {self.provider_name} 失败: {e}")

        if not self.config.fallback_enabled:
            raise Exception("回退未启用，主提供商失败")

        for fallback_name in self.config.fallback_chain:
            if fallback_name not in self.config.providers_config:
                continue

            try:
                logger.info(f"尝试回退提供商: {fallback_name}")
                return await self._call_provider(
                    fallback_name, prompt, max_tokens, temperature
                )
            except Exception as e:
                logger.warning(f"回退提供商 {fallback_name} 失败: {e}")

        raise Exception("所有提供商均失败")

    async def _call_provider(
        self,
        provider_name: str,
        prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None
    ) -> str:
        """调用指定提供商"""
        config = self.config.providers_config[provider_name]
        client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=config.model,
                messages=messages,
                max_tokens=max_tokens or config.max_tokens,
                temperature=temperature or config.temperature,
                response_format={"type": "json_object"}
            ),
            timeout=self.config.timeout_seconds
        )

        logger.info(f"提供商 {provider_name} 调用成功")
        return response.choices[0].message.content
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "api_call_count": self.api_call_count
        }

    def reset_stats(self):
        self.api_call_count = 0
