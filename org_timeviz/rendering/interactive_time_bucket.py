"""Generate a linked interactive calendar and time-bucket bar chart."""

import json
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Final

import plotly.graph_objects as go
from matplotlib import colormaps
from matplotlib.colors import to_hex
from plotly.offline import get_plotlyjs

from ..config import TimeBucketsConfig
from ..filters import ClippedRecord
from ..time_bucket_resolver import resolve_time_bucket_allocations

DAY_WIDTH_MS: Final[float] = 0.90 * 24.0 * 60.0 * 60.0 * 1000.0
CALENDAR_HEIGHT: Final[int] = 650
HISTOGRAM_HEIGHT: Final[int] = 420
LOW_OPACITY: Final[float] = 0.5


@dataclass(frozen=True)
class _PreparedRecord:
    start: datetime
    end: datetime
    task_title: str
    dominant_bucket: str
    allocations: dict[str, float]


@dataclass(frozen=True)
class _CalendarSlice:
    day: date
    task_title: str
    bucket_name: str
    start_minute: int
    end_minute: int

    @property
    def minutes(self) -> int:
        return self.end_minute - self.start_minute


def write_interactive_time_bucket_dashboard(
    records: Iterable[ClippedRecord],
    out_path: Path,
    *,
    time_buckets_cfg: TimeBucketsConfig,
    low_opacity_task_titles: Collection[str],
    initial_start: datetime,
    initial_end: datetime,
) -> None:
    """Write a standalone linked calendar/time-bucket dashboard."""
    prepared_records = _prepare_records(records, time_buckets_cfg)
    color_by_bucket = _time_bucket_colors(time_buckets_cfg.bucket_order)

    calendar_figure = _build_calendar_figure(
        prepared_records,
        bucket_order=time_buckets_cfg.bucket_order,
        color_by_bucket=color_by_bucket,
        low_opacity_task_titles=low_opacity_task_titles,
        initial_start=initial_start,
        initial_end=initial_end,
    )
    histogram_figure = _build_histogram_figure(
        prepared_records,
        bucket_order=time_buckets_cfg.bucket_order,
        color_by_bucket=color_by_bucket,
        initial_start=initial_start,
        initial_end=initial_end,
    )

    payload: list[dict[str, object]] = [
        {
            "start": record.start.isoformat(timespec="seconds"),
            "end": record.end.isoformat(timespec="seconds"),
            "allocations": record.allocations,
        }
        for record in prepared_records
    ]

    out_path.write_text(
        _dashboard_html(
            calendar_figure=calendar_figure,
            histogram_figure=histogram_figure,
            bucket_order=time_buckets_cfg.bucket_order,
            records_payload=payload,
        ),
        encoding="utf-8",
    )


def _prepare_records(
    records: Iterable[ClippedRecord],
    cfg: TimeBucketsConfig,
) -> list[_PreparedRecord]:
    """Resolve bucket allocations once for all interactive calculations."""
    bucket_order_index = {name: index for index, name in enumerate(cfg.bucket_order)}
    prepared: list[_PreparedRecord] = []

    for record in records:
        allocations = resolve_time_bucket_allocations(record.record.tags, cfg)
        dominant_bucket = min(
            allocations,
            key=lambda bucket_name: (
                -allocations[bucket_name],
                bucket_order_index.get(bucket_name, len(bucket_order_index)),
                bucket_name,
            ),
        )
        prepared.append(
            _PreparedRecord(
                start=record.start,
                end=record.end,
                task_title=record.record.headline or record.record.outline_path,
                dominant_bucket=dominant_bucket,
                allocations=allocations,
            )
        )

    return prepared


