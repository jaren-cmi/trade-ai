#!/usr/bin/env python3
"""
回测引擎存根 - 暂为简化版，不影响核心选股流程

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BacktestEngine:
    """A股回测引擎（简化版存根，不影响选股主流程）"""

    def __init__(self, initial_capital: float = 1000000, **kwargs):
        self.initial_capital = initial_capital

    def run(self, signals: pd.DataFrame, price_data: Optional[pd.DataFrame] = None,
            benchmark_code: str = "000300") -> Dict[str, Any]:
        logger.info("回测引擎：当前版本为简化版，跳过实际回测")
        return {
            "策略名称": "未知",
            "初始资金": self.initial_capital,
            "最终价值": self.initial_capital,
            "总收益率": 0.0,
            "年化收益率": 0.0,
            "夏普比率": 0.0,
            "最大回撤": 0.0,
            "交易次数": 0,
            "胜率": 0.0,
        }


def quick_backtest(strategy, data: pd.DataFrame,
                   initial_capital: float = 1000000) -> Dict[str, Any]:
    """快速回测（简化版）"""
    engine = BacktestEngine(initial_capital=initial_capital)
    return engine.run(data)
