import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from schemas.nutrition import MealType, NutritionRecordResponse


class NutritionPhotoFoodInput(BaseModel):
    """One editable food item returned by or submitted from a photo preview."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    meal_type: MealType
    food_name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit: str = Field(min_length=1, max_length=20)
    calories_kcal: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    protein_g: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    carbohydrate_g: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    fat_g: Decimal = Field(ge=0, max_digits=12, decimal_places=2)

    @field_validator("food_name", "unit")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不得为空")
        return value

    @field_serializer(
        "amount",
        "calories_kcal",
        "protein_g",
        "carbohydrate_g",
        "fat_g",
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class NutritionPhotoPreviewResponse(BaseModel):
    id: int
    status: Literal["preview", "confirmed", "cancelled"]
    image_url: str
    is_estimate: bool = True
    items: list[NutritionPhotoFoodInput]
    created_at: datetime.datetime


class NutritionPhotoConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: datetime.date
    items: list[NutritionPhotoFoodInput] = Field(min_length=1, max_length=20)


class NutritionPhotoConfirmResponse(BaseModel):
    preview_id: int
    image_url: str
    records: list[NutritionRecordResponse]
