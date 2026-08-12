from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from org_timeviz import cli, reports
from org_timeviz.config import AppConfig

from conftest import make_record


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": {"output_dir": str(tmp_path)},
            "org_sources": {"mode": "explicit", "explicit_files": []},
            "reports": {"plots": {"top_k_tasks": 5, "timeseries_last_n_days": None}},
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


def test_cli_parse_args_defaults_to_default_config() -> None:
    assert cli._parse_args([]).config == Path("configs/default.yaml")


def test_cli_main_loads_config_and_generates_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
time_buckets:
  other_bucket: other
  bucket_order: [other]
  tag_to_bucket: {}
  resolution:
    default_strategy: priority
    priority_order: [other]
""",
        encoding="utf-8",
    )
    seen: list[AppConfig] = []
    monkeypatch.setattr(cli, "setup_logger", lambda level: None)
    monkeypatch.setattr(cli, "generate_all_reports", lambda cfg: seen.append(cfg))
    assert cli.main(["--config", str(path)]) == 0
    assert len(seen) == 1


def test_generate_all_reports_returns_early_without_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(
        reports,
        "resolve_org_inputs",
        lambda cfg: SimpleNamespace(org_files=[], agenda_init_path=None),
    )
    monkeypatch.setattr(reports, "configure_emacs_init", lambda *args: None)
    monkeypatch.setattr(reports, "parse_org_clock_records_emacs", lambda **kwargs: [])
    reports.generate_all_reports(cfg)
    assert not (tmp_path / "assets").exists()


def test_generate_all_reports_orchestrates_all_current_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _cfg(tmp_path)
    cfg.reports.plots.timeseries_last_n_days = 14
    records = [
        make_record(
            start=datetime(2026, 1, 10, 9),
            end=datetime(2026, 1, 10, 10),
            tags=("job",),
            headline="Task",
        ),
        make_record(
            start=datetime(2026, 2, 10, 9),
            end=datetime(2026, 2, 10, 10),
            tags=("job",),
            headline="Task 2",
        ),
    ]
    calls: list[tuple[str, Path]] = []

    monkeypatch.setattr(
        reports,
        "resolve_org_inputs",
        lambda cfg: SimpleNamespace(org_files=[Path("one.org")], agenda_init_path=None),
    )
    monkeypatch.setattr(reports, "configure_emacs_init", lambda *args: None)
    monkeypatch.setattr(reports, "parse_org_clock_records_emacs", lambda **kwargs: records)
    monkeypatch.setattr(
        reports,
        "plot_calendar_view_by_task",
        lambda records, out_path, **kwargs: calls.append(("calendar", out_path)),
    )
    monkeypatch.setattr(
        reports,
        "plot_timeseries_daily_total",
        lambda aggs, out_path: calls.append(("timeseries", out_path)),
    )
    monkeypatch.setattr(
        reports,
        "plot_monthly_time_buckets",
        lambda report, out_path: calls.append(("monthly_buckets", out_path)),
    )
    monkeypatch.setattr(
        reports,
        "write_interactive_time_bucket_dashboard",
        lambda records, out_path, **kwargs: calls.append(("interactive", out_path)),
    )
    monkeypatch.setattr(reports, "write_summary_json", lambda aggs, out_path: None)
    monkeypatch.setattr(
        reports, "write_monthly_time_buckets_summary_json", lambda report, out_path: None
    )
    monkeypatch.setattr(
        reports,
        "write_index_html",
        lambda out_root, assets_dir: (
            calls.append(("index", out_root / "index.html")) or out_root / "index.html"
        ),
    )

    reports.generate_all_reports(cfg)

    kinds = [kind for kind, _ in calls]
    assert kinds.count("calendar") == 3  # latest rolling view + Jan/Feb calendar months
    assert kinds.count("timeseries") == 1
    assert kinds.count("monthly_buckets") == 1
    assert kinds.count("interactive") == 1
    assert kinds.count("index") == 1
