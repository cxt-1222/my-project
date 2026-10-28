from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, create_pg_tables as db_create_pg_tables
from core.security import get_current_user
from clients.chat_cache import delete_recent_messages
from clients.milvus_client import delete_chat_memories_for_session
from models import AiSessionModel, AiMessageModel, UserModel
from schemas.chat import MessageRespDTO, SessionCreateDTO, SessionRespDTO, SessionUpdateDTO
from services.chat_session_lock import chat_session_locks

chat_router = APIRouter(prefix='/chat', tags=['对话'])


# -------------------------- 建表 --------------------------
@chat_router.get('/create_chat_table')
async def create_pg_tables():
    return await db_create_pg_tables(
        tables=[AiSessionModel.__table__, AiMessageModel.__table__]
    )


# -------------------------- 会话 CRUD --------------------------
async def _get_owned_session(db: AsyncSession, session_id: int, user_id: int) -> AiSessionModel:
    """取会话并校验归属，非本人会话一律 404，避免泄露存在性"""
    session = await db.get(AiSessionModel, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=404, detail='会话不存在')
    return session


@chat_router.post('/session', response_model=SessionRespDTO)
async def create_session_api(dto: SessionCreateDTO, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """新建会话"""
    title = dto.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail='会话标题不能为空')
    session = AiSessionModel(user_id=current_user.id, title=title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@chat_router.get('/session', response_model=list[SessionRespDTO])
async def list_sessions_api(db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """当前用户的会话列表"""
    stmt = select(AiSessionModel).where(AiSessionModel.user_id == current_user.id).order_by(AiSessionModel.id.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@chat_router.get('/session/{session_id}', response_model=SessionRespDTO)
async def get_session_api(session_id: int, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """查询单个会话"""
    return await _get_owned_session(db, session_id, current_user.id)


@chat_router.get('/session/{session_id}/messages', response_model=list[MessageRespDTO])
async def list_session_messages_api(
    session_id: int,
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """查询当前用户会话中的消息，按时间正序返回最近一段上下文。"""
    await _get_owned_session(db, session_id, current_user.id)
    limit = max(1, min(limit, 100))
    result = await db.execute(
        select(AiMessageModel)
        .where(AiMessageModel.session_id == session_id)
        .order_by(AiMessageModel.create_at.desc(), AiMessageModel.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


@chat_router.put('/session/{session_id}', response_model=SessionRespDTO)
async def update_session_api(session_id: int, dto: SessionUpdateDTO, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """修改会话标题"""
    session = await _get_owned_session(db, session_id, current_user.id)
    title = dto.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail='会话标题不能为空')
    session.title = title
    await db.commit()
    await db.refresh(session)
    return session


@chat_router.delete('/session/{session_id}')
async def delete_session_api(session_id: int, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """删除会话，其消息一并删除（显式删除 + 外键 ON DELETE CASCADE 双保险）"""
    lock_token = chat_session_locks.try_acquire(current_user.id, session_id)
    if lock_token is None:
        raise HTTPException(status_code=409, detail='该会话正在回答，完成后才能删除')
    try:
        session = await _get_owned_session(db, session_id, current_user.id)
        await db.execute(delete(AiMessageModel).where(AiMessageModel.session_id == session_id))
        await db.delete(session)
        await db.commit()
        await delete_recent_messages(current_user.id, session_id)
        try:
            await delete_chat_memories_for_session(current_user.id, session_id)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Could not delete long-term memories for deleted session")
        return {"msg": "删除成功"}
    finally:
        chat_session_locks.release(current_user.id, session_id, lock_token)
