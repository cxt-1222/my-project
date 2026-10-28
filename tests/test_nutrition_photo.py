import datetime
from io import BytesIO
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import Headers, UploadFile

from api.nutrition import (
    create_my_nutrition_photo_preview,
    nutrition_router,
    read_my_nutrition_photo_image,
)
from core.config import settings
from core.security import get_current_user
from models.nutrition_photo import NutritionPhotoModel
from models.nutrition_record import NutritionRecordModel
from schemas.nutrition_photo import NutritionPhotoConfirmRequest, NutritionPhotoFoodInput
from services.nutrition_photo_service import (
    MAX_IMAGE_BYTES,
    cancel_photo_preview,
    confirm_photo_preview,
    create_photo_preview,
    nutrition_photo_key,
    validate_meal_image,
)
from services.nutrition_vision import (
    NutritionVisionError,
    NutritionVisionNotConfigured,
    parse_vision_items,
    recognize_food_image,
)


def food_item(**changes):
    values = {
        "meal_type": "lunch",
        "food_name": "鸡胸肉",
        "amount": "150",
        "unit": "g",
        "calories_kcal": "248",
        "protein_g": "46.5",
        "carbohydrate_g": "0",
        "fat_g": "5.4",
    }
    values.update(changes)
    return NutritionPhotoFoodInput.model_validate(values)


class FakeDb:
    def __init__(self, photo):
        self.photo = photo
        self.statement = None
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(scalar_one_or_none=lambda: self.photo)

    def add_all(self, values):
        self.added.extend(values)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _value):
        return None

    def add(self, value):
        self.added.append(value)


class FakeAsyncImageBody:
    def __init__(self, value):
        self.value = value
        self.closed = False

    def __aiter__(self):
        async def chunks():
            yield self.value

        return chunks()

    def close(self):
        self.closed = True


class NutritionPhotoSchemaTests(unittest.TestCase):
    def test_photo_model_is_registered_and_routes_require_authentication(self):
        self.assertIn("kh_nutrition_photo", NutritionPhotoModel.metadata.tables)
        self.assertIn("photo_id", NutritionRecordModel.__table__.columns)
        routes = [route for route in nutrition_router.routes if "/photos" in route.path]
        self.assertEqual(
            {route.path for route in routes},
            {
                "/nutrition/photos/preview",
                "/nutrition/photos/{preview_id}",
                "/nutrition/photos/{preview_id}/image",
                "/nutrition/photos/{preview_id}/confirm",
            },
        )
        for route in routes:
            dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
            self.assertIn(get_current_user, dependency_calls)
        methods = {method for route in routes for method in route.methods}
        self.assertIn("DELETE", methods)

    def test_confirmation_schema_rejects_empty_or_unknown_fields(self):
        with self.assertRaises(ValidationError):
            NutritionPhotoConfirmRequest.model_validate({"date": "2026-10-23", "items": []})
        with self.assertRaises(ValidationError):
            NutritionPhotoConfirmRequest.model_validate(
                {"date": "2026-10-23", "items": [food_item().model_dump()], "user_id": 2}
            )

    def test_parses_json_and_rejects_empty_or_invalid_model_output(self):
        parsed = parse_vision_items(
            '```json\n{"items": [{"meal_type":"lunch","food_name":"鸡胸肉",'
            '"amount":150,"unit":"g","calories_kcal":248,"protein_g":46.5,'
            '"carbohydrate_g":0,"fat_g":5.4}]}\n```'
        )
        self.assertEqual(parsed[0].food_name, "鸡胸肉")
        self.assertEqual(parsed[0].protein_g, Decimal("46.5"))
        with self.assertRaises(NutritionVisionError):
            parse_vision_items('{"items": []}')
        with self.assertRaises(NutritionVisionError):
            parse_vision_items('{"items": [{"food_name": "?"}]}')


class NutritionVisionDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_provider_status_and_request_id_without_exposing_credentials(self):
        request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
        response = httpx.Response(
            401,
            json={"error": {"code": "InvalidApiKey", "message": "do not log this message"}},
            headers={"x-request-id": "request-123"},
            request=request,
        )

        class ClientStub:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, *_args, **_kwargs):
                return response

        with (
            patch("services.nutrition_vision.httpx.AsyncClient", return_value=ClientStub()),
            patch("services.nutrition_vision.settings.QWEN_API_KEY", "test-secret"),
            patch("services.nutrition_vision.settings.QWEN_BASE_URL", "https://provider.example/v1"),
            patch("services.nutrition_vision.settings.QWEN_VISION_MODEL_NAME", "vision-test"),
            self.assertLogs("services.nutrition_vision", level="WARNING") as captured,
        ):
            with self.assertRaises(NutritionVisionError):
                await recognize_food_image(b"\xff\xd8\xffimage", "image/jpeg")

        logged = "\n".join(captured.output)
        self.assertIn("HTTP 401", logged)
        self.assertIn("InvalidApiKey", logged)
        self.assertIn("request-123", logged)
        self.assertNotIn("do not log this message", logged)
        self.assertNotIn("test-secret", logged)


class NutritionPhotoImageValidationTests(unittest.TestCase):
    def test_accepts_supported_signatures_and_builds_account_scoped_key(self):
        self.assertEqual(validate_meal_image("image/jpeg", b"\xff\xd8\xffdata"), ".jpg")
        self.assertEqual(validate_meal_image("image/png", b"\x89PNG\r\n\x1a\ndata"), ".png")
        self.assertEqual(validate_meal_image("image/webp", b"RIFF1234WEBPdata"), ".webp")
        key = nutrition_photo_key(42, ".jpg")
        self.assertTrue(key.startswith("nutrition-photos/42/"))
        self.assertTrue(key.endswith(".jpg"))

    def test_rejects_mismatched_empty_unsupported_and_oversized_images(self):
        for content_type, data in (
            ("image/gif", b"GIF89a"),
            ("image/png", b"not png"),
            ("image/jpeg", b""),
            ("image/jpeg", b"\xff\xd8\xff" + b"x" * (MAX_IMAGE_BYTES + 1)),
        ):
            with self.subTest(content_type=content_type, size=len(data)), self.assertRaises(HTTPException):
                validate_meal_image(content_type, data)


class NutritionPhotoConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_image_proxy_streams_private_image_for_owner(self):
        photo = SimpleNamespace(
            id=7,
            user_id=11,
            status="preview",
            image_key="nutrition-photos/11/photo.jpg",
            content_type="image/jpeg",
        )
        db = FakeDb(photo)
        image_stream = FakeAsyncImageBody(b"jpeg-image")
        s3 = SimpleNamespace(get_object=AsyncMock(return_value={"Body": image_stream}))

        response = await read_my_nutrition_photo_image(
            7, db=db, s3=s3, current_user=SimpleNamespace(id=11)
        )

        self.assertIn("kh_nutrition_photo.user_id", str(db.statement.whereclause))
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["content-disposition"], "inline")
        s3.get_object.assert_awaited_once_with(
            Bucket=settings.RUSTFS_BUCKET,
            Key="nutrition-photos/11/photo.jpg",
        )
        streamed_body = b"".join([chunk async for chunk in response.body_iterator])
        self.assertEqual(streamed_body, b"jpeg-image")
        self.assertTrue(image_stream.closed)

    async def test_photo_image_proxy_rejects_non_owner_before_reading_storage(self):
        db = FakeDb(None)
        s3 = SimpleNamespace(get_object=AsyncMock())

        with self.assertRaises(HTTPException) as error:
            await read_my_nutrition_photo_image(
                7, db=db, s3=s3, current_user=SimpleNamespace(id=12)
            )

        self.assertEqual(error.exception.status_code, 404)
        self.assertIn("kh_nutrition_photo.user_id", str(db.statement.whereclause))
        self.assertIn(12, db.statement.compile().params.values())
        s3.get_object.assert_not_awaited()

    async def test_photo_preview_persists_preview_only_and_not_nutrition_records(self):
        db = FakeDb(None)
        s3 = SimpleNamespace(put_object=AsyncMock(), delete_object=AsyncMock())

        photo = await create_photo_preview(
            db, s3, 11, b"\xff\xd8\xffmeal", "image/jpeg", [food_item()]
        )

        self.assertEqual(len(db.added), 1)
        self.assertIsInstance(db.added[0], NutritionPhotoModel)
        self.assertEqual(db.added[0].status, "preview")
        self.assertEqual(db.added[0].user_id, 11)
        self.assertEqual(photo.image_key.split("/")[1], "11")
        s3.put_object.assert_awaited_once()

    async def test_preview_endpoint_returns_editable_estimate_without_creating_records(self):
        uploaded = UploadFile(
            file=BytesIO(b"\xff\xd8\xffmeal"),
            filename="meal.jpg",
            headers=Headers({"content-type": "image/jpeg"}),
        )
        photo = SimpleNamespace(
            id=7,
            status="preview",
            image_key="nutrition-photos/11/meal.jpg",
            recognized_payload=[food_item().model_dump(mode="json")],
            created_at=datetime.datetime(2026, 10, 23, tzinfo=datetime.timezone.utc),
        )
        with (
            patch("api.nutrition.recognize_food_image", new=AsyncMock(return_value=[food_item()])),
            patch("api.nutrition.create_photo_preview", new=AsyncMock(return_value=photo)) as save_preview,
        ):
            result = await create_my_nutrition_photo_preview(
                uploaded, db=object(), s3=object(), current_user=SimpleNamespace(id=11)
            )
        self.assertEqual(result.id, 7)
        self.assertTrue(result.is_estimate)
        self.assertEqual(result.items[0].food_name, "鸡胸肉")
        save_preview.assert_awaited_once()

    async def test_preview_endpoint_rejects_spoofed_image_before_model_or_storage(self):
        uploaded = UploadFile(
            file=BytesIO(b"not an image"),
            filename="meal.png",
            headers=Headers({"content-type": "image/png"}),
        )
        with (
            patch("api.nutrition.recognize_food_image", new=AsyncMock()) as recognize,
            patch("api.nutrition.create_photo_preview", new=AsyncMock()) as save_preview,
        ):
            with self.assertRaises(HTTPException) as error:
                await create_my_nutrition_photo_preview(
                    uploaded, db=object(), s3=object(), current_user=SimpleNamespace(id=11)
                )
        self.assertEqual(error.exception.status_code, 415)
        recognize.assert_not_awaited()
        save_preview.assert_not_awaited()

    async def test_preview_endpoint_rejects_gif_and_oversized_upload_before_model_or_storage(self):
        cases = (
            ("image/gif", b"GIF89a", 415),
            ("image/jpeg", b"\xff\xd8\xff" + b"x" * MAX_IMAGE_BYTES, 413),
        )
        for content_type, image_bytes, expected_status in cases:
            with self.subTest(content_type=content_type, expected_status=expected_status):
                uploaded = UploadFile(
                    file=BytesIO(image_bytes),
                    filename="meal.upload",
                    headers=Headers({"content-type": content_type}),
                )
                with (
                    patch("api.nutrition.recognize_food_image", new=AsyncMock()) as recognize,
                    patch("api.nutrition.create_photo_preview", new=AsyncMock()) as save_preview,
                ):
                    with self.assertRaises(HTTPException) as error:
                        await create_my_nutrition_photo_preview(
                            uploaded, db=object(), s3=object(), current_user=SimpleNamespace(id=11)
                        )
                self.assertEqual(error.exception.status_code, expected_status)
                recognize.assert_not_awaited()
                save_preview.assert_not_awaited()

    async def test_missing_vision_configuration_does_not_save_image_or_preview(self):
        uploaded = UploadFile(
            file=BytesIO(b"\xff\xd8\xffmeal"),
            filename="meal.jpg",
            headers=Headers({"content-type": "image/jpeg"}),
        )
        with (
            patch(
                "api.nutrition.recognize_food_image",
                new=AsyncMock(side_effect=NutritionVisionNotConfigured("尚未配置餐食识别视觉模型。")),
            ),
            patch("api.nutrition.create_photo_preview", new=AsyncMock()) as save_preview,
        ):
            with self.assertRaises(HTTPException) as error:
                await create_my_nutrition_photo_preview(
                    uploaded, db=object(), s3=object(), current_user=SimpleNamespace(id=11)
                )
        self.assertEqual(error.exception.status_code, 503)
        save_preview.assert_not_awaited()

    async def test_confirmation_persists_only_edited_items_and_marks_source_photo(self):
        photo = SimpleNamespace(
            id=7,
            user_id=11,
            status="preview",
            image_key="nutrition-photos/11/photo.jpg",
            recognized_payload=[],
        )
        db = FakeDb(photo)
        item = food_item(food_name="手动修正鸡胸肉")

        confirmed_photo, records = await confirm_photo_preview(
            db,
            preview_id=7,
            user_id=11,
            record_date=datetime.date(2026, 10, 23),
            items=[item],
        )

        self.assertEqual(confirmed_photo.status, "confirmed")
        self.assertEqual(db.commits, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].food_name, "手动修正鸡胸肉")
        self.assertEqual(records[0].source, "photo")
        self.assertEqual(records[0].photo_id, 7)
        self.assertEqual(records[0].user_id, 11)

    async def test_cross_account_and_repeat_confirmation_are_rejected_without_writes(self):
        missing_db = FakeDb(None)
        with self.assertRaises(HTTPException) as missing:
            await confirm_photo_preview(
                missing_db, 7, 12, datetime.date(2026, 10, 23), [food_item()]
            )
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(missing_db.commits, 0)
        self.assertIn("FOR UPDATE", str(missing_db.statement))

        already_confirmed = SimpleNamespace(id=7, user_id=11, status="confirmed")
        repeated_db = FakeDb(already_confirmed)
        with self.assertRaises(HTTPException) as repeated:
            await confirm_photo_preview(
                repeated_db, 7, 11, datetime.date(2026, 10, 23), [food_item()]
            )
        self.assertEqual(repeated.exception.status_code, 409)
        self.assertEqual(repeated_db.added, [])
        self.assertEqual(repeated_db.commits, 0)

    async def test_cancel_marks_only_an_owned_pending_preview_and_removes_object(self):
        photo = SimpleNamespace(id=7, user_id=11, status="preview", image_key="photo.jpg")
        db = FakeDb(photo)
        s3 = SimpleNamespace(delete_object=AsyncMock())

        await cancel_photo_preview(db, s3, 7, 11)

        self.assertEqual(photo.status, "cancelled")
        self.assertEqual(db.commits, 1)
        self.assertIn("FOR UPDATE", str(db.statement))
        s3.delete_object.assert_awaited_once()

    async def test_cancel_rejects_non_owner_and_confirmed_preview_before_storage_cleanup(self):
        missing_db = FakeDb(None)
        missing_s3 = SimpleNamespace(delete_object=AsyncMock())
        with self.assertRaises(HTTPException) as missing:
            await cancel_photo_preview(missing_db, missing_s3, 7, 12)
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(missing_db.commits, 0)
        missing_s3.delete_object.assert_not_awaited()

        confirmed = SimpleNamespace(id=7, user_id=11, status="confirmed", image_key="photo.jpg")
        confirmed_db = FakeDb(confirmed)
        confirmed_s3 = SimpleNamespace(delete_object=AsyncMock())
        with self.assertRaises(HTTPException) as conflict:
            await cancel_photo_preview(confirmed_db, confirmed_s3, 7, 11)
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(confirmed_db.commits, 0)
        confirmed_s3.delete_object.assert_not_awaited()

    async def test_cancelled_preview_can_retry_failed_object_cleanup(self):
        photo = SimpleNamespace(id=7, user_id=11, status="preview", image_key="photo.jpg")
        db = FakeDb(photo)
        failing_s3 = SimpleNamespace(delete_object=AsyncMock(side_effect=RuntimeError("storage unavailable")))

        with self.assertRaises(HTTPException) as error:
            await cancel_photo_preview(db, failing_s3, 7, 11)

        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(photo.status, "cancelled")
        self.assertEqual(db.commits, 1)

        retry_s3 = SimpleNamespace(delete_object=AsyncMock())
        await cancel_photo_preview(db, retry_s3, 7, 11)
        self.assertEqual(db.commits, 1)
        retry_s3.delete_object.assert_awaited_once()

