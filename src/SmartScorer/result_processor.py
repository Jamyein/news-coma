"""ResultProcessor - 1-Pass 结果解析器"""

import json
import logging
from src.models import NewsItem, AIConfig


logger = logging.getLogger(__name__)


class ResultProcessor:
    """1-Pass结果解析器"""

    VALID_CATEGORIES = {'财经', '科技', '社会政治'}

    def __init__(self, config: AIConfig = None):
        """
        初始化结果解析器
        
        Args:
            config: AI配置对象，用于获取默认分数等配置值
        """
        self.config = config
        self._stats = {
            'total_parsed': 0,
            'parse_errors': 0,
            'missing_fields': 0
        }
        logger.info("ResultProcessor初始化完成")
    
    @property
    def default_score(self) -> float:
        """获取默认分数（从配置或回退到硬编码值）"""
        if self.config:
            return self.config.default_score_on_parse_error
        return 5.0  # 回退默认值
    
    def _apply_default_score(self, item: NewsItem, reason: str = "unknown") -> None:
        """统一应用默认分数和分类"""
        item.ai_score = self.default_score
        item.ai_category = '社会政治'
        item.ai_category_confidence = 0.5
        item.ai_summary = f"[系统默认值 - {reason}]"
        logger.debug(f"为新闻 '{item.title[:30]}...' 应用默认分数 (原因: {reason})")

    def _apply_default_to_batch(self, items: list[NewsItem], reason: str = "parse_error") -> None:
        """为一批新闻应用默认值"""
        for item in items:
            self._apply_default_score(item, reason)
        self._stats['missing_fields'] += len(items)
        logger.warning(f"已为 {len(items)} 条新闻应用默认分数 (原因: {reason})")

    def parse_1pass_response(self, items: list[NewsItem], response: str) -> list[NewsItem]:
        """解析1-pass API响应"""
        try:
            results = json.loads(response)

            if not isinstance(results, list):
                logger.error(f"响应格式错误: 期望数组，得到{type(results)}")
                self._apply_default_to_batch(items, "invalid_response_format")
                return items

            result_map = {r['news_index']: r for r in results if 'news_index' in r}

            scored_items = []
            for i, item in enumerate(items, 1):
                if i in result_map:
                    scored_items.append(self._apply_result(item, result_map[i]))
                else:
                    logger.warning(f"新闻{i}未找到评分结果，使用默认值")
                    self._apply_default_score(item, "missing_index")
                    scored_items.append(item)

            self._stats['total_parsed'] += len(items)
            return scored_items

        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"解析失败: {e}")
            self._stats['parse_errors'] += 1
            self._apply_default_to_batch(items, "json_decode_error")
            return items
    
    def _apply_result(self, item: NewsItem, result: dict) -> NewsItem:
        """将解析结果应用到新闻项"""
        # 分类
        category = result.get('category', '社会政治')
        item.ai_category = category if category in self.VALID_CATEGORIES else '社会政治'
        item.ai_category_confidence = result.get('category_confidence', 0.5)

        # 分数 - 使用配置中的默认值
        dim_default = self.config.default_dimension_score if self.config else 5
        total_score = result.get('total_score')
        if total_score is None:
            total_score = (
                result.get('importance', dim_default) * 0.30 +
                result.get('timeliness', dim_default) * 0.20 +
                result.get('technical_depth', dim_default) * 0.20 +
                result.get('audience_breadth', dim_default) * 0.15 +
                result.get('practicality', dim_default) * 0.15
            )
        item.ai_score = round(float(total_score), 1)

        # 总结
        item.ai_summary = result.get('summary', '')
        if 'key_points' in result:
            item.key_points = result['key_points']

        return item
    
    def _apply_defaults(self, items: list[NewsItem]) -> list[NewsItem]:
        """应用默认分数"""
        self._apply_default_to_batch(items, "apply_defaults")
        return items

    def get_stats(self) -> dict:
        return self._stats.copy()

    def reset_stats(self):
        self._stats = {'total_parsed': 0, 'parse_errors': 0, 'missing_fields': 0}
