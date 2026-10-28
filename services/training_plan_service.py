import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.training_plan import TrainingPlanModel
from schemas.training_plan import TrainingPlanPayload


async def list_training_plans(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[TrainingPlanModel]:
    statement = (
        select(TrainingPlanModel)
        .where(TrainingPlanModel.user_id == user_id)
        .order_by(TrainingPlanModel.update_at.desc(), TrainingPlanModel.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(statement)
    return list(result.scalars().all())


async def get_training_plan(
    db: AsyncSession,
    plan_id: int,
    user_id: int,
) -> TrainingPlanModel:
    statement = select(TrainingPlanModel).where(
        TrainingPlanModel.id == plan_id,
        TrainingPlanModel.user_id == user_id,
    )
    plan = (await db.execute(statement)).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="训练计划不存在")
    return plan


async def create_training_plan(
    db: AsyncSession,
    user_id: int,
    payload: TrainingPlanPayload,
) -> TrainingPlanModel:
    plan = TrainingPlanModel(
        user_id=user_id,
        title=payload.title,
        goal=payload.goal,
        experience=payload.experience,
        days=[day.model_dump() for day in payload.days],
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def update_training_plan(
    db: AsyncSession,
    plan_id: int,
    user_id: int,
    payload: TrainingPlanPayload,
) -> TrainingPlanModel:
    plan = await get_training_plan(db, plan_id, user_id)
    plan.title = payload.title
    plan.goal = payload.goal
    plan.experience = payload.experience
    plan.days = [day.model_dump() for day in payload.days]
    plan.update_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(plan)
    return plan
