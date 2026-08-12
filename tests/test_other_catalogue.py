import csv
from datetime import datetime
from pathlib import Path

import pytest

from org_timeviz.config import AppConfig
from org_timeviz.other_catalogue import (
    NO_TAG_LABEL,
    _compute_other_catalogue_hours,
    _write_other_catalogue_csv,
    generate_other_catalogue,
)

from conftest import make_clipped, make_record


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": {"output_dir": str(tmp_path)},
            "org_sources": {"mode": "explicit", "explicit_files": []},
            "time_buckets": {
                "other_bucket": "other",
                "bucket_order": ["work", "other"],
                "tag_to_bucket": {"job": "work"},
                "resolution": {
                    "default_strategy": "priority",
                    "priority_order": ["work", "other"],
                },
            },
        }
    )


def test_other_catalogue_counts_only_records_fully_in_other(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    records = [
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 9),
                end=datetime(2026, 1, 1, 10),
                tags=("unmapped",),
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 10),
                end=datetime(2026, 1, 1, 10, 30),
                tags=(),
            )
        ),
        make_clipped(
            make_record(
                start=datetime(2026, 1, 1, 11),
                end=datetime(2026, 1, 1, 12),
                tags=("job",),
            )
        ),
    ]
    assert _compute_other_catalogue_hours(cfg, records) == {
        "unmapped": pytest.approx(1.0),
        NO_TAG_LABEL: pytest.approx(0.5),
    }


def test_other_catalogue_csv_format(tmp_path: Path) -> None:
    path = tmp_path / "catalogue.csv"
    _write_other_catalogue_csv({"x": 1.234}, path)
    with path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.reader(handle)) == [["tag", "hours"], ["x", "1.23"]]


def test_generate_other_catalogue_writes_header_for_no_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(
        "org_timeviz.other_catalogue.resolve_org_inputs",
        lambda cfg: type("I", (), {"org_files": [], "agenda_init_path": None})(),
    )
    monkeypatch.setattr("org_timeviz.other_catalogue.configure_emacs_init", lambda *args: None)
    monkeypatch.setattr(
        "org_timeviz.other_catalogue.parse_org_clock_records_emacs", lambda **kwargs: []
    )
    path = generate_other_catalogue(cfg)
    assert path.read_text(encoding="utf-8") == "tag,hours\n"
