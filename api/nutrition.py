import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from clients.rustfs import get_s3_client
from core.config import settings
from core.database import get_db
from core.security import get_current_user
from models.nutrition_photo import NutritionPhotoModel
from models.user import UserModel
from schemas.nutrition import (
    DailyNutritionSummary,
    NutritionRecordCreate,
    NutritionRecordResponse,
    NutritionRecordUpdate,
)
from schemas.nutrition_photo import (
    NutritionPhotoConfirmRequest,
    NutritionPhotoConfirmResponse,
    NutritionPhotoPreviewResponse,
)
from services.nutrition_photo_service import (
    MAX_IMAGE_BYTES,
    cancel_photo_preview,
    confirm_photo_preview,
    create_photo_preview,
    get_owned_photo,
    validate_meal_image,
)
from services.nutrition_service import (
    create_nutrition_record,
    delete_nutrition_record,
    get_daily_nutrition_summary,
    update_nutrition_record,
)
from services.nutrition_vision import (
    NutritionVisionError,
    NutritionVisionNotConfigured,
    recognize_food_image,
)

nutrition_router = APIRouter(prefix="/nutrition", tags=["营养记录"])


@nutrition_router.get("/daily", response_model=DailyNutritionSummary)
async def read_my_daily_nutrition(
    date: datetime.date = Query(..., description="饮食日期，格式 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await get_daily_nutrition_summary(db, current_user.id, date)


@nutrition_router.post(
    "/records",
    response_model=NutritionRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_nutrition_record(
    payload: NutritionRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await create_nutrition_record(db, current_user.id, payload)


@nutrition_router.put("/records/{record_id}", response_model=NutritionRecordResponse)
async def update_my_nutrition_record(
    record_id: int,
    payload: NutritionRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return await update_nutrition_record(db, record_id, current_user.id, payload)


@nutrition_router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_nutrition_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    await delete_nutrition_record(db, record_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _photo_preview_response(photo: NutritionPhotoModel) -> NutritionPhotoPreviewResponse:
    return NutritionPhotoPreviewResponse(
        id=photo.id,
        status=photo.status,
        image_url=f"/nutrition/photos/{photo.id}/image",
        items=photo.recognized_payload,
        created_at=photo.created_at,
    )


async def _stream_photo_body(body):
    try:
        async for chunk in body:
            yield chunk
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()


@nutrition_router.post("/photos/preview", response_model=NutritionPhotoPreviewResponse)
async def create_my_nutrition_photo_preview(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    s3=Depends(get_s3_client),
    current_user: UserModel = Depends(get_current_user),
):
    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    await file.close()
    validate_meal_image(content_type, image_bytes)

    try:
        items = await recognize_food_image(image_bytes, content_type)
    except NutritionVisionNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NutritionVisionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    photo = await create_photo_preview(db, s3, current_user.id, image_bytes, content_type, items)
    return _photo_preview_response(photo)


@nutrition_router.get("/photos/{preview_id}", response_model=NutritionPhotoPreviewResponse)
async def read_my_nutrition_photo_preview(
    preview_id: int,
    db: AsyncSession = Depends(get_db),
    s3=Depends(get_s3_client),
    current_user: UserModel = Depends(get_current_user),
):
    photo = await get_owned_photo(db, preview_id, current_user.id)
    return _photo_preview_response(photo)


@nutrition_router.get("/photos/{preview_id}/image")
async def read_my_nutrition_photo_image(
    preview_id: int,
    db: AsyncSession = Depends(get_db),
    s3=Depends(get_s3_client),
    current_user: UserModel = Depends(get_current_user),
):
    photo = await get_owned_photo(db, preview_id, current_user.id)
    try:
        stored = await s3.get_object(Bucket=settings.RUSTFS_BUCKET, Key=photo.image_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound", "404"}:
            raise HTTPException(status_code=404, detail="餐食图片不存在") from exc
        raise HTTPException(status_code=502, detail="暂时无法读取餐食图片") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="暂时无法读取餐食图片") from exc
    return StreamingResponse(
        _stream_photo_body(stored["Body"]),
        media_type=photo.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@nutrition_router.delete("/photos/{preview_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_my_nutrition_photo_preview(
    preview_id: int,
    db: AsyncSession = Depends(get_db),
    s3=Depends(get_s3_client),
    current_user: UserModel = Depends(get_current_user),
):
    await cancel_photo_preview(db, s3, preview_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@nutrition_router.post(
    "/photos/{preview_id}/confirm",
    response_model=NutritionPhotoConfirmResponse,
)
async def confirm_my_nutrition_photo_preview(
    preview_id: int,
    payload: NutritionPhotoConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    photo, records = await confirm_photo_preview(
        db,
        preview_id,
        current_user.id,
        payload.date,
        payload.items,
    )
    return NutritionPhotoConfirmResponse(
        preview_id=photo.id,
        image_url=f"/nutrition/photos/{photo.id}/image",
        records=records,
    )
