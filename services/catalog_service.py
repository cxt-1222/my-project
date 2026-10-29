from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dataset_catalog import (
    DatasetImportModel,
    ExerciseCatalogModel,
    ExerciseMediaModel,
    FoodCatalogModel,
    KnowledgeSourceMappingModel,
    RecipeCatalogModel,
    RecipeIngredientModel,
)
from schemas.catalog import (
    CatalogSourceReference,
    ExerciseCatalogResponse,
    ExerciseVideoResponse,
    FoodCatalogResponse,
    FoodNutritionResponse,
    NutrientValues,
    RecipeCatalogResponse,
    RecipeNutritionIngredientIssue,
    RecipeNutritionResponse,
    RecipeIngredientResponse,
)


APPROVED_MEDIA_USES = {"link", "embed", "host"}
_REQUIRED_NUTRIENTS = {
    "calories_kcal": "energyKCal",
    "protein_g": "protein",
    "carbohydrate_g": "CHO",
    "fat_g": "fat",
}
_INGREDIENT_UNIT_TO_GRAMS = {
    "g": Decimal("1"),
    "克": Decimal("1"),
    "kg": Decimal("1000"),
    "千克": Decimal("1000"),
}
_RECIPE_NUTRIENT_PRECISION = Decimal("0.000001")
_APPROVED_INGREDIENT_MATCHES = {"exact", "approved_alias"}


