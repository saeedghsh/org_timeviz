"""Read CLOCK records from Org archive files with their original classification."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from org_timeviz.aggregate import Aggregates, compute_aggregates
from org_timeviz.config import TimeBucketsConfig
from org_timeviz.filters import clip_to_window
from org_timeviz.models import ClockRecord
from org_timeviz.org_source import emacs as emacs_source
from org_timeviz.org_source.emacs import parse_org_clock_records_emacs
from org_timeviz.rendering.monthly_time_buckets import (
    MonthlyTimeBuckets,
    compute_monthly_time_buckets,
)
from org_timeviz.rendering.tag_timeseries import compute_daily_tag_hours
from org_timeviz.time_windows import TimeWindow

requires_emacs = pytest.mark.skipif(shutil.which("emacs") is None, reason="Emacs is not installed")
EXPORT_SCRIPT = Path(emacs_source.__file__).parent / "elisp" / "org_timeviz_export.el"
ALL_OF_2026 = TimeWindow(name="all", start=datetime(2026, 1, 1), end=datetime(2027, 1, 1))

# Tags reach the clocks below from #+FILETAGS (`client`), a grandparent heading
# (`alpha`), and the headings themselves, so archiving must keep inherited tags.
WORK_ORG = """\
#+CATEGORY: CLIENT
#+FILETAGS: :client:

* Project Alpha                                                         :alpha:
:PROPERTIES:
:CATEGORY: ALPHA
:END:
** Design                                                              :design:
:LOGBOOK:
CLOCK: [2026-03-06 Fri 10:00]--[2026-03-06 Fri 11:00] =>  1:00
:END:
*** DONE Nested review                                                 :review:
:PROPERTIES:
:ID:       nested-review-id
:END:
:LOGBOOK:
CLOCK: [2026-03-04 Wed 13:00]--[2026-03-04 Wed 14:00] =>  1:00
CLOCK: [2026-03-02 Mon 09:00]--[2026-03-02 Mon 10:30] =>  1:30
:END:
** Ongoing work
:LOGBOOK:
CLOCK: [2026-03-02 Mon 11:00]--[2026-03-02 Mon 12:00] =>  1:00
:END:
* DONE Client call                                                       :call:
:LOGBOOK:
CLOCK: [2026-03-03 Tue 09:00]--[2026-03-03 Tue 09:45] =>  0:45
:END:
* Course homework                                                      :course:
:LOGBOOK:
CLOCK: [2026-04-05 Sun 18:00]--[2026-04-05 Sun 19:00] =>  1:00
:END:
"""
# "Design" is a nested subtree with a child; "Client call" is a top-level task.
ARCHIVED_HEADINGS = ("Design", "Client call")
EXPECTED_BUCKET_MINUTES = {"alpha": 270.0, "work": 45.0, "study": 60.0}

# Each case is a real Org setup for keeping inherited tags on archived headings.
ARCHIVE_SETUPS = {
    # Org's default: inherited tags are stored only in ARCHIVE_ITAGS.
    "archive-itags": "(setq org-archive-subtree-add-inherited-tags nil)",
    # Inherited tags are copied onto the heading and also stored in ARCHIVE_ITAGS.
    "heading-tags-and-archive-itags": "(setq org-archive-subtree-add-inherited-tags t)",
    # Inherited tags are copied onto the heading only.
    "heading-tags-only": (
        "(setq org-archive-subtree-add-inherited-tags t)"
        "(setq org-archive-save-context-info '(time file olpath category todo))"
    ),
}


@pytest.fixture(autouse=True)
def _isolated_emacs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Keep Emacs away from the user's home and any init file set by other tests.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ORG_TIMEVIZ_EMACS_INIT", raising=False)
    monkeypatch.delenv("ORG_TIMEVIZ_TODO_KEYWORDS", raising=False)


@pytest.fixture
def time_buckets() -> TimeBucketsConfig:
    order = ["alpha", "study", "work", "other"]
    return TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": order,
            "tag_to_bucket": {"alpha": "alpha", "course": "study", "client": "work"},
            "resolution": {"default_strategy": "priority", "priority_order": order},
        }
    )


def _archive_subtrees(org_file: Path, headings: tuple[str, ...], setup: str) -> Path:
    """Move HEADINGS into ORG_FILE's archive with Org's own `org-archive-subtree`."""
    archive_forms = "".join(
        f'(goto-char (point-min)) (re-search-forward (concat "^\\\\*+ .*" '
        f"(regexp-quote {json.dumps(heading)}))) (org-archive-subtree)"
        for heading in headings
    )
    program = (
        "(progn (require 'org) (require 'org-archive)"
        # Do not record moved IDs in an org-id locations file.
        " (setq org-id-track-globally nil)"
        f" {setup}"
        f" (with-current-buffer (find-file-noselect {json.dumps(str(org_file))})"
        f" {archive_forms} (save-buffer))"
        " (org-save-all-org-buffers))"
    )
    subprocess.run(["emacs", "--batch", "-Q", "--eval", program], check=True, capture_output=True)
    return org_file.with_name(org_file.name + "_archive")


def _classification(records: list[ClockRecord]) -> list[tuple[object, ...]]:
    """Return what reports use from each record, independent of its file."""
    return sorted(
        (record.start, record.end, record.outline_path, record.headline, sorted(record.tags))
        for record in records
    )


def _report_totals(
    records: list[ClockRecord], time_buckets: TimeBucketsConfig
) -> tuple[Aggregates, MonthlyTimeBuckets, dict[str, dict[str, float]]]:
    """Return the totals the daily, monthly, dashboard, and tag reports are built from."""
    clipped = clip_to_window(records, ALL_OF_2026)
    return (
        compute_aggregates(clipped, time_buckets),
        compute_monthly_time_buckets(clipped, time_buckets),
        compute_daily_tag_hours(clipped),
    )


def _exported_categories(org_files: list[Path]) -> dict[str, set[str]]:
    """Return the categories the batch exporter reports for each headline."""
    result = subprocess.run(
        ["emacs", "--batch", "-Q", "--load", str(EXPORT_SCRIPT), "--", *map(str, org_files)],
        check=True,
        capture_output=True,
        text=True,
    )
    categories: dict[str, set[str]] = {}
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            entry = json.loads(line)
            categories.setdefault(entry["headline"], set()).add(entry["category"])
    return categories


@requires_emacs
@pytest.mark.parametrize("setup", ARCHIVE_SETUPS.values(), ids=ARCHIVE_SETUPS.keys())
def test_archived_clocks_keep_their_classification_and_totals(
    tmp_path: Path, time_buckets: TimeBucketsConfig, setup: str
) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(WORK_ORG, encoding="utf-8")
    before = parse_org_clock_records_emacs([org_file])
    totals_before = _report_totals(before, time_buckets)

    archive = _archive_subtrees(org_file, ARCHIVED_HEADINGS, setup)
    after = parse_org_clock_records_emacs([org_file, archive])

    assert len(before) == len(after) == 6
    assert [record.headline for record in after if record.file_path == archive.resolve()] == [
        "Design",
        "Nested review",
        "Nested review",
        "Client call",
    ]
    assert _classification(after) == _classification(before)
    assert all(len(record.tags) == len(set(record.tags)) for record in after)
    assert totals_before[0].minutes_by_time_bucket == EXPECTED_BUCKET_MINUTES
    assert _report_totals(after, time_buckets) == totals_before


@requires_emacs
def test_archived_clocks_keep_their_original_category(tmp_path: Path) -> None:
    org_file = tmp_path / "work.org"
    org_file.write_text(WORK_ORG, encoding="utf-8")
    before = _exported_categories([org_file])

    archive = _archive_subtrees(org_file, ARCHIVED_HEADINGS, ARCHIVE_SETUPS["archive-itags"])

    # Without ARCHIVE_CATEGORY, the archive file's name would become the category.
    assert _exported_categories([archive]) == {
        "Design": {"ALPHA"},
        "Nested review": {"ALPHA"},
        "Client call": {"CLIENT"},
    }
    assert _exported_categories([org_file, archive]) == before


@requires_emacs
def test_archive_sibling_subtrees_keep_their_active_file_path(tmp_path: Path) -> None:
    # `org-archive-to-archive-sibling` only sets ARCHIVE_TIME and keeps the subtree
    # under its parent, so the real outline path and inherited tags still apply.
    org_file = tmp_path / "work.org"
    org_file.write_text(
        "* Project :alpha:\n** Archive :ARCHIVE:\n*** Old task\n"
        ":PROPERTIES:\n:ARCHIVE_TIME: 2026-03-09 Mon 10:00\n:END:\n"
        ":LOGBOOK:\nCLOCK: [2026-03-02 Mon 09:00]--[2026-03-02 Mon 10:00] =>  1:00\n:END:\n",
        encoding="utf-8",
    )

    [record] = parse_org_clock_records_emacs([org_file])

    assert record.outline_path == "Project / Archive / Old task"
    assert sorted(record.tags) == ["ARCHIVE", "alpha"]


@requires_emacs
def test_archived_tags_are_merged_without_repeats(tmp_path: Path) -> None:
    archive = tmp_path / "work.org_archive"
    archive.write_text(
        "#    -*- mode: org -*-\n\n"
        "* DONE Task                                                    :client:review:\n"
        ":PROPERTIES:\n:ARCHIVE_OLPATH: Project/Area\n:ARCHIVE_CATEGORY: ALPHA\n"
        ":ARCHIVE_ITAGS: client alpha\n:END:\n"
        ":LOGBOOK:\nCLOCK: [2026-03-02 Mon 09:00]--[2026-03-02 Mon 10:00] =>  1:00\n:END:\n",
        encoding="utf-8",
    )

    [record] = parse_org_clock_records_emacs([archive])

    assert record.tags == ("client", "alpha", "review")
    assert record.outline_path == "Project / Area / Task"
