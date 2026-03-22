"""Resolves a user's PostHog Code plan via the PostHog API seats endpoint.

Calls ``GET /api/seats/me/?product_key=posthog_code`` on the PostHog API,
forwarding the user's auth token. The Django SeatViewSet handles billing
JWT construction and proxies to the billing service.

Results are cached in Redis to avoid hitting the API on every request.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from llm_gateway.config import get_settings

if TYPE_CHECKING:
    import httpx
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

PLAN_CACHE_PREFIX = "plan:posthog_code"
PRO_PLAN_PREFIX = "posthog-code-200"


@dataclass
class PlanInfo:
    plan_key: str | None
    in_trial_period: bool


def _redis_key(user_id: int) -> str:
    return f"{PLAN_CACHE_PREFIX}:{user_id}"


def is_pro_plan(plan_key: str | None) -> bool:
    if not plan_key:
        return False
    return plan_key.startswith(PRO_PLAN_PREFIX)


def _is_in_trial(seat_created_at: str | None) -> bool:
    if not seat_created_at:
        return True
    try:
        created = datetime.fromisoformat(seat_created_at)
        trial_days = get_settings().free_plan_trial_period_days
        return datetime.now(tz=UTC) - created < timedelta(days=trial_days)
    except (ValueError, TypeError):
        return True


class PlanResolver:
    def __init__(
        self,
        redis: Redis[bytes] | None,
        http_client: httpx.AsyncClient,
    ):
        self._redis = redis
        self._http = http_client

    async def invalidate(self, user_id: int) -> None:
        if not self._redis:
            return
        try:
            await self._redis.delete(_redis_key(user_id))
        except Exception:
            logger.debug("plan_cache_invalidate_failed", user_id=user_id)

    async def get_plan(self, user_id: int, auth_header: str) -> PlanInfo:
        """Return the user's plan info, using cache when available."""
        cached = await self._get_cached(user_id)
        if cached is not None:
            return cached

        plan_key, seat_created_at = await self._fetch_plan(auth_header)
        await self._set_cached(user_id, plan_key, seat_created_at)
        return PlanInfo(
            plan_key=plan_key,
            in_trial_period=_is_in_trial(seat_created_at),
        )

    async def _get_cached(self, user_id: int) -> PlanInfo | None:
        if not self._redis:
            return None
        try:
            val = await self._redis.get(_redis_key(user_id))
            if val is not None:
                data = json.loads(val.decode())
                plan_key = data.get("plan_key") or None
                seat_created_at = data.get("created_at")
                return PlanInfo(
                    plan_key=plan_key,
                    in_trial_period=_is_in_trial(seat_created_at),
                )
        except Exception:
            logger.debug("plan_cache_read_failed", user_id=user_id)
        return None

    async def _set_cached(self, user_id: int, plan_key: str | None, seat_created_at: str | None) -> None:
        if not self._redis:
            return
        ttl = get_settings().plan_cache_ttl
        try:
            data = json.dumps({"plan_key": plan_key, "created_at": seat_created_at})
            await self._redis.set(_redis_key(user_id), data, ex=ttl)
        except Exception:
            logger.debug("plan_cache_write_failed", user_id=user_id)

    async def _fetch_plan(self, auth_header: str) -> tuple[str | None, str | None]:
        """Call the PostHog API seats endpoint to get the user's plan."""
        settings = get_settings()
        if not settings.posthog_api_url:
            return None, None

        try:
            url = f"{settings.posthog_api_url.rstrip('/')}/api/seats/me/"
            resp = await self._http.get(
                url,
                params={"product_key": "posthog_code"},
                headers={"Authorization": auth_header},
                timeout=5.0,
            )
            if resp.status_code == 404:
                return None, None
            resp.raise_for_status()
            data = resp.json()
            return data.get("plan_key"), data.get("created_at")
        except Exception:
            logger.warning("seat_fetch_failed")
            return None, None
