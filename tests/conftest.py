from datetime import datetime
from pathlib import Path

import pytest

from org_timeviz.config import TimeBucketsConfig
from org_timeviz.filters import ClippedRecord
from org_timeviz.models import ClockRecord


@pytest.fixture
def bucket_cfg() -> TimeBucketsConfig:
    return TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["work", "study", "other"],
            "tag_to_bucket": {"job": "work", "course": "study"},
            "resolution": {
                "default_strategy": "priority",
                "priority_order": ["work", "study", "other"],
                "weights": {},
                "rules": [],
            },
        }
    )


def make_record(
    *,
    start: datetime,
    end: datetime,
    tags: tuple[str, ...] = (),
    headline: str = "Task",
    outline_path: str | None = None,
    file_path: Path | None = None,
) -> ClockRecord:
    return ClockRecord(
        file_path=file_path or Path("sample.org"),
        outline_path=outline_path or headline,
        headline=headline,
        tags=tags,
        start=start,
        end=end,
    )


def make_clipped(record: ClockRecord, *, start: datetime | None = None, end: datetime | None = None) -> ClippedRecord:
    clipped_start = start or record.start
    clipped_end = end or record.end
    minutes = int((clipped_end - clipped_start).total_seconds() // 60)
    return ClippedRecord(record=record, start=clipped_start, end=clipped_end, minutes=minutes)
