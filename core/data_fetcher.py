#!/usr/bin/env python3
"""
数据获取模块 - A股智能选股（AKShare版）
整合自 ai-stock-picker 的数据封装 + 批量查询优化

功能：
- 获取股票列表（全市场或指数成分）
- 获取单股行情（日线、估值）
- 获取财务数据（ROE、营收增长、利润增长，可降级）
- 批量查询（多线程 + 缓存）

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import threading
import time

logger = logging.getLogger(__name__)


# ============== 全局缓存 ==============

_spot_df_cache: Optional[pd.DataFrame] = None    # 全市场实时行情缓存
_spot_cache_time: Optional[datetime] = None
_SPOT_CACHE_TTL = 300                            # 5分钟 TTL

_spot_cache_lock = threading.Lock()


# ============== 工具函数 ==============

def _to_akshare_code(code: str) -> str:
    """将各种格式股票代码转为 AKShare 所需的6位数字代码。

    示例：
        "sh.600519"  → "600519"
        "600519.SH"  → "600519"
        "600519"     → "600519"（不变）
    """
    code = str(code).strip()
    if "." in code:
        parts = code.split(".")
        if parts[0].lower() in ("sh", "sz", "bj"):
            return parts[1].zfill(6)
        # 形如 "600519.SH"
        return parts[0].zfill(6)
    return code.zfill(6)


def _to_internal_code(code: str) -> str:
    """6位数字代码 → 项目内部格式（sh.600519 / sz.000858 / bj.430047）。"""
    code = str(code).strip()
    # 已经是内部格式 sh.XXXXXX / sz.XXXXXX / bj.XXXXXX
    if "." in code:
        parts = code.split(".")
        if parts[0].lower() in ("sh", "sz", "bj"):
            return f"{parts[0].lower()}.{parts[1]}"
        # 形如 600519.SH
        suffix = parts[1].lower()
        prefix_map = {"sh": "sh", "sz": "sz", "bj": "bj"}
        return f"{prefix_map.get(suffix, 'sh')}.{parts[0]}"
    # 纯6位数字
    code = code.zfill(6)
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    if code.startswith(("0", "3")):
        return f"sz.{code}"
    if code.startswith(("8", "4")):
        return f"bj.{code}"
    return f"sh.{code}"


def _extract_code(code: str) -> str:
    """提取6位数字代码（去掉市场前缀）。"""
    code = str(code).strip()
    if "." in code:
        parts = code.split(".")
        if parts[0].lower() in ("sh", "sz", "bj"):
            return parts[1]
        return parts[0]
    return code


# ============== 实时行情缓存 ==============

def _get_spot_data() -> pd.DataFrame:
    """获取全市场A股实时行情，带5分钟内存缓存。

    返回 DataFrame（东方财富 stock_zh_a_spot_em 数据，典型列名）：
      序号, 代码, 名称, 最新价, 涨跌幅, 涨跌额, 成交量, 成交额, 振幅,
      最高, 最低, 今开, 昨收, 量比, 换手率, 市盈率-动态, 市净率,
      总市值, 流通市值, ...
    """
    global _spot_df_cache, _spot_cache_time

    with _spot_cache_lock:
        now = datetime.now()
        if (_spot_df_cache is not None and _spot_cache_time is not None and
                (now - _spot_cache_time).total_seconds() < _SPOT_CACHE_TTL):
            return _spot_df_cache

        try:
            df = ak.stock_zh_a_spot_em()
            _spot_df_cache = df
            _spot_cache_time = now
            logger.info(f"✅ 获取A股实时行情成功: {len(df)} 只")
            return df
        except Exception as e:
            logger.error(f"获取A股实时行情失败: {e}")
            if _spot_df_cache is not None:
                logger.warning("使用行情旧缓存数据")
                return _spot_df_cache
            return pd.DataFrame()


# ============== 股票列表获取 ==============

def get_stock_basic() -> pd.DataFrame:
    """
    获取全市场A股基本信息。

    返回 DataFrame 列：code（sh.600519格式）, code_name
    """
    spot = _get_spot_data()
    if spot.empty:
        logger.error("无法获取A股行情数据")
        return pd.DataFrame()

    if "代码" not in spot.columns or "名称" not in spot.columns:
        logger.error(f"行情数据缺少字段，实际列: {list(spot.columns)}")
        return pd.DataFrame()

    df = spot[["代码", "名称"]].copy()
    df.columns = ["raw_code", "code_name"]
    df["code"] = df["raw_code"].apply(_to_internal_code)

    # 只保留沪深两市
    df = df[df["code"].str.startswith(("sh.", "sz."))].copy()
    # 过滤ST和退市
    df = df[~df["code_name"].str.contains("ST|退市", na=False)]

    logger.info(f"✅ 获取股票列表成功: {len(df)} 只")
    return df[["code", "code_name"]].reset_index(drop=True)


def get_index_components(index: str = "hs300") -> List[str]:
    """
    获取指数成分股列表。

    参数:
        index: "hs300"（沪深300）| "zz500"（中证500）| "zz1000"（中证1000）| "all"

    返回: 内部格式代码列表（如 ['sh.600519', 'sz.000858']）
    """
    if index == "all":
        df = get_stock_basic()
        return df["code"].tolist() if not df.empty else []

    index_code_map = {
        "hs300":  "000300",
        "zz500":  "000905",
        "zz1000": "000852",
    }
    idx_code = index_code_map.get(index)
    if not idx_code:
        logger.warning(f"未知指数 {index}，降级到全市场")
        return get_index_components("all")

    codes: List[str] = []

    # 尝试主接口（中证指数官网）
    for fetch_fn, fn_name in [
        (lambda: ak.index_stock_cons_csindex(symbol=idx_code), "csindex"),
        (lambda: ak.index_stock_cons(symbol=idx_code), "index_stock_cons"),
    ]:
        try:
            df = fetch_fn()
            # 寻找代码列（列名因接口版本而异）
            code_col = next(
                (c for c in ["成份券代码", "品种代码", "代码", "股票代码"]
                 if c in df.columns),
                df.columns[0] if not df.empty else None,
            )
            if code_col:
                for raw in df[code_col].astype(str):
                    raw = raw.strip().zfill(6)
                    c = _to_internal_code(raw)
                    if c.startswith(("sh.", "sz.")):
                        codes.append(c)
            if codes:
                logger.info(f"✅ {index}（{fn_name}）成分股: {len(codes)} 只")
                break
        except Exception as e:
            logger.warning(f"获取 {index} 成分股（{fn_name}）失败: {e}")

    if not codes:
        logger.warning(f"{index} 成分股获取失败，降级到全市场")
        return get_index_components("all")

    return codes


# ============== 单股数据查询 ==============

def get_stock_daily(symbol: str, days: int = 30) -> pd.DataFrame:
    """获取单只股票日线行情（前复权）。"""
    ak_code = _to_akshare_code(symbol)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

    try:
        df = ak.stock_zh_a_hist(
            symbol=ak_code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
    except Exception as e:
        logger.debug(f"查询 {symbol} 日线失败: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # 列名映射为项目通用格式
    col_map = {
        "日期":  "date",
        "开盘":  "open",
        "收盘":  "close",
        "最高":  "high",
        "最低":  "low",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "pctChg",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df.set_index("date", inplace=True)

    for col in ["open", "high", "low", "close", "volume", "amount", "pctChg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "volume" in df.columns:
        df = df[df["volume"] > 0]
    if len(df) > days:
        df = df.iloc[-days:]

    return df


def get_valuation_from_spot(symbol: str) -> Optional[Dict[str, Any]]:
    """从实时行情缓存获取估值快照（PE、PB、收盘价、总市值）。"""
    ak_code = _to_akshare_code(symbol)
    spot = _get_spot_data()

    if spot.empty or "代码" not in spot.columns:
        return None

    row = spot[spot["代码"] == ak_code]
    if row.empty:
        return None

    r = row.iloc[0]

    def _safe_float(val) -> Optional[float]:
        try:
            v = float(val)
            return v if np.isfinite(v) else None
        except (ValueError, TypeError):
            return None

    pe_col    = next((c for c in ["市盈率-动态", "市盈率(动态)", "动态市盈率", "市盈率"]
                      if c in spot.columns), None)
    pb_col    = next((c for c in ["市净率", "PB"] if c in spot.columns), None)
    close_col = next((c for c in ["最新价", "收盘", "当前价"] if c in spot.columns), None)
    mcap_col  = next((c for c in ["总市值"] if c in spot.columns), None)

    return {
        "pe":         _safe_float(r[pe_col])    if pe_col    else None,
        "pb":         _safe_float(r[pb_col])    if pb_col    else None,
        "close":      _safe_float(r[close_col]) if close_col else None,
        "market_cap": _safe_float(r[mcap_col])  if mcap_col  else None,
    }


# ============== 财务数据查询 ==============

def get_financials_akshare(symbol: str) -> Dict[str, Any]:
    """
    获取单只股票财务指标（ROE、营收增长、利润增长）。

    PE/PB 从实时行情缓存取得（快速）；ROE/增长率从财务分析接口获取（可降级为 None）。
    任何异常均捕获并静默，不影响整体流程。
    """
    result: Dict[str, Any] = {
        "pe_ratio":       None,
        "pb_ratio":       None,
        "roe":            None,
        "revenue_growth": None,
        "profit_growth":  None,
        "gross_margin":   None,
        "net_margin":     None,
    }

    # PE/PB 从实时行情（内存缓存，速度极快）
    val = get_valuation_from_spot(symbol)
    if val:
        result["pe_ratio"] = val["pe"]
        result["pb_ratio"] = val["pb"]

    ak_code = _to_akshare_code(symbol)

    try:
        # 只拉近2年的数据（取最新一行），减少传输量
        start_year = str(datetime.now().year - 1)
        fin_df = ak.stock_financial_analysis_indicator(stock=ak_code, start_year=start_year)
        if fin_df is not None and not fin_df.empty:
            latest = fin_df.iloc[0]  # 通常按时间倒序，取最新一行

            def _find_col(*keywords: str) -> Optional[str]:
                for kw in keywords:
                    for c in fin_df.columns:
                        if kw in c:
                            return c
                return None

            def _safe_val(col: Optional[str]) -> Optional[float]:
                if col is None:
                    return None
                v = pd.to_numeric(latest.get(col), errors="coerce")
                return float(v) if pd.notna(v) else None

            result["roe"]            = _safe_val(_find_col("净资产收益率", "ROE"))
            result["revenue_growth"] = _safe_val(
                _find_col("主营业务收入增长率", "营业收入增长率", "营收增长"))
            result["profit_growth"]  = _safe_val(
                _find_col("净利润增长率", "净利润同比增长率"))
            result["gross_margin"]   = _safe_val(_find_col("销售毛利率", "毛利率"))
            result["net_margin"]     = _safe_val(_find_col("销售净利率", "净利率"))
    except Exception as e:
        logger.debug(f"查询 {symbol} 财务数据失败（已降级）: {e}")

    return result


# ============== 批量查询（多线程优化） ==============

def _fetch_single_stock(code: str, fields: List[str]) -> Optional[Dict[str, Any]]:
    """查询单只股票数据（供批量调用）。

    返回 None 表示"合法跳过"（ST股/无数据/亏损股）。
    抛出异常表示网络/解析错误（由上层重试逻辑处理）。
    """
    ak_code = _to_akshare_code(code)
    spot = _get_spot_data()

    # 从行情缓存获取名称
    name = ""
    if not spot.empty and "代码" in spot.columns and "名称" in spot.columns:
        row = spot[spot["代码"] == ak_code]
        if not row.empty:
            name = str(row.iloc[0]["名称"])

    # 过滤ST和退市
    if name and ("ST" in name or "退市" in name):
        return None

    # 从行情缓存获取估值
    val = get_valuation_from_spot(code)
    pe         = val["pe"]         if val else None
    pb         = val["pb"]         if val else None
    close      = val["close"]      if val else None
    market_cap = val["market_cap"] if val else None

    # 过滤亏损股（PE≤0）
    if pe is not None and pe <= 0:
        return None

    record: Dict[str, Any] = {
        "代码":  ak_code,
        "名称":  name,
        "收盘价": close,
        "PE":    pe,
        "PB":    pb,
        "总市值": market_cap,
    }

    if "financials" in fields:
        fins = get_financials_akshare(code)
        record["ROE"]        = fins.get("roe")
        record["营收增长率"]  = fins.get("revenue_growth")
        record["净利润增长率"] = fins.get("profit_growth")
        record["毛利率"]      = fins.get("gross_margin")
        record["净利率"]      = fins.get("net_margin")

    return record


def _fetch_single_stock_with_retry(
    code: str,
    fields: List[str],
    max_retries: int = 2,
    rate_limit_sleep: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """带重试和限速的单只股票查询。

    AKShare 基于 HTTP，无需全局串行锁，可安全并发。
    捕获所有异常，最多重试 max_retries 次后返回 None（跳过）。
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(2 ** (attempt - 1))   # 指数退避：第1次重试等1s，第2次等2s，依此类推
        try:
            if rate_limit_sleep > 0:
                time.sleep(rate_limit_sleep)
            return _fetch_single_stock(code, fields)
        except Exception as e:
            last_exc = e
            logger.debug(f"查询 {code} 异常(尝试{attempt + 1}/{max_retries + 1}): {e}")

    logger.debug(f"查询 {code} 已达最大重试次数，跳过: {last_exc}")
    return None


