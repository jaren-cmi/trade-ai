#!/usr/bin/env python3
"""
综合评分算法 - A股专版（三维评分：基本面+技术面+情绪面）

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

# 评分权重配置
SCORING_WEIGHTS = {
    "fundamental": 0.40,
    "technical": 0.35,
    "sentiment": 0.25,
}

STRATEGY_PARAMS = {
    "strict": {
        "pe_range": (0, 30),
        "roe_min": 12,
        "revenue_growth_min": 10,
        "profit_growth_min": 5,
    },
    "moderate": {
        "pe_range": (0, 50),
        "roe_min": 8,
        "revenue_growth_min": 5,
        "profit_growth_min": 0,
    },
    "loose": {
        "pe_range": (-50, 100),
        "roe_min": 3,
        "revenue_growth_min": 0,
        "profit_growth_min": -10,
    },
}


def normalize_score(value: float, min_val: float, max_val: float) -> float:
    """将数值归一化到 0~1"""
    if max_val == min_val:
        return 0.5
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def score_fundamental(financials: Optional[Dict[str, Any]], strategy: str = "moderate") -> float:
    """基本面评分（0~100）：指标包括 PE、ROE、营收增长率、净利润增长率"""
    if not financials:
        return 30.0

    params = STRATEGY_PARAMS[strategy]
    pe_min, pe_max = params["pe_range"]
    roe_min = params["roe_min"]
    rev_min = params["revenue_growth_min"]
    profit_min = params["profit_growth_min"]

    score = 0.0

    pe = financials.get("pe_ratio") or financials.get("PE")
    if pe is not None and not np.isnan(float(pe)):
        pe = float(pe)
        if pe_min <= pe <= pe_max:
            score += 25 * (1 - (pe - pe_min) / (pe_max - pe_min + 1e-8))
        elif pe < 0:
            if (financials.get("revenue_growth") or 0) > 0.2:
                score += 15
            else:
                score += 5

    roe = financials.get("roe") or financials.get("ROE")
    if roe is not None and not np.isnan(float(roe)):
        score += 25 * normalize_score(float(roe), roe_min, 40)

    rev_growth = financials.get("revenue_growth") or financials.get("营收增长率")
    if rev_growth is not None and not np.isnan(float(rev_growth)):
        score += 25 * normalize_score(float(rev_growth), rev_min, 50)

    profit_growth = financials.get("profit_growth") or financials.get("净利润增长率")
    if profit_growth is not None and not np.isnan(float(profit_growth)):
        score += 25 * normalize_score(float(profit_growth), profit_min, 100)

    return min(100.0, max(0.0, score))


def score_technical(price_data: Optional[pd.DataFrame], strategy: str = "moderate") -> float:
    """技术面评分（0~100）：均线多头、MACD金叉、成交量放大
    
    当无价格数据时返回 50.0 作为中性分——即 0~100 范围的中点，
    既不奖励也不惩罚，使基本面与情绪面的权重正常发挥作用。
    """
    if price_data is None or price_data.empty or len(price_data) < 20:
        return 50.0  # 0~100 的中点，表示技术面信号中性

    try:
        close_col = next((c for c in ['close', 'Close', '收盘'] if c in price_data.columns), None)
        vol_col = next((c for c in ['volume', 'Volume', '成交量'] if c in price_data.columns), None)

        if close_col is None:
            return 30.0

        close = price_data[close_col]
        ma20 = close.rolling(window=20).mean()
        score = 0.0
        latest = close.iloc[-1]

        if len(close) >= 60:
            ma60 = close.rolling(window=60).mean()
            if latest > ma20.iloc[-1] > ma60.iloc[-1]:
                score += 35
                score += min(15, (latest / ma60.iloc[-1] - 1) * 10)
            elif latest > ma20.iloc[-1]:
                score += 15
        elif latest > ma20.iloc[-1]:
            score += 20

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        if len(macd) >= 2:
            if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
                score += 25
            elif macd.iloc[-1] > signal.iloc[-1]:
                score += 15

        if vol_col:
            avg_vol = price_data[vol_col].rolling(20).mean()
            current_vol = price_data[vol_col].iloc[-1]
            if avg_vol.iloc[-1] > 0 and current_vol > avg_vol.iloc[-1] * 1.2:
                score += 25
            elif avg_vol.iloc[-1] > 0 and current_vol > avg_vol.iloc[-1]:
                score += 15
            else:
                score += 5

        return min(100.0, max(0.0, score))
    except Exception:
        return 30.0


def score_sentiment(sentiment_data: Dict[str, Any]) -> float:
    """情绪面评分（0~100）：基于 Tavily 新闻情绪分析"""
    if not sentiment_data or "error" in sentiment_data:
        return 50.0

    base_score = sentiment_data.get("score", 0.5) * 100
    news_count = sentiment_data.get("news_count", 0)
    count_bonus = min(10, news_count * 2)

    return min(100.0, max(0.0, base_score + count_bonus))


def calculate_comprehensive_score(
    financials: Optional[Dict[str, Any]],
    price_data: Optional[pd.DataFrame],
    sentiment_data: Dict[str, Any],
    strategy: str = "moderate"
) -> Dict[str, Any]:
    """
    计算综合评分（三维加权）

    Returns:
        {'总分': 75.5, '基本面': 80.0, '技术面': 70.0, '情绪面': 60.0, '评级': '🟢 推荐'}
    """
    fund_score = score_fundamental(financials, strategy)
    tech_score = score_technical(price_data, strategy)
    sent_score = score_sentiment(sentiment_data)

    total = (
        fund_score * SCORING_WEIGHTS["fundamental"] +
        tech_score * SCORING_WEIGHTS["technical"] +
        sent_score * SCORING_WEIGHTS["sentiment"]
    )

    if total >= 75:
        rating = "🟢 强烈推荐"
    elif total >= 60:
        rating = "🟢 推荐"
    elif total >= 45:
        rating = "🟡 观望"
    else:
        rating = "🔴 回避"

    return {
        "总分": round(total, 1),
        "基本面": round(fund_score, 1),
        "技术面": round(tech_score, 1),
        "情绪面": round(sent_score, 1),
        "评级": rating,
    }
