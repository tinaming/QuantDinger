"""A-share (CNStock) trading rules for ChanQuant.

Implements A-share specific rules:
- T+1 settlement: stocks bought today cannot be sold until next trading day
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Optional, Dict, Set

from app.markets.cn_stock_hours import _to_shanghai_time, _get_holidays


def get_next_trading_day(current_date: date) -> date:
    """Get the next trading day after current_date."""
    holidays = _get_holidays()
    next_day = current_date + timedelta(days=1)
    
    while True:
        if next_day.weekday() >= 5:  # Weekend
            next_day += timedelta(days=1)
            continue
        if next_day in holidays:
            next_day += timedelta(days=1)
            continue
        return next_day


def check_t_plus_1(
    buy_date: date,
    sell_date: date,
) -> Dict[str, object]:
    """Check if T+1 rule allows selling.
    
    Args:
        buy_date: Date when the stock was bought
        sell_date: Date when attempting to sell
    
    Returns:
        {"allowed": bool, "earliest_sell_date": str, "reason": str}
    """
    earliest = get_next_trading_day(buy_date)
    allowed = sell_date >= earliest
    
    return {
        "allowed": allowed,
        "earliest_sell_date": earliest.isoformat(),
        "reason": "" if allowed else f"T+1 rule: cannot sell until {earliest.isoformat()}",
    }


class TPlus1Tracker:
    """Track T+1 locks for paper trading positions.
    
    Usage:
        tracker = TPlus1Tracker()
        tracker.record_buy("300750", date.today(), 100)
        
        # Later, when attempting to sell:
        if tracker.can_sell("300750", date.today()):
            tracker.record_sell("300750", date.today(), 100)
    """
    
    def __init__(self):
        # symbol -> {locked_date: shares_count}
        self._locks: Dict[str, Dict[date, int]] = {}
    
    def record_buy(self, symbol: str, buy_date: date, shares: int) -> None:
        """Record a buy, creating a T+1 lock."""
        if symbol not in self._locks:
            self._locks[symbol] = {}
        self._locks[symbol][buy_date] = self._locks[symbol].get(buy_date, 0) + shares
    
    def can_sell(self, symbol: str, sell_date: date, shares: int = 0) -> bool:
        """Check if shares can be sold on sell_date (not locked by T+1)."""
        if symbol not in self._locks:
            return True
        
        # Count shares available (bought before today's trading day)
        available = 0
        for buy_date, count in self._locks[symbol].items():
            if buy_date < sell_date:  # Only shares bought on previous days
                available += count
        
        if shares > 0:
            return available >= shares
        return available > 0
    
    def get_locked_shares(self, symbol: str, current_date: date) -> int:
        """Get number of shares locked by T+1 on current_date."""
        if symbol not in self._locks:
            return 0
        return sum(
            count for buy_date, count in self._locks[symbol].items()
            if buy_date >= current_date
        )
    
    def cleanup_expired(self, current_date: date) -> None:
        """Remove expired lock entries (bought before current_date)."""
        for symbol in list(self._locks.keys()):
            self._locks[symbol] = {
                d: c for d, c in self._locks[symbol].items()
                if d >= current_date
            }
            if not self._locks[symbol]:
                del self._locks[symbol]
