# Org parsing and configuration safety

## Audit and API verification

Verified against the installed Emacs 30.1 / Org 9.7.11, including inspection of
`org-element-clock-parser` and synthetic batch probes. Other Org versions are
not yet covered by a compatibility matrix.

| Previous interpretation | Replacement |
| --- | --- |
| Python parenthesis/string/comment scanner for Lisp `setq` | Evaluate trusted configuration in `emacs --batch -Q`, retrieve effective values with `org-agenda-files` |
| Lisp reader walking only literal TODO `setq` forms | Evaluate configuration separately; obtain normalized `org-todo-keywords-1` from Org mode |
| Regex extraction of CLOCK timestamps in the JSONL exporter | `org-element-parse-buffer`, `org-element-map`, `org-element-property`, `org-timestamp-to-time` |
| Personal timestamp collectors and repeated daily file scans in dashboard | Same native extraction; reuse intervals for each day and week |
| Constructed heading links followed by regex description extraction | Retrieve headings with `org-get-heading`; display embedded links with `org-link-display-format` |
| Custom declared-duration interpretation | `org-duration-to-minutes` |

A detail verified experimentally: Org marks a clock without a declared duration
as `running` even if its timestamp contains both endpoints. The timestamp's
range type, rather than that status alone, determines whether it is open.
Approval identities use the timestamp's local component properties, not an epoch
round-trip: heading's **own** Org ID plus start/end `YYYY-MM-DDTHH:MM`. No IDs are
created. Files, line numbers, labels and archive locations remain display-only.

## Retained application logic

Time aggregation, clipping, bucket/tag classification, overlap and duplicate
checks, approvals, and text rendering are application logic, not Org parsing.
They remain in org-timeviz. Live dashboard clocks use a single captured current
time. Static JSONL exports still exclude open clocks.

Archive context reconstruction remains: `org-entry-get`, `org-get-tags`,
`org-get-category`, `org-get-heading`, and `org-up-heading-safe` interpret Org
structure. The application combines `ARCHIVE_OLPATH`, `ARCHIVE_ITAGS` and
`ARCHIVE_CATEGORY` with the current subtree. Org's current outline/tag APIs do
not reconstruct its former hierarchy after archiving. Splitting those stored
property values uses Org's documented slash/space serialization, not a second
heading parser. Archived tags are deduplicated as before.

A raw `CLOCK:` prefix scan is intentionally retained **only for diagnostics**.
Malformed lines may be absent from the element tree, or Org may recognize only
the first timestamp of a broken line. Unconsumed text after a single timestamp
is flagged, not treated as a live clock. No fallback timestamp extraction or
malformed-clock repair parser exists. Suspicious-clock descriptions for malformed
input are now generic rather than the personal helper's timestamp-count or
separator-specific messages. Native duration parse failures are diagnostic, not
fatal. Recoverable-looking malformed lines are not guessed into totals/overlaps;
this is an intentional limitation of delegating interpretation to Org.

## Configuration evaluation trust boundary

The configuration process loads only the selected configured init (and whatever
that init explicitly loads/requires). It does not run normal Emacs startup.
Candidate order matters: the first nonempty agenda list wins; custom agenda
variables support work/personal selection. The default puts the Org-only module
first to avoid evaluating the full UI/package init unnecessarily. An existing
but broken init is an error, not grounds to silently substitute a different
agenda list. A 30-second timeout prevents indefinitely waiting for interactive
configuration. Explicit mode keeps its explicit paths; a configured init may
still be evaluated for TODO keyword data, without using its agenda file list.

**This is not safe evaluation of untrusted Lisp.** A separate process is not a
sandbox: top-level configuration can write files, launch programs or contact the
network. Use only trusted, batch-compatible configuration. GUI-only initialization,
startup assumptions, missing packages, and configuration that itself visits or
modifies Org files cannot be made safe by this mechanism; use explicit mode with
an empty `emacs_init_paths` list if necessary. No source-file reading operation
requires loading a user's configuration into its own process.

Only JSON data passes to the reader processes. They insert source files into
temporary buffers, suppress `org-mode-hook` and Org startup actions, do not visit
files, evaluate local variables, save buffers, resolve clocks, or generate IDs.
Automatic adjacent archive discovery remains in Python and is unchanged.

## Regression evidence

The initial suite passed 171 tests, with 91.28% Python coverage. A synthetic
characterization test was run before CLOCK replacement. Additional read-only
inspection of the personal helper definitions exposed differences from the old
test stand-ins: real dashboard totals include open clocks and clip each day at
23:59:59. Only the relevant helper definitions were evaluated in a temporary
baseline harness, against synthetic files, with the original exporter from
`master`; no personal Org files or full user configuration were evaluated.
Captured midnight totals (`1:30` daily, `1:59` weekly) are now fixed assertions.
A further synthetic comparison produced identical JSONL records/metadata and,
for ordinary headings, an identical complete dashboard payload from the old and
new exporters. It also exposed and fixed chronological tie ordering: equal
clipped starts retain input file order and descending source-line order.
No deprecated parser or personal helper implementation remains in the test suite.

Tests cover closed/open clocks, durationless ranges, malformed lines, duration
mismatches and tolerance, multiple clocks per heading, duplicate and overlapping
intervals, source lines/IDs, progress cookies, brackets and embedded links,
computed agenda lists, work/personal selection, `.emacs` requiring `init-org.el`,
invalid/missing configuration, TODO normalization, and source-file immutability.
Existing real-Org archive tests continue to compare daily/bucket totals, monthly
reports, raw-tag series, generated report bytes, overlap identity and persisted
approvals before and after archiving, including stale-copy detection. Additional
checks cover same-start chronological ordering and identity components across
timezones and a DST transition.

Validation uses `make code-quality` (Ruff, ty, strict mypy, warnings-as-errors
Emacs Lisp compilation, pytest with coverage). `make run` and `make serve` are
smoke-tested with temporary configurations and synthetic Org files, not the
personal defaults. Python coverage does not measure Lisp branches; the Lisp
integration cases run actual batch Emacs processes. Final validation passed all
185 tests with 91.38% Python coverage, all code-quality checks, and both target
smoke tests (including an HTTP request to the live clock-dashboard endpoint).
