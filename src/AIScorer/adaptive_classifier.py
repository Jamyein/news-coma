"""
自适应新闻分类器 - 带语义分析和置信度评分的增强分类器

用于 Pass 1 优化，提供更智能的分类和置信度评分
"""
import re
import logging
from typing import List, Dict, Tuple, Optional, Set
from collections import Counter
from dataclasses import dataclass, field

from src.models import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class ClassifiedItem:
    """分类结果"""
    item: NewsItem
    category: str
    confidence: float  # 0-1
    feature_vector: Dict[str, float] = field(default_factory=dict)
    method: str = "keyword"  # keyword, source, semantic, fallback


class AdaptiveNewsClassifier:
    """
    自适应新闻分类器
    
    特点：
    - 多维度特征提取（来源、关键词、语义）
    - 置信度评分（0-1）
    - 语义分析（标题和摘要文本分析）
    - 动态权重调整
    - 支持四大分类：财经、科技、社会政治、未分类
    """
    
    # ===== 分类定义 =====
    CATEGORIES = {
        "财经": {
            "color": "#E74C3C",
            "priority": 1,
            "keywords": [
                # 中文关键词
                "股票", "股市", "投资", "银行", "利率", "通胀", "财报",
                "央行", "美联储", "利率决议", "货币政策", "财政政策",
                "经济数据", "GDP", "CPI", "PPI", "汇率", "人民币",
                "美股", "港股", "A股", "基金", "债券", "期货",
                "大宗商品", "黄金", "石油", "天然气", "铜", "铝",
                "房地产", "房价", "房贷", "限购", "限贷",
                "数字货币", "比特币", "以太坊", "crypto",
                # 英文关键词
                "stock", "stocks", "investment", "investing", "investor",
                "market", "markets", "economy", "economic", "finance",
                "financial", "earnings", "revenue", "profit", "loss",
                "fed", "federal reserve", "interest rate", "inflation",
                "gdp", "gdp growth", "consumer price", "cpi",
                "dollar", "yuan", "currency", "forex", "exchange rate",
                "bond", "bond yield", "treasury", "municipal bond",
                "commodity", "gold", "oil", "natural gas", "crude",
                "real estate", "housing", "mortgage", "home price",
                "crypto", "cryptocurrency", "bitcoin", "ethereum",
                "blockchain", "token", "defi", "nft"
            ],
            "sources": [
                "wsj 经济", "wsj 市场", "financial times", "bloomberg",
                "cnbc", "marketwatch", "ft.com", "华尔街见闻",
                "东方财富", "财新", "经济观察", "36氪", "香港經濟日報",
                "the economist", "bbc business", "wsj 全球经济",
                "reuters business", "financial post", "barron's",
                "investing.com", "yahoo finance", "market watch"
            ],
            "high_value": ["fed", "央行", "美联储", "财报", "earnings", "stock", "market"]
        },
        "科技": {
            "color": "#3498DB",
            "priority": 2,
            "keywords": [
                # 中文关键词
                "ai", "人工智能", "机器学习", "深度学习", "神经网络",
                "芯片", "半导体", "处理器", "GPU", "CPU", "AI芯片",
                "软件", "app", "应用程序", "移动应用",
                "互联网", "互联网公司", "科技公司", "IT",
                "算法", "大数据", "云计算", "区块链", "物联网",
                "5G", "6G", "网络", "网络安全", "黑客",
                "创业", "初创公司", " startup", "创新", "研发",
                "智能", "智能机", "智能手机", "智能汽车", "自动驾驶",
                "元宇宙", "VR", "AR", "虚拟现实", "增强现实",
                # 英文关键词
                "ai", "artificial intelligence", "machine learning",
                "deep learning", "neural network", "llm", "gpt",
                "chip", "semiconductor", "processor", "gpu", "cpu",
                "software", "app", "application", "mobile app",
                "internet", "web", "tech company", "technology",
                "algorithm", "big data", "cloud computing",
                "blockchain", "iot", "internet of things",
                "5g", "6g", "network", "cybersecurity", "hack",
                "security", "vulnerability", "breach",
                "startup", "startup", "innovation", "innovative",
                "smartphone", "smart phone", "electric vehicle", "ev",
                "autonomous", "self-driving", "tesla",
                "metaverse", "vr", "ar", "virtual reality",
                "augmented reality"
            ],
            "sources": [
                "the verge", "techcrunch", "hacker news", "github blog",
                "arstechnica", "wired", "engadget", "36氪", "华尔街见闻",
                "techmeme", "verge", "the next web", "product hunt",
                "github trending", "hacker noon", "dev.to"
            ],
            "high_value": ["ai", "gpt", "llm", "chip", "semiconductor", "人工智能", "芯片"]
        },
        "社会政治": {
            "color": "#2ECC71",
            "priority": 3,
            "keywords": [
                # 中文关键词
                "政策", "选举", "政府", "国会", "议会", "法案",
                "特朗普", "拜登", "习近平", "普京", "各国领导人",
                "外交", "国际", "国际关系", "外交关系",
                "战争", "和平", "冲突", "军事", "国防", "安全",
                "环境", "气候", "能源", "碳中和", "碳排放",
                "健康", "疫情", "公共卫生", "医疗", "疫苗",
                "教育", "社会福利", "移民", "难民",
                "法律", "法规", "监管", "诉讼", "判决",
                # 英文关键词
                "policy", "policies", "election", "elections", "vote",
                "government", "governments", "congress", "senate",
                "house of representatives", "parliament", "bill",
                "law", "laws", "regulation", "regulations",
                "trump", "biden", "putin", "xi jinping", "leader",
                "diplomacy", "diplomatic", "international", "global",
                "foreign", "foreign policy", "foreign affairs",
                "war", "peace", "conflict", "military", "defense",
                "security", "national security", "intelligence",
                "environment", "climate", "climate change", "energy",
                "carbon", "carbon neutral", "carbon emission",
                "health", "pandemic", "public health", "healthcare",
                "vaccine", "vaccination", "covid", "coronavirus",
                "education", "welfare", "immigration", "immigrant",
                "refugee", "asylum", "legal", "lawsuit", "court",
                "verdict", "ruling", "judge", "justice", "supreme court"
            ],
            "sources": [
                "bbc", "the guardian", "politico", "wsj 时政",
                "reuters", "associated press", "ap news", "36氪", 
                "华尔街见闻", "nytimes", "washington post",
                "cnn politics", "fox news", "MSNBC"
            ],
            "high_value": ["election", "government", "policy", "trump", "biden", "政府", "选举"]
        }
    }
    
    # 同义词映射（扩展语义理解）
    SYNONYM_MAP = {
        "财经": {
            "股票": ["股价", "股指", "个股", "证券", "股本"],
            "投资": ["理财", "资产配置", "持仓", "建仓"],
            "银行": ["银行业", "商业银行", "央行", "美联储"],
            "通胀": ["通货膨胀", "物价上涨", "cpi"],
            "财报": ["业绩", "盈利", "利润", "营收"],
        },
        "科技": {
            "ai": ["AI", "人工智能", "大模型", "LLM"],
            "芯片": ["处理器", "半导体", "晶圆", "集成电路"],
            "软件": ["应用程序", "App", "程序", "系统"],
            "互联网": ["网络", "在线", "数字化"],
            "算法": ["模型", "计算", "数据处理"],
        },
        "社会政治": {
            "政策": ["法规", "条例", "规定", "措施"],
            "选举": ["投票", "竞选", "公投"],
            "政府": ["官方", "当局", "部门"],
            "外交": ["国际关系", "外事", "邦交"],
            "军事": ["国防", "武装", "军队"],
        }
    }
    
    # 置信度阈值
    CONFIDENCE_THRESHOLD_HIGH = 0.8
    CONFIDENCE_THRESHOLD_MEDIUM = 0.6
    
    def __init__(self):
        """初始化分类器"""
        self._compile_patterns()
        self._initialize_weights()
        
        # 统计信息
        self._stats = {
            'total': 0,
            'by_category': Counter(),
            'by_method': Counter(),
            'confidence_distribution': Counter({'high': 0, 'medium': 0, 'low': 0}),
        }
    
    def _compile_patterns(self):
        """编译所有正则表达式模式"""
        self._category_patterns = {}
        self._source_patterns = {}
        
        for category, config in self.CATEGORIES.items():
            # 编译关键词模式
            keywords = config['keywords']
            escaped = [re.escape(kw) for kw in keywords]
            pattern = '|'.join(escaped)
            self._category_patterns[category] = re.compile(pattern, re.IGNORECASE)
            
            # 编译来源模式
            sources = config['sources']
            escaped = [re.escape(src) for src in sources]
            pattern = '|'.join(escaped)
            self._source_patterns[category] = re.compile(pattern, re.IGNORECASE)
    
    def _initialize_weights(self):
        """初始化特征权重"""
        self._weights = {
            'source_match': 0.40,      # 来源匹配权重
            'keyword_match': 0.35,     # 关键词匹配权重
            'high_value_bonus': 0.15,  # 高价值关键词奖励
            'semantic_score': 0.10,    # 语义分析权重
        }
    
    def classify_with_confidence(self, items: List[NewsItem]) -> List[ClassifiedItem]:
        """
        批量分类新闻条目
        
        Args:
            items: 新闻条目列表
            
        Returns:
            List[ClassifiedItem]: 分类结果列表
        """
        results = []
        
        for item in items:
            classified = self._classify_single(item)
            results.append(classified)
            
            # 更新统计
            self._update_stats(classified)
        
        return results
    
    def _classify_single(self, item: NewsItem) -> ClassifiedItem:
        """
        分类单个新闻条目
        
        Args:
            item: 新闻条目
            
        Returns:
            ClassifiedItem: 分类结果
        """
        # 提取特征向量
        features = self._extract_features(item)
        
        # 1. 尝试来源匹配（最高优先级）
        source_category = self._check_source_match(item.source)
        if source_category:
            confidence = self._calculate_confidence_score(item, source_category, features, method='source')
            return ClassifiedItem(
                item=item,
                category=source_category,
                confidence=confidence,
                feature_vector=features,
                method='source'
            )
        
        # 2. 尝试关键词匹配
        keyword_category = self._check_keyword_match(item)
        features['keyword_scores'] = self._get_keyword_scores(item)
        
        if keyword_category:
            confidence = self._calculate_confidence_score(item, keyword_category, features, method='keyword')
            return ClassifiedItem(
                item=item,
                category=keyword_category,
                confidence=confidence,
                feature_vector=features,
                method='keyword'
            )
        
        # 3. 尝试语义分析
        semantic_category = self._semantic_classification(item)
        if semantic_category:
            confidence = self._calculate_confidence_score(item, semantic_category, features, method='semantic')
            return ClassifiedItem(
                item=item,
                category=semantic_category,
                confidence=confidence,
                feature_vector=features,
                method='semantic'
            )
        
        # 4. Fallback 到未分类
        return ClassifiedItem(
            item=item,
            category='未分类',
            confidence=0.0,
            feature_vector=features,
            method='fallback'
        )
    
    def _extract_features(self, item: NewsItem) -> Dict[str, float]:
        """
        提取文本特征
        
        Args:
            item: 新闻条目
            
        Returns:
            Dict[str, float]: 特征向量
        """
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        text_lower = title_lower + " " + summary_lower
        
        features = {
            'title_length': len(item.title),
            'title_word_count': len(title_lower.split()),
            'has_summary': 1.0 if item.summary else 0.0,
            'summary_length': len(item.summary or ""),
            'total_length': len(item.title) + len(item.summary or ""),
            'punctuation_ratio': self._calculate_punctuation_ratio(text_lower),
            'number_ratio': self._calculate_number_ratio(text_lower),
            'uppercase_ratio': self._calculate_uppercase_ratio(item.title),
        }
        
        return features
    
    def _calculate_punctuation_ratio(self, text: str) -> float:
        """计算标点符号比例"""
        if not text:
            return 0.0
        punct_count = sum(1 for c in text if c in '.,!?;:()[]{}"\'')
        return punct_count / len(text)
    
    def _calculate_number_ratio(self, text: str) -> float:
        """计算数字比例"""
        if not text:
            return 0.0
        num_count = sum(1 for c in text if c.isdigit())
        return num_count / len(text)
    
    def _calculate_uppercase_ratio(self, text: str) -> float:
        """计算大写字母比例"""
        if not text:
            return 0.0
        upper_count = sum(1 for c in text if c.isupper())
        return upper_count / len(text)
    
    def _check_source_match(self, source: str) -> Optional[str]:
        """
        检查来源匹配
        
        Args:
            source: 新闻来源
            
        Returns:
            Optional[str]: 匹配的分类名称
        """
        source_lower = source.lower()
        
        for category, pattern in self._source_patterns.items():
            if pattern.search(source_lower):
                return category
        
        return None
    
    def _check_keyword_match(self, item: NewsItem) -> Optional[str]:
        """
        检查关键词匹配
        
        Args:
            item: 新闻条目
            
        Returns:
            Optional[str]: 匹配的分类名称
        """
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        
        # 优先检查标题
        scores = {}
        for category, pattern in self._category_patterns.items():
            title_matches = len(pattern.findall(title_lower))
            summary_matches = len(pattern.findall(summary_lower))
            
            # 标题权重更高
            scores[category] = title_matches * 1.0 + summary_matches * 0.5
        
        max_score = max(scores.values())
        
        if max_score == 0:
            return None
        
        # 返回得分最高的分类
        return max(scores, key=scores.get)
    
    def _get_keyword_scores(self, item: NewsItem) -> Dict[str, float]:
        """
        获取各分类的关键词得分
        
        Args:
            item: 新闻条目
            
        Returns:
            Dict[str, float]: 各分类得分
        """
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        
        scores = {}
        for category, pattern in self._category_patterns.items():
            title_matches = len(pattern.findall(title_lower))
            summary_matches = len(pattern.findall(summary_lower))
            scores[category] = title_matches * 1.0 + summary_matches * 0.5
        
        return scores
    
    def _semantic_classification(self, item: NewsItem) -> Optional[str]:
        """
        语义分类（基于标题和摘要分析）
        
        Args:
            item: 新闻条目
            
        Returns:
            Optional[str]: 分类名称
        """
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        text_lower = title_lower + " " + summary_lower
        
        # 1. 检查同义词匹配
        for category, synonyms in self.SYNONYM_MAP.items():
            for main_word, synonym_list in synonyms.items():
                all_terms = [main_word] + synonym_list
                for term in all_terms:
                    if term.lower() in text_lower:
                        return category
        
        # 2. 检查高价值关键词
        for category, config in self.CATEGORIES.items():
            high_value = config['high_value']
            for hv in high_value:
                if hv.lower() in text_lower:
                    return category
        
        # 3. 检查文本模式
        if self._is_finance_pattern(text_lower):
            return "财经"
        elif self._is_tech_pattern(text_lower):
            return "科技"
        elif self._is_politics_pattern(text_lower):
            return "社会政治"
        
        return None
    
    def _is_finance_pattern(self, text: str) -> bool:
        """判断是否为财经模式"""
        finance_indicators = [
            "上涨", "下跌", "涨", "跌", "跌幅", "涨幅",
            "上涨", "下挫", "上涨", "回落", "涨至",
            "up", "down", "rise", "fall", "drop", "gain", "loss"
        ]
        text_lower = text.lower()
        matches = sum(1 for ind in finance_indicators if ind in text_lower)
        return matches >= 2
    
    def _is_tech_pattern(self, text: str) -> bool:
        """判断是否为科技模式"""
        tech_indicators = [
            "发布", "推出", "更新", "升级", "发布",
            "研发", "开发", "技术", "创新", "突破",
            "release", "launch", "update", "upgrade", "develop",
            "innovate", "innovation", "breakthrough", "technology"
        ]
        text_lower = text.lower()
        matches = sum(1 for ind in tech_indicators if ind in text_lower)
        return matches >= 2
    
    def _is_politics_pattern(self, text: str) -> bool:
        """判断是否为社会政治模式"""
        politics_indicators = [
            "宣布", "声明", "表示", "指出", "强调",
            "通过", "批准", "签署", "否决", "推迟",
            "announce", "declare", "state", "approve", "sign",
            "reject", "postpone", "pass", "enact"
        ]
        text_lower = text.lower()
        matches = sum(1 for ind in politics_indicators if ind in text_lower)
        return matches >= 2
    
    def _calculate_confidence_score(
        self,
        item: NewsItem,
        category: str,
        features: Dict[str, float],
        method: str
    ) -> float:
        """
        计算置信度分数 (0-1)
        
        Args:
            item: 新闻条目
            category: 分类名称
            features: 特征向量
            method: 分类方法
            
        Returns:
            float: 置信度分数 (0-1)
        """
        base_score = 0.0
        
        # 来源匹配的高置信度
        if method == 'source':
            base_score = 0.90
        
        # 关键词匹配
        elif method == 'keyword':
            keyword_scores = features.get('keyword_scores', {})
            score = keyword_scores.get(category, 0)
            
            # 基础分数（最高 0.7）
            base_score = min(score * 0.15, 0.70)
            
            # 高价值关键词奖励
            text_lower = item.title.lower() + " " + (item.summary or "").lower()
            high_value = self.CATEGORIES[category]['high_value']
            for hv in high_value:
                if hv.lower() in text_lower:
                    base_score += 0.15
                    break
        
        # 语义分析
        elif method == 'semantic':
            base_score = 0.5  # 语义分析基础置信度较低
            
            # 标题长度合理性
            if 5 <= features.get('title_word_count', 0) <= 15:
                base_score += 0.1
            
            # 有摘要增加置信度
            if features.get('has_summary', 0) > 0:
                base_score += 0.1
        
        # 数量合理性奖励
        if features.get('number_ratio', 0) > 0.05:
            base_score += 0.05
        
        # 确保在 0-1 范围内
        return min(max(base_score, 0.0), 1.0)
    
    def _update_stats(self, classified: ClassifiedItem):
        """更新统计信息"""
        self._stats['total'] += 1
        self._stats['by_category'][classified.category] += 1
        self._stats['by_method'][classified.method] += 1
        
        if classified.confidence >= self.CONFIDENCE_THRESHOLD_HIGH:
            self._stats['confidence_distribution']['high'] += 1
        elif classified.confidence >= self.CONFIDENCE_THRESHOLD_MEDIUM:
            self._stats['confidence_distribution']['medium'] += 1
        else:
            self._stats['confidence_distribution']['low'] += 1
    
    def get_stats(self) -> Dict[str, any]:
        """
        获取统计信息
        
        Returns:
            Dict: 统计信息
        """
        return {
            'total': self._stats['total'],
            'by_category': dict(self._stats['by_category']),
            'by_method': dict(self._stats['by_method']),
            'confidence_distribution': dict(self._stats['confidence_distribution']),
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            'total': 0,
            'by_category': Counter(),
            'by_method': Counter(),
            'confidence_distribution': Counter({'high': 0, 'medium': 0, 'low': 0}),
        }
    
    def update_weights(self, weights: Dict[str, float]):
        """
        更新特征权重
        
        Args:
            weights: 新的权重字典
        """
        for key, value in weights.items():
            if key in self._weights:
                self._weights[key] = value
    
    def get_weights(self) -> Dict[str, float]:
        """
        获取当前权重
        
        Returns:
            Dict[str, float]: 当前权重
        """
        return self._weights.copy()
    
    def add_keywords(self, category: str, keywords: List[str]):
        """
        动态添加关键词
        
        Args:
            category: 分类名称
            keywords: 关键词列表
        """
        if category in self.CATEGORIES:
            self.CATEGORIES[category]['keywords'].extend(keywords)
            self._compile_patterns()
            logger.info(f"Added {len(keywords)} keywords to category '{category}'")
    
    def add_source(self, category: str, sources: List[str]):
        """
        动态添加来源
        
        Args:
            category: 分类名称
            sources: 来源列表
        """
        if category in self.CATEGORIES:
            self.CATEGORIES[category]['sources'].extend(sources)
            self._compile_patterns()
            logger.info(f"Added {len(sources)} sources to category '{category}'")
