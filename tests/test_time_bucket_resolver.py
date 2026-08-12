import pytest

from org_timeviz.config import TimeBucketsConfig
from org_timeviz.time_bucket_resolver import resolve_time_bucket_allocations


def test_unmapped_tags_go_to_other(bucket_cfg: TimeBucketsConfig) -> None:
    assert resolve_time_bucket_allocations(("unknown",), bucket_cfg) == {"other": 1.0}


def test_single_mapped_tag_uses_its_bucket(bucket_cfg: TimeBucketsConfig) -> None:
    assert resolve_time_bucket_allocations(("course",), bucket_cfg) == {"study": 1.0}


def test_priority_uses_configured_order(bucket_cfg: TimeBucketsConfig) -> None:
    assert resolve_time_bucket_allocations(("course", "job"), bucket_cfg) == {"work": 1.0}


def test_split_weighted_normalizes_weights() -> None:
    cfg = TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["a", "b", "other"],
            "tag_to_bucket": {"x": "a", "y": "b"},
            "resolution": {
                "default_strategy": "split_weighted",
                "weights": {"a": 3, "b": 1},
            },
        }
    )
    assert resolve_time_bucket_allocations(("x", "y"), cfg) == pytest.approx({"a": 0.75, "b": 0.25})


def test_split_weighted_defaults_to_equal_weights() -> None:
    cfg = TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["a", "b", "other"],
            "tag_to_bucket": {"x": "a", "y": "b"},
            "resolution": {"default_strategy": "split_weighted"},
        }
    )
    assert resolve_time_bucket_allocations(("x", "y"), cfg) == pytest.approx({"a": 0.5, "b": 0.5})


def test_first_matching_rule_overrides_default() -> None:
    cfg = TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["a", "b", "other"],
            "tag_to_bucket": {"x": "a", "y": "b"},
            "resolution": {
                "default_strategy": "priority",
                "priority_order": ["a", "b", "other"],
                "rules": [
                    {
                        "match_all_tags": ["x", "y"],
                        "strategy": "split_weighted",
                        "weights": {"a": 1, "b": 3},
                    }
                ],
            },
        }
    )
    assert resolve_time_bucket_allocations(("x", "y"), cfg) == pytest.approx({"a": 0.25, "b": 0.75})


def test_priority_falls_back_to_configured_bucket_order_when_priority_omits_matches() -> None:
    cfg = TimeBucketsConfig.model_validate(
        {
            "other_bucket": "other",
            "bucket_order": ["a", "b", "other"],
            "tag_to_bucket": {"x": "a", "y": "b"},
            "resolution": {
                "default_strategy": "priority",
                "priority_order": ["other"],
            },
        }
    )
    assert resolve_time_bucket_allocations(("x", "y"), cfg) == {"a": 1.0}
