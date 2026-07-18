"""
QMT (迅投 miniQMT) Trading Module

Provides A-share (China A-Stock) trading capabilities via the xtquant
Python SDK, which talks to a locally running miniQMT client.

Prerequisites:
- miniQMT client installed and logged in (Windows only)
- xtquant package available on sys.path (shipped with miniQMT, not on PyPI)
- The miniQMT ``userdata_mini`` directory path
- A funded securities account id (资金账号)
"""

from app.services.qmt_trading.client import QMTClient, QMTConfig, OrderResult
from app.services.qmt_trading.symbols import normalize_symbol, parse_symbol

__all__ = [
    "QMTClient",
    "QMTConfig",
    "OrderResult",
    "normalize_symbol",
    "parse_symbol",
]
