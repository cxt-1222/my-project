import json
import logging
import re
import base64
from typing import Any

import httpx
from pydantic import ValidationError

from core.config import settings
from schemas.nutrition_photo import NutritionPhotoFoodInput

logger = logging.getLogger(__name__)


class NutritionVisionError(Exception):
    """Base error for an unavailable or unusable vision response."""


class NutritionVisionNotConfigured(NutritionVisionError):
    pass


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return str(content or "").strip()


def _json_text(text: str) -> str:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{") or text.startswith("["):
        return text
    object_start = text.find("{")
    object_end = text.rfind("}")
    if object_start >= 0 and object_end > object_start:
        return text[object_start : object_end + 1]
    array_start = text.find("[")
    array_end = text.rfind("]")
    if array_start >= 0 and array_end > array_start:
        return text[array_start : array_end + 1]
    raise NutritionVisionError("视觉模型未返回可解析的 JSON。")


def _provider_error_metadata(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    error = payload.get("error")
    details = error if isinstance(error, dict) else payload
    code = details.get("code") or details.get("type") or payload.get("code")
    request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("request-id")
        or payload.get("request_id")
    )

    def safe_value(value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"[\r\n\t]+", " ", str(value))
        text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", text)
        text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
        return text[:120]

    return safe_value(code), safe_value(request_id)


def parse_vision_items(text: str) -> list[NutritionPhotoFoodInput]:
    try:
        raw = json.loads(_json_text(text))
    except (json.JSONDecodeError, NutritionVisionError) as exc:
        if isinstance(exc, NutritionVisionError):
            raise
        raise NutritionVisionError("视觉模型返回的 JSON 格式无效。") from exc

    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise NutritionVisionError("图片中未识别到可记录的食物。")

    try:
        parsed = [NutritionPhotoFoodInput.model_validate(item) for item in items]
    except ValidationError as exc:
        raise NutritionVisionError("视觉模型返回的营养字段不完整或不合法。") from exc
    if len(parsed) > 20:
        raise NutritionVisionError("单张图片最多识别 20 项食物。")
    return parsed


async def recognize_food_image(image_bytes: bytes, content_type: str) -> list[NutritionPhotoFoodInput]:
    if not settings.QWEN_API_KEY or not settings.QWEN_VISION_MODEL_NAME:
        raise NutritionVisionNotConfigured("尚未配置餐食识别视觉模型。")

    data_url = f"data:{content_type};base64," + base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "请识别这张餐食图片中的可记录食物，并只返回 JSON，不要 Markdown 或解释。"
        "格式必须是 {\"items\":[{\"meal_type\":\"breakfast|lunch|dinner|snack\","
        "\"food_name\":\"食物名称\",\"amount\":数字,\"unit\":\"g/ml/份等\","
        "\"calories_kcal\":数字,\"protein_g\":数字,\"carbohydrate_g\":数字,\"fat_g\":数字}]}。"
        "营养值和份量是估算值；看不清或无法估算时不要编造，返回空 items。"
    )
    payload = {
        "model": settings.QWEN_VISION_MODEL_NAME,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "你是餐食图片识别器，只输出符合要求的 JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    url = settings.QWEN_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.QWEN_API_KEY}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        provider_code, request_id = _provider_error_metadata(exc.response)
        logger.warning(
            "Vision provider returned HTTP %s (model=%s, code=%s, request_id=%s)",
            exc.response.status_code,
            settings.QWEN_VISION_MODEL_NAME,
            provider_code or "unavailable",
            request_id or "unavailable",
        )
        raise NutritionVisionError("餐食识别服务暂时不可用。") from exc
    except httpx.TimeoutException as exc:
        logger.warning(
            "Vision provider request timed out (model=%s)",
            settings.QWEN_VISION_MODEL_NAME,
        )
        raise NutritionVisionError("餐食识别服务暂时不可用。") from exc
    except httpx.RequestError as exc:
        logger.warning(
            "Vision provider request failed (model=%s, error_type=%s)",
            settings.QWEN_VISION_MODEL_NAME,
            type(exc).__name__,
        )
        raise NutritionVisionError("餐食识别服务暂时不可用。") from exc
    except ValueError as exc:
        logger.warning(
            "Vision provider returned invalid JSON (model=%s)",
            settings.QWEN_VISION_MODEL_NAME,
        )
        raise NutritionVisionError("餐食识别服务返回了无效响应。") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "Vision provider response is missing a chat completion (model=%s)",
            settings.QWEN_VISION_MODEL_NAME,
        )
        raise NutritionVisionError("餐食识别服务缺少识别结果。") from exc
    try:
        return parse_vision_items(_content_text(content))
    except NutritionVisionError as exc:
        logger.warning(
            "Vision provider response was rejected (model=%s, reason=%s)",
            settings.QWEN_VISION_MODEL_NAME,
            str(exc),
        )
        raise
