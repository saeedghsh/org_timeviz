"""Synthetic regression cases for native Org and configuration interpretation."""

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from conftest import write_dashboard_init
from test_clock_dashboard import _app_config

from org_timeviz.org_source.agenda import read_agenda_files_from_emacs_init
from org_timeviz.org_source.clock_dashboard import ClockDashboard, render_clock_dashboard
from org_timeviz.org_source.emacs import parse_org_clock_records_emacs

pytestmark = pytest.mark.skipif(shutil.which("emacs") is None, reason="Emacs is not installed")


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORG_TIMEVIZ_TODO_KEYWORDS", raising=False)
    monkeypatch.delenv("ORG_TIMEVIZ_EMACS_INIT", raising=False)


def _dashboard(tmp_path: Path, org: Path, init: Path | None = None) -> ClockDashboard:
    return render_clock_dashboard(
        _app_config(tmp_path / "output", [init] if init else [], [org]),
        day=date(2026, 8, 5),
        day_total_day=date(2026, 8, 5),
        week_start=date(2026, 8, 3),
    )


def test_clock_baseline(tmp_path: Path) -> None:
    org = tmp_path / "clocks.org"
    org.write_text(
        "* Parent :inherited:\n** Task [6/16] [notes] :local:\n"
        ":PROPERTIES:\n:ID: stable-id\n:END:\n:LOGBOOK:\n"
        "CLOCK: [2026-08-04 Tue 23:30]--[2026-08-05 Wed 00:30] => 1:00\n"
        "CLOCK: [2026-08-05 Wed 00:00]--[2026-08-05 Wed 01:00] => 1:00\n"
        ":END:\n",
        encoding="utf-8",
    )
    before = org.read_bytes()
    records = parse_org_clock_records_emacs([org])
    assert len(records) == 2
    assert sum((r.end - r.start).total_seconds() for r in records) == 7200
    assert records[0].headline == "Task [6/16] [notes]"
    assert records[0].tags == ("inherited", "local")
    init = tmp_path / "init.el"
    write_dashboard_init(init, [org])
    report = _dashboard(tmp_path, org, init)
    # Captured from the original exporter with the real helper definitions,
    # evaluated only against synthetic files. Its 23:59:59 boundary loses a
    # second at midnight; week totals floor the sum, not each individual day.
    assert (report.day_total, report.week_total) == ("1:30", "1:59")
    assert "Task [6/16] [notes]" in report.chronological
    assert {report.overlaps[0].a.line, report.overlaps[0].b.line} == {7, 8}
    assert report.overlaps[0].a.org_id == "stable-id"
    assert org.read_bytes() == before


@pytest.mark.parametrize(
    ("title", "label"),
    [
        ("Hierarchical forecasting [6/16]", "Hierarchical forecasting [6/16]"),
        ("Brackets [a] [b] & *bold* /italic/", "Brackets [a] [b] & *bold* /italic/"),
        ("Read [[https://example.org][linked [notes]]] [2/3]", "Read linked [notes] [2/3]"),
    ],
)
def test_readable_labels_in_every_dashboard_section(tmp_path: Path, title: str, label: str) -> None:
    org = tmp_path / "labels.org"
    org.write_text(
        f"* {title}\n"
        "CLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00] => 2:00\n"
        "CLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00] => 1:00\n",
        encoding="utf-8",
    )
    report = _dashboard(tmp_path, org)
    assert label in report.suspects
    assert "duration mismatch" in report.suspects
    assert "Possible duplicate clocks" in report.suspects
    assert label in report.chronological
    assert report.overlaps[0].a.task == f"labels.org: {label}"
    assert (report.day_total, report.week_total) == ("2:00", "2:00")


