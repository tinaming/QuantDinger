"""Test QMT (miniQMT) connection and discover account ID."""
import sys
import time

QMT_PATH = r"D:\迅投极速策略交易系统交易终端 华鑫证券QMT模拟\userdata_mini"
SESSION_ID = 888999  # different session ID to avoid stale queue conflicts

print("=== QMT Connection Test ===")
print(f"Path: {QMT_PATH}")
print(f"Session ID: {SESSION_ID}")
print()

from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

class TestCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print("[callback] Disconnected from miniQMT")

    def on_account_status(self, status):
        print(f"[callback] Account status: account_id={status.account_id}, status={status.status}")

    def on_stock_order(self, order):
        print(f"[callback] Order callback: {order}")

    def on_stock_trade(self, trade):
        print(f"[callback] Trade callback: {trade}")

# Create trader
print("1. Creating XtQuantTrader...")
trader = XtQuantTrader(QMT_PATH, SESSION_ID)
trader.register_callback(TestCallback())

print("2. Starting trader...")
trader.start()

# Wait for IPC to be ready
print("   Waiting 2s for IPC initialization...")
time.sleep(2)

# Try connecting with retries
print("3. Connecting to miniQMT (with retries)...")
connect_result = -1
for attempt in range(1, 6):
    connect_result = trader.connect()
    print(f"   Attempt {attempt}: connect() returned: {connect_result} (0 = success)")
    if connect_result == 0:
        break
    print(f"   Retrying in 3s...")
    time.sleep(3)

if connect_result != 0:
    print()
    print("   FAILED: Cannot connect after 5 attempts.")
    print("   Possible causes:")
    print("   1. miniQMT is running but NOT logged in yet (check for login dialog)")
    print("   2. miniQMT is still initializing (wait for data sync)")
    print("   3. Another xtquant session is already connected to this path")
    print("   4. Wrong userdata_mini path")
    trader.stop()
    sys.exit(1)

print("   Connected successfully!")
print()

# Wait a moment for the connection to stabilize
time.sleep(1)

# Discover account IDs via query_account_infos()
print("4. Discovering account IDs via query_account_infos()...")
found_account = False

try:
    account_infos = trader.query_account_infos()
    if account_infos:
        for ai in account_infos:
            acc_id = getattr(ai, 'account_id', '')
            acc_type = getattr(ai, 'account_type', '')
            print(f"   Found account: id={acc_id}, type={acc_type}")

            # Subscribe and query asset
            acc = StockAccount(acc_id)
            sub_result = trader.subscribe(acc)
            if sub_result == 0:
                asset = trader.query_stock_asset(acc)
                if asset:
                    print(f"     cash: {asset.cash:.2f}")
                    print(f"     frozen_cash: {asset.frozen_cash:.2f}")
                    print(f"     market_value: {asset.market_value:.2f}")
                    print(f"     total_asset: {asset.total_asset:.2f}")
                    found_account = True

                    # Query positions
                    positions = trader.query_stock_positions(acc)
                    if positions:
                        print(f"     positions ({len(positions)}):")
                        for p in positions:
                            print(f"       {p.stock_code}: vol={p.volume}, "
                                  f"can_use={p.can_use_volume}, "
                                  f"avg_price={p.avg_price:.4f}, "
                                  f"last_price={p.last_price}, "
                                  f"float_profit={p.float_profit:.2f}")
                    else:
                        print("     positions: (empty)")
            else:
                print(f"     subscribe failed: {sub_result}")
    else:
        print("   No account infos returned")
except Exception as e:
    print(f"   Error discovering accounts: {e}")

print()
print("=== Connection test complete ===")
if not found_account:
    print()
    print("No account found. Please check the miniQMT terminal is logged in.")

# Keep connection alive
time.sleep(2)
trader.stop()
