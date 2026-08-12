import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from org_timeviz.config import AppConfig
from org_timeviz.org_source.agenda import read_agenda_files_from_emacs_init
from org_timeviz.org_source.emacs import parse_org_clock_records_emacs
from org_timeviz.org_source.inputs import configure_emacs_init, resolve_org_inputs


def _app_config(**org_source_overrides: object) -> AppConfig:
    org_sources = {
        "mode": "explicit",
        "emacs_init_paths": [],
        "emacs_agenda_var": "org-agenda-files",
        "explicit_files": [],
    }
    org_sources.update(org_source_overrides)
    return AppConfig.model_validate(
        {
            "org_sources": org_sources,
            "time_buckets": {
                "other_bucket": "other",
                "bucket_order": ["other"],
                "tag_to_bucket": {},
                "resolution": {
                    "default_strategy": "priority",
                    "priority_order": ["other"],
                },
            },
        }
    )


def test_read_agenda_files_handles_comments_and_strings(tmp_path: Path) -> None:
    init = tmp_path / "init.el"
    init.write_text(
        '''
;; org-agenda-files in a comment must not count
(setq org-agenda-files
      '("~/one.org"
        ;; "ignored.org"
        "~/two.org"))
''',
        encoding="utf-8",
    )
    result = read_agenda_files_from_emacs_init(init, "org-agenda-files")
    assert result is not None
    assert [path.name for path in result.files] == ["one.org", "two.org"]
    assert result.source_path == init


def test_read_agenda_files_returns_none_for_missing_or_absent(tmp_path: Path) -> None:
    assert read_agenda_files_from_emacs_init(tmp_path / "missing.el", "org-agenda-files") is None
    init = tmp_path / "init.el"
    init.write_text("(setq something-else '(\"x\"))", encoding="utf-8")
    assert read_agenda_files_from_emacs_init(init, "org-agenda-files") is None


def test_resolve_explicit_inputs(tmp_path: Path) -> None:
    init = tmp_path / "init.el"
    init.write_text("", encoding="utf-8")
    cfg = _app_config(
        mode="explicit",
        emacs_init_paths=[str(init)],
        explicit_files=["~/one.org", "~/two.org"],
    )
    result = resolve_org_inputs(cfg)
    assert [path.name for path in result.org_files] == ["one.org", "two.org"]
    assert result.agenda_init_path == init


def test_resolve_emacs_inputs(tmp_path: Path) -> None:
    init = tmp_path / "init.el"
    init.write_text('(setq org-agenda-files \'("/tmp/a.org" "/tmp/b.org"))', encoding="utf-8")
    cfg = _app_config(mode="emacs", emacs_init_paths=[str(init)])
    result = resolve_org_inputs(cfg)
    assert result.org_files == [Path("/tmp/a.org"), Path("/tmp/b.org")]


def test_resolve_emacs_inputs_raises_if_not_found(tmp_path: Path) -> None:
    cfg = _app_config(mode="emacs", emacs_init_paths=[str(tmp_path / "missing.el")])
    with pytest.raises(FileNotFoundError):
        resolve_org_inputs(cfg)


def test_configure_emacs_init_sets_and_clears_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init = tmp_path / "init.el"
    init.write_text("", encoding="utf-8")
    cfg = _app_config(emacs_init_paths=[str(init)])
    monkeypatch.setenv("ORG_TIMEVIZ_TODO_KEYWORDS", "OLD")
    configure_emacs_init(cfg, None)
    assert Path(__import__("os").environ["ORG_TIMEVIZ_EMACS_INIT"]) == init
    assert "ORG_TIMEVIZ_TODO_KEYWORDS" not in __import__("os").environ

    empty_cfg = _app_config(emacs_init_paths=[])
    configure_emacs_init(empty_cfg, None)
    assert "ORG_TIMEVIZ_EMACS_INIT" not in __import__("os").environ


def test_emacs_batch_parser_builds_clock_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Task", encoding="utf-8")
    payload = {
        "file": str(org_file),
        "outline_path": ["Project", "Task"],
        "headline": "Task",
        "tags": ["job"],
        "start": "2026-08-11T09:00:00",
        "end": "2026-08-11T10:15:00",
    }
    stdout = "noise\n" + json.dumps(payload) + "\n"

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("org_timeviz.org_source.emacs.subprocess.run", fake_run)
    records = parse_org_clock_records_emacs([org_file])
    assert len(records) == 1
    assert records[0].outline_path == "Project / Task"
    assert records[0].headline == "Task"
    assert records[0].tags == ("job",)


def test_emacs_batch_parser_returns_empty_for_missing_files(tmp_path: Path) -> None:
    assert parse_org_clock_records_emacs([tmp_path / "missing.org"]) == []


def test_emacs_batch_parser_surfaces_process_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text("* Task", encoding="utf-8")
    monkeypatch.setattr(
        "org_timeviz.org_source.emacs.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="bad", stderr="worse"),
    )
    with pytest.raises(RuntimeError, match="Emacs batch parser failed"):
        parse_org_clock_records_emacs([org_file])
