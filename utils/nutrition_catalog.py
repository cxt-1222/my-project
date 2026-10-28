"""Pure converters for the pinned food, recipe, and portion JSON data."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Any


_NUTRIENT_FIELDS = (
    "energyKCal", "energyKJ", "protein", "fat", "CHO", "dietaryFiber", "cholesterol",
    "vitaminA", "vitaminC", "vitaminE", "Ca", "P", "K", "Na", "sodium", "Mg", "Fe", "Zn", "Se",
)
_LICENSE_STATES = {"pending_review", "approved", "restricted"}
_BASIS_VALUES = {"unknown", "per_100g", "per_serving", "other"}


@dataclass(slots=True)
class FoodCatalogItem:
    upstream_id: str
    source_key: str
    name: str
    nutrition_basis: str
    edible_value: Decimal | None
    nutrients_raw: dict[str, Decimal]
    missing_fields: list[str]
    raw_record: dict[str, Any]
    content_sha256: str
    license_status: str = "pending_review"
    record_status: str = "quarantined"
    quarantine_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecipeIngredientItem:
    position: int
    name: str
    amount: Decimal | None
    unit: str
    note: str
    food_source_key: str
    food_upstream_id: str
    match_status: str
    raw_record: dict[str, Any]


@dataclass(slots=True)
class RecipeCatalogItem:
    upstream_id: str
    title: str
    source_name: str
    source_url: str
    source_revision: str
    source_license: str
    servings: Decimal | None
    ingredients: list[RecipeIngredientItem]
    recipe_data: dict[str, Any]
    content_sha256: str
    license_status: str = "pending_review"
    record_status: str = "quarantined"
    nutrition_status: str = "not_calculated"
    calculated_nutrition: None = None
    quarantine_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CatalogConversionStats:
    input_records: int = 0
    accepted_records: int = 0
    duplicate_records: int = 0
    invalid_records: int = 0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float, str, Decimal)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _name_key(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _record_list(value: Any, label: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("foods", "recipes", "data", "results", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    raise ValueError(f"{label} 顶层必须是数组，或包含预期数组字段")


def convert_food_records(
    records: Any,
    *,
    license_by_source: Mapping[str, str] | None = None,
    nutrition_basis_by_source: Mapping[str, str] | None = None,
) -> tuple[list[FoodCatalogItem], CatalogConversionStats]:
    """Preserve raw nutrient values; unknown units keep the record quarantined."""
    rows = _record_list(records, "食材数据")
    licenses = dict(license_by_source or {})
    bases = dict(nutrition_basis_by_source or {})
    invalid_bases = {key: value for key, value in bases.items() if value not in _BASIS_VALUES}
    if invalid_bases:
        raise ValueError(f"存在无效的营养计量基准配置：{invalid_bases}")
    stats = CatalogConversionStats(input_records=len(rows))
    converted: list[FoodCatalogItem] = []
    seen: dict[tuple[str, str], str] = {}

    for row in rows:
        if not isinstance(row, dict):
            stats.invalid_records += 1
            continue
        name = _clean_text(row.get("name"))
        source_key = _clean_text(row.get("source"))
        if not name or not source_key:
            stats.invalid_records += 1
            continue
        digest = _digest(row)
        raw_id = _clean_text(str(row.get("code") or ""))
        upstream_id = raw_id or f"sha256:{digest}"
        unique_key = (source_key, upstream_id)
        if unique_key in seen:
            if seen[unique_key] == digest:
                stats.duplicate_records += 1
            else:
                stats.invalid_records += 1
            continue
        seen[unique_key] = digest

        nutrients: dict[str, Decimal] = {}
        invalid_nutrient = False
        missing_fields: list[str] = []
        for field_name in _NUTRIENT_FIELDS:
            if field_name not in row or row[field_name] is None:
                missing_fields.append(field_name)
                continue
            value = _decimal(row[field_name])
            if value is None or value < 0:
                invalid_nutrient = True
                break
            nutrients[field_name] = value
        if invalid_nutrient:
            stats.invalid_records += 1
            continue

        edible = _decimal(row.get("edible"))
        if row.get("edible") is not None and (edible is None or not Decimal(0) <= edible <= Decimal(100)):
            stats.invalid_records += 1
            continue
        basis = bases.get(source_key, "unknown")
        if basis not in _BASIS_VALUES:
            stats.invalid_records += 1
            continue
        license_status = licenses.get(source_key, "pending_review")
        if license_status not in _LICENSE_STATES:
            stats.invalid_records += 1
            continue

        quarantine_reasons: list[str] = []
        if license_status != "approved":
            quarantine_reasons.append("食材来源许可尚未批准")
        if basis == "unknown":
            quarantine_reasons.append("营养字段的计量基准尚未核实")
        if missing_fields:
            quarantine_reasons.append("部分营养字段缺失")
        converted.append(FoodCatalogItem(
            upstream_id=upstream_id,
            source_key=source_key,
            name=name,
            nutrition_basis=basis,
            edible_value=edible,
            nutrients_raw=nutrients,
            missing_fields=missing_fields,
            raw_record=row.copy(),
            content_sha256=digest,
            license_status=license_status,
            record_status="active" if not quarantine_reasons else "quarantined",
            quarantine_reasons=quarantine_reasons,
        ))
        stats.accepted_records += 1
    return converted, stats


def _food_index(foods: list[FoodCatalogItem]) -> tuple[dict[tuple[str, str], FoodCatalogItem], dict[tuple[str, str], FoodCatalogItem]]:
    by_source_id: dict[tuple[str, str], FoodCatalogItem] = {}
    by_source_name: dict[tuple[str, str], FoodCatalogItem] = {}
    for food in foods:
        if not food.upstream_id.startswith("sha256:"):
            by_source_id[(food.source_key, food.upstream_id)] = food
        key = (food.source_key, _name_key(food.name))
        by_source_name.setdefault(key, food)
    return by_source_id, by_source_name


def _recipe_license(source: Mapping[str, Any], license_by_source: Mapping[str, str]) -> str:
    explicit = license_by_source.get(_clean_text(source.get("name")))
    if explicit in _LICENSE_STATES:
        return explicit
    license_text = _clean_text(source.get("license"))
    return "pending_review" if license_text else "restricted"


def convert_recipe_records(
    records: Any,
    foods: list[FoodCatalogItem],
    *,
    recipe_license_by_source: Mapping[str, str] | None = None,
) -> tuple[list[RecipeCatalogItem], CatalogConversionStats]:
    """Validate recipe quantities and references without trusting estimated totals."""
    rows = _record_list(records, "菜谱数据")
    licenses = dict(recipe_license_by_source or {})
    by_source_id, by_source_name = _food_index(foods)
    stats = CatalogConversionStats(input_records=len(rows))
    converted: list[RecipeCatalogItem] = []
    seen: dict[str, str] = {}

    for row in rows:
        if not isinstance(row, dict):
            stats.invalid_records += 1
            continue
        upstream_id = _clean_text(str(row.get("id") or ""))
        title = _clean_text(row.get("title"))
        raw_ingredients = row.get("ingredients")
        servings = _decimal(row.get("servings"))
        if not upstream_id or not title or not isinstance(raw_ingredients, list) or not raw_ingredients:
            stats.invalid_records += 1
            continue
        if servings is None or servings <= 0:
            stats.invalid_records += 1
            continue
        digest = _digest(row)
        if upstream_id in seen:
            if seen[upstream_id] == digest:
                stats.duplicate_records += 1
            else:
                stats.invalid_records += 1
            continue
        seen[upstream_id] = digest

        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        source_name = _clean_text(source.get("name"))
        source_url = _clean_text(source.get("url"))
        source_revision = _clean_text(source.get("revision"))
        source_license = _clean_text(source.get("license"))
        license_status = _recipe_license(source, licenses)
        ingredients: list[RecipeIngredientItem] = []
        reasons: list[str] = []
        if license_status != "approved":
            reasons.append("菜谱来源许可尚未批准或许可字段缺失")

        invalid_ingredient = False
        for position, item in enumerate(raw_ingredients):
            if not isinstance(item, dict):
                invalid_ingredient = True
                break
            name = _clean_text(item.get("name"))
            unit = _clean_text(item.get("unit"))
            amount = _decimal(item.get("amount"))
            if not name or amount is None or amount <= 0 or not unit:
                invalid_ingredient = True
                break
            if unit not in {"g", "克"}:
                invalid_ingredient = True
                break

            food_ref = item.get("food") if isinstance(item.get("food"), dict) else {}
            food_source = _clean_text(food_ref.get("source"))
            food_upstream_id = _clean_text(str(food_ref.get("code") or ""))
            matched: FoodCatalogItem | None = None
            upstream_match = _clean_text(item.get("match"))
            match_status = "missing"
            if upstream_match != "global-fuzzy":
                if food_source and food_upstream_id:
                    matched = by_source_id.get((food_source, food_upstream_id))
                if matched is None and food_source and _clean_text(food_ref.get("name")):
                    matched = by_source_name.get((food_source, _name_key(_clean_text(food_ref.get("name")))))
                if matched is not None:
                    match_status = "exact"
            elif food_source and _clean_text(food_ref.get("name")):
                match_status = "fuzzy"
            if matched is None:
                reasons.append("存在未精确匹配的菜谱食材")
            elif matched.license_status != "approved" or matched.nutrition_basis == "unknown":
                reasons.append("关联食材未获批或营养基准未核实")
            ingredients.append(RecipeIngredientItem(
                position=position,
                name=name,
                amount=amount,
                unit=unit,
                note=_clean_text(item.get("note")),
                food_source_key=food_source,
                food_upstream_id=food_upstream_id,
                match_status=match_status,
                raw_record=item.copy(),
            ))
        if invalid_ingredient:
            stats.invalid_records += 1
            continue

        # The source-provided nutrition object is retained in recipe_data only; it
        # is not accepted as a computed result because the source flags it estimated.
        if any(ingredient.match_status == "fuzzy" for ingredient in ingredients):
            reasons.append("存在模糊食材匹配")
        converted.append(RecipeCatalogItem(
            upstream_id=upstream_id,
            title=title,
            source_name=source_name,
            source_url=source_url,
            source_revision=source_revision,
            source_license=source_license,
            servings=servings,
            ingredients=ingredients,
            recipe_data=row.copy(),
            content_sha256=digest,
            license_status=license_status,
            record_status="active" if not reasons else "quarantined",
            nutrition_status="estimated_not_authoritative" if row.get("nutrition") else "not_calculated",
            calculated_nutrition=None,
            quarantine_reasons=list(dict.fromkeys(reasons)),
        ))
        stats.accepted_records += 1
    return converted, stats


def portion_profile_map(data: Any) -> dict[str, dict[str, Any]]:
    """Validate portion profiles but preserve their estimated nature."""
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        raise ValueError("份量文件必须包含 profiles 数组")
    result: dict[str, dict[str, Any]] = {}
    for item in data["profiles"]:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key"))
        if key and key not in result:
            result[key] = item.copy()
    return result


def conversion_summary(items: list[Any]) -> dict[str, int]:
    return dict(Counter(item.record_status for item in items))
