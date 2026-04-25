"""Define and validate YAML configuration for report generation."""

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, Field, model_validator


def _ensure_unique(values: list[str], field_name: str) -> None:
    """Validate that a list contains unique values."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    if duplicates:
        raise ValueError(
            f"{field_name} must contain unique values; duplicates: {sorted(duplicates)}"
        )


def _ensure_known_buckets(
    bucket_names: list[str],
    known_buckets: set[str],
    field_name: str,
) -> None:
    """Validate that all referenced buckets are known."""
    unknown = sorted(set(bucket_names) - known_buckets)
    if unknown:
        raise ValueError(f"{field_name} contains unknown bucket names: {unknown}")


def _ensure_positive_weights(
    weights: dict[str, float],
    field_name: str,
) -> None:
    """Validate that all configured weights are positive."""
    bad_keys = sorted(bucket_name for bucket_name, value in weights.items() if value <= 0.0)
    if bad_keys:
        raise ValueError(f"{field_name} must contain only positive values; bad keys: {bad_keys}")


class _BaseConfig(BaseModel):
    """Validate YAML configuration with a strict schema."""

    model_config = {"extra": "forbid"}

    @classmethod
    def validate_model(cls, data: Any) -> "_BaseConfig":
        """Validate data into the model."""
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, path: Path) -> "_BaseConfig":
        """Load YAML file and validate."""
        with path.open("r", encoding="utf-8") as file_handle:
            raw = yaml.safe_load(file_handle) or {}
        return cls.validate_model(raw)


class AppSettings(_BaseConfig):
    """Hold global application settings."""

    output_dir: str = Field(default="outputs")
    log_level: str = Field(default="INFO")


class OrgSourcesConfig(_BaseConfig):
    """Describe how to locate Org files for reporting."""

    mode: Literal["emacs", "explicit"] = Field(default="emacs")
    emacs_init_paths: list[str] = Field(default_factory=list)
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


class TimeBucketRuleConfig(_BaseConfig):
    """Describe one rule for resolving ambiguous time-bucket tags."""

    name: str = Field(default="")
    match_all_tags: list[str] = Field(default_factory=list)
    match_all_buckets: list[str] = Field(default_factory=list)
    strategy: Literal["priority", "split_weighted"]
    priority_order: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        """Validate one time-bucket resolution rule."""
        if not self.match_all_tags and not self.match_all_buckets:
            raise ValueError(
                "Time bucket rule must define match_all_tags and/or match_all_buckets."
            )

        _ensure_unique(
            self.match_all_tags,
            "time_buckets.resolution.rules.match_all_tags",
        )
        _ensure_unique(
            self.match_all_buckets,
            "time_buckets.resolution.rules.match_all_buckets",
        )
        _ensure_unique(
            self.priority_order,
            "time_buckets.resolution.rules.priority_order",
        )
        _ensure_positive_weights(
            self.weights,
            "time_buckets.resolution.rules.weights",
        )

        if self.strategy == "priority" and not self.priority_order:
            raise ValueError("Priority time bucket rule requires priority_order.")

        return self


class TimeBucketResolutionConfig(_BaseConfig):
    """Describe default and rule-based time-bucket resolution."""

    default_strategy: Literal["priority", "split_weighted"] = Field(default="priority")
    priority_order: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    rules: list[TimeBucketRuleConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        """Validate default time-bucket resolution settings."""
        _ensure_unique(
            self.priority_order,
            "time_buckets.resolution.priority_order",
        )
        _ensure_positive_weights(
            self.weights,
            "time_buckets.resolution.weights",
        )

        if self.default_strategy == "priority" and not self.priority_order:
            raise ValueError("Priority time bucket resolution requires priority_order.")

        return self


class TimeBucketsConfig(_BaseConfig):
    """Describe project-wide time-bucket configuration."""

    other_bucket: str
    bucket_order: list[str]
    tag_to_bucket: dict[str, str]
    resolution: TimeBucketResolutionConfig = Field(default_factory=TimeBucketResolutionConfig)

    @model_validator(mode="after")
    def validate_time_buckets(self) -> Self:
        """Validate project-wide time-bucket settings."""
        _ensure_unique(self.bucket_order, "time_buckets.bucket_order")

        known_buckets = set(self.bucket_order)
        if not known_buckets:
            raise ValueError("time_buckets.bucket_order must not be empty.")

        if self.other_bucket not in known_buckets:
            raise ValueError(
                f"time_buckets.other_bucket={self.other_bucket!r} "
                "must exist in time_buckets.bucket_order."
            )

        _ensure_known_buckets(
            list(self.tag_to_bucket.values()),
            known_buckets,
            "time_buckets.tag_to_bucket",
        )
        _ensure_known_buckets(
            self.resolution.priority_order,
            known_buckets,
            "time_buckets.resolution.priority_order",
        )
        _ensure_known_buckets(
            list(self.resolution.weights.keys()),
            known_buckets,
            "time_buckets.resolution.weights",
        )

        for rule in self.resolution.rules:
            _ensure_known_buckets(
                rule.match_all_buckets,
                known_buckets,
                "time_buckets.resolution.rules.match_all_buckets",
            )
            _ensure_known_buckets(
                rule.priority_order,
                known_buckets,
                "time_buckets.resolution.rules.priority_order",
            )
            _ensure_known_buckets(
                list(rule.weights.keys()),
                known_buckets,
                "time_buckets.resolution.rules.weights",
            )

        return self


class ReportsConfig(_BaseConfig):
    """Hold shared configuration for all generated reports."""

    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    plots: PlotsConfig = Field(default_factory=PlotsConfig)


class AppConfig(_BaseConfig):
    """Describe full app configuration."""

    app: AppSettings = Field(default_factory=AppSettings)
    org_sources: OrgSourcesConfig = Field(default_factory=OrgSourcesConfig)
    time_buckets: TimeBucketsConfig
    reports: ReportsConfig = Field(default_factory=ReportsConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "AppConfig":
        """Load, parse, and validate configuration from YAML."""
        with path.open("r", encoding="utf-8") as file_handle:
            raw = yaml.safe_load(file_handle) or {}
        return cls.validate_model(raw)  # type: ignore[return-value]
