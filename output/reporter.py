#!/usr/bin/env python3
"""
Markdown报告生成器

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """Markdown报告生成器"""

    def generate(self,
                 selected_stocks: pd.DataFrame,
                 pool: str,
                 strategy: str,
                 backtest_result: Optional[Dict[str, Any]] = None,
                 stats: Optional[Dict[str, Any]] = None,
                 timestamp: Optional[datetime] = None) -> str:
        if timestamp is None:
            timestamp = datetime.now()

        report = self._header(pool, strategy, timestamp, stats)
        report += self._summary(selected_stocks)
        report += self._top20_table(selected_stocks)
        report += self._disclaimer(timestamp)
        return report

    def _header(self, pool: str, strategy: str, timestamp: datetime,
                stats: Optional[Dict]) -> str:
        header = f"""# 📈 A股智能选股报告

**生成时间**: {timestamp.strftime('%Y-%m-%d %H:%M')}
**股票池**: {pool}
**策略**: {strategy}
"""
        if stats:
            header += f"""
**统计信息**:
- 扫描股票数: {stats.get('total_stocks', '-')} 只
- 有效数据: {stats.get('data_fetched', '-')} 只
- 筛选结果: {stats.get('selected', '-')} 只
- 筛选比例: {stats.get('selection_ratio', 0):.1f}%

---

"""
        return header

    def _summary(self, selected_stocks: pd.DataFrame) -> str:
        if selected_stocks.empty:
            return "## ⚠️ 未找到符合条件的股票\n"

        score_col = next((c for c in ['总分', 'total_score'] if c in selected_stocks.columns), None)
        pe_col = 'PE' if 'PE' in selected_stocks.columns else None

        avg_pe = f"{selected_stocks[pe_col].mean():.1f}" if pe_col else '-'
        avg_score = f"{selected_stocks[score_col].mean():.1f}" if score_col else '-'
        max_score = f"{selected_stocks[score_col].max():.1f}" if score_col else '-'

        return f"""## 📊 筛选结果摘要

| 指标 | 数值 |
|------|------|
| 推荐股票数 | {len(selected_stocks)} 只 |
| 平均PE | {avg_pe} |
| 平均综合分 | {avg_score} 分 |
| 最高分 | {max_score} 分 |

---

"""

    def _top20_table(self, selected_stocks: pd.DataFrame) -> str:
        if selected_stocks.empty:
            return ""

        top20 = selected_stocks.head(20)
        table = "## 🏆 Top 20 推荐\n\n"
        table += "| 排名 | 代码 | 名称 | PE | PB | 收盘价 | 综合分 | 评级 |\n"
        table += "|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n"

        for idx, (_, row) in enumerate(top20.iterrows(), 1):
            code = row.get('代码', '-')
            name = row.get('名称', '-')
            pe = f"{row['PE']:.1f}" if 'PE' in row and pd.notna(row.get('PE')) else '-'
            pb = f"{row['PB']:.1f}" if 'PB' in row and pd.notna(row.get('PB')) else '-'
            close = f"{row['收盘价']:.2f}" if '收盘价' in row and pd.notna(row.get('收盘价')) else '-'
            score_val = row.get('总分', row.get('total_score', 0))
            score = f"{score_val:.1f}" if pd.notna(score_val) else '-'
            rating = row.get('评级', '-')
            table += f"| {idx} | {code} | {name} | {pe} | {pb} | {close} | **{score}** | {rating} |\n"

        return table + "\n"

    def _disclaimer(self, timestamp: datetime) -> str:
        return f"""---

## ⚠️ 免责声明

本工具仅供学习研究，**不构成任何投资建议**。
数据来自 Baostock，存在 T+1 延迟；策略未经充分回测；投资决策请自行判断、风险自负。

*报告生成时间：{timestamp.strftime('%Y-%m-%d %H:%M')}*
*由 Trade-AI（改编自 striferxu/stock-picker-plus）生成*
"""
