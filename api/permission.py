from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import create_pg_tables as db_create_pg_tables
from core.database import get_db
from core.security import require_admin
from models import PermissionModel, RolePermissionModel, UserModel
from schemas.permission import PermissionNodeDTO

permission_router = APIRouter(prefix='/permission', tags=['权限'])

SEED_PERMISSIONS = [
    # (parent_code, name, code, type)
    (None, '文档管理', 'document', 1),
    ('document', '查看文档', 'document:list', 2),
    ('document', '新建文档', 'document:create', 2),
    ('document', '编辑文档', 'document:edit', 2),
    ('document', '删除文档', 'document:delete', 2),
    (None, '检索', 'search', 1),
    ('search', '全库检索', 'search:all', 2),
    (None, '个人中心', 'profile', 1),
    ('profile', '个人资料查看', 'profile:view', 2),
    ('profile', '个人资料编辑', 'profile:edit', 2),
]


async def _seed_permissions(db: AsyncSession) -> None:
    existing = (await db.execute(select(PermissionModel.permission_code))).scalars().all()
    existing = set(existing)
    id_by_code: dict[str, int] = {}
    for parent_code, name, code, ptype in SEED_PERMISSIONS:
        if code in existing:
            continue
        perm = PermissionModel(
            parent_id=id_by_code.get(parent_code, 0),
            permission_name=name,
            permission_code=code,
            permission_type=ptype,
        )
        db.add(perm)
        await db.flush()
        id_by_code[code] = perm.id
    await db.commit()


@permission_router.get('/create_table')
async def create_pg_tables(admin_user: UserModel = Depends(require_admin)):
    res = await db_create_pg_tables(tables=[PermissionModel.__table__, RolePermissionModel.__table__])
    from core.database import SessionLocal

    async with SessionLocal() as session:
        await _seed_permissions(session)
    return res


@permission_router.get('/tree', response_model=list[PermissionNodeDTO])
async def permission_tree_api(
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """权限树(全量)"""
    perms = (await db.execute(select(PermissionModel).order_by(PermissionModel.id))).scalars().all()
    nodes = {p.id: PermissionNodeDTO.model_validate(p) for p in perms}
    roots: list[PermissionNodeDTO] = []
    for p in perms:
        node = nodes[p.id]
        if p.parent_id and p.parent_id in nodes:
            nodes[p.parent_id].children.append(node)
        else:
            roots.append(node)
    return roots
