import json
import shutil
from collections.abc import Iterator
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from conftest import write_dashboard_init

from org_timeviz.aggregate import Aggregates, compute_aggregates
from org_timeviz.config import AppConfig
from org_timeviz.filters import clip_to_window
from org_timeviz.models import ClockRecord
from org_timeviz.org_source.clock_dashboard import ClockDashboard, ClockOverlap, OverlapClock
from org_timeviz.org_source.emacs import parse_org_clock_records_emacs
from org_timeviz.overlap_approvals import (
    APPROVALS_FILE_ENV_VAR,
    APPROVALS_FILE_SETTING,
    ApprovalStore,
    ApprovalStoreError,
    ClockIdentity,
    OverlapApprovalError,
    OverlapApprovals,
    OverlapPair,
    review_overlaps,
)
from org_timeviz.rendering.index import write_index_html
from org_timeviz.rendering.monthly_time_buckets import (
    MonthlyTimeBuckets,
    compute_monthly_time_buckets,
)
from org_timeviz.rendering.tag_timeseries import compute_daily_tag_hours
from org_timeviz.server import APPROVAL_HEADER, _build_server
from org_timeviz.time_windows import TimeWindow

requires_emacs = pytest.mark.skipif(shutil.which("emacs") is None, reason="Emacs is not installed")
DASHBOARD_QUERY = "/clock-dashboard?date=2026-08-05&day_total_date=2026-08-05&week_date=2026-08-05"


def _clock(
    task: str,
    org_id: str | None,
    start: str,
    end: str | None,
    *,
    file: str = "a.org",
    line: int = 1,
) -> OverlapClock:
    return OverlapClock(
        task=task,
        interval=f"{start}--{end}",
        file=file,
        line=line,
        org_id=org_id,
        start=start,
        end=end,
    )


VACATION = _clock("a.org: Vacation", "vacation-id", "2026-08-05T08:00", "2026-08-05T16:00", line=6)
FIX = _clock("a.org: Urgent fix", "fix-id", "2026-08-05T09:00", "2026-08-05T10:00", line=13)
VACATION_FIX = ClockOverlap(a=VACATION, b=FIX)
VACATION_FIX_PAIR = OverlapPair.of(
    ClockIdentity("vacation-id", "2026-08-05T08:00", "2026-08-05T16:00"),
    ClockIdentity("fix-id", "2026-08-05T09:00", "2026-08-05T10:00"),
)


def _app_config(output_dir: Path, init_paths: list[Path] | None = None) -> AppConfig:
    return AppConfig.model_validate(
        {
            "app": {"output_dir": str(output_dir), "log_level": "INFO"},
            "org_sources": {
                "mode": "explicit",
                "explicit_files": [],
                "emacs_init_paths": [str(path) for path in (init_paths or [])],
            },
            "time_buckets": {
                "other_bucket": "other",
                "bucket_order": ["holidays", "work", "other"],
                "tag_to_bucket": {"vacation": "holidays", "job": "work"},
                "resolution": {
                    "default_strategy": "priority",
                    "priority_order": ["holidays", "work", "other"],
                    "weights": {},
                    "rules": [],
                },
            },
        }
    )


def _dashboard(*overlaps: ClockOverlap) -> ClockDashboard:
    return ClockDashboard(
        day="2026-08-05",
        day_total_day="2026-08-05",
        week_start="2026-08-03",
        week_end="2026-08-09",
        suspects="All CLOCK lines look standard.",
        chronological="entries",
        day_total="9:00",
        week_total="9:00",
        overlaps=overlaps,
    )


class _Server:
    def __init__(self, cfg: AppConfig, output_dir: Path, approvals: OverlapApprovals) -> None:
        self.httpd: ThreadingHTTPServer = _build_server(cfg, output_dir, 0, approvals)
        self.thread = Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def dashboard(self) -> dict[str, Any]:
        with urlopen(f"{self.base_url}{DASHBOARD_QUERY}") as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return payload

    def post_approval(
        self,
        body: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        request = Request(
            f"{self.base_url}/overlap-approvals",
            data=data,
            method="POST",
            headers=headers or {"Content-Type": "application/json", APPROVAL_HEADER: "1"},
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))


