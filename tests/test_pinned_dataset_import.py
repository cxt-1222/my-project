from __future__ import annotations

from collections import defaultdict
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from models.dataset_catalog import (
    DatasetImportModel,
    DatasetImportProgressModel,
    ExerciseCatalogModel,
    FoodCatalogModel,
    RecipeCatalogModel,
    RecipeIngredientModel,
)
from services.pinned_dataset_import_service import (
    ApprovedImportPlan,
    build_approved_import_plan,
    import_catalog,
    importable_items,
)
from services import pinned_dataset_import_service
from utils.exercise_catalog import convert_exercise_records
from utils.nutrition_catalog import (
    FoodCatalogItem,
    RecipeCatalogItem,
    RecipeIngredientItem,
)
from utils.pinned_dataset_preview import PinnedFile


class MemoryAsyncSession:
    """Small async-session double for deterministic catalog importer tests."""

    _models = {
        model.__tablename__: model
        for model in (
            DatasetImportModel,
            DatasetImportProgressModel,
            ExerciseCatalogModel,
            FoodCatalogModel,
            RecipeCatalogModel,
            RecipeIngredientModel,
        )
    }

    def __init__(self):
        self.rows = defaultdict(list)
        self.next_ids = defaultdict(lambda: 1)

    async def scalar(self, statement):
        model = statement.column_descriptions[0]["entity"]
        criteria = _criteria(statement)
        return next((row for row in self.rows[model] if _matches(row, criteria)), None)

    def add(self, row):
        self.rows[type(row)].append(row)

    async def flush(self):
        for rows in self.rows.values():
            for row in rows:
                if hasattr(row, "id") and row.id is None:
                    row.id = self.next_ids[type(row)]
                    self.next_ids[type(row)] += 1

    async def commit(self):
        await self.flush()

    async def rollback(self):
        return None

    async def get(self, model, row_id):
        return next((row for row in self.rows[model] if row.id == row_id), None)

    async def execute(self, statement):
        model = self._models[statement.table.name]
        criteria = _criteria(statement)
        self.rows[model] = [row for row in self.rows[model] if not _matches(row, criteria)]
        return SimpleNamespace(rowcount=0)


def _criteria(statement):
    expressions = []
    for expression in statement._where_criteria:
        expressions.extend(getattr(expression, "clauses", [expression]))
    return {
        expression.left.name: expression.right.value
        for expression in expressions
        if hasattr(expression, "left") and hasattr(expression.right, "value")
    }


def _matches(row, criteria):
    return all(getattr(row, key) == value for key, value in criteria.items())


def _plan():
    exercises, _ = convert_exercise_records([
        {"id": "squat-1", "name": "Squat", "instructions": ["Stand"]},
        {"id": "unapproved", "name": "Hidden", "instructions": ["Hidden"]},
    ], license_status="approved")
    exercises[1].license_status = "pending_review"
    exercises[1].record_status = "quarantined"

    food = FoodCatalogItem(
        upstream_id="oats-1",
        source_key="usda-approx",
        name="Oats",
        nutrition_basis="per_100g",
        edible_value=None,
        nutrients_raw={"protein": 13.2},
        missing_fields=[],
        raw_record={"name": "Oats", "source": "usda-approx"},
        content_sha256="a" * 64,
        license_status="approved",
        record_status="active",
    )
    recipe = RecipeCatalogItem(
        upstream_id="recipe-1",
        title="Oats Bowl",
        source_name="Local",
        source_url="",
        source_revision="locked-revision",
        source_license="approved-review",
        servings=1,
        ingredients=[RecipeIngredientItem(
            position=0,
            name="Oats",
            amount=50,
            unit="g",
            note="",
            food_source_key="usda-approx",
            food_upstream_id="oats-1",
            match_status="exact",
            raw_record={"name": "Oats", "amount": 50, "unit": "g"},
        )],
        recipe_data={"title": "Oats Bowl"},
        content_sha256="b" * 64,
        license_status="approved",
        record_status="active",
    )
    return ApprovedImportPlan(
        locked_on="2026-10-27",
        files=[{
            "dataset": "approved-fixture",
            "repository": "example/data",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "path": "data/all.json",
            "sha256": "c" * 64,
            "bytes": 100,
        }],
        exercises={"approved-fixture": exercises},
        foods={"approved-fixture": [food]},
        recipes={"approved-fixture": [recipe]},
        source_metadata={"approved-fixture": {
            "metadata_license_status": "approved",
            "media_license_status": "unverified",
            "license_note": "fixture",
        }},
    )


