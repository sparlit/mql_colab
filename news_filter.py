"""NFP/FOMC calendar filter — blocks trading near high-impact events."""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Minutes before/after an event to block trading
NEWS_BUFFER_MINUTES = 30

# NFP: first Friday of each month at 13:30 UTC
# Hardcoded for 2026 (update yearly or use generator)
NFP_TIMES_UTC = [
    datetime(2026, 1, 2, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 2, 6, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 3, 6, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 4, 3, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 5, 8, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 6, 5, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 7, 2, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 9, 4, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc),
    datetime(2026, 12, 4, 13, 30, tzinfo=timezone.utc),
]

# FOMC: 8 meetings per year, typically at 19:00 UTC (2:00 PM ET)
FOMC_TIMES_UTC = [
    datetime(2026, 1, 28, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 3, 18, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 5, 6, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 6, 17, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 7, 29, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 9, 16, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc),
    datetime(2026, 12, 16, 19, 0, tzinfo=timezone.utc),
]

# Configurable holidays — market closed (no trading at all)
HOLIDAYS_UTC = [
    datetime(2026, 1, 1, tzinfo=timezone.utc),
    datetime(2026, 12, 25, tzinfo=timezone.utc),
    datetime(2026, 12, 31, tzinfo=timezone.utc),
]

# Global toggle
NEWS_FILTER_ENABLED = True


def is_holiday(now=None):
    if now is None:
        now = datetime.now(timezone.utc)
    for h in HOLIDAYS_UTC:
        if now.date() == h.date():
            return True
    return False


def _find_nearest_event(now, event_times, buffer_minutes=NEWS_BUFFER_MINUTES):
    buffer = timedelta(minutes=buffer_minutes)
    for event_time in event_times:
        if abs((now - event_time).total_seconds()) <= buffer.total_seconds():
            return event_time, "news_event"
    return None, None


def is_news_window(now=None):
    if not NEWS_FILTER_ENABLED:
        return False, ""
    if now is None:
        now = datetime.now(timezone.utc)
    event_time, event_type = _find_nearest_event(now, NFP_TIMES_UTC)
    if event_time:
        return True, f"NFP at {event_time.strftime('%Y-%m-%d %H:%M UTC')}"
    event_time, event_type = _find_nearest_event(now, FOMC_TIMES_UTC)
    if event_time:
        return True, f"FOMC at {event_time.strftime('%Y-%m-%d %H:%M UTC')}"
    return False, ""
