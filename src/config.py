"""
配置管理模块
负责加载和验证配置文件
"""
import os
import yaml
from pathlib import Path

from typing import Any

from src.models import RSSSource, AIConfig, OutputConfig, FilterConfig, ProviderConfig, ScoringCriteria


class Config:
    """配置管理类"""

    def __init__(self, config_path: str = "config.yaml"):
        """初始化配置"""
        self.config_path = Path(config_path)
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """加载YAML配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    @property
    def rss_sources(self) -> list[RSSSource]:
        """获取所有启用的RSS源配置"""
        sources = []
        for source_data in self._config.get('rss_sources', []):
            sources.append(RSSSource(
                name=source_data['name'],
                url=source_data['url'],
                enabled=source_data.get('enabled', True)
            ))
        return [s for s in sources if s.enabled]
    
    @property
    def ai_config(self) -> AIConfig:
        """获取AI配置（1-Pass简化版）"""
        smart_ai_data = self._config.get('smart_ai', {})
        
        # 解析提供商配置
        providers_config = {}
        providers_raw = smart_ai_data.get('providers_config', {})
        
        for name, config in providers_raw.items():
            api_key = self._resolve_api_key(config.get('api_key', ''))
            providers_config[name] = ProviderConfig(
                api_key=api_key,
                base_url=config.get('base_url', ''),
                model=config.get('model', 'glm-4-flash'),
                max_tokens=config.get('max_tokens', 4000),
                temperature=config.get('temperature', 0.3),
                batch_size=config.get('batch_size', 10),
                max_concurrent=config.get('max_concurrent', 3),
                rate_limit_rpm=config.get('rate_limit_rpm', 60)
            )
        
        # 验证当前提供商的API key
        current_provider = smart_ai_data.get('provider', 'zhipu')
        current_config = providers_config.get(current_provider)
        if not current_config or not current_config.api_key:
            self._raise_api_key_error(current_provider, smart_ai_data)
        
        # 评分标准
        scoring_criteria = ScoringCriteria.from_dict(smart_ai_data.get('scoring_criteria', {}))
        
        # 提取常用配置项
        common_config = self._get_common_config(smart_ai_data)
        
        return AIConfig(
            provider=current_provider,
            providers_config=providers_config,
            scoring_criteria=scoring_criteria,
            **common_config
        )
    
    def _resolve_api_key(self, api_key_template: str) -> str:
        """解析API Key模板（支持环境变量）"""
        if api_key_template.startswith('${') and api_key_template.endswith('}'):
            env_var = api_key_template[2:-1]
            return os.getenv(env_var, '')
        return api_key_template
    
    def _raise_api_key_error(self, provider: str, ai_data: dict):
        """抛出API Key错误"""
        env_var = "ZHIPU_API_KEY"  # default
        provider_config = ai_data.get('providers_config', {}).get(provider, {})
        api_key_template = provider_config.get('api_key', '')
        if api_key_template.startswith('${') and api_key_template.endswith('}'):
            env_var = api_key_template[2:-1]
        
        raise ValueError(
            f"❌ 当前选择的AI提供商 '{provider}' 未配置API Key\n"
            f"请在环境变量中设置: {env_var}"
        )
    
    def _get_common_config(self, smart_ai_data: dict) -> dict:
        """提取常用AI配置项"""
        return {
            'batch_size': smart_ai_data.get('batch_size', 10),
            'max_concurrent': smart_ai_data.get('max_concurrent', 3),
            'timeout_seconds': smart_ai_data.get('timeout_seconds', 90),
            'max_output_items': smart_ai_data.get('max_output_items', 30),
            'diversity_weight': smart_ai_data.get('diversity_weight', 0.3),
            'fallback_enabled': smart_ai_data.get('fallback_enabled', True),
            'fallback_chain': smart_ai_data.get('fallback_chain', ['deepseek', 'gemini']),
            'category_min_guarantee': smart_ai_data.get('category_min_guarantee', {}),
            'category_fixed_targets': smart_ai_data.get('category_fixed_targets', {}),
            'use_fixed_proportion': smart_ai_data.get('use_fixed_proportion', False)
        }

    @property
    def output_config(self) -> OutputConfig:
        """获取输出配置"""
        output_data = self._config.get('output', {})
        return OutputConfig(
            max_news_count=output_data.get('max_news_count', 30),
            max_feed_items=output_data.get('max_feed_items', 50),
            archive_days=output_data.get('archive_days', 30),
            time_window_days=output_data.get('time_window_days', 1),
            use_smart_switch=output_data.get('use_smart_switch', True)
        )
    
    @property
    def filter_config(self) -> FilterConfig:
        """获取过滤配置"""
        filter_data = self._config.get('filters', {})
        return FilterConfig(
            min_score_threshold=filter_data.get('min_score_threshold', 6.0),
            dedup_similarity=filter_data.get('dedup_similarity', 0.85),
            blocked_keywords=filter_data.get('blocked_keywords', []),
            use_semantic_dedup=filter_data.get('use_semantic_dedup', True),
            semantic_similarity=filter_data.get('semantic_similarity', 0.85),
            use_full_content=filter_data.get('use_full_content', True),
            max_content_length=filter_data.get('max_content_length', 5000)
        )
