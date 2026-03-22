from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

import structlog

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.dependencies import get_authenticated_user
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.cost_throttles import CostThrottle, UserCostBurstThrottle, UserCostSustainedThrottle
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.services.plan_resolver import PlanResolver

logger = structlog.get_logger(__name__)

usage_router = APIRouter(prefix="/v1/usage", tags=["Usage"])


class CostLimitStatus(BaseModel):
    used_usd: float
    limit_usd: float
    remaining_usd: float
    resets_in_seconds: int
    exceeded: bool


class UsageResponse(BaseModel):
    product: str
    user_id: int
    burst: CostLimitStatus
    sustained: CostLimitStatus
    is_rate_limited: bool


async def _get_cost_status(
    throttle: CostThrottle,
    context: ThrottleContext,
) -> CostLimitStatus:
    limiter = throttle._get_limiter(context)
    key = throttle._get_cache_key(context)
    limit, _ = throttle._get_limit_and_window(context)

    current = await limiter.get_current(key)
    ttl = await limiter.get_ttl(key)
    remaining = max(0.0, limit - current)

    return CostLimitStatus(
        used_usd=round(current, 6),
        limit_usd=round(limit, 2),
        remaining_usd=round(remaining, 6),
        resets_in_seconds=ttl,
        exceeded=current >= limit,
    )


@usage_router.get("/{product}")
async def get_usage(
    product: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> UsageResponse:
    runner: ThrottleRunner = request.app.state.throttle_runner

    plan_key: str | None = None
    in_trial_period: bool = True
    settings = get_settings()
    if product == "posthog_code" and settings.plan_aware_throttling_enabled:
        plan_resolver: PlanResolver = request.app.state.plan_resolver
        auth_header = request.headers.get("Authorization", "")
        try:
            plan_info = await plan_resolver.get_plan(
                user_id=user.user_id,
                auth_header=auth_header,
            )
            plan_key = plan_info.plan_key
            in_trial_period = plan_info.in_trial_period
        except Exception:
            logger.warning("plan_resolve_failed_usage", user_id=user.user_id)

    context = ThrottleContext(
        user=user,
        product=product,
        end_user_id=str(user.user_id),
        plan_key=plan_key,
        in_trial_period=in_trial_period,
    )

    burst_status: CostLimitStatus | None = None
    sustained_status: CostLimitStatus | None = None

    for throttle in runner._throttles:
        if isinstance(throttle, UserCostBurstThrottle):
            burst_status = await _get_cost_status(throttle, context)
        elif isinstance(throttle, UserCostSustainedThrottle):
            sustained_status = await _get_cost_status(throttle, context)

    if burst_status is None:
        burst_status = CostLimitStatus(
            used_usd=0, limit_usd=0, remaining_usd=0, resets_in_seconds=0, exceeded=False
        )
    if sustained_status is None:
        sustained_status = CostLimitStatus(
            used_usd=0, limit_usd=0, remaining_usd=0, resets_in_seconds=0, exceeded=False
        )

    return UsageResponse(
        product=product,
        user_id=user.user_id,
        burst=burst_status,
        sustained=sustained_status,
        is_rate_limited=burst_status.exceeded or sustained_status.exceeded,
    )


@usage_router.post("/{product}/invalidate-plan-cache")
async def invalidate_plan_cache(
    product: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> dict[str, bool]:
    plan_resolver: PlanResolver = request.app.state.plan_resolver
    await plan_resolver.invalidate(user.user_id)
    return {"ok": True}
