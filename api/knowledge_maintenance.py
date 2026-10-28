import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_admin
from models import UserModel
from services.knowledge_cleanup_service import create_knowledge_cleanup_preview

logger = logging.getLogger(__name__)

knowledge_maintenance_router = APIRouter(
    prefix="/admin/knowledge-maintenance",
    tags=["知识库维护"],
)


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
