"""
内容获取模块
使用 trafilatura 库从URL获取文章全文
支持并发控制和超时设置，无需缓存（RSS增量获取确保不重复）
"""
import asyncio
import logging
from typing import Optional, List, Dict, Tuple
from functools import partial

# trafilatura 2.0.0 imports
from trafilatura.settings import Extractor

logger = logging.getLogger(__name__)

# 全局设置
DEFAULT_CONCURRENCY = 5
DEFAULT_TIMEOUT_MIN = 10  # 秒
DEFAULT_TIMEOUT_MAX = 30  # 秒


class ContentFetcher:
    """内容获取器 - 使用 trafilatura 获取文章全文"""
    
    def __init__(
        self, 
        max_concurrent: int = DEFAULT_CONCURRENCY,
        timeout_range: Tuple[int, int] = (DEFAULT_TIMEOUT_MIN, DEFAULT_TIMEOUT_MAX)
    ):
        """
        初始化内容获取器
        
        Args:
            max_concurrent: 最大并发数，默认为5
            timeout_range: 超时范围（最小，最大）秒，默认为(10, 30)
        """
        self.max_concurrent = max_concurrent
        self.timeout_range = timeout_range
        
        # 检查 trafilatura 库是否可用
        self._trafilatura_available = True
        try:
            import trafilatura
            self._trafilatura = trafilatura
            logger.info("✅ trafilatura 库加载成功")
        except ImportError as e:
            logger.warning(f"⚠️ trafilatura 库不可用: {e}")
            self._trafilatura_available = False
        
        # 统计信息
        self.stats = {
            "successful_fetches": 0,
            "failed_fetches": 0,
            "timeout_fetches": 0,
            "total_fetches": 0
        }
    
    async def fetch(self, url: str, timeout: Optional[int] = None) -> Optional[str]:
        """
        获取单个URL的文章全文
        
        Args:
            url: 文章URL
            timeout: 超时时间（秒），如果为None则使用默认范围
            
        Returns:
            文章全文内容，如果获取失败则返回None
        """
        self.stats["total_fetches"] += 1
        
        if timeout is None:
            # 使用默认范围的中间值
            timeout = (self.timeout_range[0] + self.timeout_range[1]) // 2
        
        logger.debug(f"🌐 开始获取全文: {url} (超时: {timeout}秒)")
        
        try:
            # 使用 asyncio.wait_for 设置超时
            content = await asyncio.wait_for(
                self._fetch_inner(url),
                timeout=timeout
            )
            
            if content:
                self.stats["successful_fetches"] += 1
                logger.info(f"✅ 成功获取全文: {url} (长度: {len(content)} 字符)")
                return content
            else:
                self.stats["failed_fetches"] += 1
                logger.warning(f"⚠️ 获取全文返回空内容: {url}")
                return None
                
        except asyncio.TimeoutError:
            self.stats["timeout_fetches"] += 1
            logger.warning(f"⏰ 获取全文超时: {url} (超时: {timeout}秒)")
            return None
        except Exception as e:
            self.stats["failed_fetches"] += 1
            logger.error(f"❌ 获取全文失败 {url}: {e}")
            return None
    
    async def fetch_multiple(
        self, 
        urls: List[str], 
        max_concurrent: Optional[int] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Optional[str]]:
        """
        批量获取多个URL的文章全文
        
        Args:
            urls: URL列表
            max_concurrent: 最大并发数，如果为None则使用实例的max_concurrent
            timeout: 每个请求的超时时间（秒），如果为None则使用默认范围
            
        Returns:
            字典格式的结果 {url: content}，失败的URL对应的值为None
        """
        if not urls:
            logger.info("📋 批量获取：URL列表为空")
            return {}
        
        # 使用指定的并发数或实例的并发数
        concurrent = max_concurrent or self.max_concurrent
        semaphore = asyncio.Semaphore(concurrent)
        
        logger.info(f"📋 开始批量获取 {len(urls)} 篇文章全文 (并发: {concurrent})")
        
        async def fetch_with_semaphore(url: str) -> Tuple[str, Optional[str]]:
            """带信号量控制的单个获取"""
            async with semaphore:
                # 添加小延迟避免被封禁
                await asyncio.sleep(0.5)
                content = await self.fetch(url, timeout)
                return url, content
        
        # 并发获取所有URL
        tasks = [fetch_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)
        
        # 转换为字典
        result_dict = {url: content for url, content in results}
        
        # 统计结果
        success_count = sum(1 for content in result_dict.values() if content is not None)
        failure_count = len(urls) - success_count
        
        logger.info(
            f"📊 批量获取完成: 成功 {success_count}/{len(urls)} 篇, "
            f"失败 {failure_count}/{len(urls)} 篇"
        )
        
        return result_dict
    
    async def fetch_with_timeout(
        self, 
        url: str, 
        min_timeout: Optional[int] = None,
        max_timeout: Optional[int] = None
    ) -> Optional[str]:
        """
        使用自适应超时获取文章全文
        如果最小超时失败，会尝试使用最大超时重试
        
        Args:
            url: 文章URL
            min_timeout: 最小超时时间（秒），如果为None则使用实例的timeout_range[0]
            max_timeout: 最大超时时间（秒），如果为None则使用实例的timeout_range[1]
            
        Returns:
            文章全文内容，如果获取失败则返回None
        """
        if min_timeout is None:
            min_timeout = self.timeout_range[0]
        if max_timeout is None:
            max_timeout = self.timeout_range[1]
        
        # 先尝试最小超时
        logger.debug(f"⚡ 尝试快速获取 (超时: {min_timeout}秒): {url}")
        content = await self.fetch(url, min_timeout)
        
        if content:
            logger.debug(f"✅ 快速获取成功: {url}")
            return content
        
        # 如果快速获取失败，尝试使用最大超时
        logger.debug(f"🐌 快速获取失败，尝试延长超时 (超时: {max_timeout}秒): {url}")
        content = await self.fetch(url, max_timeout)
        
        if content:
            logger.info(f"✅ 延长超时后获取成功: {url}")
            return content
        
        logger.warning(f"⚠️ 所有超时设置均失败: {url}")
        return None
    
    async def _fetch_inner(self, url: str) -> Optional[str]:
        """
        内部获取逻辑，使用 trafilatura 库
        需要在异步环境中运行（使用 asyncio.to_thread）
        
        Args:
            url: 文章URL
            
        Returns:
            文章全文内容
        """
        if not self._trafilatura_available:
            logger.error(f"❌ trafilatura 库不可用，无法获取全文: {url}")
            return None
        
        try:
            # trafilatura 2.0.0: 使用 Extractor 配置对象
            from asyncio import to_thread

            # 创建 Extractor 配置对象（trafilatura 2.0.0 API）
            extractor = Extractor(
                comments=False,  # 对应原 include_comments=False
                tables=True      # 对应原 include_tables=True
            )

            # 使用新版 API：fetch_url(url, no_ssl, options)
            content = await to_thread(
                self._trafilatura.fetch_url,
                url,
                no_ssl=False,
                options=extractor
            )
            
            # 清理和验证内容
            if content and isinstance(content, str):
                content = content.strip()
                if len(content) < 50:  # 如果内容太短，可能没有获取到有效内容
                    logger.debug(f"⚠️ 获取的内容过短: {url} (长度: {len(content)} 字符)")
                    return None
                return content
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ trafilatura 获取失败 {url}: {e}")
            return None
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return {
            **self.stats,
            "success_rate": (
                self.stats["successful_fetches"] / self.stats["total_fetches"] 
                if self.stats["total_fetches"] > 0 else 0
            )
        }
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self.stats = {
            "successful_fetches": 0,
            "failed_fetches": 0,
            "timeout_fetches": 0,
            "total_fetches": 0
        }


# 便捷函数
async def fetch_content(url: str, timeout: int = None) -> Optional[str]:
    """
    便捷函数：获取单个URL的文章全文
    
    Args:
        url: 文章URL
        timeout: 超时时间（秒）
        
    Returns:
        文章全文内容
    """
    fetcher = ContentFetcher()
    return await fetcher.fetch(url, timeout)


async def fetch_contents(
    urls: List[str], 
    max_concurrent: int = DEFAULT_CONCURRENCY
) -> Dict[str, Optional[str]]:
    """
    便捷函数：批量获取多个URL的文章全文
    
    Args:
        urls: URL列表
        max_concurrent: 最大并发数
        
    Returns:
        字典格式的结果 {url: content}
    """
    fetcher = ContentFetcher(max_concurrent=max_concurrent)
    return await fetcher.fetch_multiple(urls)