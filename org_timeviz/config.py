"""Define and validate YAML configuration for report generation."""

from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field


class _BaseConfig(BaseModel):
    """Validate config."""

    model_config: ClassVar[dict[str, Any]] = {"extra": "forbid"}

    @classmethod
    def validate_model(cls, data: Any) -> "_BaseConfig":
        """Validate data into model."""
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: Path) -> "_BaseConfig":
        """Load config from YAML file and validate."""
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.validate_model(raw)


class AppSettings(_BaseConfig):
    """Hold app settings."""

    output_dir: str = Field(default="outputs")
    log_level: str = Field(default="INFO")


class OrgSourcesConfig(_BaseConfig):
    """Describe how to locate Org files."""

    mode: Literal["emacs", "explicit"] = Field(default="emacs")
    emacs_init_paths: list[str] = Field(default_factory=lambda: ["~/.emacs", "~/.emacs.d/init.el"])
    emacs_agenda_var: str = Field(default="org-agenda-files")
    explicit_files: list[str] = Field(default_factory=list)


class PeriodLastNDays(_BaseConfig):
    """Describe a relative period."""

    kind: Literal["last_n_days"]
    name: str
    n: int = Field(ge=1)
    align_to_day_boundary: bool = Field(default=True)


class PeriodRange(_BaseConfig):
    """Describe an absolute date range (inclusive end_date)."""

    kind: Literal["range"]
    name: str
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD


class PeriodThisWeek(_BaseConfig):
    """Describe the current ISO week (Mon..Mon)."""

    kind: Literal["this_week"]
    name: str = Field(default="this_week")


class PeriodThisMonth(_BaseConfig):
    """Describe the current month (1st..1st)."""

    kind: Literal["this_month"]
    name: str = Field(default="this_month")


PeriodConfig = PeriodLastNDays | PeriodRange | PeriodThisWeek | PeriodThisMonth


class FiltersConfig(_BaseConfig):
    """Filter records."""

    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    tag_match_mode: Literal["any", "all"] = Field(default="any")

    include_task_regex: list[str] = Field(default_factory=list)
    exclude_task_regex: list[str] = Field(default_factory=list)


class PlotConfig(_BaseConfig):
    """Describe a plot to generate."""

    kind: Literal["bar_by_tag", "bar_by_task", "timeseries_daily_total"]
    top_k: int = Field(default=25, ge=1)
    rolling_days: int = Field(default=1, ge=1)


class ReportConfig(_BaseConfig):
    """Describe one report."""

    name: str
    period: str
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    plots: list[PlotConfig] = Field(default_factory=list)


class AppConfig(_BaseConfig):
    """Describe full app configuration."""

    app: AppSettings = Field(default_factory=AppSettings)
    org_sources: OrgSourcesConfig = Field(default_factory=OrgSourcesConfig)
    periods: list[PeriodConfig] = Field(default_factory=list)
    reports: list[ReportConfig] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "AppConfig":
        """Load app config from YAML file and validate."""
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls.validate_model(raw)  # type: ignore[return-value]
