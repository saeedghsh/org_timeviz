import json
from datetime import datetime
from pathlib import Path

import pytest

from org_timeviz.config import TimeBucketsConfig
from org_timeviz.filters import ClippedRecord
from org_timeviz.models import ClockRecord

# Minimal stand-ins for the user's init-org.el helpers, close enough to the real
# implementations that the exporter's overlap scan and time totals run unchanged.
_DASHBOARD_INIT_HELPERS = r"""
(defun my/org-clock-suspects (files) (ignore files) nil)
(defun my/org--collect-ts-pos (s)
  (let ((pos 0) acc)
    (while (string-match "\\(\\[[^]]+\\]\\)" s pos)
      (push (cons (match-string 1 s) (cons (match-beginning 1) (match-end 1))) acc)
      (setq pos (match-end 1)))
    (nreverse acc)))
(defun my/org--ts->sec (ts) (float-time (org-time-string-to-time ts)))
(defun my/org-clocklog-rows (&optional date files)
  (let* ((day-start (my/org--ts->sec (format "[%s 00:00]" date)))
         (day-end (+ day-start 86400))
         (rows '()))
    (dolist (file (or files (org-agenda-files)))
      (with-current-buffer (find-file-noselect file)
        (save-excursion
          (goto-char (point-min))
          (while (re-search-forward "^ *CLOCK: *\\(\\[[^]]+\\]\\)--\\(\\[[^]]+\\]\\)" nil t)
            (let* ((start-ts (match-string 1))
                   (end-ts (match-string 2))
                   (start (max day-start (my/org--ts->sec start-ts)))
                   (end (min day-end (my/org--ts->sec end-ts))))
              (when (< start end)
                (save-excursion
                  (org-back-to-heading t)
                  (push (list start end (/ (- end start) 60.0) (org-get-heading t t t t))
                        rows))))))))
    (sort rows (lambda (left right) (< (car left) (car right))))))
(defun my/org-clocklog--fmt-hhmm (seconds) (format-time-string "%H:%M" seconds))
(defun my/org-clocklog--fmt-dur (minutes)
  (let ((rounded (floor minutes)))
    (format "%d:%02d" (/ rounded 60) (% rounded 60))))
"""


def write_dashboard_init(path: Path, org_files: list[Path]) -> None:
    """Write an Emacs init whose agenda is ORG_FILES, with minimal dashboard helpers."""
    agenda = " ".join(json.dumps(str(org_file)) for org_file in org_files)
    path.write_text(
        f"(require 'org)\n(setq org-agenda-files '({agenda}))\n{_DASHBOARD_INIT_HELPERS}",
        encoding="utf-8",
    )


@pytest.fixture
def bucket_cfg() -> TimeBucketsConfig:
    return TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["work", "study", "other"],
            "tag_to_bucket": {"job": "work", "course": "study"},
            "resolution": {
                "default_strategy": "priority",
                "priority_order": ["work", "study", "other"],
                "weights": {},
                "rules": [],
            },
        }
    )


def make_record(
    *,
    start: datetime,
    end: datetime,
    tags: tuple[str, ...] = (),
    headline: str = "Task",
    outline_path: str | None = None,
    file_path: Path | None = None,
) -> ClockRecord:
    return ClockRecord(
        file_path=file_path or Path("sample.org"),
        outline_path=outline_path or headline,
        headline=headline,
        tags=tags,
        start=start,
        end=end,
    )


def make_clipped(
    record: ClockRecord, *, start: datetime | None = None, end: datetime | None = None
) -> ClippedRecord:
    clipped_start = start or record.start
    clipped_end = end or record.end
    minutes = int((clipped_end - clipped_start).total_seconds() // 60)
    return ClippedRecord(record=record, start=clipped_start, end=clipped_end, minutes=minutes)