def fetch_batch(
    codes: List[str],
    fields: List[str] = None,
    max_workers: int = 5,
    use_cache: bool = False,
    progress_callback=None,
    stop_event: Optional[threading.Event] = None,
    max_retries: int = 2,
    rate_limit_sleep: float = 0.3,
) -> pd.DataFrame:
    """
    批量查询多只股票数据（多线程 + 超时保护 + 失败跳过）。

    Args:
        codes:             股票代码列表（内部格式或6位数字）
        fields:            字段列表 ['basic', 'valuation', 'financials']
        max_workers:       并发线程数（默认5，AKShare HTTP安全并发）
        use_cache:         是否使用本地文件缓存（当前版本预留参数）
        progress_callback: 进度回调 fn(completed, total)
        stop_event:        停止信号 Event，设置后提前退出
        max_retries:       单股最大重试次数
        rate_limit_sleep:  每次请求前最小间隔（秒）

    Returns:
        DataFrame，每行一只股票（失败/过滤的股票自动跳过）
    """
    if fields is None:
        fields = ["basic", "valuation", "financials"]

    # 预加载全市场实时行情（一次性，供所有单股查询复用）
    logger.info("预加载A股实时行情缓存...")
    _get_spot_data()

    results: List[Dict[str, Any]] = []
    total = len(codes)
    # 整体超时：每只股票最多 8 秒，下限 60s，上限 900s
    overall_timeout = max(60, min(900, total * 8))

    logger.info(
        f"开始批量查询: {total} 只股票，{max_workers} 线程，整体超时 {overall_timeout}s"
    )

    executor = ThreadPoolExecutor(max_workers=max_workers)
    completed = 0
    try:
        future_to_code = {
            executor.submit(
                _fetch_single_stock_with_retry, code, fields, max_retries, rate_limit_sleep
            ): code
            for code in codes
        }

        try:
            for future in as_completed(future_to_code, timeout=overall_timeout):
                if stop_event is not None and stop_event.is_set():
                    logger.info(f"收到停止信号，中断批量查询 ({completed}/{total})")
                    if progress_callback:
                        progress_callback(total, total)
                    break

                code = future_to_code[future]
                try:
                    data = future.result()
                    if data:
                        results.append(data)
                except Exception as e:
                    logger.debug(f"查询 {code} 结果获取异常: {e}")

                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
                if completed % 10 == 0 or completed == total:
                    logger.info(
                        f"  进度: {completed}/{total} ({completed / total * 100:.0f}%) "
                        f"有效: {len(results)}"
                    )

        except concurrent.futures.TimeoutError:
            skipped = total - completed
            logger.warning(
                f"批量查询整体超时 ({overall_timeout}s)，{skipped} 只未完成，已跳过"
            )
            if progress_callback:
                progress_callback(total, total)

    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    success = len(results)
    uncompleted = total - completed
    logger.info(
        f"✅ 批量查询完成: 成功 {success} 只 / 共处理 {completed} 只 / "
        f"超时未处理 {uncompleted} 只（已跳过）"
    )

    if not results:
        logger.warning("批量查询未获取到有效数据")
        return pd.DataFrame()

    return pd.DataFrame(results)


