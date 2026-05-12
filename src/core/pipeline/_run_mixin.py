# -*- coding: utf-8 -*-
"""``_RunMixin``: top-level run loop and per-stock orchestration."""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import as_completed
from typing import List, Optional

from src._concurrency import get_executor

from src.analyzer import AnalysisResult
from src.enums import ReportType

logger = logging.getLogger(__name__)


class _RunMixin:
    """Run-loop methods for :class:`StockAnalysisPipeline`."""

    def process_single_stock(
        self,
        code: str,
        skip_analysis: bool = False,
        single_stock_notify: bool = False,
        report_type: ReportType = ReportType.SIMPLE,
        analysis_query_id: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Optional[AnalysisResult]:
        """
        处理单只股票的完整流程

        包括：
        1. 获取数据
        2. 保存数据
        3. AI 分析
        4. 单股推送（可选，#55）

        此方法会被线程池调用，需要处理好异常

        Args:
            analysis_query_id: 查询链路关联 id
            code: 股票代码
            skip_analysis: 是否跳过 AI 分析
            single_stock_notify: 是否启用单股推送模式（每分析完一只立即推送）
            report_type: 报告类型枚举（从配置读取，Issue #119）
            force_refresh: Whether to force refresh data (bypass local cache)

        Returns:
            AnalysisResult 或 None
        """
        logger.info(f"========== 开始处理 {code} ==========")
        
        try:
            # Step 1: 获取并保存数据
            success, error = self.fetch_and_save_stock_data(code, force_refresh=force_refresh)
            
            if not success:
                logger.warning(f"[{code}] 数据获取失败: {error}")
                # 即使获取失败，也尝试用已有数据分析
            
            # Step 2: AI 分析
            if skip_analysis:
                logger.info(f"[{code}] 跳过 AI 分析（dry-run 模式）")
                return None
            
            effective_query_id = analysis_query_id or self.query_id or uuid.uuid4().hex
            result = self.analyze_stock(code, report_type, query_id=effective_query_id)
            
            if result:
                logger.info(
                    f"[{code}] 分析完成: {result.operation_advice}, "
                    f"评分 {result.sentiment_score}"
                )
                
                # 单股推送模式（#55）：每分析完一只股票立即推送
                if single_stock_notify and self.notifier.is_available():
                    try:
                        # 根据报告类型选择生成方法
                        if report_type == ReportType.FULL:
                            report_content = self.notifier.generate_dashboard_report([result])
                            logger.info(f"[{code}] 使用完整报告格式")
                        elif report_type == ReportType.BRIEF:
                            report_content = self.notifier.generate_brief_report([result])
                            logger.info(f"[{code}] 使用简洁报告格式")
                        else:
                            report_content = self.notifier.generate_single_stock_report(result)
                            logger.info(f"[{code}] 使用精简报告格式")
                        
                        if self.notifier.send(report_content, email_stock_codes=[code]):
                            logger.info(f"[{code}] 单股推送成功")
                        else:
                            logger.warning(f"[{code}] 单股推送失败")
                    except Exception as e:
                        logger.error(f"[{code}] 单股推送异常: {e}")
            
            return result
            
        except Exception as e:
            # 捕获所有异常，确保单股失败不影响整体
            logger.exception(f"[{code}] 处理过程发生未知异常: {e}")
            return None
    
    def run(
        self,
        stock_codes: Optional[List[str]] = None,
        dry_run: bool = False,
        send_notification: bool = True,
        merge_notification: bool = False
    ) -> List[AnalysisResult]:
        """
        运行完整的分析流程

        流程：
        1. 获取待分析的股票列表
        2. 使用线程池并发处理
        3. 收集分析结果
        4. 发送通知

        Args:
            stock_codes: 股票代码列表（可选，默认使用配置中的自选股）
            dry_run: 是否仅获取数据不分析
            send_notification: 是否发送推送通知
            merge_notification: 是否合并推送（跳过本次推送，由 main 层合并个股+大盘后统一发送，Issue #190）

        Returns:
            分析结果列表
        """
        start_time = time.time()
        
        # 使用配置中的股票列表
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        
        if not stock_codes:
            logger.error("未配置自选股列表，请在 .env 文件中设置 STOCK_LIST")
            return []
        
        logger.info(f"===== 开始分析 {len(stock_codes)} 只股票 =====")
        logger.info(f"股票列表: {', '.join(stock_codes)}")
        logger.info(f"并发数: {self.max_workers}, 模式: {'仅获取数据' if dry_run else '完整分析'}")
        
        # === 批量预取实时行情（优化：避免每只股票都触发全量拉取）===
        # 只有股票数量 >= 5 时才进行预取，少量股票直接逐个查询更高效
        if len(stock_codes) >= 5:
            prefetch_count = self.fetcher_manager.prefetch_realtime_quotes(stock_codes)
            if prefetch_count > 0:
                logger.info(f"已启用批量预取架构：一次拉取全市场数据，{len(stock_codes)} 只股票共享缓存")

        # Issue #455: 预取股票名称，避免并发分析时显示「股票xxxxx」
        # dry_run 仅做数据拉取，不需要名称预取，避免额外网络开销
        if not dry_run:
            self.fetcher_manager.prefetch_stock_names(stock_codes, use_bulk=False)

        # 单股推送模式（#55）：从配置读取
        single_stock_notify = getattr(self.config, 'single_stock_notify', False)
        # Issue #119: 从配置读取报告类型
        report_type_str = getattr(self.config, 'report_type', 'simple').lower()
        if report_type_str == 'brief':
            report_type = ReportType.BRIEF
        elif report_type_str == 'full':
            report_type = ReportType.FULL
        else:
            report_type = ReportType.SIMPLE
        # Issue #128: 从配置读取分析间隔
        analysis_delay = getattr(self.config, 'analysis_delay', 0)

        if single_stock_notify:
            logger.info(f"已启用单股推送模式：每分析完一只股票立即推送（报告类型: {report_type_str}）")
        
        results: List[AnalysisResult] = []
        
        executor = get_executor(self.max_workers, "pipeline")
        future_to_code = {
            executor.submit(
                self.process_single_stock,
                code,
                skip_analysis=dry_run,
                single_stock_notify=single_stock_notify and send_notification,
                report_type=report_type,  # Issue #119: 传递报告类型
                analysis_query_id=uuid.uuid4().hex,
            ): code
            for code in stock_codes
        }
        
        for idx, future in enumerate(as_completed(future_to_code)):
            code = future_to_code[future]
            try:
                result = future.result()
                if result:
                    results.append(result)

                # Issue #128: 分析间隔 - 在个股分析和大盘分析之间添加延迟
                if idx < len(stock_codes) - 1 and analysis_delay > 0:
                    # 注意：此 sleep 发生在“主线程收集 future 的循环”中，
                    # 并不会阻止线程池中的任务同时发起网络请求。
                    # 因此它对降低并发请求峰值的效果有限；真正的峰值主要由 max_workers 决定。
                    # 该行为目前保留（按需求不改逻辑）。
                    logger.debug(f"等待 {analysis_delay} 秒后继续下一只股票...")
                    time.sleep(analysis_delay)

            except Exception as e:
                logger.error(f"[{code}] 任务执行失败: {e}")
        
        # 统计
        elapsed_time = time.time() - start_time
        
        # dry-run 模式下，数据获取成功即视为成功
        if dry_run:
            # 检查哪些股票的数据今天已存在
            success_count = sum(1 for code in stock_codes if self.db.has_today_data(code))
            fail_count = len(stock_codes) - success_count
        else:
            success_count = len(results)
            fail_count = len(stock_codes) - success_count
        
        logger.info("===== 分析完成 =====")
        logger.info(f"成功: {success_count}, 失败: {fail_count}, 耗时: {elapsed_time:.2f} 秒")
        
        # 发送通知（单股推送模式下跳过汇总推送，避免重复）
        if results and send_notification and not dry_run:
            if single_stock_notify:
                # 单股推送模式：只保存汇总报告，不再重复推送
                logger.info("单股推送模式：跳过汇总推送，仅保存报告到本地")
                self._send_notifications(results, report_type, skip_push=True)
            elif merge_notification:
                # 合并模式（Issue #190）：仅保存，不推送，由 main 层合并个股+大盘后统一发送
                logger.info("合并推送模式：跳过本次推送，将在个股+大盘复盘后统一发送")
                self._send_notifications(results, report_type, skip_push=True)
            else:
                self._send_notifications(results, report_type)
        
        return results
    
