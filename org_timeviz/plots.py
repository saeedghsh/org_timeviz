"""Generate plot and summary artifacts from aggregated time totals."""

import json
from pathlib import Path

import matplotlib.pyplot as plt

from org_timeviz.aggregate import Aggregates


def _minutes_to_hours(minutes: int) -> float:
    return minutes / 60.0


def _top_k(items: dict[str, int], k: int) -> list[tuple[str, int]]:
    return sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:k]


def plot_bar_by_tag(aggs: Aggregates, out_path: Path, top_k: int) -> None:
    """Plot a bar chart of total hours per tag."""
    pairs = _top_k(aggs.minutes_by_tag, top_k)
    labels = [p[0] for p in pairs]
    values = [_minutes_to_hours(p[1]) for p in pairs]

    plt.figure()
    plt.bar(labels, values)
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Hours")
    plt.title("Total hours by tag")
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_bar_by_task(aggs: Aggregates, out_path: Path, top_k: int) -> None:
    """Plot a bar chart of total hours per task (outline path)."""
    pairs = _top_k(aggs.minutes_by_task, top_k)
    labels = [p[0] for p in pairs]
    values = [_minutes_to_hours(p[1]) for p in pairs]

    plt.figure()
    plt.bar(labels, values)
    plt.xticks(rotation=60, ha="right")
    plt.ylabel("Hours")
    plt.title("Total hours by task (outline path)")
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_timeseries_daily_total(aggs: Aggregates, out_path: Path, rolling_days: int) -> None:
    """Plot daily total hours, optionally smoothed by a rolling mean."""
    days = sorted(aggs.minutes_by_day.keys())
    if not days:
        plt.figure()
        plt.title("Daily total hours")
        plt.tight_layout()
        plt.savefig(out_path)
        plt.close()
        return

    values = [_minutes_to_hours(aggs.minutes_by_day[d]) for d in days]

    if rolling_days > 1:
        values = _rolling_mean(values, window=rolling_days)

    plt.figure()
    plt.plot(days, values)
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Hours")
    plt.title("Daily total hours")
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def _rolling_mean(values: list[float], window: int) -> list[float]:
    if window <= 1:
        return values
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        chunk = values[lo : i + 1]
        out.append(sum(chunk) / float(len(chunk)))
    return out


def write_summary_json(aggs: Aggregates, out_path: Path) -> None:
    """Write a compact JSON summary of the report totals."""
    payload = {
        "minutes_total": aggs.minutes_total,
        "hours_total": _minutes_to_hours(aggs.minutes_total),
        "minutes_by_tag": aggs.minutes_by_tag,
        "minutes_by_task_top50": dict(_top_k(aggs.minutes_by_task, 50)),
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
