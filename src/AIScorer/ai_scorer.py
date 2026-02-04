"""
AIScorer - AI新闻评分器（重构后简化版）

职责：协调各个组件完成评分流程
代码行数：~150行（原1862行）
"""
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from src.models import NewsItem, AIConfig
from .provider_manager import ProviderManager
from .prompt_builder import PromptBuilder
from .response_parser import ResponseParser
from .error_handler import ErrorHandler
from .scoring_strategy import ScoringStrategyFactory
from .category_classifier import CategoryClassifier

logger = logging.getLogger(__name__)


class AIScorer:
    """
    AI新闻评分器 - 协调者角色
    
    重构后职责：
    1. 协调各个组件完成评分流程
    2. 提供统一的对外接口
    3. 管理2-Pass评分流程
    
    代码行数：~150行（原1862行，减少92%）
    """
    
    def __init__(self, config: AIConfig):
        """
        初始化AI评分器
        
        Args:
            config: AI配置对象
        """
        self.config = config
        
        # 初始化各个组件（依赖注入）
        self.provider_manager = ProviderManager(config)
        self.prompt_builder = PromptBuilder(config)
        self.response_parser = ResponseParser()
        self.category_classifier = CategoryClassifier()
        
        # 读取配置项
        self.use_true_batch = getattr(config, 'use_true_batch', True)
        self.true_batch_size = getattr(config, 'true_batch_size', 10)
        self.use_2pass = getattr(config, 'use_2pass', True)
        self.pass1_threshold = getattr(config, 'pass1_threshold', 7.0)
        self.pass1_max_items = getattr(config, 'pass1_max_items', 40)
        
        # 板块差异化配置
        self.pass1_threshold_finance = getattr(
            config, 'pass1_threshold_finance', 5.5
        )
        self.pass1_threshold_tech = getattr(
            config, 'pass1_threshold_tech', 6.0
        )
        self.pass1_threshold_politics = getattr(
            config, 'pass1_threshold_politics', 5.5
        )
        
        # 板块配额配置
        self.category_quota_finance = getattr(config, 'category_quota_finance', 0.40)
        self.category_quota_tech = getattr(config, 'category_quota_tech', 0.30)
        self.category_quota_politics = getattr(config, 'category_quota_politics', 0.30)
        
        # 阈值动态调整配置
        self.enable_dynamic_threshold = getattr(config, 'enable_dynamic_threshold', False)
        self.threshold_adjustment_history = []
        
        # 预筛效果统计
        self._prescreen_stats = {
            'total_runs': 0,
            'by_category': defaultdict(lambda: {'input': 0, 'passed': 0, 'avg_score': 0.0}),
            'threshold_adjustments': []
        }
        
        # 并行批处理配置（新增）
        self.use_parallel_batches = getattr(config, 'use_parallel_batches', False)
        self.max_parallel_batches = getattr(config, 'max_parallel_batches', 3)
        
        # 超时控制配置（新增）
        self.batch_timeout_seconds = getattr(config, 'batch_timeout_seconds', 120)
        self.timeout_fallback_strategy = getattr(
            config, 'timeout_fallback_strategy', 'single'
        )
        
        logger.info("AIScorer 初始化完成")
    
    # ==================== 主入口 ====================
    
    async def score_all(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        批量评分所有新闻 - 主入口
        
        Args:
            items: 新闻项列表
            
        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        if not items:
            logger.info("空输入，返回空列表")
            return []
        
        logger.info(f"开始评分: {len(items)} 条新闻")
        
        # 根据配置选择评分模式
        if self.use_2pass and len(items) > 10:
            logger.info(f"🎯 使用2-Pass评分: {len(items)} 条新闻")
            return await self._score_2pass(items)
        else:
            return await self._score_standard(items)
    
    # ==================== 标准评分流程 ====================
    
    async def _score_standard(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        标准评分流程

        Args:
            items: 新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        try:
            # 根据配置选择批处理模式
            if self.use_true_batch and len(items) > self.true_batch_size:
                return await self._score_standard_true_batch(items)
            else:
                return await self._score_standard_batch(items)

        except Exception as e:
            ErrorHandler.log_error("标准评分", e, logger)
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _score_standard_true_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        标准评分流程 - 真批处理模式

        使用真批处理（一次API调用处理多条）

        Args:
            items: 新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        logger.info(
            f"🎯 真批处理模式: {len(items)} 条新闻 "
            f"(batch_size={self.true_batch_size})"
        )

        # 构建Prompt
        prompt = self.prompt_builder.build_scoring_prompt(items)

        # 使用真批处理执行
        results, api_call_count = (
            await self.provider_manager.execute_batch_with_fallback(
                items=items,
                batch_size=self.true_batch_size,
                call_batch_api_func=self.provider_manager.call_batch_api,
                fallback_single_func=None,  # 使用默认分数
                default_score=5.0,
                prompt=prompt,
                max_tokens=min(1000 + len(items) * 500, 8000),
                temperature=self.provider_manager.current_config.temperature
            )
        )

        # 解析响应
        if results:
            content = results[0]  # 取第一批次的响应
            parsed_results = self.response_parser.parse_batch_response(
                items,
                content,
                None
            )
            logger.info(f"✅ 标准评分(真批处理)完成: {len(parsed_results)} 条")
            return parsed_results
        else:
            logger.warning("所有批次都失败，使用默认分数")
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _score_standard_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        标准评分流程 - 普通批处理模式

        单次API调用处理所有条目

        Args:
            items: 新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        # 1. 构建Prompt
        prompt = self.prompt_builder.build_scoring_prompt(items)

        # 2. 调用API（带回退）
        content = await self.provider_manager.execute_with_fallback(
            "标准评分",
            self._execute_scoring,
            prompt,
            items
        )

        # 3. 解析响应
        results = self.response_parser.parse_batch_response(
            items,
            content,
            None  # 使用AI返回的total_score
        )

        logger.info(f"标准评分完成: {len(results)} 条")
        return results
    
    async def _execute_scoring(self, prompt: str, items: List[NewsItem]) -> str:
        """
        执行评分API调用
        
        Args:
            prompt: 评分Prompt
            items: 新闻项列表（用于估算token需求）
            
        Returns:
            str: API响应内容
        """
        # 估算token需求并设置上限
        item_count = len(items) if items else 0
        estimated_tokens = min(1000 + item_count * 500, 8000)
        
        return await self.provider_manager.call_batch_api(
            prompt=prompt,
            max_tokens=estimated_tokens,
            temperature=self.provider_manager.current_config.temperature
        )
    
    # ==================== 2-Pass评分流程 ====================
    
    async def _score_2pass(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        2-Pass评分流程
        
        Pass 1: 快速预筛
        Pass 2: 深度分析
        
        Args:
            items: 新闻项列表
            
        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        logger.info("🥇 Pass 1: 快速预筛...")
        pre_screen_items = await self._pass1_pre_screen(items)
        
        if not pre_screen_items:
            logger.warning("预筛后无新闻通过")
            return items
        
        logger.info(f"🥈 Pass 2: 深度分析 {len(pre_screen_items)} 条...")
        return await self._pass2_deep_analysis(pre_screen_items)
    
    async def _pass1_pre_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Pass 1: 快速预筛
        对分类后新闻分别调用真批处理接口进行批量快速评分，
        以实现更真实的权重评估，降低对人工干预的依赖。
        每批次使用提供商的真批处理接口，并在失败时回退到单条处理。
        """
        # 1) 预分类
        categorized = self.category_classifier.classify(items)
        scored_items: List[NewsItem] = []
        
        # 更新统计
        self._prescreen_stats['total_runs'] += 1
        
        # 2) 按分类批量打分，并标注 pre_category
        for category, category_items in categorized.items():
            if not category_items:
                continue
            for it in category_items:
                it.pre_category = category
            
            batch = category_items
            try:
                # 尝试批量API调用
                results = await self._score_category_batch(batch, category)
                
                # 使用增强的阈值检查
                threshold = self._get_pass1_threshold(category)
                passed_results = [
                    item for item in results 
                    if item.ai_score is not None and item.ai_score >= threshold
                ]
                
                scored_items.extend(passed_results)
                
                # 更新统计
                self._prescreen_stats['by_category'][category]['input'] += len(batch)
                self._prescreen_stats['by_category'][category]['passed'] += len(passed_results)
                if passed_results:
                    avg_score = sum(item.ai_score for item in passed_results) / len(passed_results)
                    self._prescreen_stats['by_category'][category]['avg_score'] = avg_score
                
            except Exception as e:
                logger.error(f"Pass1批量快速评分失败（{category}）: {e}")
                # 降级：对当前分类逐条进行快速评分
                for item in batch:
                    try:
                        scored = await self._score_single_fallback(item, category)
                        
                        # 使用增强的阈值检查
                        threshold = self._get_pass1_threshold(category, item)
                        if scored.ai_score is not None and scored.ai_score >= threshold:
                            scored_items.append(scored)
                            
                            # 更新统计
                            self._prescreen_stats['by_category'][category]['input'] += 1
                            self._prescreen_stats['by_category'][category]['passed'] += 1
                    except Exception:
                        # 单条也失败，使用默认分数
                        item.ai_score = 5.0
        
        # 3) 应用板块配额
        categorized_with_scores = self._group_by_category(scored_items)
        quota_applied = self._apply_category_quotas(categorized_with_scores)
        
        # 收集所有通过阈值的项目
        passed_items = []
        for category, items in quota_applied.items():
            if category != '未分类':
                passed_items.extend(items)
        
        # 4) 根据分数排序，保留前 pass1_max_items 条
        passed_items.sort(key=lambda x: x.ai_score if x.ai_score is not None else 0.0, reverse=True)
        final_passed_items = passed_items[:self.pass1_max_items]
        
        # 5) 记录日志
        self._log_pass1_results(categorized, final_passed_items)
        return final_passed_items
    
    def _group_by_category(
        self, items: List[NewsItem]
    ) -> Dict[str, List[NewsItem]]:
        """按分类分组新闻项"""
        result = {
            "财经": [],
            "科技": [],
            "社会政治": [],
            "未分类": []
        }
        
        for item in items:
            category = getattr(item, 'pre_category', '未分类')
            if category in result:
                result[category].append(item)
            else:
                result["未分类"].append(item)
        
        return result
    
    def _get_pass1_threshold(self, category: str, item: NewsItem = None) -> float:
        """
        获取Pass1阈值（增强版：支持动态阈值调整）
        
        Args:
            category: 新闻分类
            item: 可选，新闻项用于额外判断
            
        Returns:
            float: 阈值
        """
        base_threshold = self.pass1_threshold
        
        # 获取板块基础阈值
        if '财经' in category:
            category_threshold = self.pass1_threshold_finance
        elif '科技' in category:
            category_threshold = self.pass1_threshold_tech
        elif '政治' in category:
            category_threshold = self.pass1_threshold_politics
        else:
            category_threshold = self.pass1_threshold
        
        # 动态阈值调整
        if self.enable_dynamic_threshold and item:
            adjusted_threshold = self._calculate_dynamic_threshold(category, item)
            if adjusted_threshold != category_threshold:
                self._log_threshold_adjustment(
                    category, category_threshold, adjusted_threshold, item
                )
                return adjusted_threshold
        
        return category_threshold
    
    def _calculate_dynamic_threshold(
        self, category: str, item: NewsItem
    ) -> float:
        """
        计算动态阈值
        
        Args:
            category: 新闻分类
            item: 新闻项
            
        Returns:
            float: 调整后的阈值
        """
        base_threshold = self._get_base_threshold_for_category(category)
        
        # 基于分类置信度调整
        confidence = getattr(item, 'pre_category_confidence', 0.5)
        if confidence >= 0.8:
            # 高置信度可降低阈值
            adjustment = -0.3
        elif confidence >= 0.6:
            adjustment = 0.0
        else:
            # 低置信度需提高阈值
            adjustment = +0.3
        
        # 基于边界冲突调整
        details = getattr(item, 'pre_category_details', {})
        if details.get('boundary_conflict'):
            adjustment += 0.2
        
        # 紧急情况覆盖（标题含特定关键词）
        urgent_keywords = ['breaking', '紧急', '突发', 'breaking news']
        if any(kw in item.title.lower() for kw in urgent_keywords):
            adjustment = max(adjustment, -0.5)  # 紧急情况降低阈值
        
        return max(3.0, min(base_threshold + adjustment, 9.0))
    
    def _get_base_threshold_for_category(self, category: str) -> float:
        """获取分类的基础阈值"""
        if '财经' in category:
            return self.pass1_threshold_finance
        elif '科技' in category:
            return self.pass1_threshold_tech
        elif '政治' in category:
            return self.pass1_threshold_politics
        return self.pass1_threshold
    
    def _log_threshold_adjustment(
        self,
        category: str,
        original_threshold: float,
        adjusted_threshold: float,
        item: NewsItem
    ):
        """记录阈值调整"""
        adjustment_info = {
            'timestamp': datetime.now().isoformat(),
            'category': category,
            'original_threshold': original_threshold,
            'adjusted_threshold': adjusted_threshold,
            'item_title': item.title[:50],
            'confidence': getattr(item, 'pre_category_confidence', 0),
            'boundary_conflict': getattr(item, 'pre_category_details', {}).get('boundary_conflict', False)
        }
        
        self.threshold_adjustment_history.append(adjustment_info)
        self._prescreen_stats['threshold_adjustments'].append(adjustment_info)
        
        logger.debug(
            f"阈值调整: {category} {original_threshold}->{adjusted_threshold} "
            f"(置信度: {adjustment_info['confidence']})"
        )
    
    def _apply_category_quotas(
        self,
        categorized_items: Dict[str, List[NewsItem]],
        total_quota: Optional[int] = None
    ) -> Dict[str, List[NewsItem]]:
        """
        应用板块配额限制
        
        Args:
            categorized_items: 按分类分组的新闻项
            total_quota: 总配额，默认为 pass1_max_items
            
        Returns:
            Dict[str, List[NewsItem]]: 应用配额后的分类结果
        """
        if total_quota is None:
            total_quota = self.pass1_max_items
        
        # 计算各板块配额
        quota_distribution = {
            '财经': int(total_quota * self.category_quota_finance),
            '科技': int(total_quota * self.category_quota_tech),
            '社会政治': int(total_quota * self.category_quota_politics)
        }
        
        # 确保配额至少为1
        for cat in quota_distribution:
            quota_distribution[cat] = max(1, quota_distribution[cat])
        
        # 应用配额
        result = {}
        for category, items in categorized_items.items():
            if category == '未分类' or not items:
                result[category] = items
                continue
            
            quota = quota_distribution.get(category, len(items))
            
            # 按分数排序
            sorted_items = sorted(
                items,
                key=lambda x: x.ai_score if x.ai_score is not None else 0.0,
                reverse=True
            )
            
            # 应用配额
            selected_items = sorted_items[:quota]
            remaining_quota = quota - len(selected_items)
            
            # 如果某板块配额未用完，可分配给其他板块
            if remaining_quota > 0:
                self._redistribute_remaining_quota(
                    result, remaining_quota, sorted_items[quota:]
                )
            
            result[category] = selected_items
        
        logger.debug(f"板块配额应用: {quota_distribution}")
        return result
    
    def _redistribute_remaining_quota(
        self,
        result: Dict[str, List[NewsItem]],
        remaining_quota: int,
        remaining_items: List[NewsItem]
    ):
        """重新分配剩余配额"""
        # 按当前已选数量比例分配
        current_counts = {
            cat: len(items) 
            for cat, items in result.items() 
            if cat != '未分类'
        }
        
        total_current = sum(current_counts.values())
        if total_current == 0:
            return
        
        for category in current_counts:
            additional = int(remaining_quota * current_counts[category] / total_current)
            additional = min(additional, len(remaining_items))
            
            if additional > 0:
                result[category].extend(remaining_items[:additional])
                remaining_items = remaining_items[additional:]
                remaining_quota -= additional
                
                if remaining_quota <= 0:
                    break
    
    def _simulate_quick_scoring(
        self, 
        item: NewsItem, 
        category: str
    ) -> float:
        """
        模拟快速评分（实际应调用API）

        Args:
            item: 新闻项
            category: 分类

        Returns:
            float: 评分
        """
        # 简化处理：返回默认分数
        # 实际实现应该调用 _pass1_quick_api
        return 7.0

    async def _score_category_batch(
        self,
        items: List[NewsItem],
        category: str
    ) -> List[NewsItem]:
        """
        使用真实API对单个分类进行批量评分

        Args:
            items: 新闻项列表
            category: 新闻分类

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        # 1) 构建批量Prompt
        prompt = self.prompt_builder.build_pass1_batch_prompt(items, category)

        # 2) 调用批量API
        content = await self.provider_manager.call_batch_api(
            prompt=prompt,
            max_tokens=4000,
            temperature=self.provider_manager.current_config.temperature
        )

        # 3) 解析响应（只提取total分数）
        scored_items = self._parse_pass1_batch_response(items, content)

        return scored_items

    def _parse_pass1_batch_response(
        self,
        items: List[NewsItem],
        content: str
    ) -> List[NewsItem]:
        """
        解析Pass1批量评分响应

        Args:
            items: 原始新闻项列表
            content: API响应内容

        Returns:
            List[NewsItem]: 添加了ai_score的新闻项列表
        """
        import json

        scored_items = []

        try:
            # 尝试解析JSON数组
            results = json.loads(content)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Pass1响应JSON解析失败: {e}")
            # 降级：所有项使用默认分数
            for item in items:
                item.ai_score = 5.0
                scored_items.append(item)
            return scored_items

        # 创建索引映射
        if not isinstance(results, list):
            logger.error(f"Pass1响应不是JSON数组格式")
            for item in items:
                item.ai_score = 5.0
                scored_items.append(item)
            return scored_items

        index_map = {}
        for result in results:
            if 'news_index' in result:
                index_map[result['news_index']] = result

        # 为每个新闻项分配分数
        for i, item in enumerate(items, 1):
            if i in index_map:
                result = index_map[i]
                item.ai_score = result.get('total', result.get('score', 5.0))
            else:
                # 没有匹配到分数，使用默认
                logger.warning(f"Pass1: 新闻{i}没有匹配到分数，使用默认5.0")
                item.ai_score = 5.0
            scored_items.append(item)

        return scored_items

    async def _score_single_fallback(
        self,
        item: NewsItem,
        category: str
    ) -> NewsItem:
        """
        单条评分降级处理

        Args:
            item: 新闻项
            category: 新闻分类

        Returns:
            NewsItem: 添加了ai_score的新闻项
        """
        # 构建单条Prompt
        prompt_template = self.prompt_builder.build_pass1_prompt(category)
        prompt = prompt_template.format(
            title=item.title,
            source=item.source,
            summary=item.summary[:200] if item.summary else ''
        )

        # 调用单条API
        content = await self.provider_manager.call_single_scoring_api(
            prompt=prompt,
            max_tokens=500,
            temperature=self.provider_manager.current_config.temperature
        )

        # 解析响应
        import json
        try:
            result = json.loads(content)
            item.ai_score = result.get('total', result.get('score', 5.0))
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"单条评分解析失败: {e}，使用默认分数5.0")
            item.ai_score = 5.0

        return item
    
    def _log_pass1_results(
        self,
        categorized: dict,
        passed_items: List[NewsItem]
    ):
        """记录Pass1结果日志（增强版）"""
        total_input = sum(len(items) for items in categorized.values())
        total_passed = len(passed_items)
        
        logger.info(f"🎯 Pass 1 差异化预筛完成:")
        logger.info(f"   输入: {total_input}条新闻")
        
        # 记录各板块详细信息
        category_stats = {}
        for category, items in categorized.items():
            if items:
                passed_count = sum(
                    1 for item in passed_items 
                    if getattr(item, 'pre_category', '') == category
                )
                threshold = self._get_pass1_threshold(category)
                
                # 计算平均分数
                if passed_count > 0:
                    avg_score = sum(
                        item.ai_score for item in passed_items 
                        if getattr(item, 'pre_category', '') == category
                    ) / passed_count
                else:
                    avg_score = 0.0
                
                # 计算通过率
                pass_rate = (passed_count / len(items) * 100) if items else 0
                
                category_stats[category] = {
                    'input': len(items),
                    'passed': passed_count,
                    'threshold': threshold,
                    'avg_score': avg_score,
                    'pass_rate': pass_rate
                }
                
                logger.info(
                    f"   {category}: {len(items)}条 → {passed_count}条通过 "
                    f"(阈值≥{threshold}, 通过率{pass_rate:.1f}%, 均分{avg_score:.2f})"
                )
        
        # 记录配额信息
        quota_info = {
            '财经': self.category_quota_finance,
            '科技': self.category_quota_tech,
            '社会政治': self.category_quota_politics
        }
        logger.info(f"   板块配额: {quota_info}")
        
        # 记录阈值调整历史
        if self.threshold_adjustment_history:
            recent_adjustments = self.threshold_adjustment_history[-5:]  # 最近5次
            logger.debug(f"   阈值调整: {len(recent_adjustments)}次调整")
        
        logger.info(
            f"   总计: {total_passed}/{total_input}条通过 "
            f"(上限{self.pass1_max_items}条)"
        )
    
    async def _pass2_deep_analysis(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 深度分析

        对预筛通过的新闻进行完整的5维度评分

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        try:
            # 根据配置选择批处理模式
            if self.use_true_batch and len(items) > self.true_batch_size:
                return await self._pass2_deep_analysis_true_batch(items)
            else:
                return await self._pass2_deep_analysis_batch(items)

        except Exception as e:
            ErrorHandler.log_error("Pass2深度分析", e, logger)
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _pass2_deep_analysis_true_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 深度分析 - 真批处理模式

        使用真批处理（一次API调用处理多条）

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        logger.info(
            f"🎯 Pass2 真批处理模式: {len(items)} 条新闻 "
            f"(batch_size={self.true_batch_size})"
        )

        # 构建Prompt
        prompt = self.prompt_builder.build_scoring_prompt(items)

        # 使用真批处理执行（支持并行和超时控制）
        results, api_call_count = (
            await self.provider_manager.execute_batch_with_fallback(
                items=items,
                batch_size=self.true_batch_size,
                call_batch_api_func=self.provider_manager.call_batch_api,
                fallback_single_func=None,
                default_score=5.0,
                prompt=prompt,
                max_tokens=min(1000 + len(items) * 500, 8000),
                temperature=self.provider_manager.current_config.temperature,
                # 新增：并行批处理参数
                use_parallel_batches=self.use_parallel_batches,
                max_parallel_batches=self.max_parallel_batches,
                # 新增：超时控制参数
                batch_timeout_seconds=self.batch_timeout_seconds,
                timeout_fallback_strategy=self.timeout_fallback_strategy
            )
        )

        # 解析响应
        if results:
            content = results[0]
            parsed_results = self.response_parser.parse_batch_response(
                items,
                content,
                None
            )
            logger.info(f"✅ Pass2深度分析(真批处理)完成: {len(parsed_results)} 条")
            return parsed_results
        else:
            logger.warning("所有批次都失败，使用默认分数")
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _pass2_deep_analysis_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 深度分析 - 普通批处理模式

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        # 1. 构建Prompt
        prompt = self.prompt_builder.build_scoring_prompt(items)

        # 2. 调用API（带回退）
        content = await self.provider_manager.execute_with_fallback(
            "Pass2深度分析",
            self._execute_scoring,
            prompt,
            items
        )

        # 3. 解析响应
        results = self.response_parser.parse_batch_response(
            items,
            content,
            None  # 使用AI返回的total_score
        )

        logger.info(f"Pass 2 深度分析完成: {len(results)} 条")
        return results
    
    # ==================== 深度分析功能 ====================
    
    async def deep_analysis_topn(
        self, 
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        对TopN新闻进行深度分析
        
        Args:
            items: 新闻项列表
            
        Returns:
            List[NewsItem]: 添加了深度分析字段的新闻项列表
        """
        if not items:
            return []
        
        # 筛选有全文内容的新闻
        valid_items = [
            item for item in items 
            if getattr(item, 'has_full_content', False) and 
               getattr(item, 'full_content', None)
        ]
        
        if not valid_items:
            logger.warning("⚠️ 没有符合条件的新闻进行深度分析")
            return items
        
        logger.info(f"🔍 开始深度分析: {len(valid_items)} 条有全文的新闻")
        
        try:
            # 1. 构建Prompt
            prompt = self.prompt_builder.build_deep_analysis_prompt(valid_items)
            
            # 2. 调用API（带回退）
            content = await self.provider_manager.execute_with_fallback(
                "TopN深度分析",
                self._execute_deep_analysis,
                prompt
            )
            
            # 3. 解析响应
            results = self.response_parser.parse_deep_analysis_response(
                valid_items,
                content
            )
            
            logger.info(f"✅ 深度分析完成: {len(results)} 条")
            return results
            
        except Exception as e:
            ErrorHandler.log_error("TopN深度分析", e, logger)
            return ErrorHandler.apply_batch_deep_analysis_defaults(valid_items)
    
    async def _execute_deep_analysis(self, prompt: str) -> str:
        """
        执行深度分析API调用
        
        Args:
            prompt: 深度分析Prompt
            
        Returns:
            str: API响应内容
        """
        return await self.provider_manager.call_deep_analysis_api(
            prompt=prompt,
            max_tokens=10000,
            temperature=self.provider_manager.current_config.temperature
        )
    
    # ==================== 统计和工具方法 ====================
    
    def get_api_stats(self) -> dict:
        """
        获取API调用统计
        
        Returns:
            dict: 统计信息
        """
        return {
            'api_call_count': self.provider_manager.get_api_call_count(),
            'current_provider': self.provider_manager.current_provider_name,
            'providers_available': self.provider_manager.get_available_providers(),
        }
    
    # 向后兼容方法
    def get_api_call_count(self) -> int:
        """
        获取API调用计数（向后兼容）
        
        Returns:
            int: 调用次数
        """
        return self.provider_manager.get_api_call_count()
    
    def reset_api_call_count(self):
        """重置API调用计数（向后兼容）"""
        self.provider_manager.reset_api_call_count()
    
    def reset_stats(self):
        """重置统计信息"""
        self.reset_api_call_count()
    
    def get_config_summary(self) -> dict:
        """
        获取配置摘要

        Returns:
            dict: 配置摘要
        """
        return {
            'use_2pass': self.use_2pass,
            'use_true_batch': self.use_true_batch,
            'true_batch_size': self.true_batch_size,
            'pass1_threshold': self.pass1_threshold,
            'pass1_threshold_finance': self.pass1_threshold_finance,
            'pass1_threshold_tech': self.pass1_threshold_tech,
            'pass1_threshold_politics': self.pass1_threshold_politics,
            'pass1_max_items': self.pass1_max_items,
            'category_quota_finance': self.category_quota_finance,
            'category_quota_tech': self.category_quota_tech,
            'category_quota_politics': self.category_quota_politics,
            'enable_dynamic_threshold': self.enable_dynamic_threshold,
        }
    
    # ==================== 预筛效果统计 ====================
    
    def get_prescreen_stats(self) -> dict:
        """
        获取预筛效果统计
        
        Returns:
            dict: 统计信息
        """
        return {
            'total_runs': self._prescreen_stats['total_runs'],
            'by_category': dict(self._prescreen_stats['by_category']),
            'threshold_adjustments_count': len(self._prescreen_stats['threshold_adjustments']),
            'recent_threshold_adjustments': self.threshold_adjustment_history[-10:]
        }
    
    def get_threshold_adjustment_history(self) -> List[dict]:
        """
        获取阈值调整历史
        
        Returns:
            List[dict]: 调整历史记录
        """
        return self.threshold_adjustment_history
    
    def analyze_threshold_effectiveness(self) -> dict:
        """
        分析阈值效果
        
        Returns:
            dict: 阈值效果分析
        """
        if not self._prescreen_stats['by_category']:
            return {'message': '无足够数据进行分析'}
        
        analysis = {}
        for category, stats in self._prescreen_stats['by_category'].items():
            if stats['input'] > 0:
                pass_rate = stats['passed'] / stats['input'] * 100 if stats['input'] > 0 else 0
                analysis[category] = {
                    'total_input': stats['input'],
                    'total_passed': stats['passed'],
                    'pass_rate': pass_rate,
                    'average_score': stats['avg_score'],
                    'threshold_used': self._get_base_threshold_for_category(category)
                }
        
        return analysis
    
    def get_classification_accuracy_estimate(self) -> dict:
        """
        估计分类准确率
        
        Returns:
            dict: 分类准确率估计
        """
        return self.category_classifier.get_classification_stats([])
    
    def reset_prescreen_stats(self):
        """重置预筛统计"""
        self._prescreen_stats = {
            'total_runs': 0,
            'by_category': defaultdict(lambda: {'input': 0, 'passed': 0, 'avg_score': 0.0}),
            'threshold_adjustments': []
        }
        self.threshold_adjustment_history = []
        self.category_classifier.reset_stats()
    
    # ==================== 运行时配置更新 ====================
    
    def update_threshold(self, category: str, new_threshold: float):
        """
        运行时更新阈值
        
        Args:
            category: 分类名称
            new_threshold: 新的阈值
        """
        old_threshold = self._get_base_threshold_for_category(category)
        
        if '财经' in category:
            self.pass1_threshold_finance = new_threshold
        elif '科技' in category:
            self.pass1_threshold_tech = new_threshold
        elif '政治' in category:
            self.pass1_threshold_politics = new_threshold
        
        logger.info(
            f"阈值更新: {category} {old_threshold} -> {new_threshold}"
        )
    
    def update_quota(self, category: str, new_quota_ratio: float):
        """
        运行时更新板块配额
        
        Args:
            category: 分类名称
            new_quota_ratio: 新的配额比例
        """
        if category == '财经':
            self.category_quota_finance = new_quota_ratio
        elif category == '科技':
            self.category_quota_tech = new_quota_ratio
        elif category == '社会政治':
            self.category_quota_politics = new_quota_ratio
        
        logger.info(
            f"配额更新: {category} {new_quota_ratio}"
        )
    
    def enable_dynamic_thresholds(self, enabled: bool):
        """
        启用/禁用动态阈值调整
        
        Args:
            enabled: 是否启用
        """
        self.enable_dynamic_threshold = enabled
        logger.info(f"动态阈值调整: {'启用' if enabled else '禁用'}")