def _normalize_name(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _name_pattern(value: str) -> str:
    return f"%{'%'.join(_normalize_name(value).split())}%"


def _source_reference(
    row: ExerciseCatalogModel | FoodCatalogModel | RecipeCatalogModel,
    import_row: DatasetImportModel,
) -> CatalogSourceReference:
    return CatalogSourceReference(
        dataset=import_row.dataset,
        repository=import_row.repository,
        revision=import_row.revision,
        source_record_id=row.upstream_id,
        content_sha256=row.content_sha256,
    )


def _approved_import_filters() -> tuple:
    return (
        DatasetImportModel.import_status == "imported",
        DatasetImportModel.metadata_license_status == "approved",
    )


def exercise_query(
    *,
    query: str | None = None,
    dataset: str | None = None,
    exact_name: bool = False,
    limit: int = 20,
):
    statement = (
        select(ExerciseCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == ExerciseCatalogModel.import_id)
        .where(
            ExerciseCatalogModel.record_status == "active",
            ExerciseCatalogModel.license_status == "approved",
            *_approved_import_filters(),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    if query and query.strip():
        normalized = _normalize_name(query)
        if exact_name:
            statement = statement.where(or_(
                ExerciseCatalogModel.name_normalized == normalized,
                ExerciseCatalogModel.aliases.contains([normalized]),
            ))
        else:
            statement = statement.where(or_(
                ExerciseCatalogModel.name_normalized.ilike(_name_pattern(query)),
                ExerciseCatalogModel.aliases.contains([normalized]),
            ))
    return statement.order_by(ExerciseCatalogModel.name_normalized).limit(limit)


def food_query(
    *,
    query: str | None = None,
    source_key: str | None = None,
    exact_name: bool = False,
    limit: int = 20,
):
    statement = (
        select(FoodCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == FoodCatalogModel.import_id)
        .where(
            FoodCatalogModel.record_status == "active",
            FoodCatalogModel.license_status == "approved",
            FoodCatalogModel.nutrition_basis != "unknown",
            *_approved_import_filters(),
        )
    )
    if source_key:
        statement = statement.where(FoodCatalogModel.source_key == source_key)
    if query and query.strip():
        pattern = _name_pattern(query)
        statement = statement.where(
            FoodCatalogModel.name.ilike(pattern)
            if not exact_name
            else func.lower(FoodCatalogModel.name) == query.strip().casefold()
        )
    return statement.order_by(FoodCatalogModel.name).limit(limit)


def recipe_query(
    *,
    query: str | None = None,
    dataset: str | None = None,
    exact_name: bool = False,
    limit: int = 20,
):
    statement = (
        select(RecipeCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == RecipeCatalogModel.import_id)
        .where(
            RecipeCatalogModel.record_status == "active",
            RecipeCatalogModel.license_status == "approved",
            *_approved_import_filters(),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    if query and query.strip():
        statement = statement.where(
            RecipeCatalogModel.title.ilike(_name_pattern(query))
            if not exact_name
            else func.lower(RecipeCatalogModel.title) == query.strip().casefold()
        )
    return statement.order_by(RecipeCatalogModel.title).limit(limit)


async def _videos_by_exercise(
    db: AsyncSession,
    exercise_ids: list[int],
) -> dict[int, list[ExerciseVideoResponse]]:
    if not exercise_ids:
        return {}
    rows = (await db.execute(
        select(ExerciseMediaModel)
        .where(
            ExerciseMediaModel.exercise_id.in_(exercise_ids),
            ExerciseMediaModel.media_kind == "video",
            ExerciseMediaModel.license_status == "approved",
            ExerciseMediaModel.mapping_status == "verified",
            ExerciseMediaModel.allowed_use.in_(APPROVED_MEDIA_USES),
        )
        .order_by(ExerciseMediaModel.exercise_id, ExerciseMediaModel.variant)
    )).scalars().all()
    grouped: dict[int, list[ExerciseVideoResponse]] = {}
    for media in rows:
        grouped.setdefault(media.exercise_id, []).append(ExerciseVideoResponse(
            id=media.id,
            variant=media.variant,
            allowed_use=media.allowed_use,
            source_url=media.source_url,
            source_host=media.source_host,
            attribution=media.attribution,
        ))
    return grouped


def _exercise_response(
    row: ExerciseCatalogModel,
    import_row: DatasetImportModel,
    videos: list[ExerciseVideoResponse],
) -> ExerciseCatalogResponse:
    fields = row.normalized_fields or {}
    missing_fields = sorted(key for key, value in fields.items() if value in (None, "", []))
    video_message = (
        "已获准的视频可按标注的展示方式使用。"
        if videos
        else "当前没有已获准且映射已验证的视频；动作文字资料仍可查看。"
    )
    return ExerciseCatalogResponse(
        id=row.id,
        name=row.name,
        aliases=row.aliases or [],
        fields=fields,
        missing_fields=missing_fields,
        source=_source_reference(row, import_row),
        videos=videos,
        video_status="available" if videos else "unavailable",
        video_message=video_message,
    )


async def list_exercises(
    db: AsyncSession,
    *,
    query: str | None,
    dataset: str | None,
    exact_name: bool,
    limit: int,
) -> list[ExerciseCatalogResponse]:
    rows = (await db.execute(exercise_query(
        query=query, dataset=dataset, exact_name=exact_name, limit=limit,
    ))).all()
    videos = await _videos_by_exercise(db, [row.id for row, _ in rows])
    return [_exercise_response(row, import_row, videos.get(row.id, [])) for row, import_row in rows]


async def get_exercise(
    db: AsyncSession,
    exercise_id: int,
    *,
    dataset: str | None = None,
) -> ExerciseCatalogResponse:
    statement = (
        select(ExerciseCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == ExerciseCatalogModel.import_id)
        .where(
            ExerciseCatalogModel.id == exercise_id,
            ExerciseCatalogModel.record_status == "active",
            ExerciseCatalogModel.license_status == "approved",
            *_approved_import_filters(),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    result = (await db.execute(statement)).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="动作目录记录不存在或尚未获准")
    row, import_row = result
    videos = (await _videos_by_exercise(db, [row.id])).get(row.id, [])
    return _exercise_response(row, import_row, videos)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


async def _approved_foods_by_id(
    db: AsyncSession,
    food_ids: set[int],
) -> dict[int, FoodCatalogModel]:
    if not food_ids:
        return {}
    rows = (await db.execute(
        select(FoodCatalogModel)
        .join(DatasetImportModel, DatasetImportModel.id == FoodCatalogModel.import_id)
        .where(
            FoodCatalogModel.id.in_(food_ids),
            FoodCatalogModel.record_status == "active",
            FoodCatalogModel.license_status == "approved",
            *_approved_import_filters(),
        )
    )).scalars().all()
    return {row.id: row for row in rows}


def _rounded(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_RECIPE_NUTRIENT_PRECISION, rounding=ROUND_HALF_UP)


def _nutrient_values(
    *,
    basis: str,
    totals: dict[str, Decimal | None],
    missing_fields: list[str],
) -> NutrientValues:
    return NutrientValues(
        basis=basis,
        calories_kcal=_rounded(totals["calories_kcal"]),
        protein_g=_rounded(totals["protein_g"]),
        carbohydrate_g=_rounded(totals["carbohydrate_g"]),
        fat_g=_rounded(totals["fat_g"]),
        missing_fields=missing_fields,
        complete=not missing_fields,
    )


def calculate_recipe_nutrition(
    recipe: RecipeCatalogModel,
    ingredients: list[Any],
    approved_foods: dict[int, FoodCatalogModel],
) -> RecipeNutritionResponse:
    """Calculate nutrients only from matched approved foods with gram amounts.

    A nutrient is reported only when every ingredient supplies it on a reliable
    per-100g basis. Incomplete data yields ``None`` instead of a partial total.
    Final values use ROUND_HALF_UP with six decimal places.
    """
    issues: list[RecipeNutritionIngredientIssue] = []
    weighted: list[tuple[FoodCatalogModel, Decimal]] = []
    for ingredient in ingredients:
        amount = _decimal_or_none(getattr(ingredient, "amount", None))
        unit = str(getattr(ingredient, "unit", "") or "").strip().casefold()
        reason = ""
        if getattr(ingredient, "match_status", None) not in _APPROVED_INGREDIENT_MATCHES:
            reason = "食材匹配关系尚未获准"
        elif amount is None or amount <= 0:
            reason = "食材数量缺失或无效"
        elif unit not in _INGREDIENT_UNIT_TO_GRAMS:
            reason = f"无法将单位 {unit or '未提供'} 可靠换算为克"
        else:
            food_id = getattr(ingredient, "food_id", None)
            food = approved_foods.get(food_id) if food_id is not None else None
            if food is None:
                reason = "关联食材未获准或已停用"
            elif food.nutrition_basis != "per_100g":
                reason = "关联食材没有可靠的每 100 克营养基准"
            else:
                weighted.append((food, amount * _INGREDIENT_UNIT_TO_GRAMS[unit]))
        if reason:
            issues.append(RecipeNutritionIngredientIssue(
                position=int(getattr(ingredient, "position", 0)),
                name=str(getattr(ingredient, "name", "") or "未命名食材"),
                reason=reason,
            ))

    totals: dict[str, Decimal | None] = {
        key: None
        for key in _REQUIRED_NUTRIENTS
    }
    missing_fields: list[str] = []
    if not ingredients:
        missing_fields = list(_REQUIRED_NUTRIENTS)
    elif not issues:
        for canonical, source_key in _REQUIRED_NUTRIENTS.items():
            nutrient_values: list[Decimal] = []
            for food, grams in weighted:
                raw_value = _decimal_or_none((food.nutrients_raw or {}).get(source_key))
                if raw_value is None:
                    break
                nutrient_values.append(raw_value * grams / Decimal("100"))
            if len(nutrient_values) == len(weighted) and nutrient_values:
                totals[canonical] = sum(nutrient_values, Decimal("0"))
            else:
                missing_fields.append(canonical)
    else:
        # Omitting a known ingredient would make any recipe total misleading.
        missing_fields = list(_REQUIRED_NUTRIENTS)

    total_values = _nutrient_values(
        basis="recipe_total",
        totals=totals,
        missing_fields=missing_fields,
    )
    servings = _decimal_or_none(recipe.servings)
    if servings is not None and servings > 0 and not any(
        value is None for value in totals.values()
    ):
        per_serving_values = {
            key: value / servings
            for key, value in totals.items()
        }
        per_serving = _nutrient_values(
            basis="per_serving",
            totals=per_serving_values,
            missing_fields=[],
        )
    else:
        per_serving = _nutrient_values(
            basis="per_serving",
            totals={key: None for key in _REQUIRED_NUTRIENTS},
            missing_fields=list(missing_fields),
        )
    complete = total_values.complete and per_serving.complete and not issues
    return RecipeNutritionResponse(
        total=total_values,
        per_serving=per_serving,
        missing_ingredients=issues,
        calculation=(
            "仅使用已获准食材、每 100 克营养值和明确克数；"
            "总和 = Σ(营养值 × 克数 ÷ 100)，每份值 = 总和 ÷ 菜谱份数，"
            "最终按 ROUND_HALF_UP 保留 6 位小数。"
        ),
        complete=complete,
    )


def _food_nutrition(row: FoodCatalogModel) -> FoodNutritionResponse:
    raw: dict[str, Decimal] = {}
    for key, raw_value in (row.nutrients_raw or {}).items():
        parsed = _decimal_or_none(raw_value)
        if parsed is not None:
            raw[str(key)] = parsed
    values = {
        canonical: raw.get(source_key)
        for canonical, source_key in _REQUIRED_NUTRIENTS.items()
    }
    missing = [key for key, nutrient_value in values.items() if nutrient_value is None]
    if row.nutrition_basis == "unknown":
        missing = list(_REQUIRED_NUTRIENTS)
    normalized = None
    if row.nutrition_basis == "per_100g":
        normalized = NutrientValues(
            basis="per_100g",
            calories_kcal=values["calories_kcal"],
            protein_g=values["protein_g"],
            carbohydrate_g=values["carbohydrate_g"],
            fat_g=values["fat_g"],
            missing_fields=missing,
            complete=not missing,
        )
        normalization_note = "原始数据已按每 100 克计量，未进行额外换算。"
    else:
        normalization_note = (
            f"原始计量基准为 {row.nutrition_basis}，缺少可靠的克重换算依据，"
            "不提供每 100 克营养值。"
        )
    return FoodNutritionResponse(
        basis=row.nutrition_basis,
        calories_kcal=values["calories_kcal"],
        protein_g=values["protein_g"],
        carbohydrate_g=values["carbohydrate_g"],
        fat_g=values["fat_g"],
        raw_values=raw,
        missing_fields=missing,
        complete=not missing,
        per_100g=normalized,
        normalization_note=normalization_note,
    )


def _food_response(row: FoodCatalogModel, import_row: DatasetImportModel) -> FoodCatalogResponse:
    return FoodCatalogResponse(
        id=row.id,
        name=row.name,
        source_key=row.source_key,
        source=_source_reference(row, import_row),
        edible_value=row.edible_value,
        nutrition=_food_nutrition(row),
    )


async def list_foods(
    db: AsyncSession,
    *,
    query: str | None,
    source_key: str | None,
    exact_name: bool,
    limit: int,
) -> list[FoodCatalogResponse]:
    rows = (await db.execute(food_query(
        query=query, source_key=source_key, exact_name=exact_name, limit=limit,
    ))).all()
    return [_food_response(row, import_row) for row, import_row in rows]


async def get_food(
    db: AsyncSession,
    food_id: int,
    *,
    source_key: str | None = None,
) -> FoodCatalogResponse:
    statement = (
        select(FoodCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == FoodCatalogModel.import_id)
        .where(
            FoodCatalogModel.id == food_id,
            FoodCatalogModel.record_status == "active",
            FoodCatalogModel.license_status == "approved",
            FoodCatalogModel.nutrition_basis != "unknown",
            *_approved_import_filters(),
        )
    )
    if source_key:
        statement = statement.where(FoodCatalogModel.source_key == source_key)
    result = (await db.execute(statement)).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="食材目录记录不存在或尚未获准")
    return _food_response(*result)


async def list_recipes(
    db: AsyncSession,
    *,
    query: str | None,
    dataset: str | None,
    exact_name: bool,
    limit: int,
) -> list[RecipeCatalogResponse]:
    rows = (await db.execute(recipe_query(
        query=query, dataset=dataset, exact_name=exact_name, limit=limit,
    ))).all()
    if not rows:
        return []
    recipe_ids = [row.id for row, _ in rows]
    ingredients = (await db.execute(
        select(RecipeIngredientModel)
        .where(RecipeIngredientModel.recipe_id.in_(recipe_ids))
        .order_by(RecipeIngredientModel.recipe_id, RecipeIngredientModel.position)
    )).scalars().all()
    grouped: dict[int, list[RecipeIngredientResponse]] = {}
    for ingredient in ingredients:
        grouped.setdefault(ingredient.recipe_id, []).append(RecipeIngredientResponse(
            position=ingredient.position,
            name=ingredient.name,
            amount=ingredient.amount,
            unit=ingredient.unit,
            note=ingredient.note,
            food_source_key=ingredient.food_source_key,
            food_upstream_id=ingredient.food_upstream_id,
            match_status=ingredient.match_status,
        ))
    approved_foods = await _approved_foods_by_id(db, {
        ingredient.food_id
        for ingredient in ingredients
        if ingredient.food_id is not None
    })
    raw_ingredients: dict[int, list[Any]] = {}
    for ingredient in ingredients:
        raw_ingredients.setdefault(ingredient.recipe_id, []).append(ingredient)
    return [
        _recipe_response(
            row,
            import_row,
            grouped.get(row.id, []),
            calculate_recipe_nutrition(
                row,
                raw_ingredients.get(row.id, []),
                approved_foods,
            ),
        )
        for row, import_row in rows
    ]


def _recipe_response(
    row: RecipeCatalogModel,
    import_row: DatasetImportModel,
    ingredients: list[RecipeIngredientResponse],
    nutrition: RecipeNutritionResponse,
) -> RecipeCatalogResponse:
    if row.servings is None:
        raise HTTPException(status_code=409, detail="菜谱份数缺失，不能作为可计算目录记录")
    return RecipeCatalogResponse(
        id=row.id,
        title=row.title,
        servings=row.servings,
        source=_source_reference(row, import_row),
        source_name=row.source_name,
        source_url=row.source_url,
        source_revision=row.source_revision,
        source_license=row.source_license,
        ingredients=ingredients,
        nutrition=nutrition,
    )


async def get_recipe(
    db: AsyncSession,
    recipe_id: int,
    *,
    dataset: str | None = None,
) -> RecipeCatalogResponse:
    statement = (
        select(RecipeCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == RecipeCatalogModel.import_id)
        .where(
            RecipeCatalogModel.id == recipe_id,
            RecipeCatalogModel.record_status == "active",
            RecipeCatalogModel.license_status == "approved",
            *_approved_import_filters(),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    result = (await db.execute(statement)).one_or_none()
    if result is None:
        raise HTTPException(status_code=404, detail="菜谱目录记录不存在或尚未获准")
    row, import_row = result
    ingredients = (await db.execute(
        select(RecipeIngredientModel)
        .where(RecipeIngredientModel.recipe_id == row.id)
        .order_by(RecipeIngredientModel.position)
    )).scalars().all()
    approved_foods = await _approved_foods_by_id(db, {
        ingredient.food_id
        for ingredient in ingredients
        if ingredient.food_id is not None
    })
    return _recipe_response(row, import_row, [
        RecipeIngredientResponse(
            position=ingredient.position,
            name=ingredient.name,
            amount=ingredient.amount,
            unit=ingredient.unit,
            note=ingredient.note,
            food_source_key=ingredient.food_source_key,
            food_upstream_id=ingredient.food_upstream_id,
            match_status=ingredient.match_status,
        )
        for ingredient in ingredients
    ], calculate_recipe_nutrition(row, ingredients, approved_foods))


def approved_source_document_query(
    *,
    dataset: str | None = None,
    source_record_id: str | None = None,
):
    """Resolve RAG document IDs only through active, approved source mappings."""
    exercise_match = exists().where(and_(
        ExerciseCatalogModel.import_id == KnowledgeSourceMappingModel.import_id,
        ExerciseCatalogModel.upstream_id == KnowledgeSourceMappingModel.source_record_id,
        ExerciseCatalogModel.record_status == "active",
        ExerciseCatalogModel.license_status == "approved",
    ))
    recipe_match = exists().where(and_(
        RecipeCatalogModel.import_id == KnowledgeSourceMappingModel.import_id,
        RecipeCatalogModel.upstream_id == KnowledgeSourceMappingModel.source_record_id,
        RecipeCatalogModel.record_status == "active",
        RecipeCatalogModel.license_status == "approved",
    ))
    statement = (
        select(KnowledgeSourceMappingModel.document_id)
        .join(DatasetImportModel, DatasetImportModel.id == KnowledgeSourceMappingModel.import_id)
        .where(
            KnowledgeSourceMappingModel.mapping_status == "active",
            *_approved_import_filters(),
            or_(
                and_(KnowledgeSourceMappingModel.record_kind == "exercise", exercise_match),
                and_(KnowledgeSourceMappingModel.record_kind == "recipe", recipe_match),
            ),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    if source_record_id:
        statement = statement.where(
            KnowledgeSourceMappingModel.source_record_id == source_record_id
        )
    return statement


async def approved_source_document_ids(
    db: AsyncSession,
    *,
    dataset: str | None = None,
    source_record_id: str | None = None,
) -> set[int]:
    if not dataset and not source_record_id:
        return set()
    rows = (await db.execute(approved_source_document_query(
        dataset=dataset,
        source_record_id=source_record_id,
    ))).scalars().all()
    return {int(document_id) for document_id in rows}


async def catalog_source_references_by_document(
    db: AsyncSession,
    document_ids: set[int],
) -> dict[int, dict[str, str]]:
    """Return non-sensitive provenance for mapped documents already selected as context."""
    if not document_ids:
        return {}
    rows = (await db.execute(
        select(
            KnowledgeSourceMappingModel.document_id,
            KnowledgeSourceMappingModel.record_kind,
            KnowledgeSourceMappingModel.source_record_id,
            DatasetImportModel.dataset,
            DatasetImportModel.repository,
            DatasetImportModel.revision,
        )
        .join(DatasetImportModel, DatasetImportModel.id == KnowledgeSourceMappingModel.import_id)
        .where(
            KnowledgeSourceMappingModel.document_id.in_(document_ids),
            KnowledgeSourceMappingModel.mapping_status == "active",
            *_approved_import_filters(),
        )
    )).all()
    return {
        int(row.document_id): {
            "dataset": row.dataset,
            "repository": row.repository,
            "revision": row.revision,
            "recordKind": row.record_kind,
            "sourceRecordId": row.source_record_id,
        }
        for row in rows
    }
