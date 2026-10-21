from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.fitness_profile import FitnessProfileModel
from schemas.fitness_profile import FitnessProfile


async def get_fitness_profile(db: AsyncSession, user_id: int) -> FitnessProfileModel | None:
    """只按已鉴权账号ID读取档案；调用方不得传入任意 user_id。"""
    return await db.get(FitnessProfileModel, user_id)


async def save_fitness_profile(
    db: AsyncSession,
    user_id: int,
    profile: FitnessProfile,
) -> FitnessProfileModel:
    """创建或完整替换当前用户的档案，PostgreSQL upsert 可安全处理并发首次保存。"""
    values = profile.model_dump()
    statement = pg_insert(FitnessProfileModel).values(user_id=user_id, **values)
    statement = statement.on_conflict_do_update(
        index_elements=[FitnessProfileModel.user_id],
        set_={**values, "update_at": func.now()},
    )
    await db.execute(statement)
    await db.commit()
    return await db.get(FitnessProfileModel, user_id)
