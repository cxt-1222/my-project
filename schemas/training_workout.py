import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkoutStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: int = Field(ge=1)
    day: str = Field(min_length=1, max_length=20)

    @field_validator("day")
    @classmethod
    def strip_day(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请选择训练日")
        return value


class PerformedExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    sets: int = Field(ge=1, le=30)
    reps: int = Field(ge=1, le=300)
    weight_kg: float | None = Field(default=None, ge=0, le=500)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("动作名称不能为空")
        return value


class WorkoutCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exercises: list[PerformedExerciseInput] = Field(min_length=1, max_length=20)
    body_weight_kg: float | None = Field(default=None, ge=25, le=300)

    @field_validator("exercises")
    @classmethod
    def reject_duplicate_exercises(cls, values: list[PerformedExerciseInput]):
        names = [exercise.name.casefold() for exercise in values]
        if len(names) != len(set(names)):
            raise ValueError("同一动作不能重复填写")
        return values


class WorkoutExerciseResponse(BaseModel):
    name: str
    sets: int
    reps: int | None = None
    weight_kg: float | None = None
    planned_sets: int | None = None
    planned_reps: str | None = None


class WorkoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    plan_id: int | None
    plan_title: str
    plan_day: str
    focus: str | None
    status: Literal["in_progress", "completed", "cancelled"]
    started_at: datetime.datetime
    completed_at: datetime.datetime | None
    cancelled_at: datetime.datetime | None
    duration_seconds: int | None
    body_weight_kg: float | None
    exercises: list[WorkoutExerciseResponse]


class TrainingStatsResponse(BaseModel):
    week_start_date: datetime.date
    week_workouts_count: int
    streak_days: int
    week_duration_seconds: int
    week_volume_kg: float
    primary_focus: str | None
    latest_body_weight_kg: float | None
    body_weight_change_kg: float | None

