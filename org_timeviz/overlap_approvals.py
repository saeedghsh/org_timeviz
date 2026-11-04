"""Persist which overlapping Org clocks the user approved as intentional.

Approvals only hide overlap warnings on the clock dashboard. They are never
read by the report pipeline and never change Org files or time accounting.

A clock is identified by its heading's Org `ID` property plus its start and end
timestamps; titles and line numbers are deliberately excluded because they
change as Org files are edited. An approval names an unordered pair of clocks.
The store is a JSON document of the form::

    {
      "version": 1,
      "approved_overlaps": [
        [
          {"org_id": "...", "start": "2026-01-05T13:00", "end": "2026-01-05T17:00"},
          {"org_id": "...", "start": "2026-01-05T13:35", "end": "2026-01-05T15:11"}
        ]
      ]
    }
"""

import json
import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Literal, Self

from .org_source.clock_dashboard import ClockOverlap, OverlapClock

APPROVALS_FILE_ENV_VAR = "ORG_TIMEVIZ_OVERLAP_APPROVALS_FILE"
APPROVALS_FILE_SETTING = "app.overlap_approvals_file"
SCHEMA_VERSION = 1
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
_DOCUMENT_KEYS = {"version", "approved_overlaps"}
_IDENTITY_KEYS = {"org_id", "start", "end"}

OverlapStatus = Literal["approved", "unapproved", "blocked"]


class OverlapApprovalError(Exception):
    """Report an approval change that cannot be applied."""


class ApprovalStoreError(OverlapApprovalError):
    """Report an approval file that cannot be read, parsed, or written."""


@dataclass(frozen=True, order=True)
class ClockIdentity:
    """Identify one closed clock independently of its title and location."""

    org_id: str
    start: str
    end: str

    @classmethod
    def from_json(cls, value: object) -> Self:
        """Validate a JSON clock identity."""
        if not isinstance(value, dict) or set(value) != _IDENTITY_KEYS:
            raise ValueError("a clock identity must have exactly org_id, start, and end")
        org_id = value["org_id"]
        if not isinstance(org_id, str) or not org_id or org_id != org_id.strip():
            raise ValueError("org_id must be a non-empty string without surrounding whitespace")
        for key in ("start", "end"):
            stamp = value[key]
            if not isinstance(stamp, str) or not _TIMESTAMP_RE.fullmatch(stamp):
                raise ValueError(f"{key} must be a YYYY-MM-DDTHH:MM timestamp")
        return cls(org_id=org_id, start=value["start"], end=value["end"])


@dataclass(frozen=True, order=True)
class OverlapPair:
    """Identify an unordered pair of clocks; build it with `OverlapPair.of`."""

    first: ClockIdentity
    second: ClockIdentity

    @classmethod
    def of(cls, one: ClockIdentity, other: ClockIdentity) -> Self:
        """Normalize the pair so that argument order never matters."""
        first, second = sorted((one, other))
        return cls(first=first, second=second)

    @classmethod
    def from_json(cls, value: object) -> Self:
        """Validate a JSON list of two clock identities."""
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("an overlap pair must list exactly two clock identities")
        pair = cls.of(ClockIdentity.from_json(value[0]), ClockIdentity.from_json(value[1]))
        if pair.first == pair.second:
            raise ValueError("an overlap pair must name two different clocks")
        return pair

    def to_json(self) -> list[dict[str, str]]:
        """Return the pair in its persisted JSON form."""
        return [asdict(self.first), asdict(self.second)]


