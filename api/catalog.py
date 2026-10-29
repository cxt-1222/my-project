from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import get_current_user
from models.user import UserModel
from schemas.catalog import (
    ExerciseCatalogResponse,
    FoodCatalogResponse,
    RecipeCatalogResponse,
)
from services.catalog_service import (
    get_exercise,
    get_food,
    get_recipe,
    list_exercises,
    list_foods,
    list_recipes,
)


catalog_router = APIRouter(prefix="/catalog", tags=["健身与饮食目录"])


@catalog_router.get("/exercises", response_model=list[ExerciseCatalogResponse])
async def read_exercises(
    query: Annotated[str | None, Query(max_length=120)] = None,
    dataset: Annotated[str | None, Query(max_length=80)] = None,
    exact_name: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await list_exercises(
        db, query=query, dataset=dataset, exact_name=exact_name, limit=limit,
    )


@catalog_router.get("/exercises/{exercise_id}", response_model=ExerciseCatalogResponse)
async def read_exercise(
    exercise_id: int,
    dataset: Annotated[str | None, Query(max_length=80)] = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_exercise(db, exercise_id, dataset=dataset)


@catalog_router.get("/foods", response_model=list[FoodCatalogResponse])
async def read_foods(
    query: Annotated[str | None, Query(max_length=120)] = None,
    source_key: Annotated[str | None, Query(max_length=120)] = None,
    exact_name: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await list_foods(
        db, query=query, source_key=source_key, exact_name=exact_name, limit=limit,
    )


@catalog_router.get("/foods/{food_id}", response_model=FoodCatalogResponse)
async def read_food(
    food_id: int,
    source_key: Annotated[str | None, Query(max_length=120)] = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_food(db, food_id, source_key=source_key)


@catalog_router.get("/recipes", response_model=list[RecipeCatalogResponse])
async def read_recipes(
    query: Annotated[str | None, Query(max_length=120)] = None,
    dataset: Annotated[str | None, Query(max_length=80)] = None,
    exact_name: bool = False,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await list_recipes(
        db, query=query, dataset=dataset, exact_name=exact_name, limit=limit,
    )


@catalog_router.get("/recipes/{recipe_id}", response_model=RecipeCatalogResponse)
async def read_recipe(
    recipe_id: int,
    dataset: Annotated[str | None, Query(max_length=80)] = None,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_recipe(db, recipe_id, dataset=dataset)
