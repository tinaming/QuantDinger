import sys, logging, time
sys.path.insert(0, '/app')
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(name)s %(levelname)s %(message)s')
from app.startup import get_trading_executor
executor = get_trading_executor()
result = executor.start_strategy(38)
print('start result:', result, flush=True)
time.sleep(12)
running = executor._is_strategy_running(38)
print('Still running after 12s:', running, flush=True)
