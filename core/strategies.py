#!/usr/bin/env python3
"""
策略库 - A股智能选股
包含：多因子策略、PE价值策略、三维评分策略

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import logging

from .scorer import calculate_comprehensive_score, score_fundamental

logger = logging.getLogger(__name__)


# ============== 策略基类 ==============

class BaseStrategy(ABC):
    """策略基类 - 所有策略必须继承此类"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """生成交易信号并计算评分"""
        pass

    @abstractmethod
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算策略所需指标"""
        pass

    def select_stocks(self, data: pd.DataFrame, top_n: int = 30) -> pd.DataFrame:
        """筛选股票（通用方法）"""
        score_col = next(
            (c for c in ['总分', 'total_score'] if c in data.columns), None
        )
        if score_col:
            return data[data['signal'] == 1].sort_values(score_col, ascending=False).head(top_n)
        return data[data['signal'] == 1].head(top_n) if 'signal' in data.columns else data.head(top_n)


# ============== 多因子策略 ==============

class MultiFactorStrategy(BaseStrategy):
    """
    A股多因子模型策略
    因子权重：估值40% + 盈利30% + 规模30%
    """

    def __init__(self,
                 min_score: float = 60,
                 min_market_cap: float = 50,
                 max_pe: float = 100):
        super().__init__(
            name="多因子策略",
            description="综合估值40% + 盈利30% + 规模30% 筛选"
        )
        self.min_score = min_score
        self.min_market_cap = min_market_cap
        self.max_pe = max_pe

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        pe_col = 'PE'
        roe_col = 'ROE'
        growth_col = '营收增长率'

        # 估值因子（PE倒数，越小越好）；缺失PE时用中位数兜底，避免全表失效
        if pe_col in df.columns:
            pe_series = pd.to_numeric(df[pe_col], errors='coerce')
            valid_pe = pe_series.where(pe_series > 0)
            pe_fallback = valid_pe.median() if valid_pe.notna().any() else 30.0
            pe_for_score = pe_series.where(pe_series > 0, pe_fallback).fillna(pe_fallback)
            df['pe_score'] = 1.0 / pe_for_score.clip(lower=0.1)
        else:
            df['pe_score'] = pd.Series(0.0, index=df.index)

        # 盈利因子
        df['roe_score'] = pd.to_numeric(df.get(roe_col, 0), errors='coerce').fillna(0)

        # 成长因子
        df['growth_score'] = pd.to_numeric(df.get(growth_col, 0), errors='coerce').fillna(0)

        return df

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = self.calculate_indicators(data)

        # 归一化（去极值）
        for col in ['pe_score', 'roe_score', 'growth_score']:
            if col in df.columns:
                min_val = df[col].quantile(0.05)
                max_val = df[col].quantile(0.95)
                denom = max_val - min_val + 1e-8
                df[f'{col}_norm'] = ((df[col] - min_val) / denom * 100).clip(0, 100)

        # 加权综合得分（估值40% + 盈利30% + 规模30%）
        df['total_score'] = (
            df.get('pe_score_norm', pd.Series(0, index=df.index)) * 0.40 +
            df.get('roe_score_norm', pd.Series(0, index=df.index)) * 0.30 +
            df.get('growth_score_norm', pd.Series(0, index=df.index)) * 0.30
        )

        # 统一评分列名
        df['总分'] = df['total_score'].round(1)

        # 评级
        df['评级'] = df['总分'].apply(_get_rating)

        # 筛选条件
        pe_col = 'PE'
        cond_score = df['总分'] >= self.min_score
        if pe_col in df.columns:
            pe_series = pd.to_numeric(df[pe_col], errors='coerce')
            cond_pe = pe_series.isna() | ((pe_series > 0) & (pe_series < self.max_pe))
        else:
            cond_pe = True
        cond_no_st = ~df['名称'].str.contains('ST|退市', na=False) if '名称' in df.columns else True

        df['signal'] = 0
        df.loc[cond_score & cond_pe & cond_no_st, 'signal'] = 1

        buy_count = (df['signal'] == 1).sum()
        logger.info(f"✅ 多因子策略筛选出 {buy_count} 只股票")
        return df


# ============== PE价值策略 ==============

