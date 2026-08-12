from pathlib import Path

import pytest
from pydantic import ValidationError

from org_timeviz.config import AppConfig, TimeBucketsConfig


def _base_time_buckets() -> dict[str, object]:
    return {
        "other_bucket": "other",
        "bucket_order": ["a", "b", "other"],
        "tag_to_bucket": {"tag_a": "a", "tag_b": "b"},
        "resolution": {
            "default_strategy": "priority",
            "priority_order": ["a", "b", "other"],
            "weights": {},
            "rules": [],
        },
    }


def test_app_config_loads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
time_buckets:
  other_bucket: other
  bucket_order: [work, other]
  tag_to_bucket: {job: work}
  resolution:
    default_strategy: priority
    priority_order: [work, other]
""",
        encoding="utf-8",
    )
    cfg = AppConfig.from_yaml(path)
    assert cfg.app.output_dir == "outputs"
    assert cfg.reports.plots.top_k_tasks == 25
    assert cfg.time_buckets.tag_to_bucket == {"job": "work"}


def test_extra_config_fields_are_rejected() -> None:
    data = _base_time_buckets()
    data["unexpected"] = True
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bucket_order", ["a", "a", "other"]),
        ("other_bucket", "missing"),
    ],
)
def test_invalid_bucket_definition_is_rejected(field: str, value: object) -> None:
    data = _base_time_buckets()
    data[field] = value
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


def test_unknown_mapped_bucket_is_rejected() -> None:
    data = _base_time_buckets()
    data["tag_to_bucket"] = {"tag_a": "missing"}
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


def test_priority_resolution_requires_order() -> None:
    data = _base_time_buckets()
    data["resolution"] = {"default_strategy": "priority", "priority_order": []}
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


def test_nonpositive_weights_are_rejected() -> None:
    data = _base_time_buckets()
    data["resolution"] = {
        "default_strategy": "split_weighted",
        "priority_order": [],
        "weights": {"a": 0},
    }
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


def test_rule_requires_match_condition() -> None:
    data = _base_time_buckets()
    data["resolution"] = {
        "default_strategy": "priority",
        "priority_order": ["a", "b", "other"],
        "rules": [{"strategy": "split_weighted"}],
    }
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)


def test_rule_rejects_unknown_bucket_reference() -> None:
    data = _base_time_buckets()
    data["resolution"] = {
        "default_strategy": "priority",
        "priority_order": ["a", "b", "other"],
        "rules": [
            {
                "match_all_tags": ["tag_a", "tag_b"],
                "strategy": "priority",
                "priority_order": ["missing"],
            }
        ],
    }
    with pytest.raises(ValidationError):
        TimeBucketsConfig.model_validate(data)
