"""Render live Org clock dashboard text through the user's Emacs configuration."""

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..config import AppConfig

_LOG = logging.getLogger(__name__)
DASHBOARD_JSON_PREFIX = "ORG_TIMEVIZ_CLOCK_DASHBOARD_JSON:"
_REQUIRED_INIT_MARKERS = (
    "(defun my/org-clock-suspects",
    "(defun my/org--collect-ts-pos",
    "(defun my/org--ts->sec",
    "(defun my/org-clocklog-rows",
    "(defun my/org-clocklog--fmt-hhmm",
    "(defun my/org-clocklog--fmt-dur",
)


@dataclass(frozen=True)
class ClockDashboard:
    """Hold text reports shown above the visualization dashboard."""

    day: str
    day_total_day: str
    week_start: str
    week_end: str
    suspects: str
    chronological: str
    day_total: str
    week_total: str


def render_clock_dashboard(
    cfg: AppConfig,
    *,
    day: date,
    day_total_day: date,
    week_start: date,
) -> ClockDashboard:
    """Run the live clock dashboard exporter and return its text reports."""
    init_path = _find_clock_dashboard_init(cfg)
    script_path = Path(__file__).resolve().parent / "elisp" / "clock_dashboard_export.el"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing clock dashboard exporter: {script_path}")

    cmd = [
        "emacs",
        "--batch",
        "-Q",
        "--load",
        str(init_path),
        "--load",
        str(script_path),
        "--",
        day.isoformat(),
        day_total_day.isoformat(),
        week_start.isoformat(),
    ]
    _LOG.info(
        "Running Emacs clock dashboard for chronological_day=%s day_total_day=%s week=%s",
        day,
        day_total_day,
        week_start,
    )
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(
            "Emacs clock dashboard failed.\n"
            f"cmd: {cmd}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}\n"
        )

    payload = _extract_dashboard_payload(result.stdout)
    week_end = week_start + timedelta(days=6)
    return ClockDashboard(
        day=day.isoformat(),
        day_total_day=day_total_day.isoformat(),
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        suspects=str(payload["suspects"]),
        chronological=str(payload["chronological"]),
        day_total=str(payload["day_total"]),
        week_total=str(payload["week_total"]),
    )


def _find_clock_dashboard_init(cfg: AppConfig) -> Path:
    """Find the configured init file that directly defines the dashboard helpers."""
    checked: list[str] = []
    for path_text in cfg.org_sources.emacs_init_paths:
        path = Path(path_text).expanduser()
        if not path.exists() or not path.is_file():
            continue

        checked.append(str(path))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        if all(marker in text for marker in _REQUIRED_INIT_MARKERS):
            return path.resolve()

    checked_text = ", ".join(checked) if checked else "(no existing configured init files)"
    raise FileNotFoundError(
        "Could not find an Emacs init file defining the org-timeviz clock dashboard helpers "
        f"among: {checked_text}"
    )


def _extract_dashboard_payload(stdout: str) -> dict[str, object]:
    """Extract the marked JSON object while tolerating ordinary Emacs messages."""
    for line in reversed(stdout.splitlines()):
        if line.startswith(DASHBOARD_JSON_PREFIX):
            value = json.loads(line.removeprefix(DASHBOARD_JSON_PREFIX))
            if not isinstance(value, dict):
                break
            return value
    raise RuntimeError("Emacs clock dashboard did not emit its JSON payload.")