def test_malformed_open_and_durationless_clocks(tmp_path: Path) -> None:
    org = tmp_path / "issues.org"
    org.write_text(
        "* Broken [6/16]\nCLOCK: nonsense\n"
        "CLOCK: [2026-08-05 Wed 09:00] [2026-08-05 Wed 10:00]\n"
        "* Closed without a duration\n"
        "CLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00]\n"
        "* Live\n:PROPERTIES:\n:ID: live-id\n:END:\n"
        # Far in the past so this test doesn't depend on today's date.
        "CLOCK: [2000-01-01 Sat 09:00]\n",
        encoding="utf-8",
    )
    before = org.read_bytes()
    records = parse_org_clock_records_emacs([org])
    assert len(records) == 1
    assert records[0].headline == "Closed without a duration"
    report = _dashboard(tmp_path, org)
    assert "Malformed CLOCK" in report.suspects
    assert "Line 2" in report.suspects
    assert "Line 3" in report.suspects
    assert "Broken [6/16]" in report.suspects
    assert "single timestamp (open clock)" in report.suspects
    # Open clocks count in live dashboard totals, but never in static reports.
    assert report.day_total == "24:59"
    assert report.week_total == "168:59"
    overlap = report.overlaps[0]
    live = next(c for c in (overlap.a, overlap.b) if c.org_id == "live-id")
    assert (live.start, live.end, live.line) == ("2000-01-01T09:00", None, 10)
    assert org.read_bytes() == before


def test_duration_mismatch_retains_one_minute_tolerance(tmp_path: Path) -> None:
    org = tmp_path / "tolerance.org"
    org.write_text(
        "* Task\nCLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00] => 1:01\n",
        encoding="utf-8",
    )
    assert _dashboard(tmp_path, org).suspects == "All CLOCK lines look standard."


def test_computed_config_and_work_personal_selection(tmp_path: Path) -> None:
    init = tmp_path / "init.el"
    work = tmp_path / "work.org"
    personal = tmp_path / "personal.org"
    init.write_text(
        f"(let ((root {json.dumps(str(tmp_path))}))\n"
        "  (setq work-files (mapcar (lambda (name) (expand-file-name name root))\n"
        '                           \'("work.org")))\n'
        '  (setq personal-files (list (expand-file-name "personal.org" root))))\n'
        "(setq org-agenda-files (append work-files personal-files))\n"
        '(setq org-todo-keywords \'((sequence "BACKLOG(b)" "|" "FINISHED(f)")))\n',
        encoding="utf-8",
    )
    result = read_agenda_files_from_emacs_init(init, "org-agenda-files")
    assert result is not None
    assert result.files == [work, personal]
    assert result.todo_keywords == ["BACKLOG", "FINISHED"]
    result = read_agenda_files_from_emacs_init(init, "work-files")
    assert result is not None
    assert result.files == [work]
    result = read_agenda_files_from_emacs_init(init, "personal-files")
    assert result is not None
    assert result.files == [personal]


def test_init_loading_org_module_and_reader_isolation(tmp_path: Path) -> None:
    lisp = tmp_path / ".emacs.d" / "lisp"
    lisp.mkdir(parents=True)
    org = tmp_path / "task.org"
    org.write_text(
        "* BACKLOG Task\nCLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00] => 1:00\n"
        '# Local Variables:\n# eval: (error "Must never run local eval")\n# End:\n',
        encoding="utf-8",
    )
    module = lisp / "init-org.el"
    module.write_text(
        f"(setq org-agenda-files (list {json.dumps(str(org))}))\n"
        '(setq org-todo-keywords \'((sequence "BACKLOG" "|" "FINISHED")))\n'
        '(add-hook \'org-mode-hook (lambda () (error "Must not run Org hooks")))\n'
        "(provide 'init-org)\n",
        encoding="utf-8",
    )
    init = tmp_path / ".emacs"
    init.write_text(
        f"(add-to-list 'load-path {json.dumps(str(lisp))})\n(require 'init-org)\n",
        encoding="utf-8",
    )
    before = org.read_bytes()
    report = _dashboard(tmp_path, org, init)
    assert "BACKLOG" not in report.chronological
    assert "Task" in report.chronological
    assert org.read_bytes() == before


@pytest.mark.parametrize("text", ["(setq broken", '(error "Invalid configuration")'])
def test_invalid_config_is_not_silently_ignored(tmp_path: Path, text: str) -> None:
    init = tmp_path / "init.el"
    init.write_text(text, encoding="utf-8")
    with pytest.raises(RuntimeError, match="configuration discovery failed"):
        read_agenda_files_from_emacs_init(init, "org-agenda-files")