@pytest.fixture
def approvals_path(tmp_path: Path) -> Path:
    return tmp_path / "private" / "approved_overlaps.json"


@pytest.fixture
def server(tmp_path: Path, approvals_path: Path) -> Iterator[_Server]:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    running = _Server(
        _app_config(output_dir), output_dir, OverlapApprovals(ApprovalStore(approvals_path))
    )
    try:
        with patch(
            "org_timeviz.server.render_clock_dashboard",
            return_value=_dashboard(VACATION_FIX),
        ):
            yield running
    finally:
        running.stop()


def _statuses(payload: dict[str, Any]) -> list[str]:
    return [overlap["status"] for overlap in payload["overlaps"]]


# Identities and review -------------------------------------------------------


def test_pair_identity_ignores_clock_order() -> None:
    first = ClockIdentity("a-id", "2026-08-05T08:00", "2026-08-05T09:00")
    second = ClockIdentity("b-id", "2026-08-05T08:30", "2026-08-05T10:00")

    assert OverlapPair.of(first, second) == OverlapPair.of(second, first)
    assert OverlapPair.of(second, first).to_json() == [
        {"org_id": "a-id", "start": "2026-08-05T08:00", "end": "2026-08-05T09:00"},
        {"org_id": "b-id", "start": "2026-08-05T08:30", "end": "2026-08-05T10:00"},
    ]


def test_review_matches_approvals_despite_title_location_and_display_order() -> None:
    renamed = _clock(
        "b.org: Urgent fix (renamed)",
        "fix-id",
        "2026-08-05T09:00",
        "2026-08-05T10:00",
        file="b.org",
        line=42,
    )

    (reviewed,) = review_overlaps(
        [ClockOverlap(a=renamed, b=VACATION)], frozenset({VACATION_FIX_PAIR})
    )

    assert reviewed.status == "approved"
    assert reviewed.pair == VACATION_FIX_PAIR


def test_review_blocks_missing_org_ids_and_open_clocks() -> None:
    no_id = _clock("a.org: Untracked", None, "2026-08-05T09:00", "2026-08-05T10:00")
    open_clock = _clock("a.org: Live", "live-id", "2026-08-05T09:30", None)

    missing, live = review_overlaps(
        [ClockOverlap(a=no_id, b=VACATION), ClockOverlap(a=VACATION, b=open_clock)],
        frozenset(),
    )

    assert (missing.status, missing.pair, missing.reasons) == (
        "blocked",
        None,
        ("Task A needs an Org ID",),
    )
    assert (live.status, live.pair, live.reasons) == (
        "blocked",
        None,
        ("Task B clock is still open",),
    )


def test_review_blocks_indistinguishable_clocks_even_if_approved() -> None:
    duplicate = _clock("a.org: Urgent fix", "fix-id", FIX.start, "2026-08-05T10:00", line=14)
    overlaps = [
        ClockOverlap(a=VACATION, b=FIX),
        ClockOverlap(a=VACATION, b=duplicate),
        ClockOverlap(a=FIX, b=duplicate),
    ]

    reviewed = review_overlaps(overlaps, frozenset({VACATION_FIX_PAIR}))

    assert [item.status for item in reviewed] == ["blocked", "blocked", "blocked"]
    assert reviewed[0].reasons == ("Task B shares its Org ID and interval with another clock",)
    assert all(item.pair is None for item in reviewed)


def test_review_does_not_match_approval_after_interval_edit() -> None:
    extended = _clock("a.org: Urgent fix", "fix-id", "2026-08-05T09:00", "2026-08-05T10:15")

    (reviewed,) = review_overlaps(
        [ClockOverlap(a=VACATION, b=extended)], frozenset({VACATION_FIX_PAIR})
    )

    assert reviewed.status == "unapproved"
    assert reviewed.pair != VACATION_FIX_PAIR


# Approval store --------------------------------------------------------------


def test_store_reads_missing_file_as_empty_without_creating_it(approvals_path: Path) -> None:
    assert ApprovalStore(approvals_path).load() == frozenset()
    assert not approvals_path.parent.exists()


