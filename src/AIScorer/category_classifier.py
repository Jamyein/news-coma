"""
分类器 - 新闻分类逻辑

从原 ai_scorer.py 的 _pre_categorize_items 方法提取，使其独立可测试
"""
from typing import List, Dict, Tuple
from src.models import NewsItem


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
    
    def __init__(self):
        """初始化分类器"""
        # 预编译正则表达式（提高性能）
        self._compile_regex()
    
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
    
    def _build_pattern(self, keywords: List[str]) -> re.Pattern:
        """将关键词列表编译为正则表达式"""
        import re
        
        # 转义特殊字符并构建模式
        escaped = [re.escape(kw) for kw in keywords]
        pattern = '|'.join(escaped)
        
        return re.compile(pattern, re.IGNORECASE)
    
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
            category, confidence = self.classify_single(item)
            
            # 存储分类信息到新闻项
            item.pre_category = category
            item.pre_category_confidence = confidence
            
            # 添加到对应分类
            if category in result:
                result[category].append(item)
            else:
                result["未分类"].append(item)
        
        return result
    
    def classify_single(self, item: NewsItem) -> Tuple[str, float]:
        """
        分类单条新闻
        
        Args:
            item: 新闻项
            
        Returns:
            Tuple[str, float]: (分类名称, 置信度)
        """
        source_lower = item.source.lower()
        title_lower = item.title.lower()
        
        # 1. 检查来源（置信度0.8）
        category = self._check_source(source_lower)
        if category:
            return category, 0.8
        
        # 2. 检查标题关键词（置信度0.6）
        category = self._check_title_keywords(title_lower)
        if category:
            return category, 0.6
        
        # 3. 未匹配任何关键词
        return "", 0.0
    
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
