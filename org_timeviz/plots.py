"""Generate plot and summary artifacts from aggregated time totals."""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .aggregate import Aggregates

FIGSIZE: Final[tuple[float, float]] = (20.0, 12.0)
FIGSIZE_TASK: Final[tuple[float, float]] = (20.0, 12.0)
OTHERS_LABEL: Final[str] = "(others)"

TIMESERIES_MAIN_COLOR: Final[str] = "tab:blue"
TIMESERIES_ALL_TIME_COLOR: Final[str] = "orange"
TIMESERIES_WEEKLY_COLOR: Final[str] = "green"
TIMESERIES_MONTHLY_COLOR: Final[str] = "red"
TIMESERIES_WEEKLY_WINDOW_DAYS: Final[int] = 7
TIMESERIES_MONTHLY_WINDOW_DAYS: Final[int] = 30


def _minutes_to_hours(minutes: float) -> float:
    return float(minutes) / 60.0


def _top_k_with_others(items: dict[str, float], k: int) -> list[tuple[str, float]]:
    pairs = sorted(items.items(), key=lambda kv: kv[1], reverse=True)
    if len(pairs) <= k:
        return pairs

    top = pairs[:k]
    rest_sum = sum(value for _, value in pairs[k:])
    if rest_sum > 0:
        top.append((OTHERS_LABEL, rest_sum))
    return top


def _top_k(items: dict[str, float], k: int) -> list[tuple[str, float]]:
    return sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:k]


def _finalize_figure(fig: Figure, out_path: Path) -> None:
    # bbox_inches="tight" prevents rotated tick labels from being cropped.
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _set_xtick_style(ax: Axes, rotation: float) -> None:
    ax.tick_params(axis="x", labelrotation=rotation)
    for label in ax.get_xticklabels():
        label.set_horizontalalignment("right")


def _full_day_range(start_day: date, end_day: date) -> list[date]:
    """Return all calendar days in the inclusive range."""
    return [start_day + timedelta(days=offset) for offset in range((end_day - start_day).days + 1)]


def _is_workday(day: date) -> bool:
    """Return whether a date is a weekday."""
    return day.weekday() < 5


def _workday_average(values: list[float], days: list[date]) -> float:
    """Compute average per workday for one aligned day/value sequence."""
    workday_count = sum(1 for day in days if _is_workday(day))
    if workday_count <= 0:
        return 0.0
    return sum(values) / float(workday_count)


def _rolling_workday_average(
    values: list[float],
    days: list[date],
    window_days: int,
) -> list[float]:
    """Compute trailing workday-normalized averages over calendar windows."""
    if window_days <= 1:
        return values

    out: list[float] = []
    for index in range(len(values)):
        lo = max(0, index - window_days + 1)
        chunk_values = values[lo : index + 1]
        chunk_days = days[lo : index + 1]
        out.append(_workday_average(chunk_values, chunk_days))
    return out


def plot_bar_by_time_bucket(aggs: Aggregates, out_path: Path, top_k: int) -> None:
    """Plot a bar chart of total hours per time bucket."""
    pairs = _top_k_with_others(aggs.minutes_by_time_bucket, top_k)
    labels = [pair[0] for pair in pairs]
    values = [_minutes_to_hours(pair[1]) for pair in pairs]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.bar(labels, values)
    _set_xtick_style(ax, rotation=45)

    ax.set_ylabel("Hours")
    ax.set_title("Total hours by time bucket")

    _finalize_figure(fig, out_path)


def plot_bar_by_task(aggs: Aggregates, out_path: Path, top_k: int) -> None:
    """Plot a bar chart of total hours per task (outline path)."""
    task_minutes = {label: float(value) for label, value in aggs.minutes_by_task.items()}
    pairs = _top_k_with_others(task_minutes, top_k)
    labels = [pair[0] for pair in pairs]
    values = [_minutes_to_hours(pair[1]) for pair in pairs]

    fig, ax = plt.subplots(figsize=FIGSIZE_TASK)
    ax.bar(labels, values)

    # Labels can get long on weekly plots; rotate + tight bbox avoids cropping.
    _set_xtick_style(ax, rotation=90)

    ax.set_ylabel("Hours")
    ax.set_title("Total hours by task (outline path)")

    _finalize_figure(fig, out_path)


def plot_timeseries_daily_total(aggs: Aggregates, out_path: Path, rolling_days: int) -> None:
    """Plot daily total hours with workday-normalized averages."""
    del rolling_days

    logged_days = sorted(aggs.minutes_by_day.keys())
    fig, ax = plt.subplots(figsize=FIGSIZE)

    if not logged_days:
        ax.set_title("Daily total hours")
        _finalize_figure(fig, out_path)
        return

    full_days = _full_day_range(logged_days[0], logged_days[-1])

    daily_values = [_minutes_to_hours(float(aggs.minutes_by_day[day])) for day in logged_days]
    full_values = [_minutes_to_hours(float(aggs.minutes_by_day.get(day, 0))) for day in full_days]

    weekly_values = _rolling_workday_average(
        full_values,
        full_days,
        window_days=TIMESERIES_WEEKLY_WINDOW_DAYS,
    )
    monthly_values = _rolling_workday_average(
        full_values,
        full_days,
        window_days=TIMESERIES_MONTHLY_WINDOW_DAYS,
    )
    all_time_avg = _workday_average(full_values, full_days)

    ax.plot(
        logged_days,  # type: ignore[arg-type]
        daily_values,
        color=TIMESERIES_MAIN_COLOR,
        linestyle="-",
        label="Daily total",
    )

    ax.plot(
        full_days,  # type: ignore[arg-type]
        weekly_values,
        color=TIMESERIES_WEEKLY_COLOR,
        linestyle="--",
        label=f"Weekly avg / workday ({TIMESERIES_WEEKLY_WINDOW_DAYS}d)",
    )

    ax.plot(
        full_days,  # type: ignore[arg-type]
        monthly_values,
        color=TIMESERIES_MONTHLY_COLOR,
        linestyle="--",
        label=f"Monthly avg / workday ({TIMESERIES_MONTHLY_WINDOW_DAYS}d)",
    )

    ax.axhline(
        all_time_avg,
        color=TIMESERIES_ALL_TIME_COLOR,
        linestyle="--",
        label="All-time avg / workday",
    )

    _set_xtick_style(ax, rotation=45)

    ax.set_ylabel("Hours")
    ax.set_title("Daily total hours")
    ax.legend()

    _finalize_figure(fig, out_path)


def write_summary_json(aggs: Aggregates, out_path: Path) -> None:
    """Write a compact JSON summary of the report totals."""
    payload = {
        "minutes_total": aggs.minutes_total,
        "hours_total": _minutes_to_hours(float(aggs.minutes_total)),
        "minutes_by_time_bucket": aggs.minutes_by_time_bucket,
        "minutes_by_task_top50": dict(
            _top_k({label: float(value) for label, value in aggs.minutes_by_task.items()}, 50)
        ),
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
