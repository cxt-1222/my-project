import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_admin
from models import UserModel
from schemas.knowledge_maintenance import (
    KnowledgeCleanupPreviewResponse,
    KnowledgeCleanupRequest,
    KnowledgeCleanupResult,
)
from services.knowledge_cleanup_executor import (
    CleanupConflict,
    CleanupExecutionFailure,
    execute_knowledge_cleanup,
)
from services.knowledge_cleanup_service import create_knowledge_cleanup_preview

logger = logging.getLogger(__name__)

knowledge_maintenance_router = APIRouter(
    prefix="/admin/knowledge-maintenance",
    tags=["知识库维护"],
)


@knowledge_maintenance_router.get(
    "/cleanup-preview",
    response_model=KnowledgeCleanupPreviewResponse,
    summary="预览旧知识库清理范围",
    description="只读检查各存储中的文档副本和数量，不读取知识正文，也不会执行删除。",
    responses={
        401: {"description": "缺少、无效或过期的 Bearer token"},
        403: {"description": "当前用户不是系统管理员"},
        503: {"description": "未能完整读取所有存储；没有执行删除"},
    },
)
async def cleanup_preview_api(
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """列出知识文档在各存储中的计数；此接口不会读取正文或执行删除。"""
    try:
        return await create_knowledge_cleanup_preview(db)
    except Exception as exc:
        logger.exception("Knowledge cleanup preview failed for admin user %s", admin_user.id)
        raise HTTPException(
            status_code=503,
            detail="清理预览未能完整读取所有存储；没有执行删除，请检查服务后重试。",
        ) from exc


@knowledge_maintenance_router.post(
    "/cleanup",
    response_model=KnowledgeCleanupResult,
    summary="执行已确认的旧知识库清理",
    description=(
        "仅清理 preview_sha256 对应预览中判定的目标。执行前必须重新通过清理预览，"
        "并填写确认短语“确认清理预览中的全部旧知识文档”。"
    ),
    responses={
        401: {"description": "缺少、无效或过期的 Bearer token"},
        403: {"description": "当前用户不是系统管理员"},
        409: {"description": "确认短语错误、预览已变化或存在安全阻断项；未开始清理"},
        503: {"description": "清理未完整完成；请检查执行记录"},
    },
)
async def cleanup_api(
    request: KnowledgeCleanupRequest,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """按当前预览摘要和二次确认，逐文档清理旧知识存储副本。"""
    try:
        return await execute_knowledge_cleanup(
            db,
            preview_sha256=request.preview_sha256,
            confirmation_phrase=request.confirmation_phrase,
            requested_by=int(admin_user.id),
        )
    except CleanupConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CleanupExecutionFailure as exc:
        logger.exception("Knowledge cleanup execution %s failed at %s", exc.execution_id, exc.stage)
        raise HTTPException(
            status_code=503,
            detail={
                "message": "清理未完整完成；请查看执行记录，并重新预览后重试。",
                "execution_id": exc.execution_id,
                "failed_stage": exc.stage,
            },
        ) from exc
    except Exception as exc:
        logger.exception("Knowledge cleanup could not start for admin user %s", admin_user.id)
        raise HTTPException(
            status_code=503,
            detail="清理未能开始；请检查服务状态。",
        ) from exc
