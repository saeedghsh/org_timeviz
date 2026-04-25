"""Generate a minimal index.html landing page for plot artifacts."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FRONT_MATTER_PNGS = [
    "time_buckets_monthly.png",
    "calendar_month_last.png",
    "by_task_month_last.png",
    "by_time_bucket_month_last.png",
]


@dataclass(frozen=True)
class _PlotItem:
    png_name: str
    summary_name: str | None


_BY_TASK_RE = re.compile(r"^by_task_(?P<period>week|month)_(?P<label>.+)\.png$")
_BY_TIME_BUCKET_RE = re.compile(r"^by_time_bucket_(?P<period>week|month)_(?P<label>.+)\.png$")
_CALENDAR_RE = re.compile(r"^calendar_(?P<period>week|month)_(?P<label>.+)\.png$")
_TIME_BUCKETS_RE = re.compile(r"^time_buckets_(?P<label>.+)\.png$")
_RANGE_LABEL_RE = re.compile(r"^(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})$")


def _discover_pngs(assets_dir: Path) -> list[str]:
    return sorted([path_obj.name for path_obj in assets_dir.glob("*.png")])


def _summary_for_png(assets_dir: Path, png_name: str) -> str | None:
    stem = png_name[:-4]
    candidate = assets_dir / f"{stem}__summary.json"
    return candidate.name if candidate.exists() else None


def _label_sort_key(label: str) -> tuple[int, int | str]:
    if label == "last":
        return (0, 0)

    match_obj = _RANGE_LABEL_RE.match(label)
    if match_obj:
        start_date = match_obj.group("start")
        year_str, month_str, day_str = start_date.split("-")
        ordinal = int(year_str) * 10000 + int(month_str) * 100 + int(day_str)
        return (1, -ordinal)

    return (2, label)


def _wrap_item(item: _PlotItem, asset_prefix: str) -> str:
    png_href = f"{asset_prefix}/{item.png_name}"
    png_href_esc = html.escape(png_href)
    png_name_esc = html.escape(item.png_name)

    summary_html = ""
    if item.summary_name is not None:
        summary_href = f"{asset_prefix}/{item.summary_name}"
        summary_href_esc = html.escape(summary_href)
        summary_html = f' - <a href="{summary_href_esc}">summary</a>'

    return (
        "<li>"
        f"<details><summary>{png_name_esc}</summary>"
        f'<div class="links"><a href="{png_href_esc}">open image</a>{summary_html}</div>'
        f'<img class="plot" src="{png_href_esc}" loading="lazy" />'
        "</details>"
        "</li>"
    )


def _section(title: str, items: Iterable[_PlotItem], asset_prefix: str) -> str:
    items_list = list(items)
    if not items_list:
        return ""
    body = "\n".join(_wrap_item(item, asset_prefix=asset_prefix) for item in items_list)
    title_esc = html.escape(title)
    return (
        f"<details>\n<summary>{title_esc} ({len(items_list)})</summary>\n"
        "<ul>\n"
        f"{body}\n"
        "</ul>\n"
        "</details>\n"
    )


def _front_matter_section(items: Iterable[_PlotItem], asset_prefix: str) -> str:
    items_list = list(items)
    if not items_list:
        return ""

    blocks: list[str] = []
    for item in items_list:
        png_href = f"{asset_prefix}/{item.png_name}"
        png_href_esc = html.escape(png_href)
        title_esc = html.escape(item.png_name)
        blocks.append(
            '<section class="featured-item">\n'
            f"  <h2>{title_esc}</h2>\n"
            f'  <div class="links"><a href="{png_href_esc}">open image</a></div>\n'
            f'  <img class="plot" src="{png_href_esc}" loading="lazy" />\n'
            "</section>"
        )

    body = "\n".join(blocks)
    return (
        '<section class="featured-gallery">\n'
        "  <h1>Featured plots</h1>\n"
        f"{body}\n"
        "</section>\n"
    )


def write_index_html(out_root: Path, assets_dir: Path) -> Path:
    """Write outputs/index.html describing artifacts stored under outputs/assets."""
    out_root.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    pngs = _discover_pngs(assets_dir)
    asset_prefix = html.escape(assets_dir.name)

    items_by_png = {
        png_name: _PlotItem(
            png_name=png_name,
            summary_name=_summary_for_png(assets_dir, png_name),
        )
        for png_name in pngs
    }

    featured_items = [
        items_by_png[png_name] for png_name in FRONT_MATTER_PNGS if png_name in items_by_png
    ]

    timeseries: list[_PlotItem] = []
    by_task_week: list[tuple[str, _PlotItem]] = []
    by_task_month: list[tuple[str, _PlotItem]] = []
    by_time_bucket_week: list[tuple[str, _PlotItem]] = []
    by_time_bucket_month: list[tuple[str, _PlotItem]] = []
    calendar_week: list[tuple[str, _PlotItem]] = []
    calendar_month: list[tuple[str, _PlotItem]] = []
    time_buckets: list[_PlotItem] = []
    other: list[_PlotItem] = []

    for png in pngs:
        item = items_by_png[png]

        if png.startswith("timeseries_"):
            timeseries.append(item)
            continue

        match_obj = _BY_TASK_RE.match(png)
        if match_obj:
            period = match_obj.group("period")
            label = match_obj.group("label")
            if period == "week":
                by_task_week.append((label, item))
            else:
                by_task_month.append((label, item))
            continue

        match_obj = _BY_TIME_BUCKET_RE.match(png)
        if match_obj:
            period = match_obj.group("period")
            label = match_obj.group("label")
            if period == "week":
                by_time_bucket_week.append((label, item))
            else:
                by_time_bucket_month.append((label, item))
            continue

        match_obj = _CALENDAR_RE.match(png)
        if match_obj:
            period = match_obj.group("period")
            label = match_obj.group("label")
            if period == "week":
                calendar_week.append((label, item))
            else:
                calendar_month.append((label, item))
            continue

        match_obj = _TIME_BUCKETS_RE.match(png)
        if match_obj:
            time_buckets.append(item)
            continue

        other.append(item)

    by_task_week.sort(key=lambda item: _label_sort_key(item[0]))
    by_task_month.sort(key=lambda item: _label_sort_key(item[0]))
    by_time_bucket_week.sort(key=lambda item: _label_sort_key(item[0]))
    by_time_bucket_month.sort(key=lambda item: _label_sort_key(item[0]))
    calendar_week.sort(key=lambda item: _label_sort_key(item[0]))
    calendar_month.sort(key=lambda item: _label_sort_key(item[0]))

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
    details { margin: 10px 0; }
    summary { cursor: pointer; }
    ul { margin: 8px 0 0 18px; padding: 0; }
    li { margin: 6px 0; }
    .plot { display: block; max-width: 100%%; height: auto; margin: 8px 0 0 0; border: 1px solid #ddd; }
    .links { margin-top: 6px; }
    .featured-gallery { margin-bottom: 28px; }
    .featured-item { margin: 0 0 28px 0; }
  </style>
</head>
<body>
  %s

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
        _front_matter_section(featured_items, asset_prefix),
        _section("timeseries", timeseries, asset_prefix),
        _section("by_task / week", [item for _, item in by_task_week], asset_prefix)
        + _section("by_task / month", [item for _, item in by_task_month], asset_prefix),
        _section(
            "by_time_bucket / week",
            [item for _, item in by_time_bucket_week],
            asset_prefix,
        )
        + _section(
            "by_time_bucket / month",
            [item for _, item in by_time_bucket_month],
            asset_prefix,
        ),
        _section("calendar / week", [item for _, item in calendar_week], asset_prefix)
        + _section("calendar / month", [item for _, item in calendar_month], asset_prefix),
        _section("time buckets", time_buckets, asset_prefix),
        _section("other", other, asset_prefix),
    )

    index_path = out_root / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return index_path
