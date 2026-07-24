#!/usr/bin/env python3
"""
数据获取模块 - A股智能选股（完整版）
整合自 ai-stock-picker 的 Baostock 封装 + 批量查询优化

功能：
- 登录/登出 Baostock
- 获取股票列表（全市场或指数成分）
- 获取单股行情（日线、估值）
- 获取财务数据（ROE、营收增长、利润增长）
- 批量查询（多线程 + 缓存）

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import baostock as bs
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logger = logging.getLogger(__name__)


# ============== 全局缓存 ==============

_stock_info_cache: Optional[Dict] = None  # 股票基本信息缓存（code -> name）


# ============== 全局登录状态 ==============

_bs_logged_in = False


def _ensure_login():
    """确保 Baostock 已登录"""
    global _bs_logged_in
    if not _bs_logged_in:
        lg = bs.login(user_id="anonymous", password="123456")
        if lg.error_code != "0":
            raise RuntimeError(f"Baostock登录失败: {lg.error_msg}")
        _bs_logged_in = True
        logger.info("✅ Baostock 登录成功")


def _ensure_logout():
    """确保 Baostock 已登出"""
    global _bs_logged_in
    if _bs_logged_in:
        try:
            bs.logout()
            logger.info("Baostock 已登出")
        except Exception:
            pass
        _bs_logged_in = False


# ============== 工具函数 ==============

def _normalize_code(code: str) -> str:
    """
    标准化股票代码为 Baostock 格式

    输入:
        "600519" → "sh.600519"
        "000858" → "sz.000858"
        "sh.600519" → "sh.600519"（不变）
    """
    code = str(code).strip()
    if "." not in code:
        if code.startswith("6"):
            return f"sh.{code}"
        elif code.startswith(("0", "3")):
            return f"sz.{code}"
        elif code.startswith("8"):
            return f"bj.{code}"
        else:
            return f"sh.{code}"
    return code


def _extract_code(bs_code: str) -> str:
    """从 Baostock 代码提取6位数字代码：'sh.600519' → '600519'"""
    if "." in bs_code:
        return bs_code.split(".")[1]
    return bs_code


# ============== 股票列表获取 ==============

def get_stock_basic() -> pd.DataFrame:
    """
    获取全市场A股基本信息

    返回 DataFrame 列：code, code_name, ipoDate, outDate, type, status
    """
    _ensure_login()

    rs = bs.query_stock_basic()
    if rs.error_code != "0":
        logger.error(f"获取股票列表失败: {rs.error_msg}")
        return pd.DataFrame()

    data = []
    while rs.error_code == "0" and rs.next():
        row = rs.get_row_data()
        data.append(row)

    if not data:
        logger.warning("股票列表为空")
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=rs.fields)

    # 过滤：仅保留A股（sh. 或 sz.）且状态为上市
    df = df[df['code'].str.startswith(('sh.', 'sz.'))]
    df = df[df['status'] == '1']

    logger.info(f"✅ 获取股票列表成功: {len(df)} 只")
    return df


def get_stock_info_baostock(bs_code: str) -> Optional[Dict[str, str]]:
    """获取单只股票基本信息（名称等）"""
    global _stock_info_cache

    if _stock_info_cache is None:
        df = get_stock_basic()
        if df.empty:
            return None
        _stock_info_cache = df[['code', 'code_name']].set_index('code')['code_name'].to_dict()

    name = _stock_info_cache.get(bs_code)
    if name:
        return {
            '代码': _extract_code(bs_code),
            '名称': name,
            '市场': 'sh' if bs_code.startswith('sh.') else 'sz'
        }
    return None


def get_index_components(index: str = "hs300") -> List[str]:
    """
    获取指数成分股列表

    参数:
        index: "hs300"（沪深300）| "zz500"（中证500，暂回落到全市场）| "zz1000" | "all"

    返回: Baostock格式代码列表（如 ['sh.600519', 'sz.000858']）
    """
    _ensure_login()

    if index == "all":
        df = get_stock_basic()
        return df['code'].tolist() if not df.empty else []

    if index == "hs300":
        rs = bs.query_hs300_stocks()
        if rs.error_code != "0":
            logger.error(f"获取沪深300成分股失败: {rs.error_msg}")
            return []
        codes = []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            codes.append(row[1])
        logger.info(f"✅ 沪深300成分股: {len(codes)} 只")
        return codes

    # zz500、zz1000 Baostock 暂不直接支持，返回全市场
    logger.warning(f"指数 {index} Baostock 暂不支持，降级到全市场")
    return get_index_components("all")


# ============== 单股数据查询 ==============

def get_stock_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    """获取单只股票日线行情"""
    _ensure_login()
    bs_code = _normalize_code(symbol)

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,pctChg,peTTM,pbMRQ",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2"
    )

    if rs.error_code != "0":
        logger.warning(f"查询 {symbol} 日线失败: {rs.error_msg}")
        return pd.DataFrame()

    data = []
    while rs.error_code == "0" and rs.next():
        data.append(rs.get_row_data())

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=rs.fields)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg', 'peTTM', 'pbMRQ']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df[df['volume'] > 0]
    if len(df) > days:
        df = df.iloc[-days:]

    return df


def get_valuation_snapshot(symbol: str) -> Optional[Dict[str, Any]]:
    """获取股票最新估值快照（PE、PB）"""
    df = get_stock_daily(symbol, days=5)
    if df.empty:
        return None

    latest = df.iloc[-1]
    return {
        'pe': float(latest['peTTM']) if pd.notna(latest['peTTM']) else None,
        'pb': float(latest['pbMRQ']) if pd.notna(latest['pbMRQ']) else None,
        'close': float(latest['close']) if pd.notna(latest['close']) else None,
        'date': latest.name.strftime('%Y-%m-%d')
    }


# ============== 财务数据查询 ==============

def get_financials_baostock(symbol: str) -> Dict[str, Any]:
    """获取单只股票财务指标（ROE、营收增长、利润增长）"""
    _ensure_login()

    result = {
        'pe_ratio': None,
        'pb_ratio': None,
        'roe': None,
        'revenue_growth': None,
        'profit_growth': None,
        'gross_margin': None,
        'net_margin': None,
    }

    valuation = get_valuation_snapshot(symbol)
    if valuation:
        result['pe_ratio'] = valuation['pe']
        result['pb_ratio'] = valuation['pb']

    bs_code = _normalize_code(symbol)
    current_year = datetime.now().year
    current_quarter = (datetime.now().month - 1) // 3 + 1

    try:
        for quarter in range(current_quarter, 0, -1):
            pf = bs.query_profit_data(code=bs_code, year=current_year, quarter=quarter)
            if pf.error_code == "0" and pf.next():
                row = pf.get_row_data()
                if row[3] and row[3] != '':
                    result['roe'] = float(row[3])
                if row[4] and row[4] != '':
                    result['gross_margin'] = float(row[4])
                if row[5] and row[5] != '':
                    result['net_margin'] = float(row[5])
                break
    except Exception as e:
        logger.debug(f"查询 {symbol} 盈利能力失败: {e}")

    try:
        for quarter in range(current_quarter, 0, -1):
            gr = bs.query_growth_data(code=bs_code, year=current_year, quarter=quarter)
            if gr.error_code == "0" and gr.next():
                row = gr.get_row_data()
                if row[5] and row[5] != '':
                    result['profit_growth'] = float(row[5])
                if row[6] and row[6] != '':
                    result['revenue_growth'] = float(row[6])
                break
    except Exception as e:
        logger.debug(f"查询 {symbol} 成长能力失败: {e}")

    return result


# ============== 批量查询（多线程优化） ==============

def fetch_batch(codes: List[str],
                fields: List[str] = None,
                max_workers: int = 10,
                use_cache: bool = False,
                progress_callback=None
                ) -> pd.DataFrame:
    """
    批量查询多只股票数据（多线程）

    Args:
        codes: 股票代码列表（Baostock格式或6位数字）
        fields: 字段列表 ['basic', 'valuation', 'financials']
        max_workers: 并发线程数
        use_cache: 是否使用缓存
        progress_callback: 进度回调函数 fn(completed, total)

    Returns:
        DataFrame，每行一只股票
    """
    if fields is None:
        fields = ['basic', 'valuation', 'financials']

    _ensure_login()

    results = []
    total = len(codes)

    logger.info(f"开始批量查询: {total} 只股票，{max_workers} 线程")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_code = {
            executor.submit(_fetch_single_stock, code, fields): code
            for code in codes
        }

        completed = 0
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                data = future.result(timeout=15)
                if data:
                    results.append(data)
            except Exception as e:
                logger.debug(f"查询 {code} 异常: {e}")

            completed += 1
            if progress_callback:
                progress_callback(completed, total)
            if completed % 50 == 0:
                logger.info(f"  进度: {completed}/{total} ({completed/total*100:.0f}%)")

    if not results:
        logger.warning("批量查询未获取到有效数据")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    logger.info(f"✅ 批量查询完成: {len(df)}/{total} 只有效")
    return df


def _fetch_single_stock(code: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    """查询单只股票（用于批量查询）"""
    try:
        bs_code = _normalize_code(code)

        info = get_stock_info_baostock(bs_code)
        name = info.get('名称', '') if info else ''

        val = get_valuation_snapshot(bs_code)
        pe = val['pe'] if val else None
        pb = val['pb'] if val else None
        close = val['close'] if val else None

        fins = get_financials_baostock(bs_code) if 'financials' in fields else {}

        record = {
            '代码': _extract_code(bs_code),
            '名称': name,
            '收盘价': close,
            'PE': pe,
            'PB': pb,
        }

        if 'financials' in fields:
            record['ROE'] = fins.get('roe')
            record['营收增长率'] = fins.get('revenue_growth')
            record['净利润增长率'] = fins.get('profit_growth')
            record['毛利率'] = fins.get('gross_margin')
            record['净利率'] = fins.get('net_margin')

        # 过滤亏损股
        if pe is not None and pe <= 0:
            return None

        # 过滤ST股
        if name and ('ST' in name or '退市' in name):
            return None

        return record

    except Exception as e:
        logger.debug(f"单股查询失败 {code}: {e}")
        return None


# ============== DataFetcher 类封装 ==============

class DataFetcher:
    """数据获取器类（面向对象接口）"""

    def __init__(self, config_path: str = "config/"):
        self.config = self._load_config(config_path)
        _ensure_login()

    def _load_config(self, path: str) -> Dict:
        import yaml
        try:
            path_obj = Path(path)
            if path_obj.is_dir():
                config = {}
                for yaml_file in path_obj.glob("*.yaml"):
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        config.update(yaml.safe_load(f) or {})
                return config
            else:
                with open(path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载配置失败: {e}，使用默认")
            return {}

    def get_stock_basic(self) -> pd.DataFrame:
        return get_stock_basic()

    def get_stock_daily(self, symbol: str, days: int = 30) -> pd.DataFrame:
        return get_stock_daily(symbol, days)

    def get_fundamental(self, symbol: str) -> Dict:
        return get_financials_baostock(symbol)

    def fetch_batch(self, codes: List[str], fields=None, max_workers=10,
                    use_cache=False, progress_callback=None) -> pd.DataFrame:
        if fields is None:
            fields = ['basic', 'valuation', 'financials']
        return fetch_batch(codes, fields, max_workers, use_cache, progress_callback)

    def get_index_components(self, index: str) -> List[str]:
        return get_index_components(index)


def init_data_fetcher():
    """初始化数据获取模块"""
    _ensure_login()


def cleanup_data_fetcher():
    """清理数据获取模块"""
    _ensure_logout()
