"""Orchestrate parsing, filtering, aggregation, and artifact generation."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from .aggregate import Aggregates, compute_aggregates
from .config import AppConfig
from .filters import ClippedRecord, apply_filters, clip_to_window
from .models import ClockRecord
from .org_source.emacs import parse_org_clock_records_emacs
from .org_source.inputs import configure_emacs_init, resolve_org_inputs
from .rendering.index import INTERACTIVE_TIME_BUCKET_DASHBOARD_NAME, write_index_html
from .rendering.interactive_time_bucket import write_interactive_time_bucket_dashboard
from .rendering.monthly_time_buckets import (
    compute_monthly_time_buckets,
    plot_monthly_time_buckets,
    write_monthly_time_buckets_summary_json,
)
from .rendering.plots import plot_timeseries_daily_total, write_summary_json
from .time_windows import (
    TimeWindow,
    at_midnight,
    label_range,
    window_last_n_days,
)

_LOG = logging.getLogger(__name__)
ASSETS_DIR_NAME = "assets"


def _latest_label(window: TimeWindow) -> str:
    """Build a stable label for the latest rolling window."""
    return f"{label_range(window)}__latest"


def _build_filtered_records(
    cfg: AppConfig,
    records: list[ClockRecord],
    window: TimeWindow,
) -> list[ClippedRecord]:
    """Clip records to a time window and apply report filters."""
    clipped = clip_to_window(records, window=window)
    return apply_filters(clipped, cfg=cfg.reports.filters)


def _build_aggs_from_filtered(cfg: AppConfig, records: list[ClippedRecord]) -> Aggregates:
    """Compute aggregates from already-filtered clipped records."""
    return compute_aggregates(records, cfg.time_buckets)


def _write_timeseries_report(
    aggs: Aggregates,
    assets_root: Path,
    stem: str,
) -> None:
    """Write the daily-total timeseries plot and its summary."""
    plot_timeseries_daily_total(
        aggs,
        assets_root / f"{stem}.png",
    )
    write_summary_json(aggs, assets_root / f"{stem}__summary.json")


def _write_time_buckets_report(
    filtered_records: list[ClippedRecord],
    assets_root: Path,
    cfg: AppConfig,
) -> None:
    """Write the monthly time-bucket plot and its summary."""
    stem = "timeseries__time_bucket__month__all_time"
    report = compute_monthly_time_buckets(filtered_records, cfg.time_buckets)
    plot_monthly_time_buckets(report, assets_root / f"{stem}.png")
    write_monthly_time_buckets_summary_json(report, assets_root / f"{stem}__summary.json")


def generate_all_reports(cfg: AppConfig) -> None:
    """Generate the fixed set of reports and write artifacts under the output root."""
    now = datetime.now()

    inputs = resolve_org_inputs(cfg)
    _LOG.info("Using %s org file(s)", len(inputs.org_files))

    configure_emacs_init(cfg, inputs.agenda_init_path)

    records = parse_org_clock_records_emacs(org_files=inputs.org_files)
    if not records:
        _LOG.warning("No clock records found.")
        return

    out_root = Path(cfg.app.output_dir).expanduser().resolve()
    assets_root = out_root / ASSETS_DIR_NAME
    out_root.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    min_dt = min(record.start for record in records)
    max_dt = max(record.end for record in records)

    if cfg.reports.plots.timeseries_last_n_days is None:
        ts_window = TimeWindow(
            name="timeseries",
            start=at_midnight(min_dt),
            end=at_midnight(max_dt) + timedelta(days=1),
        )
        ts_label = "all_time"
    else:
        ts_cfg_window = window_last_n_days(now, cfg.reports.plots.timeseries_last_n_days)
        ts_window = TimeWindow(
            name="timeseries",
            start=ts_cfg_window.start,
            end=ts_cfg_window.end,
        )
        ts_label = _latest_label(ts_window)

    ts_records = _build_filtered_records(cfg, records, ts_window)
    _write_timeseries_report(
        _build_aggs_from_filtered(cfg, ts_records),
        assets_root,
        f"timeseries__daily_working_hours__day__{ts_label}",
    )

    all_time_window = TimeWindow(
        name="all_time",
        start=at_midnight(min_dt),
        end=at_midnight(max_dt) + timedelta(days=1),
    )
    all_time_records = _build_filtered_records(cfg, records, all_time_window)
    _write_time_buckets_report(all_time_records, assets_root, cfg)

    initial_interactive_window = window_last_n_days(now, 30)
    write_interactive_time_bucket_dashboard(
        all_time_records,
        assets_root / INTERACTIVE_TIME_BUCKET_DASHBOARD_NAME,
        time_buckets_cfg=cfg.time_buckets,
        low_opacity_task_titles=(
            cfg.reports.plots.calendar_view_by_time_bucket.low_opacity_task_titles
        ),
        initial_start=initial_interactive_window.start,
        initial_end=initial_interactive_window.end,
    )

    _LOG.info("Wrote report artifacts to %s", assets_root)

    index_path = write_index_html(out_root=out_root, assets_dir=assets_root)
    _LOG.info("Wrote index page to %s", index_path)
