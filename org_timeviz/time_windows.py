"""Compute time windows used for clipping clock intervals."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TimeWindow:
    """Represent a half-open time window [start, end) in local time."""

    name: str
    start: datetime
    end: datetime  # exclusive


def at_midnight(dt: datetime) -> datetime:
    """Return dt truncated to local midnight."""
    return datetime(dt.year, dt.month, dt.day)


def window_last_n_days(now: datetime, n: int) -> TimeWindow:
    """Return the last n days as a midnight-aligned window."""
    end = at_midnight(now) + timedelta(days=1)
    start = end - timedelta(days=n)
    return TimeWindow(name=f"last_{n}_days", start=start, end=end)


def week_start_monday(dt: datetime) -> datetime:
    """Return the Monday (00:00) for the week containing dt."""
    day0 = at_midnight(dt)
    return day0 - timedelta(days=day0.weekday())


def month_start(dt: datetime) -> datetime:
    """Return the first day (00:00) of dt's month."""
    day0 = at_midnight(dt)
    return datetime(day0.year, day0.month, 1)


def next_month_start(dt: datetime) -> datetime:
    """Return the first day (00:00) of the month after dt."""
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1)
    return datetime(dt.year, dt.month + 1, 1)


def iter_week_windows(min_dt: datetime, max_dt: datetime) -> list[TimeWindow]:
    """Return Monday-to-Monday windows covering [min_dt, max_dt]."""
    start = week_start_monday(min_dt)
    end = week_start_monday(max_dt) + timedelta(days=7)

    windows: list[TimeWindow] = []
    cur = start
    while cur < end:
        windows.append(TimeWindow(name="week", start=cur, end=cur + timedelta(days=7)))
        cur = cur + timedelta(days=7)
    return windows


def iter_month_windows(min_dt: datetime, max_dt: datetime) -> list[TimeWindow]:
    """Return calendar-month windows covering [min_dt, max_dt]."""
    start = month_start(min_dt)
    end = next_month_start(month_start(max_dt))

    windows: list[TimeWindow] = []
    cur = start
    while cur < end:
        nxt = next_month_start(cur)
        windows.append(TimeWindow(name="month", start=cur, end=nxt))
        cur = nxt
    return windows


def label_range(window: TimeWindow) -> str:
    """Return YYYY-MM-DD_to_YYYY-MM-DD label for the window (inclusive end)."""
    start = window.start.date().isoformat()
    end_inclusive = (window.end - timedelta(days=1)).date().isoformat()
    return f"{start}_to_{end_inclusive}"