def test_store_persists_approvals_across_instances(approvals_path: Path) -> None:
    ApprovalStore(approvals_path).set_approved(VACATION_FIX_PAIR, True)

    assert json.loads(approvals_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "approved_overlaps": [VACATION_FIX_PAIR.to_json()],
    }
    assert ApprovalStore(approvals_path).load() == {VACATION_FIX_PAIR}
    assert list(approvals_path.parent.iterdir()) == [approvals_path]

    ApprovalStore(approvals_path).set_approved(VACATION_FIX_PAIR, False)

    assert ApprovalStore(approvals_path).load() == frozenset()


def test_store_skips_writes_that_change_nothing(approvals_path: Path) -> None:
    store = ApprovalStore(approvals_path)
    store.set_approved(VACATION_FIX_PAIR, False)
    assert not approvals_path.exists()

    store.set_approved(VACATION_FIX_PAIR, True)
    written = approvals_path.stat().st_mtime_ns
    with patch.object(ApprovalStore, "_write", side_effect=AssertionError("unexpected write")):
        store.set_approved(VACATION_FIX_PAIR, True)
    assert approvals_path.stat().st_mtime_ns == written


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ('{"version": 2, "approved_overlaps": []}', "unsupported version 2"),
        ('{"version": true, "approved_overlaps": []}', "unsupported version True"),
        ('{"version": 1, "approved_overlaps": {}}', "must be a list"),
        ('{"version": 1, "approved_overlaps": [], "notes": "x"}', "exactly 'version'"),
        ('{"version": 1, "approved_overlaps": [[]]}', "approved_overlaps\\[0\\]"),
        (
            '{"version": 1, "approved_overlaps": [[{"org_id": "a", "start": "x", "end": "y"},'
            '{"org_id": "b", "start": "x", "end": "y"}]]}',
            "YYYY-MM-DDTHH:MM",
        ),
    ],
)
def test_store_rejects_malformed_files_without_overwriting(
    approvals_path: Path, text: str, message: str
) -> None:
    approvals_path.parent.mkdir()
    approvals_path.write_text(text, encoding="utf-8")
    store = ApprovalStore(approvals_path)

    with pytest.raises(ApprovalStoreError, match=message):
        store.load()
    with pytest.raises(ApprovalStoreError):
        store.set_approved(VACATION_FIX_PAIR, True)
    assert approvals_path.read_text(encoding="utf-8") == text


def test_store_reports_unwritable_location(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "missing-parent" / "timeviz" / "approved.json")

    with pytest.raises(ApprovalStoreError, match="Could not write"):
        store.set_approved(VACATION_FIX_PAIR, True)
    assert not (tmp_path / "missing-parent").exists()


