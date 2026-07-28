INSERT INTO qd_strategies_trading (
    user_id, strategy_name, strategy_type, market_category,
    execution_mode, status, symbol, timeframe, initial_capital,
    leverage, market_type, exchange_config, trading_config,
    strategy_code, notification_config
) VALUES (
    1,
    'Test - Buy Every Bar BTC/USDT 1m',
    'ScriptStrategy',
    'Crypto',
    'live',
    'running',
    'BTC/USDT',
    '1m',
    20,
    1,
    'swap',
    '{"credential_id": 1}'::jsonb,
    '{"initial_capital": 20, "leverage": 1, "market_type": "swap", "symbol": "BTC/USDT", "timeframe": "1m", "trade_direction": "long", "strict_mode": false, "investment_amount": 20, "maker_fee": 0.0002, "taker_fee": 0.00045}'::jsonb,
    E'def on_init(ctx):\n    ctx.log("Test strategy started: buy every bar")\n\ndef on_bar(ctx, bar):\n    ctx.buy(reason="test_buy_every_bar")\n',
    '{}'::jsonb
) RETURNING id, strategy_name, status;