# ============== DataFetcher 类封装 ==============

class DataFetcher:
    """数据获取器类（面向对象接口）"""

    def __init__(self, config_path: str = "config/"):
        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> Dict:
        import yaml
        try:
            path_obj = Path(path)
            if path_obj.is_dir():
                config: Dict = {}
                for yaml_file in path_obj.glob("*.yaml"):
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        config.update(yaml.safe_load(f) or {})
                return config
            else:
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载配置失败: {e}，使用默认")
            return {}

    def get_stock_basic(self) -> pd.DataFrame:
        return get_stock_basic()

    def get_stock_daily(self, symbol: str, days: int = 30) -> pd.DataFrame:
        return get_stock_daily(symbol, days)

    def get_fundamental(self, symbol: str) -> Dict:
        return get_financials_akshare(symbol)

    def fetch_batch(
        self,
        codes: List[str],
        fields=None,
        max_workers: int = 5,
        use_cache: bool = False,
        progress_callback=None,
        stop_event: Optional[threading.Event] = None,
        max_retries: int = 2,
        rate_limit_sleep: float = 0.3,
    ) -> pd.DataFrame:
        if fields is None:
            fields = ["basic", "valuation", "financials"]
        return fetch_batch(
            codes, fields, max_workers, use_cache, progress_callback,
            stop_event=stop_event,
            max_retries=max_retries,
            rate_limit_sleep=rate_limit_sleep,
        )

    def get_index_components(self, index: str) -> List[str]:
        return get_index_components(index)


def init_data_fetcher():
    """初始化数据获取模块（预热行情缓存）。"""
    _get_spot_data()


def cleanup_data_fetcher():
    """清理数据获取模块（当前无持久连接需要关闭）。"""
    pass
