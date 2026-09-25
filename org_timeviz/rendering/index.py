"""Generate index and gallery HTML pages for plot artifacts."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

INTERACTIVE_TIME_BUCKET_DASHBOARD_NAME = "interactive__time_bucket.html"
INTERACTIVE_MONTHLY_TIME_BUCKET_NAME = "timeseries__time_bucket__month__all_time.html"

DEPRECATED_PNG_PREFIXES = (
    "calendar_view__task__",
    "calendar_view__time_bucket__",
    "histogram__time_bucket__",
    "timeseries__time_bucket__month__",
)

FRONT_MATTER_SELECTORS = [
    "timeseries__daily_working_hours__day__all_time.png",
]

_RANGE_LABEL_RE = re.compile(
    r"^(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})(?:__(?P<kind>latest))?$"
)

VISUALIZATION_ORDER = {
    "histogram": 0,
    "calendar_view": 1,
    "timeseries": 2,
}

CONTENT_ORDER = {
    "task": 0,
    "time_bucket": 1,
    "daily_working_hours": 2,
}

PERIOD_ORDER = {
    "week": 0,
    "month": 1,
    "day": 2,
}


@dataclass(frozen=True)
class _PlotItem:
    png_name: str
    summary_name: str | None


@dataclass(frozen=True)
class _ParsedPlotName:
    visualization: str
    content: str
    period: str
    label: str


def _discover_pngs(assets_dir: Path) -> list[str]:
    return sorted(
        path_obj.name
        for path_obj in assets_dir.glob("*.png")
        if not path_obj.name.startswith(DEPRECATED_PNG_PREFIXES)
    )


def _summary_for_png(assets_dir: Path, png_name: str) -> str | None:
    stem = png_name[:-4]
    candidate = assets_dir / f"{stem}__summary.json"
    return candidate.name if candidate.exists() else None


def _parse_plot_name(png_name: str) -> _ParsedPlotName | None:
    stem = png_name[:-4]
    parts = stem.split("__")
    if len(parts) < 4:
        return None

    return _ParsedPlotName(
        visualization=parts[0],
        content=parts[1],
        period=parts[2],
        label="__".join(parts[3:]),
    )


def _resolve_front_matter_items(
    items_by_png: dict[str, _PlotItem],
) -> list[_PlotItem]:
    """Resolve featured items from exact names or filename prefixes."""
    selected: list[_PlotItem] = []
    for selector in FRONT_MATTER_SELECTORS:
        if selector.endswith(".png"):
            if selector in items_by_png:
                selected.append(items_by_png[selector])
            continue

        matches = sorted(png_name for png_name in items_by_png if png_name.startswith(selector))
        if matches:
            selected.append(items_by_png[matches[-1]])

    return selected


def _label_sort_key(label: str) -> tuple[int, int | str]:
    if label == "all_time":
        return (0, 0)

    match_obj = _RANGE_LABEL_RE.match(label)
    if match_obj:
        start_date = match_obj.group("start")
        year_str, month_str, day_str = start_date.split("-")
        ordinal = int(year_str) * 10000 + int(month_str) * 100 + int(day_str)

        if match_obj.group("kind") == "latest":
            return (1, -ordinal)

        return (2, -ordinal)

    return (3, label)


def _visualization_sort_key(name: str) -> tuple[int, str]:
    return (VISUALIZATION_ORDER.get(name, 999), name)


def _content_sort_key(name: str) -> tuple[int, str]:
    return (CONTENT_ORDER.get(name, 999), name)


def _period_sort_key(name: str) -> tuple[int, str]:
    return (PERIOD_ORDER.get(name, 999), name)


def _wrap_gallery_item(item: _PlotItem, asset_prefix: str) -> str:
    png_href = html.escape(f"{asset_prefix}/{item.png_name}")
    png_name_esc = html.escape(item.png_name)

    summary_html = ""
    if item.summary_name is not None:
        summary_href = html.escape(f"{asset_prefix}/{item.summary_name}")
        summary_html = f' - <a href="{summary_href}">summary</a>'

    return (
        '<section class="gallery-item">\n'
        f"  <h2>{png_name_esc}</h2>\n"
        f'  <div class="links"><a href="{png_href}">open image</a>{summary_html}</div>\n'
        f'  <img class="plot" src="{png_href}" loading="lazy" />\n'
        "</section>\n"
    )


def _wrap_interactive_time_bucket(asset_prefix: str) -> str:
    dashboard_href = html.escape(f"{asset_prefix}/{INTERACTIVE_TIME_BUCKET_DASHBOARD_NAME}")
    return (
        '<section class="gallery-item">\n'
        "  <h2>calendar_view / histogram__time_bucket</h2>\n"
        f'  <div class="links"><a href="{dashboard_href}">open interactive view</a></div>\n'
        f'  <iframe class="interactive-dashboard" src="{dashboard_href}" '
        'title="Interactive calendar and time-bucket histogram"></iframe>\n'
        "</section>\n"
    )


def _wrap_interactive_monthly_time_bucket(asset_prefix: str) -> str:
    dashboard_href = html.escape(f"{asset_prefix}/{INTERACTIVE_MONTHLY_TIME_BUCKET_NAME}")
    return (
        '<section class="gallery-item">\n'
        "  <h2>timeseries__time_bucket__month__all_time</h2>\n"
        f'  <div class="links"><a href="{dashboard_href}">open interactive view</a></div>\n'
        f'  <iframe class="interactive-dashboard" src="{dashboard_href}" '
        'title="Interactive monthly time-bucket trends"></iframe>\n'
        "</section>\n"
    )


def _front_matter_section(
    items: Iterable[_PlotItem],
    asset_prefix: str,
    *,
    include_interactive_time_bucket: bool,
    include_interactive_monthly_time_bucket: bool,
) -> str:
    body_parts: list[str] = []
    if include_interactive_time_bucket:
        body_parts.append(_wrap_interactive_time_bucket(asset_prefix))
    if include_interactive_monthly_time_bucket:
        body_parts.append(_wrap_interactive_monthly_time_bucket(asset_prefix))

    body_parts.extend(_wrap_gallery_item(item, asset_prefix=asset_prefix) for item in items)
    if not body_parts:
        return ""

    body = "\n".join(body_parts)
    return f'<section class="featured-gallery">\n  <h1>Featured plots</h1>\n{body}\n</section>\n'


def _gallery_page_html(
    *,
    title: str,
    items: list[_PlotItem],
    asset_prefix: str,
) -> str:
    body = "\n".join(_wrap_gallery_item(item, asset_prefix=asset_prefix) for item in items)
    title_esc = html.escape(title)

    return """\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>%s</title>
  <style>
    body { font-family: sans-serif; margin: 16px; max-width: 1100px; }
    h1 { font-size: 22px; margin: 0 0 16px 0; }
    h2 { font-size: 18px; margin: 0 0 8px 0; }
    .plot { display: block; max-width: 100%%; height: auto; margin: 8px 0 0 0; border: 1px solid #ddd; }
    .links { margin-top: 6px; }
    .gallery-item { margin: 0 0 28px 0; }
    .back-link { margin: 0 0 20px 0; }
  </style>
</head>
<body>
  <div class="back-link"><a href="index.html">back to index</a></div>
  <h1>%s</h1>
  %s
</body>
</html>
""" % (
        title_esc,
        title_esc,
        body,
    )


def _write_gallery_page(
    *,
    out_root: Path,
    page_name: str,
    title: str,
    items: list[_PlotItem],
    asset_prefix: str,
) -> None:
    page_path = out_root / page_name
    page_path.write_text(
        _gallery_page_html(
            title=title,
            items=items,
            asset_prefix=asset_prefix,
        ),
        encoding="utf-8",
    )


def _tree_period_node(
    *,
    period: str,
    page_name: str,
    count: int,
) -> str:
    period_esc = html.escape(period)
    page_href = html.escape(page_name)
    return f'<li><a href="{page_href}">{period_esc}</a> <span class="count">({count})</span></li>'


def _tree_content_node(
    *,
    content: str,
    body: str,
) -> str:
    content_esc = html.escape(content)
    return (
        "<li>"
        f'<span class="node-label">{content_esc}</span>'
        f'<ul class="tree level-2">{body}</ul>'
        "</li>"
    )


def _tree_visualization_node(
    *,
    visualization: str,
    body: str,
) -> str:
    visualization_esc = html.escape(visualization)
    return (
        "<li>"
        f'<span class="node-label">{visualization_esc}</span>'
        f'<ul class="tree level-1">{body}</ul>'
        "</li>"
    )


def _refresh_controls_html() -> str:
    """Render browser controls for regenerating reports through the local server."""
    return """\
  <section class="refresh-controls">
    <button id="refresh-reports" type="button">Refresh reports</button>
    <span id="refresh-status" role="status"></span>
  </section>
  <script>
    (() => {
      const button = document.getElementById("refresh-reports");
      const status = document.getElementById("refresh-status");

      if (window.location.protocol === "file:") {
        button.disabled = true;
        status.textContent = "Refresh requires make serve.";
        return;
      }

      button.addEventListener("click", async () => {
        button.disabled = true;
        status.textContent = "Refreshing reports...";

        try {
          const response = await fetch("/refresh", {
            method: "POST",
            headers: {"X-Org-Timeviz-Refresh": "1"},
            cache: "no-store",
          });
          if (!response.ok) {
            throw new Error(`server returned HTTP ${response.status}`);
          }
          window.location.reload();
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          status.textContent = `Refresh failed: ${message}`;
          button.disabled = false;
        }
      });
    })();
  </script>
"""


def _clock_dashboard_html() -> str:
    """Render live text clock reports and date/week controls."""
    return """\
  <section class="clock-dashboard">
    <div class="clock-dashboard-heading">
      <h1>Clock dashboard</h1>
      <div class="clock-dashboard-actions">
        <button id="refresh-clock-dashboard" type="button">Refresh clock reports</button>
        <span id="clock-dashboard-status" role="status"></span>
      </div>
    </div>
    <p class="clock-dashboard-note">
      Live clocks are counted through the current time. Changing the date or week updates only
      these text reports; it does not regenerate the plots below.
    </p>

    <article class="clock-report">
      <h2>Suspicious clocks</h2>
      <pre><code id="clock-suspects">Loading...</code></pre>
    </article>

    <article class="clock-report">
      <div class="clock-report-heading">
        <h2>Chronological entries</h2>
        <label>Day <input id="clock-day" type="date" /></label>
      </div>
      <pre><code id="clock-chronological">Loading...</code></pre>
    </article>

    <article class="clock-report compact-clock-report">
      <div class="clock-report-heading">
        <h2>Total time logged — day</h2>
        <label>Day <input id="clock-day-total-date" type="date" /></label>
      </div>
      <pre><code id="clock-day-total">Loading...</code></pre>
    </article>

    <article class="clock-report compact-clock-report">
      <div class="clock-report-heading">
        <h2>Total time logged — week</h2>
        <label>Week containing <input id="clock-week-date" type="date" /></label>
      </div>
      <pre><code id="clock-week-total">Loading...</code></pre>
    </article>
  </section>
  <script>
    (() => {
      const dayInput = document.getElementById("clock-day");
      const dayTotalDateInput = document.getElementById("clock-day-total-date");
      const weekDateInput = document.getElementById("clock-week-date");
      const refreshButton = document.getElementById("refresh-clock-dashboard");
      const dashboardStatus = document.getElementById("clock-dashboard-status");
      const suspects = document.getElementById("clock-suspects");
      const chronological = document.getElementById("clock-chronological");
      const dayTotal = document.getElementById("clock-day-total");
      const weekTotal = document.getElementById("clock-week-total");
      const outputs = [suspects, chronological, dayTotal, weekTotal];

      function localDateValue(value) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, "0");
        const day = String(value.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
      }

      function setAll(message) {
        for (const output of outputs) {
          output.textContent = message;
        }
      }

      function renderChronological(value) {
        chronological.replaceChildren();
        const lines = value.split("\\n");
        for (const [index, line] of lines.entries()) {
          const row = document.createElement("span");
          if (/^[|] GAP +[|]/.test(line)) {
            row.className = "clock-gap-row";
          }
          row.textContent = line;
          chronological.append(row);
          if (index < lines.length - 1) {
            chronological.append(document.createTextNode("\\n"));
          }
        }
      }

      async function loadClockDashboard() {
        setAll("Loading...");
        refreshButton.disabled = true;
        dashboardStatus.textContent = "Refreshing...";
        const params = new URLSearchParams({
          date: dayInput.value,
          day_total_date: dayTotalDateInput.value,
          week_date: weekDateInput.value,
        });

        try {
          const response = await fetch(`/clock-dashboard?${params}`, {cache: "no-store"});
          if (!response.ok) {
            throw new Error(`server returned HTTP ${response.status}`);
          }
          const payload = await response.json();
          suspects.textContent = payload.suspects;
          renderChronological(payload.chronological);
          dayTotal.textContent = `${payload.day_total_day}: ${payload.day_total}`;
          weekTotal.textContent = `${payload.week_start} to ${payload.week_end}: ${payload.week_total}`;
          dashboardStatus.textContent = "";
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          setAll(`Clock dashboard failed: ${message}`);
          dashboardStatus.textContent = `Refresh failed: ${message}`;
        } finally {
          refreshButton.disabled = false;
        }
      }

      const now = new Date();
      dayInput.value = localDateValue(now);
      dayTotalDateInput.value = localDateValue(now);
      weekDateInput.value = localDateValue(now);

      if (window.location.protocol === "file:") {
        dayInput.disabled = true;
        dayTotalDateInput.disabled = true;
        weekDateInput.disabled = true;
        refreshButton.disabled = true;
        setAll("Clock dashboard requires make serve.");
        return;
      }

      dayInput.addEventListener("change", loadClockDashboard);
      dayTotalDateInput.addEventListener("change", loadClockDashboard);
      weekDateInput.addEventListener("change", loadClockDashboard);
      refreshButton.addEventListener("click", loadClockDashboard);
      loadClockDashboard();
    })();
  </script>
