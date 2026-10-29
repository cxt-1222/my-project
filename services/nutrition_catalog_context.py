from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal

from sqlalchemy import and_, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dataset_catalog import (
    DatasetImportModel,
    FoodCatalogModel,
    RecipeCatalogModel,
    RecipeIngredientModel,
)
from schemas.catalog import FoodCatalogResponse, RecipeCatalogResponse
from services.catalog_service import (
    _approved_foods_by_id,
    _food_response,
    _recipe_response,
    calculate_recipe_nutrition,
)


CatalogKind = Literal["food", "recipe"]


@dataclass(frozen=True)
class CatalogEvidence:
    kind: CatalogKind
    record_id: int
    title: str
    text: str
    excerpt: str
    source: dict[str, str]
    url: str | None = None


def _normalized_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.casefold()).strip()


def _approved_import_conditions() -> tuple:
    return (
        DatasetImportModel.import_status == "imported",
        DatasetImportModel.metadata_license_status == "approved",
    )


def _query_contains_name(query: str, column):
    """Match an approved catalog name only when it occurs in the user's text."""
    normalized = _normalized_query(query)
    return and_(
        func.char_length(func.trim(column)) >= 2,
        func.strpos(func.lower(literal(normalized)), func.lower(func.trim(column))) > 0,
    )


