"""Generate plot and summary artifacts from aggregated time totals."""

import json
from pathlib import Path
from typing import Final

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .aggregate import Aggregates

FIGSIZE: Final[tuple[float, float]] = (20.0, 12.0)
FIGSIZE_TASK: Final[tuple[float, float]] = (20.0, 12.0)
OTHERS_LABEL: Final[str] = "(others)"


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
    """Plot daily total hours, optionally smoothed by a rolling mean."""
    days = sorted(aggs.minutes_by_day.keys())
    fig, ax = plt.subplots(figsize=FIGSIZE)

    if not days:
        ax.set_title("Daily total hours")
        _finalize_figure(fig, out_path)
        return

    raw_values = [_minutes_to_hours(aggs.minutes_by_day[day]) for day in days]
    values = raw_values
    if rolling_days > 1:
        values = _rolling_mean(raw_values, window=rolling_days)

    ax.plot(days, values)  # type: ignore[arg-type]
    _set_xtick_style(ax, rotation=45)

    avg = sum(raw_values) / float(len(raw_values))
    ax.axhline(avg, linestyle="--")

    ax.set_ylabel("Hours")
    ax.set_title("Daily total hours")

    _finalize_figure(fig, out_path)


def _rolling_mean(values: list[float], window: int) -> list[float]:
    if window <= 1:
        return values
    out: list[float] = []
    for index in range(len(values)):
        lo = max(0, index - window + 1)
        chunk = values[lo : index + 1]
        out.append(sum(chunk) / float(len(chunk)))
    return out


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
