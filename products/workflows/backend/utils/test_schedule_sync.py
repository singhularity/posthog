from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest import TestCase

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.models.hog_flow_scheduled_run import HogFlowScheduledRun
from products.workflows.backend.utils.schedule_sync import _resolve_variables, sync_schedule

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}


class TestResolveVariables(TestCase):
    def test_empty_defaults_and_empty_overrides(self):
        hog_flow = type("HogFlow", (), {"variables": []})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {}

    def test_defaults_only(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": 1, "b": 2}

    def test_overrides_replace_defaults(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {"a": 99}})()
        result = _resolve_variables(hog_flow, schedule)
        assert result == {"a": 99, "b": 2}

    def test_overrides_add_new_keys(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}]})()
        schedule = type("Schedule", (), {"variables": {"b": "new"}})()
        result = _resolve_variables(hog_flow, schedule)
        assert result == {"a": 1, "b": "new"}

    def test_none_variables_on_hogflow(self):
        hog_flow = type("HogFlow", (), {"variables": None})()
        schedule = type("Schedule", (), {"variables": {"a": 1}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": 1}

    def test_variable_without_default(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a"}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert _resolve_variables(hog_flow, schedule) == {"a": None, "b": 2}


class TestSyncSchedule(BaseTest):
    def _create_hogflow(self, status="active", trigger=None, variables=None):
        return HogFlow.objects.create(
            team=self.team,
            name="Test Workflow",
            status=status,
            trigger=trigger or BATCH_TRIGGER,
            actions=[],
            variables=variables or [],
        )

    def _create_schedule(self, hog_flow, rrule="FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", status="active", variables=None):
        return HogFlowSchedule.objects.create(
            team=self.team,
            hog_flow=hog_flow,
            rrule=rrule,
            starts_at=datetime(2030, 1, 1, 9, 0, 0, tzinfo=UTC),
            timezone="UTC",
            status=status,
            variables=variables or {},
        )

    def test_active_workflow_with_schedule_creates_pending_run(self):
        hog_flow = self._create_hogflow()
        self._create_schedule(hog_flow)
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 1

    def test_multiple_active_schedules_create_multiple_pending_runs(self):
        hog_flow = self._create_hogflow()
        self._create_schedule(hog_flow, rrule="FREQ=WEEKLY;INTERVAL=1;BYDAY=MO")
        self._create_schedule(hog_flow, rrule="FREQ=DAILY;INTERVAL=1")
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 2

    def test_paused_schedule_creates_no_pending_run(self):
        hog_flow = self._create_hogflow()
        self._create_schedule(hog_flow, status="paused")
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 0

    def test_inactive_workflow_deletes_existing_pending_runs(self):
        hog_flow = self._create_hogflow()
        self._create_schedule(hog_flow)
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 1

        hog_flow.status = "draft"
        hog_flow.save()
        # post_save calls sync_schedule, which deletes pending runs
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 0

    def test_non_batch_trigger_creates_no_runs(self):
        event_trigger = {"type": "event", "filters": {"events": [{"id": "$pageview"}]}}
        hog_flow = self._create_hogflow(trigger=event_trigger)
        self._create_schedule(hog_flow)
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 0

    def test_exhausted_rrule_marks_schedule_completed(self):
        hog_flow = self._create_hogflow()
        schedule = HogFlowSchedule.objects.create(
            team=self.team,
            hog_flow=hog_flow,
            rrule="FREQ=DAILY;COUNT=1",
            starts_at=datetime(2020, 1, 1, 9, 0, 0, tzinfo=UTC),
            timezone="UTC",
            status="active",
        )
        sync_schedule(hog_flow, self.team.id)

        schedule.refresh_from_db()
        assert schedule.status == "completed"
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 0

    def test_sync_deletes_old_pending_runs_before_creating_new(self):
        hog_flow = self._create_hogflow()
        self._create_schedule(hog_flow)
        sync_schedule(hog_flow, self.team.id)
        sync_schedule(hog_flow, self.team.id)
        sync_schedule(hog_flow, self.team.id)
        assert HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending").count() == 1

    def test_pending_run_has_resolved_variables(self):
        hog_flow = self._create_hogflow(
            variables=[{"key": "greeting", "default": "Hello"}, {"key": "name", "default": "World"}]
        )
        self._create_schedule(hog_flow, variables={"greeting": "Overridden"})
        sync_schedule(hog_flow, self.team.id)

        run = HogFlowScheduledRun.objects.get(hog_flow=hog_flow, status="pending")
        assert run.variables == {"greeting": "Overridden", "name": "World"}
