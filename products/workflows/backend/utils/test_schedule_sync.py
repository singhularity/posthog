from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest import TestCase

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.utils.schedule_sync import resolve_variables, sync_next_run

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}


class TestResolveVariables(TestCase):
    def test_empty_defaults_and_empty_overrides(self):
        hog_flow = type("HogFlow", (), {"variables": []})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert resolve_variables(hog_flow, schedule) == {}

    def test_defaults_only(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert resolve_variables(hog_flow, schedule) == {"a": 1, "b": 2}

    def test_overrides_replace_defaults(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {"a": 99}})()
        result = resolve_variables(hog_flow, schedule)
        assert result == {"a": 99, "b": 2}

    def test_overrides_add_new_keys(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a", "default": 1}]})()
        schedule = type("Schedule", (), {"variables": {"b": "new"}})()
        result = resolve_variables(hog_flow, schedule)
        assert result == {"a": 1, "b": "new"}

    def test_none_variables_on_hogflow(self):
        hog_flow = type("HogFlow", (), {"variables": None})()
        schedule = type("Schedule", (), {"variables": {"a": 1}})()
        assert resolve_variables(hog_flow, schedule) == {"a": 1}

    def test_variable_without_default(self):
        hog_flow = type("HogFlow", (), {"variables": [{"key": "a"}, {"key": "b", "default": 2}]})()
        schedule = type("Schedule", (), {"variables": {}})()
        assert resolve_variables(hog_flow, schedule) == {"a": None, "b": 2}


class TestSyncNextRun(BaseTest):
    def _create_hogflow(self, status="active", trigger=None):
        return HogFlow.objects.create(
            team=self.team,
            name="Test Workflow",
            status=status,
            trigger=trigger or BATCH_TRIGGER,
            actions=[],
            variables=[],
        )

    def _create_schedule(self, hog_flow, rrule="FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", status="active"):
        return HogFlowSchedule.objects.create(
            team=self.team,
            hog_flow=hog_flow,
            rrule=rrule,
            starts_at=datetime(2030, 1, 1, 9, 0, 0, tzinfo=UTC),
            timezone="UTC",
            status=status,
        )

    def test_active_schedule_gets_next_run_at(self):
        hog_flow = self._create_hogflow()
        schedule = self._create_schedule(hog_flow)
        schedule.refresh_from_db()
        assert schedule.next_run_at is not None

    def test_paused_schedule_has_no_next_run_at(self):
        hog_flow = self._create_hogflow()
        schedule = self._create_schedule(hog_flow, status="paused")
        schedule.refresh_from_db()
        assert schedule.next_run_at is None

    def test_non_batch_trigger_has_no_next_run_at(self):
        event_trigger = {"type": "event", "filters": {"events": [{"id": "$pageview"}]}}
        hog_flow = self._create_hogflow(trigger=event_trigger)
        schedule = self._create_schedule(hog_flow)
        schedule.refresh_from_db()
        assert schedule.next_run_at is None

    def test_inactive_workflow_has_no_next_run_at(self):
        hog_flow = self._create_hogflow(status="draft")
        schedule = self._create_schedule(hog_flow)
        schedule.refresh_from_db()
        assert schedule.next_run_at is None

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
        schedule.refresh_from_db()
        assert schedule.status == "completed"
        assert schedule.next_run_at is None

    def test_repeated_sync_is_idempotent(self):
        hog_flow = self._create_hogflow()
        schedule = self._create_schedule(hog_flow)
        schedule.refresh_from_db()
        first_next_run = schedule.next_run_at

        sync_next_run(schedule)
        schedule.refresh_from_db()
        assert schedule.next_run_at == first_next_run
