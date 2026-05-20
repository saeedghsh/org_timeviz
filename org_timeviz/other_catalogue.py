"""Generate a CSV catalogue of unmapped tags contributing to the other bucket."""

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from .config import AppConfig
from .emacs_agenda import read_agenda_files_from_emacs_init
from .emacs_batch import parse_org_clock_records_emacs
from .filters import ClippedRecord, apply_filters, clip_to_window
from .logging_utils import setup_logger
from .models import ClockRecord
from .time_bucket_resolver import resolve_time_bucket_allocations
from .time_windows import TimeWindow, at_midnight

_LOG = logging.getLogger(__name__)
NO_TAG_LABEL = "(no-tag)"
OUTPUT_FILENAME = "other_catalogue.csv"


@dataclass(frozen=True)
class OrgInputs:
    """Hold resolved Org files and the Emacs init path used for discovery."""

    org_files: list[Path]
    agenda_init_path: Path | None


def generate_other_catalogue(cfg: AppConfig) -> Path:
    """Write a CSV of unmapped tags contributing to the other time bucket."""
    inputs = _resolve_org_inputs(cfg)
    _LOG.info("Using %s org file(s)", len(inputs.org_files))

    _set_emacs_init_env(cfg, inputs.agenda_init_path)

    records = parse_org_clock_records_emacs(org_files=inputs.org_files)
    out_root = Path(cfg.app.output_dir).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / OUTPUT_FILENAME

    if not records:
        _LOG.warning("No clock records found.")
        _write_other_catalogue_csv({}, out_path)
        return out_path

    filtered_records = _filter_all_time_records(cfg, records)
    hours_by_tag = _compute_other_catalogue_hours(cfg, filtered_records)
    _write_other_catalogue_csv(hours_by_tag, out_path)
    return out_path


def _filter_all_time_records(
    cfg: AppConfig,
    records: list[ClockRecord],
) -> list[ClippedRecord]:
    """Clip and filter records over their full available time span."""
    window = TimeWindow(
        name="all_time",
        start=at_midnight(min(record.start for record in records)),
        end=at_midnight(max(record.end for record in records)) + timedelta(days=1),
    )
    clipped = clip_to_window(records, window=window)
    return apply_filters(clipped, cfg=cfg.reports.filters)


def _resolve_org_inputs(cfg: AppConfig) -> OrgInputs:
    """Resolve Org files from explicit paths or configured Emacs agenda files."""
    if cfg.org_sources.mode == "explicit":
        org_files = [Path(path_str).expanduser() for path_str in cfg.org_sources.explicit_files]
        agenda_init_path = _first_existing_init_path(cfg.org_sources.emacs_init_paths)
        return OrgInputs(org_files=org_files, agenda_init_path=agenda_init_path)

    for path_str in cfg.org_sources.emacs_init_paths:
        init_path = Path(path_str).expanduser()
        result = read_agenda_files_from_emacs_init(
            init_path,
            var_name=cfg.org_sources.emacs_agenda_var,
        )
        if result is not None and result.files:
            return OrgInputs(org_files=result.files, agenda_init_path=result.source_path)

    raise FileNotFoundError(
        "Could not find org-agenda-files in any of: " + ", ".join(cfg.org_sources.emacs_init_paths)
    )


def _first_existing_init_path(paths: list[str]) -> Path | None:
    """Return the first existing Emacs init path from a configured list."""
    for path_str in paths:
        path_obj = Path(path_str).expanduser()
        if path_obj.exists():
            return path_obj
    return None


def _set_emacs_init_env(cfg: AppConfig, preferred_init_path: Path | None) -> None:
    """Set the init-file environment variable used by the Emacs batch exporter."""
    candidates: list[Path] = []
    if preferred_init_path is not None:
        candidates.append(preferred_init_path)

    for path_str in cfg.org_sources.emacs_init_paths:
        path_obj = Path(path_str).expanduser()
        if path_obj.exists() and path_obj not in candidates:
            candidates.append(path_obj)

    for init_path in candidates:
        if init_path.exists():
            os.environ["ORG_TIMEVIZ_EMACS_INIT"] = str(init_path)
            os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)
            return

    os.environ.pop("ORG_TIMEVIZ_EMACS_INIT", None)
    os.environ.pop("ORG_TIMEVIZ_TODO_KEYWORDS", None)


def _compute_other_catalogue_hours(
    cfg: AppConfig,
    records: list[ClippedRecord],
) -> dict[str, float]:
    """Compute hours by unmapped tag for records resolved to the other bucket."""
    minutes_by_tag: dict[str, int] = {}
    known_tags = set(cfg.time_buckets.tag_to_bucket)
    other_bucket = cfg.time_buckets.other_bucket

    for record in records:
        allocations = resolve_time_bucket_allocations(
            record.record.tags,
            cfg.time_buckets,
        )
        if allocations != {other_bucket: 1.0}:
            continue

        unmapped_tags = [tag_name for tag_name in record.record.tags if tag_name not in known_tags]
        if not unmapped_tags:
            unmapped_tags = [NO_TAG_LABEL]

        for tag_name in unmapped_tags:
            minutes_by_tag[tag_name] = minutes_by_tag.get(tag_name, 0) + record.minutes

    return {
        tag_name: minutes / 60.0
        for tag_name, minutes in sorted(
            minutes_by_tag.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    }


def _write_other_catalogue_csv(hours_by_tag: dict[str, float], out_path: Path) -> None:
    """Write the other catalogue CSV."""
    with out_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(["tag", "hours"])
        for tag_name, hours in hours_by_tag.items():
            writer.writerow([tag_name, f"{hours:.2f}"])


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m org_timeviz.other_catalogue",
        description="Generate a CSV of unmapped Org tags contributing to the other time bucket.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/default.yaml"),
        help="Path to YAML config file.",
    )
    return parser.parse_args(argv)


def _main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)
    config_path = args.config.expanduser().resolve()
    cfg = AppConfig.from_yaml(config_path)

    setup_logger(level=cfg.app.log_level)
    _LOG.info("Loaded config from %s", config_path)

    output_path = generate_other_catalogue(cfg)
    _LOG.info("Wrote other catalogue to %s", output_path)

    return os.EX_OK


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
