"""Aggregate filtered clock records into time-bucket/task/day totals."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .config import TimeBucketsConfig
from .filters import ClippedRecord
from .time_bucket_resolver import resolve_time_bucket_allocations


@dataclass(frozen=True)
class Aggregates:
    """Hold computed time totals across several common groupings."""

    minutes_total: int
    minutes_by_time_bucket: dict[str, float]
    minutes_by_task: dict[str, int]
    minutes_by_day: dict[date, int]


def compute_aggregates(
    records: Iterable[ClippedRecord],
    time_buckets_cfg: TimeBucketsConfig,
) -> Aggregates:
    """Compute total minutes and breakdowns by time bucket, task, and day."""
    minutes_by_time_bucket: dict[str, float] = defaultdict(float)
    minutes_by_task: dict[str, int] = defaultdict(int)
    minutes_by_day: dict[date, int] = defaultdict(int)

    total = 0
    for clipped_record in records:
        total += clipped_record.minutes

        allocations = resolve_time_bucket_allocations(
            clipped_record.record.tags,
            time_buckets_cfg,
        )
        for bucket_name, fraction in allocations.items():
            minutes_by_time_bucket[bucket_name] += float(clipped_record.minutes) * fraction

        minutes_by_task[clipped_record.record.outline_path] += clipped_record.minutes

        day = clipped_record.start.date()
        minutes_by_day[day] += clipped_record.minutes

    return Aggregates(
        minutes_total=total,
        minutes_by_time_bucket=dict(minutes_by_time_bucket),
        minutes_by_task=dict(minutes_by_task),
        minutes_by_day=dict(minutes_by_day),
    )
