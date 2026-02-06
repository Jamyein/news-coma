"""
配置管理模块
负责加载和验证配置文件
"""
import os
import yaml
from typing import List, Dict, Any
from pathlib import Path

from src.models import RSSSource, AIConfig, OutputConfig, FilterConfig, ProviderConfig, FallbackConfig
from src.models import OnePassAIConfig, OnePassProviderConfig, OnePassScoringCriteria


class Config:
    """配置管理类"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """初始化配置"""
        self.config_path = Path(config_path)
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载YAML配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    @property
    def rss_sources(self) -> List[RSSSource]:
        """获取所有启用的RSS源配置"""
        sources = []
        for source_data in self._config.get('rss_sources', []):
            sources.append(RSSSource(
                name=source_data['name'],
                url=source_data['url'],
                weight=source_data.get('weight', 1.0),
                category=source_data.get('category', '未分类'),
                enabled=source_data.get('enabled', True)
            ))
        return [s for s in sources if s.enabled]
    
    @property
    def ai_config(self) -> AIConfig:
        """获取AI配置（支持多提供商）"""
        ai_data = self._config.get('ai', {})
        
        current_provider = ai_data.get('ai_provider', 'openai')
        providers_raw = ai_data.get('ai_providers', {})
        
        # 解析提供商配置
        providers_config = {}
        for name, config in providers_raw.items():
            api_key = self._resolve_api_key(config.get('api_key', ''))
            providers_config[name] = ProviderConfig(
                api_key=api_key,
                base_url=config.get('base_url', ''),
                model=config.get('model', 'gpt-4o-mini'),
                max_tokens=config.get('max_tokens', 2000),
                temperature=config.get('temperature', 0.3),
                rate_limit_rpm=config.get('rate_limit_rpm'),
                batch_size=config.get('batch_size', 5),
                max_concurrent=config.get('max_concurrent', 3)
            )
        
        # 验证当前提供商的API key
        current_config = providers_config.get(current_provider)
        if not current_config or not current_config.api_key:
            self._raise_api_key_error(current_provider, ai_data)
        
        return AIConfig(
            provider=current_provider,
            providers_config=providers_config,
            fallback=self._build_fallback_config(ai_data.get('fallback', {})),
            scoring_criteria=ai_data.get('scoring_criteria', {
                'importance': 0.30, 'timeliness': 0.20, 'technical_depth': 0.20,
                'audience_breadth': 0.15, 'practicality': 0.15
            }),
            retry_attempts=ai_data.get('retry_attempts', 3),
            cache_ttl_hours=ai_data.get('cache_ttl_hours', 24),
            use_true_batch=ai_data.get('use_true_batch', True),
            true_batch_size=ai_data.get('true_batch_size', 10),
            use_2pass=ai_data.get('use_2pass', True),
            pass1_threshold=ai_data.get('pass1_threshold', 7.0),
            pass1_max_items=ai_data.get('pass1_max_items', 40),
            pass1_threshold_finance=ai_data.get('pass1_threshold_finance', 5.5),
            pass1_threshold_tech=ai_data.get('pass1_threshold_tech', 6.0),
            pass1_threshold_politics=ai_data.get('pass1_threshold_politics', 5.5),
            pass1_use_category_specific=ai_data.get('pass1_use_category_specific', True),
            category_quota_finance=ai_data.get('category_quota_finance', 0.40),
            category_quota_tech=ai_data.get('category_quota_tech', 0.30),
            category_quota_politics=ai_data.get('category_quota_politics', 0.30),
            # 板块最低保障配置
            category_min_guarantee=ai_data.get('category_min_guarantee', {
                'finance': 3,
                'tech': 2,
                'politics': 2
            }),
            # 并行批处理配置（新增）
            use_parallel_batches=ai_data.get('use_parallel_batches', False),
            max_parallel_batches=ai_data.get('max_parallel_batches', 3),
            # 超时控制配置（新增）
            batch_timeout_seconds=ai_data.get('batch_timeout_seconds', 120),
            timeout_fallback_strategy=ai_data.get('timeout_fallback_strategy', 'single')
        )
    
    def _resolve_api_key(self, api_key_template: str) -> str:
        """解析API Key模板（支持环境变量）"""
        if api_key_template.startswith('${') and api_key_template.endswith('}'):
            env_var = api_key_template[2:-1]
            return os.getenv(env_var, '')
        return api_key_template
    
    def _raise_api_key_error(self, provider: str, ai_data: dict):
        """抛出API Key错误"""
        env_var = "OPENAI_API_KEY"  # default
        provider_config = ai_data.get('ai_providers', {}).get(provider, {})
        api_key_template = provider_config.get('api_key', '')
        if api_key_template.startswith('${') and api_key_template.endswith('}'):
            env_var = api_key_template[2:-1]
        
        raise ValueError(
            f"❌ 当前选择的AI提供商 '{provider}' 未配置API Key\n"
            f"请在环境变量中设置: {env_var}"
        )
    
    def _build_fallback_config(self, fallback_data: dict) -> FallbackConfig:
        """构建回退配置"""
        return FallbackConfig(
            enabled=fallback_data.get('enabled', False),
            max_retries_per_provider=fallback_data.get('max_retries_per_provider', 2),
            fallback_chain=fallback_data.get('fallback_chain', [])
        )

    @property
    def output_config(self) -> OutputConfig:
        """获取输出配置"""
        output_data = self._config.get('output', {})
        return OutputConfig(
            max_news_count=output_data.get('max_news_count', 10),
            max_feed_items=output_data.get('max_feed_items', 50),
            archive_days=output_data.get('archive_days', 30),
            time_window_days=output_data.get('time_window_days', 7)
        )
    
    @property
    def filter_config(self) -> FilterConfig:
        """获取过滤配置"""
        filter_data = self._config.get('filters', {})
        return FilterConfig(
            min_score_threshold=filter_data.get('min_score_threshold', 6.0),
            dedup_similarity=filter_data.get('dedup_similarity', 0.85),
            blocked_keywords=filter_data.get('blocked_keywords', []),
            # 语义去重默认关闭（避免误判"相似但较新"的内容）
            use_semantic_dedup=filter_data.get('use_semantic_dedup', False),
            # 语义相似度阈值提高到0.90（更严格，减少误判）
            semantic_similarity=filter_data.get('semantic_similarity', 0.90)
        )

    @property
    def use_smart_scorer(self) -> bool:
        """是否使用1-pass SmartScorer"""
        return self._config.get('use_smart_scorer', False)

    @property
    def one_pass_config(self) -> OnePassAIConfig:
        """获取1-pass AI配置（简化版）"""
        smart_ai_data = self._config.get('smart_ai', {})
        
        # 解析提供商配置
        providers_config = {}
        providers_raw = smart_ai_data.get('providers_config', {})
        
        for name, config in providers_raw.items():
            api_key = self._resolve_api_key(config.get('api_key', ''))
            providers_config[name] = OnePassProviderConfig(
                api_key=api_key,
                base_url=config.get('base_url', ''),
                model=config.get('model', 'glm-4-flash'),
                max_tokens=config.get('max_tokens', 4000),
                temperature=config.get('temperature', 0.3),
                batch_size=config.get('batch_size', 10),
                max_concurrent=config.get('max_concurrent', 3)
            )
        
        # 评分标准
        criteria_data = smart_ai_data.get('scoring_criteria', {})
        scoring_criteria = OnePassScoringCriteria(
            importance=criteria_data.get('importance', 0.30),
            timeliness=criteria_data.get('timeliness', 0.20),
            technical_depth=criteria_data.get('technical_depth', 0.20),
            audience_breadth=criteria_data.get('audience_breadth', 0.15),
            practicality=criteria_data.get('practicality', 0.15)
        )
        
        return OnePassAIConfig(
            provider=smart_ai_data.get('provider', 'zhipu'),
            providers_config=providers_config,
            batch_size=smart_ai_data.get('batch_size', 10),
            max_concurrent=smart_ai_data.get('max_concurrent', 3),
            timeout_seconds=smart_ai_data.get('timeout_seconds', 90),
            max_output_items=smart_ai_data.get('max_output_items', 30),
            diversity_weight=smart_ai_data.get('diversity_weight', 0.3),
            scoring_criteria=scoring_criteria,
            fallback_enabled=smart_ai_data.get('fallback_enabled', True),
            fallback_chain=smart_ai_data.get('fallback_chain', ['deepseek', 'gemini'])
        )
