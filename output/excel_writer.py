#!/usr/bin/env python3
"""
Excel导出模块

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ExcelWriter:
    """Excel文件写入器"""

    def __init__(self, output_dir: str = "reports/daily"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_stock_pool(self,
                         selected_stocks: pd.DataFrame,
                         pool: str,
                         strategy: str,
                         timestamp: Optional[datetime] = None) -> str:
        """
        将筛选结果写入Excel文件

        Returns:
            文件路径字符串
        """
        if timestamp is None:
            timestamp = datetime.now()

        ts_str = timestamp.strftime("%Y%m%d_%H%M")
        filename = f"stock_pool_{ts_str}.xlsx"
        filepath = self.output_dir / filename

        export_df = selected_stocks.copy()

        # 重命名列
        rename_map = {
            'code': '代码',
            'name': '名称',
            'total_score': '综合分',
            'ROE': 'ROE(%)',
            '营收增长率': '营收增长率(%)',
            '净利润增长率': '净利润增长率(%)',
        }
        export_df.rename(columns=rename_map, inplace=True, errors='ignore')

        # 统一 综合分 列
        if '总分' in export_df.columns and '综合分' not in export_df.columns:
            export_df.rename(columns={'总分': '综合分'}, inplace=True)

        # 选择要导出的列（按顺序，只保留存在的）
        preferred_cols = [
            '代码', '名称', 'PE', 'PB', '收盘价',
            'ROE(%)', '营收增长率(%)', '净利润增长率(%)',
            '基本面', '技术面', '情绪面',
            '综合分', '评级'
        ]
        available = [c for c in preferred_cols if c in export_df.columns]
        # 加上其他未列出的列
        extra = [c for c in export_df.columns if c not in preferred_cols and c != 'signal']
        export_df = export_df[available + extra]

        try:
            with pd.ExcelWriter(str(filepath), engine='openpyxl') as writer:
                export_df.to_excel(writer, sheet_name='推荐股票池', index=False)

                summary_df = self._summary_sheet(selected_stocks, pool, strategy, timestamp)
                summary_df.to_excel(writer, sheet_name='汇总统计', index=False)

            logger.info(f"✅ Excel导出成功: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"❌ Excel导出失败: {e}")
            raise

    def _summary_sheet(self, df: pd.DataFrame, pool: str,
                       strategy: str, timestamp: datetime) -> pd.DataFrame:
        score_col = next((c for c in ['总分', 'total_score', '综合分'] if c in df.columns), None)
        avg_score = f"{df[score_col].mean():.1f}" if score_col else '-'
        max_score = f"{df[score_col].max():.1f}" if score_col else '-'
        min_score = f"{df[score_col].min():.1f}" if score_col else '-'

        rows = {
            '项目': ['生成时间', '股票池', '策略', '推荐数量', '平均PE',
                     '平均ROE(%)', '平均综合分', '最高分', '最低分'],
            '数值': [
                timestamp.strftime('%Y-%m-%d %H:%M'),
                pool,
                strategy,
                len(df),
                f"{df['PE'].mean():.1f}" if 'PE' in df.columns else '-',
                f"{df['ROE'].mean():.1f}" if 'ROE' in df.columns else '-',
                avg_score,
                max_score,
                min_score,
            ]
        }
        return pd.DataFrame(rows)
