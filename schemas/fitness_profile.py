import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FitnessProfile(BaseModel):
    """个人健身档案字段；PUT 按完整档案替换，未填写字段显式保存为 null。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    height: float | None = Field(default=None, ge=80, le=250)
    weight: float | None = Field(default=None, ge=25, le=300)
    goal: Literal["增肌", "减脂", "体能提升", "保持健康"] | None = None
    experience: Literal["刚开始", "训练一段时间", "比较规律"] | None = None


class FitnessProfileResponse(FitnessProfile):
    user_id: int
    create_at: datetime.datetime
    update_at: datetime.datetime
