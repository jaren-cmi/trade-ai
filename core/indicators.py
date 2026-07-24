#!/usr/bin/env python3
"""
技术指标计算模块 - A股专版
使用 ta 库计算常用技术指标

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    为DataFrame添加所有常用技术指标

    Args:
        df: 需包含列 ['open', 'high', 'low', 'close', 'volume']（或中文列名）

    Returns:
        添加了技术指标的DataFrame
    """
    try:
        import ta
    except ImportError:
        logger.warning("ta 库未安装，跳过技术指标计算")
        return df

    df = df.copy()

    close_col = next((c for c in ['close', 'Close', '收盘'] if c in df.columns), None)
    high_col = next((c for c in ['high', 'High', '最高'] if c in df.columns), None)
    low_col = next((c for c in ['low', 'Low', '最低'] if c in df.columns), None)
    vol_col = next((c for c in ['volume', 'Volume', '成交量'] if c in df.columns), None)

    if close_col is None:
        return df

    close = df[close_col]

    df['ma5'] = ta.trend.sma_indicator(close, window=5)
    df['ma10'] = ta.trend.sma_indicator(close, window=10)
    df['ma20'] = ta.trend.sma_indicator(close, window=20)
    df['ma60'] = ta.trend.sma_indicator(close, window=60)
    df['ema12'] = ta.trend.ema_indicator(close, window=12)
    df['ema26'] = ta.trend.ema_indicator(close, window=26)
    df['rsi_14'] = ta.momentum.rsi(close, window=14)

    macd = ta.trend.MACD(close)
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()

    if high_col and low_col:
        high = df[high_col]
        low = df[low_col]
        stoch = ta.momentum.StochasticOscillator(high, low, close)
        df['k'] = stoch.stoch()
        df['d'] = stoch.stoch_signal()
        df['j'] = 3 * df['k'] - 2 * df['d']

        bollinger = ta.volatility.BollingerBands(close)
        df['bb_upper'] = bollinger.bollinger_hband()
        df['bb_middle'] = bollinger.bollinger_mband()
        df['bb_lower'] = bollinger.bollinger_lband()

        df['atr_14'] = ta.volatility.average_true_range(high, low, close, window=14)

    if vol_col:
        volume = df[vol_col]
        df['obv'] = ta.volume.on_balance_volume(close, volume)

    df['returns'] = close.pct_change()
    df['returns_5d'] = close.pct_change(5)

    return df


def calculate_momentum(df: pd.DataFrame, windows: list = None) -> Dict[str, float]:
    """计算动量指标（多周期涨幅）"""
    if windows is None:
        windows = [5, 10, 20]

    close_col = next((c for c in ['close', 'Close', '收盘'] if c in df.columns), None)
    if close_col is None:
        return {}

    close = df[close_col]
    momentum = {}
    for w in windows:
        if len(close) > w:
            ret = (close.iloc[-1] / close.iloc[-w - 1] - 1) * 100
            momentum[f'momentum_{w}d'] = round(ret, 2)
        else:
            momentum[f'momentum_{w}d'] = 0
    return momentum


def check_ma_alignment(df: pd.DataFrame) -> Dict[str, Any]:
    """检查均线多头排列状态"""
    close_col = next((c for c in ['close', 'Close', '收盘'] if c in df.columns), None)
    if close_col is None or len(df) < 60:
        return {"is_bullish": False, "alignment": "数据不足", "strength": 0}

    close = df[close_col]
    ma5 = df['ma5'].iloc[-1] if 'ma5' in df.columns else close.rolling(5).mean().iloc[-1]
    ma20 = df['ma20'].iloc[-1] if 'ma20' in df.columns else close.rolling(20).mean().iloc[-1]
    ma60 = df['ma60'].iloc[-1] if 'ma60' in df.columns else close.rolling(60).mean().iloc[-1]

    latest = close.iloc[-1]
    bullish = (latest > ma5) and (ma5 > ma20) and (ma20 > ma60)
    bearish = (latest < ma5) and (ma5 < ma20) and (ma20 < ma60)

    if bullish:
        alignment = "多头排列"
        strength = min(100, (latest / ma60 - 1) * 100 * 2)
    elif bearish:
        alignment = "空头排列"
        strength = min(100, (ma60 / latest - 1) * 100 * 2)
    else:
        alignment = "混乱"
        strength = 50

    return {"is_bullish": bullish, "alignment": alignment, "strength": round(strength, 1)}


# 兼容旧名称
calculate_technical_indicators = add_all_indicators
