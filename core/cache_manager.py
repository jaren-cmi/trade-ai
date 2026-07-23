#!/usr/bin/env python3
"""
缓存管理器 - 减少重复查询（按日期缓存股票数据）

改编自：https://github.com/striferxu/stock-picker-plus（GPLv3）
"""

import pandas as pd
import json
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class CacheManager:
    """缓存管理器"""

    def __init__(self, cache_dir: str = "data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_cache: Dict[str, pd.DataFrame] = {}

    def _get_cache_key(self, prefix: str, params: Dict[str, Any]) -> str:
        param_str = json.dumps(params, sort_keys=True, default=str)
        hash_val = hashlib.md5(param_str.encode()).hexdigest()[:8]
        return f"{prefix}_{hash_val}"

    def _get_date_suffix(self) -> str:
        return date.today().strftime("%Y%m%d")

    def get(self, cache_type: str, params: Dict[str, Any]) -> Optional[pd.DataFrame]:
        key = self._get_cache_key(cache_type, params)
        date_suffix = self._get_date_suffix()
        cache_file = self.cache_dir / f"{key}_{date_suffix}.pkl"

        if key in self.memory_cache:
            return self.memory_cache[key]

        if cache_file.exists():
            try:
                df = pd.read_pickle(cache_file)
                self.memory_cache[key] = df
                logger.debug(f"缓存命中: {cache_file.name}")
                return df
            except Exception as e:
                logger.warning(f"缓存读取失败: {e}")

        return None

    def set(self, cache_type: str, params: Dict[str, Any], data: pd.DataFrame):
        if data is None or (hasattr(data, 'empty') and data.empty):
            return

        key = self._get_cache_key(cache_type, params)
        date_suffix = self._get_date_suffix()
        cache_file = self.cache_dir / f"{key}_{date_suffix}.pkl"

        try:
            data.to_pickle(cache_file)
            self.memory_cache[key] = data
            logger.debug(f"缓存写入: {cache_file.name}")
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    def clear(self, older_than_days: int = 7):
        cutoff = date.today().toordinal() - older_than_days
        cleared = 0
        for f in self.cache_dir.glob("*.pkl"):
            try:
                date_str = f.stem.split('_')[-1]
                file_date = datetime.strptime(date_str, "%Y%m%d").date()
                if file_date.toordinal() < cutoff:
                    f.unlink()
                    cleared += 1
            except Exception:
                continue
        logger.info(f"清理缓存: 删除 {cleared} 个旧文件")

    def get_stock_list_cache(self) -> Optional[pd.DataFrame]:
        return self.get("stock_list", {"source": "baostock"})

    def set_stock_list_cache(self, df: pd.DataFrame):
        self.set("stock_list", {"source": "baostock"}, df)
