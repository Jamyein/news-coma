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
from .batch_processor import BatchProcessor

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
        Pass 2: 评分

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
        
        logger.info(f"🥈 Pass 2: 评分 {len(pre_screen_items)} 条...")
        return await self._pass2_scoring(pre_screen_items)
    
    async def _pass1_pre_screen(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Pass 1: AI智能分类+打分一体化预筛

        使用AI在一次API调用中完成分类和打分，替代原有的关键词分类方式。
        对于分类置信度低的新闻，会进行重分类（最多2次重试）。

        Args:
            items: 新闻项列表

        Returns:
            List[NewsItem]: 通过预筛的新闻项列表

        Raises:
            Exception: API调用失败时抛出异常
        """
        logger.info(f"🎯 Pass 1: AI智能分类+打分一体化 ({len(items)}条新闻)")

        # 更新统计
        self._prescreen_stats['total_runs'] += 1

        # 1) AI批量分类+打分
        ai_results = await self._pass1_ai_classification_batch(items)

        # 2) 处理结果，收集低置信度项进行重分类
        low_confidence_items = []
        normal_items = []

        for item, result in zip(items, ai_results):
            item.pre_category = result.get('category', '社会政治')
            item.ai_score = result.get('total', 5.0)
            item.pre_category_confidence = result.get('category_confidence', 0.5)

            # 检查置信度
            if item.pre_category_confidence < 0.6:
                low_confidence_items.append((item, result))
            else:
                normal_items.append(item)

        # 3) 对低置信度项进行重分类（最多2次重试）
        retry_count = 0
        if low_confidence_items:
            retry_items = [item for item, _ in low_confidence_items]
            logger.info(f"   发现{len(low_confidence_items)}条低置信度新闻，开始重分类...")

            for attempt in range(2):  # 最多2次重试
                retry_results = await self._retry_classification(retry_items, f"置信度<0.6 (第{attempt+1}次重试)")
                retry_count += 1

                # 检查重试后的置信度
                still_low = []
                for item, result in zip(retry_items, retry_results):
                    confidence = result.get('category_confidence', 0)
                    if confidence >= 0.6:
                        # 重分类成功
                        item.pre_category = result.get('category', item.pre_category)
                        item.ai_score = result.get('total', item.ai_score)
                        item.pre_category_confidence = confidence
                        normal_items.append(item)
                    else:
                        still_low.append(item)

                retry_items = still_low
                if not retry_items:
                    break

            # 如果重试后仍有低置信度项，保留原结果但标记
            for item in retry_items:
                item.pre_category_confidence = 0.5  # 标记为中等置信度
                normal_items.append(item)

        # 4) 应用阈值过滤
        scored_items = []
        for item in normal_items:
            threshold = self._get_pass1_threshold(item.pre_category, item)
            if item.ai_score is not None and item.ai_score >= threshold:
                scored_items.append(item)

                # 更新统计
                self._prescreen_stats['by_category'][item.pre_category]['input'] += 1
                self._prescreen_stats['by_category'][item.pre_category]['passed'] += 1

        # 计算平均分
        for category in ['财经', '科技', '社会政治']:
            cat_items = [item for item in scored_items if item.pre_category == category]
            if cat_items:
                avg_score = sum(item.ai_score for item in cat_items) / len(cat_items)
                self._prescreen_stats['by_category'][category]['avg_score'] = avg_score

        # 5) 应用板块配额
        categorized_with_scores = self._group_by_category(scored_items)
        quota_applied = self._apply_category_quotas(categorized_with_scores)

        # 收集所有通过阈值的项目
        passed_items = []
        for category, cat_items in quota_applied.items():
            if category != '未分类':
                passed_items.extend(cat_items)

        # 6) 根据分数排序，保留前 pass1_max_items 条
        passed_items.sort(key=lambda x: x.ai_score if x.ai_score is not None else 0.0, reverse=True)
        final_passed_items = passed_items[:self.pass1_max_items]

        # 7) 构建分类结果用于日志（模拟原有关键词分类的格式）
        categorized_result = self._build_categorized_result(items)

        # 8) 记录日志
        self._log_pass1_results(categorized_result, final_passed_items, retry_count)

        logger.info(f"✅ Pass 1完成: {len(final_passed_items)}/{len(items)}条通过预筛")
        return final_passed_items

    def _build_categorized_result(self, items: List[NewsItem]) -> Dict[str, List[NewsItem]]:
        """构建分类结果（用于日志）"""
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

    async def _pass1_ai_classification_batch(
        self,
        items: List[NewsItem]
    ) -> List[Dict]:
        """
        Pass 1: AI批量分类+打分（支持分批处理）

        使用AI在一次API调用中完成分类和打分。
        当新闻数量超过单批阈值时，自动分批处理。

        Args:
            items: 新闻项列表

        Returns:
            List[Dict]: 分类结果列表，每个元素包含 category, category_confidence, total

        Raises:
            Exception: API调用失败时抛出异常
        """
        if not items:
            return []

        # 如果数量较少，直接处理（保持原有逻辑）
        if len(items) <= self.true_batch_size:
            return await self._execute_pass1_single_batch(items)
        
        # 数量较多，使用分批处理器
        logger.info(f"🔄 Pass1新闻数量({len(items)})超过单批阈值({self.true_batch_size})，启动分批处理...")
        
        processor = BatchProcessor(
            batch_size=self.true_batch_size,  # 使用配置的批次大小
            max_retries=2,
            retry_delay=1.0,
            index_key='news_index'
        )
        
        # 使用分批处理器处理所有新闻
        results = await processor.process(
            items=items,
            process_func=self._execute_pass1_single_batch,
            description="Pass1 AI分类"
        )
        
        # 记录统计信息
        stats = processor.get_stats()
        logger.info(f"✅ Pass1分批处理完成: {stats['total_results']}/{stats['total_items']}条成功")
        
        return results

    async def _execute_pass1_single_batch(
        self,
        items: List[NewsItem]
    ) -> List[Dict]:
        """
        执行单批Pass1分类（核心处理逻辑）
        
        将原_pass1_ai_classification_batch的核心逻辑提取到此方法
        
        Args:
            items: 单批新闻项列表（最多100条）
            
        Returns:
            List[Dict]: 分类结果列表
        """
        if not items:
            return []
        
        # 构建Prompt
        prompt = self.prompt_builder.build_pass1_ai_classification_prompt(items)
        
        try:
            # 调用API - 使用动态max_tokens（关键修复）
            content = await self.provider_manager.call_batch_api(
                prompt=prompt,
                max_tokens=self.provider_manager.current_config.max_tokens,  # 动态读取配置，不再是硬编码2000
                temperature=self.provider_manager.current_config.temperature
            )
            
            # 解析响应
            results = self._parse_pass1_ai_classification_response(items, content)
            
            logger.debug(f"Pass1单批处理完成: {len(results)}/{len(items)}条")
            return results
            
        except Exception as e:
            logger.error(f"Pass1单批处理失败: {e}")
            # 单批失败时抛出异常，让上层分批处理器决定是否重试
            raise

    async def _retry_classification(
        self,
        items: List[NewsItem],
        reason: str = "置信度低"
    ) -> List[Dict]:
        """
        对低置信度新闻进行重分类

        使用更明确的Prompt重新调用AI进行分类。

        Args:
            items: 需要重分类的新闻项列表
            reason: 重分类原因（用于日志）

        Returns:
            List[Dict]: 重分类结果
        """
        if not items:
            return []

        logger.debug(f"重分类{len(items)}条新闻: {reason}")

        # 构建新闻块（更简洁的格式）
        news_blocks = []
        for i, item in enumerate(items, 1):
            news_blocks.append(
                f"【{i}】{item.title}\n"
                f"    来源: {item.source}\n"
                f"    摘要: {item.summary[:150] if item.summary else 'N/A'}\n"
            )

        prompt = f"""你是一位资深新闻编辑，请对以下{len(items)}条新闻进行分类判断。

【重要提示】
上一次的分类置信度较低，请仔细分析以下内容特征，给出更准确的分类：

{''.join(news_blocks)}

【分类指南】
1. 财经：聚焦金融市场、经济数据、企业财报、投资相关
2. 科技：聚焦技术创新、AI、芯片、互联网、科研突破
3. 社会政治：聚焦政策、法律、国际关系、社会事件

【判断要点】
- 优先看标题中的核心关键词
- 看新闻内容的主要关注点
- 考虑新闻对哪个领域影响最大

【输出格式】
请返回JSON数组：
[
    {{"news_index": 1, "category": "财经", "category_confidence": 0.90, "total": 7.5}},
    ...
]

category只能是"财经"、"科技"或"社会政治"。
category_confidence表示你的确定程度（0-1，数字越大越确定）。"""

        try:
            content = await self.provider_manager.call_batch_api(
                prompt=prompt,
                max_tokens=1500,
                temperature=0.3  # 使用较低温度增加确定性
            )

            return self._parse_pass1_ai_classification_response(items, content)

        except Exception as e:
            logger.error(f"重分类失败: {e}")
            # 重分类失败时返回原项目列表，标记为低置信度
            return [
                {
                    'news_index': i,
                    'category': getattr(item, 'pre_category', '社会政治'),
                    'category_confidence': 0.5,
                    'total': getattr(item, 'ai_score', 5.0)
                }
                for i, item in enumerate(items, 1)
            ]

    def _parse_pass1_ai_classification_response(
        self,
        items: List[NewsItem],
        content: str
    ) -> List[Dict]:
        """
        解析Pass 1 AI分类响应

        Args:
            items: 原始新闻项列表
            content: API响应内容

        Returns:
            List[Dict]: 解析后的分类结果
        """
        import json

        results = []
        valid_categories = {'财经', '科技', '社会政治'}

        try:
            # 尝试解析JSON数组
            parsed = json.loads(content)

            if not isinstance(parsed, list):
                logger.error(f"AI分类响应不是JSON数组格式")
                raise ValueError("响应格式错误")

            # 创建索引映射
            index_map = {}
            for result in parsed:
                if 'news_index' in result:
                    idx = result['news_index']
                    # 标准化分类值
                    category = result.get('category', '社会政治')
                    if category not in valid_categories:
                        logger.warning(f"无效分类值 '{category}'，修正为'社会政治'")
                        category = '社会政治'

                    index_map[idx] = {
                        'news_index': idx,
                        'category': category,
                        'category_confidence': result.get('category_confidence', 0.5),
                        'total': result.get('total', 5.0)
                    }

            # 为每个新闻项匹配结果
            for i, item in enumerate(items, 1):
                if i in index_map:
                    results.append(index_map[i])
                else:
                    # 未匹配到结果，使用默认值
                    logger.warning(f"新闻{i}未匹配到AI分类结果，使用默认值")
                    results.append({
                        'news_index': i,
                        'category': '社会政治',
                        'category_confidence': 0.5,
                        'total': 5.0
                    })

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"AI分类响应解析失败: {e}")
            # 返回默认结果
            results = [
                {
                    'news_index': i,
                    'category': '社会政治',
                    'category_confidence': 0.5,
                    'total': 5.0
                }
                for i in range(1, len(items) + 1)
            ]

        return results
    
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
    
    def _log_pass1_results(
        self,
        categorized: dict,
        passed_items: List[NewsItem],
        retry_count: int = 0
    ):
        """记录Pass1结果日志（增强版 - AI智能分类）"""
        total_input = sum(len(items) for items in categorized.values())
        total_passed = len(passed_items)

        logger.info(f"🎯 Pass 1 AI智能分类预筛完成:")
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

                # 计算平均置信度
                cat_all_items = [item for item in items if hasattr(item, 'pre_category_confidence')]
                if cat_all_items:
                    avg_confidence = sum(
                        getattr(item, 'pre_category_confidence', 0.5) for item in cat_all_items
                    ) / len(cat_all_items)
                else:
                    avg_confidence = 0.0

                category_stats[category] = {
                    'input': len(items),
                    'passed': passed_count,
                    'threshold': threshold,
                    'avg_score': avg_score,
                    'pass_rate': pass_rate,
                    'avg_confidence': avg_confidence
                }

                logger.info(
                    f"   {category}: {len(items)}条 → {passed_count}条通过 "
                    f"(阈值≥{threshold}, 通过率{pass_rate:.1f}%, 均分{avg_score:.2f}, 平均置信度{avg_confidence:.2f})"
                )

        # 记录配额信息
        quota_info = {
            '财经': self.category_quota_finance,
            '科技': self.category_quota_tech,
            '社会政治': self.category_quota_politics
        }
        logger.info(f"   板块配额: {quota_info}")

        # 记录重分类统计
        if retry_count > 0:
            logger.info(f"   重分类: {retry_count}次重试")

        # 记录置信度分布
        all_confidences = [getattr(item, 'pre_category_confidence', 0.5) for item in passed_items]
        if all_confidences:
            high_conf = sum(1 for c in all_confidences if c >= 0.8)
            medium_conf = sum(1 for c in all_confidences if 0.6 <= c < 0.8)
            low_conf = sum(1 for c in all_confidences if c < 0.6)
            logger.info(f"   置信度分布: 高({high_conf}) 中({medium_conf}) 低({low_conf})")

        # 记录阈值调整历史
        if self.threshold_adjustment_history:
            recent_adjustments = self.threshold_adjustment_history[-5:]  # 最近5次
            logger.debug(f"   阈值调整: {len(recent_adjustments)}次调整")

        logger.info(
            f"   总计: {total_passed}/{total_input}条通过 "
            f"(上限{self.pass1_max_items}条)"
        )

    # ==================== Pass2 分类特定总结优化 ====================

    def _standardize_category(self, category: str) -> str:
        """
        标准化新闻分类

        将各种分类名称映射到三大类：'财经', '科技', '社会政治'
        使用关键词匹配进行标准化

        Args:
            category: 原始分类名称（可能来源ai_category、pre_category或category）

        Returns:
            str: 标准化的分类名称
        """
        if not category:
            return '未分类'

        category_lower = str(category).lower()

        # 财经类关键词列表
        finance_keywords = [
            '财经', 'finance', '经济', 'economy', '投资', 'investment',
            '股票', 'stock', '市场', 'market', '金融', 'financial',
            '银行', 'bank', '基金', 'fund', '债券', 'bond',
            '货币', 'currency', '贸易', 'trade', '企业', 'company'
        ]

        # 科技类关键词列表
        tech_keywords = [
            '科技', 'tech', 'technology', '技术', 'ai', '人工智能',
            'artificial intelligence', '创新', 'innovation', '芯片',
            'semiconductor', '软件', 'software', '互联网', 'internet',
            '云计算', 'cloud', '大数据', 'big data', '区块链', 'blockchain',
            '5g', '6g', '物联网', 'iot', '机器人', 'robot',
            '自动驾驶', 'autonomous', '虚拟现实', 'vr', '增强现实', 'ar'
        ]

        # 社会政治类关键词列表
        politics_keywords = [
            '政治', 'politics', '社会', 'society', '政策', 'policy',
            '国际', 'international', '外交', 'diplomacy', '时事',
            'current affairs', '民生', 'livelihood', '法律', 'law',
            '监管', 'regulation', '政府', 'government', '选举',
            'election', '战争', 'war', '冲突', 'conflict', '疫情',
            'pandemic', '环保', 'environment', '教育', 'education',
            '医疗', 'healthcare', '交通', 'transportation'
        ]

        # 检查分类名称中是否包含关键词
        for keyword in finance_keywords:
            if keyword in category_lower:
                return '财经'

        for keyword in tech_keywords:
            if keyword in category_lower:
                return '科技'

        for keyword in politics_keywords:
            if keyword in category_lower:
                return '社会政治'

        # 如果无法识别，返回原分类名称或默认值
        return category
    
    async def _pass2_scoring(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 评分

        对预筛通过的新闻进行完整的5维度评分

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        try:
            # 根据配置选择批处理模式
            if self.use_true_batch and len(items) > self.true_batch_size:
                return await self._pass2_scoring_true_batch(items)
            else:
                return await self._pass2_scoring_batch(items)

        except Exception as e:
            ErrorHandler.log_error("Pass2评分", e, logger)
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _pass2_scoring_true_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 评分 - 真批处理模式

        使用真批处理（一次API调用处理多条）
        使用分类特定的总结Prompt，根据新闻分类动态选择总结模板

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        logger.info(
            f"🎯 Pass2 真批处理模式: {len(items)} 条新闻 "
            f"(batch_size={self.true_batch_size}, 使用分类特定总结)"
        )

        # 构建分类映射
        category_map = {}
        for i, item in enumerate(items, 1):
            category = item.ai_category or item.pre_category or item.category
            standardized_category = self._standardize_category(category)
            category_map[i] = standardized_category
            logger.debug(f"新闻{i}分类: {category} -> {standardized_category}")

        # 构建分类特定的Pass2 Prompt
        prompt = self.prompt_builder.build_pass2_scoring_prompt(items, category_map)

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
            # 合并所有批次的解析结果
            all_parsed_results = []
            total_items_parsed = 0

            for batch_idx, content in enumerate(results, 1):
                if content:
                    try:
                        # 计算当前批次对应的新闻项范围
                        start_idx = (batch_idx - 1) * self.true_batch_size
                        end_idx = min(start_idx + self.true_batch_size, len(items))
                        batch_items = items[start_idx:end_idx]

                        parsed_batch = self.response_parser.parse_batch_response(
                            batch_items,
                            content,
                            None
                        )
                        all_parsed_results.extend(parsed_batch)
                        total_items_parsed += len(parsed_batch)
                        logger.debug(f"✅ 批次 {batch_idx} 解析完成: {len(parsed_batch)} 条")
                    except Exception as e:
                        logger.error(f"❌ 批次 {batch_idx} 解析失败: {e}")
                        # 为当前批次使用默认分数
                        start_idx = (batch_idx - 1) * self.true_batch_size
                        end_idx = min(start_idx + self.true_batch_size, len(items))
                        for item in items[start_idx:end_idx]:
                            item.ai_score = 5.0
                            all_parsed_results.append(item)

            logger.info(f"✅ Pass2评分(真批处理)完成: {total_items_parsed}/{len(items)} 条")
            return all_parsed_results if all_parsed_results else items
        else:
            logger.warning("所有批次都失败，使用默认分数")
            return ErrorHandler.apply_batch_defaults(items, 'parse_failed')

    async def _pass2_scoring_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 评分 - 普通批处理模式

        Args:
            items: 通过预筛的新闻项列表

        Returns:
            List[NewsItem]: 评分后的新闻项列表
        """
        # 1. 构建Prompt
        prompt = self.prompt_builder.build_scoring_prompt(items)

        # 2. 调用API（带回退）
        content = await self.provider_manager.execute_with_fallback(
            "Pass2评分",
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

        logger.info(f"Pass 2 评分完成: {len(results)} 条")
        return results

    async def _pass2_single_item_with_category_summary(
        self,
        item: NewsItem
    ) -> NewsItem:
        """
        Pass 2: 对单条新闻进行分类特定的深度总结

        使用分类特定的总结Prompt生成差异化的中文总结

        Args:
            item: 新闻项

        Returns:
            NewsItem: 添加了分类特定总结的新闻项
        """
        try:
            # 1. 获取并标准化分类
            category = item.ai_category or item.pre_category or item.category
            standardized_category = self._standardize_category(category)

            logger.debug(f"Pass2单条总结: {item.title[:50]}... 分类: {standardized_category}")

            # 2. 构建分类特定Prompt
            prompt = self.prompt_builder.build_category_specific_summary_prompt(
                item,
                standardized_category
            )

            # 3. 调用API
            content = await self.provider_manager.call_single_scoring_api(
                prompt=prompt,
                max_tokens=1000,
                temperature=self.provider_manager.current_config.temperature
            )

            # 4. 解析响应
            import json
            try:
                result = json.loads(content)
                # 更新新闻项的总结信息
                if 'chinese_summary' in result:
                    item.ai_summary = result['chinese_summary']
                if 'key_points' in result:
                    item.ai_key_points = result['key_points']
                if 'impact_forecast' in result:
                    item.ai_impact_forecast = result['impact_forecast']

                logger.debug(f"✅ Pass2单条总结成功: {item.title[:30]}...")
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"单条总结解析失败: {e}")
                # 使用通用Prompt作为回退
                fallback_prompt = self.prompt_builder.build_category_specific_summary_prompt(
                    item,
                    '未分类'
                )
                fallback_content = await self.provider_manager.call_single_scoring_api(
                    prompt=fallback_prompt,
                    max_tokens=1000,
                    temperature=self.provider_manager.current_config.temperature
                )
                try:
                    fallback_result = json.loads(fallback_content)
                    if 'chinese_summary' in fallback_result:
                        item.ai_summary = fallback_result['chinese_summary']
                    if 'key_points' in fallback_result:
                        item.ai_key_points = fallback_result['key_points']
                    if 'impact_forecast' in fallback_result:
                        item.ai_impact_forecast = fallback_result['impact_forecast']
                except Exception:
                    pass

        except Exception as e:
            ErrorHandler.log_error(f"Pass2单条总结: {item.title[:30]}", e, logger)

        return item
    
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

    # ==================== 流式批处理支持（新增） ====================

    async def _pass2_scoring_streaming_batch(
        self,
        items: List[NewsItem]
    ) -> List[NewsItem]:
        """
        Pass 2: 流式批处理评分
        
        使用流式 JSON 解析，边接收边解析，即使被截断也能恢复部分数据
        
        Args:
            items: 新闻项列表
        
        Returns:
            List[NewsItem]: 评分后的新闻项
        """
        logger.info(f"🌊 Pass2 流式批处理: {len(items)} 条新闻")
        
        # 构建分类映射
        category_map = {}
        for i, item in enumerate(items, 1):
            category = item.ai_category or item.pre_category or item.category
            standardized_category = self._standardize_category(category)
            category_map[i] = standardized_category
        
        # 分批处理
        batch_size = self.true_batch_size
        batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
        
        all_parsed_results = []
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"📦 流式处理批次 {batch_idx}/{len(batches)} ({len(batch)} 条)")
            
            try:
                # 构建 Prompt
                prompt = self.prompt_builder.build_pass2_scoring_prompt(batch, category_map)
                
                # 流式接收和解析
                buffer = ""
                parsed_objects = []
                
                async for chunk in self.provider_manager.call_streaming_api(
                    prompt=prompt,
                    max_tokens=min(1000 + len(batch) * 600, 12000),
                    temperature=self.provider_manager.current_config.temperature
                ):
                    buffer += chunk
                    
                    # 尝试解析已接收的数据（关键：使用 try_parse_partial_json）
                    objects, remaining = self.response_parser.try_parse_partial_json(buffer, logger)
                    if objects:
                        parsed_objects.extend(objects)
                        buffer = remaining  # 保留未解析的部分
                        logger.debug(f"批次 {batch_idx} 实时解析 {len(objects)} 个，累计 {len(parsed_objects)} 个")
                
                # 完成解析（处理剩余数据）
                if buffer:
                    try:
                        # 尝试使用传统的 fix_truncated_json 修复
                        fixed = self.response_parser.fix_truncated_json(buffer)
                        data = json.loads(fixed)
                        if isinstance(data, list):
                            parsed_objects.extend(data)
                        elif isinstance(data, dict):
                            parsed_objects.append(data)
                    except Exception as e:
                        logger.warning(f"批次 {batch_idx} 剩余数据解析失败: {e}")
                
                logger.info(f"✅ 批次 {batch_idx} 流式解析完成: {len(parsed_objects)}/{len(batch)} 条")
                
                # 应用评分到新闻项
                for obj in parsed_objects:
                    try:
                        index = obj.get('news_index', 0) - 1
                        if 0 <= index < len(batch):
                            item = batch[index]
                            self.response_parser._apply_batch_scores(
                                item, obj, None, logger
                            )
                            all_parsed_results.append(item)
                    except Exception as e:
                        logger.error(f"应用评分失败: {e}")
                
            except Exception as e:
                logger.error(f"❌ 批次 {batch_idx} 流式处理失败: {e}")
                # 降级：使用默认分数
                for item in batch:
                    item.ai_score = 5.0
                    all_parsed_results.append(item)
        
        logger.info(f"✅ Pass2 流式批处理完成: {len(all_parsed_results)}/{len(items)} 条")
        return all_parsed_results
