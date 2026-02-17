from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_LOG = logging.getLogger(__name__)

_CLOCK_RE = re.compile(r"^\s*CLOCK:\s*\[(?P<start>[^\]]+)\]\s*--\s*\[(?P<end>[^\]]+)\]")
_HEADING_RE = re.compile(r"^(?P<stars>\*+)\s+(?P<body>.+?)\s*$")


@dataclass(frozen=True)
class ClockRecord:
    file_path: Path
    outline_path: str
    headline: str
    tags: tuple[str, ...]
    start: datetime
    end: datetime


def _parse_org_timestamp(ts: str) -> datetime:
    parts = ts.strip().split()
    if not parts:
        raise ValueError(f"Empty timestamp: {ts!r}")

    date_part = parts[0]
    time_part = "00:00"
    if len(parts) >= 3:
        time_part = parts[2]
    elif len(parts) == 2 and ":" in parts[1]:
        time_part = parts[1]

    if len(time_part.split(":")) == 2:
        fmt = "%Y-%m-%d %H:%M"
    else:
        fmt = "%Y-%m-%d %H:%M:%S"

    return datetime.strptime(f"{date_part} {time_part}", fmt)


def _split_heading_and_tags(line: str) -> tuple[str, tuple[str, ...]]:
    stripped = line.rstrip()

    if not stripped.endswith(":"):
        return stripped, ()

    last_space = stripped.rfind(" ")
    if last_space < 0:
        return stripped, ()

    maybe_tags = stripped[last_space + 1 :]
    if not (maybe_tags.startswith(":") and maybe_tags.endswith(":")):
        return stripped, ()

    if " " in maybe_tags or "\t" in maybe_tags:
        return stripped, ()

    tag_tokens = [t for t in maybe_tags.split(":") if t]
    if not tag_tokens:
        return stripped, ()

    title = stripped[:last_space].rstrip()
    return title, tuple(tag_tokens)


@dataclass
class _HeadingFrame:
    level: int
    headline: str
    tags: tuple[str, ...]


def parse_org_clock_records(file_path: Path) -> list[ClockRecord]:
    """Parse CLOCK records from one Org file."""
    text = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

    stack: list[_HeadingFrame] = []
    records: list[ClockRecord] = []

    for raw in text:
        m = _HEADING_RE.match(raw)
        if m:
            level = len(m.group("stars"))
            body = m.group("body")
            headline_with_tags = body.strip()
            headline, tags = _split_heading_and_tags(headline_with_tags)

            while stack and stack[-1].level >= level:
                stack.pop()
            stack.append(_HeadingFrame(level=level, headline=headline, tags=tags))
            continue

        c = _CLOCK_RE.match(raw)
        if not c:
            continue

        if not stack:
            continue

        start = _parse_org_timestamp(c.group("start"))
        end = _parse_org_timestamp(c.group("end"))

        outline = " / ".join([h.headline for h in stack])
        headline = stack[-1].headline

        inherited_tags: list[str] = []
        seen: set[str] = set()
        for h in stack:
            for t in h.tags:
                if t not in seen:
                    inherited_tags.append(t)
                    seen.add(t)

        records.append(
            ClockRecord(
                file_path=file_path,
                outline_path=outline,
                headline=headline,
                tags=tuple(inherited_tags),
                start=start,
                end=end,
            )
        )

    _LOG.info("Parsed %s clock record(s) from %s", len(records), file_path)
    return records
