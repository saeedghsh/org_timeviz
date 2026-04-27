"""Orchestrate parsing, filtering, aggregation, and artifact generation."""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .aggregate import Aggregates, compute_aggregates
from .calendar_view import plot_calendar_view
from .config import AppConfig
from .emacs_agenda import read_agenda_files_from_emacs_init
from .emacs_batch import parse_org_clock_records_emacs
from .filters import ClippedRecord, apply_filters, clip_to_window
from .index_html import write_index_html
from .models import ClockRecord
from .plots import plot_bar_by_time_bucket, plot_timeseries_daily_total, write_summary_json
from .time_buckets import (
    compute_monthly_time_buckets,
    plot_monthly_time_buckets,
    write_monthly_time_buckets_summary_json,
)
from .time_windows import (
    TimeWindow,
    at_midnight,
    iter_month_windows,
    iter_week_windows,
    label_range,
    window_last_n_days,
)

_LOG = logging.getLogger(__name__)
ASSETS_DIR_NAME = "assets"


def _latest_label(window: TimeWindow) -> str:
    """Build a stable label for the latest rolling window."""
    return f"{label_range(window)}__latest"


@dataclass(frozen=True)
class _OrgInputs:
    org_files: list[Path]
    agenda_init_path: Path | None


def _first_existing_init_path(paths: list[str]) -> Path | None:
    for path_str in paths:
        path_obj = Path(path_str).expanduser()
        if path_obj.exists():
            return path_obj
    return None


def _resolve_org_inputs(cfg: AppConfig) -> _OrgInputs:
    if cfg.org_sources.mode == "explicit":
        org_files = [Path(path_str).expanduser() for path_str in cfg.org_sources.explicit_files]
        agenda_init_path = _first_existing_init_path(cfg.org_sources.emacs_init_paths)
        return _OrgInputs(org_files=org_files, agenda_init_path=agenda_init_path)

    for path_str in cfg.org_sources.emacs_init_paths:
        init_path = Path(path_str).expanduser()
        result = read_agenda_files_from_emacs_init(
            init_path,
            var_name=cfg.org_sources.emacs_agenda_var,
        )
        if result is not None and result.files:
            return _OrgInputs(org_files=result.files, agenda_init_path=result.source_path)

    raise FileNotFoundError(
        "Could not find org-agenda-files in any of: " + ", ".join(cfg.org_sources.emacs_init_paths)
    )


def _set_emacs_init_env(cfg: AppConfig, preferred_init_path: Path | None) -> None:
    candidates: list[Path] = []
    if preferred_init_path is not None:
        candidates.append(preferred_init_path)

    for path_str in cfg.org_sources.emacs_init_paths:
        path_obj = Path(path_str).expanduser()
        if path_obj.exists() and path_obj not in candidates:
            candidates.append(path_obj)

    for init_path in candidates:
        if init_path.exists():
            os.environ["ORG_TIMEVIZ_EMACS_INIT"] = str(init_path)
            os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)
            return

    os.environ.pop("ORG_TIMEVIZ_EMACS_INIT", None)
    os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)


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


def _write_time_bucket_report(
    aggs: Aggregates,
    assets_root: Path,
    stem: str,
    top_k: int,
) -> None:
    """Write the time-bucket bar plot and its summary."""
    plot_bar_by_time_bucket(aggs, assets_root / f"{stem}.png", top_k=top_k)
    write_summary_json(aggs, assets_root / f"{stem}__summary.json")


def _write_calendar_report(
    filtered_records: list[ClippedRecord],
    aggs: Aggregates,
    assets_root: Path,
    *,
    period: str,
    label: str,
    top_k_tasks: int,
) -> None:
    """Write the calendar-like day/time plot and its summary."""
    stem = f"calendar_view__task__{period}__{label}"
    title = f"Calendar view ({period}: {label})"
    plot_calendar_view(
        filtered_records,
        assets_root / f"{stem}.png",
        title=title,
        top_k_tasks=top_k_tasks,
    )
    write_summary_json(aggs, assets_root / f"{stem}__summary.json")


def _write_window_reports(
    filtered_records: list[ClippedRecord],
    aggs: Aggregates,
    assets_root: Path,
    *,
    period: str,
    label: str,
    top_k_tasks: int,
    top_k_time_buckets: int,
) -> None:
    """Write time-bucket histograms and monthly calendar views for one window."""
    _write_time_bucket_report(
        aggs,
        assets_root,
        f"histogram__time_bucket__{period}__{label}",
        top_k=top_k_time_buckets,
    )
    if period == "month":
        _write_calendar_report(
            filtered_records,
            aggs,
            assets_root,
            period=period,
            label=label,
            top_k_tasks=top_k_tasks,
        )


def _write_timeseries_report(
    aggs: Aggregates,
    assets_root: Path,
    stem: str,
    rolling_days: int,
) -> None:
    """Write the daily-total timeseries plot and its summary."""
    plot_timeseries_daily_total(
        aggs,
        assets_root / f"{stem}.png",
        rolling_days=rolling_days,
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

    inputs = _resolve_org_inputs(cfg)
    _LOG.info("Using %s org file(s)", len(inputs.org_files))

    _set_emacs_init_env(cfg, inputs.agenda_init_path)

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

    top_k_tasks = cfg.reports.plots.top_k_tasks
    top_k_time_buckets = cfg.reports.plots.top_k_tags

    for period, window in (
        ("week", window_last_n_days(now, 7)),
        ("month", window_last_n_days(now, 30)),
    ):
        filtered_records = _build_filtered_records(cfg, records, window)
        aggs = _build_aggs_from_filtered(cfg, filtered_records)
        _write_window_reports(
            filtered_records,
            aggs,
            assets_root,
            period=period,
            label=_latest_label(window),
            top_k_tasks=top_k_tasks,
            top_k_time_buckets=top_k_time_buckets,
        )

    for window in iter_week_windows(min_dt, max_dt):
        filtered_records = _build_filtered_records(cfg, records, window)
        aggs = _build_aggs_from_filtered(cfg, filtered_records)
        _write_window_reports(
            filtered_records,
            aggs,
            assets_root,
            period="week",
            label=label_range(window),
            top_k_tasks=top_k_tasks,
            top_k_time_buckets=top_k_time_buckets,
        )

    for window in iter_month_windows(min_dt, max_dt):
        filtered_records = _build_filtered_records(cfg, records, window)
        aggs = _build_aggs_from_filtered(cfg, filtered_records)
        _write_window_reports(
            filtered_records,
            aggs,
            assets_root,
            period="month",
            label=label_range(window),
            top_k_tasks=top_k_tasks,
            top_k_time_buckets=top_k_time_buckets,
        )

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
        rolling_days=cfg.reports.plots.timeseries_rolling_days,
    )

    all_time_window = TimeWindow(
        name="all_time",
        start=at_midnight(min_dt),
        end=at_midnight(max_dt) + timedelta(days=1),
    )
    all_time_records = _build_filtered_records(cfg, records, all_time_window)
    _write_time_buckets_report(all_time_records, assets_root, cfg)

    _LOG.info("Wrote report artifacts to %s", assets_root)

    index_path = write_index_html(out_root=out_root, assets_dir=assets_root)
    _LOG.info("Wrote index page to %s", index_path)
