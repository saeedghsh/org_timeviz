"""Define lightweight in-memory data models for clock records."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ClockRecord:
    """Represent one raw clock interval with task context and tags."""

    file_path: Path
    outline_path: str
    headline: str
    tags: tuple[str, ...]
    start: datetime
    end: datetime
