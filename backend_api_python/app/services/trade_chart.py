"""
Trade chart visualization service.

Generates a self-contained HTML page using TradingView lightweight-charts
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
        # Milliseconds guard
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    s = str(raw).strip()
    if not s:
        return None
    # Try ISO-like formats
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    # Unix numeric string
    try:
        ts = int(float(s))
        if ts > 10_000_000_000:
            ts //= 1000
        return ts
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Candle data normalization
# ---------------------------------------------------------------------------

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


def _prepare_candles(klines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert raw kline rows to lightweight-charts candle series."""
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
    """Convert trade rows to lightweight-charts marker objects."""
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

        # Color / shape
        if entry and side == "long":
            color = "#22c55e"
            shape = "arrowUp"
            label = "买入"
        elif entry and side == "short":
            color = "#ef4444"
            shape = "arrowDown"
            label = "做空"
        elif exit_ and profit >= 0:
            color = "#22c55e"
            shape = "arrowDown"
            label = "平多" if side == "long" else "平空"
        elif exit_:
            color = "#ef4444"
            shape = "arrowUp"
            label = "平多" if side == "long" else "平空"
        else:
            color = "#60a5fa"
            shape = "circle"
            label = trade_type or "操作"

        pnl_str = f"+{profit:.2f}" if profit >= 0 else f"{profit:.2f}"
        text = f"{label} @ {price:.4g}  |  PnL: {pnl_str}"

        markers.append({
            "time": ts,
            "position": "belowBar" if entry else "aboveBar",
            "color": color,
            "shape": shape,
            "text": text,
            # Stash extra fields for tooltip JS
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
# HTML generation
# ---------------------------------------------------------------------------

_LWCHARTS_CDN = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def build_chart_html(
    klines: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    *,
    symbol: str = "",
    timeframe: str = "",
    theme: str = "dark",
) -> str:
    """
    Build a self-contained HTML page with:
      - lightweight-charts candlestick chart
      - Trade markers overlaid
      - Summary stats card
      - Trade detail table
    """
    candles = _prepare_candles(klines)
    markers = _prepare_markers(trades)
    table_rows = _prepare_trade_table(trades)
    summary = _build_summary(trades)

    # Strip internal fields before serializing for JS
    markers_for_js = []
    for m in markers:
        markers_for_js.append({
            "time": m["time"],
            "position": m["position"],
            "color": m["color"],
            "shape": m["shape"],
            "text": m["text"],
        })

    candles_json = json.dumps(candles, ensure_ascii=False)
    markers_json = json.dumps(markers_for_js, ensure_ascii=False)
    table_json = json.dumps(table_rows, ensure_ascii=False)
    summary_json = json.dumps(summary, ensure_ascii=False)

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
  #chart-container {{
    width: 100%;
    height: 480px;
    padding: 8px 12px;
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
  <span class="subtitle">Generated by ChanQuant · lightweight-charts</span>
</div>

<div class="stats-bar" id="stats-bar"></div>

<div id="chart-container"></div>

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

<script src="{_LWCHARTS_CDN}"></script>
<script>
(function() {{
  // ---- Data ----
  const candles = {candles_json};
  const markers = {markers_json};
  const tableData = {table_json};
  const summary = {summary_json};

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

  // ---- Chart ----
  if (!candles.length) {{
    document.getElementById('chart-container').innerHTML =
      '<div class="empty-state">暂无K线数据，无法渲染图表</div>';
  }} else {{
    const container = document.getElementById('chart-container');
    const chart = LightweightCharts.createChart(container, {{
      width: container.clientWidth,
      height: 480,
      layout: {{
        background: {{ type: 'solid', color: '#0b1120' }},
        textColor: '#94a3b8',
        attributionLogo: false,
      }},
      grid: {{
        vertLines: {{ color: 'rgba(148,163,184,0.06)' }},
        horzLines: {{ color: 'rgba(148,163,184,0.06)' }},
      }},
      crosshair: {{
        mode: LightweightCharts.CrosshairMode.Normal,
      }},
      timeScale: {{
        timeVisible: true,
        secondsVisible: false,
        borderColor: 'rgba(148,163,184,0.15)',
      }},
      rightPriceScale: {{
        borderColor: 'rgba(148,163,184,0.15)',
      }},
    }});

    const candleSeries = chart.addCandlestickSeries({{
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#22c55e',
      wickDownColor: '#ef4444',
      wickUpColor: '#22c55e',
    }});

    candleSeries.setData(candles);

    if (markers.length) {{
      candleSeries.setMarkers(markers);
    }}

    chart.timeScale().fitContent();

    window.addEventListener('resize', () => {{
      chart.applyOptions({{ width: container.clientWidth }});
    }});
  }}

  // ---- Table ----
  const tbody = document.getElementById('trade-tbody');
  function renderTable(rows) {{
    tbody.innerHTML = rows.map(r => {{
      const dirCls = r.side === 'long' ? 'dir-long' : 'dir-short';
      const pnlCls = r.profit >= 0 ? 'pnl-pos' : 'pnl-neg';
      const pnlStr = (r.profit >= 0 ? '+' : '') + r.profit.toFixed(2);
      return `<tr>
        <td>${{r.index}}</td>
        <td>${{r.time}}</td>
        <td class="${{dirCls}}">${{r.direction}}</td>
        <td>${{r.price.toLocaleString(undefined, {{maximumFractionDigits: 6}})}}</td>
        <td>${{r.amount.toLocaleString(undefined, {{maximumFractionDigits: 6}})}}</td>
        <td class="${{pnlCls}}">${{pnlStr}}</td>
        <td>${{r.balance.toLocaleString(undefined, {{maximumFractionDigits: 2}})}}</td>
      </tr>`;
    }}).join('');
  }}
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
      const span = document.createElement('span');
      span.className = 'sort-arrow';
      span.textContent = sortAsc ? '▲' : '▼';
      th.appendChild(span);
    }});
  }});
}})();
</script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Combined review page: metrics + chart + trade table
# ---------------------------------------------------------------------------

