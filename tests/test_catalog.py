import datetime
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.catalog import catalog_router
from api.ai import _prepare_materials
from core.security import get_current_user
from schemas.catalog import FoodNutritionResponse
from services.catalog_service import (
    _exercise_response,
    _food_nutrition,
    _videos_by_exercise,
    approved_source_document_query,
    calculate_recipe_nutrition,
    exercise_query,
    food_query,
    recipe_query,
)


def import_row(**changes):
    values = {
        "id": 9,
        "dataset": "approved-fixture",
        "repository": "example/approved-fixture",
        "revision": "a" * 40,
        "import_status": "imported",
        "metadata_license_status": "approved",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def exercise_row(**changes):
    values = {
        "id": 3,
        "upstream_id": "squat-1",
        "name": "Dumbbell Squat",
        "name_normalized": "dumbbell squat",
        "aliases": ["哑铃深蹲"],
        "normalized_fields": {
            "body_part": "upper legs",
            "target_muscle": "glutes",
            "equipment": "dumbbell",
            "steps": ["Lower into a squat."],
            "common_mistakes": None,
        },
        "content_sha256": "b" * 64,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def food_row(**changes):
    values = {
        "id": 5,
        "upstream_id": "oats-1",
        "source_key": "usda-approx",
        "name": "Oats",
        "nutrition_basis": "per_100g",
        "edible_value": Decimal("100"),
        "nutrients_raw": {
            "energyKCal": "389",
            "protein": "16.9",
            "CHO": "66.3",
            "fat": "6.9",
        },
        "content_sha256": "c" * 64,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class CatalogRouteTests(unittest.TestCase):
    def test_catalog_routes_require_authentication_and_are_read_only(self):
        methods = {}
        for route in catalog_router.routes:
            methods.setdefault(route.path, set()).update(route.methods)
            dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
            self.assertIn(get_current_user, dependency_calls)

        self.assertEqual(methods["/catalog/exercises"], {"GET"})
        self.assertEqual(methods["/catalog/exercises/{exercise_id}"], {"GET"})
        self.assertEqual(methods["/catalog/foods"], {"GET"})
        self.assertEqual(methods["/catalog/foods/{food_id}"], {"GET"})
        self.assertEqual(methods["/catalog/recipes"], {"GET"})
        self.assertEqual(methods["/catalog/recipes/{recipe_id}"], {"GET"})


class CatalogApprovalFilterTests(unittest.TestCase):
    def test_every_catalog_query_requires_active_approved_records_and_approved_import(self):
        statements = (
            exercise_query(query="squat"),
            food_query(query="oats"),
            recipe_query(query="oats"),
        )
        for statement in statements:
            sql = str(statement.compile())
            self.assertIn("kh_dataset_import.import_status", sql)
            self.assertIn("kh_dataset_import.metadata_license_status", sql)
            self.assertIn("license_status", sql)
            self.assertIn("record_status", sql)

        food_sql = str(food_query(query="oats").compile())
        self.assertIn("kh_food_catalog.nutrition_basis !=", food_sql)

    def test_exact_name_search_uses_normalized_equality_not_partial_match(self):
        statement = exercise_query(query="Dumbbell Squat", exact_name=True)
        sql = str(statement.compile())

        self.assertIn("kh_exercise_catalog.name_normalized =", sql)
        self.assertNotIn("lower(kh_exercise_catalog.name_normalized) LIKE", sql)

    def test_source_document_scope_resolves_only_approved_active_mappings(self):
        statement = approved_source_document_query(
            dataset="approved-fixture",
            source_record_id="squat-1",
        )
        sql = str(statement.compile())
        self.assertIn("kh_knowledge_source_mapping.mapping_status", sql)
        self.assertIn("kh_dataset_import.import_status", sql)
        self.assertIn("kh_exercise_catalog", sql)
        self.assertIn("kh_recipe_catalog", sql)
        self.assertIn("kh_knowledge_source_mapping.source_record_id", sql)
        params = statement.compile().params.values()
        self.assertIn("approved-fixture", params)
        self.assertIn("squat-1", params)


class CatalogResponseTests(unittest.IsolatedAsyncioTestCase):
    def test_food_nutrition_keeps_raw_values_and_marks_missing_fields(self):
        complete = _food_nutrition(food_row())
        self.assertEqual(complete.protein_g, Decimal("16.9"))
        self.assertTrue(complete.complete)
        self.assertEqual(complete.raw_values["energyKCal"], Decimal("389"))

        incomplete_row = food_row(nutrients_raw={"energyKCal": "100", "protein": "5"})
        incomplete = _food_nutrition(incomplete_row)
        self.assertFalse(incomplete.complete)
        self.assertIsNone(incomplete.carbohydrate_g)
        self.assertIn("carbohydrate_g", incomplete.missing_fields)
        self.assertIn("fat_g", incomplete.missing_fields)
        self.assertFalse(incomplete.per_100g.complete)

        serialized = FoodNutritionResponse.model_validate(incomplete).model_dump(mode="json")
        self.assertIsNone(serialized["carbohydrate_g"])
        self.assertEqual(serialized["protein_g"], 5.0)

    def test_food_per_100g_is_exposed_only_for_verified_basis(self):
        verified = _food_nutrition(food_row())
        self.assertIsNotNone(verified.per_100g)
        self.assertEqual(verified.per_100g.basis, "per_100g")
        self.assertEqual(verified.per_100g.protein_g, Decimal("16.9"))
        self.assertIn("未进行额外换算", verified.normalization_note)

        serving = _food_nutrition(food_row(nutrition_basis="per_serving"))
        self.assertIsNone(serving.per_100g)
        self.assertIn("缺少可靠的克重换算依据", serving.normalization_note)

    async def test_only_approved_verified_and_allowed_video_is_returned(self):
        approved_media = SimpleNamespace(
            id=7,
            exercise_id=3,
            variant="male",
            allowed_use="link",
            source_url="https://approved.example/video.mp4",
            source_host="approved.example",
            attribution="Example Media",
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [approved_media]),
        )))

        videos = await _videos_by_exercise(db, [3])

        self.assertEqual(videos[3][0].attribution, "Example Media")
        self.assertEqual(videos[3][0].playback_status, "available")
        sql = str(db.execute.await_args.args[0].compile())
        self.assertIn("kh_exercise_media.license_status", sql)
        self.assertIn("kh_exercise_media.mapping_status", sql)
        self.assertIn("kh_exercise_media.allowed_use IN", sql)

    def test_unavailable_video_keeps_action_text_visible(self):
        response = _exercise_response(exercise_row(), import_row(), [])

        self.assertEqual(response.video_status, "unavailable")
        self.assertIn("动作文字资料仍可查看", response.video_message)
        self.assertEqual(response.fields["steps"], ["Lower into a squat."])
        self.assertEqual(response.source.source_record_id, "squat-1")
        self.assertIn("common_mistakes", response.missing_fields)

    async def test_detail_record_outside_approval_returns_not_found(self):
        from services.catalog_service import get_food

        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            one_or_none=lambda: None,
        )))
        with self.assertRaises(HTTPException) as raised:
            await get_food(db, 5)
        self.assertEqual(raised.exception.status_code, 404)


