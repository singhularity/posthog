from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.user import User

from .models import MCPAnalyticsSubmission


class MCPAnalyticsSubmissionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for this submission.")
    kind = serializers.ChoiceField(
        choices=MCPAnalyticsSubmission.Kind.choices,
        read_only=True,
        help_text="Whether this submission is general feedback or a missing capability report.",
    )
    goal = serializers.CharField(help_text="The user's goal in plain language.")
    summary = serializers.CharField(help_text="The core feedback or missing capability request.")
    category = serializers.CharField(
        read_only=True,
        help_text="Feedback category when present. Empty for submissions that do not use categories.",
    )
    blocked = serializers.BooleanField(
        allow_null=True,
        read_only=True,
        help_text="Whether the missing capability blocked progress. Null when not provided.",
    )
    attempted_tool = serializers.CharField(
        read_only=True,
        help_text="The tool the user tried before submitting this feedback, if known.",
    )
    mcp_client_name = serializers.CharField(
        read_only=True,
        help_text="MCP client name captured alongside the submission when available.",
    )
    mcp_client_version = serializers.CharField(
        read_only=True,
        help_text="MCP client version captured alongside the submission when available.",
    )
    mcp_protocol_version = serializers.CharField(
        read_only=True,
        help_text="MCP protocol version captured alongside the submission when available.",
    )
    mcp_transport = serializers.CharField(
        read_only=True,
        help_text="MCP transport captured alongside the submission when available.",
    )
    mcp_session_id = serializers.CharField(
        read_only=True,
        help_text="MCP session identifier captured alongside the submission when available.",
    )
    mcp_trace_id = serializers.CharField(
        read_only=True,
        help_text="MCP trace identifier captured alongside the submission when available.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When this submission was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When this submission was last updated.")

    class Meta:
        model = MCPAnalyticsSubmission
        fields = [
            "id",
            "kind",
            "goal",
            "summary",
            "category",
            "blocked",
            "attempted_tool",
            "mcp_client_name",
            "mcp_client_version",
            "mcp_protocol_version",
            "mcp_transport",
            "mcp_session_id",
            "mcp_trace_id",
            "created_at",
            "updated_at",
        ]


class MCPAnalyticsSubmissionContextSerializer(serializers.Serializer):
    attempted_tool = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="The tool the user tried before leaving feedback, if known.",
    )
    mcp_client_name = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="MCP client name, for example Claude Desktop or Cursor.",
    )
    mcp_client_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Version string for the MCP client when available.",
    )
    mcp_protocol_version = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="MCP protocol version negotiated for the session when available.",
    )
    mcp_transport = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Transport used for the MCP session, for example streamable_http or sse.",
    )
    mcp_session_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Stable MCP session identifier when available.",
    )
    mcp_trace_id = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Trace identifier for the surrounding MCP workflow when available.",
    )


class MCPFeedbackCreateSerializer(MCPAnalyticsSubmissionContextSerializer):
    goal = serializers.CharField(help_text="The user's intended outcome when using MCP.")
    feedback = serializers.CharField(
        source="summary",
        help_text="Concrete feedback about the MCP experience, tool result, or workflow friction.",
    )
    category = serializers.ChoiceField(
        choices=MCPAnalyticsSubmission.FeedbackCategory.choices,
        required=False,
        default=MCPAnalyticsSubmission.FeedbackCategory.OTHER,
        help_text="High-level category for the feedback.",
    )


class MCPMissingCapabilityCreateSerializer(MCPAnalyticsSubmissionContextSerializer):
    goal = serializers.CharField(help_text="The user's intended outcome when using MCP.")
    missing_capability = serializers.CharField(
        source="summary",
        help_text="Capability, tool, or workflow support that is currently missing.",
    )
    blocked = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether the missing capability blocked the user's progress.",
    )


@extend_schema(tags=["mcp_analytics"])
class BaseMCPAnalyticsSubmissionViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "mcp_analytics"
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["create"]
    queryset = MCPAnalyticsSubmission.objects.all()
    serializer_class = MCPAnalyticsSubmissionSerializer
    permission_classes = [IsAuthenticated]
    kind: str = ""
    user_action_name: str = ""

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team, kind=self.kind)

    def _create_submission(
        self,
        request: Request,
        validated_data: dict[str, Any],
        *,
        response_status: int = status.HTTP_201_CREATED,
    ) -> Response:
        submission = MCPAnalyticsSubmission.objects.create(
            team=self.team,
            created_by=cast(User, request.user),
            kind=self.kind,
            **validated_data,
        )

        report_user_action(
            cast(User, request.user),
            self.user_action_name,
            {
                "submission_id": str(submission.id),
                "kind": submission.kind,
                "attempted_tool": submission.attempted_tool,
                "mcp_client_name": submission.mcp_client_name,
                "mcp_session_id_present": bool(submission.mcp_session_id),
                "mcp_trace_id_present": bool(submission.mcp_trace_id),
            },
            team=self.team,
            request=request,
        )

        return Response(self.get_serializer(submission).data, status=response_status)


class MCPFeedbackViewSet(BaseMCPAnalyticsSubmissionViewSet):
    kind = MCPAnalyticsSubmission.Kind.FEEDBACK
    user_action_name = "mcp analytics feedback created"

    @validated_request(
        request_serializer=MCPFeedbackCreateSerializer,
        responses={201: OpenApiResponse(response=MCPAnalyticsSubmissionSerializer)},
        operation_id="mcp_analytics_feedback_create",
        description="Create a new MCP feedback submission for the current project.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        return self._create_submission(request, request.validated_data)

    @extend_schema(
        operation_id="mcp_analytics_feedback_list",
        description="List MCP feedback submissions for the current project, newest first.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)


class MCPMissingCapabilityViewSet(BaseMCPAnalyticsSubmissionViewSet):
    kind = MCPAnalyticsSubmission.Kind.MISSING_CAPABILITY
    user_action_name = "mcp analytics missing capability reported"

    @validated_request(
        request_serializer=MCPMissingCapabilityCreateSerializer,
        responses={201: OpenApiResponse(response=MCPAnalyticsSubmissionSerializer)},
        operation_id="mcp_analytics_missing_capabilities_create",
        description="Create a new missing capability report for the current project.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        return self._create_submission(request, request.validated_data)

    @extend_schema(
        operation_id="mcp_analytics_missing_capabilities_list",
        description="List missing capability reports for the current project, newest first.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)
