"""Debug: inspect backtest result structure"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.backtest import BacktestService
from datetime import datetime
from tests.test_czsc_strategy_generation import CZSC_TREND_INDICATOR_CODE

svc = BacktestService()
result = svc.run(
    indicator_code=CZSC_TREND_INDICATOR_CODE,
    market='crypto', symbol='BTC/USDT', timeframe='1h',
    start_date=datetime(2024,1,1), end_date=datetime(2024,7,1),
    initial_capital=10000, commission=0.001, slippage=0.0,
    leverage=1, trade_direction='both',
    indicator_params={'trend_filter': 1},
    strategy_config={'execution': {'signalTiming': 'next_bar_open'}},
)

print('=== Top-level keys ===')
for k in sorted(result.keys()):
    v = result[k]
    if isinstance(v, dict):
        print(f'  {k}: dict({len(v)} keys) -> {sorted(v.keys())[:10]}')
    elif isinstance(v, list):
        print(f'  {k}: list({len(v)} items)')
    elif isinstance(v, (int, float)):
        print(f'  {k}: {v}')
    elif isinstance(v, str):
        print(f'  {k}: str({len(v)} chars)')

print()
if 'summary' in result:
    s = result['summary']
    print('=== Summary keys ===')
    for k in sorted(s.keys()):
        print(f'  {k}: {s[k]}')
else:
    print('No summary key found')

if 'performance' in result:
    p = result['performance']
    print('=== Performance keys ===')
    for k in sorted(p.keys()):
        print(f'  {k}: {p[k]}')
else:
    print('No performance key found')

print()
print('=== Trades ===')
trades = result.get('trades', [])
print(f'  Count: {len(trades)}')
if trades:
    t0 = trades[0]
    print(f'  First trade keys: {sorted(t0.keys())}')
    print(f'  First trade: {t0}')