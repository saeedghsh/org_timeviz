import json
from datetime import date, datetime
from pathlib import Path

import pytest

from org_timeviz.config import TimeBucketsConfig
from org_timeviz.rendering.index import write_index_html
from org_timeviz.rendering.interactive_time_bucket import (
    _bucket_hours_for_interval,
    _calendar_slices,
    _format_minute,
    _prepare_records,
    _script_safe_json,
    _time_bucket_colors,
    write_interactive_time_bucket_dashboard,
)
from org_timeviz.rendering.monthly_time_buckets import (
    compute_monthly_time_buckets,
    plot_monthly_time_buckets,
    write_monthly_time_buckets_summary_json,
)
from org_timeviz.rendering.plots import plot_timeseries_daily_total, write_summary_json
from org_timeviz.aggregate import compute_aggregates

from conftest import make_clipped, make_record


def test_monthly_time_buckets_split_record_across_months(bucket_cfg: TimeBucketsConfig) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 31, 23, 30),
            end=datetime(2026, 2, 1, 0, 30),
            tags=("job",),
        )
    )
    report = compute_monthly_time_buckets([record], bucket_cfg)
    assert report.months == [date(2026, 1, 1), date(2026, 2, 1)]
    assert report.minutes_total_by_month == {date(2026, 1, 1): 30.0, date(2026, 2, 1): 30.0}
    assert report.minutes_by_bucket["work"] == {
        date(2026, 1, 1): 30.0,
        date(2026, 2, 1): 30.0,
    }


def test_monthly_time_bucket_outputs(tmp_path: Path, bucket_cfg: TimeBucketsConfig) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 2, 9),
            end=datetime(2026, 1, 2, 10),
            tags=("job",),
        )
    )
    report = compute_monthly_time_buckets([record], bucket_cfg)
    png = tmp_path / "monthly.png"
    summary = tmp_path / "monthly.json"
    plot_monthly_time_buckets(report, png)
    write_monthly_time_buckets_summary_json(report, summary)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert png.exists() and png.stat().st_size > 0
    assert payload["hours_by_bucket"]["work"]["2026-01-01"] == pytest.approx(1.0)
    assert payload["percent_by_bucket"]["work"]["2026-01-01"] == pytest.approx(100.0)


def test_interactive_preparation_preserves_task_and_dominant_bucket(
    bucket_cfg: TimeBucketsConfig,
) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("course", "job"),
            headline="Actual task title",
        )
    )
    prepared = _prepare_records([record], bucket_cfg)
    assert prepared[0].task_title == "Actual task title"
    assert prepared[0].dominant_bucket == "work"


def test_interactive_calendar_splits_midnight(bucket_cfg: TimeBucketsConfig) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 23, 45),
            end=datetime(2026, 1, 2, 0, 15),
            tags=("job",),
        )
    )
    slices = _calendar_slices(_prepare_records([record], bucket_cfg))
    assert [item.minutes for item in slices] == [15, 15]


def test_bucket_hours_clip_to_visible_interval_and_keep_fixed_order(
    bucket_cfg: TimeBucketsConfig,
) -> None:
    records = [
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 9),
                end=datetime(2026, 1, 1, 11),
                tags=("job",),
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 10),
                end=datetime(2026, 1, 1, 11),
                tags=("course",),
            )
        ),
    ]
    prepared = _prepare_records(records, bucket_cfg)
    values = _bucket_hours_for_interval(
        prepared,
        bucket_order=bucket_cfg.bucket_order,
        start=datetime(2026, 1, 1, 10),
        end=datetime(2026, 1, 1, 10, 30),
    )
    assert values == pytest.approx([0.5, 0.5, 0.0])


def test_interactive_helpers_are_stable(bucket_cfg: TimeBucketsConfig) -> None:
    colors = _time_bucket_colors(bucket_cfg.bucket_order)
    assert list(colors) == bucket_cfg.bucket_order
    assert len(set(colors.values())) == len(colors)
    assert _format_minute(0) == "00:00"
    assert _format_minute(24 * 60) == "24:00"
    assert _script_safe_json('{"x":"</script>"}') == '{"x":"<\\/script>"}'


