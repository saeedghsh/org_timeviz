"""Orchestrate parsing, filtering, aggregation, and artifact generation."""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .aggregate import compute_aggregates
from .config import AppConfig
from .emacs_agenda import read_agenda_files_from_emacs_init
from .emacs_batch import parse_org_clock_records_emacs
from .filters import apply_filters, clip_to_window
from .plots import (
    plot_bar_by_tag,
    plot_bar_by_task,
    plot_timeseries_daily_total,
    write_summary_json,
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


@dataclass(frozen=True)
class _OrgInputs:
    org_files: list[Path]
    agenda_init_path: Path | None


def _first_existing_init_path(paths: list[str]) -> Path | None:
    for p in paths:
        pp = Path(p).expanduser()
        if pp.exists():
            return pp
    return None


def _resolve_org_inputs(cfg: AppConfig) -> _OrgInputs:
    if cfg.org_sources.mode == "explicit":
        org_files = [Path(p).expanduser() for p in cfg.org_sources.explicit_files]
        agenda_init_path = _first_existing_init_path(cfg.org_sources.emacs_init_paths)
        return _OrgInputs(org_files=org_files, agenda_init_path=agenda_init_path)

    for p in cfg.org_sources.emacs_init_paths:
        init_path = Path(p).expanduser()
        res = read_agenda_files_from_emacs_init(
            init_path, var_name=cfg.org_sources.emacs_agenda_var
        )
        if res is not None and res.files:
            return _OrgInputs(org_files=res.files, agenda_init_path=res.source_path)

    raise FileNotFoundError(
        "Could not find org-agenda-files in any of: " + ", ".join(cfg.org_sources.emacs_init_paths)
    )


def _set_emacs_init_env(cfg: AppConfig, preferred_init_path: Path | None) -> None:
    candidates: list[Path] = []
    if preferred_init_path is not None:
        candidates.append(preferred_init_path)

    for p in cfg.org_sources.emacs_init_paths:
        pp = Path(p).expanduser()
        if pp.exists() and pp not in candidates:
            candidates.append(pp)

    # Prefer the first existing candidate; Emacs/Elisp will read it robustly.
    for init_path in candidates:
        if init_path.exists():
            os.environ["ORG_TIMEVIZ_EMACS_INIT"] = str(init_path)
            # Ensure no stale override remains.
            os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)
            return

    # If nothing found, unset it (exporter will just not customize todo keywords).
    os.environ.pop("ORG_TIMEVIZ_EMACS_INIT", None)
    os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)


def _build_aggs(cfg: AppConfig, records, window: TimeWindow):
    clipped = clip_to_window(records, window=window)
    filtered = apply_filters(clipped, cfg=cfg.reports.filters)
    return compute_aggregates(filtered)


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
    out_root.mkdir(parents=True, exist_ok=True)

    plots_cfg = cfg.reports.plots

    min_dt = min(r.start for r in records)
    max_dt = max(r.end for r in records)

    # Fixed "last" windows.
    w_last7 = window_last_n_days(now, 7)
    w_last30 = window_last_n_days(now, 30)

    aggs = _build_aggs(cfg, records, w_last7)
    plot_bar_by_task(aggs, out_root / "by_task_week_last.png", top_k=plots_cfg.top_k_tasks)
    write_summary_json(aggs, out_root / "by_task_week_last__summary.json")
    plot_bar_by_tag(aggs, out_root / "by_tags_week_last.png", top_k=plots_cfg.top_k_tags)
    write_summary_json(aggs, out_root / "by_tags_week_last__summary.json")

    aggs = _build_aggs(cfg, records, w_last30)
    plot_bar_by_task(aggs, out_root / "by_task_month_last.png", top_k=plots_cfg.top_k_tasks)
    write_summary_json(aggs, out_root / "by_task_month_last__summary.json")
    plot_bar_by_tag(aggs, out_root / "by_tags_month_last.png", top_k=plots_cfg.top_k_tags)
    write_summary_json(aggs, out_root / "by_tags_month_last__summary.json")

    # All weeks (Mon..Sun) and all months in the data range.
    for w in iter_week_windows(min_dt, max_dt):
        label = label_range(w)
        aggs = _build_aggs(cfg, records, w)

        plot_bar_by_task(
            aggs,
            out_root / f"by_task_week_{label}.png",
            top_k=plots_cfg.top_k_tasks,
        )
        write_summary_json(aggs, out_root / f"by_task_week_{label}__summary.json")

        plot_bar_by_tag(
            aggs,
            out_root / f"by_tags_week_{label}.png",
            top_k=plots_cfg.top_k_tags,
        )
        write_summary_json(aggs, out_root / f"by_tags_week_{label}__summary.json")

    for m in iter_month_windows(min_dt, max_dt):
        label = label_range(m)
        aggs = _build_aggs(cfg, records, m)

        plot_bar_by_task(
            aggs,
            out_root / f"by_task_month_{label}.png",
            top_k=plots_cfg.top_k_tasks,
        )
        write_summary_json(aggs, out_root / f"by_task_month_{label}__summary.json")

        plot_bar_by_tag(
            aggs,
            out_root / f"by_tags_month_{label}.png",
            top_k=plots_cfg.top_k_tags,
        )
        write_summary_json(aggs, out_root / f"by_tags_month_{label}__summary.json")

    # One timeseries: last n-days if configured, else all time.
    if plots_cfg.timeseries_last_n_days is None:
        ts_start = at_midnight(min_dt)
        ts_end = at_midnight(max_dt) + timedelta(days=1)
    else:
        ts_window = window_last_n_days(now, plots_cfg.timeseries_last_n_days)
        ts_start, ts_end = ts_window.start, ts_window.end

    ts_window = TimeWindow(name="timeseries", start=ts_start, end=ts_end)
    aggs = _build_aggs(cfg, records, ts_window)

    plot_timeseries_daily_total(
        aggs,
        out_root / "timeseries_daily_total.png",
        rolling_days=plots_cfg.timeseries_rolling_days,
    )
    write_summary_json(aggs, out_root / "timeseries_daily_total__summary.json")

    _LOG.info("Wrote report artifacts to %s", out_root)
