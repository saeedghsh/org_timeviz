"""Ask Emacs to evaluate explicitly configured, trusted agenda configuration."""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)
_PREFIX = "ORG_TIMEVIZ_AGENDA_JSON:"


@dataclass(frozen=True)
class EmacsAgendaFilesResult:
    """Hold effective agenda paths and TODO keywords from a trusted init file."""

    files: list[Path]
    source_path: Path
    todo_keywords: list[str]


def read_agenda_files_from_emacs_init(
    init_path: Path, var_name: str
) -> EmacsAgendaFilesResult | None:
    """Evaluate one trusted init in an isolated batch process, not a Lisp parser.

    Configuration is executable code and can have side effects. Only explicitly
    configured files are loaded; no normal Emacs startup occurs. Errors and
    timeouts are reported, never disguised as empty agenda lists.
    """
    if not init_path.is_file():
        return None
    script = Path(__file__).parent / "elisp" / "agenda_export.el"
    command = ["emacs", "--batch", "-Q", "--load", str(script), "--", str(init_path), var_name]
    result = subprocess.run(
        command, check=False, capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    if result.returncode:
        raise RuntimeError(
            f"Emacs configuration discovery failed for {init_path}:\n{result.stderr}"
        )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(_PREFIX):
            payload = json.loads(line.removeprefix(_PREFIX))
            files = [Path(path).expanduser() for path in payload["files"]]
            _LOG.info("Read %s agenda file(s) from %s", len(files), init_path)
            return EmacsAgendaFilesResult(files, init_path, payload["todo_keywords"])
    raise RuntimeError(f"Emacs configuration discovery emitted no payload for {init_path}")
