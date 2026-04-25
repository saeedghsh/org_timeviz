"""Report Org headings with invalid time-bucket tags."""

import csv
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from org_timeviz.emacs_agenda import (
    read_agenda_files_from_emacs_init,
    read_todo_keywords_from_emacs_init,
)
from org_timeviz.logging_utils import setup_logger

_LOG = logging.getLogger(__name__)


TIME_BUCKET_TAGS: tuple[str, ...] = (
    # PROJECTS
    # "keeper",
    "pride",
    "alfa_laval",
    "aim_flix",
    # msc
    "msc",
    # MISC
    # "hh",
    # "ite",
    # "isdd",
    # "admin",
    "tooling",
    "ml_tooling_tutorial",
    # "unbinned",
    # TIME-OFF
    "holidays",
    "vacations",
)

EMACS_INIT_FILE = Path("~/.emacs").expanduser()
ORG_SETTINGS_FILE = Path("~/.emacs.d/lisp/init-org.el").expanduser()
AGENDA_VAR = "org-agenda-files"
EMACS_EXECUTABLE = "emacs"
OUTPUT_DIR = Path("outputs")
OUTPUT_FILE = OUTPUT_DIR / "time_bucket_violations.csv"
LOG_LEVEL = "INFO"
EMACS_TIMEOUT_SECONDS = 60

ELISP_EXPORTER = r"""
(require 'org)
(require 'json)

(setq org-use-tag-inheritance t)

(defun time-bucket-check--maybe-configure-todo-keywords ()
  "Configure org-todo-keywords from JSON in the environment."
  (let ((override (getenv "ORG_TIME_BUCKET_TODO_KEYWORDS")))
    (when (and override (> (length override) 0))
      (let* ((json-array-type 'list)
             (json-object-type 'alist)
             (kws (json-read-from-string override)))
        (when (and (listp kws) kws)
          (setq org-todo-keywords (list (cons 'sequence kws)))
          (org-set-regexps-and-options))))))

(defun time-bucket-check--outline-path ()
  "Return outline path as a list of headings from top to current."
  (save-excursion
    (org-back-to-heading t)
    (let ((parts (list (org-get-heading t t t t))))
      (while (org-up-heading-safe)
        (push (org-get-heading t t t t) parts))
      parts)))

(defun time-bucket-check--emit-jsonl (obj)
  "Emit OBJ as one JSON line."
  (princ (json-encode obj))
  (princ "\n"))

(defun time-bucket-check--export-file (file)
  "Export headings from FILE as JSONL."
  (with-temp-buffer
    (insert-file-contents file)
    (setq buffer-file-name file)
    (org-mode)
    (goto-char (point-min))
    (org-map-entries
     (lambda ()
       (let ((path (time-bucket-check--outline-path)))
         (time-bucket-check--emit-jsonl
          `((file . ,(expand-file-name file))
            (line . ,(line-number-at-pos))
            (headline . ,(org-get-heading t t t t))
            (outline_path . ,path)
            (todo . ,(org-get-todo-state))
            (tags . ,(org-get-tags))))))
     t
     'file)))

(defun time-bucket-check-main ()
  "Main batch entry point."
  (time-bucket-check--maybe-configure-todo-keywords)
  (dolist (f command-line-args-left)
    (when (and f (file-exists-p f))
      (time-bucket-check--export-file f))))

(when noninteractive
  (time-bucket-check-main))
"""


@dataclass(frozen=True)
class HeadingRecord:
    """Represent one Org heading with inherited tags."""

    file_path: Path
    line_number: int
    headline: str
    outline_path: str
    todo_state: str | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class Violation:
    """Represent one heading with an invalid time-bucket assignment."""

    heading: HeadingRecord
    matched_buckets: tuple[str, ...]
    reason: str


def _resolve_org_settings_file() -> Path:
    """Return the file that actually contains Org settings."""
    if not EMACS_INIT_FILE.exists():
        raise FileNotFoundError(f"Missing init file: {EMACS_INIT_FILE}")

    init_text = EMACS_INIT_FILE.read_text(encoding="utf-8")

    if "(require 'init-org)" in init_text and ORG_SETTINGS_FILE.exists():
        return ORG_SETTINGS_FILE

    return EMACS_INIT_FILE


