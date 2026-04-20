"""Generate a minimal index.html landing page for plot artifacts."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class _PlotItem:
    png_name: str
    summary_name: str | None


_BY_TASK_RE = re.compile(r"^by_task_(?P<period>week|month)_(?P<label>.+)\.png$")
_BY_TAGS_RE = re.compile(r"^by_tags_(?P<period>week|month)_(?P<label>.+)\.png$")
_CALENDAR_RE = re.compile(r"^calendar_(?P<period>week|month)_(?P<label>.+)\.png$")
_RANGE_LABEL_RE = re.compile(r"^(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})$")
_TIME_BUCKETS_RE = re.compile(r"^time_buckets_(?P<label>.+)\.png$")


def _discover_pngs(assets_dir: Path) -> list[str]:
    return sorted([p.name for p in assets_dir.glob("*.png")])


def _summary_for_png(assets_dir: Path, png_name: str) -> str | None:
    stem = png_name[:-4]
    candidate = assets_dir / f"{stem}__summary.json"
    return candidate.name if candidate.exists() else None


def _label_sort_key(label: str) -> tuple[int, str]:
    if label == "last":
        return (0, "")
    m = _RANGE_LABEL_RE.match(label)
    if m:
        return (1, m.group("start"))
    return (2, label)


def _wrap_item(item: _PlotItem, asset_prefix: str) -> str:
    png_href = f"{asset_prefix}/{item.png_name}"
    png_href_esc = html.escape(png_href)
    png_name_esc = html.escape(item.png_name)

    summ = ""
    if item.summary_name is not None:
        summ_href = f"{asset_prefix}/{item.summary_name}"
        summ_href_esc = html.escape(summ_href)
        summ = f' - <a href="{summ_href_esc}">summary</a>'

    return (
        "<li>"
        f"<details><summary>{png_name_esc}</summary>"
        f'<div class="links"><a href="{png_href_esc}">open image</a>{summ}</div>'
        f'<img class="plot" src="{png_href_esc}" loading="lazy" />'
        "</details>"
        "</li>"
    )


def _section(title: str, items: Iterable[_PlotItem], asset_prefix: str) -> str:
    items_list = list(items)
    if not items_list:
        return ""
    body = "\n".join(_wrap_item(it, asset_prefix=asset_prefix) for it in items_list)
    title_esc = html.escape(title)
    return (
        f"<details>\n<summary>{title_esc} ({len(items_list)})</summary>\n"
        "<ul>\n"
        f"{body}\n"
        "</ul>\n"
        "</details>\n"
    )


def write_index_html(out_root: Path, assets_dir: Path) -> Path:
    """Write outputs/index.html describing artifacts stored under outputs/assets."""
    out_root.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    pngs = _discover_pngs(assets_dir)
    asset_prefix = html.escape(assets_dir.name)

    timeseries: list[_PlotItem] = []
    by_task_week: list[tuple[str, _PlotItem]] = []
    by_task_month: list[tuple[str, _PlotItem]] = []
    by_tags_week: list[tuple[str, _PlotItem]] = []
    by_tags_month: list[tuple[str, _PlotItem]] = []
    calendar_week: list[tuple[str, _PlotItem]] = []
    calendar_month: list[tuple[str, _PlotItem]] = []
    time_buckets: list[_PlotItem] = []
    other: list[_PlotItem] = []

    for png in pngs:
        item = _PlotItem(png_name=png, summary_name=_summary_for_png(assets_dir, png))

        if png.startswith("timeseries_"):
            timeseries.append(item)
            continue

        m = _BY_TASK_RE.match(png)
        if m:
            period = m.group("period")
            label = m.group("label")
            if period == "week":
                by_task_week.append((label, item))
            else:
                by_task_month.append((label, item))
            continue

        m = _BY_TAGS_RE.match(png)
        if m:
            period = m.group("period")
            label = m.group("label")
            if period == "week":
                by_tags_week.append((label, item))
            else:
                by_tags_month.append((label, item))
            continue

        m = _CALENDAR_RE.match(png)
        if m:
            period = m.group("period")
            label = m.group("label")
            if period == "week":
                calendar_week.append((label, item))
            else:
                calendar_month.append((label, item))
            continue

        m = _TIME_BUCKETS_RE.match(png)
        if m:
            time_buckets.append(item)
            continue

        other.append(item)

    by_task_week.sort(key=lambda x: _label_sort_key(x[0]))
    by_task_month.sort(key=lambda x: _label_sort_key(x[0]))
    by_tags_week.sort(key=lambda x: _label_sort_key(x[0]))
    by_tags_month.sort(key=lambda x: _label_sort_key(x[0]))
    calendar_week.sort(key=lambda x: _label_sort_key(x[0]))
    calendar_month.sort(key=lambda x: _label_sort_key(x[0]))

    html_text = """\
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>org-timeviz outputs</title>
  <style>
    body { font-family: sans-serif; margin: 16px; max-width: 1100px; }
    h1 { font-size: 20px; margin: 0 0 12px 0; }
    details { margin: 10px 0; }
    summary { cursor: pointer; }
    ul { margin: 8px 0 0 18px; padding: 0; }
    li { margin: 6px 0; }
    .plot { display: block; max-width: 100%%; height: auto; margin: 8px 0 0 0; border: 1px solid #ddd; }
    .links { margin-top: 6px; }
  </style>
</head>
<body>
  <h1>org-timeviz outputs</h1>
  <p>Generated index for the current contents of this directory.</p>

  %s

  %s

  %s

  %s

  %s

  %s
</body>
</html>
""" % (
        _section("timeseries", timeseries, asset_prefix),
        _section("by_task / week", [it for _, it in by_task_week], asset_prefix)
        + _section("by_task / month", [it for _, it in by_task_month], asset_prefix),
        _section("by_tags / week", [it for _, it in by_tags_week], asset_prefix)
        + _section("by_tags / month", [it for _, it in by_tags_month], asset_prefix),
        _section("calendar / week", [it for _, it in calendar_week], asset_prefix)
        + _section("calendar / month", [it for _, it in calendar_month], asset_prefix),
        _section("time buckets", time_buckets, asset_prefix),
        _section("other", other, asset_prefix),
    )

    index_path = out_root / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return index_path
