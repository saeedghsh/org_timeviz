"""Define and validate YAML configuration for report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field


class _BaseConfig(BaseModel):
    """Validate YAML configuration with a strict schema."""

    model_config: ClassVar[dict[str, Any]] = {"extra": "forbid"}

    @classmethod
    def validate_model(cls, data: Any) -> "_BaseConfig":
        """Validate data into the model."""
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: Path) -> "_BaseConfig":
        """Load YAML file and validate."""
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.validate_model(raw)


class AppSettings(_BaseConfig):
    """Hold global application settings."""

    output_dir: str = Field(default="outputs")
    log_level: str = Field(default="INFO")


class OrgSourcesConfig(_BaseConfig):
    """Describe how to locate Org files for reporting."""

    mode: Literal["emacs", "explicit"] = Field(default="emacs")
    emacs_init_paths: list[str] = Field(
        default_factory=lambda: ["~/.emacs", "~/.emacs.d/init.el"]
    )
    emacs_agenda_var: str = Field(default="org-agenda-files")
    explicit_files: list[str] = Field(default_factory=list)


class FiltersConfig(_BaseConfig):
    """Describe filters applied before aggregation."""

    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    tag_match_mode: Literal["any", "all"] = Field(default="any")

    include_task_regex: list[str] = Field(default_factory=list)
    exclude_task_regex: list[str] = Field(default_factory=list)


class PlotsConfig(_BaseConfig):
    """Hold plot settings shared by all generated reports."""

    top_k_tasks: int = Field(default=25, ge=1)
    top_k_tags: int = Field(default=25, ge=1)

    # If null, timeseries spans the full data range.
    timeseries_last_n_days: int | None = Field(default=None)

    timeseries_rolling_days: int = Field(default=7, ge=1)


class ReportsConfig(_BaseConfig):
    """Hold shared configuration for all generated reports."""

    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    plots: PlotsConfig = Field(default_factory=PlotsConfig)


class AppConfig(_BaseConfig):
    """Describe full app configuration."""

    app: AppSettings = Field(default_factory=AppSettings)
    org_sources: OrgSourcesConfig = Field(default_factory=OrgSourcesConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "AppConfig":
        """Load, parse, and validate configuration from YAML."""
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.validate_model(raw)  # type: ignore[return-value]
