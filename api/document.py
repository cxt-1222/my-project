from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from clients.es_client import delete_data as es_delete_data
from core.database import get_db, create_pg_tables, drop_pg_tables
from core.security import can_review_doc, get_current_user, is_admin_user, require_admin
from models import KhDocument, ReviewTaskModel, TeamMemberModel, UserModel
from schemas.content import DocContent
from schemas.document import KhDocumentRespDTO, KhDocumentRespDTOUpdate
from services.content_service import add_mongo_doc, delete_mongo_doc, update_mongo_doc
from services.document_service import compute_parse_status, create_kh_doc, delete_kh_doc, get_doc, update_kh_doc

pg_router = APIRouter(prefix='/pg',tags=['PG数据库'])


def _can_view(doc: KhDocument, user: UserModel) -> bool:
    """公开文档所有人可见;非公开仅作者可见"""
    return doc.is_public == 1 or doc.author_id == user.id


# 生成表
@pg_router.post('/create_table',description='权限操作，切勿使用')
async def create_table_api(admin_user: UserModel = Depends(require_admin)):
    return await create_pg_tables(tables=[KhDocument.__table__])


# 删除表
@pg_router.post('/drop_table',description='权限操作，切勿使用')
async def drop_table_api(admin_user: UserModel = Depends(require_admin)):
    return await drop_pg_tables(tables=[KhDocument.__table__])


# 查询 doc(公开或作者本人可见)
@pg_router.get('/check',response_model=KhDocumentRespDTO)
async def get_doc_api(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    doc = await get_doc(db,id)
    if not doc:
        return None
    if not _can_view(doc, current_user):
        # 放行:文档有待审任务且当前用户有审核权限(从审核工作台进入详情)
        has_pending = (
            await db.execute(
                select(ReviewTaskModel.id).where(
                    ReviewTaskModel.doc_id == doc.id, ReviewTaskModel.review_result.is_(None)
                )
            )
        ).scalar_one_or_none()
        if not has_pending or not await can_review_doc(db, current_user, doc):
            raise HTTPException(status_code=403, detail="无权查看该文档")
    item = KhDocumentRespDTO.model_validate(doc)
    if doc.author_id is not None:
        item.uploader = (
            await db.execute(select(UserModel.username).where(UserModel.id == doc.author_id))
        ).scalar_one_or_none()
    item.parse_status = compute_parse_status(doc.idx_status, doc.rag_status, doc.kg_status)
    return item


@pg_router.get('/check_all',response_model=list[KhDocumentRespDTO])
async def get_all_docs(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    stmt = select(KhDocument).where(
        or_(KhDocument.is_public == 1, KhDocument.author_id == current_user.id)
    )
    result = await db.execute(stmt)
    docs = result.scalars().all()
    # 关联 kh_user 取上传人用户名
    author_ids = {d.author_id for d in docs if d.author_id is not None}
    name_map: dict[int, str] = {}
    if author_ids:
        rows = await db.execute(
            select(UserModel.id, UserModel.username).where(UserModel.id.in_(author_ids))
        )
        name_map = dict(rows.all())
    resp_list = []
    for d in docs:
        item = KhDocumentRespDTO.model_validate(d)
        item.uploader = name_map.get(d.author_id)
        item.parse_status = compute_parse_status(d.idx_status, d.rag_status, d.kg_status)
        resp_list.append(item)
    return resp_list


# 新增doc
@pg_router.post('/add_doc',response_model=KhDocumentRespDTO)
async def add_doc_api(
    cfg: KhDocumentRespDTO,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    cfg.author_id = current_user.id
    cfg.id = None
    cfg.content_id = None
    cfg.status = 0
    cfg.publish_time = None
    cfg.is_public = 0
    if not await is_admin_user(db, current_user):
        team_id = (
            await db.execute(
                select(TeamMemberModel.team_id).where(TeamMemberModel.user_id == str(current_user.id))
            )
        ).scalars().first()
        cfg.team_id = int(team_id) if team_id and team_id.isdigit() else None
    doc = await create_kh_doc(db,cfg)
    # 同步 MongoDB（原 create_kh_doc 内联逻辑，编排上移 api 层）
    if cfg.content:
        mongo_cfg = DocContent(
            _id=doc.content_id,
            document_id=doc.id,
            content=cfg.content,
            content_summary=doc.summary
        )
        await add_mongo_doc(mongo_cfg)
    return doc


# 删除doc(作者本人或系统管理员)
@pg_router.delete('/del_doc')
async def delete_kh_doc_api(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    doc = await get_doc(db, doc_id)
    if not doc:
        return False
    if doc.author_id != current_user.id and not await is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="仅作者或系统管理员可删除该文档")
    # 级联删除关联的审核任务,避免审核工作台残留 title 为 null 的任务
    await db.execute(delete(ReviewTaskModel).where(ReviewTaskModel.doc_id == doc_id))
    res = await delete_kh_doc(db,doc_id)
    # 同步删除 MongoDB（原 delete_kh_doc 内联逻辑，编排上移 api 层）
    if res:
        await delete_mongo_doc(doc_id)
        # 同步清理 ES 索引(已发布文档),失败不阻断删除
        try:
            await es_delete_data(doc_id)
        except Exception:
            pass
    return res


# 修改doc(仅作者或系统管理员)
@pg_router.put('/update_doc',response_model=KhDocumentRespDTO)
async def update_kh_doc_api(
    dto: KhDocumentRespDTOUpdate,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    doc = await get_doc(db,doc_id)
    if not doc:
        return None
    if doc.author_id != current_user.id and not await is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="无权编辑该文档")
    if doc.author_id == current_user.id and not await is_admin_user(db, current_user):
        protected_fields = dto.model_fields_set.intersection(
            {"id", "content_id", "status", "publish_time", "create_at", "author_id", "team_id", "is_public"}
        )
        if protected_fields:
            raise HTTPException(status_code=403, detail="作者只能编辑文档内容，发布状态和归属由系统管理")
    # 同步 MongoDB（原 update_kh_doc 内联逻辑，先于 PG 字段更新，编排上移 api 层）
    if doc.content_id is not None and dto.content:
        mongo_cfg = DocContent(
            _id=doc.content_id,
            document_id=doc.id,
            content=dto.content,
            content_summary=doc.summary,
        )
        await update_mongo_doc(doc_id=doc.content_id,cfg=mongo_cfg)
    return await update_kh_doc(db,dto,doc_id)
