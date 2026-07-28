from datetime import datetime, timedelta, timezone
import math

timeframe = '10s'
tf_seconds = 10
limit = 10200

# Check TIMEFRAME_SECONDS in base.py
from app.data_sources.base import TIMEFRAME_SECONDS as BASE_TF
print(f"base.py TIMEFRAME_SECONDS['10s'] = {BASE_TF.get('10s')}")

# calculate_time_range
ct = BASE_TF.get(timeframe, 86400) * limit * 1.2
print(f"calculate_time_range: {ct}s = {ct/3600:.1f}h")

# Backtest _fetch_kline_data calculations
now_ts = int(datetime.now().timestamp())
print(f"now_ts = {now_ts} ({datetime.fromtimestamp(now_ts)})")

max_lb = tf_seconds * 9500
earliest = now_ts - max_lb
print(f"earliest_allowed = {earliest} ({datetime.fromtimestamp(earliest)})")
print(f"max lookback = {max_lb}s = {max_lb/3600:.1f}h")

start_date_ts = int(datetime(2026, 7, 19).timestamp())
after_time = start_date_ts - 86400
print(f"after_time (before clamp) = {after_time} ({datetime.fromtimestamp(after_time)})")

if after_time < earliest:
    after_time = earliest
print(f"after_time (after clamp) = {after_time} ({datetime.fromtimestamp(after_time)})")

delta_h = (now_ts - after_time) / 3600
print(f"lookback from now: {delta_h:.1f}h")

# _fetch_ohlcv calculation
total_seconds = ct  # from calculate_time_range
before_time = int((datetime(2026, 7, 20) + timedelta(days=1)).timestamp())
safe_before_ts = min(before_time, now_ts)
end_dt = datetime.fromtimestamp(safe_before_ts, tz=timezone.utc)
start_dt = end_dt - timedelta(seconds=total_seconds)
floor_dt = datetime.fromtimestamp(after_time, tz=timezone.utc)
start_dt = min(start_dt, floor_dt)
since_ms = int(start_dt.timestamp() * 1000)
print(f"\n_fetch_ohlcv:")
print(f"  safe_before_ts = {safe_before_ts} ({datetime.fromtimestamp(safe_before_ts)})")
print(f"  end_dt = {end_dt}")
print(f"  start_dt (before floor) = {end_dt - timedelta(seconds=total_seconds)}")
print(f"  floor_dt = {floor_dt}")
print(f"  start_dt (after floor) = {start_dt}")
print(f"  since_ms = {since_ms}")
print(f"  lookback from now = {(now_ts - start_dt.timestamp())/3600:.1f}h")

# Test fetch
import ccxt, time as _t
ex = ccxt.gate({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
try:
    bars = ex.fetch_ohlcv('NEAR/USDT:USDT', '10s', since=since_ms, limit=5)
    print(f"\nDirect fetch with since={since_ms}: Got {len(bars)} bars")
    if bars:
        print(f"  First: {bars[0]}")
except Exception as e:
    print(f"\nDirect fetch FAILED: {e}")
