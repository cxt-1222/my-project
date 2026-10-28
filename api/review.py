import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.publish import mq_publish_es
from core.database import create_pg_tables as db_create_pg_tables
from core.database import get_db
from core.security import (
    ADMIN_ROLE_CODE,
    REVIEWER_ROLE_CODE,
    can_review_doc,
    get_current_user,
    get_user_role_codes,
    get_user_team_ids,
    is_admin_user,
    require_admin,
    require_reviewer_or_admin,
)
from models import KhDocument, ReviewTaskModel, UserModel
from schemas.document import KhDocumentRespDTOUpdate
from schemas.review import ReviewActionDTO, ReviewPageRespDTO, ReviewTaskRespDTO, SubmitReviewDTO
from services.content_service import get_mongo_doc
from services.document_service import update_kh_doc

review_router = APIRouter(prefix='/review', tags=['审核'])


@review_router.get('/create_table')
async def create_pg_tables(admin_user: UserModel = Depends(require_admin)):
    return await db_create_pg_tables(tables=[ReviewTaskModel.__table__])


@review_router.post('/submit', response_model=ReviewTaskRespDTO)
async def submit_review_api(
    dto: SubmitReviewDTO,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """提交审核:创建审核任务,文档状态置为 3 审核中"""
    doc = await db.get(KhDocument, dto.doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.author_id != current_user.id and not await is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="只能提交自己的文档审核")
    if doc.status in (1, 3):
        raise HTTPException(status_code=400, detail="该文档已发布或正在审核中")
    stmt = select(ReviewTaskModel).where(
        ReviewTaskModel.doc_id == dto.doc_id, ReviewTaskModel.review_result.is_(None)
    )
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该文档已有待审核任务")
    task = ReviewTaskModel(doc_id=dto.doc_id, submitter_id=current_user.id, before_status=doc.status or 0)
    db.add(task)
    doc.status = 3
    await db.commit()
    await db.refresh(task)
    return ReviewTaskRespDTO.model_validate(task).model_copy(update={'title': doc.title})


@review_router.get('/tasks', response_model=ReviewPageRespDTO)
async def review_tasks_api(
    status: str = Query('pending', description='pending/approved/rejected'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(require_reviewer_or_admin),
):
    """审核任务分页列表(每行带 can_review 标识当前用户是否有审核权限)"""
    stmt = (
        select(ReviewTaskModel, KhDocument.title, KhDocument.team_id, KhDocument.author_id)
        .outerjoin(KhDocument, KhDocument.id == ReviewTaskModel.doc_id)
    )
    user_roles = await get_user_role_codes(db, current_user)
    is_admin = ADMIN_ROLE_CODE in user_roles
    is_reviewer = REVIEWER_ROLE_CODE in user_roles
    my_team_ids: set[str] = set()
    if not is_admin:
        my_team_ids = await get_user_team_ids(db, current_user)
        valid_team_ids = [team_id for team_id in my_team_ids if team_id.isdigit()]
        if valid_team_ids:
            stmt = stmt.where(cast(KhDocument.team_id, String).in_(valid_team_ids))
        else:
            stmt = stmt.where(False)
    if status == 'pending':
        stmt = stmt.where(ReviewTaskModel.review_result.is_(None))
    elif status == 'approved':
        stmt = stmt.where(ReviewTaskModel.review_result == 1)
    elif status == 'rejected':
        stmt = stmt.where(ReviewTaskModel.review_result == 2)
    else:
        raise HTTPException(status_code=400, detail="status 仅支持 pending/approved/rejected")
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(ReviewTaskModel.id.desc()).offset((page - 1) * page_size).limit(page_size))
    ).all()
    items = []
    for task, doc_title, doc_team_id, doc_author_id in rows:
        if is_admin:
            can_review = True
        elif is_reviewer and doc_team_id and str(doc_team_id) in my_team_ids:
            can_review = True
        else:
            can_review = False
        items.append(
            ReviewTaskRespDTO.model_validate(task).model_copy(
                update={'title': doc_title, 'can_review': can_review}
            )
        )
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'list': items,
    }


