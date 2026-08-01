"""
V3 CZSC Batch Backtest — multi-symbol × multi-timeframe screening.

Usage:
    cd backend_api_python
    python scripts/backtest_czsc_batch.py
    python scripts/backtest_czsc_batch.py --timeframes 1H,4H
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.backtest import BacktestService
from app.services.backtest_execution import DEFAULT_SLIPPAGE
from tests.test_czsc_strategy_generation import CZSC_TREND_INDICATOR_CODE

# ── Test symbols (major USDT pairs on Gate.io) ──
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "POL/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT",
    "FIL/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "NEAR/USDT",
    "INJ/USDT", "SUI/USDT", "SEI/USDT", "TIA/USDT", "RUNE/USDT",
    "FET/USDT", "WIF/USDT", "PEPE/USDT", "RENDER/USDT", "TAO/USDT",
    "TRX/USDT", "STRK/USDT", "AAVE/USDT", "VET/USDT", "CRV/USDT",
    "WLD/USDT", "ORDI/USDT", "STX/USDT", "IMX/USDT", "GRT/USDT",
]

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1H", "4H"]
# Gate.io: max 10000 bars lookback. Lower TFs use shorter (recent) windows.
# End date is ~3 days before now to ensure completed candles only.
DATE_RANGE = {
    "1m":  (datetime(2026, 7, 21), datetime(2026, 7, 26)),  # 5d,   ~7200 bars
    "5m":  (datetime(2026, 6, 23), datetime(2026, 7, 26)),  # 33d,  ~9504 bars
    "15m": (datetime(2026, 4, 15), datetime(2026, 7, 26)),  # 102d, ~9792 bars
    "30m": (datetime(2026, 1, 1),  datetime(2026, 7, 29)),  # 209d, ~10000 bars
    "1H":  (datetime(2025, 7, 1),  datetime(2026, 1, 1)),   # 184d, ~4416 bars (cached)
    "4H":  (datetime(2025, 7, 1),  datetime(2026, 1, 1)),   # 184d, ~1104 bars (cached)
}
CAPITAL = 10000.0
COMMISSION = 0.001
LEVERAGE = 1


def run_one(
    service,
    symbol,
    tf,
    start_date,
    end_date,
    *,
    strict: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run V3 backtest, return metrics or None on failure."""
    try:
        # Live-aligned path: closed-bar confirm + next_bar_open (+ default slippage).
        # Loose path keeps prior screening semantics (0 slippage, explicit next_bar_open).
        if strict:
            result = service.run_aligned(
                strict_mode=True,
                indicator_code=CZSC_TREND_INDICATOR_CODE,
                market="crypto", symbol=symbol, timeframe=tf,
                start_date=start_date, end_date=end_date,
                initial_capital=CAPITAL, commission=COMMISSION,
                slippage=DEFAULT_SLIPPAGE, leverage=LEVERAGE, trade_direction="both",
                indicator_params={"trend_filter": 1},
                strategy_config={
                    "signal_mode": "confirmed",
                    "exit_signal_mode": "confirmed",
                    "strict_mode": True,
                },
            )
        else:
            result = service.run(
                indicator_code=CZSC_TREND_INDICATOR_CODE,
                market="crypto", symbol=symbol, timeframe=tf,
                start_date=start_date, end_date=end_date,
                initial_capital=CAPITAL, commission=COMMISSION,
                slippage=0.0, leverage=LEVERAGE, trade_direction="both",
                indicator_params={"trend_filter": 1},
                strategy_config={"execution": {"signalTiming": "next_bar_open"}},
            )
        if isinstance(result, dict) and result.get("error"):
            return {
                "symbol": symbol, "tf": tf, "error": str(result["error"]),
                "total_trades": 0, "strict_mode": strict,
            }
        ea = (result or {}).get("executionAssumptions") or {}
        return {
            "symbol": symbol,
            "tf": tf,
            "strict_mode": strict,
            "total_return": result.get("totalReturn"),
            "max_drawdown": result.get("maxDrawdown"),
            "sharpe": result.get("sharpeRatio"),
            "win_rate": result.get("winRate"),
            "profit_factor": result.get("profitFactor"),
            "total_trades": result.get("totalTrades", 0),
            "total_pnl": result.get("totalProfit"),
            "annual_return": result.get("annualReturn"),
            "benchmark_return": result.get("benchmarkReturn"),
            "fill_rule": ea.get("fillRule"),
            "simulation_mode": ea.get("simulationMode"),
            "elapsed": 0,
            "error": None,
        }
    except Exception as e:
        return {
            "symbol": symbol, "tf": tf, "error": str(e),
            "total_trades": 0, "strict_mode": strict,
        }