def _calendar_slices(records: Iterable[_PreparedRecord]) -> list[_CalendarSlice]:
    """Split records at midnight so each block belongs to one day column."""
    slices: list[_CalendarSlice] = []

    for record in records:
        current = record.start
        while current < record.end:
            day_start = datetime(current.year, current.month, current.day)
            next_day_start = day_start + timedelta(days=1)
            segment_end = min(record.end, next_day_start)

            start_minute = int((current - day_start).total_seconds() // 60)
            end_minute = int((segment_end - day_start).total_seconds() // 60)
            if end_minute > start_minute:
                slices.append(
                    _CalendarSlice(
                        day=current.date(),
                        task_title=record.task_title,
                        bucket_name=record.dominant_bucket,
                        start_minute=start_minute,
                        end_minute=end_minute,
                    )
                )

            current = segment_end

    return slices


def _time_bucket_colors(bucket_order: list[str]) -> dict[str, str]:
    """Assign stable Matplotlib-tab20 colors in configured bucket order."""
    color_map = colormaps["tab20"]
    return {
        bucket_name: to_hex(color_map(index % color_map.N), keep_alpha=False)
        for index, bucket_name in enumerate(bucket_order)
    }


def _build_calendar_figure(
    records: list[_PreparedRecord],
    *,
    bucket_order: list[str],
    color_by_bucket: dict[str, str],
    low_opacity_task_titles: Collection[str],
    initial_start: datetime,
    initial_end: datetime,
) -> go.Figure:
    """Build the interactive calendar figure using one trace per bucket."""
    slices = _calendar_slices(records)
    low_opacity_titles = set(low_opacity_task_titles)
    figure = go.Figure()

    for bucket_name in bucket_order:
        bucket_slices = [item for item in slices if item.bucket_name == bucket_name]
        figure.add_trace(
            go.Bar(
                name=bucket_name,
                x=[datetime.combine(item.day, time(hour=12)) for item in bucket_slices],
                y=[float(item.minutes) / 60.0 for item in bucket_slices],
                base=[float(item.start_minute) / 60.0 for item in bucket_slices],
                width=[DAY_WIDTH_MS for _ in bucket_slices],
                marker={
                    "color": color_by_bucket[bucket_name],
                    "opacity": [
                        LOW_OPACITY if item.task_title in low_opacity_titles else 1.0
                        for item in bucket_slices
                    ],
                    "line": {"width": 0},
                },
                customdata=[
                    [
                        item.task_title,
                        bucket_name,
                        item.day.isoformat(),
                        _format_minute(item.start_minute),
                        _format_minute(item.end_minute),
                    ]
                    for item in bucket_slices
                ],
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "%{customdata[2]}<br>"
                    "%{customdata[3]}–%{customdata[4]}<br>"
                    "%{customdata[1]}<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        title="Calendar view by time bucket",
        barmode="overlay",
        dragmode="pan",
        hovermode="closest",
        height=CALENDAR_HEIGHT,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"l": 75, "r": 170, "t": 55, "b": 120},
        legend={
            "title": {"text": "Time buckets"},
            "x": 1.02,
            "xanchor": "left",
            "y": 1.0,
            "yanchor": "top",
        },
        xaxis={
            "title": {"text": "Day"},
            "range": [initial_start, initial_end],
            "tickformat": "%a / %Y-%m-%d",
            "tickangle": -90,
            "showgrid": True,
            "gridcolor": "#d9d9d9",
            "rangeslider": {"visible": True, "thickness": 0.08},
            "rangeselector": {
                "buttons": [
                    {"count": 7, "label": "7d", "step": "day", "stepmode": "backward"},
                    {"count": 30, "label": "30d", "step": "day", "stepmode": "backward"},
                    {"count": 90, "label": "90d", "step": "day", "stepmode": "backward"},
                    {"step": "all", "label": "all"},
                ]
            },
        },
        yaxis={
            "title": {"text": "Hour of day"},
            "range": [24.0, 0.0],
            "fixedrange": True,
            "tickmode": "array",
            "tickvals": list(range(0, 25, 2)),
            "ticktext": [f"{hour:02d}:00" for hour in range(0, 25, 2)],
            "showgrid": True,
            "gridcolor": "#cccccc",
        },
    )
    return figure


def _build_histogram_figure(
    records: list[_PreparedRecord],
    *,
    bucket_order: list[str],
    color_by_bucket: dict[str, str],
    initial_start: datetime,
    initial_end: datetime,
) -> go.Figure:
    """Build the fixed-order time-bucket bar chart for the initial range."""
    values = _bucket_hours_for_interval(
        records,
        bucket_order=bucket_order,
        start=initial_start,
        end=initial_end,
    )
    figure = go.Figure(
        data=[
            go.Bar(
                x=bucket_order,
                y=values,
                marker={
                    "color": [color_by_bucket[bucket_name] for bucket_name in bucket_order],
                    "line": {"width": 0},
                },
                hovertemplate="%{x}: %{y:.2f} h<extra></extra>",
                showlegend=False,
            )
        ]
    )
    figure.update_layout(
        title="Total hours by time bucket",
        height=HISTOGRAM_HEIGHT,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"l": 75, "r": 30, "t": 55, "b": 120},
        xaxis={
            "title": {"text": "Time bucket"},
            "categoryorder": "array",
            "categoryarray": bucket_order,
            "tickangle": -45,
            "fixedrange": True,
        },
        yaxis={
            "title": {"text": "Hours"},
            "rangemode": "tozero",
            "fixedrange": True,
            "showgrid": True,
            "gridcolor": "#cccccc",
        },
    )
    return figure


def _bucket_hours_for_interval(
    records: Iterable[_PreparedRecord],
    *,
    bucket_order: list[str],
    start: datetime,
    end: datetime,
) -> list[float]:
    """Return fixed-order bucket hours clipped to one visible interval."""
    totals = {bucket_name: 0.0 for bucket_name in bucket_order}

    for record in records:
        overlap_start = max(record.start, start)
        overlap_end = min(record.end, end)
        if overlap_end <= overlap_start:
            continue

        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        for bucket_name, fraction in record.allocations.items():
            if bucket_name in totals:
                totals[bucket_name] += hours * fraction

    return [totals[bucket_name] for bucket_name in bucket_order]


def _format_minute(minute: int) -> str:
    """Format a minute offset from midnight as HH:MM."""
    if minute == 24 * 60:
        return "24:00"
    hour, minute_in_hour = divmod(minute, 60)
    return f"{hour:02d}:{minute_in_hour:02d}"


def _script_safe_json(json_text: str) -> str:
    """Prevent embedded JSON data from terminating a script element."""
    return json_text.replace("</", "<\\/")


def _dashboard_html(
    *,
    calendar_figure: go.Figure,
    histogram_figure: go.Figure,
    bucket_order: list[str],
    records_payload: list[dict[str, object]],
) -> str:
    """Render a self-contained HTML page and link the figures in JavaScript."""
    plotly_js = get_plotlyjs()
    calendar_json = _script_safe_json(calendar_figure.to_json())
    histogram_json = _script_safe_json(histogram_figure.to_json())
    bucket_order_json = _script_safe_json(json.dumps(bucket_order, ensure_ascii=False))
    records_json = _script_safe_json(json.dumps(records_payload, ensure_ascii=False))
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
  <title>Interactive time-bucket view</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: white; font-family: sans-serif; }}
    .plot {{ width: 100%; }}
  </style>
