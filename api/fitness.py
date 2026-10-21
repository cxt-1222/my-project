from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.user import UserModel
from schemas.fitness_profile import FitnessProfile, FitnessProfileResponse
from services.fitness_profile_service import get_fitness_profile, save_fitness_profile

fitness_router = APIRouter(prefix="/fitness", tags=["健身档案"])


@fitness_router.get("/profile", response_model=FitnessProfileResponse | None)
async def read_my_fitness_profile(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """读取登录用户自己的档案；尚未创建时返回 JSON null。"""
    return await get_fitness_profile(db, current_user.id)


@fitness_router.put("/profile", response_model=FitnessProfileResponse)
async def write_my_fitness_profile(
    profile: FitnessProfile,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """保存登录用户自己的档案；不会接受客户端指定的 user_id。"""
    return await save_fitness_profile(db, current_user.id, profile)
