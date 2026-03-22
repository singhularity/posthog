from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest import TestCase

import pytz
from parameterized import parameterized
from rest_framework import status

from posthog.models.hog_flow.hog_flow import HogFlow

from products.workflows.backend.models.hog_flow_scheduled_run import HogFlowScheduledRun
from products.workflows.backend.utils.rrule_utils import compute_next_occurrences, validate_rrule

BATCH_TRIGGER = {
    "type": "batch",
    "filters": {"properties": [{"key": "$browser", "type": "person", "value": ["Chrome"], "operator": "exact"}]},
}


def _make_workflow_payload(workflow_status="draft", schedule_config=None):
    payload = {
        "name": "Test Batch Workflow",
        "status": workflow_status,
        "actions": [
            {
                "id": "trigger_node",
                "name": "trigger",
                "type": "trigger",
                "config": BATCH_TRIGGER,
            }
        ],
    }
    if schedule_config is not None:
        payload["schedule_config"] = schedule_config
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
        assert occurrences[0].weekday() == 0

    def test_compute_next_occurrences_daily_count_1(self):
        starts_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
        after = datetime(2026, 3, 16, 11, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, after=after, count=5)
        assert len(occurrences) == 1

    def test_compute_next_occurrences_monthly_last_day(self):
        starts_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=MONTHLY;BYMONTHDAY=-1", starts_at, after=starts_at, count=4)
        assert len(occurrences) == 4
        assert occurrences[0].day == 31
        assert occurrences[1].day == 30
        assert occurrences[2].day == 31
        assert occurrences[3].day == 30

    def test_compute_next_occurrences_with_until(self):
        starts_at = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=WEEKLY;UNTIL=20260401T000000Z", starts_at, after=starts_at, count=10
        )
        for occ in occurrences:
            assert occ.replace(tzinfo=None) <= datetime(2026, 4, 1, 0, 0, 0)

    def test_compute_next_occurrences_exhausted_rrule_returns_empty(self):
        starts_at = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
        after = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences("FREQ=DAILY;COUNT=1", starts_at, after=after, count=5)
        assert len(occurrences) == 0

    def test_compute_next_occurrences_timezone_aware_dst(self):
        """9 AM Europe/Prague should stay at 9 AM local across DST (March 29, 2026)."""
        prague = pytz.timezone("Europe/Prague")
        starts_at = prague.localize(datetime(2026, 3, 16, 9, 0, 0))

        occurrences = compute_next_occurrences(
            "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
            starts_at,
            timezone_str="Europe/Prague",
            after=starts_at,
            count=4,
        )
        assert len(occurrences) == 4
        assert occurrences[0].astimezone(prague).hour == 9
        assert occurrences[0].astimezone(pytz.utc).hour == 8
        assert occurrences[2].astimezone(prague).hour == 9
        assert occurrences[2].astimezone(pytz.utc).hour == 7

    def test_compute_next_occurrences_returns_utc(self):
        starts_at = datetime(2026, 3, 16, 9, 0, 0, tzinfo=UTC)
        occurrences = compute_next_occurrences(
            "FREQ=DAILY;INTERVAL=1", starts_at, timezone_str="US/Eastern", after=starts_at, count=3
        )
        for occ in occurrences:
            assert occ.tzinfo is not None
            offset = occ.utcoffset()
            assert offset is not None
            assert offset.total_seconds() == 0


