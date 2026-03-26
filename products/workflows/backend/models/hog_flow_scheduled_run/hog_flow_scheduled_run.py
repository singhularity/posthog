from django.db import models

from posthog.models.utils import RootTeamMixin, UUIDTModel


class HogFlowScheduledRun(RootTeamMixin, UUIDTModel):
    """
    Tracks a single scheduled execution of a HogFlow.
    One pending row per schedule represents the next run. Completed rows serve as execution history.
    """

    class Meta:
        indexes = [
            models.Index(fields=["status", "run_at"]),  # Poller query
            models.Index(fields=["hog_flow", "-run_at"]),  # List runs for a workflow
        ]

    class Status(models.TextChoices):
        PENDING = "pending"
        COMPLETED = "completed"
        FAILED = "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING)
    hog_flow = models.ForeignKey("posthog.HogFlow", on_delete=models.DO_NOTHING, related_name="scheduled_runs")
    schedule = models.ForeignKey(
        "workflows.HogFlowSchedule", null=True, blank=True, on_delete=models.SET_NULL, related_name="scheduled_runs"
    )
    run_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    variables = models.JSONField(default=dict)  # Snapshot of resolved variables at creation time
    batch_job = models.ForeignKey("workflows.HogFlowBatchJob", null=True, blank=True, on_delete=models.SET_NULL)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"HogFlowScheduledRun {self.id} at {self.run_at} ({self.status})"
