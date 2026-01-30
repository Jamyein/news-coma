"""
配置管理模块
负责加载和验证配置文件
"""
import os
import yaml
from typing import List, Dict, Any
from pathlib import Path

from src.models import RSSSource, AIConfig, OutputConfig, FilterConfig, ProviderConfig, FallbackConfig


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
        
        # 读取当前提供商（简化版核心）
        current_provider = ai_data.get('ai_provider', 'openai')
        
        # 读取所有提供商配置
        providers_raw = ai_data.get('ai_providers', {})
        providers_config = {}
        
        for name, config in providers_raw.items():
            # 解析api_key环境变量
            api_key = config.get('api_key', '')
            if api_key.startswith('${') and api_key.endswith('}'):
                env_var = api_key[2:-1]
                api_key = os.getenv(env_var, '')
            
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
        
        # 读取回退配置
        fallback_data = ai_data.get('fallback', {})
        fallback = FallbackConfig(
            enabled=fallback_data.get('enabled', False),
            max_retries_per_provider=fallback_data.get('max_retries_per_provider', 2),
            fallback_chain=fallback_data.get('fallback_chain', [])
        )
        
        # 读取评分标准
        scoring_criteria = ai_data.get('scoring_criteria', {
            'importance': 0.30,
            'timeliness': 0.20,
            'technical_depth': 0.20,
            'audience_breadth': 0.15,
            'practicality': 0.15
        })
        
        return AIConfig(
            provider=current_provider,
            providers_config=providers_config,
            fallback=fallback,
            scoring_criteria=scoring_criteria,
            retry_attempts=ai_data.get('retry_attempts', 3)
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
            blocked_keywords=filter_data.get('blocked_keywords', [])
        )
