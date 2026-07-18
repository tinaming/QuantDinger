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

# Try to discover account IDs
print("4. Attempting to discover account IDs...")

# Method 1: Check if trader has get_stock_account_ids or similar
for method_name in dir(trader):
    if 'account' in method_name.lower():
        print(f"   Found method: {method_name}")

# Method 2: Try common account ID patterns
print()
print("5. Trying common account ID patterns...")
test_accounts = ["", "0", "1", "模拟"]

found_account = False
for acc_id in test_accounts:
    try:
        acc = StockAccount(acc_id)
        asset = trader.query_stock_asset(acc)
        if asset is not None:
            print(f"   Account '{acc_id}': FOUND!")
            print(f"     account_id: {asset.account_id}")
            print(f"     cash: {asset.cash}")
            print(f"     total_value: {asset.total_value}")
            found_account = True
            break
    except Exception as e:
        print(f"   Account '{acc_id}': {e}")

# Method 3: Check trader attributes for connection info
print()
print("6. Checking trader attributes...")
for attr in dir(trader):
    if not attr.startswith('_'):
        val = getattr(trader, attr, None)
        if not callable(val):
            print(f"   {attr}: {val}")

print()
print("=== Connection test complete ===")
if not found_account:
    print()
    print("No account found automatically. Please check the miniQMT terminal")
    print("for your account ID (资金账号). It's usually displayed in the top bar")
    print("or in the account list panel.")

# Keep connection alive
time.sleep(2)
trader.stop()
