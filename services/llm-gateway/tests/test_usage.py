from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from llm_gateway.rate_limiting.cost_throttles import (
    UserCostBurstThrottle,
    UserCostSustainedThrottle,
)
from llm_gateway.rate_limiting.throttles import ThrottleContext

from tests.conftest import create_test_app


class TestUsageEndpoint:
    @pytest.fixture
    def authenticated_usage_client(self, mock_db_pool: MagicMock) -> TestClient:
        app = create_test_app(mock_db_pool)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "key_id",
                "user_id": 42,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 1,
                "distinct_id": "test-distinct-id",
            }
        )
        mock_db_pool.acquire = AsyncMock(return_value=conn)
        mock_db_pool.release = AsyncMock()

        with TestClient(app) as c:
            yield c

    def test_returns_usage_for_product(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["product"] == "posthog_code"
        assert data["user_id"] == 42

        assert data["burst"]["used_usd"] == 0.0
        assert data["burst"]["limit_usd"] == 100.0
        assert data["burst"]["remaining_usd"] == 100.0
        assert data["burst"]["exceeded"] is False

        assert data["sustained"]["used_usd"] == 0.0
        assert data["sustained"]["limit_usd"] == 1000.0
        assert data["sustained"]["remaining_usd"] == 1000.0
        assert data["sustained"]["exceeded"] is False

        assert data["is_rate_limited"] is False

    def test_returns_401_without_auth(self, client: TestClient) -> None:
        response = client.get("/v1/usage/posthog_code")
        assert response.status_code == 401

    def test_reflects_accumulated_cost(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        runner = app.state.throttle_runner

        context = ThrottleContext(
            user=MagicMock(user_id=42, team_id=1),
            product="posthog_code",
            end_user_id="42",
        )

        burst_throttle = next(t for t in runner._throttles if isinstance(t, UserCostBurstThrottle))
        sustained_throttle = next(t for t in runner._throttles if isinstance(t, UserCostSustainedThrottle))

        import asyncio

        asyncio.get_event_loop().run_until_complete(burst_throttle.record_cost(context, 25.50))
        asyncio.get_event_loop().run_until_complete(sustained_throttle.record_cost(context, 25.50))

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_usd"] == 25.5
        assert data["burst"]["remaining_usd"] == 74.5
        assert data["burst"]["exceeded"] is False

        assert data["sustained"]["used_usd"] == 25.5
        assert data["sustained"]["remaining_usd"] == 974.5
        assert data["sustained"]["exceeded"] is False

    def test_shows_rate_limited_when_burst_exceeded(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        runner = app.state.throttle_runner

        context = ThrottleContext(
            user=MagicMock(user_id=42, team_id=1),
            product="posthog_code",
            end_user_id="42",
        )

        burst_throttle = next(t for t in runner._throttles if isinstance(t, UserCostBurstThrottle))

        import asyncio

        asyncio.get_event_loop().run_until_complete(burst_throttle.record_cost(context, 100.0))

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["exceeded"] is True
        assert data["is_rate_limited"] is True

    def test_ignores_user_id_query_param(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code?user_id=99",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == 42
