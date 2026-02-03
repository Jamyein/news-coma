"""
分类器 - 新闻分类逻辑

从原 ai_scorer.py 的 _pre_categorize_items 方法提取，使其独立可测试
"""
import re
import logging
from typing import List, Dict, Tuple, Optional
from collections import Counter
from difflib import SequenceMatcher

from src.models import NewsItem

logger = logging.getLogger(__name__)


class CategoryClassifier:
    """
    新闻分类器
    
    基于来源和关键词将新闻分为三大板块：
    - 财经
    - 科技
    - 社会政治
    
    提取自原 _pre_categorize_items 方法（行号930-1053）
    使分类逻辑独立可测试
    """
    
    # 财经来源关键词
    FINANCE_SOURCES = [
        "wsj 经济", "wsj 市场", "financial times", "bloomberg",
        "cnbc", "marketwatch", "ft.com", "华尔街见闻",
        "东方财富", "财新", "经济观察", "36氪", "香港經濟日報",
        "the economist", "bbc business", "wsj 全球经济",
        "reuters business", "financial post", "barron's",
        "investing.com", "yahoo finance", "market watch"
    ]
    
    # 科技来源关键词
    TECH_SOURCES = [
        "the verge", "techcrunch", "hacker news", "github blog",
        "arstechnica", "wired", "engadget", "36氪", "华尔街见闻",
        "techmeme", "verge", "the next web", "product hunt",
        "github trending", "hacker noon", "dev.to"
    ]
    
    # 社会政治来源关键词
    POLITICS_SOURCES = [
        "bbc", "the guardian", "politico", "wsj 时政",
        "reuters", "associated press", "ap news", "36氪", 
        "华尔街见闻", "nytimes", "washington post",
        "cnn politics", "fox news", "MSNBC"
    ]
    
    # 财经标题关键词
    FINANCE_KEYWORDS = [
        # 中文
        "股票", "股市", "投资", "银行", "利率", "通胀", "财报",
        "央行", "美联储", "利率决议", "货币政策", "财政政策",
        "经济数据", "GDP", "CPI", "PPI", "汇率", "人民币",
        "美股", "港股", "A股", "基金", "债券", "期货",
        "大宗商品", "黄金", "石油", "天然气", "铜", "铝",
        "房地产", "房价", "房贷", "限购", "限贷",
        "数字货币", "比特币", "以太坊", "crypto",
        
        # 英文
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
    ]
    
    # 科技标题关键词
    TECH_KEYWORDS = [
        # 中文
        "ai", "人工智能", "机器学习", "深度学习", "神经网络",
        "芯片", "半导体", "处理器", "GPU", "CPU", "AI芯片",
        "软件", "app", "应用程序", "移动应用",
        "互联网", "互联网公司", "科技公司", "IT",
        "算法", "大数据", "云计算", "区块链", "物联网",
        "5G", "6G", "网络", "网络安全", "黑客",
        "创业", "初创公司", " startup", "创新", "研发",
        "智能", "智能机", "智能手机", "智能汽车", "自动驾驶",
        "元宇宙", "VR", "AR", "虚拟现实", "增强现实",
        
        # 英文
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
    ]
    
    # 社会政治标题关键词
    POLITICS_KEYWORDS = [
        # 中文
        "政策", "选举", "政府", "国会", "议会", "法案",
        "特朗普", "拜登", "习近平", "普京", "各国领导人",
        "外交", "国际", "国际关系", "外交关系",
        "战争", "和平", "冲突", "军事", "国防", "安全",
        "环境", "气候", "能源", "碳中和", "碳排放",
        "健康", "疫情", "公共卫生", "医疗", "疫苗",
        "教育", "社会福利", "移民", "难民",
        "法律", "法规", "监管", "诉讼", "判决",
        
        # 英文
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
    ]
    
    # 行业术语同义词扩展
    SYNONYMS = {
        "财经": {
            "股票": ["股价", "股指", "个股", "证券", "股本"],
            "投资": ["理财", "资产配置", "持仓", "建仓"],
            "银行": ["银行业", "商业银行", "央行", "美联储"],
            "通胀": ["通货膨胀", "物价上涨", " CPI"],
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
    
    # 模糊匹配阈值
    FUZZY_MATCH_THRESHOLD = 0.8
    
    def __init__(self):
        """初始化分类器"""
        # 预编译正则表达式（提高性能）
        self._compile_regex()
        
        # 初始化统计计数器
        self._classification_stats = {
            'total_classified': 0,
            'by_category': Counter(),
            'confidence_distribution': Counter({'high': 0, 'medium': 0, 'low': 0}),
            'reclassified': 0
        }
    
    def _compile_regex(self):
        """预编译关键词正则表达式"""
        import re
        
        # 编译所有关键词列表为正则表达式
        self._finance_pattern = self._build_pattern(self.FINANCE_KEYWORDS)
        self._tech_pattern = self._build_pattern(self.TECH_KEYWORDS)
        self._politics_pattern = self._build_pattern(self.POLITICS_KEYWORDS)
        
        self._finance_source_pattern = self._build_pattern(self.FINANCE_SOURCES)
        self._tech_source_pattern = self._build_pattern(self.TECH_SOURCES)
        self._politics_source_pattern = self._build_pattern(self.POLITICS_SOURCES)
        
        # 编译同义词正则表达式
        self._synonym_patterns = self._build_synonym_patterns()
    
    def _build_pattern(self, keywords: List[str]) -> re.Pattern:
        """将关键词列表编译为正则表达式"""
        import re
        
        # 转义特殊字符并构建模式
        escaped = [re.escape(kw) for kw in keywords]
        pattern = '|'.join(escaped)
        
        return re.compile(pattern, re.IGNORECASE)
    
    def _build_synonym_patterns(self) -> Dict[str, Dict[str, re.Pattern]]:
        """构建同义词正则表达式模式"""
        patterns = {}
        for category, synonyms in self.SYNONYMS.items():
            patterns[category] = {}
            for main_word, synonym_list in synonyms.items():
                all_terms = [main_word] + synonym_list
                patterns[category][main_word] = self._build_pattern(all_terms)
        return patterns
    
    def classify(self, items: List[NewsItem]) -> Dict[str, List[NewsItem]]:
        """
        预分类：基于来源和关键词快速将新闻分为三大板块
        
        Args:
            items: 新闻项列表
            
        Returns:
            Dict[str, List[NewsItem]]:
                {
                    "财经": [...],
                    "科技": [...],
                    "社会政治": [...],
                    "未分类": [...]
                }
        """
        result = {
            "财经": [],
            "科技": [],
            "社会政治": [],
            "未分类": []
        }
        
        for item in items:
            category, confidence, details = self.classify_single(item)
            
            # 存储分类信息到新闻项
            item.pre_category = category
            item.pre_category_confidence = confidence
            item.pre_category_details = details
            
            # 添加到对应分类
            if category in result:
                result[category].append(item)
            else:
                result["未分类"].append(item)
            
            # 更新统计
            self._classification_stats['total_classified'] += 1
            self._classification_stats['by_category'][category if category else '未分类'] += 1
            
            if confidence >= 0.8:
                self._classification_stats['confidence_distribution']['high'] += 1
            elif confidence >= 0.6:
                self._classification_stats['confidence_distribution']['medium'] += 1
            else:
                self._classification_stats['confidence_distribution']['low'] += 1
        
        return result
    
    def classify_single(self, item: NewsItem) -> Tuple[str, float, Dict]:
        """
        分类单条新闻（增强版：返回详细分类信息）
        
        Args:
            item: 新闻项
            
        Returns:
            Tuple[str, float, Dict]: (分类名称, 置信度, 详细分类信息)
        """
        source_lower = item.source.lower()
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        
        details = {
            'source_match': None,
            'keyword_matches': {},
            'title_relevance': 0.0,
            'synonym_matches': {},
            'boundary_conflict': False
        }
        
        # 1. 检查来源匹配
        source_category, source_confidence = self._check_source_detailed(source_lower)
        details['source_match'] = source_category
        
        if source_category:
            details['boundary_conflict'] = self._check_boundary_conflict(source_category, title_lower, summary_lower)
            return source_category, source_confidence, details
        
        # 2. 检查标题关键词匹配
        title_category, keyword_scores, match_counts = self._check_title_keywords_detailed(title_lower)
        details['keyword_matches'] = keyword_scores
        details['match_counts'] = match_counts
        
        if title_category:
            # 计算标题相关性
            title_relevance = self._calculate_title_relevance(item, title_category)
            details['title_relevance'] = title_relevance
            
            # 计算综合置信度
            confidence = self._calculate_confidence(
                source_match=False,
                keyword_matches=keyword_scores.get(title_category, 0),
                title_relevance=title_relevance,
                match_counts=match_counts
            )
            
            # 检查边界冲突
            details['boundary_conflict'] = self._check_boundary_conflict(
                title_category, title_lower, summary_lower
            )
            
            return title_category, confidence, details
        
        # 3. 尝试摘要关键词匹配
        summary_category, summary_scores = self._check_summary_keywords(summary_lower)
        if summary_category:
            details['summary_matches'] = summary_scores
            confidence = summary_scores.get(summary_category, 0) * 0.5
            return summary_category, confidence, details
        
        # 4. 尝试模糊匹配
        fuzzy_category, fuzzy_confidence = self._fuzzy_match(item)
        if fuzzy_category:
            details['fuzzy_match'] = fuzzy_category
            return fuzzy_category, fuzzy_confidence, details
        
        # 5. 未匹配任何关键词 - 尝试二次分类
        reclassified_category, reclassified_confidence = self._reclassify_uncertain(item)
        if reclassified_category:
            details['reclassified'] = True
            self._classification_stats['reclassified'] += 1
            return reclassified_category, reclassified_confidence, details
        
        # 6. 完全未分类
        return "", 0.0, details
    
    def _check_source_detailed(self, source_lower: str) -> Tuple[Optional[str], float]:
        """详细检查来源匹配"""
        if self._finance_source_pattern.search(source_lower):
            return "财经", 0.9
        elif self._tech_source_pattern.search(source_lower):
            return "科技", 0.9
        elif self._politics_source_pattern.search(source_lower):
            return "社会政治", 0.9
        return None, 0.0
    
    def _check_title_keywords_detailed(
        self, title_lower: str
    ) -> Tuple[Optional[str], Dict[str, int], Dict[str, int]]:
        """
        详细检查标题关键词
        
        Returns:
            Tuple[分类, 各分类匹配数, 各分类权重分]
        """
        # 基础关键词匹配
        finance_matches = len(self._finance_pattern.findall(title_lower))
        tech_matches = len(self._tech_pattern.findall(title_lower))
        politics_matches = len(self._politics_pattern.findall(title_lower))
        
        match_counts = {
            '财经': finance_matches,
            '科技': tech_matches,
            '社会政治': politics_matches
        }
        
        # 计算加权分数（考虑关键词重要性）
        keyword_scores = {
            '财经': self._calculate_weighted_score('财经', finance_matches, title_lower),
            '科技': self._calculate_weighted_score('科技', tech_matches, title_lower),
            '社会政治': self._calculate_weighted_score('社会政治', politics_matches, title_lower)
        }
        
        max_score = max(keyword_scores.values())
        
        if max_score == 0:
            return None, {}, match_counts
        
        # 确定最佳分类
        if max_score == keyword_scores['财经']:
            return "财经", keyword_scores, match_counts
        elif max_score == keyword_scores['科技']:
            return "科技", keyword_scores, match_counts
        else:
            return "社会政治", keyword_scores, match_counts
    
    def _calculate_weighted_score(
        self, category: str, match_count: int, title_lower: str
    ) -> float:
        """计算加权分数"""
        if match_count == 0:
            return 0.0
        
        # 基础分数
        base_score = match_count * 1.0
        
        # 高价值关键词加权
        high_value_keywords = {
            '财经': ['stock', 'market', 'fed', 'inflation', 'gdp', '央行', '美联储', '财报'],
            '科技': ['ai', 'gpt', 'chip', 'semiconductor', '人工智能', '芯片'],
            '社会政治': ['election', 'government', 'policy', 'trump', 'biden', '政府', '选举']
        }
        
        bonus = 0.0
        for kw in high_value_keywords.get(category, []):
            if kw.lower() in title_lower:
                bonus += 0.3
        
        return min(base_score + bonus, 3.0)
    
    def _check_summary_keywords(self, summary_lower: str) -> Tuple[Optional[str], Dict[str, float]]:
        """检查摘要中的关键词"""
        finance_matches = len(self._finance_pattern.findall(summary_lower))
        tech_matches = len(self._tech_pattern.findall(summary_lower))
        politics_matches = len(self._politics_pattern.findall(summary_lower))
        
        scores = {
            '财经': finance_matches * 0.5,
            '科技': tech_matches * 0.5,
            '社会政治': politics_matches * 0.5
        }
        
        max_score = max(scores.values())
        if max_score == 0:
            return None, scores
        
        if max_score == scores['财经']:
            return "财经", scores
        elif max_score == scores['科技']:
            return "科技", scores
        else:
            return "社会政治", scores
    
    def _calculate_confidence(
        self,
        source_match: bool,
        keyword_matches: int,
        title_relevance: float,
        match_counts: Dict[str, int]
    ) -> float:
        """计算分类置信度（增强版）"""
        base_confidence = 0.0
        
        if source_match:
            base_confidence += 0.4  # 来源匹配权重
        
        # 关键词匹配权重（最多0.3）
        keyword_weight = min(keyword_matches * 0.1, 0.3)
        base_confidence += keyword_weight
        
        # 标题相关性权重
        base_confidence += title_relevance * 0.2
        
        # 匹配多样性奖励
        total_matches = sum(match_counts.values())
        if total_matches > 2:
            base_confidence += 0.1
        
        return min(base_confidence, 1.0)
    
    def _calculate_title_relevance(self, item: NewsItem, category: str) -> float:
        """计算标题与分类的相关性"""
        title_lower = item.title.lower()
        summary_lower = (item.summary or "").lower()
        
        # 检查同义词匹配
        synonym_score = 0.0
        if category in self.SYNONYMS:
            for main_word, synonym_list in self.SYNONYMS[category].items():
                pattern = self._synonym_patterns[category].get(main_word)
                if pattern:
                    if pattern.search(title_lower):
                        synonym_score += 0.2
                    elif pattern.search(summary_lower):
                        synonym_score += 0.1
        
        # 检查标题长度相关性
        title_length = len(title_lower.split())
        if 5 <= title_length <= 15:  # 合理标题长度
            title_length_score = 0.1
        else:
            title_length_score = 0.0
        
        return min(synonym_score + title_length_score, 0.5)
    
    def _fuzzy_match(self, item: NewsItem) -> Tuple[Optional[str], float]:
        """模糊匹配"""
        title_lower = item.title.lower()
        
        # 尝试使用编辑距离匹配
        for category, keywords in {
            '财经': self.FINANCE_KEYWORDS[:20],
            '科技': self.TECH_KEYWORDS[:20],
            '社会政治': self.POLITICS_KEYWORDS[:20]
        }.items():
            for kw in keywords:
                kw_lower = kw.lower()
                similarity = SequenceMatcher(None, title_lower[:50], kw_lower[:50]).ratio()
                
                if similarity >= self.FUZZY_MATCH_THRESHOLD:
                    logger.debug(f"模糊匹配: '{item.title}' -> '{kw}' (相似度: {similarity:.2f})")
                    return category, similarity * 0.6  # 降低置信度
        
        return None, 0.0
    
    def _reclassify_uncertain(self, item: NewsItem) -> Tuple[Optional[str], float]:
        """二次分类尝试（对不确定的分类）"""
        # 使用摘要进行二次判断
        summary_lower = (item.summary or "").lower()
        
        # 统计各类关键词在摘要中的出现次数
        finance_count = len(self._finance_pattern.findall(summary_lower))
        tech_count = len(self._tech_pattern.findall(summary_lower))
        politics_count = len(self._politics_pattern.findall(summary_lower))
        
        counts = {'财经': finance_count, '科技': tech_count, '社会政治': politics_count}
        max_count = max(counts.values())
        
        if max_count >= 2:  # 需要至少2个关键词匹配
            category = max(counts, key=counts.get)
            confidence = 0.3  # 较低置信度
            return category, confidence
        
        return None, 0.0
    
    def _check_boundary_conflict(
        self, primary_category: str, title_lower: str, summary_lower: str
    ) -> bool:
        """检查分类边界冲突"""
        text_lower = title_lower + " " + summary_lower
        
        # 检查是否有其他分类的强烈信号
        conflict_categories = {
            '财经': {'tech': self._tech_pattern, 'politics': self._politics_pattern},
            '科技': {'finance': self._finance_pattern, 'politics': self._politics_pattern},
            '社会政治': {'finance': self._finance_pattern, 'tech': self._tech_pattern}
        }
        
        conflicts = conflict_categories.get(primary_category, {})
        for conflict_name, pattern in conflicts.items():
            matches = len(pattern.findall(text_lower))
            if matches >= 2:  # 其他分类有多个匹配
                return True
        
        return False
    
    def _check_source(self, source_lower: str) -> str:
        """检查来源"""
        if self._finance_source_pattern.search(source_lower):
            return "财经"
        elif self._tech_source_pattern.search(source_lower):
            return "科技"
        elif self._politics_source_pattern.search(source_lower):
            return "社会政治"
        
        return ""
    
    def _check_title_keywords(self, title_lower: str) -> str:
        """检查标题关键词"""
        finance_matches = len(self._finance_pattern.findall(title_lower))
        tech_matches = len(self._tech_pattern.findall(title_lower))
        politics_matches = len(self._politics_pattern.findall(title_lower))
        
        max_matches = max(finance_matches, tech_matches, politics_matches)
        
        if max_matches == 0:
            return ""
        
        if max_matches == finance_matches:
            return "财经"
        elif max_matches == tech_matches:
            return "科技"
        else:
            return "社会政治"
    
    def get_classification_stats(
        self, 
        items: List[NewsItem]
    ) -> Dict[str, any]:
        """
        获取分类统计信息
        
        Args:
            items: 新闻项列表
            
        Returns:
            Dict: 统计信息
        """
        categorized = self.classify(items)
        
        total = len(items)
        stats = {
            "total": total,
            "by_category": {},
            "confidence_distribution": {
                "high": 0,    # 置信度 >= 0.8
                "medium": 0,  # 置信度 0.6-0.8
                "low": 0,     # 置信度 < 0.6
            }
        }
        
        for category, category_items in categorized.items():
            stats["by_category"][category] = {
                "count": len(category_items),
                "percentage": round(len(category_items) / total * 100, 2) if total > 0 else 0
            }
            
            for item in category_items:
                confidence = getattr(item, 'pre_category_confidence', 0)
                if confidence >= 0.8:
                    stats["confidence_distribution"]["high"] += 1
                elif confidence >= 0.6:
                    stats["confidence_distribution"]["medium"] += 1
                else:
                    stats["confidence_distribution"]["low"] += 1
        
        return stats
    
    def get_keywords_for_category(self, category: str) -> List[str]:
        """
        获取指定分类的关键词列表
        
        Args:
            category: 分类名称
            
        Returns:
            List[str]: 关键词列表
        """
        keywords_map = {
            "财经": self.FINANCE_KEYWORDS + self.FINANCE_SOURCES,
            "科技": self.TECH_KEYWORDS + self.TECH_SOURCES,
            "社会政治": self.POLITICS_KEYWORDS + self.POLITICS_SOURCES,
        }
        
        return keywords_map.get(category, [])
    
    def add_keywords(self, category: str, keywords: List[str]):
        """
        动态添加关键词
        
        Args:
            category: 分类名称
            keywords: 要添加的关键词列表
        """
        keywords_map = {
            "财经": self.FINANCE_KEYWORDS,
            "科技": self.TECH_KEYWORDS,
            "社会政治": self.POLITICS_KEYWORDS,
        }
        
        if category in keywords_map:
            keywords_map[category].extend(keywords)
            # 重新编译正则表达式
            self._compile_regex()
    
    def remove_keywords(self, category: str, keywords: List[str]):
        """
        动态删除关键词
        
        Args:
            category: 分类名称
            keywords: 要删除的关键词列表
        """
        keywords_map = {
            "财经": self.FINANCE_KEYWORDS,
            "科技": self.TECH_KEYWORDS,
            "社会政治": self.POLITICS_KEYWORDS,
        }
        
        if category in keywords_map:
            for kw in keywords:
                if kw in keywords_map[category]:
                    keywords_map[category].remove(kw)
            # 重新编译正则表达式
            self._compile_regex()
    
    def add_synonyms(self, category: str, main_word: str, synonyms: List[str]):
        """
        动态添加同义词
        
        Args:
            category: 分类名称
            main_word: 主词
            synonyms: 同义词列表
        """
        if category not in self.SYNONYMS:
            self.SYNONYMS[category] = {}
        
        if main_word not in self.SYNONYMS[category]:
            self.SYNONYMS[category][main_word] = []
        
        self.SYNONYMS[category][main_word].extend(synonyms)
        # 重新编译同义词模式
        self._build_synonym_patterns()
    
    def get_classification_history(self) -> Dict[str, any]:
        """
        获取分类历史统计
        
        Returns:
            Dict: 历史统计信息
        """
        return {
            'total_classified': self._classification_stats['total_classified'],
            'by_category': dict(self._classification_stats['by_category']),
            'confidence_distribution': dict(self._classification_stats['confidence_distribution']),
            'reclassified_count': self._classification_stats['reclassified']
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self._classification_stats = {
            'total_classified': 0,
            'by_category': Counter(),
            'confidence_distribution': Counter({'high': 0, 'medium': 0, 'low': 0}),
            'reclassified': 0
        }
