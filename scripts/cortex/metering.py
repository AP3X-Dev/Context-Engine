"""Usage metering with per-tier rate limit checking for ONI Cortex."""

from dataclasses import dataclass
from datetime import datetime, timezone

from scripts.cortex.config import TIER_LIMITS
from scripts.cortex.database import get_usage_count, record_usage

# Map public metric names to TIER_LIMITS keys
_METRIC_TO_LIMIT_KEY = {
    "queries": "queries_per_day",
}


@dataclass
class MeterResult:
    """Result of a rate-limit check."""

    allowed: bool
    current: int
    limit: int
    metric: str


async def check_rate_limit(tenant_id: str, metric: str, plan: str) -> MeterResult:
    """Check whether a tenant is within their rate limit for *metric*.

    Looks up the limit from ``TIER_LIMITS`` using *plan*.  The metric name is
    mapped to the corresponding limit key (e.g. ``"queries"`` -> ``"queries_per_day"``).

    If the limit is ``-1`` (enterprise / unlimited), the request is always allowed.
    Otherwise the total usage since the start of today (UTC) is compared to the
    configured limit.
    """

    limit_key = _METRIC_TO_LIMIT_KEY.get(metric, metric)
    tier = TIER_LIMITS.get(plan, TIER_LIMITS["free"])
    limit_value: int = tier.get(limit_key, 0)

    # Enterprise / unlimited
    if limit_value == -1:
        current = await get_usage_count(tenant_id, metric)
        return MeterResult(allowed=True, current=current, limit=-1, metric=metric)

    # Compute the start of today (UTC)
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    current = await get_usage_count(tenant_id, metric, since=start_of_day)

    return MeterResult(
        allowed=current < limit_value,
        current=current,
        limit=limit_value,
        metric=metric,
    )


async def meter_and_check(
    tenant_id: str, metric: str, plan: str, count: int = 1
) -> MeterResult:
    """Record usage first, then check the rate limit.

    This is the typical call-path: record *count* units of *metric* for the
    tenant and immediately return whether they are still within their tier
    limit.
    """

    await record_usage(tenant_id, metric, count)
    return await check_rate_limit(tenant_id, metric, plan)
