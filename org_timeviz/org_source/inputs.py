"""Resolve configured Org sources and prepare the Emacs batch environment."""

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import AppConfig
from .agenda import read_agenda_files_from_emacs_init

# Org's default `org-archive-location` ("%s_archive::") archives to this file.
_ARCHIVE_SUFFIX = "_archive"


@dataclass(frozen=True)
class OrgInputs:
    """Hold resolved Org files and the Emacs init path used for discovery."""

    org_files: list[Path]
    agenda_init_path: Path | None


def resolve_org_inputs(cfg: AppConfig) -> OrgInputs:
    """Resolve configured Org files, each followed by its existing archive file."""
    if cfg.org_sources.mode == "explicit":
        org_files = [Path(path_str).expanduser() for path_str in cfg.org_sources.explicit_files]
        return OrgInputs(
            org_files=_with_archive_files(org_files),
            agenda_init_path=_first_existing_init_path(cfg.org_sources.emacs_init_paths),
        )

    for path_str in cfg.org_sources.emacs_init_paths:
        init_path = Path(path_str).expanduser()
        result = read_agenda_files_from_emacs_init(
            init_path,
            var_name=cfg.org_sources.emacs_agenda_var,
        )
        if result is not None and result.files:
            return OrgInputs(
                org_files=_with_archive_files(result.files),
                agenda_init_path=result.source_path,
            )

    raise FileNotFoundError(
        "Could not find org-agenda-files in any of: " + ", ".join(cfg.org_sources.emacs_init_paths)
    )


def configure_emacs_init(cfg: AppConfig, preferred_init_path: Path | None) -> None:
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


def _with_archive_files(org_files: list[Path]) -> list[Path]:
    """Add each file's archive when it exists, dropping paths that repeat a file."""
    unique: dict[Path, Path] = {}
    for org_file in org_files:
        unique.setdefault(org_file.resolve(), org_file)
        archive = org_file.with_name(org_file.name + _ARCHIVE_SUFFIX)
        if archive.is_file():
            unique.setdefault(archive.resolve(), archive)
    return list(unique.values())


def _first_existing_init_path(paths: list[str]) -> Path | None:
    for path_str in paths:
        path_obj = Path(path_str).expanduser()
        if path_obj.exists():
            return path_obj
    return None
