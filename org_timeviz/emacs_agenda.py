import logging
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmacsAgendaFilesResult:
    files: list[Path]
    source_path: Path


def _find_setq_block(text: str, var_name: str) -> str | None:
    needle = var_name
    idx = text.find(needle)
    if idx < 0:
        return None

    setq_idx = text.rfind("(setq", 0, idx)
    if setq_idx < 0:
        return None

    depth = 0
    in_str = False
    esc = False
    end_idx = None

    for i in range(setq_idx, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":  # escape char in elisp strings
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break

    if end_idx is None:
        return None

    return text[setq_idx:end_idx]


def _extract_double_quoted_strings(block: str) -> list[str]:
    strings: list[str] = []
    i = 0
    while i < len(block):
        if block[i] != '"':
            i += 1
            continue
        i += 1
        buf: list[str] = []
        esc = False
        while i < len(block):
            ch = block[i]
            if esc:
                buf.append(ch)
                esc = False
            elif ch == "\\":  # escape char in elisp strings
                esc = True
            elif ch == '"':
                break
            else:
                buf.append(ch)
            i += 1
        strings.append("".join(buf))
        i += 1
    return strings


def read_agenda_files_from_emacs_init(
    init_path: Path, var_name: str
) -> EmacsAgendaFilesResult | None:
    """Read org-agenda-files from an Emacs init file."""
    if not init_path.exists():
        return None

    text = init_path.read_text(encoding="utf-8")

    block = _find_setq_block(text, var_name=var_name)
    if block is None:
        return None

    raw_files = _extract_double_quoted_strings(block)
    files = [Path(s).expanduser() for s in raw_files]

    _LOG.info("Read %s agenda file(s) from %s", len(files), init_path)
    return EmacsAgendaFilesResult(files=files, source_path=init_path)
