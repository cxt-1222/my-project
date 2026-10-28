from decimal import Decimal

import pytest

from utils.nutrition_catalog import (
    convert_food_records,
    convert_recipe_records,
    portion_profile_map,
)


def _food(name="Oats", code="oats-1", source="usda-approx", **overrides):
    row = {
        "code": code,
        "name": name,
        "source": source,
        "edible": 100,
        "energyKCal": 389,
        "protein": 16.9,
        "fat": 6.9,
        "CHO": 66.3,
    }
    row.update(overrides)
    return row


def test_food_converter_uses_decimal_and_keeps_unknown_basis_quarantined():
    items, stats = convert_food_records([_food()], license_by_source={"usda-approx": "approved"})

    assert stats.accepted_records == 1
    assert items[0].nutrients_raw["protein"] == Decimal("16.9")
    assert items[0].nutrition_basis == "unknown"
    assert items[0].record_status == "quarantined"
    assert "营养字段的计量基准尚未核实" in items[0].quarantine_reasons


def test_food_converter_rejects_bad_numbers_and_keeps_missing_fields_explicit():
    bad = _food(code="bad", protein="not-a-number")
    sparse = _food(code="sparse", fat=None)
    items, stats = convert_food_records([bad, sparse], nutrition_basis_by_source={"usda-approx": "per_100g"})

    assert stats.invalid_records == 1
    assert len(items) == 1
    assert items[0].upstream_id == "sparse"
    assert "fat" in items[0].missing_fields


def test_recipe_converter_validates_grams_and_does_not_trust_estimated_nutrition():
    foods, _ = convert_food_records(
        [_food()],
        license_by_source={"usda-approx": "approved"},
        nutrition_basis_by_source={"usda-approx": "per_100g"},
    )
    recipe = {
        "id": "oats-bowl",
        "title": "Oats Bowl",
        "servings": 2,
        "source": {"name": "Example", "license": "Unlicense"},
        "ingredients": [{
            "name": "Oats", "unit": "g", "amount": 50,
            "food": {"name": "Oats", "source": "usda-approx", "code": "oats-1"},
            "match": "food",
        }],
        "nutrition": {"protein": 8.45},
        "health": {"confidence": "estimated"},
    }

    items, stats = convert_recipe_records([recipe], foods)

    assert stats.accepted_records == 1
    assert items[0].ingredients[0].match_status == "exact"
    assert items[0].nutrition_status == "estimated_not_authoritative"
    assert items[0].calculated_nutrition is None
    assert items[0].record_status == "quarantined"


def test_recipe_converter_quarantines_fuzzy_or_incompatible_references():
    foods, _ = convert_food_records(
        [_food()],
        license_by_source={"usda-approx": "approved"},
        nutrition_basis_by_source={"usda-approx": "per_100g"},
    )
    recipe = {
        "id": "fuzzy",
        "title": "Fuzzy Recipe",
        "servings": 1,
        "source": {"name": "Example", "license": "Unlicense"},
        "ingredients": [{
            "name": "Unknown", "unit": "cup", "amount": 1,
            "food": {"name": "Unknown", "source": "usda-approx", "code": ""},
            "match": "global-fuzzy",
        }],
    }

    items, stats = convert_recipe_records([recipe], foods)

    assert stats.accepted_records == 0
    assert stats.invalid_records == 1
    assert items == []


def test_portion_profiles_are_validated_but_not_converted_to_nutrition():
    profiles = portion_profile_map({"profiles": [{"key": "apple", "defaultUnit": "个"}, {"key": "apple"}]})

    assert list(profiles) == ["apple"]
    assert profiles["apple"]["defaultUnit"] == "个"


def test_food_converter_rejects_invalid_basis_configuration():
    with pytest.raises(ValueError):
        # An invalid configured basis is a conversion configuration error, not a
        # reason to silently guess a unit.
        convert_food_records([_food()], nutrition_basis_by_source={"usda-approx": "guess"})
