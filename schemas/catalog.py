from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CatalogSourceReference(BaseModel):
    """Auditable identity of one approved record from a pinned dataset."""

    dataset: str
    repository: str
    revision: str
    source_record_id: str
    content_sha256: str


class ExerciseVideoResponse(BaseModel):
    id: int
    variant: str
    allowed_use: Literal["link", "embed", "host"]
    source_url: str
    source_host: str
    attribution: str
    playback_status: Literal["available", "unavailable"] = "available"


class ExerciseCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    aliases: list[str] = Field(default_factory=list)
    fields: dict[str, Any]
    missing_fields: list[str] = Field(default_factory=list)
    source: CatalogSourceReference
    videos: list[ExerciseVideoResponse] = Field(default_factory=list)
    video_status: Literal["available", "unavailable"]
    video_message: str


class NutrientValues(BaseModel):
    """Deterministically calculated nutrient values with an explicit basis."""

    model_config = ConfigDict(extra="forbid")

    basis: Literal["per_100g", "recipe_total", "per_serving"]
    calories_kcal: Decimal | None = None
    protein_g: Decimal | None = None
    carbohydrate_g: Decimal | None = None
    fat_g: Decimal | None = None
    missing_fields: list[str] = Field(default_factory=list)
    complete: bool

    @field_serializer(
        "calories_kcal",
        "protein_g",
        "carbohydrate_g",
        "fat_g",
    )
    def serialize_decimal(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class FoodNutritionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basis: Literal["per_100g", "per_serving", "other"]
    calories_kcal: Decimal | None = None
    protein_g: Decimal | None = None
    carbohydrate_g: Decimal | None = None
    fat_g: Decimal | None = None
    raw_values: dict[str, Decimal] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    complete: bool
    per_100g: NutrientValues | None = None
    normalization_note: str = ""

    @field_serializer(
        "calories_kcal",
        "protein_g",
        "carbohydrate_g",
        "fat_g",
    )
    def serialize_decimal(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class FoodCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    source_key: str
    source: CatalogSourceReference
    edible_value: Decimal | None = None
    nutrition: FoodNutritionResponse

    @field_serializer("edible_value")
    def serialize_edible_value(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class RecipeIngredientResponse(BaseModel):
    position: int
    name: str
    amount: Decimal | None = None
    unit: str
    note: str
    food_source_key: str
    food_upstream_id: str
    match_status: Literal["unresolved", "exact", "approved_alias", "fuzzy", "missing"]

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None


class RecipeNutritionIngredientIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int
    name: str
    reason: str


class RecipeNutritionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: NutrientValues
    per_serving: NutrientValues
    missing_ingredients: list[RecipeNutritionIngredientIssue] = Field(default_factory=list)
    calculation: str
    complete: bool


class RecipeCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    servings: Decimal
    source: CatalogSourceReference
    source_name: str
    source_url: str
    source_revision: str
    source_license: str
    ingredients: list[RecipeIngredientResponse] = Field(default_factory=list)
    nutrition: RecipeNutritionResponse

    @field_serializer("servings")
    def serialize_servings(self, value: Decimal) -> float:
        return float(value)
