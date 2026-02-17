from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from org_timeviz.filters import ClippedRecord


@dataclass(frozen=True)
class Aggregates:
    minutes_total: int
    minutes_by_tag: dict[str, int]
    minutes_by_task: dict[str, int]
    minutes_by_day: dict[date, int]


def compute_aggregates(records: Iterable[ClippedRecord]) -> Aggregates:
    minutes_by_tag: dict[str, int] = defaultdict(int)
    minutes_by_task: dict[str, int] = defaultdict(int)
    minutes_by_day: dict[date, int] = defaultdict(int)

    total = 0
    for cr in records:
        total += cr.minutes

        tags = cr.record.tags or ("(no-tag)",)
        for t in tags:
            minutes_by_tag[t] += cr.minutes

        minutes_by_task[cr.record.outline_path] += cr.minutes

        day = cr.start.date()
        minutes_by_day[day] += cr.minutes

    return Aggregates(
        minutes_total=total,
        minutes_by_tag=dict(minutes_by_tag),
        minutes_by_task=dict(minutes_by_task),
        minutes_by_day=dict(minutes_by_day),
    )
