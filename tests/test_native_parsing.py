"""Synthetic characterization cases shared by the native Org migration."""

from datetime import date
from pathlib import Path

from conftest import write_dashboard_init

from org_timeviz.org_source.clock_dashboard import render_clock_dashboard
from org_timeviz.org_source.emacs import parse_org_clock_records_emacs
from test_clock_dashboard import _app_config


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
    report = render_clock_dashboard(
        _app_config(tmp_path / "output", [init], [org]),
        day=date(2026, 8, 5),
        day_total_day=date(2026, 8, 5),
        week_start=date(2026, 8, 3),
    )
    assert (report.day_total, report.week_total) == ("1:30", "2:00")
    assert "Task [6/16] [notes]" in report.chronological
    assert {report.overlaps[0].a.line, report.overlaps[0].b.line} == {7, 8}
    assert report.overlaps[0].a.org_id == "stable-id"
    assert org.read_bytes() == before
