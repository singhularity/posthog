from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest import TestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.models.hog_flow_scheduled_run import HogFlowScheduledRun
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule
from products.workflows.backend.utils.schedule_sync import _resolve_variables

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}

EVENT_TRIGGER = {
    "type": "event",
    "filters": {
        "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
    },
}

SCHEDULE = {
    "rrule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
    "starts_at": "2030-01-01T09:00:00Z",
    "timezone": "UTC",
}


def _make_workflow_payload(workflow_status="draft", schedules=None, trigger_config=None):
    payload = {
        "name": "Test Batch Workflow",
        "status": workflow_status,
        "actions": [
            {
                "id": "trigger_node",
                "name": "trigger",
                "type": "trigger",
                "config": trigger_config or BATCH_TRIGGER,
            }
        ],
    }
    if schedules is not None:
        payload["schedules"] = schedules
    return payload


class TestRRuleUtils(TestCase):
    @parameterized.expand(
        [
            ("FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",),
            ("FREQ=DAILY;COUNT=1",),
            ("FREQ=MONTHLY;BYMONTHDAY=15",),
            ("FREQ=MONTHLY;BYMONTHDAY=-1",),
            ("FREQ=YEARLY;INTERVAL=2",),
        ]
    )
    def test_validate_rrule_accepts_valid_strings(self, rrule_str):
        validate_rrule(rrule_str)

    @parameterized.expand(
        [
            ("NOT_A_RRULE",),
            ("FREQ=INVALID",),
            ("",),
            ("DTSTART:20260101T000000\nRRULE:FREQ=DAILY",),
            ("BYDAY=MO",),
        ]
    )
    def test_validate_rrule_rejects_invalid_strings(self, rrule_str):
        with self.assertRaises(ValueError):
            validate_rrule(rrule_str)

    def test_compute_next_occurrences_weekly(self):
        starts_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", starts_at, timezone_str="UTC", after=starts_at, count=3
        )
        assert len(occurrences) == 3
        assert all(o.weekday() == 0 for o in occurrences)  # Monday

    def test_compute_next_occurrences_daily_count_1(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, after=starts_at, count=5)
        assert len(occurrences) == 0

    def test_compute_next_occurrences_monthly_last_day(self):
        starts_at = datetime(2030, 1, 31, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=MONTHLY;BYMONTHDAY=-1", starts_at, timezone_str="UTC", after=starts_at, count=3
        )
        assert len(occurrences) == 3
        assert occurrences[0].day == 28  # Feb
        assert occurrences[1].day == 31  # Mar
        assert occurrences[2].day == 30  # Apr

    def test_compute_next_occurrences_with_until(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=DAILY;UNTIL=20300105T235959", starts_at, timezone_str="UTC", after=starts_at, count=10
        )
        assert len(occurrences) == 4

    def test_compute_next_occurrences_exhausted_rrule_returns_empty(self):
        starts_at = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, timezone_str="UTC", count=5)
        assert len(occurrences) == 0

    def test_compute_next_occurrences_timezone_aware_dst(self):
        # starts_at is March 1 09:00 UTC = 10:00 CET (Prague winter time)
        starts_at = datetime(2030, 3, 1, 9, 0, 0, tzinfo=UTC)
        # Use a point before starts_at so March 1 is included
        after = datetime(2030, 2, 28, 0, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=MONTHLY;BYMONTHDAY=1",
            starts_at,
            timezone_str="Europe/Prague",
            after=after,
            count=3,
        )
        assert len(occurrences) == 3
        # March: CET (UTC+1), 10:00 local -> 09:00 UTC
        assert occurrences[0].hour == 9
        # April: CEST (UTC+2), 10:00 local -> 08:00 UTC
        assert occurrences[1].hour == 8
        # May: still CEST
        assert occurrences[2].hour == 8

    def test_compute_next_occurrences_returns_utc(self):
        starts_at = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=DAILY;COUNT=3", starts_at, timezone_str="US/Eastern", after=starts_at, count=5
        )
        for o in occurrences:
            assert o.tzinfo == UTC


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


