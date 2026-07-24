#!/usr/bin/env python3
"""
主引擎 - 选股系统核心
整合数据获取、策略评分、报告生成全流程

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
import logging
import random
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from .data_fetcher import DataFetcher, get_index_components
from .strategies import get_strategy, BaseStrategy, STRATEGY_REGISTRY
from .cache_manager import CacheManager
from output.reporter import MarkdownReporter
from output.excel_writer import ExcelWriter
from output.qq_notifier import QQNotifier

logger = logging.getLogger(__name__)


class StockPickerEngine:
    """
    选股引擎 - 核心协调器

    使用示例：
    ```python
    engine = StockPickerEngine()
    result = engine.run(
        pool="all",
        strategy_name="multi_factor",
        sample_size=200,
        use_cache=True,
        send_qq=False,
    )
    selected = result['selected']
    excel_path = result['excel_path']
    ```
    """

    def __init__(self,
                 config_path: str = "config/",
                 cache_dir: str = "data/cache",
                 reports_dir: str = "reports/daily"):
        logger.info("初始化选股引擎...")
        self.fetcher = DataFetcher(config_path)
        self.cache = CacheManager(cache_dir)
        self.reporter = MarkdownReporter()
        self.excel_writer = ExcelWriter(reports_dir)
        self.qq_notifier = QQNotifier()
        self.strategies = STRATEGY_REGISTRY
        logger.info("✅ 引擎初始化完成")

    def run(self,
            pool: str = "all",
            strategy_name: str = "multi_factor",
            strategy_params: Optional[Dict] = None,
            use_cache: bool = True,
            run_backtest: bool = False,
            send_qq: bool = False,
            top_n: int = 30,
            sample_size: Optional[int] = None,
            progress_callback: Optional[Callable[[str], None]] = None,
            stop_event: Optional[threading.Event] = None,
            ) -> Dict[str, Any]:
        """
        执行完整选股流程

        Args:
            pool: 股票池 ("all", "hs300", "zz500", "zz1000")
            strategy_name: 策略名称
            strategy_params: 策略参数（覆盖默认）
            use_cache: 是否使用缓存
            run_backtest: 是否运行回测
            send_qq: 是否QQ推送
            top_n: 最终推荐数量
            sample_size: 采样大小（None=全市场，int=采样N只）
            progress_callback: 进度回调 fn(message: str)
            stop_event: 停止信号 Event，设置后提前中断数据获取

        Returns:
            结果字典（包含 selected, report_md, excel_path, stats）
        """

        def _notify(msg: str):
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        start_time = datetime.now()
        _notify(f"🚀 开始运行 | 池: {pool} | 策略: {strategy_name}")

        # ========== Step 1: 获取股票池 ==========
        _notify("【Step 1/6】获取股票列表...")
        if use_cache:
            stock_list_df = self.cache.get_stock_list_cache()
            if stock_list_df is None:
                stock_list_df = self.fetcher.get_stock_basic()
                self.cache.set_stock_list_cache(stock_list_df)
        else:
            stock_list_df = self.fetcher.get_stock_basic()

        if stock_list_df.empty:
            raise ValueError("无法获取股票列表")

        stock_codes = self._filter_stock_pool(stock_list_df, pool)
        _notify(f"股票池: {len(stock_codes)} 只")

        if sample_size and sample_size < len(stock_codes):
            random.seed(42)
            stock_codes = random.sample(stock_codes, sample_size)
            _notify(f"采样模式: {len(stock_codes)} 只")

        # ========== Step 2: 批量获取数据 ==========
        _notify(f"【Step 2/6】批量获取数据（多线程，共 {len(stock_codes)} 只）...")

        # 从配置读取并发参数（data_sources.yaml → baostock）
        bs_cfg = self.fetcher.config.get('baostock', {})
        max_workers = int(bs_cfg.get('max_workers', 3))
        max_retries = int(bs_cfg.get('max_retries', 2))
        rate_limit_sleep = float(bs_cfg.get('rate_limit_sleep', 0.1))

        fetch_progress = [0]

        def _fetch_progress_cb(completed: int, total: int):
            pct = int(completed / total * 100)
            if pct != fetch_progress[0] and pct % 20 == 0:
                fetch_progress[0] = pct
                _notify(f"  数据获取进度: {pct}% ({completed}/{total})")

        data_df = self.fetcher.fetch_batch(
            stock_codes,
            fields=['basic', 'valuation', 'financials'],
            use_cache=use_cache,
            max_workers=max_workers,
            progress_callback=_fetch_progress_cb,
            stop_event=stop_event,
            max_retries=max_retries,
            rate_limit_sleep=rate_limit_sleep,
        )

        # 检查是否被用户停止
        if stop_event is not None and stop_event.is_set():
            _notify("⏹ 运行已停止")
            return {"error": "运行已停止", "selected": pd.DataFrame(),
                    "stats": {"selected": 0, "total_stocks": len(stock_codes),
                               "data_fetched": len(data_df)}}

        success_count = len(data_df)
        skipped_count = len(stock_codes) - success_count
        _notify(
            f"数据获取完成: 成功 {success_count} 只"
            + (f"（失败/过滤 {skipped_count} 只，已跳过）" if skipped_count > 0 else "")
        )

        if data_df.empty:
            return {
                "error": (
                    "无法获取任何股票数据。可能原因：\n"
                    "① Baostock 网络不稳定 — 稍后重试\n"
                    "② VPN 影响国内数据连接 — 尝试关闭 VPN\n"
                    "③ 采样量过大 — 调小采样数量后重试"
                ),
                "selected": pd.DataFrame(),
                "stats": {"selected": 0, "total_stocks": len(stock_codes), "data_fetched": 0},
            }

        # ========== Step 3: 策略评分 ==========
        _notify("【Step 3/6】应用策略评分...")
        strategy = self._get_strategy(strategy_name, strategy_params)
        scored_df = strategy.generate_signals(data_df)

        # ========== Step 4: 筛选 ==========
        _notify("【Step 4/6】筛选推荐股票...")
        selected = strategy.select_stocks(scored_df, top_n=top_n)
        _notify(f"筛选结果: {len(selected)} 只推荐")

        if selected.empty:
            return {
                "selected": pd.DataFrame(),
                "stats": {"selected": 0, "total_stocks": len(stock_codes),
                          "data_fetched": len(data_df)},
                "report_md": "未筛选出符合条件的股票。",
                "excel_path": None,
            }

        # ========== Step 5: 生成报告 ==========
        _notify("【Step 5/6】生成报告...")
        timestamp = datetime.now()
        stats = {
            "total_stocks": len(stock_codes),
            "data_fetched": len(data_df),
            "selected": len(selected),
            "selection_ratio": len(selected) / len(data_df) * 100 if len(data_df) > 0 else 0,
        }

        report_md = self.reporter.generate(
            selected_stocks=selected,
            pool=self._pool_name(pool),
            strategy=strategy.name,
            stats=stats,
            timestamp=timestamp
        )

        # ========== Step 6: 导出Excel ==========
        _notify("【Step 6/6】导出Excel报告...")
        excel_path = self.excel_writer.write_stock_pool(
            selected_stocks=selected,
            pool=self._pool_name(pool),
            strategy=strategy.name,
            timestamp=timestamp
        )

        # QQ推送（可选）
        if send_qq:
            try:
                self.qq_notifier.send(report_md, excel_path, stats)
            except Exception as e:
                logger.warning(f"QQ推送失败: {e}")

        elapsed = (datetime.now() - start_time).total_seconds()
        _notify(f"✅ 运行完成 | 耗时: {elapsed:.1f}秒 | 推荐: {len(selected)} 只")

        return {
            "selected": selected,
            "report_md": report_md,
            "excel_path": excel_path,
            "stats": stats,
            "elapsed_seconds": elapsed,
            "timestamp": timestamp,
        }

    def _filter_stock_pool(self, stock_df: pd.DataFrame, pool: str) -> List[str]:
        """根据股票池筛选代码列表，返回 Baostock 格式代码"""
        if pool == "all":
            df = stock_df.copy()
            df = df[df['code'].str.startswith(('sh.', 'sz.'))]
            df = df[~df['code_name'].str.contains('ST|退市', na=False)]
            return df['code'].tolist()
        else:
            return self.fetcher.get_index_components(pool)

    def _pool_name(self, pool: str) -> str:
        names = {"all": "全A股", "hs300": "沪深300", "zz500": "中证500", "zz1000": "中证1000"}
        return names.get(pool, pool)

    def _get_strategy(self, name: str, params: Optional[Dict]) -> BaseStrategy:
        if params:
            return get_strategy(name, **params)
        return get_strategy(name)


# ============== 便捷函数 ==============

def run_quick_scan(pool: str = "all", sample_size: int = 200,
                   strategy: str = "multi_factor") -> Dict[str, Any]:
    """快速扫描（采样版）：耗时约20-30秒"""
    engine = StockPickerEngine()
    return engine.run(pool=pool, strategy_name=strategy,
                      sample_size=sample_size, use_cache=True)


def run_full_scan(pool: str = "all",
                  strategy: str = "multi_factor") -> Dict[str, Any]:
    """全市场扫描：耗时约15-20分钟"""
    engine = StockPickerEngine()
    return engine.run(pool=pool, strategy_name=strategy, use_cache=False, top_n=50)
