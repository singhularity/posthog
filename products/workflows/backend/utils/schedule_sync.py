from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences


def sync_next_run(schedule: HogFlowSchedule) -> None:
    """
    Compute and set next_run_at for a schedule.
    Clears next_run_at if the schedule is not active or the workflow isn't
    a batch trigger. Marks as completed if the RRULE is exhausted.
    Called from the HogFlowSchedule post_save signal.
    """
    if schedule.status != HogFlowSchedule.Status.ACTIVE:
        if schedule.next_run_at is not None:
            HogFlowSchedule.objects.filter(id=schedule.id).update(next_run_at=None)
        return

    hog_flow = schedule.hog_flow
    trigger_type = (hog_flow.trigger or {}).get("type")
    if hog_flow.status != "active" or trigger_type != "batch":
        if schedule.next_run_at is not None:
            HogFlowSchedule.objects.filter(id=schedule.id).update(next_run_at=None)
        return

    occurrences = compute_next_occurrences(
        rrule_string=schedule.rrule,
        starts_at=schedule.starts_at,
        timezone_str=schedule.timezone,
        count=1,
    )

    if not occurrences:
        HogFlowSchedule.objects.filter(id=schedule.id).update(
            status=HogFlowSchedule.Status.COMPLETED,
            next_run_at=None,
        )
        return

    next_run = occurrences[0]
    if schedule.next_run_at != next_run:
        HogFlowSchedule.objects.filter(id=schedule.id).update(next_run_at=next_run)


def resolve_variables(hog_flow, schedule: HogFlowSchedule) -> dict:
    """Build default variables from HogFlow schema, then merge schedule overrides."""
    defaults = {}
    for var in hog_flow.variables or []:
        defaults[var.get("key")] = var.get("default")
    defaults.update(schedule.variables or {})
    return defaults