class PEStrategy(BaseStrategy):
    """低PE选股策略"""

    def __init__(self,
                 pe_threshold: float = 20,
                 roe_threshold: float = 15,
                 revenue_growth: float = 5,
                 min_market_cap: float = 10):
        super().__init__(
            name="低PE价值策略",
            description=f"PE<{pe_threshold} + ROE>{roe_threshold}% + 营收增长>{revenue_growth}%"
        )
        self.pe_threshold = pe_threshold
        self.roe_threshold = roe_threshold
        self.revenue_growth = revenue_growth
        self.min_market_cap = min_market_cap

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.copy()

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = self.calculate_indicators(data)

        pe_col = 'PE'
        roe_col = 'ROE'
        growth_col = '营收增长率'

        if pe_col in df.columns:
            pe_series = pd.to_numeric(df[pe_col], errors='coerce')
            cond_pe = pe_series.isna() | ((pe_series < self.pe_threshold) & (pe_series > 0))
        else:
            cond_pe = True
        cond_roe = df[roe_col] > self.roe_threshold if roe_col in df.columns else True
        cond_growth = df[growth_col] > self.revenue_growth if growth_col in df.columns else True
        cond_no_st = ~df['名称'].str.contains('ST|退市', na=False) if '名称' in df.columns else True

        df['signal'] = 0
        df.loc[cond_pe & cond_roe & cond_growth & cond_no_st, 'signal'] = 1

        # 计算 PE价值得分（PE越低得分越高）
        if pe_col in df.columns and roe_col in df.columns:
            pe_series = pd.to_numeric(df[pe_col], errors='coerce')
            roe_norm = pd.to_numeric(df[roe_col], errors='coerce')
            pe_valid = pe_series.where(pe_series > 0)

            if pe_valid.notna().any():
                pe_fill = pe_valid.median()
                pe_norm = (1 / pe_series.where(pe_series > 0, pe_fill).fillna(pe_fill).clip(lower=0.1))
                pe_min, pe_max = pe_norm.quantile(0.05), pe_norm.quantile(0.95)
                pe_score = ((pe_norm - pe_min) / (pe_max - pe_min + 1e-8) * 100).clip(0, 100)
            else:
                pe_score = pd.Series(50.0, index=df.index)

            if roe_norm.notna().any():
                roe_fill = roe_norm.median()
                roe_norm = roe_norm.fillna(roe_fill)
                roe_min, roe_max = roe_norm.quantile(0.05), roe_norm.quantile(0.95)
                roe_score = ((roe_norm - roe_min) / (roe_max - roe_min + 1e-8) * 100).clip(0, 100)
            else:
                roe_score = pd.Series(50.0, index=df.index)

            df['总分'] = (pe_score * 0.6 + roe_score * 0.4).round(1)
        else:
            df['总分'] = 60.0

        df['评级'] = df['总分'].apply(_get_rating)

        buy_count = (df['signal'] == 1).sum()
        logger.info(f"✅ PE策略筛选出 {buy_count} 只股票")
        return df


# ============== 三维评分策略 ==============

class ThreeDimensionalStrategy(BaseStrategy):
    """三维评分策略：基本面 + 技术面 + 情绪面"""

    def __init__(self, strategy_mode: str = "moderate"):
        super().__init__(
            name="三维评分策略",
            description="基本面40% + 技术面35% + 情绪面25%"
        )
        self.strategy_mode = strategy_mode

    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        return data.copy()

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        df = self.calculate_indicators(data)

        scores = []
        for _, row in df.iterrows():
            financials = {
                'pe_ratio': row.get('PE'),
                'roe': row.get('ROE'),
                'revenue_growth': row.get('营收增长率'),
                'profit_growth': row.get('净利润增长率'),
            }
            score_result = calculate_comprehensive_score(
                financials=financials,
                price_data=None,
                sentiment_data={},
                strategy=self.strategy_mode
            )
            scores.append(score_result)

        score_df = pd.DataFrame(scores)
        df = pd.concat([df.reset_index(drop=True), score_df], axis=1)

        cond_score = df['总分'] >= 50  # 三维策略无技术/情绪数据时基准适当放宽
        if 'PE' in df.columns:
            pe_series = pd.to_numeric(df['PE'], errors='coerce')
            cond_pe = pe_series.isna() | (pe_series > 0)
        else:
            cond_pe = True
        cond_no_st = ~df['名称'].str.contains('ST|退市', na=False) if '名称' in df.columns else True

        df['signal'] = 0
        df.loc[cond_score & cond_pe & cond_no_st, 'signal'] = 1

        buy_count = (df['signal'] == 1).sum()
        logger.info(f"✅ 三维评分策略筛选出 {buy_count} 只股票")
        return df


# ============== 工具函数 ==============

def _get_rating(score: float) -> str:
    if score >= 75:
        return "🟢 强烈推荐"
    elif score >= 60:
        return "🟢 推荐"
    elif score >= 45:
        return "🟡 观望"
    else:
        return "🔴 回避"


# ============== 策略工厂 ==============

STRATEGY_REGISTRY = {
    "multi_factor": MultiFactorStrategy,
    "pe_value": PEStrategy,
    "three_dimensional": ThreeDimensionalStrategy,
}


def get_strategy(name: str, **kwargs) -> BaseStrategy:
    """获取策略实例"""
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"未知策略: {name}。可选: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[name](**kwargs)


def list_strategies() -> Dict[str, str]:
    """列出所有可用策略"""
    return {
        name: cls().description
        for name, cls in STRATEGY_REGISTRY.items()
    }
