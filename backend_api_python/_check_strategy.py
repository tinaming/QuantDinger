"""Check strategy 38 status and start it if not running."""
import sys, os, datetime
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://quantdinger:quantdinger123@postgres:5432/quantdinger')

import jwt, requests
from dotenv import load_dotenv
load_dotenv('/app/.env')

secret = os.getenv('SECRET_KEY', '')
payload = {'user_id': 1, 'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)}
token = jwt.encode(payload, secret, algorithm='HS256')
headers = {'Authorization': f'Bearer {token}'}

# Find the right endpoint
for ep in ['/api/strategies', '/api/strategy/list', '/api/trading/strategies']:
    r = requests.get(f'http://127.0.0.1:5000{ep}', headers=headers, timeout=5)
    if r.status_code == 200:
        data = r.json()
        items = data.get('data', data.get('strategies', []))
        if isinstance(items, list) and len(items) > 0:
            print(f'Endpoint: {ep} -> {len(items)} strategies')
            for s in items[:5]:
                sid = s.get('id', s.get('strategy_id'))
                status = s.get('status')
                running = s.get('is_running', s.get('thread_alive', '?'))
                print(f'  id={sid} status={status} running={running}')
            break
        else:
            print(f'{ep}: 200 but empty')
    else:
        print(f'{ep}: {r.status_code}')

# Try to start strategy 38 via API
print('\n--- Starting strategy 38 ---')
r = requests.post('http://127.0.0.1:5000/api/strategies/start',
                  headers=headers, json={'id': 38, 'strategy_id': 38}, timeout=10)
print(f'Start API: {r.status_code} {r.text[:300]}')

# Check market hours
print('\n--- Market hours check ---')
from app.markets.cn_stock_hours import is_cn_market_open, get_cn_market_session
print(f'is_cn_market_open() = {is_cn_market_open()}')
print(f'session = {get_cn_market_session()}')
