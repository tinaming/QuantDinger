"""
QMT Bridge — lightweight HTTP service running on Windows host.

The Docker backend cannot access miniQMT (xtquant uses Windows IPC).
This bridge runs on the Windows host (port 5001) and exposes the same
QMT trading API. The Docker backend's QMT routes proxy to this bridge
when xtquant is not available locally.

Usage:
    python scripts/qmt_bridge.py

Requires:
    - Windows
    - miniQMT running and logged in
    - xtquant available (shipped with miniQMT)
"""
import os
import sys
import json
import time
import threading
from flask import Flask, request, jsonify

# ── xtquant setup ──────────────────────────────────────────────────────
QMT_PATH = os.getenv(
    "QMT_PATH",
    r"D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\userdata_mini",
)
QMT_ACCOUNT_ID = os.getenv("QMT_ACCOUNT_ID", "00930599")
QMT_SESSION_ID = int(os.getenv("QMT_SESSION_ID", "999999"))
QMT_LIB_PATH = os.getenv(
    "QMT_LIB_PATH",
    os.path.join(QMT_PATH, "site-packages"),
)

if QMT_LIB_PATH and QMT_LIB_PATH not in sys.path:
    sys.path.insert(0, QMT_LIB_PATH)

from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant

# ── Symbol normalization (inline, no dependency on app/) ───────────────

SH_SUFFIX = ".SH"
SZ_SUFFIX = ".SZ"
BJ_SUFFIX = ".BJ"
CN_SUFFIXES = {SH_SUFFIX, SZ_SUFFIX, BJ_SUFFIX}


def _detect_exchange(code: str) -> str:
    c = code.strip()
    if not c or not c[0].isdigit():
        return SH_SUFFIX
    prefix = c[:3]
    sh_prefixes = {"600", "601", "603", "605", "688", "689",
                   "110", "113", "118", "130", "500", "501", "502", "510",
                   "511", "512", "513", "515", "516", "517", "518", "520",
                   "522", "523", "525", "526", "588"}
    sz_prefixes = {"000", "001", "002", "003", "300", "301",
                   "120", "123", "125", "128", "159", "150", "151",
                   "152", "153", "154", "155", "159", "184", "185", "188"}
    bj_prefixes = {"430", "830", "831", "832", "833", "834", "835",
                   "836", "837", "838", "839", "870", "871", "872", "873",
                   "874", "875", "876", "877", "878", "879", "880", "889", "920"}
    if prefix in sh_prefixes:
        return SH_SUFFIX
    if prefix in sz_prefixes:
        return SZ_SUFFIX
    if prefix in bj_prefixes:
        return BJ_SUFFIX
    if c.startswith("6"):
        return SH_SUFFIX
    if c.startswith("0") or c.startswith("3"):
        return SZ_SUFFIX
    if c.startswith("8") or c.startswith("4") or c.startswith("9"):
        return BJ_SUFFIX
    return SH_SUFFIX


def normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    s = s.replace(" ", "").replace("-", "").replace("_", "").replace("/", "")
    for pfx, sfx in (("SH", SH_SUFFIX), ("SZ", SZ_SUFFIX), ("BJ", BJ_SUFFIX), ("SS", SH_SUFFIX)):
        if s.startswith(pfx) and len(s) > len(pfx):
            rest = s[len(pfx):]
            if rest and rest[0].isdigit():
                s = rest + sfx
                break
    for alias, real in ((".XSHG", SH_SUFFIX), (".XSHE", SZ_SUFFIX),
                         (".SS", SH_SUFFIX), (".SZ", SZ_SUFFIX),
                         (".SH", SH_SUFFIX), (".BJ", BJ_SUFFIX)):
        if s.endswith(alias):
            s = s[: -len(alias)] + real
            break
    for sfx in CN_SUFFIXES:
        if s.endswith(sfx):
            return s
    if "." in s:
        tail = s[s.rfind("."):]
        if tail.upper() in CN_SUFFIXES:
            return s
        s = s[: s.rfind(".")]
    return s + _detect_exchange(s)


# ── QMT connection management ──────────────────────────────────────────

_lock = threading.Lock()
_trader: XtQuantTrader | None = None
_account: StockAccount | None = None
_connected = False


class _BridgeCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        global _connected
        _connected = False
        print("[bridge] miniQMT disconnected")

    def on_stock_order(self, order):
        pass

    def on_stock_trade(self, trade):
        pass

    def on_order_error(self, err):
        print(f"[bridge] order error: {getattr(err, 'error_msg', '')}")

    def on_cancel_error(self, err):
        print(f"[bridge] cancel error: {getattr(err, 'error_msg', '')}")

    def on_account_status(self, status):
        pass


