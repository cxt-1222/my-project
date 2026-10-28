from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.user import UserModel
from schemas.training_workout import (
    TrainingStatsResponse,
    WorkoutCompleteRequest,
    WorkoutResponse,
    WorkoutStartRequest,
)
from services.training_workout_service import (
    cancel_workout,
    complete_workout,
    delete_workout,
    get_workout,
    get_training_stats,
    list_workouts,
    start_workout,
)

workout_router = APIRouter(prefix="/training", tags=["训练打卡"])


@workout_router.post("/workouts", response_model=WorkoutResponse, status_code=status.HTTP_201_CREATED)
async def start_my_workout(
    payload: WorkoutStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await start_workout(
        db,
        current_user.id,
        plan_id=payload.plan_id,
        day=payload.day,
    )


@workout_router.post("/workouts/{workout_id}/complete", response_model=WorkoutResponse)
async def complete_my_workout(
    workout_id: int,
    payload: WorkoutCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await complete_workout(db, workout_id, current_user.id, payload)


@workout_router.get("/workouts/{workout_id}", response_model=WorkoutResponse)
async def read_my_workout(
    workout_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_workout(db, workout_id, current_user.id)


@workout_router.post("/workouts/{workout_id}/cancel", response_model=WorkoutResponse)
async def cancel_my_workout(
    workout_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await cancel_workout(db, workout_id, current_user.id)


@workout_router.get("/workouts", response_model=list[WorkoutResponse])
async def list_my_workouts(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await list_workouts(db, current_user.id, limit=limit, offset=offset)


@workout_router.delete("/workouts/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_workout(
    workout_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    await delete_workout(db, workout_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workout_router.get("/stats", response_model=TrainingStatsResponse)
async def read_my_training_stats(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_training_stats(db, current_user.id)
