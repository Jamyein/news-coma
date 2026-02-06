"""
ResultProcessor - 1-Pass 结果解析器

解析1-pass API响应，提取分类和评分信息
目标代码量: ~100行
"""

import json
import logging
from typing import List, Dict, Optional
from src.models import NewsItem

logger = logging.getLogger(__name__)


class ResultProcessor:
    """
    1-Pass结果解析器
    
    职责:
    1. 解析API返回的JSON响应
    2. 提取分类、评分、总结信息
    3. 处理解析错误和缺失字段
    4. 更新NewsItem对象
    """
    
    def __init__(self):
        """初始化结果处理器"""
        self._stats = {
            'total_parsed': 0,
            'parse_errors': 0,
            'missing_fields': 0
        }
        
        logger.info("ResultProcessor初始化完成")
    
    def parse_1pass_response(
        self,
        items: List[NewsItem],
        response: str
    ) -> List[NewsItem]:
        """
        解析1-pass API响应
        
        从JSON响应中提取：
        - 分类信息
        - 5维度评分
        - 总分
        - 中文总结
        
        Args:
            items: 原始新闻列表
            response: API响应内容（JSON字符串）
            
        Returns:
            List[NewsItem]: 已评分的新闻列表
        """
        try:
            # 解析JSON
            results = json.loads(response)
            
            # 确保是数组
            if not isinstance(results, list):
                logger.error(f"响应格式错误: 期望数组，得到{type(results)}")
                return self._apply_defaults(items)
            
            # 创建索引映射
            result_map = {}
            for result in results:
                if 'news_index' in result:
                    idx = result['news_index']
                    result_map[idx] = result
            
            # 应用到新闻项
            scored_items = []
            for i, item in enumerate(items, 1):
                if i in result_map:
                    scored_item = self._apply_result(item, result_map[i])
                    scored_items.append(scored_item)
                else:
                    logger.warning(f"新闻{i}未找到评分结果，使用默认值")
                    item.ai_score = 5.0
                    scored_items.append(item)
            
            self._stats['total_parsed'] += len(items)
            return scored_items
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            self._stats['parse_errors'] += 1
            return self._apply_defaults(items)
        except Exception as e:
            logger.error(f"解析响应时出错: {e}")
            self._stats['parse_errors'] += 1
            return self._apply_defaults(items)
    
    def _apply_result(self, item: NewsItem, result: Dict) -> NewsItem:
        """
        将解析结果应用到新闻项
        
        Args:
            item: 新闻项
            result: 解析结果字典
            
        Returns:
            NewsItem: 更新后的新闻项
        """
        # 分类信息
        valid_categories = {'财经', '科技', '社会政治'}
        category = result.get('category', '社会政治')
        if category not in valid_categories:
            category = '社会政治'
        
        item.ai_category = category
        item.ai_category_confidence = result.get('category_confidence', 0.5)
        
        # 5维度评分（计算加权总分）
        importance = result.get('importance', 5)
        timeliness = result.get('timeliness', 5)
        technical_depth = result.get('technical_depth', 5)
        audience_breadth = result.get('audience_breadth', 5)
        practicality = result.get('practicality', 5)
        
        # 使用返回的总分或计算
        total_score = result.get('total_score')
        if total_score is None:
            # 计算加权平均
            total_score = (
                importance * 0.30 +
                timeliness * 0.20 +
                technical_depth * 0.20 +
                audience_breadth * 0.15 +
                practicality * 0.15
            )
        
        item.ai_score = round(float(total_score), 1)
        
        # 总结
        item.ai_summary = result.get('summary', '')
        
        # 关键词（如果有）
        if 'key_points' in result:
            item.key_points = result['key_points']
        
        return item
    
    def _apply_defaults(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        应用默认分数（解析失败时使用）
        
        Args:
            items: 新闻列表
            
        Returns:
            List[NewsItem]: 带默认分数的新闻列表
        """
        for item in items:
            item.ai_score = 5.0
            item.ai_category = '社会政治'
            item.ai_category_confidence = 0.5
        
        self._stats['missing_fields'] += len(items)
        logger.warning(f"已应用默认分数到 {len(items)} 条新闻")
        
        return items
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self._stats.copy()
    
    def reset_stats(self):
        """重置统计"""
        self._stats = {
            'total_parsed': 0,
            'parse_errors': 0,
            'missing_fields': 0
        }
