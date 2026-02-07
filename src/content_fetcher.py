"""
内容获取模块
使用 trafilatura 库从URL获取文章全文
支持并发控制和超时设置，无需缓存（RSS增量获取确保不重复）
"""
import asyncio
import logging
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)


class ContentFetcher:
    """内容获取器 - 使用 trafilatura 获取文章全文"""
    
    def __init__(
        self, 
        max_concurrent: int = 5,
        timeout_range: Tuple[int, int] = (10, 30)
    ):
        """初始化内容获取器"""
        self.max_concurrent = max_concurrent
        self.timeout_range = timeout_range
        
        # 尝试导入 trafilatura
        try:
            import trafilatura
            self._trafilatura = trafilatura
            logger.info("✅ trafilatura 库加载成功")
        except ImportError:
            self._trafilatura = None
            logger.warning("⚠️ trafilatura 库不可用")
        
        # 统计信息
        self.stats = {
            "successful_fetches": 0,
            "failed_fetches": 0,
            "timeout_fetches": 0,
            "total_fetches": 0
        }
    
    def _handle_fetch_error(self, error: Exception, url: str, context: str = "") -> None:
        """统一处理获取错误并更新统计"""
        error_type = type(error).__name__

        if isinstance(error, asyncio.TimeoutError):
            self.stats["timeout_fetches"] += 1
            logger.warning(f"⏰ 获取超时 [{context}]: {url}")
        else:
            self.stats["failed_fetches"] += 1
            logger.error(f"❌ 获取失败 [{context}] {url}: {error}")

    async def fetch(self, url: str, timeout: Optional[int] = None) -> Optional[str]:
        """获取单个URL的文章全文"""
        self.stats["total_fetches"] += 1
        timeout = timeout or (self.timeout_range[0] + self.timeout_range[1]) // 2

        try:
            content = await asyncio.wait_for(self._fetch_inner(url), timeout=timeout)
            if content:
                self.stats["successful_fetches"] += 1
                logger.debug(f"✅ 获取全文成功: {url} ({len(content)} 字符)")
                return content
            else:
                self.stats["failed_fetches"] += 1
                return None
        except Exception as e:
            self._handle_fetch_error(e, url)
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
        """使用自适应超时获取文章全文（先尝试快超时，失败则用慢超时）"""
        min_timeout = min_timeout or self.timeout_range[0]
        max_timeout = max_timeout or self.timeout_range[1]
        
        # 先尝试最小超时
        content = await self.fetch(url, min_timeout)
        if content:
            return content
        
        # 失败则用最大超时重试
        return await self.fetch(url, max_timeout)
    
    async def _fetch_inner(self, url: str) -> Optional[str]:
        """使用 trafilatura 获取文章全文"""
        if not self._trafilatura:
            return None
        
        try:
            from asyncio import to_thread
            from trafilatura.settings import Extractor

            extractor = Extractor(comments=False, tables=True)
            content = await to_thread(
                self._trafilatura.fetch_url, url, no_ssl=False, options=extractor
            )
            
            if content and len(content.strip()) >= 50:
                return content.strip()
            return None
                
        except Exception as e:
            logger.debug(f"trafilatura 获取失败 {url}: {e}")
            return None
    
    def get_stats(self) -> Dict[str, float]:
        """获取统计信息"""
        total = self.stats["total_fetches"]
        return {
            **self.stats,
            "success_rate": self.stats["successful_fetches"] / total if total > 0 else 0
        }
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        for key in self.stats:
            self.stats[key] = 0


# 便捷函数
# 便捷函数
async def fetch_content(url: str, timeout: int = None) -> Optional[str]:
    """便捷函数：获取单个URL的文章全文"""
    return await ContentFetcher().fetch(url, timeout)


async def fetch_contents(urls: List[str], max_concurrent: int = 5) -> Dict[str, Optional[str]]:
    """便捷函数：批量获取多个URL的文章全文"""
    return await ContentFetcher(max_concurrent=max_concurrent).fetch_multiple(urls)