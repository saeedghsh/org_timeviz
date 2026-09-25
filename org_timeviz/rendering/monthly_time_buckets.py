"""Render monthly time-bucket trends from clipped Org clock records."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Iterable

import plotly.graph_objects as go
from matplotlib import colormaps
from matplotlib.colors import to_hex
from plotly.offline import get_plotlyjs

from ..config import TimeBucketsConfig
from ..filters import ClippedRecord
from ..time_bucket_resolver import resolve_time_bucket_allocations
from ..time_windows import month_start, next_month_start

MONTHLY_FIGURE_HEIGHT: Final[int] = 500


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


def write_monthly_time_buckets_html(
    report: MonthlyTimeBuckets,
    out_path: Path,
) -> None:
    """Write an interactive monthly time-bucket trend dashboard."""
    color_by_bucket = _time_bucket_colors(report.bucket_order)
    percent_figure = _build_monthly_time_bucket_figure(
        report,
        title="Monthly time-bucket share of total time",
        value_kind="percent",
        yaxis_title="Percent",
        hover_suffix="%",
        color_by_bucket=color_by_bucket,
    )
    hours_figure = _build_monthly_time_bucket_figure(
        report,
        title="Monthly time-bucket hours",
        value_kind="hours",
        yaxis_title="Hours",
        hover_suffix=" h",
        color_by_bucket=color_by_bucket,
    )

    out_path.write_text(
        _monthly_time_bucket_html(
            percent_figure=percent_figure,
            hours_figure=hours_figure,
        ),
        encoding="utf-8",
    )


def _build_monthly_time_bucket_figure(
    report: MonthlyTimeBuckets,
    *,
    title: str,
    value_kind: str,
    yaxis_title: str,
    hover_suffix: str,
    color_by_bucket: dict[str, str],
) -> go.Figure:
    """Build one interactive monthly line chart."""
    figure = go.Figure()
    month_labels = [month_key.isoformat() for month_key in report.months]

    for bucket_name in report.bucket_order:
        values = [
            _monthly_value(
                report,
                bucket_name=bucket_name,
                month_key=month_key,
                value_kind=value_kind,
            )
            for month_key in report.months
        ]
        figure.add_trace(
            go.Scatter(
                name=bucket_name,
                x=month_labels,
                y=values,
                mode="lines+markers",
                line={"color": color_by_bucket[bucket_name]},
                marker={"color": color_by_bucket[bucket_name]},
                hovertemplate=f"%{{x|%Y-%m}}<br>{bucket_name}: %{{y:.2f}}{hover_suffix}<extra></extra>",
            )
        )

    figure.update_layout(
        title=title,
        dragmode="pan",
        hovermode="x unified",
        height=MONTHLY_FIGURE_HEIGHT,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"l": 75, "r": 170, "t": 55, "b": 90},
        legend={
            "title": {"text": "Time buckets"},
            "x": 1.02,
            "xanchor": "left",
            "y": 1.0,
            "yanchor": "top",
        },
        xaxis={
            "title": {"text": "Month"},
            "type": "date",
            "tickformat": "%Y-%m",
            "tickangle": -45,
            "showgrid": True,
            "gridcolor": "#d9d9d9",
            "rangeslider": {"visible": True, "thickness": 0.08},
            "rangeselector": {
                "buttons": [
                    {"count": 6, "label": "6m", "step": "month", "stepmode": "backward"},
                    {"count": 12, "label": "12m", "step": "month", "stepmode": "backward"},
                    {"count": 24, "label": "24m", "step": "month", "stepmode": "backward"},
                    {"step": "all", "label": "all"},
                ]
            },
        },
        yaxis={
            "title": {"text": yaxis_title},
            "rangemode": "tozero",
            "showgrid": True,
            "gridcolor": "#cccccc",
        },
    )
    return figure


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


def _monthly_value(
    report: MonthlyTimeBuckets,
    *,
    bucket_name: str,
    month_key: date,
    value_kind: str,
) -> float:
    """Return one monthly value as either percent or hours."""
    minutes = report.minutes_by_bucket[bucket_name][month_key]
    if value_kind == "percent":
        return _percentage(minutes, report.minutes_total_by_month[month_key])
    if value_kind == "hours":
        return _minutes_to_hours(minutes)
    raise ValueError(f"Unsupported monthly value kind: {value_kind}")


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


def _time_bucket_colors(bucket_order: list[str]) -> dict[str, str]:
    """Assign stable Matplotlib-tab20 colors in configured bucket order."""
    color_map = colormaps["tab20"]
    return {
        bucket_name: to_hex(color_map(index % color_map.N), keep_alpha=False)
        for index, bucket_name in enumerate(bucket_order)
    }


def _script_safe_json(json_text: str) -> str:
    """Prevent embedded JSON data from terminating a script element."""
    return json_text.replace("</", "<\\/")


def _monthly_time_bucket_html(
    *,
    percent_figure: go.Figure,
    hours_figure: go.Figure,
) -> str:
    """Render a self-contained interactive monthly time-bucket dashboard."""
    plotly_js = get_plotlyjs()
    percent_json = _script_safe_json(percent_figure.to_json())
    hours_json = _script_safe_json(hours_figure.to_json())
    config_json = json.dumps(
        {
            "displaylogo": False,
            "responsive": True,
            "scrollZoom": True,
        }
    )

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Monthly time-bucket trends</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: white; font-family: sans-serif; }}
    .plot {{ width: 100%; }}
  </style>
</head>
<body>
  <div id="monthly-time-bucket-percent" class="plot"></div>
  <div id="monthly-time-bucket-hours" class="plot"></div>

  <script>{plotly_js}</script>
  <script>
    const percentFigure = {percent_json};
    const hoursFigure = {hours_json};
    const plotConfig = {config_json};
    let syncingRange = false;

    Promise.all([
      Plotly.newPlot("monthly-time-bucket-percent", percentFigure.data, percentFigure.layout, plotConfig),
      Plotly.newPlot("monthly-time-bucket-hours", hoursFigure.data, hoursFigure.layout, plotConfig),
    ]).then(() => {{
      const percentPlot = document.getElementById("monthly-time-bucket-percent");
      const hoursPlot = document.getElementById("monthly-time-bucket-hours");

      function relayoutTarget(target, eventData) {{
        if (syncingRange) {{
          return;
        }}
        const update = {{}};
        if (Object.hasOwn(eventData, "xaxis.range[0]") && Object.hasOwn(eventData, "xaxis.range[1]")) {{
          update["xaxis.range"] = [eventData["xaxis.range[0]"], eventData["xaxis.range[1]"]];
        }} else if (Object.hasOwn(eventData, "xaxis.range")) {{
          update["xaxis.range"] = eventData["xaxis.range"];
        }} else if (Object.hasOwn(eventData, "xaxis.autorange")) {{
          update["xaxis.autorange"] = eventData["xaxis.autorange"];
        }} else {{
          return;
        }}

        syncingRange = true;
        Plotly.relayout(target, update).finally(() => {{
          syncingRange = false;
        }});
      }}

      percentPlot.on("plotly_relayout", (eventData) => relayoutTarget(hoursPlot, eventData));
      hoursPlot.on("plotly_relayout", (eventData) => relayoutTarget(percentPlot, eventData));
    }});
  </script>
</body>
</html>
"""