class TestHogFlowScheduleAPI(APIBaseTest):
    def _create_batch_workflow(self, schedules=None, workflow_status="active"):
        payload = _make_workflow_payload(workflow_status=workflow_status, schedules=schedules)
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_saving_workflow_with_schedule_creates_schedule(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        schedules = HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"])
        assert schedules.count() == 1
        assert schedules.first().rrule == "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"

    def test_schedules_returned_in_response(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        assert len(workflow["schedules"]) == 1
        assert workflow["schedules"][0]["rrule"] == "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"

    def test_active_workflow_with_schedule_creates_pending_run(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        runs = HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending")
        assert runs.count() == 1
        assert runs.first().schedule is not None

    def test_draft_workflow_creates_no_pending_run(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE], workflow_status="draft")
        runs = HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending")
        assert runs.count() == 0

    def test_multiple_schedules_per_workflow(self):
        schedule2 = {**SCHEDULE, "rrule": "FREQ=DAILY;INTERVAL=1"}
        workflow = self._create_batch_workflow(schedules=[SCHEDULE, schedule2])
        schedules = HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"])
        assert schedules.count() == 2
        runs = HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending")
        assert runs.count() == 2

    def test_removing_schedule_deletes_pending_run(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 1

        # Update with empty schedules
        payload = _make_workflow_payload(workflow_status="active", schedules=[])
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}", payload)
        assert response.status_code == status.HTTP_200_OK

        assert HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"]).count() == 0
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 0

    def test_deactivating_workflow_deletes_pending_run(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 1

        payload = {"status": "draft"}
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}", payload)
        assert response.status_code == status.HTTP_200_OK

        # Schedule still exists, but no pending runs
        assert HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"]).count() == 1
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 0

    def test_updating_one_schedule_keeps_another(self):
        schedule2 = {**SCHEDULE, "rrule": "FREQ=DAILY;INTERVAL=1"}
        workflow = self._create_batch_workflow(schedules=[SCHEDULE, schedule2])
        schedules = list(HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"]).order_by("created_at"))
        assert len(schedules) == 2

        # Keep only the first schedule (by ID), remove the second
        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[
                {
                    "id": str(schedules[0].id),
                    "rrule": "FREQ=MONTHLY;BYMONTHDAY=1",
                    "starts_at": "2030-01-01T09:00:00Z",
                    "timezone": "UTC",
                }
            ],
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}", payload)
        assert response.status_code == status.HTTP_200_OK

        remaining = HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"])
        assert remaining.count() == 1
        assert remaining.first().rrule == "FREQ=MONTHLY;BYMONTHDAY=1"

    def test_rrule_validation_rejects_invalid_rrule(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[{**SCHEDULE, "rrule": "INVALID"}],
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("FREQ=MINUTELY;INTERVAL=1",),
            ("FREQ=SECONDLY;INTERVAL=1",),
        ]
    )
    def test_rrule_validation_rejects_too_frequent_schedules(self, rrule_str):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[{**SCHEDULE, "rrule": rrule_str}],
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rrule_validation_accepts_hourly_schedule(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[{**SCHEDULE, "rrule": "FREQ=HOURLY;INTERVAL=1"}],
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED

    def test_scheduled_runs_endpoint(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/scheduled_runs/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1

    def test_schedule_config_cleared_for_non_batch_trigger(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[SCHEDULE],
            trigger_config=EVENT_TRIGGER,
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED

        assert HogFlowSchedule.objects.filter(hog_flow_id=response.json()["id"]).count() == 0
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=response.json()["id"], status="pending").count() == 0

    def test_switching_from_batch_to_event_trigger_clears_schedules(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        assert HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"]).count() == 1
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 1

        payload = _make_workflow_payload(
            workflow_status="active",
            schedules=[SCHEDULE],
            trigger_config=EVENT_TRIGGER,
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}", payload)
        assert response.status_code == status.HTTP_200_OK

        assert HogFlowSchedule.objects.filter(hog_flow_id=workflow["id"]).count() == 0
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"], status="pending").count() == 0

    def test_schedule_with_variable_overrides(self):
        schedule_with_vars = {**SCHEDULE, "variables": {"greeting": "Hello", "count": 5}}
        workflow = self._create_batch_workflow(schedules=[schedule_with_vars])

        schedule = HogFlowSchedule.objects.get(hog_flow_id=workflow["id"])
        assert schedule.variables == {"greeting": "Hello", "count": 5}

        run = HogFlowScheduledRun.objects.get(hog_flow_id=workflow["id"], status="pending")
        assert run.variables["greeting"] == "Hello"
        assert run.variables["count"] == 5

    def test_variable_overrides_merge_with_hogflow_defaults(self):
        """Schedule variables override HogFlow defaults, unset keys keep defaults."""
        payload = _make_workflow_payload(
            workflow_status="active", schedules=[{**SCHEDULE, "variables": {"greeting": "Overridden"}}]
        )
        payload["variables"] = [
            {"key": "greeting", "type": "string", "default": "Default Hello"},
            {"key": "name", "type": "string", "default": "World"},
        ]
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED

        run = HogFlowScheduledRun.objects.get(hog_flow_id=response.json()["id"], status="pending")
        # "greeting" overridden by schedule, "name" kept from HogFlow default
        assert run.variables["greeting"] == "Overridden"
        assert run.variables["name"] == "World"

    def test_schedule_without_variables_uses_hogflow_defaults(self):
        payload = _make_workflow_payload(workflow_status="active", schedules=[SCHEDULE])
        payload["variables"] = [
            {"key": "greeting", "type": "string", "default": "Default Hello"},
        ]
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED

        run = HogFlowScheduledRun.objects.get(hog_flow_id=response.json()["id"], status="pending")
        assert run.variables["greeting"] == "Default Hello"

    def test_multiple_schedules_with_different_variables(self):
        schedules = [
            {**SCHEDULE, "variables": {"region": "US"}},
            {**SCHEDULE, "rrule": "FREQ=DAILY;INTERVAL=1", "variables": {"region": "EU"}},
        ]
        payload = _make_workflow_payload(workflow_status="active", schedules=schedules)
        payload["variables"] = [
            {"key": "region", "type": "string", "default": "Global"},
            {"key": "format", "type": "string", "default": "html"},
        ]
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows", payload)
        assert response.status_code == status.HTTP_201_CREATED

        runs = HogFlowScheduledRun.objects.filter(hog_flow_id=response.json()["id"], status="pending").order_by(
            "run_at"
        )
        assert runs.count() == 2
        # Both runs have "format" from HogFlow defaults
        assert runs[0].variables["format"] == "html"
        assert runs[1].variables["format"] == "html"
        # Each run has its own "region" override
        regions = {runs[0].variables["region"], runs[1].variables["region"]}
        assert regions == {"US", "EU"}

    def test_schedule_with_timezone(self):
        schedule = {**SCHEDULE, "timezone": "US/Eastern"}
        workflow = self._create_batch_workflow(schedules=[schedule])

        s = HogFlowSchedule.objects.get(hog_flow_id=workflow["id"])
        assert s.timezone == "US/Eastern"

    def test_repeated_sync_produces_one_pending_run_per_schedule(self):
        workflow = self._create_batch_workflow(schedules=[SCHEDULE])
        hog_flow = HogFlow.objects.get(id=workflow["id"])

        from products.workflows.backend.utils.schedule_sync import sync_schedule

        sync_schedule(hog_flow, self.team.id)
        sync_schedule(hog_flow, self.team.id)
        sync_schedule(hog_flow, self.team.id)

        runs = HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status="pending")
        assert runs.count() == 1