class RecipeNutritionCalculationTests(unittest.TestCase):
    def test_recipe_totals_use_decimal_gram_proportions_and_servings(self):
        recipe = SimpleNamespace(servings=Decimal("3"))
        ingredients = [
            SimpleNamespace(
                position=0,
                name="Oats",
                amount=Decimal("100"),
                unit="g",
                food_id=5,
                match_status="exact",
            ),
            SimpleNamespace(
                position=1,
                name="Milk",
                amount=Decimal("50"),
                unit="克",
                food_id=6,
                match_status="approved_alias",
            ),
        ]
        foods = {
            5: food_row(),
            6: food_row(
                id=6,
                nutrients_raw={
                    "energyKCal": "60",
                    "protein": "3.2",
                    "CHO": "4.8",
                    "fat": "3.4",
                },
            ),
        }

        result = calculate_recipe_nutrition(recipe, ingredients, foods)

        self.assertTrue(result.complete)
        self.assertEqual(result.total.calories_kcal, Decimal("419.000000"))
        self.assertEqual(result.total.protein_g, Decimal("18.500000"))
        self.assertEqual(result.total.carbohydrate_g, Decimal("68.700000"))
        self.assertEqual(result.total.fat_g, Decimal("8.600000"))
        self.assertEqual(result.per_serving.calories_kcal, Decimal("139.666667"))
        self.assertIn("ROUND_HALF_UP", result.calculation)
        self.assertEqual(result.missing_ingredients, [])

    def test_missing_food_or_incompatible_unit_blocks_recipe_total(self):
        recipe = SimpleNamespace(servings=Decimal("2"))
        ingredients = [
            SimpleNamespace(
                position=0,
                name="Oats",
                amount=Decimal("50"),
                unit="g",
                food_id=5,
                match_status="exact",
            ),
            SimpleNamespace(
                position=1,
                name="Milk",
                amount=Decimal("1"),
                unit="cup",
                food_id=6,
                match_status="fuzzy",
            ),
        ]

        result = calculate_recipe_nutrition(recipe, ingredients, {5: food_row()})

        self.assertFalse(result.complete)
        self.assertIsNone(result.total.calories_kcal)
        self.assertIsNone(result.per_serving.protein_g)
        self.assertEqual(len(result.missing_ingredients), 1)
        self.assertEqual(result.missing_ingredients[0].name, "Milk")
        self.assertIn("尚未获准", result.missing_ingredients[0].reason)
        self.assertIn("calories_kcal", result.total.missing_fields)

    def test_unverified_food_basis_marks_each_nutrient_missing(self):
        recipe = SimpleNamespace(servings=Decimal("1"))
        ingredients = [SimpleNamespace(
            position=0,
            name="Oats",
            amount=Decimal("50"),
            unit="g",
            food_id=5,
            match_status="exact",
        )]
        foods = {5: food_row(nutrition_basis="per_serving")}

        result = calculate_recipe_nutrition(recipe, ingredients, foods)

        self.assertFalse(result.complete)
        self.assertEqual(
            set(result.total.missing_fields),
            {"calories_kcal", "protein_g", "carbohydrate_g", "fat_g"},
        )
        self.assertIn("每 100 克营养基准", result.missing_ingredients[0].reason)