def _ensure_connected() -> bool:
    global _trader, _account, _connected
    if _connected and _trader is not None:
        return True
    with _lock:
        if _connected and _trader is not None:
            return True
        try:
            _trader = XtQuantTrader(QMT_PATH, QMT_SESSION_ID)
            _trader.register_callback(_BridgeCallback())
            _trader.start()
            time.sleep(1)
            result = _trader.connect()
            if result != 0:
                print(f"[bridge] connect failed: {result}")
                _trader.stop()
                _trader = None
                return False
            _account = StockAccount(QMT_ACCOUNT_ID)
            sub = _trader.subscribe(_account)
            if sub != 0:
                print(f"[bridge] subscribe failed: {sub}")
                _trader.stop()
                _trader = None
                _account = None
                return False
            _connected = True
            print(f"[bridge] connected: account={QMT_ACCOUNT_ID}")
            return True
        except Exception as e:
            print(f"[bridge] connection error: {e}")
            return False


def _disconnect():
    global _trader, _account, _connected
    with _lock:
        if _trader:
            try:
                _trader.stop()
            except Exception:
                pass
        _trader = None
        _account = None
        _connected = False


# ── Flask app ──────────────────────────────────────────────────────────

app = Flask(__name__)


def _ok(data, message="ok"):
    return jsonify({"code": 0, "message": message, "data": data})


def _err(code, message, details=""):
    return jsonify({"code": code, "message": message, "details": details})


@app.route("/qmt/status")
def status():
    return _ok({
        "connected": _connected,
        "account_id": QMT_ACCOUNT_ID,
        "qmt_path": QMT_PATH,
        "session_id": QMT_SESSION_ID,
    })


@app.route("/qmt/connect", methods=["POST"])
def connect():
    if _connected:
        return _ok({"connected": True, "message": "Already connected"})
    ok = _ensure_connected()
    if not ok:
        return _err(502, "Failed to connect to miniQMT")
    return _ok({"connected": True, "message": "Connected successfully"})


@app.route("/qmt/disconnect", methods=["POST"])
def disconnect():
    _disconnect()
    return _ok({"connected": False, "message": "Disconnected"})


@app.route("/qmt/asset")
def asset():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        a = _trader.query_stock_asset(_account)
        if a is None:
            return _err(502, "Failed to query asset")
        return _ok({
            "success": True,
            "account_id": QMT_ACCOUNT_ID,
            "cash": float(a.cash),
            "frozen_cash": float(a.frozen_cash),
            "market_value": float(a.market_value),
            "total_asset": float(a.total_asset),
        })
    except Exception as e:
        return _err(500, f"Asset query error: {e}")


@app.route("/qmt/positions")
def positions():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        sym_filter = normalize_symbol(request.args.get("symbol", "")) if request.args.get("symbol") else None
        raw = _trader.query_stock_positions(_account) or []
        result = []
        for p in raw:
            code = getattr(p, "stock_code", "")
            if sym_filter and code.upper() != sym_filter:
                continue
            result.append({
                "symbol": code,
                "volume": int(getattr(p, "volume", 0) or 0),
                "can_use_volume": int(getattr(p, "can_use_volume", 0) or 0),
                "open_price": float(getattr(p, "open_price", 0) or 0),
                "avg_price": float(getattr(p, "avg_price", 0) or 0),
                "last_price": float(getattr(p, "last_price", 0) or 0),
                "market_value": float(getattr(p, "market_value", 0) or 0),
                "float_profit": float(getattr(p, "float_profit", 0) or 0),
                "frozen_volume": int(getattr(p, "frozen_volume", 0) or 0),
            })
        return _ok({"positions": result, "count": len(result)})
    except Exception as e:
        return _err(500, f"Positions query error: {e}")


@app.route("/qmt/orders")
def orders():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        sym_filter = normalize_symbol(request.args.get("symbol", "")) if request.args.get("symbol") else None
        raw = _trader.query_stock_orders(_account) or []
        result = []
        for o in raw:
            code = getattr(o, "stock_code", "")
            if sym_filter and code.upper() != sym_filter:
                continue
            status_val = getattr(o, "order_status", 0)
            status_map = {56: "filled", 55: "partially_filled", 57: "rejected",
                          54: "canceled", 50: "pending", 53: "cancelling",
                          58: "partially_canceled", 59: "queueing"}
            result.append({
                "order_id": getattr(o, "order_id", 0),
                "symbol": code,
                "side": "buy" if getattr(o, "order_type", 0) in (23, 24) else "sell",
                "volume": int(getattr(o, "order_volume", 0) or 0),
                "traded_volume": int(getattr(o, "traded_volume", 0) or 0),
                "traded_price": float(getattr(o, "traded_price", 0) or 0),
                "order_status": status_map.get(int(status_val), f"unknown({status_val})"),
                "price": float(getattr(o, "price", 0) or 0),
                "order_time": getattr(o, "order_time", 0),
            })
        return _ok({"orders": result, "count": len(result)})
    except Exception as e:
        return _err(500, f"Orders query error: {e}")


