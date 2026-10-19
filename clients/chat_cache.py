import json
import logging

from redis.asyncio import Redis

from core.config import settings

logger = logging.getLogger(__name__)
_redis: Redis | None = None


def _cache_key(user_id: int, session_id: int) -> str:
    return f"chat:{user_id}:{session_id}:recent"


def _message_dict(message) -> dict:
    if isinstance(message, dict):
        get_value = message.get
    else:
        get_value = lambda key, default=None: getattr(message, key, default)
    created_at = get_value("create_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    return {
        "role": get_value("role"),
        "content": get_value("content", ""),
        "sources": get_value("sources", []) or [],
        "create_at": created_at,
    }


async def init_chat_cache() -> None:
    global _redis
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        logger.warning("Redis chat cache unavailable; using PostgreSQL only: %s", exc)
        await client.aclose()
        _redis = None
        return
    _redis = client
    logger.info("Redis chat context cache connected")


async def close_chat_cache() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_recent_messages(user_id: int, session_id: int) -> list[dict] | None:
    if _redis is None:
        return None
    try:
        values = await _redis.lrange(_cache_key(user_id, session_id), 0, -1)
        if not values:
            return None
        return [json.loads(value) for value in values]
    except Exception as exc:
        logger.warning("Could not read chat context from Redis: %s", exc)
        return None


async def replace_recent_messages(user_id: int, session_id: int, messages: list) -> None:
    if _redis is None:
        return
    key = _cache_key(user_id, session_id)
    try:
        pipeline = _redis.pipeline(transaction=True)
        pipeline.delete(key)
        if messages:
            pipeline.rpush(key, *[
                json.dumps(_message_dict(message), ensure_ascii=False)
                for message in messages[-settings.CHAT_CONTEXT_MESSAGE_LIMIT:]
            ])
            pipeline.expire(key, settings.CHAT_CONTEXT_CACHE_TTL_SECONDS)
        await pipeline.execute()
    except Exception as exc:
        logger.warning("Could not populate chat context in Redis: %s", exc)


async def append_recent_message(
    user_id: int,
    session_id: int,
    role: str,
    content: str,
    sources=None,
    limit: int | None = None,
) -> None:
    if _redis is None:
        return
    key = _cache_key(user_id, session_id)
    message = {"role": role, "content": content, "sources": sources or [], "create_at": None}
    try:
        pipeline = _redis.pipeline(transaction=True)
        pipeline.rpush(key, json.dumps(message, ensure_ascii=False))
        pipeline.ltrim(key, -(limit or settings.CHAT_CONTEXT_MESSAGE_LIMIT), -1)
        pipeline.expire(key, settings.CHAT_CONTEXT_CACHE_TTL_SECONDS)
        await pipeline.execute()
    except Exception as exc:
        logger.warning("Could not append chat context to Redis: %s", exc)


async def delete_recent_messages(user_id: int, session_id: int) -> None:
    if _redis is None:
        return
    try:
        await _redis.delete(_cache_key(user_id, session_id))
    except Exception as exc:
        logger.warning("Could not delete chat context from Redis: %s", exc)
