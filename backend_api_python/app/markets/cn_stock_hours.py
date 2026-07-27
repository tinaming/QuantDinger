"""A-share (CNStock) trading hours and session detection for ChanQuant.

Handles Chinese mainland stock market trading schedule:
- Pre-market auction: 09:15 - 09:25 (CST/Asia/Shanghai)
- Morning session: 09:30 - 11:30
- Lunch break: 11:30 - 13:00
- Afternoon session: 13:00 - 15:00
- Weekends and configurable holidays: closed
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time, date
from typing import Optional, Dict

# Default holidays can be overridden via CN_HOLIDAYS env var (JSON list of "YYYY-MM-DD")
# Example: CN_HOLIDAYS='["2026-01-01","2026-01-02","2026-01-03"]'

_PRE_MARKET_OPEN = time(9, 15)
_PRE_MARKET_CLOSE = time(9, 25)
_MORNING_OPEN = time(9, 30)
_MORNING_CLOSE = time(11, 30)
_AFTERNOON_OPEN = time(13, 0)
_AFTERNOON_CLOSE = time(15, 0)


def _get_holidays() -> set[date]:
    """Load holidays from CN_HOLIDAYS env var or return empty set."""
    raw = os.getenv("CN_HOLIDAYS", "").strip()
    if not raw:
        return set()
    try:
        dates = json.loads(raw)
        return {date.fromisoformat(d) for d in dates if d}
    except (json.JSONDecodeError, ValueError):
        return set()


def _to_shanghai_time(dt: datetime) -> datetime:
    """Convert datetime to Asia/Shanghai timezone.

    If the datetime is naive, it is interpreted as *local container time*
    (which may already be CST).  To avoid double-offset bugs we simply
    replace tzinfo with Asia/Shanghai for naive datetimes.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Shanghai")
        if dt.tzinfo is None:
            # Naive datetime from datetime.now() is container-local time.
            # The container TZ is typically already Asia/Shanghai (+0800),
            # so just tag it — do NOT assume UTC and add 8h again.
            return dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    except ImportError:
        # Fallback: assume already in Shanghai time
        return dt


def is_cn_market_open(now: datetime | None = None) -> bool:
    """Check if A-share market is currently in a trading session."""
    if now is None:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
        except ImportError:
            now = datetime.now()
    now = _to_shanghai_time(now)
    
    # Weekend check
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Holiday check
    if now.date() in _get_holidays():
        return False
    
    t = now.time()
    return (_MORNING_OPEN <= t <= _MORNING_CLOSE or
            _AFTERNOON_OPEN <= t <= _AFTERNOON_CLOSE)


def get_cn_market_session(now: datetime | None = None) -> str:
    """Get current market session name.
    
    Returns one of: "pre-market", "morning", "lunch-break", "afternoon", "closed"
    """
    if now is None:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
        except ImportError:
            now = datetime.now()
    now = _to_shanghai_time(now)
    
    if now.weekday() >= 5 or now.date() in _get_holidays():
        return "closed"
    
    t = now.time()
    if _PRE_MARKET_OPEN <= t < _PRE_MARKET_CLOSE:
        return "pre-market"
    elif _PRE_MARKET_CLOSE <= t < _MORNING_OPEN:
        return "pre-market"
    elif _MORNING_OPEN <= t <= _MORNING_CLOSE:
        return "morning"
    elif _MORNING_CLOSE < t < _AFTERNOON_OPEN:
        return "lunch-break"
    elif _AFTERNOON_OPEN <= t <= _AFTERNOON_CLOSE:
        return "afternoon"
    else:
        return "closed"


def next_cn_market_event(now: datetime | None = None) -> Dict:
    """Get the next market event (open/close/lunch).
    
    Returns: {"event": str, "time": str (ISO format), "session": str}
    """
    if now is None:
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
        except ImportError:
            now = datetime.now()
    now = _to_shanghai_time(now)
    
    t = now.time()
    today = now.date()
    
    events = [
        ("pre-market-open", _PRE_MARKET_OPEN, "pre-market"),
        ("morning-open", _MORNING_OPEN, "morning"),
        ("morning-close", _MORNING_CLOSE, "lunch-break"),
        ("afternoon-open", _AFTERNOON_OPEN, "afternoon"),
        ("afternoon-close", _AFTERNOON_CLOSE, "closed"),
    ]
    
    for event_name, event_time, next_session in events:
        if t < event_time:
            from datetime import datetime as dt_cls
            event_dt = dt_cls.combine(today, event_time)
            return {
                "event": event_name,
                "time": event_dt.isoformat(),
                "session": next_session,
            }
    
    # All events passed today, next event is tomorrow's pre-market
    from datetime import timedelta
    tomorrow = today + timedelta(days=1)
    # Skip weekends
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)
    
    event_dt = datetime.combine(tomorrow, _PRE_MARKET_OPEN)
    return {
        "event": "pre-market-open",
        "time": event_dt.isoformat(),
        "session": "pre-market",
    }
