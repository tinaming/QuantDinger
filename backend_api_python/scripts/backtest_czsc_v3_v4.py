"""
CZSC V3 vs V4 Backtest Comparison
==================================
Runs real backtests for V3 and V4 CZSC strategies on crypto data
and compares key metrics: total return, Sharpe, win rate, max drawdown, etc.

Usage:
    cd backend_api_python
    python scripts/backtest_czsc_v3_v4.py
    python scripts/backtest_czsc_v3_v4.py --symbol ETH/USDT --timeframe 4H
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

# Bootstrap
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.backtest import BacktestService
from tests.test_czsc_strategy_generation import (
    CZSC_TREND_INDICATOR_CODE,
    CZSC_CENTER_BREAKOUT_CODE,
    CZSC_V4_INDICATOR_CODE,
    CZSC_V4_RELAXED_INDICATOR_CODE,
)

# ─────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_TIMEFRAME = "1H"
DEFAULT_START = "2024-01-01"
DEFAULT_END = "2024-07-01"
DEFAULT_CAPITAL = 10000.0
DEFAULT_COMMISSION = 0.001
DEFAULT_LEVERAGE = 1


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def _fmt_float(val: Optional[float], decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def _safe_get(d: dict, key: str, default=None):
    v = d.get(key, default)
    if v is None:
        return default
    return v


def extract_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key metrics from backtest result dict."""
    return {
        "total_return": result.get("totalReturn"),
        "max_drawdown": result.get("maxDrawdown"),
        "sharpe": result.get("sharpeRatio"),
        "win_rate": result.get("winRate"),
        "profit_factor": result.get("profitFactor"),
        "total_trades": result.get("totalTrades", 0),
        "total_pnl": result.get("totalProfit"),
        "annual_return": result.get("annualReturn"),
        "total_commission": result.get("totalCommission"),
        "alpha_return": result.get("alphaReturn"),
        "benchmark_return": result.get("benchmarkReturn"),
    }


def run_backtest(
    service: BacktestService,
    indicator_code: str,
    indicator_params: Optional[Dict[str, Any]],
    label: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    initial_capital: float,
    commission: float,
    leverage: int,
    trade_direction: str = "both",
) -> Dict[str, Any]:
    """Run a single backtest and return metrics."""
    print(f"\n  Running: {label} ...", end=" ", flush=True)
    t0 = time.time()

    try:
        result = service.run(
            indicator_code=indicator_code,
            market="crypto",
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            commission=commission,
            slippage=0.0,
            leverage=leverage,
            trade_direction=trade_direction,
            indicator_params=indicator_params,
            strategy_config={
                "execution": {"signalTiming": "next_bar_open"},
            },
        )
        elapsed = time.time() - t0
        metrics = extract_metrics(result)
        metrics["elapsed"] = elapsed
        metrics["label"] = label
        metrics["error"] = None
        print(f"done ({elapsed:.1f}s)")
        return metrics
    except Exception as e:
        elapsed = time.time() - t0
        print(f"ERROR: {e}")
        return {
            "label": label, "error": str(e), "elapsed": elapsed,
            "total_return": None, "max_drawdown": None, "sharpe": None,
            "win_rate": None, "profit_factor": None, "total_trades": 0,
            "total_pnl": None, "annual_return": None,
            "total_commission": None, "alpha_return": None,
            "benchmark_return": None,
        }


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def print_separator(title: str = ""):
    print(f"\n{'=' * 72}")
    if title:
        print(f"  {title}")
        print(f"{'=' * 72}")


def print_metric_table(metrics_list: list, metric_keys: list):
    """Print a comparison table of metrics across runs."""
    # Header
    header = f"{'Run':<34s}"
    for key in metric_keys:
        header += f"  {key:>12s}"
    print(header)
    print("-" * len(header))

    for m in metrics_list:
        row = f"  {m['label']:<32s}"
        for key in metric_keys:
            val = m.get(key)
            if key in ("total_return", "max_drawdown", "win_rate"):
                row += f"  {_fmt_pct(val):>12s}"
            elif key == "total_trades":
                row += f"  {str(val) if val is not None else 'N/A':>12s}"
            else:
                row += f"  {_fmt_float(val):>12s}"
        print(row)


