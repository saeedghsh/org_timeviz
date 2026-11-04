"""Render an interactive daily time series for any raw Org tag."""

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from ..filters import ClippedRecord

TAG_TIMESERIES_HEIGHT = 580


def compute_daily_tag_hours(records: Iterable[ClippedRecord]) -> dict[str, dict[str, float]]:
    """Aggregate clocked hours by raw tag and calendar day."""
    hours_by_tag: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for record in records:
        tags = set(record.record.tags)
        if not tags:
            continue

        current = record.start
        while current < record.end:
            next_day = datetime.combine(current.date() + timedelta(days=1), datetime.min.time())
            segment_end = min(record.end, next_day)
            hours = (segment_end - current).total_seconds() / 3600.0
            day_label = current.date().isoformat()
            for tag in tags:
                hours_by_tag[tag][day_label] += hours
            current = segment_end

    return {tag: dict(sorted(day_hours.items())) for tag, day_hours in sorted(hours_by_tag.items())}


def write_tag_timeseries_html(records: Iterable[ClippedRecord], out_path: Path) -> None:
    """Write an interactive daily time series with a raw-tag selector."""
    hours_by_tag = compute_daily_tag_hours(records)
    all_dates = sorted({day for daily in hours_by_tag.values() for day in daily})
    days: list[str] = []
    if all_dates:
        current = date.fromisoformat(all_dates[0])
        last_day = date.fromisoformat(all_dates[-1])
        while current <= last_day:
            days.append(current.isoformat())
            current += timedelta(days=1)

    figure = go.Figure(
        data=[
            go.Scatter(
                name="Daily hours",
                x=days,
                y=[0.0 for _ in days],
                mode="lines",
                hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} h<extra></extra>",
            )
        ]
    )
    initial_range: list[str] | None = None
    if days:
        end_day = date.fromisoformat(days[-1])
        start_day = max(date.fromisoformat(days[0]), end_day - timedelta(days=29))
        initial_range = [start_day.isoformat(), (end_day + timedelta(days=1)).isoformat()]

    figure.update_layout(
        title="Daily hours by Org tag",
        height=TAG_TIMESERIES_HEIGHT,
        dragmode="pan",
        hovermode="x unified",
        showlegend=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"l": 75, "r": 40, "t": 55, "b": 65},
        xaxis={
            "title": {"text": "Day"},
            "type": "date",
            "range": initial_range,
            "tickformat": "%Y-%m-%d",
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
            "title": {"text": "Hours"},
            "rangemode": "tozero",
            "showgrid": True,
            "gridcolor": "#cccccc",
        },
    )

    figure_json = _script_safe_json(figure.to_json())
    hours_json = _script_safe_json(json.dumps(hours_by_tag, ensure_ascii=False))
    plotly_js = get_plotlyjs()
    out_path.write_text(
        f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Daily hours by Org tag</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: white; font-family: sans-serif; }}
    .controls {{ margin: 10px 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 18px; }}
    #tag-selector {{ min-width: 180px; max-width: 100%; padding: 5px; }}
    #tag-total {{ font-weight: bold; }}
    #tag-chart {{ width: 100%; }}
  </style>
</head>
<body>
  <div class="controls">
    <label for="tag-selector">Org tag:
      <select id="tag-selector"><option value="">Select a tag</option></select>
    </label>
    <span id="tag-total" role="status">Select a tag to see hours.</span>
  </div>
  <div id="tag-chart"></div>

  <script>{plotly_js}</script>
  <script>
    const figure = {figure_json};
    const hoursByTag = {hours_json};
    const plot = document.getElementById("tag-chart");
    const selector = document.getElementById("tag-selector");
    const totalLabel = document.getElementById("tag-total");
    const days = figure.data[0].x;
    const options = {{displaylogo: false, responsive: true, scrollZoom: true}};
    let selectedValues = days.map(() => 0);

    for (const tag of Object.keys(hoursByTag)) {{
      selector.add(new Option(tag, tag));
    }}

    function toMillis(value) {{
      if (value instanceof Date) return value.getTime();
      if (typeof value === "number") return value;
      return new Date(String(value).replace(" ", "T")).getTime();
    }}

    function updateTotal() {{
      if (!selector.value) {{
        totalLabel.textContent = "Select a tag to see hours.";
        return;
      }}
      const range = plot._fullLayout.xaxis.range;
      const start = toMillis(range[0]);
      const end = toMillis(range[1]);
      let sum = 0;
      for (let index = 0; index < days.length; index += 1) {{
        const day = toMillis(days[index] + "T00:00:00");
        if (day >= start && day < end) {{
          sum += selectedValues[index];
        }}
      }}
      totalLabel.textContent = `Total in visible range: ${{sum.toFixed(2)}} h`;
    }}

    Plotly.newPlot(plot, figure.data, figure.layout, options).then(() => {{
      selector.addEventListener("change", () => {{
        const daily = hoursByTag[selector.value] || {{}};
        selectedValues = days.map((day) => daily[day] || 0);
        Plotly.restyle(plot, {{y: [selectedValues]}}, [0]).then(updateTotal);
      }});
      plot.on("plotly_relayout", (changes) => {{
        if (Object.keys(changes).some((key) => key.startsWith("xaxis."))) {{
          updateTotal();
        }}
      }});
    }});
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )


def _script_safe_json(json_text: str) -> str:
    """Prevent embedded JSON from terminating a script element."""
    return json_text.replace("</", "<\\/")