@review_router.post('/action', response_model=ReviewTaskRespDTO)
async def review_action_api(
    dto: ReviewActionDTO,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    """审核操作:通过(1,文档发布)或驳回(2,文档恢复提交前状态),驳回必须填写意见;仅 ROLE_ADMIN 或同部门 ROLE_SH 可审"""
    task = await db.get(ReviewTaskModel, dto.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="审核任务不存在")
    if task.review_result is not None:
        raise HTTPException(status_code=400, detail="该任务已审核")
    if dto.result not in (1, 2):
        raise HTTPException(status_code=400, detail="result 仅支持 1通过/2驳回")
    if dto.result == 2 and not (dto.comment or '').strip():
        raise HTTPException(status_code=400, detail="驳回必须填写意见")
    doc = await db.get(KhDocument, task.doc_id)
    if not await can_review_doc(db, current_user, doc):
        raise HTTPException(status_code=403, detail="仅系统管理员或同部门审核员可执行审核")
    task.review_result = dto.result
    task.review_comment = (dto.comment or '').strip() or None
    task.reviewer_id = current_user.id
    task.reviewer_name = current_user.username
    task.reviewed_at = datetime.datetime.utcnow()
    if dto.result == 1:
        upd = KhDocumentRespDTOUpdate(status=1, publish_time=datetime.datetime.utcnow())
        pg_data = await update_kh_doc(db, upd, task.doc_id)
        if pg_data is None:
            raise HTTPException(status_code=404, detail="文档不存在")
    else:
        upd = KhDocumentRespDTOUpdate(status=task.before_status)
        await update_kh_doc(db, upd, task.doc_id)
    await db.commit()
    await db.refresh(task)
    if dto.result == 1:
        try:
            mondb_data = await get_mongo_doc(task.doc_id)
            content = mondb_data.content if mondb_data else ''
            meta = {c.name: getattr(pg_data, c.name) for c in pg_data.__table__.columns}
            meta = {k: (v.isoformat() if isinstance(v, datetime.datetime) else v) for k, v in meta.items()}
            # ES 索引 is_public 为 boolean 类型,PG 为 0/1 整型,转换避免写入报错
            if 'is_public' in meta and meta['is_public'] is not None:
                meta['is_public'] = bool(meta['is_public'])
            await mq_publish_es(task.doc_id, meta, content)
        except Exception:
            # MQ 入队失败不阻断审核结果,ES/RAG/KG 可后续补发
            pass
    doc = await db.get(KhDocument, task.doc_id)
    return ReviewTaskRespDTO.model_validate(task).model_copy(update={'title': doc.title if doc else None})


@review_router.get('/task_of_doc')
async def task_of_doc_api(doc_id: int, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """查询文档的审核任务及当前用户审核权限(供详情页展示审核操作)"""
    doc = await db.get(KhDocument, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.author_id != current_user.id and not await can_review_doc(db, current_user, doc):
        raise HTTPException(status_code=403, detail="无权查看该文档的审核信息")
    stmt = (
        select(ReviewTaskModel)
        .where(ReviewTaskModel.doc_id == doc_id)
        .order_by(ReviewTaskModel.id.desc())
    )
    task = (await db.execute(stmt)).scalars().first()
    if not task:
        return {'task': None}
    can_review = task.review_result is None and await can_review_doc(db, current_user, doc)
    return {
        'task': ReviewTaskRespDTO.model_validate(task).model_copy(
            update={'title': doc.title if doc else None, 'can_review': can_review}
        )
    }


@review_router.get('/pending_count')
async def pending_count_api(db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(require_reviewer_or_admin)):
    """待审核任务数"""
    stmt = (
        select(func.count())
        .select_from(ReviewTaskModel)
        .join(KhDocument, KhDocument.id == ReviewTaskModel.doc_id)
        .where(ReviewTaskModel.review_result.is_(None))
    )
    if not await is_admin_user(db, current_user):
        team_ids = [team_id for team_id in await get_user_team_ids(db, current_user) if team_id.isdigit()]
        if team_ids:
            stmt = stmt.where(cast(KhDocument.team_id, String).in_(team_ids))
        else:
            stmt = stmt.where(False)
    return {'count': (await db.execute(stmt)).scalar() or 0}