@dataclass(frozen=True)
class ReviewedOverlap:
    """Annotate one detected overlap with its approval state.

    `pair` is set exactly when the overlap can be approved or unapproved;
    otherwise `reasons` explains what blocks approval.
    """

    overlap: ClockOverlap
    status: OverlapStatus
    pair: OverlapPair | None
    reasons: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        """Return the dashboard JSON form of this overlap."""
        return {
            "a": asdict(self.overlap.a),
            "b": asdict(self.overlap.b),
            "status": self.status,
            "pair": None if self.pair is None else self.pair.to_json(),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class OverlapReview:
    """Hold reviewed overlaps and whether approvals can currently change."""

    enabled: bool
    message: str | None
    overlaps: tuple[ReviewedOverlap, ...]


def clock_identity(clock: OverlapClock) -> ClockIdentity | None:
    """Return the persistent identity of CLOCK, or `None` if it has none yet."""
    if clock.org_id is None or clock.end is None:
        return None
    return ClockIdentity(org_id=clock.org_id, start=clock.start, end=clock.end)


def review_overlaps(
    overlaps: Sequence[ClockOverlap],
    approved: frozenset[OverlapPair],
) -> tuple[ReviewedOverlap, ...]:
    """Classify each overlap as approved, unapproved, or blocked from approval."""
    # Identical identities always overlap each other, so every clock sharing an
    # identity appears in OVERLAPS; counting distinct locations finds them all.
    locations: dict[ClockIdentity, set[tuple[str, int]]] = defaultdict(set)
    for overlap in overlaps:
        for clock in (overlap.a, overlap.b):
            identity = clock_identity(clock)
            if identity is not None:
                locations[identity].add((clock.file, clock.line))

    reviewed: list[ReviewedOverlap] = []
    for overlap in overlaps:
        reasons: list[str] = []
        for label, clock in (("Task A", overlap.a), ("Task B", overlap.b)):
            if clock.org_id is None:
                reasons.append(f"{label} needs an Org ID")
            if clock.end is None:
                reasons.append(f"{label} clock is still open")
            identity = clock_identity(clock)
            if identity is not None and len(locations[identity]) > 1:
                reasons.append(f"{label} shares its Org ID and interval with another clock")

        identity_a = clock_identity(overlap.a)
        identity_b = clock_identity(overlap.b)
        if reasons or identity_a is None or identity_b is None:
            reviewed.append(ReviewedOverlap(overlap, "blocked", None, tuple(reasons)))
            continue
        pair = OverlapPair.of(identity_a, identity_b)
        status: OverlapStatus = "approved" if pair in approved else "unapproved"
        reviewed.append(ReviewedOverlap(overlap, status, pair, ()))
    return tuple(reviewed)


class ApprovalStore:
    """Read and atomically update the approval JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_lock = Lock()

    def load(self) -> frozenset[OverlapPair]:
        """Return the approved pairs without modifying the file."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return frozenset()
        except OSError as error:
            raise ApprovalStoreError(f"Could not read {self.path}: {error}") from error
        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise ApprovalStoreError(f"{self.path} is not valid JSON: {error}") from error
        return self._parse_document(document)

    def set_approved(self, pair: OverlapPair, approved: bool) -> None:
        """Approve or unapprove PAIR, writing only when the state changes."""
        with self._write_lock:
            current = self.load()
            updated = current | {pair} if approved else current - {pair}
            if updated != current:
                self._write(updated)

    def _parse_document(self, document: object) -> frozenset[OverlapPair]:
        if not isinstance(document, dict) or set(document) != _DOCUMENT_KEYS:
            raise ApprovalStoreError(
                f"{self.path} must be a JSON object with exactly 'version' and 'approved_overlaps'."
            )
        version = document["version"]
        if isinstance(version, bool) or version != SCHEMA_VERSION:
            raise ApprovalStoreError(
                f"{self.path} has unsupported version {version!r}; expected {SCHEMA_VERSION}."
            )
        entries = document["approved_overlaps"]
        if not isinstance(entries, list):
            raise ApprovalStoreError(f"{self.path}: 'approved_overlaps' must be a list.")
        pairs: set[OverlapPair] = set()
        for index, entry in enumerate(entries):
            try:
                pairs.add(OverlapPair.from_json(entry))
            except ValueError as error:
                raise ApprovalStoreError(
                    f"{self.path}: approved_overlaps[{index}] is invalid: {error}"
                ) from error
        return frozenset(pairs)

    def _write(self, pairs: frozenset[OverlapPair]) -> None:
        document = {
            "version": SCHEMA_VERSION,
            "approved_overlaps": [pair.to_json() for pair in sorted(pairs)],
        }
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        try:
            # Create only the immediate parent so a mistyped path fails loudly.
            self.path.parent.mkdir(exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                temp_path.replace(self.path)
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        except OSError as error:
            raise ApprovalStoreError(f"Could not write {self.path}: {error}") from error


class OverlapApprovals:
    """Combine the approval store with the most recently detected overlaps."""

    def __init__(self, store: ApprovalStore | None, disabled_message: str | None = None) -> None:
        self._store = store
        self._disabled_message = disabled_message or "Overlap approval is disabled."
        # Replaced wholesale by each review, so readers always see one snapshot.
        self._approvable: frozenset[OverlapPair] = frozenset()

    @classmethod
    def from_settings(cls, configured_file: str | None, environ: Mapping[str, str]) -> Self:
        """Configure the store from the environment override or the YAML setting.

        A nonempty `ORG_TIMEVIZ_OVERLAP_APPROVALS_FILE` takes precedence over
        CONFIGURED_FILE, the `app.overlap_approvals_file` setting.
        """
        source = APPROVALS_FILE_ENV_VAR
        value = environ.get(APPROVALS_FILE_ENV_VAR, "").strip()
        if not value:
            source = APPROVALS_FILE_SETTING
            value = (configured_file or "").strip()
        if not value:
            return cls(
                None,
                f"Overlap approval is disabled. Set {APPROVALS_FILE_SETTING} in the config "
                f"file (or the {APPROVALS_FILE_ENV_VAR} environment variable) to an approval "
                "JSON file outside this repository and restart the server.",
            )
        try:
            path = Path(value).expanduser()
        except RuntimeError:  # `~user` for an unknown user stays relative.
            path = Path(value)
        if not path.is_absolute():
            return cls(
                None,
                f"Overlap approval is disabled: {source} must be an absolute path, not {value!r}.",
            )
        return cls(ApprovalStore(path))

    @property
    def store_path(self) -> Path | None:
        """Return the configured approval file, if any."""
        return None if self._store is None else self._store.path

    @property
    def disabled_message(self) -> str | None:
        """Explain why approvals are not configured, or return `None`."""
        return self._disabled_message if self._store is None else None

    def review(self, overlaps: Sequence[ClockOverlap]) -> OverlapReview:
        """Annotate OVERLAPS with approval state and remember which are approvable."""
        message: str | None = None
        approved: frozenset[OverlapPair] = frozenset()
        if self._store is None:
            message = self._disabled_message
        else:
            try:
                approved = self._store.load()
            except ApprovalStoreError as error:
                message = f"Overlap approvals are unavailable: {error}"

        reviewed = review_overlaps(overlaps, approved)
        self._approvable = frozenset(item.pair for item in reviewed if item.pair is not None)
        return OverlapReview(enabled=message is None, message=message, overlaps=reviewed)

    def set_approved(self, pair: OverlapPair, approved: bool) -> None:
        """Persist an approval change for a pair from the latest review."""
        if self._store is None:
            raise OverlapApprovalError(self._disabled_message)
        if approved and pair not in self._approvable:
            raise OverlapApprovalError(
                "This pair is not among the currently detected approvable overlaps; "
                "refresh the clock dashboard and try again."
            )
        self._store.set_approved(pair, approved)