class SourceLimitedAITests(unittest.IsolatedAsyncioTestCase):
    async def test_dataset_scope_filters_es_candidates_before_rerank_and_disables_web(self):
        db = SimpleNamespace(execute=AsyncMock())
        db.execute.side_effect = [
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [1, 2])),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [
                SimpleNamespace(id=1, title="Approved source"),
            ])),
        ]
        rerank = AsyncMock(return_value=[{
            "doc_id": "1",
            "relevance_score": 0.9,
            "text": "Only approved scoped context",
            "hit": {"_id": "1", "title": "Approved source"},
        }])

        with (
            patch("api.ai.approved_source_document_ids", new_callable=AsyncMock, return_value={1}),
            patch("api.ai.catalog_source_references_by_document", new_callable=AsyncMock, return_value={
                1: {
                    "dataset": "approved-fixture",
                    "repository": "example/approved-fixture",
                    "revision": "a" * 40,
                    "recordKind": "exercise",
                    "sourceRecordId": "squat-1",
                },
            }),
            patch("api.ai.search_milvus_data", new_callable=AsyncMock, return_value={"data": []}) as milvus,
            patch("api.ai.get_es", new_callable=AsyncMock, return_value=object()),
            patch("api.ai.search_data", new_callable=AsyncMock, return_value={"data": [
                {"_id": "1", "content": "approved hit"},
                {"_id": "2", "content": "unrelated hit"},
            ]}),
            patch("api.ai.rerank_call", rerank),
            patch(
                "api.ai.load_named_catalog_evidence",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("api.ai.web_search", new_callable=AsyncMock) as web,
        ):
            context, sources = await _prepare_materials(
                "给出训练饮食建议",
                5,
                True,
                db,
                SimpleNamespace(id=42),
                dataset="approved-fixture",
            )

        milvus.assert_awaited_once_with("给出训练饮食建议", [1])
        fused_hits = rerank.await_args.args[1]
        self.assertEqual({item["doc_id"] for item in fused_hits}, {"1"})
        web.assert_not_awaited()
        self.assertEqual(context, "[1] 类型:知识库 | 标题:Approved source\nOnly approved scoped context")
        self.assertEqual(sources[0]["catalogSource"]["sourceRecordId"], "squat-1")

    async def test_empty_dataset_scope_returns_no_materials_and_no_web_fallback(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [1]),
        )))

        with (
            patch("api.ai.approved_source_document_ids", new_callable=AsyncMock, return_value=set()),
            patch("api.ai.search_milvus_data", new_callable=AsyncMock, return_value={"data": []}) as milvus,
            patch("api.ai.get_es", new_callable=AsyncMock, return_value=object()),
            patch("api.ai.search_data", new_callable=AsyncMock, return_value={"data": [
                {"_id": "1", "content": "must not leak"},
            ]}),
            patch("api.ai.rerank_call", new_callable=AsyncMock, return_value=[]),
            patch(
                "api.ai.load_named_catalog_evidence",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("api.ai.web_search", new_callable=AsyncMock) as web,
        ):
            context, sources = await _prepare_materials(
                "给出训练饮食建议",
                5,
                True,
                db,
                SimpleNamespace(id=42),
                dataset="unapproved-dataset",
            )

        milvus.assert_awaited_once_with("给出训练饮食建议", [])
        web.assert_not_awaited()
        self.assertEqual(context, "（无检索资料）")
        self.assertEqual(sources, [])

    async def test_record_scope_requires_dataset_to_avoid_cross_dataset_ambiguity(self):
        with self.assertRaises(HTTPException) as raised:
            await _prepare_materials(
                "给出训练饮食建议",
                5,
                False,
                SimpleNamespace(),
                SimpleNamespace(id=42),
                source_record_id="same-upstream-id",
            )

        self.assertEqual(raised.exception.status_code, 400)
