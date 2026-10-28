import datetime
import uuid
from typing import Any

from fastapi import HTTPException
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.nutrition_photo import NutritionPhotoModel
from models.nutrition_record import NutritionRecordModel
from schemas.nutrition_photo import NutritionPhotoFoodInput

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def validate_meal_image(content_type: str | None, image_bytes: bytes) -> str:
    normalized = (content_type or "").lower().split(";", 1)[0].strip()
    extension = ALLOWED_IMAGE_TYPES.get(normalized)
    if not extension:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 WebP 餐食图片")
    if not image_bytes:
        raise HTTPException(status_code=400, detail="图片内容不能为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片大小不能超过 10 MB")
    signatures = {
        "image/jpeg": image_bytes.startswith(b"\xff\xd8\xff"),
        "image/png": image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP",
    }
    if not signatures.get(normalized, False):
        raise HTTPException(status_code=415, detail="图片内容与声明的格式不一致")
    return extension


def nutrition_photo_key(user_id: int, extension: str) -> str:
    return f"nutrition-photos/{user_id}/{uuid.uuid4().hex}{extension}"


async def get_owned_photo(db: AsyncSession, preview_id: int, user_id: int) -> NutritionPhotoModel:
    statement = select(NutritionPhotoModel).where(
        NutritionPhotoModel.id == preview_id,
        NutritionPhotoModel.user_id == user_id,
    )
    photo = (await db.execute(statement)).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="餐食图片预览不存在")
    if photo.status == "cancelled":
        raise HTTPException(status_code=404, detail="餐食图片预览不存在")
    return photo


async def cancel_photo_preview(db: AsyncSession, s3: Any, preview_id: int, user_id: int) -> None:
    # Serialize cancellation with confirmation so only one terminal state can win.
    statement = select(NutritionPhotoModel).where(
        NutritionPhotoModel.id == preview_id,
        NutritionPhotoModel.user_id == user_id,
    ).with_for_update()
    photo = (await db.execute(statement)).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="餐食图片预览不存在")
    if photo.status == "confirmed":
        raise HTTPException(status_code=409, detail="仅可取消尚未确认的餐食图片预览")
    if photo.status != "cancelled":
        photo.status = "cancelled"
        await db.commit()
    try:
        await s3.delete_object(Bucket=settings.RUSTFS_BUCKET, Key=photo.image_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "NotFound", "404"}:
            raise HTTPException(status_code=502, detail="预览已取消，但图片清理失败") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="预览已取消，但图片清理失败") from exc


async def create_photo_preview(
    db: AsyncSession,
    s3: Any,
    user_id: int,
    image_bytes: bytes,
    content_type: str,
    items: list[NutritionPhotoFoodInput],
) -> NutritionPhotoModel:
    extension = ALLOWED_IMAGE_TYPES[content_type]
    image_key = nutrition_photo_key(user_id, extension)
    try:
        await s3.put_object(
            Bucket=settings.RUSTFS_BUCKET,
            Key=image_key,
            Body=image_bytes,
            ContentType=content_type,
        )
        photo = NutritionPhotoModel(
            user_id=user_id,
            image_key=image_key,
            content_type=content_type,
            status="preview",
            recognized_payload=[item.model_dump(mode="json") for item in items],
        )
        db.add(photo)
        await db.commit()
        await db.refresh(photo)
        return photo
    except Exception:
        try:
            await s3.delete_object(Bucket=settings.RUSTFS_BUCKET, Key=image_key)
        except Exception:
            pass
        await db.rollback()
        raise


async def confirm_photo_preview(
    db: AsyncSession,
    preview_id: int,
    user_id: int,
    record_date: datetime.date,
    items: list[NutritionPhotoFoodInput],
) -> tuple[NutritionPhotoModel, list[NutritionRecordModel]]:
    statement = (
        select(NutritionPhotoModel)
        .where(
            NutritionPhotoModel.id == preview_id,
            NutritionPhotoModel.user_id == user_id,
        )
        .with_for_update()
    )
    photo = (await db.execute(statement)).scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="餐食图片预览不存在")
    if photo.status != "preview":
        raise HTTPException(status_code=409, detail="该餐食图片预览已经确认，不能重复保存")

    records = [
        NutritionRecordModel(
            user_id=user_id,
            record_date=record_date,
            meal_type=item.meal_type,
            food_name=item.food_name,
            amount=item.amount,
            unit=item.unit,
            calories_kcal=item.calories_kcal,
            protein_g=item.protein_g,
            carbohydrate_g=item.carbohydrate_g,
            fat_g=item.fat_g,
            source="photo",
            photo_id=photo.id,
        )
        for item in items
    ]
    photo.status = "confirmed"
    photo.recognized_payload = [item.model_dump(mode="json") for item in items]
    db.add_all(records)
    try:
        await db.commit()
        for record in records:
            await db.refresh(record)
        await db.refresh(photo)
    except Exception:
        await db.rollback()
        raise
    return photo, records


