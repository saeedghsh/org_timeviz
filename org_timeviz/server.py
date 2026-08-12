"""Serve generated reports locally and refresh them from the browser."""

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, timedelta
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

from .config import AppConfig
from .logging_utils import setup_logger
from .org_source.clock_dashboard import render_clock_dashboard
from .reports import generate_all_reports

_LOG = logging.getLogger(__name__)
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
REFRESH_PATH = "/refresh"
CLOCK_DASHBOARD_PATH = "/clock-dashboard"
REFRESH_HEADER = "X-Org-Timeviz-Refresh"
_REFRESH_LOCK = Lock()


class ReportRequestHandler(SimpleHTTPRequestHandler):
    """Serve report artifacts and expose a local-only refresh endpoint."""

    config: ClassVar[AppConfig]

    def end_headers(self) -> None:
        """Disable browser caching so regenerated artifacts are fetched immediately."""
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        """Serve static files or live clock-dashboard JSON."""
        parsed = urlsplit(self.path)
        if parsed.path == CLOCK_DASHBOARD_PATH:
            self._write_clock_dashboard(parse_qs(parsed.query))
            return
        super().do_GET()

    def _write_clock_dashboard(self, query: dict[str, list[str]]) -> None:
        """Render one live clock-dashboard response."""
        try:
            today = date.today()
            day = date.fromisoformat(query.get("date", [today.isoformat()])[0])
            day_total_day = date.fromisoformat(
                query.get("day_total_date", [today.isoformat()])[0]
            )
            week_anchor = date.fromisoformat(query.get("week_date", [today.isoformat()])[0])
            week_start = week_anchor - timedelta(days=week_anchor.weekday())
            payload = asdict(
                render_clock_dashboard(
                    self.config,
                    day=day,
                    day_total_day=day_total_day,
                    week_start=week_start,
                )
            )
        except (ValueError, IndexError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid dashboard date or week.")
            return
        except Exception:
            _LOG.exception("Clock dashboard generation failed")
            self.send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Clock dashboard generation failed; see the server log.",
            )
            return

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        """Regenerate reports when the index refresh control is used."""
        if self.path != REFRESH_PATH:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if self.headers.get(REFRESH_HEADER) != "1":
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        if not _REFRESH_LOCK.acquire(blocking=False):
            self.send_error(HTTPStatus.CONFLICT, "A report refresh is already running.")
            return

        try:
            generate_all_reports(self.config)
        except Exception:
            _LOG.exception("Report refresh failed")
            self.send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Report refresh failed; see the server log.",
            )
            return
        finally:
            _REFRESH_LOCK.release()

        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m org_timeviz.server",
        description="Generate and serve org-timeviz reports with browser refresh support.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/default.yaml"),
        help="Path to YAML config file.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local HTTP port (default: {DEFAULT_PORT}).",
    )
    return parser.parse_args(argv)


def _build_server(cfg: AppConfig, output_dir: Path, port: int) -> ThreadingHTTPServer:
    """Build a localhost-only HTTP server rooted at the report output directory."""
    ReportRequestHandler.config = cfg
    handler = partial(ReportRequestHandler, directory=str(output_dir))
    return ThreadingHTTPServer((LOCAL_HOST, port), handler)


def serve_reports(cfg: AppConfig, port: int = DEFAULT_PORT) -> None:
    """Generate current reports, then serve them until interrupted."""
    generate_all_reports(cfg)

    output_dir = Path(cfg.app.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with _build_server(cfg, output_dir, port) as server:
        actual_port = server.server_address[1]
        _LOG.info("Serving reports at http://%s:%s/", LOCAL_HOST, actual_port)
        _LOG.info("Press Ctrl-C to stop the report server")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            _LOG.info("Stopping report server")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the local report server and return a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    config_path = args.config.expanduser().resolve()
    cfg = AppConfig.from_yaml(config_path)

    setup_logger(level=cfg.app.log_level)
    _LOG.info("Loaded config from %s", config_path)

    serve_reports(cfg, port=args.port)
    return os.EX_OK


if __name__ == "__main__":
    sys.exit(main())
