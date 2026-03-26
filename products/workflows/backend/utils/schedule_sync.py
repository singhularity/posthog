from django.db import transaction

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.models.hog_flow_scheduled_run import HogFlowScheduledRun
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences


def sync_schedule(hog_flow: HogFlow, team_id: int) -> None:
    """
    Manage pending HogFlowScheduledRuns based on active HogFlowSchedules.
    Deletes all existing pending runs and creates one per active schedule.
    Called from the HogFlow post_save signal.
    """
    with transaction.atomic():
        # Lock the HogFlow row to serialize concurrent syncs
        HogFlow.objects.select_for_update().get(id=hog_flow.id)

        HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status=HogFlowScheduledRun.Status.PENDING).delete()

        trigger_type = (hog_flow.trigger or {}).get("type")
        if hog_flow.status != HogFlow.State.ACTIVE or trigger_type != "batch":
            return

        for schedule in HogFlowSchedule.objects.filter(hog_flow=hog_flow, status=HogFlowSchedule.Status.ACTIVE):
            occurrences = compute_next_occurrences(
                rrule_string=schedule.rrule,
                starts_at=schedule.starts_at,
                timezone_str=schedule.timezone,
                count=1,
            )
            if not occurrences:
                schedule.status = HogFlowSchedule.Status.COMPLETED
                schedule.save(update_fields=["status"])
                continue

            variables = _resolve_variables(hog_flow, schedule)
            HogFlowScheduledRun.objects.create(
                team_id=team_id,
                hog_flow=hog_flow,
                schedule=schedule,
                run_at=occurrences[0],
                status=HogFlowScheduledRun.Status.PENDING,
                variables=variables,
            )


def _resolve_variables(hog_flow: HogFlow, schedule: HogFlowSchedule) -> dict:
    """Build default variables from HogFlow schema, then merge schedule overrides."""
    defaults = {}
    for var in hog_flow.variables or []:
        defaults[var.get("key")] = var.get("default")
    defaults.update(schedule.variables or {})
    return defaults
