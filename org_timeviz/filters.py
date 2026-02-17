from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from org_timeviz.config import FiltersConfig
from org_timeviz.org_parser import ClockRecord
from org_timeviz.time_windows import TimeWindow


@dataclass(frozen=True)
class ClippedRecord:
    record: ClockRecord
    start: datetime
    end: datetime
    minutes: int


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> tuple[datetime, datetime] | None:
    start = max(a0, b0)
    end = min(a1, b1)
    if end <= start:
        return None
    return start, end


def _minutes_between(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def clip_to_window(records: Iterable[ClockRecord], window: TimeWindow) -> list[ClippedRecord]:
    clipped: list[ClippedRecord] = []
    for r in records:
        ov = _overlap(r.start, r.end, window.start, window.end)
        if ov is None:
            continue
        s, e = ov
        mins = _minutes_between(s, e)
        if mins <= 0:
            continue
        clipped.append(ClippedRecord(record=r, start=s, end=e, minutes=mins))
    return clipped


def apply_filters(records: Iterable[ClippedRecord], cfg: FiltersConfig) -> list[ClippedRecord]:
    include_tags = set(cfg.include_tags)
    exclude_tags = set(cfg.exclude_tags)

    include_task_res = [re.compile(p) for p in cfg.include_task_regex]
    exclude_task_res = [re.compile(p) for p in cfg.exclude_task_regex]

    def tags_ok(tags: tuple[str, ...]) -> bool:
        tagset = set(tags)
        if exclude_tags and (tagset & exclude_tags):
            return False
        if not include_tags:
            return True
        if cfg.tag_match_mode == "all":
            return include_tags.issubset(tagset)
        return bool(tagset & include_tags)

    def task_ok(outline_path: str) -> bool:
        if exclude_task_res and any(rx.search(outline_path) for rx in exclude_task_res):
            return False
        if include_task_res and not any(rx.search(outline_path) for rx in include_task_res):
            return False
        return True

    out: list[ClippedRecord] = []
    for cr in records:
        if not tags_ok(cr.record.tags):
            continue
        if not task_ok(cr.record.outline_path):
            continue
        out.append(cr)

    return out
