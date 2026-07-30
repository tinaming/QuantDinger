"""
CNStock CZSC V3 Backtest — 30天回测 QMT 持仓股票

Usage:
    cd backend_api_python
    python scripts/backtest_cnstock_30d.py
    python scripts/backtest_cnstock_30d.py --timeframe 1D
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Force QMT Bridge as CNStock data source (bridge is running on port 5002)
os.environ["CN_STOCK_DATA_SOURCE"] = "bridge"
os.environ["QMT_BRIDGE_URL"] = "http://127.0.0.1:5002"

from app.services.backtest import BacktestService
from tests.test_czsc_strategy_generation import CZSC_TREND_INDICATOR_CODE

# ── QMT 持仓股票 (2026-07-28 snapshot) ──
SYMBOLS = [
    ("600030.SH", "中信证券"),
    ("600036.SH", "招商银行"),
    ("600519.SH", "贵州茅台"),
    ("002594.SZ", "比亚迪"),
    ("000858.SZ", "五粮液"),
]

# ── 90 天范围: 2026-04-29 → 2026-07-28 (更多交易日产生更多信号) ──
END_DATE   = datetime(2026, 7, 28)
START_DATE = END_DATE - timedelta(days=90)

CAPITAL      = 100_000.0   # 10万
COMMISSION   = 0.001       # 万一
LEVERAGE     = 1


def fmt(val, suffix="", decimals=2):
    if val is None:
        return "N/A"
    return f"{val:+.{decimals}f}{suffix}" if suffix else f"{val:.{decimals}f}"


def run_one(service: BacktestService, symbol: str, name: str, timeframe: str) -> Optional[Dict[str, Any]]:
    print(f"\n{'─'*60}")
    print(f"  {symbol}  ({name})  timeframe={timeframe}")
    print(f"{'─'*60}")
    t0 = time.time()
    try:
        result = service.run(
            indicator_code=CZSC_TREND_INDICATOR_CODE,
            market="CNStock",
            symbol=symbol,
            timeframe=timeframe,
            start_date=START_DATE,
            end_date=END_DATE,
            initial_capital=CAPITAL,
            commission=COMMISSION,
            leverage=LEVERAGE,
            trade_direction="long",
            indicator_params={"trend_filter": 1},
        )
    except Exception as e:
        print(f"  ✗  Error: {e}")
        return None

    elapsed = time.time() - t0
    total_ret   = result.get("totalReturn")
    max_dd      = result.get("maxDrawdown")
    sharpe      = result.get("sharpeRatio")
    win_rate    = result.get("winRate")
    pf          = result.get("profitFactor")
    trades      = result.get("totalTrades", 0)
    pnl         = result.get("totalProfit")
    end_capital = result.get("endCapital", CAPITAL)
    bars        = len(result.get('trades', [])) or result.get('totalBars', 0)
    signal_diag = result.get('signalDiagnostics', {})

    print(f"  Trades={trades}  Time={elapsed:.1f}s")
    if signal_diag:
        print(f"  Signals: open_long={signal_diag.get('open_long',0)} close_long={signal_diag.get('close_long',0)}")
    print(f"  Return:      {fmt(total_ret, '%')}")
    print(f"  Max DD:      {fmt(max_dd, '%')}")
    print(f"  Sharpe:      {fmt(sharpe)}")
    print(f"  Win Rate:    {fmt(win_rate, '%')}")
    print(f"  Profit Fct:  {fmt(pf)}")
    print(f"  P&L:         ¥{fmt(pnl)}   End Capital: ¥{fmt(end_capital)}")
    return result


def main():
    parser = argparse.ArgumentParser(description="CNStock CZSC V3 30-day backtest")
    parser.add_argument("--timeframe", default="1D", help="K-line timeframe (default: 1D)")
    args = parser.parse_args()

    print("=" * 60)
    print("  CZSC V3 CNStock 30-Day Backtest")
    print(f"  Range:   {START_DATE.strftime('%Y-%m-%d')} → {END_DATE.strftime('%Y-%m-%d')}")
    print(f"  TF:      {args.timeframe}")
    print(f"  Capital: ¥{CAPITAL:,.0f}")
    print(f"  Comm:    {COMMISSION*100:.2f}%")
    print("=" * 60)

    service = BacktestService()
    results = []

    for symbol, name in SYMBOLS:
        r = run_one(service, symbol, name, args.timeframe)
        if r:
            results.append((symbol, name, r))
        time.sleep(0.5)   # throttle bridge

    # ── Summary table ──
    print("\n\n" + "=" * 60)
    print("  SUMMARY (30-Day CZSC V3)")
    print("=" * 60)
    print(f"{'Symbol':<12} {'Name':<10} {'Return':>10} {'MaxDD':>9} {'Sharpe':>8} {'WinRate':>9} {'Trades':>7}")
    print("─" * 70)
    for symbol, name, r in results:
        print(
            f"{symbol:<12} {name:<10} "
            f"{fmt(r.get('totalReturn'), '%'):>10} "
            f"{fmt(r.get('maxDrawdown'), '%'):>9} "
            f"{fmt(r.get('sharpeRatio')):>8} "
            f"{fmt(r.get('winRate'), '%'):>9} "
            f"{r.get('totalTrades', 0):>7}"
        )
    if not results:
        print("(no results)")


if __name__ == "__main__":
    main()