def build_review_page_html(
    klines: List[Dict[str, Any]],
    trades: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    *,
    symbol: str = "",
    timeframe: str = "",
    strategy_name: str = "",
    lookback_days: int = 30,
) -> str:
    """Build a combined performance-review + trade-chart HTML page.

    Shows:
      - Performance KPI cards (from review report metrics)
      - K-line candlestick chart with trade markers
      - Trade detail table
    """
    candles = _prepare_candles(klines)
    markers = _prepare_markers(trades)
    table_rows = _prepare_trade_table(trades)
    trade_summary = _build_summary(trades)

    # Strip internal fields before JS serialization
    markers_for_js = []
    for m in markers:
        markers_for_js.append({
            "time": m["time"],
            "position": m["position"],
            "color": m["color"],
            "shape": m["shape"],
            "text": m["text"],
        })

    candles_json = json.dumps(candles, ensure_ascii=False)
    markers_json = json.dumps(markers_for_js, ensure_ascii=False)
    table_json = json.dumps(table_rows, ensure_ascii=False)

    # Extract review metrics for display
    m = metrics or {}
    title = f"{strategy_name or symbol or '策略'} · {timeframe or ''} · 绩效复盘".strip(" ·")

    # Build KPI cards from metrics
    kpi_items = [
        {"label": "回看天数", "value": f"{int(m.get('lookback_days', lookback_days))}d", "cls": "neutral"},
        {"label": "初始资金", "value": f"{_as_float(m.get('initial_capital')):,.0f}", "cls": "neutral"},
        {"label": "当前权益", "value": f"{_as_float(m.get('current_equity')):,.2f}", "cls": "neutral"},
        {"label": "总净盈亏", "value": f"{_as_float(m.get('total_net_pnl')):+,.2f}", "cls": "positive" if _as_float(m.get('total_net_pnl')) >= 0 else "negative"},
        {"label": "窗口收益率", "value": f"{_as_float(m.get('window_return_pct')):+.2f}%", "cls": "positive" if _as_float(m.get('window_return_pct')) >= 0 else "negative"},
        {"label": "最大回撤", "value": f"{_as_float(m.get('window_max_drawdown_pct')):.2f}%", "cls": "negative"},
        {"label": "胜率", "value": f"{_as_float(m.get('win_rate')):.1f}%", "cls": "positive" if _as_float(m.get('win_rate')) >= 50 else "negative"},
        {"label": "盈亏比", "value": f"{_as_float(m.get('profit_factor')):.2f}", "cls": "positive" if _as_float(m.get('profit_factor')) >= 1 else "negative"},
        {"label": "期望值", "value": f"{_as_float(m.get('expectancy')):+,.2f}", "cls": "positive" if _as_float(m.get('expectancy')) >= 0 else "negative"},
        {"label": "交易次数", "value": f"{int(m.get('closing_events') or 0)}", "cls": "neutral"},
        {"label": "盈利次数", "value": f"{int(m.get('winning_trades') or 0)}", "cls": "positive"},
        {"label": "亏损次数", "value": f"{int(m.get('losing_trades') or 0)}", "cls": "negative"},
        {"label": "平均盈利", "value": f"{_as_float(m.get('avg_win')):+,.2f}", "cls": "positive"},
        {"label": "平均亏损", "value": f"{_as_float(m.get('avg_loss')):+,.2f}", "cls": "negative"},
        {"label": "最大单笔盈利", "value": f"{_as_float(m.get('max_win')):+,.2f}", "cls": "positive"},
        {"label": "最大单笔亏损", "value": f"{_as_float(m.get('max_loss')):+,.2f}", "cls": "negative"},
        {"label": "总手续费", "value": f"{_as_float(m.get('total_commission')):,.2f}", "cls": "neutral"},
        {"label": "最大连亏", "value": f"{int(m.get('max_consecutive_losses') or 0)}", "cls": "negative" if int(m.get('max_consecutive_losses') or 0) > 2 else "neutral"},
    ]

    kpi_html = "\n".join(
        f'<div class="kpi"><div class="kpi-label">{k["label"]}</div>'
        f'<div class="kpi-value {k["cls"]}">{k["value"]}</div></div>'
        for k in kpi_items
    )

    # Exit reason breakdown
    exit_reasons = m.get("exit_reason_counts") or {}
    reason_html = ""
    if exit_reasons:
        reason_rows = "\n".join(
            f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in exit_reasons.items()
        )
        reason_html = f"""
        <div class="panel">
          <h3>平仓原因分布</h3>
          <table class="mini-table">
            <thead><tr><th>原因</th><th>次数</th></tr></thead>
            <tbody>{reason_rows}</tbody>
          </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-cmn-Hans">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — ChanQuant 绩效复盘</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, sans-serif;
    background: #0b1120;
    color: #f8fafc;
  }}
  .header {{
    padding: 20px 28px;
    border-bottom: 1px solid rgba(148,163,184,0.15);
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header .sub {{ font-size: 13px; color: #94a3b8; }}

  /* KPI grid */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 10px;
    padding: 16px 28px;
    border-bottom: 1px solid rgba(148,163,184,0.1);
  }}
  .kpi {{
    background: rgba(30,41,59,0.7);
    border: 1px solid rgba(148,163,184,0.12);
    border-radius: 10px;
    padding: 12px 14px;
  }}
  .kpi-label {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.4px; }}
  .kpi-value {{ font-size: 17px; font-weight: 700; margin-top: 4px; }}
  .kpi-value.positive {{ color: #22c55e; }}
  .kpi-value.negative {{ color: #ef4444; }}
  .kpi-value.neutral  {{ color: #60a5fa; }}

  /* Chart */
  #chart-container {{ width: 100%; height: 460px; padding: 12px 16px; }}

  /* Panel */
  .panel {{
    padding: 16px 28px;
  }}
  .panel h3 {{
    font-size: 15px; font-weight: 600; margin-bottom: 10px; color: #cbd5e1;
  }}

  /* Mini table */
  .mini-table {{ border-collapse: collapse; font-size: 13px; width: auto; }}
  .mini-table th {{ text-align: left; padding: 6px 14px 6px 0; color: #94a3b8; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid rgba(148,163,184,0.2); }}
  .mini-table td {{ padding: 5px 14px 5px 0; color: #e2e8f0; }}

  /* Trade table */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  thead th {{
    text-align: left; padding: 8px 10px;
    border-bottom: 1px solid rgba(148,163,184,0.2);
    color: #94a3b8; font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.4px;
    cursor: pointer; user-select: none;
  }}
  thead th:hover {{ color: #f8fafc; }}
  tbody tr {{ border-bottom: 1px solid rgba(148,163,184,0.08); transition: background 0.12s; }}
  tbody tr:hover {{ background: rgba(59,130,246,0.08); }}
  tbody td {{ padding: 7px 10px; color: #e2e8f0; }}
  .dir-long {{ color: #22c55e; font-weight: 600; }}
  .dir-short {{ color: #ef4444; font-weight: 600; }}
  .pnl-pos {{ color: #22c55e; }}
  .pnl-neg {{ color: #ef4444; }}
  .sort-arrow {{ margin-left: 4px; font-size: 10px; }}
  .empty-state {{ text-align: center; padding: 48px; color: #64748b; font-size: 14px; }}
  .flex-row {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .flex-row > .panel {{ flex: 1; min-width: 240px; }}
</style>
</head>
<body>

<div class="header">
  <h1>{title}</h1>
  <span class="sub">ChanQuant 绩效复盘 · lightweight-charts</span>
</div>

<div class="kpi-grid">
{kpi_html}
</div>

<div id="chart-container"></div>

<div class="flex-row">
{reason_html}
</div>

<div class="panel">
  <h3>交易明细</h3>
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

<script src="{_LWCHARTS_CDN}"></script>
<script>
(function() {{
  const candles = {candles_json};
  const markers = {markers_json};
  const tableData = {table_json};

  // ---- Chart ----
  if (!candles.length) {{
    document.getElementById('chart-container').innerHTML =
      '<div class="empty-state">暂无K线数据，无法渲染图表</div>';
  }} else {{
    const container = document.getElementById('chart-container');
    const chart = LightweightCharts.createChart(container, {{
      width: container.clientWidth,
      height: 440,
      layout: {{
        background: {{ type: 'solid', color: '#0b1120' }},
        textColor: '#94a3b8',
        attributionLogo: false,
      }},
      grid: {{
        vertLines: {{ color: 'rgba(148,163,184,0.06)' }},
        horzLines: {{ color: 'rgba(148,163,184,0.06)' }},
      }},
      crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
      timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: 'rgba(148,163,184,0.15)' }},
      rightPriceScale: {{ borderColor: 'rgba(148,163,184,0.15)' }},
    }});

    const candleSeries = chart.addCandlestickSeries({{
      upColor: '#22c55e', downColor: '#ef4444',
      borderDownColor: '#ef4444', borderUpColor: '#22c55e',
      wickDownColor: '#ef4444', wickUpColor: '#22c55e',
    }});
    candleSeries.setData(candles);
    if (markers.length) candleSeries.setMarkers(markers);
    chart.timeScale().fitContent();
    window.addEventListener('resize', () => chart.applyOptions({{ width: container.clientWidth }}));
  }}

  // ---- Table ----
  const tbody = document.getElementById('trade-tbody');
  function renderTable(rows) {{
    tbody.innerHTML = rows.map(r => {{
      const dirCls = r.side === 'long' ? 'dir-long' : 'dir-short';
      const pnlCls = r.profit >= 0 ? 'pnl-pos' : 'pnl-neg';
      const pnlStr = (r.profit >= 0 ? '+' : '') + r.profit.toFixed(2);
      return `<tr>
        <td>${{r.index}}</td><td>${{r.time}}</td>
        <td class="${{dirCls}}">${{r.direction}}</td>
        <td>${{r.price.toLocaleString(undefined, {{maximumFractionDigits: 6}})}}</td>
        <td>${{r.amount.toLocaleString(undefined, {{maximumFractionDigits: 6}})}}</td>
        <td class="${{pnlCls}}">${{pnlStr}}</td>
        <td>${{r.balance.toLocaleString(undefined, {{maximumFractionDigits: 2}})}}</td>
      </tr>`;
    }}).join('');
  }}
  renderTable(tableData);

  // Sort
  let sortCol = null, sortAsc = true;
  document.querySelectorAll('#trade-table thead th').forEach(th => {{
    th.addEventListener('click', () => {{
      const col = th.dataset.col;
      if (sortCol === col) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = true; }}
      const sorted = [...tableData].sort((a, b) => {{
        const va = a[col], vb = b[col];
        if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va;
        return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      }});
      renderTable(sorted);
      document.querySelectorAll('#trade-table thead th').forEach(h => {{
        const a = h.querySelector('.sort-arrow'); if (a) a.remove();
      }});
      const span = document.createElement('span');
      span.className = 'sort-arrow'; span.textContent = sortAsc ? '▲' : '▼';
      th.appendChild(span);
    }});
  }});
}})();
</script>
</body>
</html>"""
    return html


def _as_float(v: Any, default: float = 0.0) -> float:
    """Local helper mirroring strategy_review._as_float."""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default
