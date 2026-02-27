"""Read org-agenda-files and Org TODO keywords from an Emacs init file."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmacsAgendaFilesResult:
    """Hold agenda file paths discovered from an Emacs init file."""

    files: list[Path]
    source_path: Path


def read_agenda_files_from_emacs_init(
    init_path: Path, var_name: str
) -> EmacsAgendaFilesResult | None:
    """Extract org-agenda-files from an Emacs init file, if present."""
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


def _find_setq_block(text: str, var_name: str) -> str | None:  # pylint: disable=too-many-branches
    # Find the actual (setq <var_name> ...) form, not just any mention of var_name.
    pattern = re.compile(r"\(\s*setq\s+" + re.escape(var_name) + r"\b", flags=re.MULTILINE)

    m = pattern.search(text)
    if m is None:
        return None

    start_idx = m.start()

    depth = 0
    in_str = False
    esc = False

    i = start_idx
    end_idx: int | None = None

    while i < len(text):
        ch = text[i]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue

        # Elisp line comment outside strings: from ';' to end-of-line
        if ch == ";":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue

        if ch == '"':
            in_str = True
            i += 1
            continue

        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if not depth:
                end_idx = i + 1
                break

        i += 1

    if end_idx is None:
        return None

    return text[start_idx:end_idx]


def _extract_double_quoted_strings(block: str) -> list[str]:
    strings: list[str] = []
    i = 0
    in_str = False
    esc = False
    buf: list[str] = []

    while i < len(block):
        ch = block[i]

        if not in_str and ch == ";":
            # Skip line comments outside strings
            while i < len(block) and block[i] != "\n":
                i += 1
            continue

        if in_str:
            if esc:
                buf.append(ch)
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                strings.append("".join(buf))
                buf = []
                in_str = False
            else:
                buf.append(ch)
            i += 1
            continue

        if ch == '"':
            in_str = True
            i += 1
            continue

        i += 1

    return strings


def read_todo_keywords_from_emacs_init(init_path: Path) -> list[str] | None:
    """Extract Org TODO keywords from an Emacs init file, if present."""
    if not init_path.exists():
        return None

    text = init_path.read_text(encoding="utf-8")

    block = _find_setq_block(text, var_name="org-todo-keywords")
    if block is None:
        return None

    kws = _extract_double_quoted_strings(block)
    if not kws:
        return None

    # Remove separators and de-duplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for k in kws:
        k = k.strip()
        if not k or k == "|":
            continue
        if k not in seen:
            out.append(k)
            seen.add(k)

    return out or None