def _resolve_org_files() -> list[Path]:
    """Resolve Org agenda files from the Org settings file."""
    settings_file = _resolve_org_settings_file()
    result = read_agenda_files_from_emacs_init(
        settings_file,
        var_name=AGENDA_VAR,
    )

    if result is None or not result.files:
        raise FileNotFoundError(f"Could not read {AGENDA_VAR!r} from {settings_file}")

    files = [path.expanduser().resolve() for path in result.files]
    existing = [path for path in files if path.exists()]

    if not existing:
        raise FileNotFoundError("Resolved org-agenda-files, but none exist on disk.")

    _LOG.info("Resolved %s Org agenda file(s): %s", len(existing), existing)
    return existing


def _read_todo_keywords() -> list[str]:
    """Read Org TODO keywords from the Org settings file when present."""
    settings_file = _resolve_org_settings_file()
    keywords = read_todo_keywords_from_emacs_init(settings_file)
    return keywords or []


def _run_emacs_export_for_file(org_file: Path) -> list[HeadingRecord]:
    """Run Emacs batch export for one Org file."""
    env = os.environ.copy()

    todo_keywords = _read_todo_keywords()
    if todo_keywords:
        env["ORG_TIME_BUCKET_TODO_KEYWORDS"] = json.dumps(todo_keywords)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".el",
        delete=False,
    ) as handle:
        handle.write(ELISP_EXPORTER)
        script_path = Path(handle.name)

    try:
        cmd = [
            EMACS_EXECUTABLE,
            "--batch",
            "-Q",
            "--load",
            str(script_path),
            "--",
            str(org_file),
        ]

        _LOG.info("Running Emacs batch export on file: %s", org_file)

        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=EMACS_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Emacs batch export failed.\n"
                f"file: {org_file}\n"
                f"cmd: {cmd}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}\n"
            )

        headings: list[HeadingRecord] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped or not stripped.startswith("{"):
                continue

            obj = json.loads(stripped)
            outline_path_list = obj.get("outline_path") or []
            outline_path = " / ".join(outline_path_list)

            headings.append(
                HeadingRecord(
                    file_path=Path(obj["file"]),
                    line_number=int(obj["line"]),
                    headline=str(obj["headline"]),
                    outline_path=outline_path,
                    todo_state=obj.get("todo"),
                    tags=tuple(obj.get("tags") or []),
                )
            )

        _LOG.info("Parsed %s heading(s) from %s", len(headings), org_file)
        return headings

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Emacs batch export timed out after {exc.timeout}s for file: {org_file}"
        ) from exc
    finally:
        script_path.unlink(missing_ok=True)


def _run_emacs_export(org_files: list[Path]) -> list[HeadingRecord]:
    """Run Emacs batch export across Org files, one file at a time."""
    all_headings: list[HeadingRecord] = []

    for org_file in org_files:
        headings = _run_emacs_export_for_file(org_file)
        all_headings.extend(headings)

    _LOG.info("Parsed %s heading(s) in total", len(all_headings))
    return all_headings


def _find_violations(headings: list[HeadingRecord]) -> list[Violation]:
    """Find headings with zero or multiple matching time-bucket tags."""
    bucket_set = set(TIME_BUCKET_TAGS)
    violations: list[Violation] = []

    for heading in headings:
        matched_buckets = tuple(sorted(tag for tag in heading.tags if tag in bucket_set))
        if len(matched_buckets) == 1:
            continue

        reason = "missing" if not matched_buckets else "multiple"
        violations.append(
            Violation(
                heading=heading,
                matched_buckets=matched_buckets,
                reason=reason,
            )
        )

    violations.sort(key=lambda item: (str(item.heading.file_path), item.heading.line_number))
    return violations


def _write_csv(violations: list[Violation]) -> None:
    """Write violations to a CSV file under outputs/."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reason",
                "file",
                "line",
                "todo",
                "headline",
                "outline_path",
                "matched_buckets",
                "all_tags",
            ],
        )
        writer.writeheader()

        for item in violations:
            writer.writerow(
                {
                    "reason": item.reason,
                    "file": str(item.heading.file_path),
                    "line": item.heading.line_number,
                    "todo": item.heading.todo_state or "",
                    "headline": item.heading.headline,
                    "outline_path": item.heading.outline_path,
                    "matched_buckets": ";".join(item.matched_buckets),
                    "all_tags": ";".join(item.heading.tags),
                }
            )


def _main() -> int:
    """Run the report."""
    setup_logger(LOG_LEVEL)

    org_files = _resolve_org_files()
    headings = _run_emacs_export(org_files)
    violations = _find_violations(headings)
    _write_csv(violations)

    if violations:
        print(f"Found {len(violations)} invalid heading(s). " f"Wrote: {OUTPUT_FILE}")
        return 1

    print(f"OK: every heading has exactly one time-bucket tag. Wrote: {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
