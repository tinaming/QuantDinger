import numpy as np
from app.services.czsc_bridge import compute_czsc_features
from app.data_sources.crypto import CryptoDataSource

ds = CryptoDataSource()
# Use direct ccxt fetch for more data
import ccxt, time as _t
ex = ccxt.gate({'options': {'defaultType': 'swap'}, 'enableRateLimit': True})
all_bars = []
since = int((_t.time() - 14*3600) * 1000)  # 14 hours ago
while True:
    batch = ex.fetch_ohlcv('ARB/USDT:USDT', '10s', since=since, limit=300)
    if not batch:
        break
    all_bars.extend(batch)
    since = batch[-1][0] + 10000
    if len(batch) < 300:
        break
print(f'Got {len(all_bars)} klines via direct ccxt')

import pandas as pd
df = pd.DataFrame(all_bars, columns=['time','open','high','low','close','volume'])
df['time'] = pd.to_datetime(df['time'], unit='ms')
df = df.set_index('time')

result = compute_czsc_features(df, freq='10s', symbol='ARB/USDT:USDT')
bi_dir = result['czsc_bi_dir'].values
nonzero = np.where(bi_dir != 0)[0]

print(f'Total bars: {len(bi_dir)}')
print(f'Non-zero bi_dir count: {len(nonzero)}')
if len(nonzero) > 0:
    print(f'Last non-zero bi_dir at index: {nonzero[-1]} (of {len(bi_dir)-1})')
    print(f'Bars since last completed stroke: {len(bi_dir) - 1 - nonzero[-1]}')
    print(f'bi_dir[-30:]: {bi_dir[-30:].tolist()}')
    print(f'bi_dir last non-zero value: {bi_dir[nonzero[-1]]}')
else:
    print('ALL bi_dir values are 0!')

bs_type = result['czsc_bs_type'].values
nonempty_bs = np.where(bs_type != '')[0]
print(f'\nBuy/sell points: {len(nonempty_bs)}')
if len(nonempty_bs) > 0:
    print(f'Last bs_type at index: {nonempty_bs[-1]}, type: {bs_type[nonempty_bs[-1]]}')
    print(f'Bars since last bs_type: {len(bs_type) - 1 - nonempty_bs[-1]}')

trend = result['czsc_trend'].values
print(f'\nTrend non-zero: {len(np.where(trend != 0)[0])}')
print(f'trend[-5:]: {trend[-5:].tolist()}')
