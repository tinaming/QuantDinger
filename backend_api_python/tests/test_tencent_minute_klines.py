"""Tencent A-share minute (mkline) fallback for CNStock/multi-source."""

from app.data_sources import tencent
from app.data_sources.cn_stock import CNStockDataSource


def test_parse_tencent_kline_time_supports_compact_minute():
    ts = tencent.parse_tencent_kline_time("202607311114")
    assert ts is not None
    assert ts > 0


def test_fetch_minute_klines_parses_mkline_payload(monkeypatch):
    class _Resp:
        text = '{"ok": true}'
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "sh600519": {
                        "m1": [
                            ["202607310935", "1329.00", "1331.31", "1331.31", "1328.09", "1057.00"],
                            ["202607310936", "1331.31", "1332.00", "1332.50", "1331.00", "200.00"],
                        ]
                    }
                },
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(tencent, "assert_fd_available", lambda *_a, **_k: None)
    monkeypatch.setattr(tencent, "get_tencent_limiter", lambda: type("L", (), {"wait": staticmethod(lambda: None)})())
    monkeypatch.setattr(tencent.requests, "get", lambda *a, **k: _Resp())

    bars = tencent.fetch_minute_klines("SH600519", "1m", count=10)
    assert len(bars) == 2
    assert bars[0]["open"] == 1329.0
    assert bars[0]["close"] == 1331.31
    assert bars[0]["high"] == 1331.31
    assert bars[0]["low"] == 1328.09
    assert bars[1]["volume"] == 200.0


def test_cn_stock_uses_tencent_minute_when_other_tiers_empty(monkeypatch):
    monkeypatch.setattr("app.data_sources.cn_stock.fetch_twelvedata_klines", lambda **_k: [])
    monkeypatch.setattr("app.data_sources.cn_stock.fetch_yfinance_klines", lambda **_k: [])
    monkeypatch.setattr("app.data_sources.cn_stock.fetch_akshare_minute_klines", lambda **_k: [])
    monkeypatch.setattr(
        "app.data_sources.cn_stock.fetch_minute_klines",
        lambda code, timeframe, count=300: [
            {"time": 1_753_928_100, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 10.0},
            {"time": 1_753_928_160, "open": 1.05, "high": 1.2, "low": 1.0, "close": 1.1, "volume": 12.0},
        ],
    )

    ds = CNStockDataSource()
    bars = ds.get_kline("600519", "1m", 50)
    assert len(bars) == 2
    assert bars[-1]["close"] == 1.1