@app.route("/qmt/quote")
def quote():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return _err(400, "symbol parameter is required")
    try:
        from xtquant import xtdata
        qmt_symbol = normalize_symbol(symbol)
        # Use get_full_tick for real-time quote
        tick = xtdata.get_full_tick([qmt_symbol])
        if not tick or qmt_symbol not in tick:
            # Try with market_data_ex
            data = xtdata.get_market_data_ex([], [qmt_symbol], period='tick', count=1)
            if data and qmt_symbol in data and len(data[qmt_symbol]) > 0:
                df = data[qmt_symbol].iloc[-1]
                return _ok({
                    "success": True,
                    "symbol": qmt_symbol,
                    "last_price": float(df.get('close', 0)),
                    "open": float(df.get('open', 0)),
                    "high": float(df.get('high', 0)),
                    "low": float(df.get('low', 0)),
                    "volume": int(df.get('volume', 0)),
                    "amount": float(df.get('amount', 0)),
                })
            return _err(502, f"No quote for {qmt_symbol}")
        t = tick[qmt_symbol]
        return _ok({
            "success": True,
            "symbol": qmt_symbol,
            "last_price": float(t.get('lastPrice', 0)),
            "open": float(t.get('open', 0)),
            "high": float(t.get('high', 0)),
            "low": float(t.get('low', 0)),
            "last_close": float(t.get('lastClose', 0)),
            "volume": int(t.get('volume', 0)),
            "amount": float(t.get('amount', 0)),
            "bid_price": float(t.get('bidPrice', [0])[0] if t.get('bidPrice') else 0),
            "ask_price": float(t.get('askPrice', [0])[0] if t.get('askPrice') else 0),
        })
    except Exception as e:
        return _err(500, f"Quote error: {e}")


@app.route("/qmt/orders", methods=["POST"])
def place_order():
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    body = request.get_json(force=True) or {}
    symbol = (body.get("symbol") or "").strip()
    side = (body.get("side") or "").strip().lower()
    order_type = (body.get("order_type") or body.get("orderType") or "market").strip().lower()
    volume = int(body.get("volume") or body.get("qty") or 0)
    price = float(body.get("price") or body.get("limit_price") or 0)
    comment = (body.get("comment") or "QuantDinger").strip()

    if not symbol:
        return _err(400, "symbol is required")
    if side not in ("buy", "sell"):
        return _err(400, "side must be 'buy' or 'sell'")
    if volume <= 0:
        return _err(400, "volume must be positive")

    qmt_symbol = normalize_symbol(symbol)
    order_dir = xtconstant.STOCK_BUY if side == "buy" else xtconstant.STOCK_SELL
    pt = xtconstant.FIX_PRICE if order_type == "limit" else xtconstant.LATEST_PRICE
    if order_type == "limit" and price <= 0:
        return _err(400, "price required for limit orders")
    if order_type != "limit":
        price = 0.0

    try:
        order_id = _trader.order_stock(
            _account, qmt_symbol, order_dir, volume, pt, price,
            "QuantDinger", comment,
        )
        if order_id is None or order_id < 0:
            return _err(500, f"order_stock returned error: {order_id}")

        filled = 0.0
        fill_price = 0.0
        status_str = "submitted"
        try:
            o = _trader.query_stock_order(_account, order_id)
            if o:
                filled = float(getattr(o, "traded_volume", 0) or 0)
                fill_price = float(getattr(o, "traded_price", 0) or 0)
        except Exception:
            pass

        return _ok({
            "order_id": order_id,
            "filled": filled,
            "price": fill_price,
            "status": status_str,
            "message": "Order submitted to miniQMT",
            "paper": False,
        }, message="live-order")
    except Exception as e:
        return _err(500, f"Order error: {e}")


@app.route("/qmt/orders/<int:order_id>", methods=["DELETE"])
def cancel_order(order_id: int):
    if not _ensure_connected():
        return _err(502, "Cannot connect to miniQMT")
    try:
        result = _trader.cancel_order_stock(_account, order_id)
        if result == 0:
            return _ok({"order_id": order_id, "cancelled": True, "message": "Cancel accepted"})
        return _err(500, f"Cancel failed: code={result}")
    except Exception as e:
        return _err(500, f"Cancel error: {e}")


# ── Main ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("QMT_BRIDGE_PORT", "5001"))
    print(f"=== QMT Bridge starting on port {port} ===")
    print(f"  QMT_PATH: {QMT_PATH}")
    print(f"  ACCOUNT:  {QMT_ACCOUNT_ID}")
    print(f"  SESSION:  {QMT_SESSION_ID}")

    # Auto-connect on startup
    if _ensure_connected():
        print("  Status:   CONNECTED")
    else:
        print("  Status:   NOT CONNECTED (miniQMT may not be running)")

    app.run(host="127.0.0.1", port=port, debug=False)
