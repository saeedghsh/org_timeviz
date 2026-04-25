"""Resolve time-bucket allocations from raw task tags."""

from .config import TimeBucketRuleConfig, TimeBucketsConfig


def resolve_time_bucket_allocations(
    tags: tuple[str, ...],
    cfg: TimeBucketsConfig,
) -> dict[str, float]:
    """Resolve raw tags into reporting allocations across time buckets."""
    tag_set = set(tags)
    matched_buckets = _matched_buckets_from_tags(tag_set, cfg)

    if not matched_buckets:
        return {cfg.other_bucket: 1.0}

    if len(matched_buckets) == 1:
        return {matched_buckets[0]: 1.0}

    matched_bucket_set = set(matched_buckets)

    for rule in cfg.resolution.rules:
        if _rule_matches(rule, tag_set, matched_bucket_set):
            return _apply_strategy(
                matched_buckets=matched_buckets,
                strategy=rule.strategy,
                priority_order=rule.priority_order or cfg.resolution.priority_order,
                weights=rule.weights or cfg.resolution.weights,
            )

    return _apply_strategy(
        matched_buckets=matched_buckets,
        strategy=cfg.resolution.default_strategy,
        priority_order=cfg.resolution.priority_order,
        weights=cfg.resolution.weights,
    )


def _matched_buckets_from_tags(
    tag_set: set[str],
    cfg: TimeBucketsConfig,
) -> list[str]:
    """Map raw tags to canonical buckets in configured bucket order."""
    mapped = {cfg.tag_to_bucket[tag_name] for tag_name in tag_set if tag_name in cfg.tag_to_bucket}
    return [bucket_name for bucket_name in cfg.bucket_order if bucket_name in mapped]


def _rule_matches(
    rule: TimeBucketRuleConfig,
    tag_set: set[str],
    matched_buckets: set[str],
) -> bool:
    """Check whether one configured rule matches the current task."""
    if rule.match_all_tags and not set(rule.match_all_tags).issubset(tag_set):
        return False

    if rule.match_all_buckets and not set(rule.match_all_buckets).issubset(matched_buckets):
        return False

    return True


def _apply_strategy(
    matched_buckets: list[str],
    strategy: str,
    priority_order: list[str],
    weights: dict[str, float],
) -> dict[str, float]:
    """Apply one arbitration strategy to the matched buckets."""
    if strategy == "priority":
        return _apply_priority(
            matched_buckets=matched_buckets,
            priority_order=priority_order,
        )

    if strategy == "split_weighted":
        return _apply_split_weighted(
            matched_buckets=matched_buckets,
            weights=weights,
        )

    raise ValueError(f"Unsupported time bucket strategy: {strategy}")


def _apply_priority(
    matched_buckets: list[str],
    priority_order: list[str],
) -> dict[str, float]:
    """Pick exactly one bucket according to priority order."""
    matched_set = set(matched_buckets)

    for bucket_name in priority_order:
        if bucket_name in matched_set:
            return {bucket_name: 1.0}

    return {matched_buckets[0]: 1.0}


def _apply_split_weighted(
    matched_buckets: list[str],
    weights: dict[str, float],
) -> dict[str, float]:
    """Split across all matched buckets using configured weights."""
    raw_weights: dict[str, float] = {}
    for bucket_name in matched_buckets:
        raw_weights[bucket_name] = float(weights.get(bucket_name, 1.0))

    total_weight = sum(raw_weights.values())
    if total_weight <= 0.0:
        raise ValueError("Split-weighted time bucket resolution produced zero total weight.")

    return {
        bucket_name: raw_weight / total_weight for bucket_name, raw_weight in raw_weights.items()
    }
