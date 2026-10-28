import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from api.ai import _load_account_fitness_profile, ai_invoke, ai_invoke_stream_with_profile
from models.fitness_profile import FitnessProfileModel
from schemas.fitness_profile import FitnessProfile


class FitnessProfileSchemaTests(unittest.TestCase):
    def test_accepts_all_supported_profile_values(self):
        profile = FitnessProfile(
            height=175,
            weight=72.5,
            age=25,
            sex="不愿透露",
            goal="增肌",
            experience="刚开始",
            weekly_training_days=3,
            equipment="哑铃、弹力带",
            limitations="避免跳跃动作",
        )
        self.assertEqual(profile.height, 175)
        self.assertEqual(profile.weight, 72.5)
        self.assertEqual(profile.age, 25)
        self.assertEqual(profile.sex, "不愿透露")
        self.assertEqual(profile.goal, "增肌")
        self.assertEqual(profile.experience, "刚开始")
        self.assertEqual(profile.weekly_training_days, 3)
        self.assertEqual(profile.equipment, "哑铃、弹力带")
        self.assertEqual(profile.limitations, "避免跳跃动作")

    def test_empty_profile_is_valid_and_represents_cleared_fields(self):
        self.assertEqual(
            FitnessProfile().model_dump(),
            {
                "height": None,
                "weight": None,
                "age": None,
                "sex": None,
                "goal": None,
                "experience": None,
                "weekly_training_days": None,
                "equipment": None,
                "limitations": None,
            },
        )

    def test_rejects_out_of_range_measurements_and_unknown_options(self):
        for values in (
            {"height": 79},
            {"height": 251},
            {"weight": 24},
            {"weight": 301},
            {"age": 12},
            {"age": 101},
            {"sex": "其他任意输入"},
            {"weekly_training_days": 0},
            {"weekly_training_days": 8},
            {"equipment": "x" * 301},
            {"limitations": "x" * 501},
            {"goal": "随便写一段文本"},
            {"experience": "自定义"},
            {"user_id": 999},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                FitnessProfile(**values)


class FitnessProfileAIIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_profile_loader_reads_by_authenticated_user_id(self):
        db = object()
        current_user = SimpleNamespace(id=42)
        db_profile = FitnessProfileModel(
            user_id=42,
            height=175,
            weight=72.5,
            age=25,
            sex="女",
            goal="增肌",
            experience="刚开始",
            weekly_training_days=3,
            equipment="哑铃",
            limitations="避免跳跃",
        )

        with patch("api.ai.get_fitness_profile", new_callable=AsyncMock, return_value=db_profile) as get_profile:
            profile = await _load_account_fitness_profile(db, current_user)

        get_profile.assert_awaited_once_with(db, 42)
        self.assertEqual(profile.model_dump(), {
            "height": 175,
            "weight": 72.5,
            "age": 25,
            "sex": "女",
            "goal": "增肌",
            "experience": "刚开始",
            "weekly_training_days": 3,
            "equipment": "哑铃",
            "limitations": "避免跳跃",
        })

    async def test_ai_profile_loader_returns_none_when_account_has_no_profile(self):
        with patch("api.ai.get_fitness_profile", new_callable=AsyncMock, return_value=None) as get_profile:
            profile = await _load_account_fitness_profile(object(), SimpleNamespace(id=7))

        get_profile.assert_awaited_once()
        self.assertIsNone(profile)

    async def test_regular_ai_endpoint_ignores_legacy_request_profile(self):
        db = object()
        user = SimpleNamespace(id=7)
        legacy_body = {"profile": {"height": 190, "goal": "client-controlled"}, "other": "ignored"}

        with patch("api.ai._do_invoke", new_callable=AsyncMock, return_value={"content": "ok"}) as invoke:
            result = await ai_invoke(
                query="给我建议",
                profile_request=legacy_body,
                db=db,
                current_user=user,
            )

        self.assertEqual(result, {"content": "ok"})
        invoke.assert_awaited_once_with("给我建议", 5, False, None, db, user)

    async def test_streaming_ai_endpoint_ignores_legacy_request_profile(self):
        db = object()
        user = SimpleNamespace(id=7)
        legacy_body = {"profile": {"height": 190, "goal": "client-controlled"}, "other": "ignored"}

        with patch("api.ai._do_invoke_stream", new_callable=AsyncMock, return_value="stream") as invoke_stream:
            result = await ai_invoke_stream_with_profile(
                query="给我建议",
                profile_request=legacy_body,
                db=db,
                current_user=user,
            )

        self.assertEqual(result, "stream")
        invoke_stream.assert_awaited_once_with("给我建议", 5, False, None, db, user)


if __name__ == "__main__":
    unittest.main()
