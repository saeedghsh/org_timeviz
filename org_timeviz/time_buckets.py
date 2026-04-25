"""Plot monthly time-bucket trends from clipped Org clock records."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Iterable

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .config import TimeBucketsConfig
from .filters import ClippedRecord
from .time_bucket_resolver import resolve_time_bucket_allocations
from .time_windows import month_start, next_month_start

FIGSIZE: Final[tuple[float, float]] = (22.0, 10.0)


@dataclass(frozen=True)
class MonthlyTimeBuckets:
    """Hold monthly totals and bucket breakdowns."""

    bucket_order: list[str]
    months: list[date]
    minutes_total_by_month: dict[date, float]
    minutes_by_bucket: dict[str, dict[date, float]]


def compute_monthly_time_buckets(
    records: Iterable[ClippedRecord],
    cfg: TimeBucketsConfig,
) -> MonthlyTimeBuckets:
    """Aggregate clipped records by calendar month and time-bucket."""
    minutes_total_by_month: dict[date, float] = defaultdict(float)
    raw_minutes_by_bucket: dict[str, dict[date, float]] = {
        bucket_name: defaultdict(float) for bucket_name in cfg.bucket_order
    }

    for record in records:
        allocations = resolve_time_bucket_allocations(record.record.tags, cfg)

        for month_key, minutes in _split_record_across_months(record):
            minutes_total_by_month[month_key] += float(minutes)

            for bucket_name, fraction in allocations.items():
                raw_minutes_by_bucket[bucket_name][month_key] += float(minutes) * fraction

    months = sorted(minutes_total_by_month.keys())
    minutes_by_bucket: dict[str, dict[date, float]] = {}

    for bucket_name in cfg.bucket_order:
        minutes_by_bucket[bucket_name] = {
            month_key: raw_minutes_by_bucket[bucket_name].get(month_key, 0.0)
            for month_key in months
        }

    return MonthlyTimeBuckets(
        bucket_order=list(cfg.bucket_order),
        months=months,
        minutes_total_by_month=dict(minutes_total_by_month),
        minutes_by_bucket=minutes_by_bucket,
    )


def plot_monthly_time_buckets(report: MonthlyTimeBuckets, out_path: Path) -> None:
    """Plot monthly time-bucket lines for percentage and absolute hours."""
    fig, (ax_pct, ax_abs) = plt.subplots(2, 1, figsize=FIGSIZE, sharex=True)

    if not report.months:
        ax_pct.set_title("Monthly time-bucket share of total time")
        ax_pct.set_ylabel("Percent")
        ax_abs.set_title("Monthly time-bucket hours")
        ax_abs.set_ylabel("Hours")
        ax_abs.set_xlabel("Month")
        _finalize_figure(fig, out_path)
        return

    for bucket_name in report.bucket_order:
        pct_values = [
            _percentage(
                report.minutes_by_bucket[bucket_name][month_key],
                report.minutes_total_by_month[month_key],
            )
            for month_key in report.months
        ]
        abs_values = [
            _minutes_to_hours(report.minutes_by_bucket[bucket_name][month_key])
            for month_key in report.months
        ]

        ax_pct.plot(report.months, pct_values, marker="o", label=bucket_name)  # type: ignore[arg-type]
        ax_abs.plot(report.months, abs_values, marker="o", label=bucket_name)  # type: ignore[arg-type]

    ax_pct.set_title("Monthly time-bucket share of total time")
    ax_pct.set_ylabel("Percent")
    ax_pct.grid(True)

    ax_abs.set_title("Monthly time-bucket hours")
    ax_abs.set_ylabel("Hours")
    ax_abs.set_xlabel("Month")
    ax_abs.grid(True)

    _set_xtick_style(ax_abs, rotation=45)
    ax_pct.legend(
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
    )

    _finalize_figure(fig, out_path, tight_layout_rect=(0.0, 0.0, 0.82, 1.0))


def write_monthly_time_buckets_summary_json(
    report: MonthlyTimeBuckets,
    out_path: Path,
) -> None:
    """Write a JSON summary for the monthly time-bucket report."""
    payload = {
        "months": [month_key.isoformat() for month_key in report.months],
        "hours_total_by_month": {
            month_key.isoformat(): _minutes_to_hours(report.minutes_total_by_month[month_key])
            for month_key in report.months
        },
        "hours_by_bucket": {
            bucket_name: {
                month_key.isoformat(): _minutes_to_hours(
                    report.minutes_by_bucket[bucket_name][month_key]
                )
                for month_key in report.months
            }
            for bucket_name in report.bucket_order
        },
        "percent_by_bucket": {
            bucket_name: {
                month_key.isoformat(): _percentage(
                    report.minutes_by_bucket[bucket_name][month_key],
                    report.minutes_total_by_month[month_key],
                )
                for month_key in report.months
            }
            for bucket_name in report.bucket_order
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _split_record_across_months(record: ClippedRecord) -> list[tuple[date, int]]:
    """Split one clipped record into month-local minute chunks."""
    out: list[tuple[date, int]] = []
    cur = record.start

    while cur < record.end:
        this_month_start = month_start(cur)
        next_boundary = next_month_start(this_month_start)
        segment_end = min(record.end, next_boundary)
        minutes = int((segment_end - cur).total_seconds() // 60)

        if minutes > 0:
            out.append((this_month_start.date(), minutes))

        cur = segment_end

    return out


def _minutes_to_hours(minutes: float) -> float:
    """Convert minutes to hours."""
    return float(minutes) / 60.0


def _percentage(part: float, whole: float) -> float:
    """Convert a part/whole pair to percentage."""
    if whole <= 0.0:
        return 0.0
    return 100.0 * float(part) / float(whole)


def _set_xtick_style(ax: Axes, rotation: float) -> None:
    """Rotate and right-align x tick labels."""
    ax.tick_params(axis="x", labelrotation=rotation)
    for label in ax.get_xticklabels():
        label.set_horizontalalignment("right")


def _finalize_figure(
    fig: Figure,
    out_path: Path,
    tight_layout_rect: tuple[float, float, float, float] | None = None,
) -> None:
    """Tighten layout, save the figure, and close it."""
    if tight_layout_rect is None:
        fig.tight_layout()
    else:
        fig.tight_layout(rect=tight_layout_rect)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
