import logging
from datetime import datetime
from pathlib import Path

from org_timeviz.aggregate import compute_aggregates
from org_timeviz.config import AppConfig, PlotConfig
from org_timeviz.emacs_agenda import read_agenda_files_from_emacs_init
from org_timeviz.emacs_batch import parse_org_clock_records_emacs
from org_timeviz.filters import apply_filters, clip_to_window
from org_timeviz.plots import (
    plot_bar_by_tag,
    plot_bar_by_task,
    plot_timeseries_daily_total,
    write_summary_json,
)
from org_timeviz.time_windows import resolve_time_windows

_LOG = logging.getLogger(__name__)


def _resolve_org_files(cfg: AppConfig) -> list[Path]:
    if cfg.org_sources.mode == "explicit":
        return [Path(p).expanduser() for p in cfg.org_sources.explicit_files]

    for p in cfg.org_sources.emacs_init_paths:
        init_path = Path(p).expanduser()
        res = read_agenda_files_from_emacs_init(
            init_path, var_name=cfg.org_sources.emacs_agenda_var
        )
        if res is not None and res.files:
            return res.files

    raise FileNotFoundError(
        "Could not find org-agenda-files in any of: " + ", ".join(cfg.org_sources.emacs_init_paths)
    )


def _plot_one(aggs, plot_cfg: PlotConfig, out_dir: Path) -> None:
    if plot_cfg.kind == "bar_by_tag":
        plot_bar_by_tag(aggs, out_dir / "bar_by_tag.png", top_k=plot_cfg.top_k)
        return
    if plot_cfg.kind == "bar_by_task":
        plot_bar_by_task(aggs, out_dir / "bar_by_task.png", top_k=plot_cfg.top_k)
        return
    if plot_cfg.kind == "timeseries_daily_total":
        plot_timeseries_daily_total(
            aggs, out_dir / "timeseries_daily_total.png", rolling_days=plot_cfg.rolling_days
        )
        return

    raise ValueError(f"Unknown plot kind: {plot_cfg.kind}")


def _parse_records(cfg: AppConfig, org_files: list[Path]):
    return parse_org_clock_records_emacs(
        org_files=org_files,
        emacs_executable=cfg.parser.emacs_executable,
    )


def generate_all_reports(cfg: AppConfig) -> None:
    now = datetime.now()
    windows = resolve_time_windows(cfg.periods, now=now)

    org_files = _resolve_org_files(cfg)
    _LOG.info("Using %s org file(s)", len(org_files))

    all_records = _parse_records(cfg, org_files=org_files)

    out_root = Path(cfg.app.output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    for rep in cfg.reports:
        if rep.period not in windows:
            raise KeyError(f"Report {rep.name!r} refers to unknown period {rep.period!r}")

        window = windows[rep.period]
        _LOG.info(
            "Report %s: window %s (%s .. %s)", rep.name, window.name, window.start, window.end
        )

        clipped = clip_to_window(all_records, window=window)
        filtered = apply_filters(clipped, cfg=rep.filters)
        aggs = compute_aggregates(filtered)

        rep_out = out_root / rep.name
        rep_out.mkdir(parents=True, exist_ok=True)

        for p in rep.plots:
            _plot_one(aggs, plot_cfg=p, out_dir=rep_out)

        write_summary_json(aggs, rep_out / "summary.json")

        _LOG.info("Wrote report artifacts to %s", rep_out)
