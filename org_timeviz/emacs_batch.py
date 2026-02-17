import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from org_timeviz.models import ClockRecord

_LOG = logging.getLogger(__name__)


def parse_org_clock_records_emacs(
    org_files: list[Path],
    emacs_executable: str,
) -> list[ClockRecord]:
    """Parse CLOCK records by calling Emacs in batch mode."""
    script_path = Path(__file__).resolve().parent / "elisp" / "org_timeviz_export.el"
    if not script_path.exists():
        raise FileNotFoundError(f"Missing elisp exporter: {script_path}")

    files = [p.expanduser().resolve() for p in org_files if p.expanduser().exists()]
    if not files:
        return []

    cmd = [
        emacs_executable,
        "--batch",
        "-Q",
        "--load",
        str(script_path),
        "--",
        *[str(p) for p in files],
    ]

    _LOG.info("Running Emacs batch parser on %s file(s)", len(files))
    res = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if res.returncode != 0:
        raise RuntimeError(
            "Emacs batch parser failed.\n"
            f"cmd: {cmd}\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}\n"
        )

    records: list[ClockRecord] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{"):
            # Be tolerant of any stray output.
            _LOG.debug("Skipping non-JSON line from Emacs: %r", line[:200])
            continue

        obj = json.loads(line)

        start = datetime.fromisoformat(obj["start"])
        end = datetime.fromisoformat(obj["end"])
        outline_path_list = obj.get("outline_path") or []
        outline_path = (
            " / ".join(outline_path_list)
            if outline_path_list
            else obj.get("headline", "(no-headline)")
        )
        headline = obj.get("headline") or (
            outline_path_list[-1] if outline_path_list else "(no-headline)"
        )
        tags = tuple(obj.get("tags") or [])

        records.append(
            ClockRecord(
                file_path=Path(obj["file"]),
                outline_path=outline_path,
                headline=headline,
                tags=tags,
                start=start,
                end=end,
            )
        )

    _LOG.info("Emacs parsed %s clock record(s)", len(records))
    return records
