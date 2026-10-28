import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from schemas.fitness_profile import FitnessProfile
from schemas.training_plan import TrainingPlanGenerateRequest, TrainingPlanPayload
from services.training_plan_service import (
    create_training_plan,
    get_training_plan,
    list_training_plans,
    update_training_plan,
)


def valid_payload() -> TrainingPlanPayload:
    return TrainingPlanPayload.model_validate({
        "title": "新手增肌计划",
        "goal": "增肌",
        "experience": "刚开始",
        "days": [
            {
                "day": "周一",
                "focus": "上肢",
                "exercises": [
                    {"name": "哑铃卧推", "sets": 3, "reps": "8-12", "rest_seconds": 90}
                ],
            },
            {"day": "周二", "is_rest_day": True},
        ],
    })


class TrainingPlanSchemaTests(unittest.TestCase):
    def test_accepts_plan_with_training_and_rest_days(self):
        payload = valid_payload()
        self.assertEqual(payload.title, "新手增肌计划")
        self.assertEqual(payload.days[0].exercises[0].name, "哑铃卧推")
        self.assertTrue(payload.days[1].is_rest_day)

    def test_rejects_empty_training_day_or_exercises_on_rest_day(self):
        invalid_plans = (
            {"title": "计划", "days": [{"day": "周一"}]},
            {
                "title": "计划",
                "days": [{
                    "day": "周日",
                    "is_rest_day": True,
                    "exercises": [{"name": "深蹲", "sets": 3, "reps": "10"}],
                }],
            },
        )
        for values in invalid_plans:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                TrainingPlanPayload.model_validate(values)

    def test_rejects_duplicate_day_names(self):
        with self.assertRaises(ValidationError):
            TrainingPlanPayload.model_validate({
                "title": "重复日期计划",
                "days": [
                    {"day": "周一", "exercises": [{"name": "深蹲", "sets": 3, "reps": "10"}]},
                    {"day": "周一", "is_rest_day": True},
                ],
            })

    def test_rejects_invalid_owner_fields_and_out_of_range_values(self):
        base = valid_payload().model_dump()
        for changes in (
            {"user_id": 999},
            {"goal": "自定义目标"},
            {"days": [{"day": "周一", "exercises": [{"name": "深蹲", "sets": 0, "reps": "10"}]}]},
            {"days": [{"day": "周一", "exercises": [{"name": "深蹲", "sets": 3, "reps": "10", "unknown": True}]}]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                TrainingPlanPayload.model_validate({**base, **changes})


class TrainingPlanOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_lookup_filters_by_plan_and_authenticated_owner(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))

        with self.assertRaises(HTTPException) as raised:
            await get_training_plan(db, plan_id=101, user_id=42)

        self.assertEqual(raised.exception.status_code, 404)
        statement = db.execute.await_args.args[0]
        compiled = statement.compile()
        self.assertIn("kh_training_plan.id", str(compiled))
        self.assertIn("kh_training_plan.user_id", str(compiled))
        self.assertIn(101, compiled.params.values())
        self.assertIn(42, compiled.params.values())

    async def test_plan_list_is_scoped_to_authenticated_owner(self):
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        plans = await list_training_plans(db, user_id=42, limit=10, offset=0)

        self.assertEqual(plans, [])
        statement = db.execute.await_args.args[0]
        compiled = statement.compile()
        self.assertIn("kh_training_plan.user_id", str(compiled))
        self.assertIn(42, compiled.params.values())

    async def test_create_uses_owner_id_from_service_argument(self):
        db = SimpleNamespace(
            add=Mock(),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )

        plan = await create_training_plan(db, user_id=42, payload=valid_payload())

        db.add.assert_called_once()
        saved = db.add.call_args.args[0]
        self.assertEqual(saved.user_id, 42)
        self.assertEqual(saved.title, "新手增肌计划")
        self.assertEqual(saved.days[0]["exercises"][0]["name"], "哑铃卧推")
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(saved)
        self.assertIs(plan, saved)

    async def test_update_changes_only_the_plan_returned_for_owner(self):
        existing = SimpleNamespace(
            id=101,
            user_id=42,
            title="旧计划",
            goal=None,
            experience=None,
            days=[],
            update_at=None,
        )
        db = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

        with patch(
            "services.training_plan_service.get_training_plan",
            new_callable=AsyncMock,
            return_value=existing,
        ) as get_plan:
            updated = await update_training_plan(
                db, plan_id=101, user_id=42, payload=valid_payload()
            )

        get_plan.assert_awaited_once_with(db, 101, 42)
        self.assertEqual(updated.title, "新手增肌计划")
        self.assertEqual(updated.user_id, 42)
        self.assertEqual(updated.days[0]["exercises"][0]["sets"], 3)
        self.assertIsNotNone(updated.update_at)
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(existing)


class TrainingPlanPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_returns_unpersisted_preview_and_filters_unknown_source_refs(self):
        from api.training import preview_training_plan

        generated = {
            "title": "一周增肌草稿",
            "goal": "减脂",
            "experience": "比较规律",
            "days": [{
                "day": "周一",
                "focus": "上肢",
                "exercises": [
                    {"name": "哑铃卧推", "sets": 3, "reps": "8-12", "evidence_type": "knowledge_base", "source_refs": [1]},
                    {"name": "未知动作", "sets": 2, "reps": "10", "evidence_type": "knowledge_base", "source_refs": [99]},
                ],
            }],
            "general_notes": ["器械条件未提供，请先核对。"],
        }
        profile = FitnessProfile(
            goal="增肌",
            experience="刚开始",
            height=175,
            weight=72,
            age=25,
            sex="女",
            weekly_training_days=3,
            equipment="哑铃",
            limitations="避免跳跃动作",
        )
        db = Mock()
        source = {"index": 1, "documentId": "31", "documentTitle": "动作知识库 023", "score": 0.8, "sourceType": "doc"}
        llm = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps(generated, ensure_ascii=False))))
        with (
            patch("api.training._load_account_fitness_profile", new_callable=AsyncMock, return_value=profile),
            patch("api.training._prepare_materials", new_callable=AsyncMock, return_value=("[1] 类型:知识库 | 标题:动作知识库 023\n动作名称：哑铃卧推\n主要目标肌群：胸肌", [source])),
            patch("api.training.model", llm),
        ):
            result = await preview_training_plan(
                TrainingPlanGenerateRequest(request="根据档案安排一周计划"),
                db=db,
                current_user=SimpleNamespace(id=42),
            )

        self.assertEqual(result["plan"].goal, "增肌")
        self.assertEqual(result["plan"].experience, "刚开始")
        exercises = result["plan"].days[0].exercises
        self.assertEqual(exercises[0].evidence_type, "knowledge_base")
        self.assertEqual(exercises[0].source_refs, [1])
        self.assertEqual(exercises[1].evidence_type, "general_advice")
        self.assertEqual(exercises[1].source_refs, [])
        self.assertEqual(result["sources"], [source])
        generated_prompt = llm.ainvoke.await_args.args[0][1].content
        self.assertIn("可用器械：哑铃", generated_prompt)
        self.assertIn("每周可训练天数：3", generated_prompt)
        self.assertIn("身体限制：避免跳跃动作", generated_prompt)
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_generate_request_rejects_unknown_fields_and_invalid_training_days(self):
        for payload in (
            {"request": "安排训练", "user_id": 42},
            {"request": "安排训练", "training_days": 8},
            {"request": " "},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                TrainingPlanGenerateRequest.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