def named_food_query(
    query: str,
    *,
    dataset: str | None = None,
    source_record_id: str | None = None,
    limit: int = 3,
):
    statement = (
        select(FoodCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == FoodCatalogModel.import_id)
        .where(
            FoodCatalogModel.record_status == "active",
            FoodCatalogModel.license_status == "approved",
            FoodCatalogModel.nutrition_basis == "per_100g",
            *_approved_import_conditions(),
            _query_contains_name(query, FoodCatalogModel.name),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    if source_record_id:
        statement = statement.where(FoodCatalogModel.upstream_id == source_record_id)
    return statement.order_by(
        func.char_length(FoodCatalogModel.name).desc(),
        FoodCatalogModel.name,
    ).limit(limit)


def named_recipe_query(
    query: str,
    *,
    dataset: str | None = None,
    source_record_id: str | None = None,
    limit: int = 3,
):
    statement = (
        select(RecipeCatalogModel, DatasetImportModel)
        .join(DatasetImportModel, DatasetImportModel.id == RecipeCatalogModel.import_id)
        .where(
            RecipeCatalogModel.record_status == "active",
            RecipeCatalogModel.license_status == "approved",
            *_approved_import_conditions(),
            _query_contains_name(query, RecipeCatalogModel.title),
        )
    )
    if dataset:
        statement = statement.where(DatasetImportModel.dataset == dataset)
    if source_record_id:
        statement = statement.where(RecipeCatalogModel.upstream_id == source_record_id)
    return statement.order_by(
        func.char_length(RecipeCatalogModel.title).desc(),
        RecipeCatalogModel.title,
    ).limit(limit)


def _format_decimal(value: Decimal | None, unit: str) -> str:
    if value is None:
        return f"缺失（{unit}）"
    normalized = format(value.normalize(), "f")
    return f"{normalized} {unit}"


def _format_nutrients(values, *, prefix: str = "") -> str:
    return (
        f"{prefix}热量 {_format_decimal(values.calories_kcal, 'kcal')}；"
        f"蛋白质 {_format_decimal(values.protein_g, 'g')}；"
        f"碳水化合物 {_format_decimal(values.carbohydrate_g, 'g')}；"
        f"脂肪 {_format_decimal(values.fat_g, 'g')}"
    )


def _source_dict(
    response: FoodCatalogResponse | RecipeCatalogResponse,
    kind: CatalogKind,
) -> dict[str, str]:
    source = response.source
    return {
        "dataset": source.dataset,
        "repository": source.repository,
        "revision": source.revision,
        "recordKind": kind,
        "recordId": str(response.id),
        "sourceRecordId": source.source_record_id,
        "contentSha256": source.content_sha256,
    }


def format_food_evidence(response: FoodCatalogResponse) -> CatalogEvidence:
    nutrition = response.nutrition
    normalized = nutrition.per_100g
    lines = [
        "结构化目录记录类型：食材",
        f"食材名称：{response.name}",
        f"原始计量基准：{nutrition.basis}",
    ]
    if normalized is not None:
        lines.append(_format_nutrients(normalized, prefix="每 100 克："))
        if normalized.missing_fields:
            lines.append(f"缺失营养字段：{'、'.join(normalized.missing_fields)}")
    else:
        lines.append("每 100 克营养值：缺失")
    lines.append(f"计量说明：{nutrition.normalization_note}")
    lines.append(
        f"来源：{response.source.dataset} @ {response.source.revision}；"
        f"上游记录 {response.source.source_record_id}"
    )
    text = "\n".join(lines)
    return CatalogEvidence(
        kind="food",
        record_id=response.id,
        title=f"食材目录：{response.name}",
        text=text,
        excerpt=text[:120],
        source=_source_dict(response, "food"),
    )


def format_recipe_evidence(response: RecipeCatalogResponse) -> CatalogEvidence:
    nutrition = response.nutrition
    lines = [
        "结构化目录记录类型：菜谱",
        f"菜谱名称：{response.title}",
        f"份数：{_format_decimal(response.servings, '份')}",
        _format_nutrients(nutrition.per_serving, prefix="每份："),
        _format_nutrients(
            nutrition.total,
            prefix=f"整份（{_format_decimal(response.servings, '份')}）：",
        ),
        f"计算依据：{nutrition.calculation}",
    ]
    if nutrition.missing_ingredients:
        missing = "；".join(
            f"{item.name}（{item.reason}）"
            for item in nutrition.missing_ingredients
        )
        lines.append(f"营养结果不完整：{missing}")
    lines.append(f"来源名称：{response.source_name or response.source.dataset}")
    lines.append(
        f"来源：{response.source.dataset} @ {response.source.revision}；"
        f"上游记录 {response.source.source_record_id}"
    )
    text = "\n".join(lines)
    return CatalogEvidence(
        kind="recipe",
        record_id=response.id,
        title=f"菜谱目录：{response.title}",
        text=text,
        excerpt=text[:120],
        source=_source_dict(response, "recipe"),
        url=response.source_url or None,
    )


async def load_named_catalog_evidence(
    db: AsyncSession,
    query: str,
    *,
    dataset: str | None = None,
    source_record_id: str | None = None,
    limit: int = 3,
) -> list[CatalogEvidence]:
    """Load only approved records whose names the user explicitly mentioned."""
    food_rows = (await db.execute(named_food_query(
        query,
        dataset=dataset,
        source_record_id=source_record_id,
        limit=limit,
    ))).all()
    recipe_rows = (await db.execute(named_recipe_query(
        query,
        dataset=dataset,
        source_record_id=source_record_id,
        limit=limit,
    ))).all()

    evidence = [
        format_food_evidence(_food_response(row, import_row))
        for row, import_row in food_rows
    ]
    if not recipe_rows:
        return evidence

    recipe_ids = [row.id for row, _ in recipe_rows]
    ingredients = (await db.execute(
        select(RecipeIngredientModel)
        .where(RecipeIngredientModel.recipe_id.in_(recipe_ids))
        .order_by(RecipeIngredientModel.recipe_id, RecipeIngredientModel.position)
    )).scalars().all()
    approved_foods = await _approved_foods_by_id(db, {
        ingredient.food_id
        for ingredient in ingredients
        if ingredient.food_id is not None
    })
    grouped: dict[int, list] = {}
    for ingredient in ingredients:
        grouped.setdefault(ingredient.recipe_id, []).append(ingredient)
    for row, import_row in recipe_rows:
        recipe_ingredients = grouped.get(row.id, [])
        evidence.append(format_recipe_evidence(_recipe_response(
            row,
            import_row,
            recipe_ingredients,
            calculate_recipe_nutrition(row, recipe_ingredients, approved_foods),
        )))
    return evidence


def evidence_source(evidence: CatalogEvidence, index: int) -> dict:
    return {
        "index": index,
        "documentId": None,
        "documentTitle": evidence.title,
        "heading": "结构化营养目录",
        "excerpt": evidence.excerpt,
        "score": 1.0,
        "fileKey": None,
        "sourceType": "catalog",
        "url": evidence.url,
        "catalogSource": evidence.source,
    }
