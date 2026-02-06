"""ResultProcessor - 1-Pass 结果解析器"""

import json
import logging
from typing import List, Dict
from src.models import NewsItem

logger = logging.getLogger(__name__)


class ResultProcessor:
    """1-Pass结果解析器"""

    VALID_CATEGORIES = {'财经', '科技', '社会政治'}
    DEFAULT_SCORE = 5.0

    def __init__(self):
        self._stats = {
            'total_parsed': 0,
            'parse_errors': 0,
            'missing_fields': 0
        }
        logger.info("ResultProcessor初始化完成")
    
    def parse_1pass_response(self, items: List[NewsItem], response: str) -> List[NewsItem]:
        """解析1-pass API响应"""
        try:
            results = json.loads(response)

            if not isinstance(results, list):
                logger.error(f"响应格式错误: 期望数组，得到{type(results)}")
                return self._apply_defaults(items)

            result_map = {r['news_index']: r for r in results if 'news_index' in r}

            scored_items = []
            for i, item in enumerate(items, 1):
                if i in result_map:
                    scored_items.append(self._apply_result(item, result_map[i]))
                else:
                    logger.warning(f"新闻{i}未找到评分结果，使用默认值")
                    item.ai_score = self.DEFAULT_SCORE
                    scored_items.append(item)

            self._stats['total_parsed'] += len(items)
            return scored_items

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"解析失败: {e}")
            self._stats['parse_errors'] += 1
            return self._apply_defaults(items)
    
    def _apply_result(self, item: NewsItem, result: Dict) -> NewsItem:
        """将解析结果应用到新闻项"""
        # 分类
        category = result.get('category', '社会政治')
        item.ai_category = category if category in self.VALID_CATEGORIES else '社会政治'
        item.ai_category_confidence = result.get('category_confidence', 0.5)

        # 分数
        total_score = result.get('total_score')
        if total_score is None:
            total_score = (
                result.get('importance', 5) * 0.30 +
                result.get('timeliness', 5) * 0.20 +
                result.get('technical_depth', 5) * 0.20 +
                result.get('audience_breadth', 5) * 0.15 +
                result.get('practicality', 5) * 0.15
            )
        item.ai_score = round(float(total_score), 1)

        # 总结
        item.ai_summary = result.get('summary', '')
        if 'key_points' in result:
            item.key_points = result['key_points']

        return item
    
    def _apply_defaults(self, items: List[NewsItem]) -> List[NewsItem]:
        """应用默认分数"""
        for item in items:
            item.ai_score = self.DEFAULT_SCORE
            item.ai_category = '社会政治'
            item.ai_category_confidence = 0.5

        self._stats['missing_fields'] += len(items)
        logger.warning(f"已应用默认分数到 {len(items)} 条新闻")
        return items

    def get_stats(self) -> Dict:
        return self._stats.copy()

    def reset_stats(self):
        self._stats = {'total_parsed': 0, 'parse_errors': 0, 'missing_fields': 0}
