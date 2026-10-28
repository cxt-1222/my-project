import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.nutrition_record import NutritionRecordModel
from schemas.nutrition import NutritionRecordInput


async def create_nutrition_record(
    db: AsyncSession,
    user_id: int,
    payload: NutritionRecordInput,
    *,
    source: str = "manual",
    photo_id: int | None = None,
) -> NutritionRecordModel:
    record = NutritionRecordModel(
        user_id=user_id,
        record_date=payload.date,
        meal_type=payload.meal_type,
        food_name=payload.food_name,
        amount=payload.amount,
        unit=payload.unit,
        calories_kcal=payload.calories_kcal,
        protein_g=payload.protein_g,
        carbohydrate_g=payload.carbohydrate_g,
        fat_g=payload.fat_g,
        source=source,
        photo_id=photo_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_daily_nutrition_summary(
    db: AsyncSession,
    user_id: int,
    record_date: datetime.date,
) -> dict:
    statement = (
        select(NutritionRecordModel)
        .where(
            NutritionRecordModel.user_id == user_id,
            NutritionRecordModel.record_date == record_date,
        )
        .order_by(NutritionRecordModel.created_at.asc(), NutritionRecordModel.id.asc())
    )
    result = await db.execute(statement)
    records = result.scalars().all()
    totals = {
        field: sum((getattr(record, field) for record in records), Decimal("0"))
        for field in ("calories_kcal", "protein_g", "carbohydrate_g", "fat_g")
    }
    return {"date": record_date, "records": records, "totals": totals}


async def _get_owned_nutrition_record(
    db: AsyncSession,
    record_id: int,
    user_id: int,
) -> NutritionRecordModel:
    statement = select(NutritionRecordModel).where(
        NutritionRecordModel.id == record_id,
        NutritionRecordModel.user_id == user_id,
    )
    record = (await db.execute(statement)).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="营养记录不存在")
    return record


async def update_nutrition_record(
    db: AsyncSession,
    record_id: int,
    user_id: int,
    payload: NutritionRecordInput,
) -> NutritionRecordModel:
    record = await _get_owned_nutrition_record(db, record_id, user_id)
    record.record_date = payload.date
    record.meal_type = payload.meal_type
    record.food_name = payload.food_name
    record.amount = payload.amount
    record.unit = payload.unit
    record.calories_kcal = payload.calories_kcal
    record.protein_g = payload.protein_g
    record.carbohydrate_g = payload.carbohydrate_g
    record.fat_g = payload.fat_g
    await db.commit()
    await db.refresh(record)
    return record


async def delete_nutrition_record(
    db: AsyncSession,
    record_id: int,
    user_id: int,
) -> None:
    record = await _get_owned_nutrition_record(db, record_id, user_id)
    await db.delete(record)
    await db.commit()
