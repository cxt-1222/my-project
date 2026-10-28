import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TrainingGoal = Literal["增肌", "减脂", "体能提升", "保持健康"]
TrainingExperience = Literal["刚开始", "训练一段时间", "比较规律"]


class TrainingPlanExercise(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    sets: int = Field(ge=1, le=20)
    reps: str = Field(min_length=1, max_length=32)
    rest_seconds: int = Field(default=90, ge=0, le=900)
    notes: str | None = Field(default=None, max_length=500)
    evidence_type: Literal["knowledge_base", "general_advice"] = "general_advice"
    source_refs: list[int] = Field(default_factory=list, max_length=5)
    source_titles: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("name", "reps")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


class TrainingPlanDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str = Field(min_length=1, max_length=20, description="如周一、Day 1")
    focus: str | None = Field(default=None, max_length=120)
    is_rest_day: bool = False
    exercises: list[TrainingPlanExercise] = Field(default_factory=list, max_length=20)

    @field_validator("day", "focus")
    @classmethod
    def strip_day_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @model_validator(mode="after")
    def validate_day_contents(self):
        if self.is_rest_day and self.exercises:
            raise ValueError("休息日不能包含训练动作")
        if not self.is_rest_day and not self.exercises:
            raise ValueError("训练日至少需要一个动作")
        return self


class TrainingPlanPayload(BaseModel):
    """创建或完整替换计划的请求结构。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    goal: TrainingGoal | None = None
    experience: TrainingExperience | None = None
    days: list[TrainingPlanDay] = Field(min_length=1, max_length=7)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("计划名称不能为空")
        return value

    @model_validator(mode="after")
    def validate_unique_days(self):
        day_names = [day.day.casefold() for day in self.days]
        if len(day_names) != len(set(day_names)):
            raise ValueError("一周计划中的日期名称不能重复")
        return self


class TrainingPlanResponse(TrainingPlanPayload):
    id: int
    user_id: int
    create_at: datetime.datetime
    update_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class TrainingPlanGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=2, max_length=1000)
    equipment: str | None = Field(default=None, max_length=300)
    training_days: int | None = Field(default=None, ge=1, le=7)
    limitations: str | None = Field(default=None, max_length=500)

    @field_validator("request", "equipment", "limitations")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value


class TrainingPlanPreviewResponse(BaseModel):
    plan: TrainingPlanPayload
    general_notes: list[str] = Field(default_factory=list, max_length=10)
    sources: list[dict] = Field(default_factory=list)