class TestHogFlowScheduleAPI(APIBaseTest):
    def _create_batch_workflow(self, schedule_config=None, workflow_status="active"):
        payload = _make_workflow_payload(workflow_status=workflow_status, schedule_config=schedule_config)
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_saving_workflow_with_schedule_sets_schedule_config(self):
        schedule_config = {
            "rrule": "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "Europe/Prague",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        hog_flow = HogFlow.objects.get(id=workflow["id"])
        assert hog_flow.schedule_config is not None
        assert hog_flow.schedule_config["rrule"] == "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO"
        assert hog_flow.schedule_config["timezone"] == "Europe/Prague"

    def test_saving_active_workflow_with_schedule_creates_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert pending.count() == 1

    def test_saving_workflow_with_count_1_creates_one_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;COUNT=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert pending.count() == 1

    def test_removing_schedule_deletes_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/",
            {"schedule_config": None},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        hog_flow = HogFlow.objects.get(id=workflow["id"])
        assert hog_flow.schedule_config is None

        pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert pending.count() == 0

    def test_deactivating_workflow_deletes_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=WEEKLY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/",
            {"status": "draft"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert pending.count() == 0

    def test_draft_workflow_creates_no_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config, workflow_status="draft")

        pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert pending.count() == 0

        hog_flow = HogFlow.objects.get(id=workflow["id"])
        assert hog_flow.schedule_config is not None

    def test_rrule_validation_rejects_invalid_rrule(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedule_config={"rrule": "NOT_VALID", "starts_at": "2030-01-01T12:00:00.000Z", "timezone": "UTC"},
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("FREQ=MINUTELY;INTERVAL=30",),
            ("FREQ=SECONDLY;INTERVAL=1",),
            ("FREQ=MINUTELY;INTERVAL=1",),
        ]
    )
    def test_rrule_validation_rejects_too_frequent_schedules(self, rrule_str):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedule_config={"rrule": rrule_str, "starts_at": "2030-01-01T12:00:00.000Z", "timezone": "UTC"},
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_rrule_validation_accepts_hourly_schedule(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedule_config={
                "rrule": "FREQ=HOURLY;INTERVAL=1",
                "starts_at": "2030-01-01T12:00:00.000Z",
                "timezone": "UTC",
            },
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/", payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED

    def test_rrule_validation_rejects_missing_starts_at(self):
        payload = _make_workflow_payload(
            workflow_status="active",
            schedule_config={"rrule": "FREQ=DAILY;INTERVAL=1", "timezone": "UTC"},
        )
        response = self.client.post(f"/api/projects/{self.team.id}/hog_flows/", payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_scheduled_runs_endpoint(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        response = self.client.get(f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/scheduled_runs/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["status"] == "pending"

    def test_updating_schedule_replaces_pending_run(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        old_run = HogFlowScheduledRun.objects.get(hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_flows/{workflow['id']}/",
            {
                "schedule_config": {
                    "rrule": "FREQ=WEEKLY;INTERVAL=1",
                    "starts_at": "2030-01-01T12:00:00.000Z",
                    "timezone": "UTC",
                }
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        assert not HogFlowScheduledRun.objects.filter(id=old_run.id).exists()

        new_pending = HogFlowScheduledRun.objects.filter(
            hog_flow_id=workflow["id"], status=HogFlowScheduledRun.Status.PENDING
        )
        assert new_pending.count() == 1

    def test_no_schedule_creates_nothing(self):
        workflow = self._create_batch_workflow()
        hog_flow = HogFlow.objects.get(id=workflow["id"])
        assert hog_flow.schedule_config is None
        assert HogFlowScheduledRun.objects.filter(hog_flow_id=workflow["id"]).count() == 0

    def test_repeated_sync_produces_exactly_one_pending_run(self):
        """Calling sync_schedule multiple times should always result in exactly one pending run."""
        from products.workflows.backend.utils.schedule_sync import sync_schedule

        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T12:00:00.000Z",
            "timezone": "UTC",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)
        hog_flow = HogFlow.objects.get(id=workflow["id"])

        # Call sync multiple times
        for _ in range(5):
            sync_schedule(hog_flow, self.team.id)

        pending = HogFlowScheduledRun.objects.filter(hog_flow=hog_flow, status=HogFlowScheduledRun.Status.PENDING)
        assert pending.count() == 1

    def test_schedule_with_timezone_stores_timezone(self):
        schedule_config = {
            "rrule": "FREQ=DAILY;INTERVAL=1",
            "starts_at": "2030-01-01T08:00:00.000Z",
            "timezone": "US/Eastern",
        }
        workflow = self._create_batch_workflow(schedule_config=schedule_config)

        hog_flow = HogFlow.objects.get(id=workflow["id"])
        assert hog_flow.schedule_config is not None
        assert hog_flow.schedule_config["timezone"] == "US/Eastern"
