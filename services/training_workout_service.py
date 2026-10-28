import datetime
import re
from collections import Counter
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.training_plan import TrainingPlanModel
from models.training_record import TrainingRecordModel
from schemas.training_workout import WorkoutCompleteRequest
from services.training_plan_service import get_training_plan

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _local_datetime(value: datetime.datetime) -> datetime.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(APP_TIMEZONE)


def _planned_reps(value: object) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 1


async def start_workout(
    db: AsyncSession,
    user_id: int,
    *,
    plan_id: int,
    day: str,
) -> TrainingRecordModel:
    plan: TrainingPlanModel = await get_training_plan(db, plan_id, user_id)
    selected_day = next(
        (item for item in (plan.days or []) if str(item.get("day", "")).casefold() == day.casefold()),
        None,
    )
    if selected_day is None:
        raise HTTPException(status_code=404, detail="该训练日不在计划中")
    if selected_day.get("is_rest_day"):
        raise HTTPException(status_code=422, detail="休息日不能开始训练")

    exercise_snapshot = []
    for item in selected_day.get("exercises", []):
        prescribed_reps = str(item.get("reps", ""))
        prescribed_sets = int(item.get("sets", 1))
        exercise_snapshot.append({
            "name": str(item["name"]).strip(),
            "sets": prescribed_sets,
            "reps": _planned_reps(prescribed_reps),
            "weight_kg": None,
            "planned_sets": prescribed_sets,
            "planned_reps": prescribed_reps,
        })

    record = TrainingRecordModel(
        user_id=user_id,
        plan_id=plan.id,
        plan_title=plan.title,
        plan_day=str(selected_day.get("day", day)),
        focus=selected_day.get("focus"),
        status="in_progress",
        started_at=_utc_now(),
        exercises=exercise_snapshot,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_workout(
    db: AsyncSession,
    workout_id: int,
    user_id: int,
    *,
    for_update: bool = False,
) -> TrainingRecordModel:
    statement = select(TrainingRecordModel).where(
        TrainingRecordModel.id == workout_id,
        TrainingRecordModel.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    record = (await db.execute(statement)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="训练记录不存在")
    return record


async def complete_workout(
    db: AsyncSession,
    workout_id: int,
    user_id: int,
    payload: WorkoutCompleteRequest,
) -> TrainingRecordModel:
    record = await get_workout(db, workout_id, user_id, for_update=True)
    if record.status != "in_progress":
        raise HTTPException(status_code=409, detail="只有进行中的训练可以完成")

    planned = {item["name"].casefold(): item for item in (record.exercises or [])}
    unknown = [item.name for item in payload.exercises if item.name.casefold() not in planned]
    if unknown:
        raise HTTPException(status_code=422, detail="完成记录中包含不属于本次计划的动作")

    final_exercises = []
    for item in payload.exercises:
        snapshot = planned[item.name.casefold()]
        final_exercises.append({
            "name": item.name,
            "sets": item.sets,
            "reps": item.reps,
            "weight_kg": item.weight_kg,
            "planned_sets": snapshot.get("planned_sets"),
            "planned_reps": snapshot.get("planned_reps"),
        })

    completed_at = _utc_now()
    started_at = record.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=datetime.timezone.utc)
    record.exercises = final_exercises
    record.body_weight_kg = payload.body_weight_kg
    record.completed_at = completed_at
    record.duration_seconds = max(0, int((completed_at - started_at).total_seconds()))
    record.status = "completed"
    await db.commit()
    await db.refresh(record)
    return record


async def cancel_workout(db: AsyncSession, workout_id: int, user_id: int) -> TrainingRecordModel:
    record = await get_workout(db, workout_id, user_id, for_update=True)
    if record.status != "in_progress":
        raise HTTPException(status_code=409, detail="只有进行中的训练可以取消")
    record.status = "cancelled"
    record.cancelled_at = _utc_now()
    await db.commit()
    await db.refresh(record)
    return record


async def list_workouts(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[TrainingRecordModel]:
    statement = (
        select(TrainingRecordModel)
        .where(
            TrainingRecordModel.user_id == user_id,
            TrainingRecordModel.status != "cancelled",
        )
        .order_by(TrainingRecordModel.started_at.desc(), TrainingRecordModel.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(statement)
    return list(result.scalars().all())


async def delete_workout(db: AsyncSession, workout_id: int, user_id: int) -> None:
    record = await get_workout(db, workout_id, user_id)
    if record.status != "completed":
        raise HTTPException(status_code=409, detail="只能删除已完成的训练记录")
    await db.delete(record)
    await db.commit()


def build_training_stats(
    records: list[TrainingRecordModel],
    *,
    now: datetime.datetime | None = None,
) -> dict:
    now_local = _local_datetime(now or _utc_now())
    today = now_local.date()
    week_start = today - datetime.timedelta(days=today.weekday())
    completed = [record for record in records if record.status == "completed" and record.completed_at]
    localized = [(record, _local_datetime(record.completed_at)) for record in completed]
    weekly = [(record, completed_at) for record, completed_at in localized if week_start <= completed_at.date() <= today]

    workout_dates = {completed_at.date() for _, completed_at in localized}
    streak_start = today if today in workout_dates else today - datetime.timedelta(days=1)
    streak = 0
    cursor = streak_start
    while cursor in workout_dates:
        streak += 1
        cursor -= datetime.timedelta(days=1)

    volume = 0.0
    for record, _ in weekly:
        for exercise in record.exercises or []:
            if exercise.get("weight_kg") is None:
                continue
            volume += int(exercise.get("sets", 0)) * int(exercise.get("reps", 0)) * float(exercise["weight_kg"])

    focus_counts = Counter(record.focus.strip() for record, _ in weekly if record.focus and record.focus.strip())
    latest_focus_date = {}
    for record, completed_at in weekly:
        if record.focus and record.focus.strip():
            latest_focus_date[record.focus.strip()] = max(
                latest_focus_date.get(record.focus.strip(), completed_at), completed_at
            )
    primary_focus = sorted(
        focus_counts,
        key=lambda focus: (-focus_counts[focus], -latest_focus_date[focus].timestamp()),
    )[0] if focus_counts else None

    weighed = sorted(
        ((completed_at, record.body_weight_kg) for record, completed_at in localized if record.body_weight_kg is not None),
        key=lambda item: item[0],
    )
    weight_change = None
    if len(weighed) >= 2:
        weight_change = round(float(weighed[-1][1]) - float(weighed[0][1]), 2)

    return {
        "week_start_date": week_start,
        "week_workouts_count": len(weekly),
        "streak_days": streak,
        "week_duration_seconds": sum(record.duration_seconds or 0 for record, _ in weekly),
        "week_volume_kg": round(volume, 2),
        "primary_focus": primary_focus,
        "latest_body_weight_kg": float(weighed[-1][1]) if weighed else None,
        "body_weight_change_kg": weight_change,
    }


async def get_training_stats(db: AsyncSession, user_id: int) -> dict:
    statement = (
        select(TrainingRecordModel)
        .where(
            TrainingRecordModel.user_id == user_id,
            TrainingRecordModel.status == "completed",
        )
        .order_by(TrainingRecordModel.completed_at.asc())
    )
    result = await db.execute(statement)
    return build_training_stats(list(result.scalars().all()))
