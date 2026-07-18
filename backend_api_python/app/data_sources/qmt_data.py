"""
A股数据源 — QMT (xtdata)

通过 miniQMT 的 xtdata 模块获取 A 股 K 线数据。
优势：数据最全、实时、不依赖外部 API。

依赖：
- miniQMT 客户端运行中（XtMiniQmt.exe）
- xtquant 包在 sys.path 中

配置：
- QMT_LIB_PATH: xtquant 所在 site-packages 路径
  默认: D:\\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\\userdata_mini\\site-packages
"""

from __future__ import annotations

import sys
import time
from typing import Dict, List, Any, Optional

from app.data_sources.base import BaseDataSource
from app.utils.logger import get_logger

logger = get_logger(__name__)

# xtquant 模块缓存
_xtdata = None


def _ensure_xtdata(lib_path: str = ""):
    """确保 xtdata 可导入"""
    global _xtdata
    if _xtdata is not None:
        return _xtdata

    path = (lib_path or "").strip()
    if path and path not in sys.path:
        sys.path.insert(0, path)

    try:
        from xtquant import xtdata
        _xtdata = xtdata
        logger.info("xtdata loaded successfully from %s", path or "sys.path")
        return xtdata
    except ImportError as e:
        raise ImportError(
            f"xtquant is not available. Ensure miniQMT is installed and "
            f"QMT_LIB_PATH points to the site-packages directory. Error: {e}"
        )


# QuantDinger timeframe → xtdata period 映射
_TF_TO_PERIOD = {
    '1m': '1m',
    '3m': '3m',
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '1H': '60m',
    '4H': '60m',   # xtdata 没有 4H，用 60m 后聚合
    '1D': '1d',
    '1W': '1w',
}


def _normalize_cn_symbol(symbol: str) -> str:
    """
    标准化 A 股代码为 QMT 格式 (600519.SH)。

    支持: "600519", "600519.SH", "SH600519", "600519.SS", "600519.XSHG"
    """
    s = (symbol or "").strip().upper().replace(" ", "").replace("-", "")

    # 已有 .SH/.SZ/.BJ 后缀
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            return s

    # SS/XSHG → SH, XSHE → SZ
    for alias, real in (".SS", ".SH"), (".XSHG", ".SH"), (".XSHE", ".SZ"):
        if s.endswith(alias):
            s = s[:-len(alias)] + real
            return s

    # SH600519 / SZ000001 前缀格式
    for pfx, sfx in (("SH", ".SH"), ("SZ", ".SZ"), ("BJ", ".BJ")):
        if s.startswith(pfx) and len(s) > len(pfx) and s[len(pfx)].isdigit():
            return s[len(pfx):] + sfx

    # 纯数字代码，根据前缀推断交易所
    if s.isdigit() and len(s) == 6:
        if s.startswith("6") or s.startswith("5"):
            return s + ".SH"
        if s.startswith("0") or s.startswith("3"):
            return s + ".SZ"
        if s.startswith("8") or s.startswith("4") or s.startswith("9"):
            return s + ".BJ"

    # 默认上海
    return s + ".SH" if s.isdigit() else s


