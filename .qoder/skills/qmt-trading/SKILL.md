name: qmt-trading
description: >-
  QMT (迅投 miniQMT) A-share trading integration: launch miniQMT terminal,
  diagnose connection, place orders, query positions/assets/orders, and
  fetch real-time quotes for China A-stocks via xtquant SDK.
  Use when working with A股, CNStock, QMT, miniQMT, xtquant, or
  A-share trading features.
---

# QMT A-Share Trading (迅投 miniQMT)

## When this applies

Use this skill whenever you need to:

- Start / diagnose the miniQMT terminal on the local Windows machine
- Place A-share buy/sell orders (market or limit)
- Query account assets, positions, or today's orders
- Fetch real-time quotes for A-share stocks
- Work with code under `app/services/qmt_trading/`
- Debug QMT connection or xtquant import issues

## Prerequisites

| Component | Requirement |
|-----------|-------------|
| OS | Windows only (miniQMT is Windows-exclusive) |
| miniQMT terminal | Installed at `D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟` |
| userdata path | `D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\userdata_mini` |
| xtquant SDK | Shipped with miniQMT (NOT on PyPI), version `xtquant_250516` |
| Account | 资金账号 (fund account ID) configured in env |
| Login | miniQMT terminal must be running AND logged in before API calls |

## Launching miniQMT

The terminal executable is at:

```
D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\bin.x64\XtMiniQmt.exe
```

Launch via PowerShell:

```powershell
Start-Process "D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\bin.x64\XtMiniQmt.exe"
```

After launch, **wait ~10 seconds** for the process to initialize and auto-login.
Verify with:

```powershell
Get-Process -Name "XtMiniQmt" -ErrorAction SilentlyContinue
```

> **Important**: miniQMT must be running AND fully logged in (check the terminal
> window for "已登录" status) before any xtquant API call will succeed.

## Connection Test

Use the test script to verify end-to-end connectivity:

```powershell
cd chanquant\backend_api_python
python test_qmt_connect.py
```

This script will:
1. Create an `XtQuantTrader` instance
2. Connect to the running miniQMT process (with retries)
3. Attempt to discover and query the account

Expected output on success: `connect() returned: 0` and account asset info.

## Architecture

### Module: `app/services/qmt_trading/`

| File | Purpose |
|------|---------|
| `__init__.py` | Public exports: `QMTClient`, `QMTConfig`, `OrderResult`, `normalize_symbol`, `parse_symbol` |
| `client.py` (771 lines) | Full trading client: connect, order, query, disconnect |
| `symbols.py` (173 lines) | Symbol normalization: `600000` → `600000.SH`, exchange auto-detection |

### QMTConfig

```python
@dataclass
class QMTConfig:
    qmt_path: str = ""           # userdata_mini 完整路径
    qmt_account_id: str = ""     # 资金账号
    qmt_session_id: int = 123456 # 会话ID (唯一)
    qmt_username: str = ""       # 登录用户名
    qmt_password: str = ""       # 登录密码
    qmt_lib_path: str = ""       # xtquant site-packages 路径
    strategy_name: str = "ChanQuant"
```

### QMTClient API

| Method | Description |
|--------|-------------|
| `connect() -> bool` | Connect to miniQMT (must be running + logged in) |
| `disconnect()` | Clean disconnect |
| `place_market_order(symbol, side, volume, comment)` | Market order (最新价) |
| `place_limit_order(symbol, side, volume, price, comment)` | Limit order (限价) |
| `cancel_order(order_id) -> bool` | Cancel an order |
| `get_account_info() -> dict` | Cash, frozen_cash, market_value, total_asset |
| `get_positions(symbol=None) -> list[dict]` | Stock positions (T+1 aware: `can_use_volume`) |
| `get_orders(symbol=None) -> list[dict]` | Today's orders |
| `get_quote(symbol) -> dict` | Real-time quote via xtdata |
| `get_connection_status() -> dict` | Connection status check |

### Global Singleton

```python
from app.services.qmt_trading import get_qmt_client, reset_qmt_client

client = get_qmt_client(config)  # first call initializes
reset_qmt_client()              # disconnect and clear
```

## Symbol Conventions

QMT uses `CODE.EXCHANGE` format. The module auto-detects the exchange:

| Input | Normalized | Exchange |
|-------|-----------|----------|
| `600000` | `600000.SH` | Shanghai Main Board |
| `688001` | `688001.SH` | STAR Market (科创板) |
| `000001` | `000001.SZ` | Shenzhen Main Board |
| `300001` | `300001.SZ` | ChiNext (创业板) |
| `830899` | `830899.BJ` | Beijing Stock Exchange |

Also accepts prefix-style (`SH600000`, `SZ000001`) and long aliases (`.XSHG`, `.SS`).

## A-Share Trading Rules (Important!)

- **Lot size**: Volume must be a multiple of 100 (1 手 = 100 股)
- **T+1 settlement**: Shares bought today cannot be sold until next trading day
  - `can_use_volume` in positions shows what's available to sell
- **Order types**: Market (最新价 `LATEST_PRICE`) or Limit (限价 `FIX_PRICE`)
- **Sides**: `buy` (STOCK_BUY) / `sell` (STOCK_SELL) — no short selling via QMT
- **Trading hours**: 09:30–11:30, 13:00–15:00 Beijing time

## Order Status Codes

| Code | Status | Chinese |
|------|--------|---------|
| 50 | pending | 等待 |
| 55 | partially_filled | 部分成交 |
| 56 | filled | 全部成交 |
| 57 | rejected | 废单 |
| 54 | canceled | 已撤 |
| 53 | cancelling | 撤单中 |
| 58 | partially_canceled | 部撤 |
| 59 | queueing | 排队中 |

## Environment Guard

QMT is gated by `ALLOW_LOCAL_DESKTOP_BROKERS` env var (see `app/utils/local_brokers.py`).
When `false`, all QMT/IBKR/MT5 flows are rejected with a cloud-incompatible message.
Default is `true` for local development.

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `connect() returned: -1` | miniQMT not running or not logged in | Launch terminal and wait for login |
| `connect() returned: -2` | Another xtquant session on same path | Kill other Python processes using xtquant |
| `ImportError: xtquant` | xtquant not on sys.path | Set `qmt_lib_path` to `userdata_mini/site-packages` |
| `subscribe failed` | Wrong account_id | Check 资金账号 in miniQMT terminal top bar |
| Order rejected (废单) | Non-trading hours, or volume not 100x | Check time and lot size |

## Data Source Integration

A-share K-line data is fetched separately (not via QMT trading connection):

- **Tier 1**: TwelveData (disabled by default)
- **Tier 2**: Tencent (enabled)
- **Tier 3**: yfinance (enabled)
- **Tier 4**: AkShare (enabled)

Check status via API: `GET /api/agent/v1/markets/CNStock/data-source-status`
Or via MCP: `cn_stock_data_status`

## Red Lines

- **Never** store real account credentials in code or commit them
- **Never** bypass the `ALLOW_LOCAL_DESKTOP_BROKERS` guard without explicit user approval
- **Always** confirm with the user before placing live orders (paper trading is default)
- xtquant is **not** on PyPI — do not add it to `requirements.txt`