</head>
<body>
  <div id="calendar-view" class="plot"></div>
  <div id="bucket-histogram" class="plot"></div>

  <script>{plotly_js}</script>
  <script>
    const calendarFigure = {calendar_json};
    const histogramFigure = {histogram_json};
    const bucketOrder = {bucket_order_json};
    const rawRecords = {records_json};
    const plotConfig = {config_json};

    function toMillis(value) {{
      if (value instanceof Date) {{
        return value.getTime();
      }}
      if (typeof value === "number") {{
        return value;
      }}
      return new Date(String(value).replace(" ", "T")).getTime();
    }}

    function formatLocalDate(value) {{
      const dateValue = new Date(value);
      const year = String(dateValue.getFullYear()).padStart(4, "0");
      const month = String(dateValue.getMonth() + 1).padStart(2, "0");
      const day = String(dateValue.getDate()).padStart(2, "0");
      return `${{year}}-${{month}}-${{day}}`;
    }}

    const records = rawRecords.map((record) => ({{
      start: toMillis(record.start),
      end: toMillis(record.end),
      allocations: record.allocations,
    }}));

    function bucketHours(start, end) {{
      const totals = Object.fromEntries(bucketOrder.map((bucketName) => [bucketName, 0.0]));

      for (const record of records) {{
        const overlapStart = Math.max(record.start, start);
        const overlapEnd = Math.min(record.end, end);
        if (overlapEnd <= overlapStart) {{
          continue;
        }}

        const hours = (overlapEnd - overlapStart) / (60.0 * 60.0 * 1000.0);
        for (const [bucketName, fraction] of Object.entries(record.allocations)) {{
          if (Object.hasOwn(totals, bucketName)) {{
            totals[bucketName] += hours * fraction;
          }}
        }}
      }}

      return bucketOrder.map((bucketName) => totals[bucketName]);
    }}

    Promise.all([
      Plotly.newPlot("calendar-view", calendarFigure.data, calendarFigure.layout, plotConfig),
      Plotly.newPlot("bucket-histogram", histogramFigure.data, histogramFigure.layout, plotConfig),
    ]).then(() => {{
      const calendar = document.getElementById("calendar-view");
      const histogram = document.getElementById("bucket-histogram");

      function updateHistogram() {{
        const visibleRange = calendar._fullLayout.xaxis.range;
        const start = toMillis(visibleRange[0]);
        const end = toMillis(visibleRange[1]);
        const values = bucketHours(start, end);

        const rangeLabel = `${{formatLocalDate(start)}} to ${{formatLocalDate(end)}}`;
        Plotly.restyle(histogram, {{ y: [values] }}, [0]);
        Plotly.relayout(histogram, {{
          "title.text": `Total hours by time bucket (${{rangeLabel}})`,
          "yaxis.autorange": true,
        }});
      }}

      calendar.on("plotly_relayout", (eventData) => {{
        if (Object.keys(eventData).some((key) => key.startsWith("xaxis."))) {{
          updateHistogram();
        }}
      }});

      updateHistogram();
    }});
  </script>
</body>
</html>
"""
