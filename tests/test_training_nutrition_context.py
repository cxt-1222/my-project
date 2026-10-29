from decimal import Decimal
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.ai import (
    _build_messages,
    _do_invoke,
    _is_training_nutrition_request,
    _load_account_training_plan,
    _prepare_materials,
)
from schemas.catalog import (
    CatalogSourceReference,
    FoodCatalogResponse,
    FoodNutritionResponse,
    NutrientValues,
    RecipeCatalogResponse,
    RecipeNutritionIngredientIssue,
    RecipeNutritionResponse,
)
from services.nutrition_catalog_context import (
    format_food_evidence,
    format_recipe_evidence,
    named_food_query,
    named_recipe_query,
)


def source_reference(**changes):
    values = {
        "dataset": "approved-fixtures",
        "repository": "example/approved-fixtures",
        "revision": "a" * 40,
        "source_record_id": "record-1",
        "content_sha256": "b" * 64,
    }
    values.update(changes)
    return CatalogSourceReference(**values)


def food_response(**changes):
    values = {
        "id": 5,
        "name": "鸡胸肉",
        "source_key": "approved-source",
        "source": source_reference(source_record_id="chicken-1"),
        "nutrition": FoodNutritionResponse(
            basis="per_100g",
            calories_kcal=Decimal("165"),
            protein_g=Decimal("31"),
            carbohydrate_g=Decimal("0"),
            fat_g=Decimal("3.6"),
            complete=True,
            per_100g=NutrientValues(
                basis="per_100g",
                calories_kcal=Decimal("165"),
                protein_g=Decimal("31"),
                carbohydrate_g=Decimal("0"),
                fat_g=Decimal("3.6"),
                complete=True,
            ),
            normalization_note="原始数据已按每 100 克计量，未进行额外换算。",
        ),
    }
    values.update(changes)
    return FoodCatalogResponse(**values)


def recipe_response(*, complete=True, missing_ingredients=None):
    missing_fields = [] if complete else ["calories_kcal"]
    return RecipeCatalogResponse(
        id=8,
        title="训练后燕麦碗",
        servings=Decimal("2"),
        source=source_reference(source_record_id="bowl-1"),
        source_name="Approved recipes",
        source_url="",
        source_revision="fixture",
        source_license="approved",
        ingredients=[],
        nutrition=RecipeNutritionResponse(
            total=NutrientValues(
                basis="recipe_total",
                calories_kcal=Decimal("500") if complete else None,
                protein_g=Decimal("20") if complete else None,
                carbohydrate_g=Decimal("70") if complete else None,
                fat_g=Decimal("10") if complete else None,
                missing_fields=missing_fields,
                complete=complete,
            ),
            per_serving=NutrientValues(
                basis="per_serving",
                calories_kcal=Decimal("250") if complete else None,
                protein_g=Decimal("10") if complete else None,
                carbohydrate_g=Decimal("35") if complete else None,
                fat_g=Decimal("5") if complete else None,
                missing_fields=missing_fields,
                complete=complete,
            ),
            missing_ingredients=missing_ingredients or [],
            calculation="总和 = Σ(营养值 × 克数 ÷ 100)，每份值 = 总和 ÷ 菜谱份数。",
            complete=complete,
        ),
    )


class TrainingNutritionDetectionTests(unittest.TestCase):
    def test_distinguishes_training_diet_from_factual_training_questions(self):
        for query in (
            "训练后吃什么",
            "力量训练期间怎么补充蛋白质",
            "给我一份增肌餐建议",
            "增肌阶段吃什么",
            "健身前后饮食怎么安排",
        ):
            with self.subTest(query=query):
                self.assertTrue(_is_training_nutrition_request(query))

        for query in (
            "哑铃深蹲的动作步骤",
            "安排一周训练计划",
            "减脂训练动作怎么安排",
            "只根据知识库说明鸡胸肉的热量",
        ):
            with self.subTest(query=query):
                self.assertFalse(_is_training_nutrition_request(query))


class TrainingPlanContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_plan_is_loaded_only_for_authenticated_user(self):
        plan = SimpleNamespace(id=101, user_id=42, title="我的计划")
        db = object()
        current_user = SimpleNamespace(id=42)
        with patch(
            "api.ai.list_training_plans",
            new_callable=AsyncMock,
            return_value=[plan],
        ) as list_plans:
            loaded = await _load_account_training_plan(db, current_user)

        self.assertIs(loaded, plan)
        list_plans.assert_awaited_once_with(db, 42, limit=1, offset=0)

    def test_prompt_includes_own_profile_plan_and_strict_nutrition_rules(self):
        plan = SimpleNamespace(
            title="我的增肌安排",
            goal="增肌",
            experience="刚开始",
            days=[{
                "day": "周一",
                "focus": "上肢",
                "exercises": [{"name": "哑铃卧推", "sets": 3, "reps": "8-12"}],
            }],
        )
        profile = SimpleNamespace(
            height=175,
            weight=70,
            age=25,
            sex="女",
            goal="增肌",
            experience="刚开始",
            weekly_training_days=3,
            equipment="哑铃",
            limitations=None,
        )
        messages = _build_messages(
            "训练后吃鸡胸肉合适吗",
            "[1] 类型:结构化营养目录 | 标题:食材目录：鸡胸肉\n营养值",
            profile=profile,
            training_plan=plan,
        )

        self.assertIn("训练饮食回答约束", messages[0].content)
        prompt = messages[-1].content
        self.assertIn("当前账号最新训练安排", prompt)
        self.assertIn("我的增肌安排", prompt)
        self.assertIn("哑铃卧推", prompt)
        self.assertIn('"当前目标": "增肌"', prompt)

    def test_prompt_explicitly_reports_missing_training_plan(self):
        messages = _build_messages("训练后怎么吃", "（无检索资料）", profile=None)

        self.assertIn("用户尚未保存有效训练安排", messages[-1].content)
        self.assertIn("数据不完整", messages[0].content)

    async def test_training_diet_invoke_loads_profile_and_plan_for_current_user(self):
        profile = SimpleNamespace(
            height=None,
            weight=None,
            age=None,
            sex=None,
            goal="增肌",
            experience=None,
            weekly_training_days=3,
            equipment=None,
            limitations=None,
        )
        plan = SimpleNamespace(
            title="本人计划",
            goal="增肌",
            experience=None,
            days=[{"day": "周一", "is_rest_day": True, "exercises": []}],
        )
        llm = SimpleNamespace(
            ainvoke=AsyncMock(return_value=SimpleNamespace(content="训练后饮食建议"))
        )
        with (
            patch("api.ai._get_history", new_callable=AsyncMock, return_value=[]),
            patch("api.ai._recall_chat_memories", new_callable=AsyncMock, return_value=[]),
            patch(
                "api.ai._load_account_fitness_profile",
                new_callable=AsyncMock,
                return_value=profile,
            ) as load_profile,
            patch(
                "api.ai._load_account_training_plan",
                new_callable=AsyncMock,
                return_value=plan,
            ) as load_plan,
            patch("api.ai._save_message", new_callable=AsyncMock),
            patch(
                "api.ai._prepare_materials",
                new_callable=AsyncMock,
                return_value=("[1] 类型:结构化营养目录\n鸡胸肉", []),
            ),
            patch("api.ai._extract_and_store_chat_memories", new_callable=AsyncMock),
            patch("api.ai.model", llm),
        ):
            result = await _do_invoke(
                "训练后吃鸡胸肉合适吗",
                5,
                True,
                None,
                object(),
                SimpleNamespace(id=42),
            )

        load_profile.assert_awaited_once()
        load_plan.assert_awaited_once()
        self.assertEqual(load_profile.await_args.args[1].id, 42)
        self.assertEqual(load_plan.await_args.args[1].id, 42)
        self.assertIn("本人计划", llm.ainvoke.await_args.args[0][-1].content)
        self.assertEqual(result["content"], "训练后饮食建议")


class NutritionEvidenceFormattingTests(unittest.TestCase):
    def test_food_evidence_includes_source_basis_and_values(self):
        evidence = format_food_evidence(food_response())

        self.assertEqual(evidence.kind, "food")
        self.assertIn("每 100 克", evidence.text)
        self.assertIn("31 g", evidence.text)
        self.assertIn("approved-fixtures", evidence.text)
        self.assertEqual(evidence.source["sourceRecordId"], "chicken-1")

    def test_incomplete_recipe_is_labeled_not_estimated(self):
        evidence = format_recipe_evidence(recipe_response(
            complete=False,
            missing_ingredients=[
                RecipeNutritionIngredientIssue(
                    position=1,
                    name="牛奶",
                    reason="关联食材未获准或已停用",
                ),
            ],
        ))

        self.assertIn("营养结果不完整", evidence.text)
        self.assertIn("牛奶", evidence.text)
        self.assertIn("缺失", evidence.text)

    def test_named_queries_require_approval_and_scope(self):
        food_sql = str(named_food_query(
            "训练后吃鸡胸肉",
            dataset="approved-fixtures",
            source_record_id="chicken-1",
        ).compile())
        recipe_sql = str(named_recipe_query(
            "训练后吃燕麦碗",
            dataset="approved-fixtures",
        ).compile())

        for sql in (food_sql, recipe_sql):
            self.assertIn("license_status", sql)
            self.assertIn("record_status", sql)
            self.assertIn("import_status", sql)
            self.assertIn("metadata_license_status", sql)
            self.assertIn("strpos", sql)
        self.assertIn("dataset", food_sql)
        self.assertIn("upstream_id", food_sql)


class NutritionEvidenceAITests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_materials_uses_the_same_citation_index_for_context_and_source(self):
        evidence = format_food_evidence(food_response())
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [42]),
        )))

        with (
            patch("api.ai.search_milvus_data", new_callable=AsyncMock, return_value={"data": []}),
            patch("api.ai.get_es", new_callable=AsyncMock, return_value=object()),
            patch("api.ai.search_data", new_callable=AsyncMock, return_value={"data": []}),
            patch("api.ai.rerank_call", new_callable=AsyncMock, return_value=[]),
            patch(
                "api.ai.load_named_catalog_evidence",
                new_callable=AsyncMock,
                return_value=[evidence],
            ) as load_evidence,
            patch("api.ai.web_search", new_callable=AsyncMock) as web_search,
        ):
            context, sources = await _prepare_materials(
                "训练后吃鸡胸肉",
                5,
                True,
                db,
                SimpleNamespace(id=42),
            )

        load_evidence.assert_awaited_once()
        web_search.assert_not_awaited()
        self.assertIn("[1] 类型:结构化营养目录", context)
        self.assertIn(evidence.text, context)
        self.assertEqual(sources[0]["index"], 1)
        self.assertEqual(sources[0]["sourceType"], "catalog")
        self.assertEqual(sources[0]["documentTitle"], evidence.title)
        self.assertEqual(sources[0]["catalogSource"]["sourceRecordId"], "chicken-1")


if __name__ == "__main__":
    unittest.main()
