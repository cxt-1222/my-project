from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import ADMIN_ROLE_CODE, count_users_with_role, get_user_role_codes, require_admin
from models import PermissionModel, RoleModel, RolePermissionModel, UserModel, UserRoleModel
from schemas.permission import AssignPermissionDTO, RolePermissionRespDTO
from schemas.user import AddRoleDTO, BindRoleDTO, RoleRespDTO, RoleWithUsersRespDTO, UpdateRoleDTO

role_router = APIRouter(prefix='/role', tags=['角色'])

PROTECTED_ROLE_CODES = {'ROLE_ADMIN', 'ROLE_SH', 'ROLE_USER'}


# -------------------------- 角色接口 --------------------------
@role_router.get('/get_roles', response_model=list[RoleWithUsersRespDTO])
async def get_roles_api(db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """查询全部角色及其已绑定用户"""
    roles = (await db.execute(select(RoleModel))).scalars().all()
    rels = (await db.execute(select(UserRoleModel))).scalars().all()
    user_ids = {int(rel.user_id) for rel in rels}
    users_by_id = {}
    if user_ids:
        users_by_id = {
            str(user.id): user
            for user in (await db.execute(select(UserModel).where(UserModel.id.in_(user_ids)))).scalars().all()
        }
    grouped: dict[str, list] = {}
    for rel in rels:
        user = users_by_id.get(rel.user_id)
        if user:
            grouped.setdefault(rel.role_id, []).append(user)
    return [
        RoleWithUsersRespDTO(
            id=role.id, role_name=role.role_name, role_code=role.role_code,
            description=role.description,
            create_at=role.create_at, update_at=role.update_at,
            users=grouped.get(str(role.id), []),
        )
        for role in roles
    ]

@role_router.post('/add_role', response_model=RoleRespDTO)
async def add_role_api(dto: AddRoleDTO, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """新增角色"""
    stmt = select(RoleModel).where(RoleModel.role_code == dto.role_code)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="角色编码已存在")
    role = RoleModel(**dto.model_dump())
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


@role_router.put('/update_role', response_model=RoleRespDTO)
async def update_role_api(role_id: int, dto: UpdateRoleDTO, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """修改角色,只更新传入的字段"""
    role = await db.get(RoleModel, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    update_data = {k: v for k, v in dto.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要修改的字段")
    if role.role_code in PROTECTED_ROLE_CODES and update_data.get('role_code') not in (None, role.role_code):
        raise HTTPException(status_code=400, detail="系统内置角色编码不可修改")
    if 'role_code' in update_data and update_data['role_code'] != role.role_code:
        stmt = select(RoleModel).where(RoleModel.role_code == update_data['role_code'])
        if (await db.execute(stmt)).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="角色编码已存在")
    for key, value in update_data.items():
        setattr(role, key, value)
    await db.commit()
    await db.refresh(role)
    return role


@role_router.delete('/del_role')
async def del_role_api(role_id: int, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """删除角色，同时清理其用户关联"""
    role = await db.get(RoleModel, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    if role.role_code in PROTECTED_ROLE_CODES:
        raise HTTPException(status_code=400, detail="系统内置角色不可删除")
    await db.execute(delete(UserRoleModel).where(UserRoleModel.role_id == str(role_id)))
    await db.delete(role)
    await db.commit()
    return {"msg": "删除成功"}


@role_router.post('/bind_role')
async def bind_role_api(dto: BindRoleDTO, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """给用户绑定角色"""
    if not await db.get(UserModel, dto.user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    if not await db.get(RoleModel, dto.role_id):
        raise HTTPException(status_code=404, detail="角色不存在")
    stmt = select(UserRoleModel).where(
        UserRoleModel.user_id == str(dto.user_id), UserRoleModel.role_id == str(dto.role_id)
    )
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该用户已绑定此角色")
    rel = UserRoleModel(user_id=str(dto.user_id), role_id=str(dto.role_id))
    db.add(rel)
    await db.commit()
    return {"msg": "绑定成功"}


@role_router.delete('/unbind_role')
async def unbind_role_api(user_id: int, role_id: int, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """给用户解绑角色"""
    user = await db.get(UserModel, user_id)
    role = await db.get(RoleModel, role_id)
    if not user or not role:
        raise HTTPException(status_code=404, detail="用户或角色不存在")
    if role.role_code == ADMIN_ROLE_CODE and ADMIN_ROLE_CODE in await get_user_role_codes(db, user):
        if await count_users_with_role(db, ADMIN_ROLE_CODE) <= 1:
            raise HTTPException(status_code=400, detail="不能移除系统中最后一个管理员角色")
    stmt = delete(UserRoleModel).where(
        UserRoleModel.user_id == str(user_id), UserRoleModel.role_id == str(role_id)
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="绑定关系不存在")
    return {"msg": "解绑成功"}


# -------------------------- 角色权限接口 --------------------------
@role_router.get('/permissions', response_model=RolePermissionRespDTO)
async def role_permissions_api(role_id: int, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """查询角色已分配的权限"""
    if not await db.get(RoleModel, role_id):
        raise HTTPException(status_code=404, detail="角色不存在")
    rows = (
        await db.execute(select(RolePermissionModel.permission_id).where(RolePermissionModel.role_id == str(role_id)))
    ).scalars().all()
    return {'role_id': role_id, 'permission_ids': [int(x) for x in rows]}


@role_router.post('/assign_permissions')
async def assign_permissions_api(dto: AssignPermissionDTO, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """给角色分配权限(覆盖式:清空后按提交的权限ID重新绑定)"""
    if not await db.get(RoleModel, dto.role_id):
        raise HTTPException(status_code=404, detail="角色不存在")
    if dto.permission_ids:
        perms = (
            await db.execute(select(PermissionModel.id).where(PermissionModel.id.in_(dto.permission_ids)))
        ).scalars().all()
        missing = set(dto.permission_ids) - set(perms)
        if missing:
            raise HTTPException(status_code=400, detail=f"权限ID不存在: {sorted(missing)}")
    await db.execute(delete(RolePermissionModel).where(RolePermissionModel.role_id == str(dto.role_id)))
    for pid in dto.permission_ids:
        db.add(RolePermissionModel(role_id=str(dto.role_id), permission_id=str(pid)))
    await db.commit()
    return {"msg": "分配成功"}