def main():
    parser = argparse.ArgumentParser(description="CZSC V3 vs V4 Backtest Comparison")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="Trading symbol")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME, help="Timeframe")
    parser.add_argument("--start", default=DEFAULT_START, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=DEFAULT_END, help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL, help="Initial capital")
    parser.add_argument("--commission", type=float, default=DEFAULT_COMMISSION, help="Commission rate")
    parser.add_argument("--leverage", type=int, default=DEFAULT_LEVERAGE, help="Leverage")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d")
    end_date = datetime.strptime(args.end, "%Y-%m-%d")

    print_separator(f"CZSC V3 vs V4 Backtest Comparison")
    print(f"  Symbol: {args.symbol}  Timeframe: {args.timeframe}")
    print(f"  Period: {args.start} ~ {args.end}")
    print(f"  Capital: {args.capital}  Commission: {args.commission}  Leverage: {args.leverage}")

    service = BacktestService()

    # ── Run all backtests ──
    all_metrics = []

    # V3: Trend Reversal (causal)
    m = run_backtest(
        service, CZSC_TREND_INDICATOR_CODE,
        {"trend_filter": 1},
        "V3 Trend Reversal (因果反转)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V3: Center Breakout
    m = run_backtest(
        service, CZSC_CENTER_BREAKOUT_CODE,
        {"min_level": 1},
        "V3 Center Breakout (中枢突破)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4: All off (V3 baseline)
    m = run_backtest(
        service, CZSC_V4_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 0, "center_narrow": 0,
         "divergence_filter": 0, "range_trade": 0},
        "V4 Baseline (all filters off)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4: +S1 only (breakout)
    m = run_backtest(
        service, CZSC_V4_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 1,
         "divergence_filter": 0, "range_trade": 0},
        "V4 +S1 (放量突破)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4: +S1+S2 (breakout + divergence)
    m = run_backtest(
        service, CZSC_V4_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 1,
         "divergence_filter": 1, "range_trade": 0},
        "V4 +S1+S2 (突破+背驰过滤)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4 Original: Full (S1+S2+S3, strict)
    m = run_backtest(
        service, CZSC_V4_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 1,
         "divergence_filter": 1, "range_trade": 1},
        "V4 Full (strict, +S3 range)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4 Relaxed: Baseline (S1 relaxed, S2 relaxed, S3 off)
    m = run_backtest(
        service, CZSC_V4_RELAXED_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 0,
         "divergence_filter": 1, "range_trade": 0},
        "V4R Baseline (S1 relaxed, S3 off)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4 Relaxed: S1 only (relaxed breakout, no divergence filter)
    m = run_backtest(
        service, CZSC_V4_RELAXED_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 0,
         "divergence_filter": 0, "range_trade": 0},
        "V4R +S1 only (relaxed breakout)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4 Relaxed: S1+S2 (relaxed breakout + relaxed divergence)
    m = run_backtest(
        service, CZSC_V4_RELAXED_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 0,
         "divergence_filter": 1, "range_trade": 0},
        "V4R +S1+S2 (relaxed two filters)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # V4 Relaxed: Full (S1+S2 relaxed + S3 range trade)
    m = run_backtest(
        service, CZSC_V4_RELAXED_INDICATOR_CODE,
        {"trend_filter": 1, "vol_confirm": 1, "center_narrow": 0,
         "divergence_filter": 1, "range_trade": 1},
        "V4R Full (+S3 range trade)",
        args.symbol, args.timeframe, start_date, end_date,
        args.capital, args.commission, args.leverage,
    )
    all_metrics.append(m)

    # ── Print comparison ──
    print_separator("BACKTEST RESULTS COMPARISON")

    metric_keys = ["total_return", "max_drawdown", "sharpe", "win_rate", "total_trades"]
    print_metric_table(all_metrics, metric_keys)

    # ── Scenario impact analysis ──
    print_separator("SCENARIO IMPACT ANALYSIS")

    v3_trend = all_metrics[0]
    v4_baseline = all_metrics[2]
    v4_s1 = all_metrics[3]
    v4_s12 = all_metrics[4]
    v4_full = all_metrics[5]
    v4r_baseline = all_metrics[6]
    v4r_s1 = all_metrics[7]
    v4r_s12 = all_metrics[8]
    v4r_full = all_metrics[9]

    def delta(prev, curr, key):
        pv = prev.get(key)
        cv = curr.get(key)
        if pv is None or cv is None:
            return "N/A"
        if key in ("total_return", "max_drawdown", "win_rate"):
            return f"{(cv - pv):+.2f}%"
        return f"{cv - pv:+.2f}"

    print(f"\n  [1] V3 -> V4 Original Baseline (all filters off):")
    print(f"    Return: {_fmt_pct(v3_trend['total_return'])} -> {_fmt_pct(v4_baseline['total_return'])}  (delta={delta(v3_trend, v4_baseline, 'total_return')})")
    print(f"    Trades: {v3_trend['total_trades']} -> {v4_baseline['total_trades']}")

    print(f"\n  [2] V4 Original +S1 (strict breakout):")
    print(f"    Return: {_fmt_pct(v4_s1['total_return'])}  Trades: {v4_s1['total_trades']}  Sharpe: {_fmt_float(v4_s1['sharpe'])}")

    print(f"\n  [3] V4 Original Full (S1+S2+S3, strict):")
    print(f"    Return: {_fmt_pct(v4_full['total_return'])}  Trades: {v4_full['total_trades']}  MaxDD: {_fmt_pct(v4_full['max_drawdown'])}")

    print(f"\n  --- RELAXED VERSION (S1: 1.2x vol, S2: 0.85x decay, S3: off) ---")

    print(f"\n  [4] V3 -> V4R Baseline (S1 relaxed, S3 off):")
    print(f"    Return: {_fmt_pct(v3_trend['total_return'])} -> {_fmt_pct(v4r_baseline['total_return'])}  (delta={delta(v3_trend, v4r_baseline, 'total_return')})")
    print(f"    Trades: {v3_trend['total_trades']} -> {v4r_baseline['total_trades']}")

    print(f"\n  [5] V4R +S1 only (relaxed breakout, no divergence):")
    print(f"    Return: {_fmt_pct(v4r_s1['total_return'])}  Trades: {v4r_s1['total_trades']}  Sharpe: {_fmt_float(v4r_s1['sharpe'])}")

    print(f"\n  [6] V4R +S1+S2 (relaxed breakout + divergence):")
    print(f"    Return: {_fmt_pct(v4r_s12['total_return'])}  Trades: {v4r_s12['total_trades']}  WinRate: {_fmt_pct(v4r_s12['win_rate'])}")

    print(f"\n  [7] V4R Full (+S3 range trade):")
    print(f"    Return: {_fmt_pct(v4r_full['total_return'])}  Trades: {v4r_full['total_trades']}  MaxDD: {_fmt_pct(v4r_full['max_drawdown'])}")

    print(f"\n  --- KEY COMPARISON ---")
    print(f"  V3 Trend Reversal           : {_fmt_pct(v3_trend['total_return'])}  trades={v3_trend['total_trades']}")
    print(f"  V4 Original Full (strict)   : {_fmt_pct(v4_full['total_return'])}  trades={v4_full['total_trades']}")
    print(f"  V4R Full (relaxed, S3 on)   : {_fmt_pct(v4r_full['total_return'])}  trades={v4r_full['total_trades']}")
    print(f"  V4R Baseline (relaxed,S3 off): {_fmt_pct(v4r_baseline['total_return'])}  trades={v4r_baseline['total_trades']}")

    # ── Final verdict ──
    print_separator("FINAL VERDICT")
    best = max(all_metrics, key=lambda m: m.get("total_return") or -999)
    best_sharpe = max(all_metrics, key=lambda m: m.get("sharpe") or -999)
    best_wr = max(all_metrics, key=lambda m: m.get("win_rate") or -999)

    print(f"  Best Return:   {best['label']} ({_fmt_pct(best['total_return'])})")
    print(f"  Best Sharpe:   {best_sharpe['label']} ({_fmt_float(best_sharpe['sharpe'])})")
    print(f"  Best Win Rate: {best_wr['label']} ({_fmt_pct(best_wr['win_rate'])})")

    v3_ret = v3_trend.get("total_return") or 0
    v4_ret = v4_full.get("total_return") or 0
    improvement = v4_ret - v3_ret
    print(f"\n  V3 -> V4 Full improvement: {_fmt_pct(improvement) if improvement is not None else 'N/A'}")
    print()


if __name__ == "__main__":
    main()