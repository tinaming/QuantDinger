UPDATE qd_strategies_trading 
SET trading_config = (trading_config::jsonb || '{"trade_direction": "both"}'::jsonb)::text
WHERE id = 38
RETURNING id, strategy_name, trading_config::jsonb->>'trade_direction' AS trade_direction;
