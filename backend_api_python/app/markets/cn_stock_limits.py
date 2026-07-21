"""A-share (CNStock) price limit (涨跌停) calculation for ChanQuant.

Price limits by board:
- Main board (60xxxx, 00xxxx): ±10%
- ChiNext/创业板 (30xxxx): ±20%
- STAR/科创板 (688xxx): ±20%
- ST stocks (name contains 'ST'): ±5%
- BSE/北交所 (8xxxxx, 4xxxxx): ±30%
"""
from __future__ import annotations

from typing import Optional, Dict


def _get_limit_pct(symbol: str, name: Optional[str] = None) -> float:
    """Determine price limit percentage based on symbol and name."""
    # ST check (name-based)
    if name and "ST" in name.upper():
        return 5.0
    
    # BSE/北交所
    if symbol.startswith("8") or symbol.startswith("4"):
        return 30.0
    
    # STAR/科创板
    if symbol.startswith("688"):
        return 20.0
    
    # ChiNext/创业板
    if symbol.startswith("300") or symbol.startswith("301"):
        return 20.0
    
    # Main board (default)
    return 10.0


def get_price_limit(
    symbol: str,
    previous_close: float,
    name: Optional[str] = None,
) -> Dict[str, object]:
    """Calculate price limits for a given stock.
    
    Returns:
        {
            "upper": float,  # 涨停价
            "lower": float,  # 跌停价
            "limit_pct": float,  # 涨跌幅限制百分比
            "symbol": str,
        }
    """
    pct = _get_limit_pct(symbol, name)
    upper = round(previous_close * (1 + pct / 100), 2)
    lower = round(previous_close * (1 - pct / 100), 2)
    
    return {
        "upper": upper,
        "lower": lower,
        "limit_pct": pct,
        "symbol": symbol,
    }


def is_at_price_limit(price: float, previous_close: float, symbol: str, name: Optional[str] = None) -> Dict[str, bool]:
    """Check if a stock is at its price limit.
    
    Returns:
        {"at_upper": bool, "at_lower": bool}
    """
    limits = get_price_limit(symbol, previous_close, name)
    return {
        "at_upper": price >= limits["upper"],
        "at_lower": price <= limits["lower"],
    }
