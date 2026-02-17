from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ClockRecord:
    file_path: Path
    outline_path: str
    headline: str
    tags: tuple[str, ...]
    start: datetime
    end: datetime
