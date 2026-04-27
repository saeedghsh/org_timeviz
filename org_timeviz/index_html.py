"""Generate a minimal index.html landing page for plot artifacts."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FRONT_MATTER_SELECTORS = [
    "timeseries__time_bucket__month__all_time.png",
    "calendar_view__task__month__",
    "histogram__time_bucket__month__",
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
    return sorted([path_obj.name for path_obj in assets_dir.glob("*.png")])


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


def _leaf_section(title: str, items: Iterable[_PlotItem], asset_prefix: str) -> str:
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


def _node_section(title: str, body: str) -> str:
    if not body.strip():
        return ""

    title_esc = html.escape(title)
    return f"<details>\n<summary>{title_esc}</summary>\n" f"{body}\n" "</details>\n"


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

    visualization_sections: list[str] = []
    for visualization in sorted(tree.keys(), key=_visualization_sort_key):
        content_sections: list[str] = []

        for content in sorted(tree[visualization].keys(), key=_content_sort_key):
            period_sections: list[str] = []

            for period in sorted(tree[visualization][content].keys(), key=_period_sort_key):
                labeled_items = tree[visualization][content][period]
                labeled_items.sort(key=lambda pair: _label_sort_key(pair[0]))
                period_sections.append(
                    _leaf_section(
                        period,
                        [item for _, item in labeled_items],
                        asset_prefix,
                    )
                )

            content_sections.append(_node_section(content, "\n".join(period_sections)))

        visualization_sections.append(_node_section(visualization, "\n".join(content_sections)))

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
</body>
</html>
""" % (
        _front_matter_section(featured_items, asset_prefix),
        "\n".join(visualization_sections),
        _leaf_section("other", other, asset_prefix),
    )

    index_path = out_root / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return index_path
