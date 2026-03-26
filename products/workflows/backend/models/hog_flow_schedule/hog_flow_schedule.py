from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.models.utils import RootTeamMixin, UUIDTModel

logger = structlog.get_logger(__name__)


class HogFlowSchedule(RootTeamMixin, UUIDTModel):
    """
    A recurring schedule definition for a HogFlow.
    Multiple schedules per workflow are supported, each with their own
    RRULE, timezone, and variable overrides.
    """

    class Status(models.TextChoices):
        ACTIVE = "active"
        PAUSED = "paused"
        COMPLETED = "completed"  # RRULE exhausted (COUNT/UNTIL reached)

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    hog_flow = models.ForeignKey("posthog.HogFlow", on_delete=models.CASCADE, related_name="schedules")
    rrule = models.TextField()
    starts_at = models.DateTimeField()
    timezone = models.CharField(max_length=64, default="UTC")
    variables = models.JSONField(default=dict)  # {key: value} overrides, merged with HogFlow defaults at execution
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"HogFlowSchedule {self.id} ({self.rrule}, {self.status})"


@receiver(post_save, sender=HogFlowSchedule)
def hog_flow_schedule_saved(sender, instance: HogFlowSchedule, created, **kwargs):
    try:
        from products.workflows.backend.utils.schedule_sync import sync_next_run

        sync_next_run(instance)
    except Exception:
        logger.warning(
            "Failed to sync next run for HogFlowSchedule",
            schedule_id=str(instance.id),
            exc_info=True,
        )