def test_interactive_dashboard_contains_task_and_linking_script(
    tmp_path: Path, bucket_cfg: TimeBucketsConfig
) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 1, 9),
            end=datetime(2026, 1, 1, 10),
            tags=("job",),
            headline="Hover task",
        )
    )
    out = tmp_path / "interactive.html"
    write_interactive_time_bucket_dashboard(
        [record],
        out,
        time_buckets_cfg=bucket_cfg,
        initial_start=datetime(2026, 1, 1),
        initial_end=datetime(2026, 1, 2),
    )
    text = out.read_text(encoding="utf-8")
    assert "Hover task" in text
    assert 'calendar.on("plotly_relayout"' in text
    assert "bucketHours" in text


def test_timeseries_and_summary_outputs(tmp_path: Path, bucket_cfg: TimeBucketsConfig) -> None:
    records = [
        make_clipped(
            make_record(
                start=datetime(2026, 1, 2, 9),
                end=datetime(2026, 1, 2, 10),
                tags=("job",),
                outline_path="A",
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 5, 9),
                end=datetime(2026, 1, 5, 11),
                tags=("course",),
                outline_path="B",
            )
        ),
    ]
    aggs = compute_aggregates(records, bucket_cfg)
    png = tmp_path / "timeseries.png"
    summary = tmp_path / "summary.json"
    plot_timeseries_daily_total(aggs, png)
    write_summary_json(aggs, summary)
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert png.exists() and png.stat().st_size > 0
    assert payload["hours_total"] == pytest.approx(3.0)
    assert payload["minutes_by_task_top50"] == {"A": 60.0, "B": 120.0}


def test_index_ignores_deprecated_pngs_and_embeds_interactive_dashboard(tmp_path: Path) -> None:
    out_root = tmp_path / "outputs"
    assets = out_root / "assets"
    assets.mkdir(parents=True)
    (assets / "calendar_view__time_bucket__month__old.png").write_bytes(b"old")
    (assets / "histogram__time_bucket__month__old.png").write_bytes(b"old")
    current = "timeseries__daily_working_hours__day__all_time.png"
    (assets / current).write_bytes(b"png")
    (assets / "interactive__time_bucket.html").write_text("dashboard", encoding="utf-8")

    index_path = write_index_html(out_root, assets)
    text = index_path.read_text(encoding="utf-8")
    assert "interactive__time_bucket.html" in text
    assert current in text
    assert "calendar_view__time_bucket__month__old.png" not in text
    assert "histogram__time_bucket__month__old.png" not in text
    assert 'class="outputs-section"' not in text


def test_empty_monthly_and_timeseries_plots_are_still_valid_files(
    tmp_path: Path, bucket_cfg: TimeBucketsConfig
) -> None:
    monthly = compute_monthly_time_buckets([], bucket_cfg)
    monthly_png = tmp_path / "empty-monthly.png"
    plot_monthly_time_buckets(monthly, monthly_png)
    assert monthly_png.exists() and monthly_png.stat().st_size > 0

    empty_aggs = compute_aggregates([], bucket_cfg)
    daily_png = tmp_path / "empty-daily.png"
    plot_timeseries_daily_total(empty_aggs, daily_png)
    assert daily_png.exists() and daily_png.stat().st_size > 0


def test_index_routes_unparsed_pngs_to_other_gallery(tmp_path: Path) -> None:
    out_root = tmp_path / "outputs"
    assets = out_root / "assets"
    assets.mkdir(parents=True)
    (assets / "misc.png").write_bytes(b"png")
    write_index_html(out_root, assets)
    assert "other.html" in (out_root / "index.html").read_text(encoding="utf-8")
    assert "misc.png" in (out_root / "other.html").read_text(encoding="utf-8")
