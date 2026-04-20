"""Render a calendar-like day/time view from clipped Org clock records."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from textwrap import shorten
from typing import Final, Iterable

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch, Rectangle

from .filters import ClippedRecord

FIGURE_HEIGHT: Final[float] = 8.0
MIN_FIGURE_WIDTH: Final[float] = 16.0
WIDTH_PER_DAY: Final[float] = 0.65
COLUMN_WIDTH: Final[float] = 0.9
OTHERS_LABEL: Final[str] = "(others)"
MAX_CALENDAR_TASK_GROUPS: Final[int] = 12


@dataclass(frozen=True)
class CalendarSlice:
    """Represent one task fragment inside one calendar day."""

    day: date
    task: str
    start_minute: int
    end_minute: int
    minutes: int


def build_calendar_slices(records: Iterable[ClippedRecord]) -> list[CalendarSlice]:
    """Split clipped records into day-local task fragments."""
    slices: list[CalendarSlice] = []

    for record in records:
        cur = record.start
        while cur < record.end:
            day_start = datetime(cur.year, cur.month, cur.day)
            next_day_start = day_start + timedelta(days=1)
            segment_end = min(record.end, next_day_start)

            start_minute = int((cur - day_start).total_seconds() // 60)
            end_minute = int((segment_end - day_start).total_seconds() // 60)
            minutes = end_minute - start_minute

            if minutes > 0:
                slices.append(
                    CalendarSlice(
                        day=cur.date(),
                        task=record.record.outline_path,
                        start_minute=start_minute,
                        end_minute=end_minute,
                        minutes=minutes,
                    )
                )

            cur = segment_end

    return slices


def plot_calendar_view(
    records: Iterable[ClippedRecord],
    out_path: Path,
    *,
    title: str,
    top_k_tasks: int,
) -> None:
    """Plot a calendar-like day/time view for clipped clock records."""
    slices = build_calendar_slices(records)
    fig, ax = plt.subplots(figsize=_figure_size_for_days(_day_count(slices)))

    if not slices:
        ax.set_title(title)
        ax.set_xlabel("Day")
        ax.set_ylabel("Hour of day")
        _set_hour_ticks(ax)
        _finalize_figure(fig, out_path)
        return

    slices.sort(key=lambda item: (item.day, item.start_minute, item.end_minute, item.task))
    unique_days = sorted({item.day for item in slices})
    if unique_days:
        first_day = unique_days[0]
        last_day = unique_days[-1]
        days = [
            first_day + timedelta(days=offset) for offset in range((last_day - first_day).days + 1)
        ]
    else:
        days = []

    day_to_x = {day: index for index, day in enumerate(days)}

    grouped_task_names, color_by_task = _task_groups_and_colors(
        slices,
        top_k=min(top_k_tasks, MAX_CALENDAR_TASK_GROUPS),
    )

    for item in slices:
        grouped_task = item.task if item.task in color_by_task else OTHERS_LABEL
        x_left = day_to_x[item.day] - (COLUMN_WIDTH / 2.0)
        y_bottom = item.start_minute / 60.0
        height = item.minutes / 60.0

        patch = Rectangle(
            (x_left, y_bottom),
            COLUMN_WIDTH,
            height,
            facecolor=color_by_task[grouped_task],
            edgecolor="none",
        )
        ax.add_patch(patch)

    for x_pos in range(len(days) + 1):
        ax.axvline(x_pos - 0.5, linewidth=0.5, color="0.85")

    ax.set_xlim(-0.5, len(days) - 0.5)
    ax.set_ylim(24.0, 0.0)
    ax.set_xlabel("Day")
    ax.set_ylabel("Hour of day")
    ax.set_title(title)

    ax.set_xticks(list(range(len(days))))
    ax.set_xticklabels([_format_day_label(day) for day in days])
    _set_xtick_style(ax, rotation=90)

    _set_hour_ticks(ax)
    ax.grid(axis="y", linestyle=":", linewidth=0.5, color="0.80")

    handles = [
        Patch(facecolor=color_by_task[name], label=_legend_label(name))
        for name in grouped_task_names
    ]
    if handles:
        ax.legend(
            handles=handles,
            title="Tasks",
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            borderaxespad=0.0,
        )
        _finalize_figure(fig, out_path, tight_layout_rect=(0.0, 0.0, 0.82, 1.0))
        return

    _finalize_figure(fig, out_path)


def _day_count(slices: list[CalendarSlice]) -> int:
    """Return the number of distinct days covered by slices."""
    if not slices:
        return 7
    return len({item.day for item in slices})


def _figure_size_for_days(day_count: int) -> tuple[float, float]:
    """Compute a figure size that scales with the number of days."""
    width = max(MIN_FIGURE_WIDTH, WIDTH_PER_DAY * float(day_count))
    return (width, FIGURE_HEIGHT)


def _task_groups_and_colors(
    slices: list[CalendarSlice],
    top_k: int,
) -> tuple[list[str], dict[str, object]]:
    """Rank tasks by total minutes and assign colors."""
    minutes_by_task: dict[str, int] = defaultdict(int)
    for item in slices:
        minutes_by_task[item.task] += item.minutes

    ranked_tasks = sorted(minutes_by_task.items(), key=lambda kv: kv[1], reverse=True)
    top_task_names = [name for name, _ in ranked_tasks[:top_k]]

    grouped_names = list(top_task_names)
    if len(ranked_tasks) > len(top_task_names):
        grouped_names.append(OTHERS_LABEL)

    color_map = plt.get_cmap("tab20")
    color_by_task: dict[str, object] = {}
    for index, name in enumerate(top_task_names):
        color_by_task[name] = color_map(index % color_map.N)

    if OTHERS_LABEL in grouped_names:
        color_by_task[OTHERS_LABEL] = "#c0c0c0"

    return grouped_names, color_by_task


def _format_day_label(day: date) -> str:
    """Format a compact day label for the x-axis."""
    return day.strftime("%a / %Y-%m-%d")


def _legend_label(task_name: str) -> str:
    """Shorten long task labels for the legend."""
    return shorten(task_name, width=60, placeholder="...")


def _set_hour_ticks(ax: Axes) -> None:
    """Format the y-axis as hours in the day."""
    tick_hours = list(range(0, 25, 2))
    ax.set_yticks(tick_hours)
    ax.set_yticklabels([f"{hour:02d}:00" for hour in tick_hours])


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
