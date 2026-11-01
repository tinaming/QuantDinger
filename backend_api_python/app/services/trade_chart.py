"""
Trade chart visualization service.

Generates a self-contained HTML page using Apache ECharts
to display K-line candlesticks with trade markers overlaid.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Trade type classification
# ---------------------------------------------------------------------------

_OPEN_TYPES = frozenset({
    "open_long", "open_short",
    "add_long", "add_short",
})

_CLOSE_TYPES = frozenset({
    "close_long", "close_short",
    "close_long_stop", "close_short_stop",
    "close_long_trailing", "close_short_trailing",
    "close_long_profit", "close_short_profit",
    "reduce_long", "reduce_short",
    "liquidation",
})


def _is_entry(trade_type: str) -> bool:
    t = (trade_type or "").lower()
    if t in _OPEN_TYPES:
        return True
    return t.startswith("open_") or t.startswith("add_")


def _is_exit(trade_type: str) -> bool:
    t = (trade_type or "").lower()
    if t in _CLOSE_TYPES:
        return True
    return t.startswith("close_") or t == "liquidation"


def _trade_side(trade_type: str) -> str:
    """Return 'long' or 'short' from trade type string."""
    t = (trade_type or "").lower()
    if "short" in t:
        return "short"
    return "long"


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_trade_time(raw: Any) -> Optional[int]:
    """Convert a trade time value to a Unix timestamp (seconds)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = int(raw)
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    try:
        ts = int(float(s))
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    except Exception:
        pass
    return None


def _normalize_kline_time(raw: Any) -> Optional[int]:
    """Convert a kline time value to a Unix timestamp (seconds)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = int(raw)
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    try:
        ts = int(float(s))
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Candle data normalization
# ---------------------------------------------------------------------------

def _prepare_candles(klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw kline rows to candle data."""
    candles = []
    for row in klines:
        ts = _normalize_kline_time(row.get("time") or row.get("timestamp") or row.get("dt"))
        if ts is None:
            continue
        try:
            candles.append({
                "time": ts,
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
            })
        except Exception:
            continue
    candles.sort(key=lambda c: c["time"])
    return candles


