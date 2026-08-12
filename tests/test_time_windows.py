from datetime import datetime

from org_timeviz.time_windows import (
    TimeWindow,
    at_midnight,
    iter_month_windows,
    label_range,
    month_start,
    next_month_start,
    window_last_n_days,
)


def test_midnight_and_month_boundaries() -> None:
    value = datetime(2026, 8, 11, 13, 42)
    assert at_midnight(value) == datetime(2026, 8, 11)
    assert month_start(value) == datetime(2026, 8, 1)
    assert next_month_start(value) == datetime(2026, 9, 1)
    assert next_month_start(datetime(2026, 12, 5)) == datetime(2027, 1, 1)


def test_window_last_n_days_is_midnight_aligned_and_includes_today() -> None:
    window = window_last_n_days(datetime(2026, 8, 11, 12), 7)
    assert window.start == datetime(2026, 8, 5)
    assert window.end == datetime(2026, 8, 12)


def test_iter_month_windows_covers_full_months() -> None:
    windows = iter_month_windows(datetime(2025, 12, 20), datetime(2026, 2, 3))
    assert [(w.start, w.end) for w in windows] == [
        (datetime(2025, 12, 1), datetime(2026, 1, 1)),
        (datetime(2026, 1, 1), datetime(2026, 2, 1)),
        (datetime(2026, 2, 1), datetime(2026, 3, 1)),
    ]


def test_label_range_uses_inclusive_display_end() -> None:
    window = TimeWindow("month", datetime(2026, 1, 1), datetime(2026, 2, 1))
    assert label_range(window) == "2026-01-01_to_2026-01-31"
