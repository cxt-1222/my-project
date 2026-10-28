import datetime
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from pydantic import ValidationError

from api.nutrition import nutrition_router
from core.security import get_current_user
from models.nutrition_record import NutritionRecordModel
from schemas.nutrition import (
    DailyNutritionSummary,
    NutritionRecordCreate,
    NutritionRecordResponse,
)
from services.nutrition_service import (
    create_nutrition_record,
    delete_nutrition_record,
    get_daily_nutrition_summary,
    update_nutrition_record,
)


def valid_payload(**changes) -> NutritionRecordCreate:
    values = {
        "date": "2026-10-22",
        "meal_type": "breakfast",
        "food_name": "燕麦粥",
        "amount": "250",
        "unit": "ml",
        "calories_kcal": "160.50",
        "protein_g": "6.20",
        "carbohydrate_g": "28.00",
        "fat_g": "3.10",
    }
    values.update(changes)
    return NutritionRecordCreate.model_validate(values)


class NutritionSchemaTests(unittest.TestCase):
    def test_authenticated_routes_are_registered_and_model_is_in_metadata(self):
        route_methods = {}
        for route in nutrition_router.routes:
            route_methods.setdefault(route.path, set()).update(route.methods)
        self.assertIn("/nutrition/daily", route_methods)
        self.assertIn("GET", route_methods["/nutrition/daily"])
        self.assertIn("POST", route_methods["/nutrition/records"])
        self.assertIn("PUT", route_methods["/nutrition/records/{record_id}"])
        self.assertIn("DELETE", route_methods["/nutrition/records/{record_id}"])
        for route in nutrition_router.routes:
            dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
            self.assertIn(get_current_user, dependency_calls)
        self.assertIn("kh_nutrition_record", NutritionRecordModel.metadata.tables)

    def test_accepts_manual_food_entry(self):
        payload = valid_payload()
        self.assertEqual(payload.date, datetime.date(2026, 10, 22))
        self.assertEqual(payload.food_name, "燕麦粥")
        self.assertEqual(payload.calories_kcal, Decimal("160.50"))

    def test_rejects_blank_text_invalid_meal_negative_values_and_owner_fields(self):
        invalid = (
            {"food_name": "   "},
            {"unit": " "},
            {"meal_type": "midnight"},
            {"amount": 0},
            {"amount": -1},
            {"protein_g": -0.1},
            {"calories_kcal": -1},
            {"user_id": 999},
            {"date": "not-a-date"},
            {"unknown": "value"},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                valid_payload(**values)

    def test_response_reads_record_date_and_serializes_numeric_values(self):
        record = SimpleNamespace(
            record_date=datetime.date(2026, 10, 22),
            meal_type="breakfast",
            food_name="燕麦粥",
            amount=Decimal("250.000"),
            unit="ml",
            calories_kcal=Decimal("160.50"),
            protein_g=Decimal("6.20"),
            carbohydrate_g=Decimal("28.00"),
            fat_g=Decimal("3.10"),
            id=3,
            created_at=datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc),
            updated_at=datetime.datetime(2026, 10, 22, tzinfo=datetime.timezone.utc),
        )
        response = NutritionRecordResponse.model_validate(record)
        self.assertEqual(response.date, datetime.date(2026, 10, 22))
        self.assertEqual(response.model_dump(mode="json")["calories_kcal"], 160.5)

    def test_empty_summary_defaults_to_zero_totals(self):
        summary = DailyNutritionSummary(date=datetime.date(2026, 10, 22), records=[], totals={})
        self.assertEqual(summary.model_dump(mode="json")["totals"], {
            "calories_kcal": 0.0,
            "protein_g": 0.0,
            "carbohydrate_g": 0.0,
            "fat_g": 0.0,
        })


class NutritionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_assigns_authenticated_owner_and_persists_user_values(self):
        db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())

        record = await create_nutrition_record(db, user_id=42, payload=valid_payload())

        saved = db.add.call_args.args[0]
        self.assertIsInstance(saved, NutritionRecordModel)
        self.assertEqual(saved.user_id, 42)
        self.assertEqual(saved.food_name, "燕麦粥")
        self.assertEqual(saved.record_date, datetime.date(2026, 10, 22))
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(saved)
        self.assertIs(record, saved)

    async def test_daily_summary_filters_owner_and_date_and_sums_only_returned_records(self):
        rows = [
            SimpleNamespace(calories_kcal=Decimal("100.25"), protein_g=Decimal("5"), carbohydrate_g=Decimal("20"), fat_g=Decimal("1.5")),
            SimpleNamespace(calories_kcal=Decimal("60.25"), protein_g=Decimal("2"), carbohydrate_g=Decimal("8"), fat_g=Decimal("1.6")),
        ]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))))

        summary = await get_daily_nutrition_summary(db, user_id=42, record_date=datetime.date(2026, 10, 22))

        self.assertEqual(summary["records"], rows)
        self.assertEqual(summary["totals"]["calories_kcal"], Decimal("160.50"))
        self.assertEqual(summary["totals"]["protein_g"], Decimal("7"))
        compiled = db.execute.await_args.args[0].compile()
        sql = str(compiled)
        self.assertIn("kh_nutrition_record.user_id", sql)
        self.assertIn("kh_nutrition_record.record_date", sql)
        self.assertIn(42, compiled.params.values())
        self.assertIn(datetime.date(2026, 10, 22), compiled.params.values())

    async def test_empty_day_returns_empty_records_and_zero_totals(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))))

        summary = await get_daily_nutrition_summary(db, user_id=42, record_date=datetime.date(2026, 10, 22))

        self.assertEqual(summary["records"], [])
        self.assertEqual(summary["totals"], {
            "calories_kcal": Decimal("0"),
            "protein_g": Decimal("0"),
            "carbohydrate_g": Decimal("0"),
            "fat_g": Decimal("0"),
        })

    async def test_update_and_delete_scope_lookup_to_record_id_and_owner(self):
        record = SimpleNamespace(
            id=7,
            user_id=42,
            record_date=datetime.date(2026, 10, 21),
            meal_type="snack",
            food_name="旧食物",
            amount=Decimal("1"),
            unit="份",
            calories_kcal=Decimal("10"),
            protein_g=Decimal("0"),
            carbohydrate_g=Decimal("1"),
            fat_g=Decimal("0"),
        )
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)),
            commit=AsyncMock(),
            refresh=AsyncMock(),
            delete=AsyncMock(),
        )

        updated = await update_nutrition_record(db, record_id=7, user_id=42, payload=valid_payload())
        self.assertIs(updated, record)
        self.assertEqual(record.food_name, "燕麦粥")
        statement = db.execute.await_args.args[0].compile()
        self.assertIn("kh_nutrition_record.id", str(statement))
        self.assertIn("kh_nutrition_record.user_id", str(statement))
        self.assertIn(7, statement.params.values())
        self.assertIn(42, statement.params.values())
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(record)

        await delete_nutrition_record(db, record_id=7, user_id=42)
        db.delete.assert_awaited_once_with(record)
        self.assertEqual(db.commit.await_count, 2)

    async def test_foreign_or_missing_record_returns_not_found_without_mutation(self):
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
            commit=AsyncMock(),
            delete=AsyncMock(),
        )
        with self.assertRaises(HTTPException) as raised:
            await update_nutrition_record(db, record_id=7, user_id=99, payload=valid_payload())
        self.assertEqual(raised.exception.status_code, 404)
        with self.assertRaises(HTTPException) as raised:
            await delete_nutrition_record(db, record_id=7, user_id=99)
        self.assertEqual(raised.exception.status_code, 404)
        db.commit.assert_not_awaited()
        db.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