def _prepare_markers(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert trade rows to ECharts markPoint objects."""
    markers = []
    for trade in trades:
        ts = _parse_trade_time(trade.get("time") or trade.get("created_at") or trade.get("timestamp"))
        if ts is None:
            continue
        trade_type = str(trade.get("type") or "")
        price = float(trade.get("price") or 0)
        profit = float(trade.get("profit") or 0)
        amount = float(trade.get("amount") or trade.get("size") or 0)
        side = _trade_side(trade_type)
        entry = _is_entry(trade_type)
        exit_ = _is_exit(trade_type)

        # Color / symbol
        if entry and side == "long":
            color = "#22c55e"
            symbol = "pin"
            symbol_rotate = 0
            label = "买入"
        elif entry and side == "short":
            color = "#ef4444"
            symbol = "pin"
            symbol_rotate = 180
            label = "做空"
        elif exit_ and profit >= 0:
            color = "#22c55e"
            symbol = "pin"
            symbol_rotate = 180
            label = "平多" if side == "long" else "平空"
        elif exit_:
            color = "#ef4444"
            symbol = "pin"
            symbol_rotate = 0
            label = "平多" if side == "long" else "平空"
        else:
            color = "#60a5fa"
            symbol = "circle"
            symbol_rotate = 0
            label = trade_type or "操作"

        pnl_str = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"
        if price >= 1000:
            price_str = f"{price:,.0f}"
        elif price >= 1:
            price_str = f"{price:.2f}"
        else:
            price_str = f"{price:.4f}"
        text = f"{label} {price_str} | {pnl_str}"

        markers.append({
            "time": ts,
            "coord": [ts, price],
            "value": text,
            "symbol": symbol,
            "symbolRotate": symbol_rotate,
            "itemStyle": {"color": color},
            "label": {"show": True, "position": "bottom" if entry else "top", "color": color, "fontSize": 10},
            "_type": trade_type,
            "_price": price,
            "_amount": amount,
            "_profit": profit,
        })
    markers.sort(key=lambda m: m["time"])
    return markers


def _prepare_trade_table(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build table rows for the trade list below the chart."""
    rows = []
    for i, trade in enumerate(trades, 1):
        ts = _parse_trade_time(trade.get("time") or trade.get("created_at") or trade.get("timestamp"))
        trade_type = str(trade.get("type") or "")
        price = float(trade.get("price") or 0)
        amount = float(trade.get("amount") or trade.get("size") or 0)
        profit = float(trade.get("profit") or 0)
        balance = float(trade.get("balance") or 0)
        side = _trade_side(trade_type)
        entry = _is_entry(trade_type)

        time_str = ""
        if ts is not None:
            try:
                time_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except Exception:
                time_str = str(trade.get("time") or "")

        direction = ""
        if entry:
            direction = "开多" if side == "long" else "开空"
        elif _is_exit(trade_type):
            direction = "平多" if side == "long" else "平空"
        else:
            direction = trade_type

        rows.append({
            "index": i,
            "time": time_str,
            "direction": direction,
            "type": trade_type,
            "price": price,
            "amount": amount,
            "profit": profit,
            "balance": balance,
            "side": side,
            "_ts": ts,
        })
    return rows


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def _build_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute basic summary from the trade list."""
    exits = [t for t in trades if _is_exit(str(t.get("type") or ""))]
    profits = [float(t.get("profit") or 0) for t in exits]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    total_pnl = sum(profits)
    win_rate = len(wins) / len(profits) * 100 if profits else 0.0
    max_win = max(profits) if profits else 0.0
    max_loss = min(profits) if profits else 0.0
    return {
        "total_trades": len(exits),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
    }


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _calculate_rsi(candles: List[Dict], period: int = 14) -> List[Dict]:
    """Calculate RSI from candle data."""
    if len(candles) < period + 1:
        return []
    rsi_data = []
    gains = []
    losses = []
    for i in range(1, len(candles)):
        change = candles[i]['close'] - candles[i-1]['close']
        gains.append(max(0, change))
        losses.append(max(0, -change))
        if i >= period:
            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            rsi_data.append({'time': candles[i]['time'], 'value': rsi})
    return rsi_data


def _calculate_kdj(candles: List[Dict], period: int = 9, k_smooth: int = 3, d_smooth: int = 3) -> List[Dict]:
    """Calculate KDJ from candle data."""
    if len(candles) < period:
        return []
    kdj_data = []
    k = 50
    d = 50
    for i in range(period - 1, len(candles)):
        window = candles[i-period+1:i+1]
        low = min(c['low'] for c in window)
        high = max(c['high'] for c in window)
        if high == low:
            rsv = 50
        else:
            rsv = (candles[i]['close'] - low) / (high - low) * 100
        k = (2/3) * k + (1/3) * rsv
        d = (2/3) * d + (1/3) * k
        j = 3 * k - 2 * d
        kdj_data.append({'time': candles[i]['time'], 'k': k, 'd': d, 'j': j})
    return kdj_data


def _calculate_bollinger_bands(candles: List[Dict], period: int = 20, std_dev: float = 2.0) -> Dict[str, List[Dict]]:
    """Calculate Bollinger Bands (upper, middle, lower) from candle data."""
    if len(candles) < period:
        return {'upper': [], 'middle': [], 'lower': []}
    upper, middle, lower = [], [], []
    for i in range(period - 1, len(candles)):
        window = [candles[j]['close'] for j in range(i - period + 1, i + 1)]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = variance ** 0.5
        upper.append({'time': candles[i]['time'], 'value': sma + std_dev * std})
        middle.append({'time': candles[i]['time'], 'value': sma})
        lower.append({'time': candles[i]['time'], 'value': sma - std_dev * std})
    return {'upper': upper, 'middle': middle, 'lower': lower}


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"


def build_chart_html(
    klines: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    *,
    symbol: str = "",
    timeframe: str = "",
    theme: str = "dark",
    result_id: Optional[int] = None,
    backend_url: str = "",
) -> str:
    """
    Build a self-contained HTML page with:
      - ECharts candlestick chart
      - Trade markers overlaid
      - RSI and KDJ indicators
      - Timeframe selector
      - Toggle for trade markers
      - Summary stats card
      - Trade detail table
    """
    candles = _prepare_candles(klines)
    markers = _prepare_markers(trades)
    table_rows = _prepare_trade_table(trades)
    summary = _build_summary(trades)
    rsi_data = _calculate_rsi(candles)
    kdj_data = _calculate_kdj(candles)
    bb_data = _calculate_bollinger_bands(candles)

    # Prepare data for ECharts
    # ECharts candlestick expects [open, close, low, high] for each data point
    candle_times = [c['time'] * 1000 for c in candles]  # Convert to milliseconds
    candle_values = [[c['open'], c['close'], c['low'], c['high']] for c in candles]

    # Prepare markPoint data
    mark_points = []
    for m in markers:
        mark_points.append({
            "coord": [m['time'] * 1000, m['_price']],
            "value": m['value'],
            "symbol": m['symbol'],
            "symbolRotate": m['symbolRotate'],
            "itemStyle": m['itemStyle'],
            "label": m['label'],
        })

    # Prepare RSI data
    rsi_times = [d['time'] * 1000 for d in rsi_data]
    rsi_values = [d['value'] for d in rsi_data]

    # Prepare KDJ data
    kdj_times = [d['time'] * 1000 for d in kdj_data]
    k_values = [d['k'] for d in kdj_data]
    d_values = [d['d'] for d in kdj_data]
    j_values = [d['j'] for d in kdj_data]

    # Prepare BB data
    bb_upper_values = [[d['time'] * 1000, d['value']] for d in bb_data.get('upper', [])]
    bb_middle_values = [[d['time'] * 1000, d['value']] for d in bb_data.get('middle', [])]
    bb_lower_values = [[d['time'] * 1000, d['value']] for d in bb_data.get('lower', [])]

    candles_json = json.dumps(candle_times, ensure_ascii=False)
    candle_values_json = json.dumps(candle_values, ensure_ascii=False)
    mark_points_json = json.dumps(mark_points, ensure_ascii=False)
    table_json = json.dumps(table_rows, ensure_ascii=False)
    summary_json = json.dumps(summary, ensure_ascii=False)
    rsi_times_json = json.dumps(rsi_times, ensure_ascii=False)
    rsi_values_json = json.dumps(rsi_values, ensure_ascii=False)
    kdj_times_json = json.dumps(kdj_times, ensure_ascii=False)
    k_values_json = json.dumps(k_values, ensure_ascii=False)
    d_values_json = json.dumps(d_values, ensure_ascii=False)
    j_values_json = json.dumps(j_values, ensure_ascii=False)
    bb_upper_json = json.dumps(bb_upper_values, ensure_ascii=False)
    bb_middle_json = json.dumps(bb_middle_values, ensure_ascii=False)
    bb_lower_json = json.dumps(bb_lower_values, ensure_ascii=False)

    title = f"{symbol or '策略'} · {timeframe or ''} · 交易复盘".strip(" ·")

    html = f"""<!DOCTYPE html>
<html lang="zh-cmn-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — ChanQuant</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: #0b1120;
    color: #f8fafc;
  }}
  .header {{
    padding: 16px 24px;
    border-bottom: 1px solid rgba(148,163,184,0.15);
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }}
  .header h1 {{
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
  }}
  .header .subtitle {{
    font-size: 13px;
    color: #94a3b8;
  }}
  .stats-bar {{
    display: flex;
    gap: 12px;
    padding: 12px 24px;
    flex-wrap: wrap;
    border-bottom: 1px solid rgba(148,163,184,0.1);
  }}
  .stat-card {{
    background: rgba(30,41,59,0.7);
    border: 1px solid rgba(148,163,184,0.12);
    border-radius: 10px;
    padding: 10px 16px;
    min-width: 100px;
  }}
  .stat-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
  .stat-value {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
  .stat-value.positive {{ color: #22c55e; }}
  .stat-value.negative {{ color: #ef4444; }}
  .stat-value.neutral  {{ color: #60a5fa; }}
  .controls {{
    padding: 12px 24px;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
    border-bottom: 1px solid rgba(148,163,184,0.1);
  }}
  .controls label {{ font-size: 12px; color: #94a3b8; }}
  .tf-btn {{
    background: rgba(30,41,59,0.7);
    border: 1px solid rgba(148,163,184,0.2);
    color: #cbd5e1;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
  }}
  .tf-btn:hover {{ background: rgba(59,130,246,0.2); }}
  .tf-btn.active {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
  .toggle-btn {{
    background: rgba(30,41,59,0.7);
    border: 1px solid rgba(148,163,184,0.2);
    color: #cbd5e1;
    padding: 6px 12px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    margin-left: auto;
  }}
  .toggle-btn:hover {{ background: rgba(59,130,246,0.2); }}
  .toggle-btn.active {{ background: #22c55e; color: white; border-color: #22c55e; }}
  #chart-container {{
    width: 100%;
    height: 480px;
    padding: 8px 12px;
  }}
  .indicator-panel {{
    width: 100%;
    height: 200px;
    padding: 8px 12px;
    border-top: 1px solid rgba(148,163,184,0.1);
  }}
  .table-section {{
    padding: 16px 24px;
  }}
  .table-section h2 {{
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 10px;
    color: #cbd5e1;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  thead th {{
    text-align: left;
    padding: 8px 10px;
    border-bottom: 1px solid rgba(148,163,184,0.2);
    color: #94a3b8;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    cursor: pointer;
    user-select: none;
  }}
  thead th:hover {{ color: #f8fafc; }}
  tbody tr {{
    border-bottom: 1px solid rgba(148,163,184,0.08);
    transition: background 0.12s;
  }}
  tbody tr:hover {{ background: rgba(59,130,246,0.08); }}
  tbody td {{
    padding: 7px 10px;
    color: #e2e8f0;
  }}
  .dir-long {{ color: #22c55e; font-weight: 600; }}
  .dir-short {{ color: #ef4444; font-weight: 600; }}
  .pnl-pos {{ color: #22c55e; }}
  .pnl-neg {{ color: #ef4444; }}
  .sort-arrow {{ margin-left: 4px; font-size: 10px; }}
  .empty-state {{
    text-align: center;
    padding: 48px;
    color: #64748b;
    font-size: 14px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>{title}</h1>
  <span class="subtitle">Generated by ChanQuant · ECharts</span>
</div>

<div class="stats-bar" id="stats-bar"></div>

<div class="controls">
  <label>时间周期:</label>
  <button class="tf-btn" data-tf="1m">1m</button>
  <button class="tf-btn" data-tf="5m">5m</button>
  <button class="tf-btn" data-tf="15m">15m</button>
  <button class="tf-btn" data-tf="30m">30m</button>
  <button class="tf-btn" data-tf="1H">1H</button>
  <button class="tf-btn" data-tf="4H">4H</button>
  <button class="tf-btn active" data-tf="{timeframe or '1D'}">{timeframe or '1D'}</button>
  <button class="tf-btn" data-tf="1W">1W</button>
  <button class="toggle-btn active" id="toggle-markers">显示交易标记</button>
</div>

<div id="chart-container"></div>
<div class="indicator-panel" id="rsi-container"></div>
<div class="indicator-panel" id="kdj-container"></div>

<div class="table-section">
  <h2>交易明细</h2>
  <table id="trade-table">
    <thead>
      <tr>
        <th data-col="index">#</th>
        <th data-col="time">时间</th>
        <th data-col="direction">方向</th>
        <th data-col="price">成交价</th>
        <th data-col="amount">数量</th>
        <th data-col="profit">盈亏</th>
        <th data-col="balance">账户余额</th>
      </tr>
    </thead>
    <tbody id="trade-tbody"></tbody>
  </table>
</div>

<script src="{_ECHARTS_CDN}"></script>
<script>
(function() {{
  // ---- Data ----
  const candleTimes = {candles_json};
  const candleValues = {candle_values_json};
  const markPoints = {mark_points_json};
  const tableData = {table_json};
  const summary = {summary_json};
  const rsiTimes = {rsi_times_json};
  const rsiValues = {rsi_values_json};
  const kdjTimes = {kdj_times_json};
  const kValues = {k_values_json};
  const dValues = {d_values_json};
  const jValues = {j_values_json};
  const bbUpper = {bb_upper_json};
  const bbMiddle = {bb_middle_json};
  const bbLower = {bb_lower_json};
  let markersVisible = true;
  const backendUrl = "{backend_url}";

  // ---- Stats bar ----
  const statsEl = document.getElementById('stats-bar');
  const statItems = [
    {{ label: '总交易次数', value: summary.total_trades, cls: 'neutral' }},
    {{ label: '胜率', value: summary.win_rate + '%', cls: summary.win_rate >= 50 ? 'positive' : 'negative' }},
    {{ label: '总盈亏', value: (summary.total_pnl >= 0 ? '+' : '') + summary.total_pnl.toFixed(2), cls: summary.total_pnl >= 0 ? 'positive' : 'negative' }},
    {{ label: '最大盈利', value: '+' + summary.max_win.toFixed(2), cls: 'positive' }},
    {{ label: '最大亏损', value: summary.max_loss.toFixed(2), cls: 'negative' }},
    {{ label: '盈利次数', value: summary.wins, cls: 'positive' }},
    {{ label: '亏损次数', value: summary.losses, cls: 'negative' }},
  ];
  statsEl.innerHTML = statItems.map(s => `
    <div class="stat-card">
      <div class="stat-label">${{s.label}}</div>
      <div class="stat-value ${{s.cls}}">${{s.value}}</div>
    </div>
  `).join('');

  // ---- Charts ----
  let mainChart = null;
  let rsiChart = null;
  let kdjChart = null;

  if (!candleValues.length) {{
    document.getElementById('chart-container').innerHTML =
      '<div class="empty-state">暂无 K 线数据，无法渲染图表</div>';
  }} else {{
    const chartContainer = document.getElementById('chart-container');
    const rsiContainer = document.getElementById('rsi-container');
    const kdjContainer = document.getElementById('kdj-container');

    // Main chart
    mainChart = echarts.init(chartContainer);
    const mainOption = {{
      backgroundColor: '#0b1120',
      animation: false,
      tooltip: {{
        trigger: 'axis',
        axisPointer: {{ type: 'cross' }},
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        borderColor: '#334155',
        textStyle: {{ color: '#e2e8f0' }},
      }},
      axisPointer: {{
        link: [{{ xAxisIndex: 'all' }}],
        label: {{ backgroundColor: '#334155' }},
      }},
      grid: [
        {{ left: '8%', right: '8%', top: '8%', height: '85%' }},
      ],
      xAxis: {{
        type: 'time',
        boundaryGap: true,
        axisLine: {{ lineStyle: {{ color: '#475569' }} }},
        axisLabel: {{ color: '#94a3b8' }},
        splitLine: {{ show: false }},
      }},
      yAxis: {{
        scale: true,
        position: 'right',
        axisLine: {{ lineStyle: {{ color: '#475569' }} }},
        axisLabel: {{ color: '#94a3b8' }},
        splitLine: {{ lineStyle: {{ color: 'rgba(71, 85, 105, 0.2)' }} }},
      }},
      dataZoom: [
        {{
          type: 'inside',
          xAxisIndex: [0],
          start: 0,
          end: 100,
        }},
        {{
          type: 'slider',
          xAxisIndex: [0],
          bottom: 10,
          height: 20,
          borderColor: '#334155',
          fillerColor: 'rgba(59, 130, 246, 0.2)',
          handleStyle: {{ color: '#3b82f6' }},
          textStyle: {{ color: '#94a3b8' }},
        }},
      ],
      series: [
        {{
          name: 'K 线',
          type: 'candlestick',
          data: candleValues.map((v, i) => [candleTimes[i], v]),
          itemStyle: {{
            color: '#22c55e',
            color0: '#ef4444',
            borderColor: '#22c55e',
            borderColor0: '#ef4444',
          }},
          markPoint: {{
            symbol: 'pin',
            symbolSize: 50,
            data: markPoints,
          }},
        }},
      ],
    }};

    // Add Bollinger Bands if available
    if (bbUpper.length > 0) {{
      mainOption.series.push(
        {{
          name: 'BB 上轨',
          type: 'line',
          data: bbUpper,
          showSymbol: false,
          lineStyle: {{ color: '#f97316', width: 1 }},
        }},
        {{
          name: 'BB 中轨',
          type: 'line',
          data: bbMiddle,
          showSymbol: false,
          lineStyle: {{ color: '#94a3b8', width: 1, type: 'dashed' }},
        }},
        {{
          name: 'BB 下轨',
          type: 'line',
          data: bbLower,
          showSymbol: false,
          lineStyle: {{ color: '#f97316', width: 1 }},
        }}
      );
    }}

    mainChart.setOption(mainOption);

    // RSI chart
    if (rsiValues.length > 0) {{
      rsiChart = echarts.init(rsiContainer);
      rsiChart.setOption({{
        backgroundColor: '#0b1120',
        animation: false,
        tooltip: {{
          trigger: 'axis',
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          borderColor: '#334155',
          textStyle: {{ color: '#e2e8f0' }},
        }},
        grid: {{ left: '8%', right: '8%', top: '10%', bottom: '20%' }},
        xAxis: {{
          type: 'time',
          axisLine: {{ lineStyle: {{ color: '#475569' }} }},
          axisLabel: {{ color: '#94a3b8' }},
          splitLine: {{ show: false }},
        }},
        yAxis: {{
          scale: true,
          position: 'right',
          min: 0,
          max: 100,
          axisLine: {{ lineStyle: {{ color: '#475569' }} }},
          axisLabel: {{ color: '#94a3b8' }},
          splitLine: {{ lineStyle: {{ color: 'rgba(71, 85, 105, 0.2)' }} }},
        }},
        dataZoom: [
          {{
            type: 'inside',
            xAxisIndex: [0],
            start: 0,
            end: 100,
          }},
        ],
        series: [
          {{
            name: 'RSI',
            type: 'line',
            data: rsiValues.map((v, i) => [rsiTimes[i], v]),
            showSymbol: false,
            lineStyle: {{ color: '#a855f7', width: 2 }},
            markLine: {{
              silent: true,
              lineStyle: {{ color: '#475569', type: 'dashed' }},
              data: [
                {{ yAxis: 70 }},
                {{ yAxis: 30 }},
              ],
            }},
          }},
        ],
      }});
    }}

    // KDJ chart
    if (kValues.length > 0) {{
      kdjChart = echarts.init(kdjContainer);
      kdjChart.setOption({{
        backgroundColor: '#0b1120',
        animation: false,
        tooltip: {{
          trigger: 'axis',
          backgroundColor: 'rgba(15, 23, 42, 0.9)',
          borderColor: '#334155',
          textStyle: {{ color: '#e2e8f0' }},
        }},
        grid: {{ left: '8%', right: '8%', top: '10%', bottom: '20%' }},
        xAxis: {{
          type: 'time',
          axisLine: {{ lineStyle: {{ color: '#475569' }} }},
          axisLabel: {{ color: '#94a3b8' }},
          splitLine: {{ show: false }},
        }},
        yAxis: {{
          scale: true,
          position: 'right',
          axisLine: {{ lineStyle: {{ color: '#475569' }} }},
          axisLabel: {{ color: '#94a3b8' }},
          splitLine: {{ lineStyle: {{ color: 'rgba(71, 85, 105, 0.2)' }} }},
        }},
        dataZoom: [
          {{
            type: 'inside',
            xAxisIndex: [0],
            start: 0,
            end: 100,
          }},
        ],
        series: [
          {{
            name: 'K',
            type: 'line',
            data: kValues.map((v, i) => [kdjTimes[i], v]),
            showSymbol: false,
            lineStyle: {{ color: '#3b82f6', width: 2 }},
          }},
          {{
            name: 'D',
            type: 'line',
            data: dValues.map((v, i) => [kdjTimes[i], v]),
            showSymbol: false,
            lineStyle: {{ color: '#f59e0b', width: 2 }},
          }},
          {{
            name: 'J',
            type: 'line',
            data: jValues.map((v, i) => [kdjTimes[i], v]),
            showSymbol: false,
            lineStyle: {{ color: '#ec4899', width: 2 }},
          }},
        ],
      }});
    }}

    // Link charts for synchronized zoom
    if (rsiChart) echarts.connect([mainChart, rsiChart]);
    if (kdjChart) echarts.connect([mainChart, kdjChart]);

    // Handle resize
    window.addEventListener('resize', () => {{
      mainChart && mainChart.resize();
      rsiChart && rsiChart.resize();
      kdjChart && kdjChart.resize();
    }});
  }}

  // ---- Toggle Markers ----
  const toggleBtn = document.getElementById('toggle-markers');
  if (toggleBtn && mainChart) {{
    toggleBtn.addEventListener('click', () => {{
      markersVisible = !markersVisible;
      toggleBtn.classList.toggle('active', markersVisible);
      toggleBtn.textContent = markersVisible ? '显示交易标记' : '隐藏交易标记';
      mainChart.setOption({{
        series: [{{
          markPoint: {{
            data: markersVisible ? markPoints : [],
          }},
        }}],
      }});
    }});
  }}

  // ---- Trade Table ----
  function renderTable(data) {{
    const tbody = document.getElementById('trade-tbody');
    tbody.innerHTML = data.map(r => {{
      const dirClass = r.direction.includes('多') ? 'dir-long' : 'dir-short';
      const pnlClass = r.profit > 0 ? 'pnl-pos' : (r.profit < 0 ? 'pnl-neg' : '');
      const pnlStr = r.profit > 0 ? '+' + r.profit.toFixed(2) : r.profit.toFixed(2);
      return `<tr data-time="${{r._ts || ''}}" data-index="${{r.index}}">
        <td>${{r.index}}</td>
        <td>${{r.time}}</td>
        <td class="${{dirClass}}">${{r.direction}}</td>
        <td>${{r.price.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 4}})}}</td>
        <td>${{r.amount}}</td>
        <td class="${{pnlClass}}">${{pnlStr}}</td>
        <td>${{r.balance.toLocaleString(undefined, {{minimumFractionDigits: 2}})}}</td>
      </tr>`;
    }}).join('');

    // Add click handlers to rows
    tbody.querySelectorAll('tr').forEach(tr => {{
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', () => {{
        const tradeTime = tr.dataset.time;
        if (!tradeTime || !mainChart) return;

        // Highlight selected row
        if (selectedRow) selectedRow.style.background = '';
        tr.style.background = 'rgba(59,130,246,0.2)';
        selectedRow = tr;

        // Navigate chart to trade time
        const tradeTimeMs = parseInt(tradeTime) * 1000;
        const tfSeconds = {{
          '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
          '1H': 3600, '4H': 14400, '1D': 86400, '1W': 604800
        }}[currentTf] || 86400;
        const rangeMs = tfSeconds * 50 * 1000;

        mainChart.dispatchAction({{
          type: 'dataZoom',
          startValue: tradeTimeMs - rangeMs,
          endValue: tradeTimeMs + rangeMs,
        }});
      }});
    }});
  }}

  let selectedRow = null;
  const currentTf = "{timeframe or '1D'}";
  renderTable(tableData);

  // ---- Sort ----
  let sortCol = null;
  let sortAsc = true;
  document.querySelectorAll('#trade-table thead th').forEach(th => {{
    th.addEventListener('click', () => {{
      const col = th.dataset.col;
      if (sortCol === col) {{ sortAsc = !sortAsc; }} else {{ sortCol = col; sortAsc = true; }}
      const sorted = [...tableData].sort((a, b) => {{
        const va = a[col], vb = b[col];
        if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va;
        return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      }});
      renderTable(sorted);
      // Update arrow
      document.querySelectorAll('#trade-table thead th').forEach(h => {{
        const arrow = h.querySelector('.sort-arrow');
        if (arrow) arrow.remove();
      }});
      const arrow = document.createElement('span');
      arrow.className = 'sort-arrow';
      arrow.textContent = sortAsc ? '▲' : '▼';
      th.appendChild(arrow);
    }});
  }});

  // ---- Timeframe Switching (AJAX) ----
  const currentSymbol = "{symbol}";
  const currentResultId = "{result_id if result_id else ''}";
  document.querySelectorAll('.tf-btn').forEach(btn => {{
    btn.addEventListener('click', async () => {{
      const tf = btn.dataset.tf;
      if (!tf || tf === (currentTf || '')) return;

      document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      try {{
        // Get token from localStorage or auto-login for testing
        let token = localStorage.getItem('token') || '';
        if (!token && backendUrl) {{
          try {{
            const loginResp = await fetch(backendUrl + '/api/auth/login', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ username: 'quantdinger', password: 'nodame88' }})
            }});
            const loginData = await loginResp.json();
            if (loginData.code === 1 && loginData.data && loginData.data.token) {{
              token = loginData.data.token;
              localStorage.setItem('token', token);
            }}
          }} catch (e) {{
            console.warn('Auto-login failed:', e);
          }}
        }}
        
        const params = new URLSearchParams({{
          symbol: currentSymbol,
          timeframe: tf,
          market: 'Crypto'
        }});
        if (currentResultId) params.append('resultId', currentResultId);

        const apiBase = backendUrl || (window.location.origin && window.location.origin.startsWith('http') ? window.location.origin : '');
        const resp = await fetch(apiBase + '/api/chart/backtest/data?' + params.toString(), {{
          headers: {{ 'Authorization': 'Bearer ' + token }}
        }});
        const json = await resp.json();

        if (json.code === 1 && json.data) {{
          const newCandles = json.data.candles || [];
          const newMarkers = json.data.markers || [];
          const newTableData = json.data.trades || [];
          const newSummary = json.data.summary || {{}};
          const newBB = json.data.bb || null;
          const newRSI = json.data.rsi || [];
          const newKDJ = json.data.kdj || [];

          // Update main chart
          if (mainChart && newCandles.length) {{
            const times = newCandles.map(c => c.time * 1000);
            const values = newCandles.map(c => [c.open, c.close, c.low, c.high]);
            const mpData = newMarkers.map(m => ({{
              coord: [m.time * 1000, m._price || m.price],
              value: m.text,
              symbol: m.symbol || 'pin',
              symbolRotate: m.symbolRotate || 0,
              itemStyle: {{ color: m.color }},
              label: {{ show: true, position: m.position === 'belowBar' ? 'bottom' : 'top', color: m.color, fontSize: 10 }},
            }}));

            mainChart.setOption({{
              xAxis: {{ data: times }},
              series: [
                {{
                  type: 'candlestick',
                  data: values,
                  markPoint: {{ data: markersVisible ? mpData : [] }},
                }},
              ],
            }});

            // Update BB
            if (newBB && newBB.upper) {{
              mainChart.setOption({{
                series: [
                  {{ type: 'line', data: newBB.upper.map(d => [d.time * 1000, d.value]) }},
                  {{ type: 'line', data: newBB.middle.map(d => [d.time * 1000, d.value]) }},
                  {{ type: 'line', data: newBB.lower.map(d => [d.time * 1000, d.value]) }},
                ],
              }});
            }}
          }}

          // Update RSI
          if (rsiChart && newRSI.length) {{
            rsiChart.setOption({{
              series: [{{ type: 'line', data: newRSI.map(d => d.value) }}],
            }});
          }}

          // Update KDJ
          if (kdjChart && newKDJ.length) {{
            kdjChart.setOption({{
              series: [
                {{ type: 'line', data: newKDJ.map(d => d.k) }},
                {{ type: 'line', data: newKDJ.map(d => d.d) }},
                {{ type: 'line', data: newKDJ.map(d => d.j) }},
              ],
            }});
          }}

          // Update stats
          if (newSummary.total_trades !== undefined) {{
            const statItems = [
              {{ label: '总交易次数', value: newSummary.total_trades, cls: 'neutral' }},
              {{ label: '胜率', value: (newSummary.win_rate || 0) + '%', cls: (newSummary.win_rate || 0) >= 50 ? 'positive' : 'negative' }},
              {{ label: '总盈亏', value: ((newSummary.total_pnl || 0) >= 0 ? '+' : '') + (newSummary.total_pnl || 0).toFixed(2), cls: (newSummary.total_pnl || 0) >= 0 ? 'positive' : 'negative' }},
              {{ label: '最大盈利', value: '+' + (newSummary.max_win || 0).toFixed(2), cls: 'positive' }},
              {{ label: '最大亏损', value: (newSummary.max_loss || 0).toFixed(2), cls: 'negative' }},
              {{ label: '盈利次数', value: newSummary.wins || 0, cls: 'positive' }},
              {{ label: '亏损次数', value: newSummary.losses || 0, cls: 'negative' }},
            ];
            statsEl.innerHTML = statItems.map(s => `
              <div class="stat-card">
                <div class="stat-label">${{s.label}}</div>
                <div class="stat-value ${{s.cls}}">${{s.value}}</div>
              </div>
            `).join('');
          }}

          // Update table
          renderTable(newTableData);
        }} else {{
          alert('切换时间周期失败：' + (json.msg || '未知错误'));
        }}
      }} catch (e) {{
        alert('切换时间周期失败：' + e.message);
      }}
    }});
  }});
}})();
</script>
</body>
</html>
"""

    return html
