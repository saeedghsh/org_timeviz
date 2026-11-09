"""Render live Org clock dashboard text using Org's native parser."""

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from ..config import AppConfig
from .inputs import resolve_org_inputs

_LOG = logging.getLogger(__name__)
DASHBOARD_JSON_PREFIX = "ORG_TIMEVIZ_CLOCK_DASHBOARD_JSON:"


@dataclass(frozen=True)
class OverlapClock:
    """Describe one clock entry that overlaps another.

    `file` and `line` locate the `CLOCK:` line for display only. `org_id` is the
    owning heading's `ID` property, and `start`/`end` are the clock timestamps as
    `YYYY-MM-DDTHH:MM`; `end` is `None` while the clock is open.
    """

    task: str
    interval: str
    file: str
    line: int
    org_id: str | None
    start: str
    end: str | None


@dataclass(frozen=True)
class ClockOverlap:
    """Pair two overlapping clocks, with the shorter task label as `a`."""

    a: OverlapClock
    b: OverlapClock


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
    overlaps: tuple[ClockOverlap, ...]


def render_clock_dashboard(
    cfg: AppConfig,
    *,
    day: date,
    day_total_day: date,
    week_start: date,
) -> ClockDashboard:
    """Run the live clock dashboard exporter and return its text reports."""
    script_path = Path(__file__).resolve().parent / "elisp" / "clock_dashboard_export.el"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing clock dashboard exporter: {script_path}")
    # Scan the same active and archive files as the reports, not `org-agenda-files`.
    org_files = [
        path.expanduser().resolve()
        for path in resolve_org_inputs(cfg).org_files
        if path.expanduser().exists()
    ]

    cmd = [
        "emacs",
        "--batch",
        "-Q",
        "--load",
        str(script_path),
        "--",
        day.isoformat(),
        day_total_day.isoformat(),
        week_start.isoformat(),
        *[str(path) for path in org_files],
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
        overlaps=_parse_overlaps(payload["overlaps"]),
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


def _parse_overlaps(value: object) -> tuple[ClockOverlap, ...]:
    """Convert the exporter's overlap records into typed values."""
    if not isinstance(value, list):
        raise RuntimeError("Emacs clock dashboard emitted malformed overlaps.")
    try:
        return tuple(
            ClockOverlap(a=_parse_overlap_clock(item["a"]), b=_parse_overlap_clock(item["b"]))
            for item in value
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Emacs clock dashboard emitted malformed overlaps.") from error


def _parse_overlap_clock(value: dict[str, object]) -> OverlapClock:
    line = value["line"]
    if not isinstance(line, int):
        raise TypeError("overlap clock line must be an integer")
    return OverlapClock(
        task=str(value["task"]),
        interval=str(value["interval"]),
        file=str(value["file"]),
        line=line,
        org_id=_optional_text(value["org_id"]),
        start=str(value["start"]),
        end=_optional_text(value["end"]),
    )


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)
