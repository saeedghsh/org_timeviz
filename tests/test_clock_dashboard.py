import json
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from subprocess import CompletedProcess
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from org_timeviz.config import AppConfig
from org_timeviz.org_source.clock_dashboard import (
    DASHBOARD_JSON_PREFIX,
    ClockDashboard,
    _extract_dashboard_payload,
    render_clock_dashboard,
)
from org_timeviz.rendering.index import write_index_html
from org_timeviz.server import _build_server


def _app_config(output_dir: Path, init_paths: list[Path] | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": {"output_dir": str(output_dir), "log_level": "INFO"},
            "org_sources": {
                "mode": "explicit",
                "explicit_files": [],
                "emacs_init_paths": [str(path) for path in (init_paths or [])],
            },
            "time_buckets": {
                "other_bucket": "other",
                "bucket_order": ["other"],
                "tag_to_bucket": {},
                "resolution": {
                    "default_strategy": "priority",
                    "priority_order": ["other"],
                    "weights": {},
                    "rules": [],
                },
            },
        }
    )


def _write_dashboard_init(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "(defun my/org-clock-suspects (files) nil)",
                "(defun my/org--collect-ts-pos (text) nil)",
                "(defun my/org--ts->sec (timestamp) 0)",
                "(defun my/org-clocklog-rows (&optional date files) nil)",
                "(defun my/org-clocklog--fmt-hhmm (seconds) \"00:00\")",
                "(defun my/org-clocklog--fmt-dur (minutes) \"0:00\")",
            ]
        ),
        encoding="utf-8",
    )


def _start_server(cfg: AppConfig, output_dir: Path) -> tuple[ThreadingHTTPServer, Thread, str]:
    server = _build_server(cfg, output_dir, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop_server(server: ThreadingHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_render_clock_dashboard_uses_configured_init_and_marked_json(tmp_path: Path) -> None:
    init_path = tmp_path / "init-org.el"
    _write_dashboard_init(init_path)
    cfg = _app_config(tmp_path / "outputs", [init_path])
    payload = {
        "suspects": "No suspects",
        "chronological": "09:00 Task",
        "day_total": "1:30",
        "week_total": "8:15",
    }
    stdout = f"ordinary Emacs message\n{DASHBOARD_JSON_PREFIX}{json.dumps(payload)}\n"

    with patch(
        "org_timeviz.org_source.clock_dashboard.subprocess.run",
        return_value=CompletedProcess([], 0, stdout=stdout, stderr=""),
    ) as run:
        report = render_clock_dashboard(
            cfg,
            day=date(2026, 8, 5),
            day_total_day=date(2026, 8, 6),
            week_start=date(2026, 8, 3),
        )

    command = run.call_args.args[0]
    assert command[:3] == ["emacs", "--batch", "-Q"]
    assert command[4] == str(init_path.resolve())
    assert command[-3:] == ["2026-08-05", "2026-08-06", "2026-08-03"]
    assert report == ClockDashboard(
        day="2026-08-05",
        day_total_day="2026-08-06",
        week_start="2026-08-03",
        week_end="2026-08-09",
        suspects="No suspects",
        chronological="09:00 Task",
        day_total="1:30",
        week_total="8:15",
    )


def test_render_clock_dashboard_requires_custom_helpers(tmp_path: Path) -> None:
    init_path = tmp_path / "init-org.el"
    init_path.write_text("(require 'org)\n", encoding="utf-8")
    cfg = _app_config(tmp_path / "outputs", [init_path])

    with pytest.raises(FileNotFoundError, match="clock dashboard helpers"):
        render_clock_dashboard(
            cfg,
            day=date(2026, 8, 5),
            day_total_day=date(2026, 8, 6),
            week_start=date(2026, 8, 3),
        )


def test_render_clock_dashboard_reports_emacs_failure(tmp_path: Path) -> None:
    init_path = tmp_path / "init-org.el"
    _write_dashboard_init(init_path)
    cfg = _app_config(tmp_path / "outputs", [init_path])

    with patch(
        "org_timeviz.org_source.clock_dashboard.subprocess.run",
        return_value=CompletedProcess([], 2, stdout="some stdout", stderr="some stderr"),
    ):
        with pytest.raises(RuntimeError, match="Emacs clock dashboard failed"):
            render_clock_dashboard(
                cfg,
                day=date(2026, 8, 5),
                day_total_day=date(2026, 8, 5),
                week_start=date(2026, 8, 3),
            )


def test_dashboard_payload_requires_marker() -> None:
    with pytest.raises(RuntimeError, match="did not emit"):
        _extract_dashboard_payload("ordinary output only")


def test_clock_dashboard_endpoint_resolves_selected_date_to_week(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    expected = ClockDashboard(
        day="2026-08-05",
        day_total_day="2026-08-06",
        week_start="2026-08-03",
        week_end="2026-08-09",
        suspects="suspects",
        chronological="entries",
        day_total="2:00",
        week_total="10:00",
    )

    try:
        with patch("org_timeviz.server.render_clock_dashboard", return_value=expected) as render:
            with urlopen(
                f"{base_url}/clock-dashboard?date=2026-08-05"
                "&day_total_date=2026-08-06&week_date=2026-08-05"
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert payload["week_start"] == "2026-08-03"
        render.assert_called_once()
        assert render.call_args.kwargs["day"].isoformat() == "2026-08-05"
        assert render.call_args.kwargs["day_total_day"].isoformat() == "2026-08-06"
        assert render.call_args.kwargs["week_start"].isoformat() == "2026-08-03"
    finally:
        _stop_server(server, thread)


def test_clock_dashboard_endpoint_rejects_invalid_date(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)

    try:
        with pytest.raises(HTTPError) as error:
            urlopen(
                f"{base_url}/clock-dashboard?date=bad-date"
                "&day_total_date=2026-08-05&week_date=2026-08-05"
            )
        assert error.value.code == 400
    finally:
        _stop_server(server, thread)


def test_clock_dashboard_endpoint_reports_export_failure(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)

    try:
        with patch("org_timeviz.server.render_clock_dashboard", side_effect=RuntimeError("boom")):
            with pytest.raises(HTTPError) as error:
                urlopen(
                    f"{base_url}/clock-dashboard?date=2026-08-05"
                    "&day_total_date=2026-08-06&week_date=2026-08-05"
                )
        assert error.value.code == 500
    finally:
        _stop_server(server, thread)


def test_generated_index_contains_live_clock_dashboard(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True)

    index_path = write_index_html(output_dir, assets_dir)
    text = index_path.read_text(encoding="utf-8")

    assert "Suspicious clocks" in text
    assert "Chronological entries" in text
    assert "Total time logged — day" in text
    assert "Total time logged — week" in text
    assert 'id="clock-day" type="date"' in text
    assert 'id="clock-day-total-date" type="date"' in text
    assert 'id="clock-week-date" type="date"' in text
    assert 'id="refresh-clock-dashboard"' in text
    assert "day_total_date: dayTotalDateInput.value" in text
    assert "/clock-dashboard?" in text
    assert "Clock dashboard requires make serve." in text