def test_store_cleans_up_after_failed_replace(approvals_path: Path) -> None:
    with patch("org_timeviz.overlap_approvals.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(ApprovalStoreError, match="disk full"):
            ApprovalStore(approvals_path).set_approved(VACATION_FIX_PAIR, True)
    assert list(approvals_path.parent.iterdir()) == []


@pytest.mark.parametrize(
    ("environment_file", "configured_file", "expected"),
    [
        ("/env/approved.json", "/yaml/approved.json", Path("/env/approved.json")),
        ("/env/approved.json", None, Path("/env/approved.json")),
        (None, "/yaml/approved.json", Path("/yaml/approved.json")),
        ("  ", "/yaml/approved.json", Path("/yaml/approved.json")),
    ],
)
def test_environment_variable_overrides_configured_approvals_file(
    environment_file: str | None, configured_file: str | None, expected: Path
) -> None:
    environ = {} if environment_file is None else {APPROVALS_FILE_ENV_VAR: environment_file}

    approvals = OverlapApprovals.from_settings(configured_file, environ)

    assert approvals.store_path == expected
    assert approvals.disabled_message is None


_RELATIVE_PATH = "must be an absolute path"


@pytest.mark.parametrize(
    ("environment_file", "configured_file", "message"),
    [
        (None, None, f"Set {APPROVALS_FILE_SETTING}"),
        ("   ", "  ", f"Set {APPROVALS_FILE_SETTING}"),
        ("relative/approved.json", None, f"{APPROVALS_FILE_ENV_VAR} {_RELATIVE_PATH}"),
        (None, "relative/approved.json", f"{APPROVALS_FILE_SETTING} {_RELATIVE_PATH}"),
        (None, "~no-such-org-timeviz-user/approved.json", _RELATIVE_PATH),
        # An invalid override is reported rather than silently replaced by the YAML path.
        ("relative/approved.json", "/yaml/approved.json", APPROVALS_FILE_ENV_VAR),
    ],
)
def test_approvals_are_disabled_without_an_absolute_configured_path(
    environment_file: str | None, configured_file: str | None, message: str
) -> None:
    environ = {} if environment_file is None else {APPROVALS_FILE_ENV_VAR: environment_file}
    approvals = OverlapApprovals.from_settings(configured_file, environ)

    review = approvals.review([VACATION_FIX])

    assert approvals.store_path is None
    assert approvals.disabled_message is not None and message in approvals.disabled_message
    assert (review.enabled, review.message) == (False, approvals.disabled_message)
    assert review.overlaps[0].status == "unapproved"
    with pytest.raises(OverlapApprovalError, match=message):
        approvals.set_approved(VACATION_FIX_PAIR, True)


@pytest.mark.parametrize("from_environment", [True, False])
def test_approvals_expand_home_in_configured_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, from_environment: bool
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    environ = {APPROVALS_FILE_ENV_VAR: "~/orgs/a.json"} if from_environment else {}

    approvals = OverlapApprovals.from_settings(
        None if from_environment else "~/orgs/a.json", environ
    )

    assert approvals.store_path == tmp_path / "orgs" / "a.json"
    assert approvals.disabled_message is None


def test_directory_as_approvals_file_disables_approvals_safely(tmp_path: Path) -> None:
    approvals = OverlapApprovals.from_settings(str(tmp_path), {})

    review = approvals.review([VACATION_FIX])

    assert review.enabled is False
    assert review.message is not None and "Could not read" in review.message
    assert review.overlaps[0].status == "unapproved"
    with pytest.raises(OverlapApprovalError, match="Could not read"):
        approvals.set_approved(VACATION_FIX_PAIR, False)
    assert list(tmp_path.iterdir()) == []


def test_approvals_only_accept_pairs_from_the_latest_review(approvals_path: Path) -> None:
    approvals = OverlapApprovals(ApprovalStore(approvals_path))

    with pytest.raises(OverlapApprovalError, match="refresh the clock dashboard"):
        approvals.set_approved(VACATION_FIX_PAIR, True)

    approvals.review([VACATION_FIX])
    approvals.set_approved(VACATION_FIX_PAIR, True)
    assert approvals.review([VACATION_FIX]).overlaps[0].status == "approved"

    approvals.review([])
    with pytest.raises(OverlapApprovalError):
        approvals.set_approved(VACATION_FIX_PAIR, True)
    approvals.set_approved(VACATION_FIX_PAIR, False)
    assert ApprovalStore(approvals_path).load() == frozenset()


# HTTP API --------------------------------------------------------------------


def test_dashboard_reports_overlap_state_without_creating_store(
    server: _Server, approvals_path: Path
) -> None:
    payload = server.dashboard()

    assert payload["overlap_approvals"] == {"enabled": True, "message": None}
    assert payload["suspects"] == "All CLOCK lines look standard."
    assert payload["overlaps"] == [
        {
            "a": {
                "task": "a.org: Vacation",
                "interval": "2026-08-05T08:00--2026-08-05T16:00",
                "file": "a.org",
                "line": 6,
                "org_id": "vacation-id",
                "start": "2026-08-05T08:00",
                "end": "2026-08-05T16:00",
            },
            "b": {
                "task": "a.org: Urgent fix",
                "interval": "2026-08-05T09:00--2026-08-05T10:00",
                "file": "a.org",
                "line": 13,
                "org_id": "fix-id",
                "start": "2026-08-05T09:00",
                "end": "2026-08-05T10:00",
            },
            "status": "unapproved",
            "pair": VACATION_FIX_PAIR.to_json(),
            "reasons": [],
        }
    ]
    assert not approvals_path.exists()


def test_approve_and_unapprove_are_persistent_and_idempotent(
    server: _Server, approvals_path: Path
) -> None:
    pair = server.dashboard()["overlaps"][0]["pair"]
    reversed_pair = list(reversed(pair))

    for body_pair in (pair, reversed_pair):
        status, result = server.post_approval({"action": "approve", "pair": body_pair})
        assert (status, result) == (200, {"pair": pair, "approved": True})
    assert _statuses(server.dashboard()) == ["approved"]
    assert ApprovalStore(approvals_path).load() == {VACATION_FIX_PAIR}

    for _ in range(2):
        status, result = server.post_approval({"action": "unapprove", "pair": reversed_pair})
        assert (status, result) == (200, {"pair": pair, "approved": False})
    assert _statuses(server.dashboard()) == ["unapproved"]
    assert ApprovalStore(approvals_path).load() == frozenset()


def test_approval_survives_server_restart(tmp_path: Path, approvals_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    environ = {APPROVALS_FILE_ENV_VAR: str(approvals_path)}

    with patch("org_timeviz.server.render_clock_dashboard", return_value=_dashboard(VACATION_FIX)):
        first = _Server(
            _app_config(output_dir), output_dir, OverlapApprovals.from_settings(None, environ)
        )
        try:
            pair = first.dashboard()["overlaps"][0]["pair"]
            assert first.post_approval({"action": "approve", "pair": pair})[0] == 200
        finally:
            first.stop()

        second = _Server(
            _app_config(output_dir), output_dir, OverlapApprovals.from_settings(None, environ)
        )
        try:
            assert _statuses(second.dashboard()) == ["approved"]
        finally:
            second.stop()


def test_approval_rejects_pairs_that_are_not_detected(server: _Server) -> None:
    server.dashboard()
    other = OverlapPair.of(
        ClockIdentity("vacation-id", "2026-08-05T08:00", "2026-08-05T16:00"),
        ClockIdentity("other-id", "2026-08-05T09:00", "2026-08-05T10:00"),
    )

    status, result = server.post_approval({"action": "approve", "pair": other.to_json()})

    assert status == 409
    assert "not among the currently detected" in result["error"]


@pytest.mark.parametrize(
    ("body", "headers", "expected_status"),
    [
        ({"action": "approve"}, None, 400),
        ({"action": "delete", "pair": VACATION_FIX_PAIR.to_json()}, None, 400),
        ({"action": "approve", "pair": VACATION_FIX_PAIR.to_json(), "path": "/x"}, None, 400),
        ({"action": "approve", "pair": [VACATION_FIX_PAIR.to_json()[0]]}, None, 400),
        ({"action": "approve", "pair": [VACATION_FIX_PAIR.to_json()[0]] * 2}, None, 400),
        (
            {"action": "approve", "pair": [{"org_id": " x", "start": "a", "end": "b"}] * 2},
            None,
            400,
        ),
        (b"{not json", None, 400),
        (b"\xff\xfe\xfa", None, 400),
        ({}, {"Content-Type": "application/json"}, 403),
        ({}, {"Content-Type": "application/json", APPROVAL_HEADER: "1", "Host": "evil.test"}, 403),
        ({}, {"Content-Type": "text/plain", APPROVAL_HEADER: "1"}, 415),
        (
            {},
            {"Content-Type": "application/json", APPROVAL_HEADER: "1", "Content-Length": "x"},
            411,
        ),
        (
            {},
            {"Content-Type": "application/json", APPROVAL_HEADER: "1", "Content-Length": "9000"},
            413,
        ),
    ],
)
def test_approval_endpoint_validates_requests(
    server: _Server,
    approvals_path: Path,
    body: object,
    headers: dict[str, str] | None,
    expected_status: int,
) -> None:
    server.dashboard()

    status, result = server.post_approval(body, headers=headers)

    assert status == expected_status
    assert result["error"]
    assert not approvals_path.exists()


def test_approval_endpoint_is_disabled_without_configured_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    running = _Server(_app_config(output_dir), output_dir, OverlapApprovals.from_settings(None, {}))
    try:
        with patch(
            "org_timeviz.server.render_clock_dashboard", return_value=_dashboard(VACATION_FIX)
        ):
            payload = running.dashboard()
            status, result = running.post_approval(
                {"action": "approve", "pair": payload["overlaps"][0]["pair"]}
            )
    finally:
        running.stop()

    assert payload["overlap_approvals"]["enabled"] is False
    assert APPROVALS_FILE_SETTING in payload["overlap_approvals"]["message"]
    assert _statuses(payload) == ["unapproved"]
    assert status == 409
    assert APPROVALS_FILE_SETTING in result["error"]


def test_malformed_store_disables_approvals_and_is_preserved(
    server: _Server, approvals_path: Path
) -> None:
    approvals_path.parent.mkdir()
    approvals_path.write_text("{broken", encoding="utf-8")

    payload = server.dashboard()
    status, result = server.post_approval(
        {"action": "approve", "pair": payload["overlaps"][0]["pair"]}
    )

    assert payload["overlap_approvals"]["enabled"] is False
    assert "not valid JSON" in payload["overlap_approvals"]["message"]
    assert status == 409
    assert "not valid JSON" in result["error"]
    assert approvals_path.read_text(encoding="utf-8") == "{broken"


def test_unknown_post_path_is_still_rejected(server: _Server) -> None:
    request = Request(f"{server.base_url}/overlap-approvals/x", data=b"{}", method="POST")

    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == 404


def test_generated_index_contains_interactive_overlap_table(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    write_index_html(output_dir, output_dir / "assets")
    text = (output_dir / "index.html").read_text(encoding="utf-8")

    assert 'id="clock-suspects"' in text
    assert 'id="clock-overlaps"' in text
    assert 'id="show-approved-overlaps" type="checkbox" /> Show approved overlaps' in text
    assert 'id="show-approved-overlaps" type="checkbox" checked' not in text
    assert 'overlaps.filter((overlap) => overlap.status !== "approved")' in text
    assert 'showApprovedInput.addEventListener("change", renderOverlaps)' in text
    assert 'fetch("/overlap-approvals"' in text
    assert '"X-Org-Timeviz-Approval": "1"' in text
    assert "No unapproved overlapping clocks" in text
    assert 'row.className = "approved-overlap"' in text
    assert '"Location A"' in text


# End to end with Emacs -------------------------------------------------------

VACATION_ORG = """\
* Vacation                                                         :vacation:
:PROPERTIES:
:ID:       vacation-id
:END:
:LOGBOOK:
CLOCK: [2026-08-05 Wed 08:00]--[2026-08-05 Wed 16:00] =>  8:00
:END:
"""

WORK_ORG = """\
* Urgent fix                                                            :job:
:PROPERTIES:
:ID:       fix-id
:END:
:LOGBOOK:
CLOCK: [2026-08-05 Wed 09:00]--[2026-08-05 Wed 10:00] =>  1:00
:END:
* Review without ID                                                     :job:
:LOGBOOK:
CLOCK: [2026-08-05 Wed 13:00]--[2026-08-05 Wed 13:30] =>  0:30
:END:
"""


@pytest.fixture
def org_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[AppConfig, list[Path]]:
    # Keep the report parser away from any init file configured by other tests.
    monkeypatch.delenv("ORG_TIMEVIZ_EMACS_INIT", raising=False)
    monkeypatch.delenv("ORG_TIMEVIZ_TODO_KEYWORDS", raising=False)
    org_files = [tmp_path / "a.org", tmp_path / "b.org"]
    org_files[0].write_text(VACATION_ORG, encoding="utf-8")
    org_files[1].write_text(WORK_ORG, encoding="utf-8")
    init_path = tmp_path / "init-org.el"
    write_dashboard_init(init_path, org_files)
    (tmp_path / "outputs").mkdir()
    return _app_config(tmp_path / "outputs", [init_path]), org_files


def _accounting_snapshot(
    cfg: AppConfig, org_files: list[Path]
) -> tuple[list[ClockRecord], Aggregates, MonthlyTimeBuckets, dict[str, dict[str, float]]]:
    """Return the parsed records and the totals every time report is built from."""
    records = parse_org_clock_records_emacs(org_files)
    clipped = clip_to_window(
        records, TimeWindow(name="all", start=datetime(2026, 1, 1), end=datetime(2027, 1, 1))
    )
    return (
        records,
        compute_aggregates(clipped, cfg.time_buckets),
        compute_monthly_time_buckets(clipped, cfg.time_buckets),
        compute_daily_tag_hours(clipped),
    )


def _start_e2e_server(cfg: AppConfig, approvals_path: Path) -> _Server:
    approvals = OverlapApprovals.from_settings(str(approvals_path), {})
    return _Server(cfg, Path(cfg.app.output_dir), approvals)


@requires_emacs
def test_end_to_end_approval_hides_warning_without_changing_accounting(
    org_workspace: tuple[AppConfig, list[Path]], approvals_path: Path
) -> None:
    cfg, org_files = org_workspace
    org_bytes = [path.read_bytes() for path in org_files]
    accounting = _accounting_snapshot(cfg, org_files)
    # Overlapping clocks keep counting independently: 8:00 + 1:00 + 0:30.
    assert accounting[1].minutes_total == 570

    server = _start_e2e_server(cfg, approvals_path)
    try:
        before = server.dashboard()
        assert _statuses(before) == ["unapproved", "blocked"]
        assert [(o["a"]["task"], o["b"]["task"]) for o in before["overlaps"]] == [
            ("a.org: Vacation", "b.org: Urgent fix"),
            ("a.org: Vacation", "b.org: Review without ID"),
        ]
        assert before["overlaps"][1]["reasons"] == ["Task B needs an Org ID"]
        assert (before["day_total"], before["week_total"]) == ("9:30", "9:30")

        status, _ = server.post_approval(
            {"action": "approve", "pair": before["overlaps"][0]["pair"]}
        )
        assert status == 200
    finally:
        server.stop()

    server = _start_e2e_server(cfg, approvals_path)
    try:
        after = server.dashboard()
    finally:
        server.stop()
    assert _statuses(after) == ["approved", "blocked"]
    unchanged_fields = ("suspects", "chronological", "day_total", "week_total")
    assert {key: after[key] for key in unchanged_fields} == {
        key: before[key] for key in unchanged_fields
    }
    assert _accounting_snapshot(cfg, org_files) == accounting
    assert [path.read_bytes() for path in org_files] == org_bytes
    assert json.loads(approvals_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "approved_overlaps": [VACATION_FIX_PAIR.to_json()],
    }


@requires_emacs
def test_end_to_end_identity_follows_org_id_and_interval_edits(
    org_workspace: tuple[AppConfig, list[Path]], approvals_path: Path
) -> None:
    cfg, org_files = org_workspace
    work_org = org_files[1]
    server = _start_e2e_server(cfg, approvals_path)
    try:
        pair = server.dashboard()["overlaps"][0]["pair"]
        assert server.post_approval({"action": "approve", "pair": pair})[0] == 200

        # Renaming the task and shifting its lines keeps the approval.
        work_org.write_text(
            "#+TITLE: Work\n\n" + WORK_ORG.replace("Urgent fix", "Urgent production fix"),
            encoding="utf-8",
        )
        moved = server.dashboard()["overlaps"][0]
        assert (moved["status"], moved["b"]["task"], moved["b"]["line"]) == (
            "approved",
            "b.org: Urgent production fix",
            8,
        )

        # Adding the missing ID makes the second overlap approvable.
        work_org.write_text(
            WORK_ORG.replace(
                "* Review without ID                                                     :job:\n",
                "* Review without ID :job:\n:PROPERTIES:\n:ID:       review-id\n:END:\n",
            ),
            encoding="utf-8",
        )
        assert _statuses(server.dashboard()) == ["approved", "unapproved"]

        # Editing an approved clock's interval invalidates its approval.
        work_org.write_text(
            WORK_ORG.replace("Wed 10:00] =>  1:00", "Wed 10:15] =>  1:15"), encoding="utf-8"
        )
        assert _statuses(server.dashboard()) == ["unapproved", "blocked"]
    finally:
        server.stop()
