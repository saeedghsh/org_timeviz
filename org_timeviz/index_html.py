"""Generate index and gallery HTML pages for plot artifacts."""

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FRONT_MATTER_SELECTORS = [
    "calendar_view__time_bucket__month__",
    "histogram__time_bucket__month__",
    "timeseries__time_bucket__month__all_time.png",
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


def _front_matter_section(items: Iterable[_PlotItem], asset_prefix: str) -> str:
    items_list = list(items)
    if not items_list:
        return ""

    body = "\n".join(_wrap_gallery_item(item, asset_prefix=asset_prefix) for item in items_list)
    return (
        '<section class="featured-gallery">\n'
        "  <h1>Featured plots</h1>\n"
        f"{body}\n"
        "</section>\n"
    )


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
    return (
        "<li>"
        f'<a href="{page_href}">{period_esc}</a> '
        f'<span class="count">({count})</span>'
        "</li>"
    )


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


def write_index_html(out_root: Path, assets_dir: Path) -> Path:
    """Write outputs/index.html and leaf gallery pages for current artifacts."""
    out_root.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    pngs = _discover_pngs(assets_dir)
    asset_prefix = assets_dir.name

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
            '<li><a href="other.html">other</a> ' f'<span class="count">({len(other)})</span></li>'
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
    .links { margin-top: 6px; }
    .featured-gallery { margin-bottom: 28px; }
    .gallery-item { margin: 0 0 28px 0; }
    .outputs-section { margin-top: 40px; }
    .tree { list-style: none; padding-left: 0; margin: 0; }
    .tree ul { list-style: none; margin: 4px 0 0 0; }
    .level-1 { padding-left: 20px; }
    .level-2 { padding-left: 20px; }
    .node-label { font-weight: bold; }
    .count { color: #555; }
    .tree li { margin: 6px 0; }
  </style>
</head>
<body>
  %s

  <section class="outputs-section">
    <h1>org-timeviz outputs</h1>
    <ul class="tree">
      %s
    </ul>
  </section>
</body>
</html>
""" % (
        _front_matter_section(featured_items, asset_prefix),
        "\n".join(visualization_nodes),
    )

    index_path = out_root / "index.html"
    index_path.write_text(html_text, encoding="utf-8")
    return index_path