def _build_plan_with_license_mappings(monkeypatch, *, food_licenses, recipe_licenses=None):
    commit = "0123456789abcdef0123456789abcdef01234567"
    files = [
        PinnedFile(
            dataset="chisha-fixture",
            repository="example/data",
            commit=commit,
            metadata_license_status="pending_review",
            media_license_status="not_applicable",
            license_note="fixture",
            path="foods.json",
            kind="food_records",
            expected_sha256="a" * 64,
            max_bytes=1024,
            record_license_by_source=food_licenses,
            nutrition_basis_by_source={"usda-approx": "per_100g", "china-food": "per_100g"},
        ),
        PinnedFile(
            dataset="chisha-fixture",
            repository="example/data",
            commit=commit,
            metadata_license_status="pending_review",
            media_license_status="not_applicable",
            license_note="fixture",
            path="recipes.json",
            kind="recipe_records",
            expected_sha256="b" * 64,
            max_bytes=1024,
            recipe_license_by_source=recipe_licenses or {},
        ),
    ]
    reports = [
        {"dataset": item.dataset, "path": item.path, "bytes": 10, "sha256": item.expected_sha256}
        for item in files
    ]
    nutrients = {
        field: 0
        for field in (
            "energyKCal", "energyKJ", "protein", "fat", "CHO", "dietaryFiber", "cholesterol",
            "vitaminA", "vitaminC", "vitaminE", "Ca", "P", "K", "Na", "sodium", "Mg", "Fe", "Zn", "Se",
        )
    }
    fixture_data = {
        "foods.json": [
            {"code": "oats-1", "name": "Oats", "source": "usda-approx", **nutrients},
            {"code": "grain-1", "name": "Grain", "source": "china-food", **nutrients},
        ],
        "recipes.json": [{
            "id": "recipe-1",
            "title": "Oats Bowl",
            "servings": 1,
            "source": {"name": "Local Recipes", "license": "Unlicense"},
            "ingredients": [{
                "name": "Oats",
                "amount": 50,
                "unit": "g",
                "food": {"source": "usda-approx", "code": "oats-1", "name": "Oats"},
            }],
        }],
    }

    monkeypatch.setattr(
        pinned_dataset_import_service,
        "validate_reviewed_manifest",
        lambda *args, **kwargs: {"files": reports},
    )
    monkeypatch.setattr(
        pinned_dataset_import_service,
        "load_source_lock",
        lambda path: (files, "2026-10-27"),
    )
    monkeypatch.setattr(
        pinned_dataset_import_service,
        "fetch_pinned_json",
        lambda source_file, client, **kwargs: (
            fixture_data[source_file.path],
            {"bytes": 10, "sha256": source_file.expected_sha256},
        ),
    )
    return build_approved_import_plan(None, None, None, None)


def test_import_catalog_writes_only_approved_active_rows_and_is_idempotent():
    session = MemoryAsyncSession()
    plan = _plan()

    first = asyncio.run(import_catalog(session, plan, batch_size=1))
    second = asyncio.run(import_catalog(session, plan, batch_size=1))

    assert first["processed"] == 3
    assert second["processed"] == 3
    assert len(session.rows[DatasetImportModel]) == 1
    assert len(session.rows[ExerciseCatalogModel]) == 1
    assert session.rows[ExerciseCatalogModel][0].upstream_id == "squat-1"
    assert len(session.rows[FoodCatalogModel]) == 1
    assert len(session.rows[RecipeCatalogModel]) == 1
    assert len(session.rows[RecipeIngredientModel]) == 1
    assert len(session.rows[DatasetImportProgressModel]) == 6
    statuses = {row.storage_name: row.progress_status for row in session.rows[DatasetImportProgressModel]}
    assert statuses["postgres_catalog"] == "completed"
    assert all(status == "pending" for name, status in statuses.items() if name != "postgres_catalog")


@pytest.mark.parametrize("rag_stages_completed", [True, False])
def test_catalog_reimport_preserves_published_status_only_when_all_stages_are_complete(rag_stages_completed):
    session = MemoryAsyncSession()
    plan = _plan()
    asyncio.run(import_catalog(session, plan, batch_size=1))

    import_row = session.rows[DatasetImportModel][0]
    import_row.import_status = "imported"
    for progress in session.rows[DatasetImportProgressModel]:
        if progress.storage_name != "postgres_catalog":
            progress.progress_status = "completed" if rag_stages_completed else "pending"

    asyncio.run(import_catalog(session, plan, batch_size=1))

    expected_status = "imported" if rag_stages_completed else "importing"
    assert import_row.import_status == expected_status


def test_import_plan_quarantines_records_when_source_approval_is_missing(monkeypatch):
    plan = _build_plan_with_license_mappings(monkeypatch, food_licenses={})

    assert plan.importable_count == 0
    assert plan.skipped_count == 3
    assert importable_items(plan) == {}


def test_import_plan_includes_only_approved_food_and_recipe_sources(monkeypatch):
    plan = _build_plan_with_license_mappings(
        monkeypatch,
        food_licenses={"usda-approx": "approved", "china-food": "pending_review"},
        recipe_licenses={"Local Recipes": "approved"},
    )

    rows = importable_items(plan)
    assert plan.importable_count == 2
    assert plan.skipped_count == 1
    assert [item.name for item in rows["chisha-fixture"] if isinstance(item, FoodCatalogItem)] == ["Oats"]
    assert [item.title for item in rows["chisha-fixture"] if isinstance(item, RecipeCatalogItem)] == ["Oats Bowl"]


def test_import_catalog_resumes_from_last_committed_source_record():
    session = MemoryAsyncSession()
    plan = _plan()
    real_upsert_food = pinned_dataset_import_service._upsert_food
    attempts = 0

    async def fail_first_food_write(db, import_id, item):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary storage failure")
        await real_upsert_food(db, import_id, item)

    with patch.object(pinned_dataset_import_service, "_upsert_food", fail_first_food_write):
        with pytest.raises(RuntimeError, match="temporary storage failure"):
            asyncio.run(import_catalog(session, plan, batch_size=1))

        progress = next(
            row for row in session.rows[DatasetImportProgressModel]
            if row.storage_name == "postgres_catalog"
        )
        assert progress.progress_status == "failed"
        assert progress.checkpoint == {"last_record_key": "exercise:squat-1"}

        result = asyncio.run(import_catalog(session, plan, batch_size=1))

    assert result["processed"] == 2
    assert len(session.rows[ExerciseCatalogModel]) == 1
    assert len(session.rows[FoodCatalogModel]) == 1
    assert len(session.rows[RecipeCatalogModel]) == 1
    assert progress.progress_status == "completed"
    assert progress.processed_records == 3
    assert progress.last_error == ""
    assert progress.completed_at is not None
