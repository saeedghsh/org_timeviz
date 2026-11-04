from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from org_timeviz.config import AppConfig
from org_timeviz.overlap_approvals import APPROVALS_FILE_ENV_VAR, OverlapApprovals
from org_timeviz.rendering.index import write_index_html
from org_timeviz.server import (
    _REFRESH_LOCK,
    REFRESH_HEADER,
    _build_server,
    _parse_args,
    main,
    serve_reports,
)


def _app_config(output_dir: Path, overlap_approvals_file: str | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": {
                "output_dir": str(output_dir),
                "log_level": "INFO",
                "overlap_approvals_file": overlap_approvals_file,
            },
            "org_sources": {"mode": "explicit", "explicit_files": []},
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


def _start_server(cfg: AppConfig, output_dir: Path) -> tuple[ThreadingHTTPServer, Thread, str]:
    server = _build_server(cfg, output_dir, port=0, overlap_approvals=OverlapApprovals(None))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop_server(server: ThreadingHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_generated_index_contains_clock_dashboard_refresh(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True)

    index_path = write_index_html(output_dir, assets_dir)
    text = index_path.read_text(encoding="utf-8")

    assert 'id="refresh-clock-dashboard"' in text
    assert ">Refresh<" in text
    assert "fetch(`/clock-dashboard" in text
    assert "Clock dashboard requires make serve." in text
    assert 'id="refresh-reports"' not in text


def test_generated_visualizations_page_contains_refresh_controls(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    assets_dir = output_dir / "assets"
    assets_dir.mkdir(parents=True)

    write_index_html(output_dir, assets_dir)
    text = (output_dir / "visualizations.html").read_text(encoding="utf-8")

    assert 'id="refresh-reports"' in text
    assert ">Refresh<" in text
    assert 'fetch("/refresh"' in text
    assert '"X-Org-Timeviz-Refresh": "1"' in text
    assert "Refresh requires make serve." in text


def test_parse_args_supports_config_and_port() -> None:
    args = _parse_args(["--config", "custom.yaml", "--port", "8123"])
    assert args.config == Path("custom.yaml")
    assert args.port == 8123


def test_server_serves_output_without_cache(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "index.html").write_text("fresh index", encoding="utf-8")
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)

    try:
        with urlopen(f"{base_url}/") as response:
            assert response.read().decode("utf-8") == "fresh index"
            assert response.headers["Cache-Control"] == "no-store"
    finally:
        _stop_server(server, thread)


def test_refresh_endpoint_regenerates_reports(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    request = Request(
        f"{base_url}/refresh",
        method="POST",
        headers={REFRESH_HEADER: "1"},
    )

    try:
        with patch("org_timeviz.server.generate_all_reports") as generate:
            with urlopen(request) as response:
                assert response.status == 204
            generate.assert_called_once_with(cfg)
    finally:
        _stop_server(server, thread)


def test_refresh_endpoint_rejects_unknown_post_path(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    request = Request(
        f"{base_url}/not-refresh",
        method="POST",
        headers={REFRESH_HEADER: "1"},
    )

    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 404
    finally:
        _stop_server(server, thread)


def test_refresh_endpoint_rejects_requests_without_refresh_header(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    request = Request(f"{base_url}/refresh", method="POST")

    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
    finally:
        _stop_server(server, thread)


def test_refresh_endpoint_rejects_concurrent_refresh(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    request = Request(
        f"{base_url}/refresh",
        method="POST",
        headers={REFRESH_HEADER: "1"},
    )

    _REFRESH_LOCK.acquire()
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 409
    finally:
        _REFRESH_LOCK.release()
        _stop_server(server, thread)


def test_refresh_endpoint_reports_generation_failure(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    cfg = _app_config(output_dir)
    server, thread, base_url = _start_server(cfg, output_dir)
    request = Request(
        f"{base_url}/refresh",
        method="POST",
        headers={REFRESH_HEADER: "1"},
    )

    try:
        with (
            patch(
                "org_timeviz.server.generate_all_reports",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(HTTPError) as error,
        ):
            urlopen(request)
        assert error.value.code == 500
    finally:
        _stop_server(server, thread)


def _serve_reports_until_interrupted(cfg: AppConfig) -> tuple[MagicMock, MagicMock]:
    """Run `serve_reports` against a fake server; return the report and server mocks."""
    fake_server = MagicMock()
    fake_server.__enter__.return_value = fake_server
    fake_server.__exit__.return_value = False
    fake_server.server_address = ("127.0.0.1", 8000)
    fake_server.serve_forever.side_effect = KeyboardInterrupt

    with (
        patch("org_timeviz.server.generate_all_reports") as generate,
        patch("org_timeviz.server._build_server", return_value=fake_server) as build_server,
    ):
        serve_reports(cfg, port=8000)
    return generate, build_server


def test_serve_reports_generates_before_serving(tmp_path: Path) -> None:
    cfg = _app_config(tmp_path / "outputs")

    generate, build_server = _serve_reports_until_interrupted(cfg)

    generate.assert_called_once_with(cfg)
    build_server.assert_called_once()
    assert build_server.call_args.args[:3] == (cfg, (tmp_path / "outputs").resolve(), 8000)


@pytest.mark.parametrize(
    ("environment_file", "configured_file", "expected"),
    [
        (None, "~/orgs/timeviz/approved_overlaps.json", "orgs/timeviz/approved_overlaps.json"),
        ("~/override.json", "~/orgs/timeviz/approved_overlaps.json", "override.json"),
        (None, None, None),
    ],
)
def test_serve_reports_configures_overlap_approvals_from_yaml_or_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_file: str | None,
    configured_file: str | None,
    expected: str | None,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    if environment_file is None:
        monkeypatch.delenv(APPROVALS_FILE_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(APPROVALS_FILE_ENV_VAR, environment_file)
    cfg = _app_config(tmp_path / "outputs", overlap_approvals_file=configured_file)

    _, build_server = _serve_reports_until_interrupted(cfg)

    approvals = build_server.call_args.args[3]
    assert approvals.store_path == (None if expected is None else tmp_path / expected)
    assert (approvals.disabled_message is None) == (expected is not None)


def test_main_loads_config_and_starts_server(tmp_path: Path) -> None:
    cfg = _app_config(tmp_path / "outputs")
    config_path = tmp_path / "config.yaml"

    with (
        patch("org_timeviz.server.AppConfig.from_yaml", return_value=cfg) as from_yaml,
        patch("org_timeviz.server.setup_logger") as setup_logger,
        patch("org_timeviz.server.serve_reports") as serve,
    ):
        result = main(["--config", str(config_path), "--port", "9000"])

    assert result == 0
    from_yaml.assert_called_once_with(config_path.resolve())
    setup_logger.assert_called_once_with(level="INFO")
    serve.assert_called_once_with(cfg, port=9000)
