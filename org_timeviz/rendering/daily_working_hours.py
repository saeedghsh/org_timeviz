"""Write interactive daily working-hours time-series reports."""

from datetime import date, timedelta
from pathlib import Path
from typing import Final

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs

from ..aggregate import Aggregates

DAILY_WORKING_HOURS_HEIGHT: Final[int] = 650
TIMESERIES_WEEKLY_WINDOW_DAYS: Final[int] = 7
TIMESERIES_MONTHLY_WINDOW_DAYS: Final[int] = 30


def write_daily_working_hours_html(aggs: Aggregates, out_path: Path) -> None:
    """Write a standalone interactive daily working-hours time-series report."""
    figure = _build_daily_working_hours_figure(aggs)
    out_path.write_text(_timeseries_html(figure), encoding="utf-8")


def _build_daily_working_hours_figure(aggs: Aggregates) -> go.Figure:
    """Build a Plotly figure for daily totals and workday-normalized averages."""
    logged_days = sorted(aggs.minutes_by_day.keys())
    figure = go.Figure()

    if not logged_days:
        figure.update_layout(
            title="Daily total hours",
            height=DAILY_WORKING_HOURS_HEIGHT,
            plot_bgcolor="white",
            paper_bgcolor="white",
            margin={"l": 75, "r": 40, "t": 55, "b": 80},
            xaxis={"title": {"text": "Day"}},
            yaxis={"title": {"text": "Hours"}, "rangemode": "tozero"},
        )
        return figure

    full_days = _full_day_range(logged_days[0], logged_days[-1])

    daily_values = [
        _minutes_to_hours(float(aggs.minutes_by_day[day])) for day in logged_days
    ]
    full_values = [
        _minutes_to_hours(float(aggs.minutes_by_day.get(day, 0)))
        for day in full_days
    ]

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

    figure.add_trace(
        go.Scatter(
            name="Daily total",
            x=logged_days,
            y=daily_values,
            mode="lines",
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} h<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            name=f"Weekly avg / workday ({TIMESERIES_WEEKLY_WINDOW_DAYS}d)",
            x=full_days,
            y=weekly_values,
            mode="lines",
            line={"dash": "dash"},
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} h/workday<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            name=f"Monthly avg / workday ({TIMESERIES_MONTHLY_WINDOW_DAYS}d)",
            x=full_days,
            y=monthly_values,
            mode="lines",
            line={"dash": "dash"},
            hovertemplate="%{x|%Y-%m-%d}: %{y:.2f} h/workday<extra></extra>",
        )
    )
    figure.add_trace(
        go.Scatter(
            name="All-time avg / workday",
            x=full_days,
            y=[all_time_avg for _ in full_days],
            mode="lines",
            line={"dash": "dash"},
            hovertemplate="%{y:.2f} h/workday<extra></extra>",
        )
    )

    figure.update_layout(
        title="Daily total hours",
        height=DAILY_WORKING_HOURS_HEIGHT,
        hovermode="x unified",
        dragmode="pan",
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"l": 75, "r": 220, "t": 55, "b": 55},
        legend={
            "x": 1.02,
            "xanchor": "left",
            "y": 1.0,
            "yanchor": "top",
        },
        xaxis={
            "title": {"text": "Day"},
            "tickformat": "%Y-%m-%d",
            "showgrid": True,
            "gridcolor": "#d9d9d9",
            "rangeslider": {"visible": True, "thickness": 0.08},
            "rangeselector": {
                "buttons": [
                    {"count": 7, "label": "7d", "step": "day", "stepmode": "backward"},
                    {
                        "count": 30,
                        "label": "30d",
                        "step": "day",
                        "stepmode": "backward",
                    },
                    {
                        "count": 90,
                        "label": "90d",
                        "step": "day",
                        "stepmode": "backward",
                    },
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
    return figure


def _timeseries_html(figure: go.Figure) -> str:
    """Render a self-contained HTML page for one Plotly figure."""
    plotly_js = get_plotlyjs()
    figure_json = _script_safe_json(figure.to_json())
    config_json = '{"displaylogo": false, "responsive": true, "scrollZoom": true}'

    return f"""\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Interactive daily working hours</title>
  <style>
    html, body {{ margin: 0; padding: 0; background: white; font-family: sans-serif; }}
    .plot {{ width: 100%; }}
  </style>
</head>
<body>
  <div id="daily-working-hours" class="plot"></div>
  <script>{plotly_js}</script>
  <script>
    const figure = {figure_json};
    const plotConfig = {config_json};
    Plotly.newPlot("daily-working-hours", figure.data, figure.layout, plotConfig);
  </script>
</body>
</html>
"""


def _full_day_range(start_day: date, end_day: date) -> list[date]:
    """Return all calendar days in the inclusive range."""
    return [
        start_day + timedelta(days=offset)
        for offset in range((end_day - start_day).days + 1)
    ]


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


def _minutes_to_hours(minutes: float) -> float:
    """Convert minutes to hours."""
    return float(minutes) / 60.0


def _script_safe_json(json_text: str) -> str:
    """Prevent embedded JSON data from terminating a script element."""
    return json_text.replace("</", "<\\/")