"""


def write_index_html(out_root: Path, assets_dir: Path) -> Path:
    """Write outputs/index.html and leaf gallery pages for current artifacts."""
    out_root.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    pngs = _discover_pngs(assets_dir)
    asset_prefix = assets_dir.name
    interactive_time_bucket_exists = (assets_dir / INTERACTIVE_TIME_BUCKET_DASHBOARD_NAME).exists()
    interactive_monthly_time_bucket_exists = (
        assets_dir / INTERACTIVE_MONTHLY_TIME_BUCKET_NAME
    ).exists()

    items_by_png = {
        png_name: _PlotItem(
            png_name=png_name,
            summary_name=_summary_for_png(assets_dir, png_name),
        )
        for png_name in pngs
    }

    featured_items = _resolve_front_matter_items(items_by_png)

    tree: dict[str, dict[str, dict[str, list[tuple[str, _PlotItem]]]]] = {}
    other: list[_PlotItem] = []

    for png_name in pngs:
        parsed = _parse_plot_name(png_name)
        item = items_by_png[png_name]

        if parsed is None:
            other.append(item)
            continue

        tree.setdefault(parsed.visualization, {})
        tree[parsed.visualization].setdefault(parsed.content, {})
        tree[parsed.visualization][parsed.content].setdefault(parsed.period, [])
        tree[parsed.visualization][parsed.content][parsed.period].append((parsed.label, item))

    visualization_nodes: list[str] = []

    for visualization in sorted(tree.keys(), key=_visualization_sort_key):
        content_nodes: list[str] = []

        for content in sorted(tree[visualization].keys(), key=_content_sort_key):
            period_nodes: list[str] = []

            for period in sorted(tree[visualization][content].keys(), key=_period_sort_key):
                labeled_items = tree[visualization][content][period]
                labeled_items.sort(key=lambda pair: _label_sort_key(pair[0]))
                items = [item for _, item in labeled_items]

                page_name = f"{visualization}__{content}__{period}.html"
                page_title = f"{visualization} / {content} / {period}"
                _write_gallery_page(
                    out_root=out_root,
                    page_name=page_name,
                    title=page_title,
                    items=items,
                    asset_prefix=asset_prefix,
                )

                period_nodes.append(
                    _tree_period_node(
                        period=period,
                        page_name=page_name,
                        count=len(items),
                    )
                )

            content_nodes.append(
                _tree_content_node(
                    content=content,
                    body="\n".join(period_nodes),
                )
            )

        visualization_nodes.append(
            _tree_visualization_node(
                visualization=visualization,
                body="\n".join(content_nodes),
            )
        )

    if other:
        _write_gallery_page(
            out_root=out_root,
            page_name="other.html",
            title="other",
            items=other,
            asset_prefix=asset_prefix,
        )
        visualization_nodes.append(
            f'<li><a href="other.html">other</a> <span class="count">({len(other)})</span></li>'
        )

    html_text = """\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>org-timeviz outputs</title>
  <style>
    body { font-family: sans-serif; margin: 16px; max-width: 1100px; }
    h1 { font-size: 22px; margin: 0 0 16px 0; }
    h2 { font-size: 18px; margin: 0 0 8px 0; }
    .plot { display: block; max-width: 100%%; height: auto; margin: 8px 0 0 0; border: 1px solid #ddd; }
    .interactive-dashboard { display: block; width: 100%%; height: 1100px; margin: 8px 0 0 0; border: 1px solid #ddd; }
    .links { margin-top: 6px; }
    .featured-gallery { margin-bottom: 28px; }
    .gallery-item { margin: 0 0 28px 0; }
    .refresh-controls { display: flex; align-items: center; gap: 12px; margin: 0 0 20px 0; }
    .refresh-controls button { padding: 8px 14px; cursor: pointer; }
    .refresh-controls button:disabled { cursor: default; opacity: 0.6; }
    #refresh-status { color: #555; }
    .clock-dashboard { margin: 0 0 36px 0; }
    .clock-dashboard-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .clock-dashboard-actions { display: flex; align-items: center; gap: 10px; }
    .clock-dashboard-actions button { padding: 7px 12px; cursor: pointer; }
    .clock-dashboard-actions button:disabled { cursor: default; opacity: 0.6; }
    #clock-dashboard-status { color: #555; }
    .clock-dashboard-note { color: #555; margin: -6px 0 18px 0; }
    .clock-report { margin: 0 0 22px 0; }
    .compact-clock-report { max-width: 720px; }
    .clock-report-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    .clock-report-heading label { white-space: nowrap; }
    .clock-report-heading input { margin-left: 6px; }
    .clock-report pre { overflow-x: auto; margin: 8px 0 0 0; padding: 12px; background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; }
    .clock-report code { font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }
    .clock-gap-row { color: #656d76; }
  </style>
</head>
<body>
  %s

  %s

  %s

</body>
</html>
""" % (
        _refresh_controls_html(),
        _clock_dashboard_html(),
        _front_matter_section(
            featured_items,
            asset_prefix,
            include_interactive_time_bucket=interactive_time_bucket_exists,
            include_interactive_monthly_time_bucket=interactive_monthly_time_bucket_exists,
        ),
    )

    index_path = out_root / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return index_path
