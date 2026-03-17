import requests
import structlog
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.cloud_utils import get_cached_instance_license

from ee.billing.billing_manager import build_billing_token
from ee.settings import BILLING_SERVICE_URL


logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 30


class CodeSeatViewSet(viewsets.ViewSet):
    """
    Proxy for PostHog Code seat management through the billing service.

    All endpoints resolve ``me`` in the URL to the requesting user's
    ``distinct_id``, build a billing JWT and forward the request to the
    billing service's ``/api/v2/seats/`` endpoints.

    Successful responses that contain seat data are unwrapped so the
    client receives the seat object directly (not the billing envelope).
    Error responses are forwarded as-is.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_billing_headers(self, request):
        license = get_cached_instance_license()
        org = request.user.organization
        if not org or not license:
            return None
        try:
            token = build_billing_token(license, org, request.user)
        except NotAuthenticated:
            logger.warning("User not a member of their current organization", user_id=request.user.id)
            return None
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    def _resolve_distinct_id(pk, request):
        if pk == "me":
            return str(request.user.distinct_id)
        return pk

    def _forward_response(self, billing_response, extract_seat=True):
        """Convert a billing service response to a DRF Response.

        For successful responses that contain a ``seat`` key the seat
        object is returned directly so the client doesn't need to know
        about the billing envelope.  Error responses pass through as-is.
        """
        if billing_response is None:
            return Response({"detail": "Billing service unavailable"}, status=status.HTTP_502_BAD_GATEWAY)

        if billing_response.status_code == 204:
            return Response(status=status.HTTP_204_NO_CONTENT)

        try:
            data = billing_response.json()
        except ValueError:
            return Response({"detail": "Invalid response from billing service"}, status=status.HTTP_502_BAD_GATEWAY)

        if billing_response.ok and extract_seat and isinstance(data, dict) and "seat" in data:
            return Response(data["seat"], status=billing_response.status_code)

        return Response(data, status=billing_response.status_code)

    def _billing_request(self, method, path, headers, json_body=None, query_params=None):
        url = f"{BILLING_SERVICE_URL}{path}"
        try:
            return requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=query_params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            logger.exception("Billing service request failed", path=path, method=method)
            return None

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def create(self, request):
        """POST /api/code/seats/ -> POST /api/v2/seats/"""
        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        resp = self._billing_request("POST", "/api/v2/seats/", headers, json_body=request.data)
        return self._forward_response(resp)

    def retrieve(self, request, pk=None):
        """GET /api/code/seats/me/ -> GET /api/v2/seats/{distinct_id}/?product_key="""
        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "GET",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            query_params=request.query_params.dict(),
        )
        return self._forward_response(resp)

    def partial_update(self, request, pk=None):
        """PATCH /api/code/seats/me/ -> PATCH /api/v2/seats/{distinct_id}/"""
        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "PATCH",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            json_body=request.data,
        )
        return self._forward_response(resp)

    def destroy(self, request, pk=None):
        """DELETE /api/code/seats/me/?product_key= -> DELETE /api/v2/seats/{distinct_id}/?product_key="""
        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "DELETE",
            f"/api/v2/seats/{distinct_id}/",
            headers,
            query_params=request.query_params.dict(),
        )
        return self._forward_response(resp, extract_seat=False)

    @action(detail=True, methods=["post"], url_path="reactivate")
    def reactivate(self, request, pk=None):
        """POST /api/code/seats/me/reactivate/ -> POST /api/v2/seats/{distinct_id}/reactivate/"""
        headers = self._get_billing_headers(request)
        if not headers:
            return Response({"detail": "No organization or license found"}, status=status.HTTP_400_BAD_REQUEST)

        distinct_id = self._resolve_distinct_id(pk, request)
        resp = self._billing_request(
            "POST",
            f"/api/v2/seats/{distinct_id}/reactivate/",
            headers,
            json_body=request.data,
        )
        return self._forward_response(resp)
