from datetime import date, datetime

from org_timeviz.aggregate import compute_aggregates
from org_timeviz.config import FiltersConfig, TimeBucketsConfig
from org_timeviz.filters import apply_filters, clip_to_window
from org_timeviz.time_windows import TimeWindow

from conftest import make_clipped, make_record


def test_clip_to_window_clips_and_drops_nonoverlap() -> None:
    records = [
        make_record(start=datetime(2026, 1, 1, 9), end=datetime(2026, 1, 1, 11)),
        make_record(start=datetime(2026, 1, 2, 9), end=datetime(2026, 1, 2, 10)),
    ]
    window = TimeWindow("test", datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 12))
    clipped = clip_to_window(records, window)
    assert len(clipped) == 1
    assert clipped[0].start == datetime(2026, 1, 1, 10)
    assert clipped[0].end == datetime(2026, 1, 1, 11)
    assert clipped[0].minutes == 60


def test_half_open_window_excludes_touching_record() -> None:
    record = make_record(start=datetime(2026, 1, 1, 8), end=datetime(2026, 1, 1, 9))
    window = TimeWindow("test", datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10))
    assert clip_to_window([record], window) == []


def test_apply_filters_handles_tags_and_task_regex() -> None:
    keep = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("work", "focus"),
            outline_path="Project / Keep",
        )
    )
    reject_tag = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 10),
            end=datetime(2026, 1, 1, 11),
            tags=("work", "skip"),
            outline_path="Project / Other",
        )
    )
    cfg = FiltersConfig(
        include_tags=["work", "focus"],
        exclude_tags=["skip"],
        tag_match_mode="all",
        include_task_regex=["Project"],
        exclude_task_regex=["Blocked"],
    )
    assert apply_filters([keep, reject_tag], cfg) == [keep]


def test_apply_filters_any_tag_mode() -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("one",),
        )
    )
    assert apply_filters([record], FiltersConfig(include_tags=["one", "two"])) == [record]


def test_compute_aggregates_tracks_total_task_day_and_bucket(bucket_cfg: TimeBucketsConfig) -> None:
    first = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("job",),
            outline_path="A",
        )
    )
    second = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 10),
            end=datetime(2026, 1, 1, 10, 30),
            tags=("course",),
            outline_path="B",
        )
    )
    aggs = compute_aggregates([first, second], bucket_cfg)
    assert aggs.minutes_total == 90
    assert aggs.minutes_by_task == {"A": 60, "B": 30}
    assert aggs.minutes_by_day == {date(2026, 1, 1): 90}
    assert aggs.minutes_by_time_bucket == {"work": 60.0, "study": 30.0}


def test_apply_filters_excludes_task_regex_and_nonmatching_include() -> None:
    blocked = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            outline_path="Project / Blocked task",
        )
    )
    other = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 10),
            end=datetime(2026, 1, 1, 11),
            outline_path="Personal / Task",
        )
    )
    cfg = FiltersConfig(include_task_regex=["Project"], exclude_task_regex=["Blocked"])
    assert apply_filters([blocked, other], cfg) == []


def test_apply_filters_rejects_missing_required_tag() -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("one",),
        )
    )
    cfg = FiltersConfig(include_tags=["one", "two"], tag_match_mode="all")
    assert apply_filters([record], cfg) == []
