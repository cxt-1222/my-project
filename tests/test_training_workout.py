import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from schemas.training_workout import WorkoutCompleteRequest, WorkoutStartRequest
from services.training_workout_service import (
    build_training_stats,
    cancel_workout,
    complete_workout,
    delete_workout,
    list_workouts,
    start_workout,
)


def completed_record(
    workout_id: int,
    completed_at: datetime.datetime,
    *,
    focus: str = "上肢",
    duration_seconds: int = 1800,
    body_weight_kg: float | None = None,
    status: str = "completed",
    exercises: list | None = None,
):
    return SimpleNamespace(
        id=workout_id,
        status=status,
        completed_at=completed_at,
        focus=focus,
        duration_seconds=duration_seconds,
        body_weight_kg=body_weight_kg,
        exercises=exercises or [],
    )


class WorkoutSchemaTests(unittest.TestCase):
    def test_start_requires_plan_and_nonblank_day(self):
        with self.assertRaises(ValidationError):
            WorkoutStartRequest.model_validate({"plan_id": 0, "day": "周一"})
        with self.assertRaises(ValidationError):
            WorkoutStartRequest.model_validate({"plan_id": 2, "day": " "})

    def test_completion_validates_load_repetitions_and_duplicate_names(self):
        valid = WorkoutCompleteRequest.model_validate({
            "exercises": [{"name": "深蹲", "sets": 3, "reps": 10, "weight_kg": 20}],
            "body_weight_kg": 68.5,
        })
        self.assertEqual(valid.exercises[0].weight_kg, 20)
        for payload in (
            {"exercises": [{"name": "深蹲", "sets": 0, "reps": 10}]},
            {"exercises": [{"name": "深蹲", "sets": 3, "reps": 0}]},
            {"exercises": [{"name": "深蹲", "sets": 3, "reps": 10}, {"name": "深蹲", "sets": 2, "reps": 8}]},
            {"exercises": [{"name": "深蹲", "sets": 3, "reps": 10}], "body_weight_kg": 400},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                WorkoutCompleteRequest.model_validate(payload)


class WorkoutOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_workout_snapshots_the_owned_plan_day_and_initializes_reps(self):
        plan = SimpleNamespace(
            id=5,
            user_id=7,
            title="新手计划",
            days=[{
                "day": "周一",
                "focus": "上肢",
                "is_rest_day": False,
                "exercises": [{"name": "哑铃卧推", "sets": 3, "reps": "8-12"}],
            }],
        )
        db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
        with patch("services.training_workout_service.get_training_plan", new_callable=AsyncMock, return_value=plan):
            record = await start_workout(db, 7, plan_id=5, day="周一")

        saved = db.add.call_args.args[0]
        self.assertIs(record, saved)
        self.assertEqual(saved.status, "in_progress")
        self.assertEqual(saved.user_id, 7)
        self.assertEqual(saved.exercises[0]["planned_reps"], "8-12")
        self.assertEqual(saved.exercises[0]["reps"], 8)
        db.commit.assert_awaited_once()

    async def test_start_rejects_rest_day_without_creating_a_record(self):
        plan = SimpleNamespace(
            id=5,
            user_id=7,
            title="新手计划",
            days=[{"day": "周日", "is_rest_day": True, "exercises": []}],
        )
        db = SimpleNamespace(add=Mock(), commit=AsyncMock())
        with patch("services.training_workout_service.get_training_plan", new_callable=AsyncMock, return_value=plan):
            with self.assertRaises(HTTPException) as raised:
                await start_workout(db, 7, plan_id=5, day="周日")
        self.assertEqual(raised.exception.status_code, 422)
        db.add.assert_not_called()

    async def test_list_workouts_filters_by_owner_and_hides_cancelled_rows(self):
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        self.assertEqual(await list_workouts(db, 7, limit=10), [])
        statement = db.execute.await_args.args[0]
        compiled = statement.compile()
        self.assertIn("kh_training_record.user_id", str(compiled))
        self.assertIn("kh_training_record.status", str(compiled))
        self.assertIn(7, compiled.params.values())

    async def test_cancel_only_marks_the_owners_in_progress_workout_cancelled(self):
        record = SimpleNamespace(status="in_progress", cancelled_at=None)
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        result = await cancel_workout(db, 88, 7)
        self.assertIs(result, record)
        self.assertEqual(record.status, "cancelled")
        self.assertIsNotNone(record.cancelled_at)
        db.commit.assert_awaited_once()

    async def test_delete_hides_records_owned_by_another_user(self):
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
            delete=AsyncMock(),
            commit=AsyncMock(),
        )
        with self.assertRaises(HTTPException) as raised:
            await delete_workout(db, workout_id=88, user_id=7)
        self.assertEqual(raised.exception.status_code, 404)
        compiled = db.execute.await_args.args[0].compile()
        self.assertIn("kh_training_record.user_id", str(compiled))
        self.assertIn(7, compiled.params.values())
        db.delete.assert_not_awaited()

    async def test_delete_only_removes_completed_records(self):
        record = SimpleNamespace(status="in_progress")
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)),
            delete=AsyncMock(),
            commit=AsyncMock(),
        )
        with self.assertRaises(HTTPException) as raised:
            await delete_workout(db, workout_id=88, user_id=7)
        self.assertEqual(raised.exception.status_code, 409)
        db.delete.assert_not_awaited()

    async def test_complete_uses_server_elapsed_time_and_plan_snapshot(self):
        started = datetime.datetime(2026, 10, 22, 1, 0, tzinfo=datetime.timezone.utc)
        finished = started + datetime.timedelta(minutes=43)
        record = SimpleNamespace(
            id=88,
            user_id=7,
            status="in_progress",
            started_at=started,
            exercises=[{
                "name": "深蹲",
                "planned_sets": 3,
                "planned_reps": "8-12",
                "sets": 3,
                "reps": 8,
                "weight_kg": None,
            }],
            completed_at=None,
            cancelled_at=None,
            duration_seconds=None,
            body_weight_kg=None,
        )
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        payload = WorkoutCompleteRequest.model_validate({
            "exercises": [{"name": "深蹲", "sets": 4, "reps": 10, "weight_kg": 30}],
            "body_weight_kg": 70,
        })
        with patch("services.training_workout_service._utc_now", return_value=finished):
            result = await complete_workout(db, 88, 7, payload)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.duration_seconds, 43 * 60)
        self.assertEqual(result.exercises[0]["planned_reps"], "8-12")
        self.assertEqual(result.exercises[0]["sets"], 4)
        self.assertEqual(result.body_weight_kg, 70)
        db.commit.assert_awaited_once()

    def test_stats_use_local_week_streak_volume_focus_and_all_time_weight_change(self):
        # 2026-10-22 is Thursday in the app's Asia/Shanghai timezone.
        now = datetime.datetime(2026, 10, 22, 3, 0, tzinfo=datetime.timezone.utc)
        records = [
            completed_record(
                1,
                datetime.datetime(2026, 10, 21, 13, 0, tzinfo=datetime.timezone.utc),
                focus="上肢",
                duration_seconds=2400,
                body_weight_kg=70,
                exercises=[{"sets": 3, "reps": 10, "weight_kg": 20}],
            ),
            completed_record(
                2,
                datetime.datetime(2026, 10, 22, 2, 0, tzinfo=datetime.timezone.utc),
                focus="上肢",
                duration_seconds=1800,
                body_weight_kg=69.5,
                exercises=[
                    {"sets": 2, "reps": 8, "weight_kg": 10},
                    {"sets": 3, "reps": 12, "weight_kg": None},
                ],
            ),
            completed_record(
                3,
                datetime.datetime(2026, 10, 18, 10, 0, tzinfo=datetime.timezone.utc),
                focus="腿部",
                body_weight_kg=71,
            ),
            completed_record(
                4,
                datetime.datetime(2026, 10, 22, 2, 30, tzinfo=datetime.timezone.utc),
                status="cancelled",
                body_weight_kg=60,
            ),
        ]

        stats = build_training_stats(records, now=now)

        self.assertEqual(stats["week_start_date"], datetime.date(2026, 10, 19))
        self.assertEqual(stats["week_workouts_count"], 2)
        self.assertEqual(stats["streak_days"], 2)
        self.assertEqual(stats["week_duration_seconds"], 4200)
        self.assertEqual(stats["week_volume_kg"], 760)
        self.assertEqual(stats["primary_focus"], "上肢")
        self.assertEqual(stats["latest_body_weight_kg"], 69.5)
        self.assertEqual(stats["body_weight_change_kg"], -1.5)

    def test_stats_report_zero_streak_and_no_weight_change_with_missing_data(self):
        now = datetime.datetime(2026, 10, 22, 3, 0, tzinfo=datetime.timezone.utc)
        records = [completed_record(1, datetime.datetime(2026, 10, 19, 10, tzinfo=datetime.timezone.utc))]
        stats = build_training_stats(records, now=now)
        self.assertEqual(stats["streak_days"], 0)
        self.assertIsNone(stats["body_weight_change_kg"])


if __name__ == "__main__":
    unittest.main()
