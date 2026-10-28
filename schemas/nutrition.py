import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class NutritionRecordInput(BaseModel):
    """User-provided values for one food entry; ownership is never client supplied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: datetime.date
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


class NutritionRecordCreate(NutritionRecordInput):
    pass


class NutritionRecordUpdate(NutritionRecordInput):
    pass


class NutritionRecordResponse(NutritionRecordInput):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    date: datetime.date = Field(validation_alias="record_date")
    id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    source: Literal["manual", "photo"] = "manual"
    photo_id: int | None = None

    @field_serializer(
        "amount",
        "calories_kcal",
        "protein_g",
        "carbohydrate_g",
        "fat_g",
    )
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class DailyNutritionTotals(BaseModel):
    calories_kcal: Decimal = Decimal("0")
    protein_g: Decimal = Decimal("0")
    carbohydrate_g: Decimal = Decimal("0")
    fat_g: Decimal = Decimal("0")

    @field_serializer("calories_kcal", "protein_g", "carbohydrate_g", "fat_g")
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class DailyNutritionSummary(BaseModel):
    date: datetime.date
    records: list[NutritionRecordResponse]
    totals: DailyNutritionTotals
