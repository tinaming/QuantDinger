"""OpenAPI tag names (English). Keep stable for published docs."""

HEALTH = "Health"
POLICY = "Policy"
AUTH = "Auth"
USERS = "Users"
MARKET = "Market"
INDICATOR = "Indicator"
BACKTEST = "Backtest"
STRATEGY = "Strategy"
ACCOUNT = "Account"
COMMUNITY = "Community"
CREDENTIALS = "Credentials"
DASHBOARD = "Dashboard"
PORTFOLIO = "Portfolio"
SETTINGS = "Settings"
BILLING = "Billing"
EXPERIMENT = "Experiment"
FAST_ANALYSIS = "FastAnalysis"
GLOBAL_MARKET = "GlobalMarket"
AI_CHAT = "AIChat"
QUICK_TRADE = "QuickTrade"
IBKR = "IBKR"
ALPACA = "Alpaca"
COINOS = "CoinOS"
COINOS_MARKET = "CoinOS-Market"
COINOS_HYPERLIQUID = "CoinOS-Hyperliquid"
COINOS_TRADING = "CoinOS-Trading"
COINOS_FREQTRADE = "CoinOS-Freqtrade"
COINOS_ACCOUNT = "CoinOS-Account"
COINOS_ONCHAIN = "CoinOS-Onchain"

ALL_TAGS = [
    {"name": HEALTH, "description": "Liveness and API metadata (Public)"},
    {"name": POLICY, "description": "Capability and broker policy discovery (Public)"},
    {"name": AUTH, "description": "Authentication and OAuth (Public)"},
    {"name": USERS, "description": "User profile and administration (Mixed)"},
    {"name": MARKET, "description": "Market data and watchlists (Public)"},
    {"name": INDICATOR, "description": "Indicator IDE workspace (Public)"},
    {"name": BACKTEST, "description": "Indicator backtesting (Public)"},
    {"name": STRATEGY, "description": "Strategy runtime and bots (Internal)"},
    {"name": ACCOUNT, "description": "Trading account snapshots and positions (Internal)"},
    {"name": COMMUNITY, "description": "Indicator marketplace (Public)"},
    {"name": CREDENTIALS, "description": "Exchange credential vault (Internal)"},
    {"name": DASHBOARD, "description": "Dashboard aggregates (Internal)"},
    {"name": PORTFOLIO, "description": "Manual portfolio tracking (Internal)"},
    {"name": SETTINGS, "description": "System and brand settings (Mixed)"},
    {"name": BILLING, "description": "Membership and USDT billing (Internal)"},
    {"name": EXPERIMENT, "description": "Strategy tuning experiments (Internal)"},
    {"name": FAST_ANALYSIS, "description": "Fast AI analysis (Public)"},
    {"name": GLOBAL_MARKET, "description": "Global market overview (Public)"},
    {"name": AI_CHAT, "description": "Legacy AI chat compatibility (Internal)"},
    {"name": QUICK_TRADE, "description": "Manual quick trade (Internal)"},
    {"name": IBKR, "description": "Interactive Brokers adapter (Internal)"},
    {"name": ALPACA, "description": "Alpaca adapter (Internal)"},
    {"name": COINOS, "description": "CoinOS Skills integration — crypto market data, trading, analytics (Internal)"},
    {"name": COINOS_MARKET, "description": "AiCoin market data — 200+ exchanges, 183 endpoints (Public)"},
    {"name": COINOS_HYPERLIQUID, "description": "Hyperliquid whale analytics and on-chain perp data (Public)"},
    {"name": COINOS_TRADING, "description": "CEX trading via CCXT — Binance, OKX, Bybit, etc. (Internal)"},
    {"name": COINOS_FREQTRADE, "description": "Freqtrade strategy create/backtest/deploy/control (Internal)"},
    {"name": COINOS_ACCOUNT, "description": "Exchange account management and API key info (Internal)"},
    {"name": COINOS_ONCHAIN, "description": "On-chain DEX via OKX Web3 — swap, wallet, gas (Internal)"},
]