def main():
    # Load backend .env so DATABASE_URL / exchange keys are available for kline cache.
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(_BACKEND_DIR, ".env"))
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframes", default="1m,5m,15m,30m,1H,4H")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument(
        "--strict", action="store_true",
        help="Live-aligned: run_aligned(strict_mode=True), confirmed signals, default slippage",
    )
    args = parser.parse_args()

    tfs = [t.strip() for t in args.timeframes.split(",")]
    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols else SYMBOLS
    )
    strict = bool(args.strict)

    service = BacktestService()
    results: List[Dict] = []
    total = len(symbols) * len(tfs)
    done = 0

    mode_label = "STRICT (live-aligned)" if strict else "screening"
    slip = DEFAULT_SLIPPAGE if strict else 0.0
    print(f"V3 CZSC Batch Backtest [{mode_label}]: {len(symbols)} symbols x {len(tfs)} timeframes = {total} runs", flush=True)
    print(f"Periods: { {tf: f'{s.date()}~{e.date()}' for tf, (s, e) in DATE_RANGE.items() if tf in tfs} }", flush=True)
    print(f"Capital: ${CAPITAL:,.0f} | Lev: {LEVERAGE}x | Comm: {COMMISSION*100:.1f}% | Slip: {slip*100:.2f}%", flush=True)
    print(f"DB cache: {'on' if os.getenv('DATABASE_URL') else 'off (DATABASE_URL missing)'}", flush=True)
    print("=" * 110, flush=True)

    for symbol in symbols:
        for tf in tfs:
            done += 1
            start_date, end_date = DATE_RANGE[tf]
            ts = time.time()
            r = run_one(service, symbol, tf, start_date, end_date, strict=strict)
            r["elapsed"] = time.time() - ts

            # Retry once on rate-limit failures
            if r.get("error") and "No candle" in str(r.get("error", "")):
                time.sleep(30)
                ts2 = time.time()
                r = run_one(service, symbol, tf, start_date, end_date, strict=strict)
                r["elapsed"] = time.time() - ts2 + r.get("elapsed", 0)

            results.append(r)

            if r.get("error"):
                status = f"[FAIL] {r['error'][:50]}"
            else:
                trades = r.get("total_trades", 0)
                ret = r.get("total_return")
                status = f"[OK] {trades} trades, ret={ret:+.1f}%" if ret is not None else "[OK] 0 trades"
            print(f"  [{done:3d}/{total}] {symbol:14s} {tf:3s}  {status}  ({r['elapsed']:.1f}s)", flush=True)

            # Rate-limit gate between exchange fetches
            time.sleep(1)

    # ── Rank by total_return ──
    valid = [r for r in results if r.get("error") is None and r.get("total_trades", 0) >= args.min_trades]
    valid.sort(key=lambda r: r.get("total_return") or -999, reverse=True)

    print("\n" + "=" * 110)
    print(f"Ranked by Total Return ({len(valid)} valid, >= {args.min_trades} trades)")
    print(f"{'Rank':>4}  {'Symbol':<14} {'TF':>4}  {'Return':>8}  {'Drawdown':>8}  {'Sharpe':>7}  "
          f"{'Win%':>6}  {'Trades':>6}  {'PF':>6}  {'Bench':>8}")
    print("-" * 110)

    for i, r in enumerate(valid, 1):
        def pct(v): return f"{v:+.1f}%" if v is not None else "N/A"
        def f2(v): return f"{v:.2f}" if v is not None else "N/A"
        print(f"  {i:3d}  {r['symbol']:<14} {r['tf']:>4}  {pct(r['total_return']):>8}  "
              f"{pct(r['max_drawdown']):>8}  {f2(r['sharpe']):>7}  "
              f"{pct(r['win_rate']):>6}  {r['total_trades']:>6}  "
              f"{f2(r['profit_factor']):>6}  {pct(r['benchmark_return']):>8}")

    # ── Summary by timeframe ──
    print(f"\n--- By Timeframe ---")
    for tf in tfs:
        subset = [r for r in valid if r["tf"] == tf]
        if subset:
            avg_ret = sum(r["total_return"] for r in subset if r["total_return"]) / len(subset)
            avg_sharpe = sum(r["sharpe"] for r in subset if r["sharpe"]) / len(subset)
            avg_trades = sum(r["total_trades"] for r in subset) / len(subset)
            print(f"  {tf}: {len(subset)} symbols, avg return={avg_ret:+.1f}%, "
                  f"avg sharpe={avg_sharpe:.2f}, avg trades={avg_trades:.1f}")

    # ── Failed ──
    failed = [r for r in results if r.get("error")]
    if failed:
        print(f"\n--- Failed ({len(failed)}) ---")
        for r in failed:
            print(f"  {r['symbol']} {r['tf']}: {r['error'][:80]}")

    # ── Persist artifact ──
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tf_tag = "-".join(tfs)
    mode_tag = "strict" if strict else "screen"
    out_path = os.path.join(_REPO_ROOT, f"backtest_czsc_v3_{mode_tag}_{tf_tag}_{stamp}.json")
    artifact = {
        "strategy": "CZSC_V3_Trend_Reversal",
        "strict_mode": strict,
        "indicator_params": {"trend_filter": 1},
        "execution": {
            "signalTiming": "next_bar_open",
            "signal_mode": "confirmed" if strict else None,
            "exit_signal_mode": "confirmed" if strict else None,
            "slippage": slip,
        },
        "capital": CAPITAL,
        "commission": COMMISSION,
        "leverage": LEVERAGE,
        "trade_direction": "both",
        "timeframes": tfs,
        "date_range": {
            tf: {"start": DATE_RANGE[tf][0].isoformat(), "end": DATE_RANGE[tf][1].isoformat()}
            for tf in tfs if tf in DATE_RANGE
        },
        "symbols": symbols,
        "min_trades": args.min_trades,
        "results": results,
        "ranked": valid,
        "failed_count": len(failed),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nWrote artifact: {out_path}", flush=True)


if __name__ == "__main__":
    main()