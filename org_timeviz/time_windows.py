"""Resolve named time windows used to clip clock intervals."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from org_timeviz.config import (
    PeriodConfig,
    PeriodLastNDays,
    PeriodRange,
    PeriodThisMonth,
    PeriodThisWeek,
)


@dataclass(frozen=True)
class TimeWindow:
    """Represent a half-open time window [start, end) in local time."""

    name: str
    start: datetime
    end: datetime  # exclusive


def _at_midnight(dt: datetime) -> datetime:
    return datetime(dt.year, dt.month, dt.day)


def _next_month_start(dt: datetime) -> datetime:
    if dt.month == 12:
        return datetime(dt.year + 1, 1, 1)
    return datetime(dt.year, dt.month + 1, 1)


def resolve_time_windows(periods: Iterable[PeriodConfig], now: datetime) -> dict[str, TimeWindow]:
    """Resolve configured period specs into concrete time windows."""
    windows: dict[str, TimeWindow] = {}

    for p in periods:
        if isinstance(p, PeriodLastNDays):
            if p.align_to_day_boundary:
                end = _at_midnight(now) + timedelta(days=1)
                start = end - timedelta(days=p.n)
            else:
                end = now
                start = now - timedelta(days=p.n)
            windows[p.name] = TimeWindow(name=p.name, start=start, end=end)

        elif isinstance(p, PeriodRange):
            start_date = datetime.strptime(p.start_date, "%Y-%m-%d")
            end_date = datetime.strptime(p.end_date, "%Y-%m-%d")
            start = _at_midnight(start_date)
            end = _at_midnight(end_date) + timedelta(days=1)
            windows[p.name] = TimeWindow(name=p.name, start=start, end=end)

        elif isinstance(p, PeriodThisWeek):
            today = _at_midnight(now)
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=7)
            windows[p.name] = TimeWindow(name=p.name, start=start, end=end)

        elif isinstance(p, PeriodThisMonth):
            today = _at_midnight(now)
            start = datetime(today.year, today.month, 1)
            end = _next_month_start(today)
            windows[p.name] = TimeWindow(name=p.name, start=start, end=end)

        else:
            raise ValueError(f"Unsupported period: {p}")

    return windows
