"""
评分策略 - 策略模式实现

解决原 ai_scorer.py 中5处重复的评分计算逻辑（35行重复代码）
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class ScoringDimension:
    """
    评分维度
    
    用于定义评分策略中的各个维度
    """
    name: str           # 维度名称（用于显示）
    field: str          # 字段名（用于从数据中获取值）
    weight: float       # 权重（0-1）
    default: float = 5.0  # 默认值


class BaseScoringStrategy(ABC):
    """
    评分策略基类
    
    替代原代码中5处重复的评分计算：
    - 行号501-507 (财经)
    - 行号510-516 (科技)
    - 行号519-525 (社会政治)
    - 行号528-534 (通用)
    - 行号709-714 (_parse_response)
    
    使用策略模式，统一评分计算逻辑
    """
    
    # 子类需要覆盖
    DIMENSIONS: List[ScoringDimension] = []
    CATEGORY_NAME: str = ""
    
    def calculate_score(self, item_data: Dict) -> float:
        """
        计算评分
        
        Args:
            item_data: 包含各个维度分数的数据字典
            
        Returns:
            float: 计算后的总分（保留1位小数）
        """
        total = 0.0
        
        for dim in self.DIMENSIONS:
            value = item_data.get(dim.field, dim.default)
            total += value * dim.weight
        
        return round(total, 1)
    
    def calculate_score_with_override(
        self,
        item_data: Dict,
        override_score: Optional[float] = None
    ) -> float:
        """
        计算评分（支持覆盖总分）
        
        Args:
            item_data: 包含各个维度分数的数据字典
            override_score: 覆盖的总分（如果提供则直接使用）
            
        Returns:
            float: 计算后的总分
        """
        if override_score is not None:
            return round(override_score, 1)
        
        return self.calculate_score(item_data)
    
    def get_dimension_scores(self, item_data: Dict) -> Dict[str, float]:
        """
        获取各维度的分数
        
        Args:
            item_data: 包含各个维度分数的数据字典
            
        Returns:
            Dict[str, float]: 维度名称到分数的映射
        """
        return {
            dim.name: item_data.get(dim.field, dim.default)
            for dim in self.DIMENSIONS
        }
    
    def get_weights(self) -> Dict[str, float]:
        """
        获取权重映射
        
        Returns:
            Dict[str, float]: 维度名称到权重的映射
        """
        return {dim.name: dim.weight for dim in self.DIMENSIONS}
    
    def get_category_name(self) -> str:
        """获取分类名称"""
        return self.CATEGORY_NAME
    
    def validate_item_data(self, item_data: Dict) -> bool:
        """
        验证数据是否包含必要的维度
        
        Args:
            item_data: 待验证的数据字典
            
        Returns:
            bool: 数据是否有效
        """
        required_fields = {dim.field for dim in self.DIMENSIONS}
        return all(field in item_data for field in required_fields)
    
    def get_missing_fields(self, item_data: Dict) -> List[str]:
        """
        获取缺失的字段
        
        Args:
            item_data: 待检查的数据字典
            
        Returns:
            List[str]: 缺失的字段列表
        """
        return [
            dim.field 
            for dim in self.DIMENSIONS 
            if dim.field not in item_data
        ]


class FinanceScoringStrategy(BaseScoringStrategy):
    """
    财经新闻评分策略
    
    维度：
    - 市场影响 (40%): 对股市/债市/汇市的影响程度
    - 投资价值 (30%): 对投资决策的参考价值
    - 时效性 (20%): 新闻的及时性和新鲜度
    - 深度 (10%): 分析的深度和专业性
    - 受众广度 (0%): 财经新闻此项权重为0
    """
    
    DIMENSIONS = [
        ScoringDimension('市场影响', 'market_impact', 0.4),
        ScoringDimension('投资价值', 'investment_value', 0.3),
        ScoringDimension('时效性', 'timeliness', 0.2),
        ScoringDimension('深度', 'depth', 0.1),
        ScoringDimension('受众广度', 'audience_breadth', 0.0),
    ]
    
    CATEGORY_NAME = "财经"
    
    def __init__(self):
        # 财经新闻使用固定的权重
        pass


class TechnologyScoringStrategy(BaseScoringStrategy):
    """
    科技新闻评分策略
    
    维度：
    - 技术创新 (40%): 技术突破和创新程度
    - 实用性 (30%): 实际应用价值和可行性
    - 影响力 (20%): 对行业和社会的影响
    - 深度 (10%): 技术解读的专业深度
    - 受众广度 (0%): 科技新闻此项权重为0
    """
    
    DIMENSIONS = [
        ScoringDimension('技术创新', 'innovation', 0.4),
        ScoringDimension('实用性', 'practicality', 0.3),
        ScoringDimension('影响力', 'influence', 0.2),
        ScoringDimension('深度', 'depth', 0.1),
        ScoringDimension('受众广度', 'audience_breadth', 0.0),
    ]
    
    CATEGORY_NAME = "科技"


class PoliticsScoringStrategy(BaseScoringStrategy):
    """
    社会政治新闻评分策略
    
    维度：
    - 政策影响 (40%): 对政策制定和执行的影响
    - 公众关注度 (30%): 社会关注度和讨论热度
    - 时效性 (20%): 新闻的及时性和紧迫性
    - 深度 (10%): 背景分析的深入程度
    - 受众广度 (0%): 社会政治新闻此项权重为0
    """
    
    DIMENSIONS = [
        ScoringDimension('政策影响', 'policy_impact', 0.4),
        ScoringDimension('公众关注度', 'public_attention', 0.3),
        ScoringDimension('时效性', 'timeliness', 0.2),
        ScoringDimension('深度', 'depth', 0.1),
        ScoringDimension('受众广度', 'audience_breadth', 0.0),
    ]
    
    CATEGORY_NAME = "社会政治"


class GenericScoringStrategy(BaseScoringStrategy):
    """
    通用评分策略
    
    用于未分类的新闻或默认情况
    根据传入的criteria动态设置权重
    """
    
    def __init__(self, criteria: Dict[str, float]):
        """
        初始化通用策略
        
        Args:
            criteria: 评分权重配置
                - importance: 重要性权重 (默认0.3)
                - timeliness: 时效性权重 (默认0.2)
                - technical_depth: 技术深度权重 (默认0.2)
                - audience_breadth: 受众广度权重 (默认0.15)
                - practicality: 实用性权重 (默认0.15)
        """
        self.DIMENSIONS = [
            ScoringDimension(
                '重要性',
                'importance',
                criteria.get('importance', 0.3)
            ),
            ScoringDimension(
                '时效性',
                'timeliness',
                criteria.get('timeliness', 0.2)
            ),
            ScoringDimension(
                '技术深度',
                'technical_depth',
                criteria.get('technical_depth', 0.2)
            ),
            ScoringDimension(
                '受众广度',
                'audience_breadth',
                criteria.get('audience_breadth', 0.15)
            ),
            ScoringDimension(
                '实用性',
                'practicality',
                criteria.get('practicality', 0.15)
            ),
        ]
        
        self.CATEGORY_NAME = "通用"
        self.criteria = criteria
    
    def get_criteria(self) -> Dict[str, float]:
        """获取评分标准"""
        return self.criteria.copy()


class ScoringStrategyFactory:
    """
    评分策略工厂
    
    根据新闻分类返回对应的评分策略
    """
    
    # 策略映射
    _STRATEGIES = {
        '财经': FinanceScoringStrategy,
        '科技': TechnologyScoringStrategy,
        '社会政治': PoliticsScoringStrategy,
        '政治': PoliticsScoringStrategy,
    }
    
    # 分类关键词（用于模糊匹配）
    _CATEGORY_KEYWORDS = {
        '财经': ['股票', '股市', '投资', '金融', '经济', '银行', '财报'],
        '科技': ['ai', '人工智能', '技术', '软件', '硬件', '算法', '数据'],
        '社会政治': ['政策', '政府', '选举', '国际', '政治', '社会'],
    }
    
    @classmethod
    def get_strategy(
        cls, 
        category: str,
        criteria: Dict[str, float] = None
    ) -> BaseScoringStrategy:
        """
        获取评分策略
        
        Args:
            category: 新闻分类
            criteria: 通用策略的权重配置（可选）
            
        Returns:
            BaseScoringStrategy: 对应的评分策略
        """
        if not category:
            # 无分类，使用通用策略
            return GenericScoringStrategy(criteria or {})
        
        # 精确匹配
        category_lower = category.lower()
        for key, strategy_class in cls._STRATEGIES.items():
            if key.lower() in category_lower:
                return strategy_class()
        
        # 模糊匹配
        for key, keywords in cls._CATEGORY_KEYWORDS.items():
            if any(kw in category_lower for kw in keywords):
                return cls._STRATEGIES[key]()
        
        # 默认返回通用策略
        return GenericScoringStrategy(criteria or {})
    
    @classmethod
    def get_strategy_for_item(
        cls,
        item: NewsItem,
        criteria: Dict[str, float] = None
    ) -> BaseScoringStrategy:
        """
        根据新闻项获取评分策略
        
        优先使用AI分类结果，如果没有则使用预分类
        
        Args:
            item: 新闻项
            criteria: 通用策略的权重配置
            
        Returns:
            BaseScoringStrategy: 对应的评分策略
        """
        # 优先使用AI分类
        if hasattr(item, 'ai_category') and item.ai_category:
            return cls.get_strategy(item.ai_category, criteria)
        
        # 使用预分类
        if hasattr(item, 'pre_category') and item.pre_category:
            return cls.get_strategy(item.pre_category, criteria)
        
        # 默认通用策略
        return cls.get_strategy('', criteria)
    
    @classmethod
    def register_strategy(
        cls, 
        category: str, 
        strategy_class: type
    ):
        """
        注册新的评分策略
        
        Args:
            category: 分类名称
            strategy_class: 策略类（必须是BaseScoringStrategy的子类）
        """
        cls._STRATEGIES[category] = strategy_class
    
    @classmethod
    def get_available_categories(cls) -> List[str]:
        """
        获取可用的分类列表
        
        Returns:
            List[str]: 分类名称列表
        """
        return list(cls._STRATEGIES.keys()) + ['通用']
