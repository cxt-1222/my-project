import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_admin
from models import UserModel
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


class KnowledgeCleanupRequest(BaseModel):
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_phrase: str


@knowledge_maintenance_router.get("/cleanup-preview")
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


@knowledge_maintenance_router.post("/cleanup")
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
