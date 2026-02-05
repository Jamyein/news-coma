"""
响应解析器 - 统一JSON响应解析

解决原 ai_scorer.py 中3处重复的JSON清理和解析逻辑（56行重复代码）
"""
import json
import re
from typing import Any, List, Dict, Set
from datetime import datetime
from src.models import NewsItem
from .error_handler import ErrorHandler


class ResponseParser:
    """
    统一响应解析器
    
    提供统一的JSON响应解析、清理和映射功能
    替代原代码中3处重复的JSON解析逻辑
    
    解决的重复代码：
    - 行号451-472 (_parse_batch_response)
    - 行号1548-1569 (_parse_deep_analysis_response)
    - 行号1801-1812 (_parse_single_deep_analysis_response)
    """
    
    # 常见的markdown包装标记
    MARKDOWN_PATTERNS = [
        (r'^```json\s*', ''),      # ```json
        (r'^```\s*', ''),           # ```
        (r'\s*```$', ''),           # 结尾的 ```
    ]
    
    @staticmethod
    def clean_json_content(content: str) -> str:
        """
        清理JSON响应中的markdown标记

        Args:
            content: 原始响应内容

        Returns:
            str: 清理后的内容
        """
        if not content:
            return "{}"

        # 移除markdown代码块标记
        cleaned = content.strip()

        for pattern, replacement in ResponseParser.MARKDOWN_PATTERNS:
            cleaned = re.sub(pattern, replacement, cleaned)

        return cleaned.strip()

    @staticmethod
    def fix_truncated_json(content: str) -> str:
        """
        修复可能被截断的JSON字符串

        Args:
            content: 原始JSON内容

        Returns:
            str: 修复后的JSON内容
        """
        if not content:
            return "{}"

        content = content.strip()

        # 统计开闭括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')

        # 如果字符串在引号中未闭合，尝试截断到最后一个完整键值对
        in_string = False
        escape_next = False
        last_safe_index = len(content)

        for i, char in enumerate(content):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"' and not in_string:
                in_string = True
            elif char == '"' and in_string:
                in_string = False
                last_safe_index = i + 1

        # 如果字符串未闭合，截断到最后安全位置
        if in_string and last_safe_index < len(content):
            content = content[:last_safe_index]
            # 重新计算括号
            open_braces = content.count('{') - content.count('}')
            open_brackets = content.count('[') - content.count(']')

        # 补齐括号
        while open_braces > 0:
            content += '}'
            open_braces -= 1
        while open_brackets > 0:
            content += ']'
            open_brackets -= 1

        # 处理多余的闭括号（在开头截断的情况）
        while content and content[0] in '}]':
            content = content[1:]

        return content if content else "{}"
    
    @staticmethod
    def extract_data_list(data: Any) -> List[Dict]:
        """
        从可能的包装对象中提取数据列表
        
        Args:
            data: JSON解析后的数据
            
        Returns:
            List[Dict]: 数据列表
        """
        # 如果本身就是列表，直接返回
        if isinstance(data, list):
            return data
        
        # 如果是字典，寻找其中的列表字段
        if isinstance(data, dict):
            # 常见的包装字段名
            possible_keys = ['results', 'data', 'items', 'news', 'analyses', 'output']
            
            for key in possible_keys:
                if key in data and isinstance(data[key], list):
                    return data[key]
            
            # 如果找不到常见字段，查找任何列表类型的值
            for key, value in data.items():
                if isinstance(value, list):
                    return value
        
        # 返回空列表
        return []
    
    @classmethod
    def parse_json_response(
        cls, 
        content: str,
        logger=None
    ) -> List[Dict]:
        """
        完整的JSON解析流程
        
        Args:
            content: 原始响应内容
            logger: 日志记录器（可选）
            
        Returns:
            List[Dict]: 解析后的数据列表
            
        Raises:
            ValueError: JSON解析失败
        """
        try:
            cleaned = cls.clean_json_content(content)
            data = json.loads(cleaned)
            data_list = cls.extract_data_list(data)

            if not data_list:
                raise ValueError("响应中未找到数据列表")

            return data_list

        except json.JSONDecodeError as e:
            ErrorHandler.log_error(
                context="JSON解析",
                error=e,
                logger=logger,
                level='warning'
            )
            # 尝试修复截断的JSON
            try:
                fixed = cls.fix_truncated_json(content)
                data = json.loads(fixed)
                data_list = cls.extract_data_list(data)

                if data_list:
                    if logger:
                        logger.info(f"[JSON修复] 成功修复截断的JSON，提取到 {len(data_list)} 条数据")
                    return data_list
            except Exception as fix_error:
                if logger:
                    logger.warning(f"[JSON修复] 修复失败: {fix_error}")

            raise ValueError(f"JSON解析失败: {e}")
    
    @classmethod
    def parse_batch_response(
        cls,
        items: List[NewsItem],
        content: str,
        scoring_strategy=None,
        logger=None
    ) -> List[NewsItem]:
        """
        解析批量评分响应
        
        替代原 _parse_batch_response 方法
        
        Args:
            items: 新闻项列表
            content: 原始响应内容
            scoring_strategy: 评分策略（可选）
            logger: 日志记录器（可选）
            
        Returns:
            List[NewsItem]: 解析后的新闻项列表
        """
        try:
            data_list = cls.parse_json_response(content, logger)
            
            results = []
            processed_indices: Set[int] = set()
            
            for item_data in data_list:
                try:
                    # 获取新闻索引
                    index = item_data.get('news_index', 0) - 1
                    
                    # 验证索引
                    if 0 <= index < len(items) and index not in processed_indices:
                        item = items[index]
                        
                        # 应用评分结果
                        cls._apply_batch_scores(
                            item, 
                            item_data, 
                            scoring_strategy,
                            logger
                        )
                        
                        results.append(item)
                        processed_indices.add(index)
                        
                except Exception as e:
                    ErrorHandler.log_error(
                        context="解析单条结果",
                        error=e,
                        logger=logger,
                        level='warning'
                    )
                    continue
            
            # 处理未返回结果的条目
            for i, item in enumerate(items):
                if i not in processed_indices:
                    ErrorHandler.apply_default_values(item, 'no_response')
                    results.append(item)
                    ErrorHandler.log_error(
                        context="批处理未返回结果",
                        error=f"索引 {i}: {item.title[:30]}...",
                        logger=logger,
                        level='warning'
                    )
            
            return results
            
        except Exception as e:
            ErrorHandler.log_error(
                context="批量解析",
                error=e,
                logger=logger,
                level='error'
            )
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')
    
    @classmethod
    def _apply_batch_scores(
        cls,
        item: NewsItem,
        item_data: Dict,
        scoring_strategy=None,
        logger=None
    ):
        """
        应用批量评分结果到新闻项
        
        Args:
            item: 新闻项
            item_data: 评分数据
            scoring_strategy: 评分策略
            logger: 日志记录器
        """
        # 获取分类
        category = item_data.get('category', '')
        
        # 存储分类信息
        item.ai_category = category
        item.ai_category_confidence = item_data.get('category_confidence', 0.0)
        
        # 计算分数
        if 'total_score' in item_data:
            # 使用AI计算的分数
            try:
                item.ai_score = round(float(item_data['total_score']), 1)
            except (ValueError, TypeError):
                item.ai_score = 5.0
        elif scoring_strategy:
            # 使用评分策略计算
            item.ai_score = scoring_strategy.calculate_score(item_data)
        else:
            # 默认分数
            item.ai_score = 5.0
        
        # 应用其他字段
        item.translated_title = item_data.get('chinese_title', item.title)
        item.ai_summary = item_data.get('chinese_summary', '')
        item.key_points = item_data.get('key_points', [])
        
        if not item.key_points:
            item.key_points = []
    
    @classmethod
    def parse_single_response(
        cls,
        item: NewsItem,
        content: str,
        criteria: Dict[str, float],
        logger=None
    ) -> NewsItem:
        """
        解析单条响应
        
        替代原 _parse_response 方法
        
        Args:
            item: 新闻项
            content: 原始响应内容
            criteria: 评分权重
            logger: 日志记录器（可选）
            
        Returns:
            NewsItem: 解析后的新闻项
        """
        try:
            data = json.loads(content)
            
            # 计算加权总分
            total_score = sum(
                data.get(key, 5) * weight
                for key, weight in criteria.items()
            )
            
            item.ai_score = round(total_score, 1)
            item.translated_title = data.get('chinese_title', item.title)
            item.ai_summary = data.get('chinese_summary', '')
            item.key_points = data.get('key_points', [])
            
            if not item.key_points:
                item.key_points = []
            
            return item
            
        except Exception as e:
            ErrorHandler.log_error(
                context="单条解析",
                error=e,
                logger=logger,
                level='error'
            )
            return ErrorHandler.apply_default_values(item, 'parse_failed')
    
    @classmethod
    def parse_response_with_fallback(
        cls,
        items: List[NewsItem],
        content: str,
        scoring_strategy=None,
        criteria: Dict[str, float] = None,
        logger=None
    ) -> List[NewsItem]:
        """
        解析响应（带降级处理）
        
        智能选择批量或单条解析方式
        
        Args:
            items: 新闻项列表
            content: 原始响应内容
            scoring_strategy: 评分策略
            criteria: 评分权重（单条解析时使用）
            logger: 日志记录器
            
        Returns:
            List[NewsItem]: 解析后的新闻项列表
        """
        # 尝试批量解析
        try:
            return cls.parse_batch_response(
                items, content, scoring_strategy, logger
            )
        except ValueError:
            # 降级为单条解析
            if criteria:
                return [
                    cls.parse_single_response(item, content, criteria, logger)
                    for item in items
                ]
            else:
                # 使用默认值
                return ErrorHandler.apply_batch_defaults(items, 'parse_failed')
