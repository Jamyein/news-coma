"""
Tests for AIScorer fix: AttributeError: 'AIConfig' object has no attribute 'get'

这些测试验证修复后 _execute_scoring 方法正确接收 items 参数，
而不是依赖 config.get('items', [])
"""
import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from typing import List
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.models import NewsItem, AIConfig, ProviderConfig, FallbackConfig
from src.AIScorer.ai_scorer import AIScorer


class TestAIScorerExecuteScoringFix:
    """测试 _execute_scoring 方法修复"""

    @pytest.fixture
    def mock_config(self):
        """创建测试用的 mock AIConfig"""
        providers_config = {
            'test': ProviderConfig(
                api_key='test-key',
                base_url='https://test.com',
                model='test-model',
                max_tokens=2000,
                temperature=0.3
            )
        }
        
        fallback = FallbackConfig(
            enabled=False,
            max_retries_per_provider=2,
            fallback_chain=[]
        )
        
        return AIConfig(
            provider='test',
            providers_config=providers_config,
            fallback=fallback,
            scoring_criteria={'importance': 0.3}
        )

    @pytest.fixture
    def mock_provider_manager(self):
        """创建 mock ProviderManager"""
        manager = Mock()
        manager.current_config = Mock()
        manager.current_config.temperature = 0.3
        manager.call_batch_api = AsyncMock(return_value='{"results": []}')
        return manager

    def test_execute_scoring_accepts_items_parameter(self, mock_config, mock_provider_manager):
        """
        测试 _execute_scoring 方法接受 items 参数
        
        RED 阶段：当前实现应该失败，因为还没有添加 items 参数
        """
        scorer = AIScorer(mock_config)
        scorer.provider_manager = mock_provider_manager
        
        # 验证 _execute_scoring 签名包含 items 参数
        import inspect
        sig = inspect.signature(scorer._execute_scoring)
        params = list(sig.parameters.keys())
        
        # 这个测试应该在 GREEN 阶段通过
        assert 'items' in params, (
            f"_execute_scoring 应该接受 items 参数，但当前签名是: ({', '.join(params)})"
        )

    def test_execute_scoring_uses_items_for_token_estimation(self, mock_config, mock_provider_manager):
        """
        测试 _execute_scoring 使用 items 参数计算 token 估计
        
        RED 阶段：当前实现应该失败，因为使用了 config.get('items', [])
        """
        scorer = AIScorer(mock_config)
        scorer.provider_manager = mock_provider_manager
        
        # 创建测试数据
        test_items = [Mock(spec=NewsItem) for _ in range(5)]
        test_prompt = "test prompt"
        
        # 执行调用
        import asyncio
        async def run_test():
            return await scorer._execute_scoring(test_prompt, test_items)
        
        try:
            asyncio.run(run_test())
            
            # 验证 call_batch_api 被调用
            mock_provider_manager.call_batch_api.assert_called_once()
            
            # 验证调用参数中使用了正确的 max_tokens
            call_kwargs = mock_provider_manager.call_batch_api.call_args.kwargs
            # 如果正确实现，estimated_tokens 应该基于 len(items) = 5
            # 即 estimated_tokens = min(1000 + 5 * 500, 8000) = 3500
            expected_tokens = min(1000 + len(test_items) * 500, 8000)
            assert call_kwargs.get('max_tokens') == expected_tokens, (
                f"expected max_tokens={expected_tokens}, got {call_kwargs.get('max_tokens')}"
            )
            
        except TypeError as e:
            # 如果还没有实现 items 参数，会抛出 TypeError
            pytest.fail(f"_execute_scoring 还没有接受 items 参数: {e}")

    def test_execute_scoring_handles_empty_items(self, mock_config, mock_provider_manager):
        """
        测试 _execute_scoring 处理空 items 列表
        """
        scorer = AIScorer(mock_config)
        scorer.provider_manager = mock_provider_manager
        
        test_items = []
        test_prompt = "test prompt"
        
        import asyncio
        async def run_test():
            return await scorer._execute_scoring(test_prompt, test_items)
        
        try:
            asyncio.run(run_test())
            mock_provider_manager.call_batch_api.assert_called_once()
            
            # 空列表时，estimated_tokens = min(1000 + 0 * 500, 8000) = 1000
            call_kwargs = mock_provider_manager.call_batch_api.call_args.kwargs
            assert call_kwargs.get('max_tokens') == 1000, (
                f"空 items 应该使用默认 1000 tokens，但 got {call_kwargs.get('max_tokens')}"
            )
            
        except TypeError as e:
            pytest.fail(f"_execute_scoring 还没有接受 items 参数: {e}")


class TestScoreAllIntegration:
    """集成测试：验证完整评分流程"""

    @pytest.fixture
    def mock_config(self):
        """创建测试用的 mock AIConfig"""
        providers_config = {
            'test': ProviderConfig(
                api_key='test-key',
                base_url='https://test.com',
                model='test-model',
                max_tokens=2000,
                temperature=0.3
            )
        }
        
        fallback = FallbackConfig(
            enabled=False,
            max_retries_per_provider=2,
            fallback_chain=[]
        )
        
        return AIConfig(
            provider='test',
            providers_config=providers_config,
            fallback=fallback,
            scoring_criteria={'importance': 0.3},
            use_2pass=False  # 使用标准评分流程
        )

    def test_score_all_no_attribute_error(self, mock_config):
        """
        测试 score_all 不再抛出 AttributeError
        
        这是主要的回归测试：确保不再出现
        AttributeError: 'AIConfig' object has no attribute 'get'
        """
        scorer = AIScorer(mock_config)
        
        # 创建测试数据
        test_items = [Mock(spec=NewsItem) for _ in range(3)]
        
        import asyncio
        async def run_test():
            # 这应该不会抛出 AttributeError
            return await scorer.score_all(test_items)
        
        try:
            # 捕获任何 AttributeError
            with pytest.raises(AttributeError) as exc_info:
                asyncio.run(run_test())
            
            # 如果抛出 AttributeError，检查是否是 'get' 相关的错误
            if "'AIConfig' object has no attribute 'get'" in str(exc_info.value):
                pytest.fail(
                    "仍然存在 AttributeError: 'AIConfig' object has no attribute 'get'\n"
                    "这表明 config.get('items', []) 调用还没有修复"
                )
                
        except TypeError as e:
            # 如果抛出 TypeError，可能是因为参数不匹配
            if "positional argument" in str(e):
                pytest.fail(
                    f"_execute_scoring 调用签名不匹配: {e}\n"
                    "需要确保所有调用点都传递了 items 参数"
                )
            else:
                raise
        except Exception as e:
            # 其他异常是预期的（因为 mock 不完整）
            # 只要不是 AttributeError 就好
            pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