class QMTDataSource(BaseDataSource):
    """A 股数据源 — 通过 miniQMT xtdata 获取 K 线"""

    name = "CNStock/QMT"

    def __init__(self, lib_path: str = ""):
        self._lib_path = lib_path

    def _get_xtdata(self):
        return _ensure_xtdata(self._lib_path)

    def get_kline(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        before_time: Optional[int] = None,
        after_time: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        xtdata = self._get_xtdata()

        qmt_symbol = _normalize_cn_symbol(symbol)
        period = _TF_TO_PERIOD.get(timeframe, '1d')
        lim = max(int(limit or 300), 1)

        # 计算时间范围
        from datetime import datetime, timezone, timedelta
        tz_cst = timezone(timedelta(hours=8))

        if before_time:
            end_dt = datetime.fromtimestamp(before_time, tz=timezone.utc)
        else:
            end_dt = datetime.now(tz=timezone.utc)

        if after_time:
            start_dt = datetime.fromtimestamp(after_time, tz=timezone.utc)
        else:
            # 根据 timeframe 估算起始时间
            from app.data_sources.base import TIMEFRAME_SECONDS
            tf_sec = TIMEFRAME_SECONDS.get(timeframe, 86400)
            total_sec = int(tf_sec * lim * 1.5)
            start_dt = end_dt - timedelta(seconds=total_sec)

        start_str = start_dt.strftime('%Y%m%d')
        end_str = end_dt.strftime('%Y%m%d')

        logger.info(
            "QMT get_kline: symbol=%s period=%s range=%s~%s limit=%d",
            qmt_symbol, period, start_str, end_str, lim,
        )

        try:
            # 先下载数据（xtdata 会缓存到本地）
            xtdata.download_history_data(qmt_symbol, period, start_str, end_str)
            time.sleep(1)

            # 获取数据
            data = xtdata.get_market_data_ex(
                ['open', 'high', 'low', 'close', 'volume'],
                [qmt_symbol],
                period=period,
                start_time=start_str,
                end_time=end_str,
                count=-1,
                dividend_type='front',  # 前复权
            )

            if not isinstance(data, dict) or qmt_symbol not in data:
                logger.warning("QMT: no data for %s period=%s", qmt_symbol, period)
                return []

            df = data[qmt_symbol]
            if df is None or len(df) == 0:
                logger.warning("QMT: empty DataFrame for %s period=%s", qmt_symbol, period)
                return []

            # 4H 聚合：将 60m 数据聚合为 4H
            if timeframe == '4H':
                df = self._aggregate_4h(df)

            # 转换为 QuantDinger 格式
            klines = []
            for idx, row in df.iterrows():
                # xtdata 索引格式: YYYYMMDD (日线) 或 YYYYMMDDHHMMSS (分钟线)
                ts = self._parse_xtdata_timestamp(str(idx), timeframe)
                if ts is None:
                    continue

                klines.append({
                    'time': ts,
                    'open': round(float(row['open']), 4),
                    'high': round(float(row['high']), 4),
                    'low': round(float(row['low']), 4),
                    'close': round(float(row['close']), 4),
                    'volume': round(float(row.get('volume', 0)), 2),
                })

            # 过滤和限制
            return self.filter_and_limit(
                klines,
                limit=lim,
                before_time=before_time,
                after_time=after_time,
                truncate=(after_time is None),
            )

        except Exception as e:
            logger.error(f"QMT get_kline failed: {e}")
            return []

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """获取最新行情"""
        try:
            xtdata = self._get_xtdata()
            qmt_symbol = _normalize_cn_symbol(symbol)

            xtdata.subscribe_quote(qmt_symbol, period="tick")
            time.sleep(1)

            tick = xtdata.get_full_tick([qmt_symbol])
            if qmt_symbol in tick and tick[qmt_symbol]:
                t = tick[qmt_symbol]
                last_price = float(t.get("lastPrice", 0))
                return {
                    "last": last_price,
                    "open": float(t.get("open", 0)),
                    "high": float(t.get("high", 0)),
                    "low": float(t.get("low", 0)),
                    "previousClose": float(t.get("lastClose", 0)),
                    "volume": float(t.get("volume", 0)),
                    "amount": float(t.get("amount", 0)),
                    "symbol": qmt_symbol,
                }
            return {"last": 0, "symbol": qmt_symbol}
        except Exception as e:
            logger.error(f"QMT get_ticker failed: {e}")
            return {"last": 0, "symbol": symbol}

    @staticmethod
    def _parse_xtdata_timestamp(ts_str: str, timeframe: str) -> Optional[int]:
        """
        将 xtdata 时间戳字符串转为 Unix 秒。

        日线: "20240102" → 当天 00:00:00 UTC+8
        分钟线: "20250704101200" → 精确时间
        """
        from datetime import datetime, timezone, timedelta

        tz_cst = timezone(timedelta(hours=8))

        try:
            if len(ts_str) == 8:
                # 日线格式 YYYYMMDD
                dt = datetime.strptime(ts_str, '%Y%m%d')
                dt = dt.replace(tzinfo=tz_cst)
            elif len(ts_str) == 14:
                # 分钟线格式 YYYYMMDDHHMMSS
                dt = datetime.strptime(ts_str, '%Y%m%d%H%M%S')
                dt = dt.replace(tzinfo=tz_cst)
            else:
                return None
            return int(dt.timestamp())
        except (ValueError, OSError):
            return None

    @staticmethod
    def _aggregate_4h(df) -> 'pd.DataFrame':
        """将 60 分钟数据聚合为 4 小时 K 线"""
        import pandas as pd

        if df is None or len(df) == 0:
            return df

        df = df.copy()
        # 确保索引是 datetime
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, format='%Y%m%d%H%M%S', errors='coerce')
            df = df.dropna()

        # 4H 重采样
        resampled = df.resample('4H').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
        }).dropna()

        return resampled
