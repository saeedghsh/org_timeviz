"""Test interactive raw-tag aggregation and output integration."""

from datetime import datetime
from pathlib import Path

import pytest
from conftest import make_clipped, make_record

from org_timeviz.rendering.index import write_index_html
from org_timeviz.rendering.tag_timeseries import (
    compute_daily_tag_hours,
    write_tag_timeseries_html,
)


def test_tag_hours_split_days_and_keep_raw_tags() -> None:
    records = [
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 23, 30),
                end=datetime(2026, 1, 2, 0, 30),
                tags=("msc_theses", "unmapped", "msc_theses"),
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 2, 10),
                end=datetime(2026, 1, 2, 12),
                tags=("msc_theses",),
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 3, 9),
                end=datetime(2026, 1, 3, 10),
                tags=(),
            )
        ),
    ]

    hours = compute_daily_tag_hours(records)
    assert hours["msc_theses"] == pytest.approx({"2026-01-01": 0.5, "2026-01-02": 2.5})
    assert hours["unmapped"] == pytest.approx({"2026-01-01": 0.5, "2026-01-02": 0.5})


def test_tag_html_contains_controls_and_embedded_data(tmp_path: Path) -> None:
    record = make_clipped(
        make_record(
            start=datetime(2026, 1, 2, 9),
            end=datetime(2026, 1, 2, 10),
            tags=("arbitrary_tag",),
        )
    )
    out = tmp_path / "timeseries__tag__day__all_time.html"
    write_tag_timeseries_html([record], out)
    text = out.read_text(encoding="utf-8")

    assert 'id="tag-selector"' in text
    assert 'id="tag-total"' in text
    assert '"arbitrary_tag": {"2026-01-02": 1.0}' in text
    assert 'plot.on("plotly_relayout"' in text
    assert "Plotly.restyle" in text


def test_visualizations_embed_tag_report_without_changing_index(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "timeseries__tag__day__all_time.html").write_text("report", encoding="utf-8")
    write_index_html(tmp_path, assets)

    visualizations = (tmp_path / "visualizations.html").read_text(encoding="utf-8")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "interactive-tag-timeseries" in visualizations
    assert "timeseries__tag__day__all_time.html" in visualizations
    assert "timeseries__tag__day__all_time.html" not in index
