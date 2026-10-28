import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FitnessProfile(BaseModel):
    """个人健身档案字段；PUT 按完整档案替换，未填写字段显式保存为 null。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)

    height: float | None = Field(default=None, ge=80, le=250)
    weight: float | None = Field(default=None, ge=25, le=300)
    age: int | None = Field(default=None, ge=13, le=100)
    sex: Literal["男", "女", "不愿透露"] | None = None
    goal: Literal["增肌", "减脂", "体能提升", "保持健康"] | None = None
    experience: Literal["刚开始", "训练一段时间", "比较规律"] | None = None
    weekly_training_days: int | None = Field(default=None, ge=1, le=7)
    equipment: str | None = Field(default=None, max_length=300)
    limitations: str | None = Field(default=None, max_length=500)

    @field_validator("equipment", "limitations", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class FitnessProfileResponse(FitnessProfile):
    user_id: int
    create_at: datetime.datetime
    update_at: datetime.datetime
