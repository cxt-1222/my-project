from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, create_pg_tables as db_create_pg_tables
from core.security import ADMIN_ROLE_CODE, count_users_with_role, get_current_user, get_user_role_codes, is_admin_user, require_admin
from models import KhDocument, UserModel, RoleModel, TeamMemberModel, TeamModel, UserRoleModel
from schemas.user import AssignRolesDTO, CreateUserDTO, LoginDTO, RefreshTokenDTO, RegisterDTO, UpdateUserDTO, UserPageRespDTO, UserRespDTO, UserWithRolesRespDTO
from utils.auth import create_access_token, create_refresh_token, decode_token
from utils.hashing import get_password_hash, verify_password

user_router = APIRouter(prefix='/user', tags=['用户'])


# -------------------------- 建表 --------------------------
@user_router.get('/create_table')
async def create_pg_tables(admin_user: UserModel = Depends(require_admin)):
    return await db_create_pg_tables(
        tables=[UserModel.__table__, RoleModel.__table__, UserRoleModel.__table__]
    )
    

# -------------------------- 用户接口 --------------------------
async def get_user_by_username(db: AsyncSession, username: str):
    stmt = select(UserModel).where(UserModel.username == username)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


@user_router.get('/query_users', response_model=UserPageRespDTO)
async def query_users_api(
    username: str = Query('', description='用户名，模糊匹配'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """按用户名分页查询用户"""
    stmt = select(UserModel)
    if username:
        stmt = stmt.where(UserModel.username.ilike(f'%{username}%'))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(UserModel.id).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    role_codes_map: dict[int, list[str]] = {}
    team_name_map: dict[int, str] = {}
    if rows:
        rels = (
            await db.execute(select(UserRoleModel).where(UserRoleModel.user_id.in_([str(r.id) for r in rows])))
        ).scalars().all()
        if rels:
            role_ids = {int(rel.role_id) for rel in rels}
            code_by_id = {
                role.id: role.role_code
                for role in (await db.execute(select(RoleModel).where(RoleModel.id.in_(role_ids)))).scalars().all()
            }
            for rel in rels:
                code = code_by_id.get(int(rel.role_id))
                if code:
                    role_codes_map.setdefault(int(rel.user_id), []).append(code)
        team_rels = (
            await db.execute(select(TeamMemberModel).where(TeamMemberModel.user_id.in_([str(r.id) for r in rows])))
        ).scalars().all()
        if team_rels:
            team_ids = {int(x.team_id) for x in team_rels if x.team_id.isdigit()}
            name_by_id = {
                t.id: t.team_name
                for t in (await db.execute(select(TeamModel).where(TeamModel.id.in_(team_ids)))).scalars().all()
            }
            for x in team_rels:
                if x.team_id.isdigit():
                    team_name_map[int(x.user_id)] = name_by_id.get(int(x.team_id))
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'list': [
            UserWithRolesRespDTO(
                id=r.id, username=r.username, email=r.email,
                create_at=r.create_at, update_at=r.update_at,
                role_codes=role_codes_map.get(r.id, []),
                team_name=team_name_map.get(r.id),
            )
            for r in rows
        ],
    }


@user_router.get('/stats')
async def user_stats_api(db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """用户统计(文档数为本人上传数,浏览/点赞/评论暂无数据来源,返回0)"""
    doc_count = (
        await db.execute(
            select(func.count()).select_from(KhDocument).where(KhDocument.author_id == current_user.id)
        )
    ).scalar() or 0
    return {
        'document_count': doc_count,
        'view_count': 0,
        'like_count': 0,
        'comment_count': 0,
    }


@user_router.get('/roles')
async def user_roles_api(user_id: int, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """查询用户已绑定的角色编码"""
    if user_id != current_user.id and not await is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="只能查询自己的角色")
    if not await db.get(UserModel, user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    rows = (
        await db.execute(select(UserRoleModel.role_id).where(UserRoleModel.user_id == str(user_id)))
    ).scalars().all()
    role_ids = {int(x) for x in rows}
    codes = []
    if role_ids:
        codes = (
            await db.execute(select(RoleModel.role_code).where(RoleModel.id.in_(role_ids)))
        ).scalars().all()
    return {'user_id': user_id, 'role_codes': list(codes)}


@user_router.post('/assign_roles')
async def assign_roles_api(
    dto: AssignRolesDTO,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """给用户分配角色(覆盖式:清空该用户现有角色后按提交的角色编码重新绑定)"""
    target = await db.get(UserModel, dto.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    current_codes = await get_user_role_codes(db, target)
    requested_codes = set(dto.role_codes)
    if ADMIN_ROLE_CODE in current_codes and ADMIN_ROLE_CODE not in requested_codes:
        if await count_users_with_role(db, ADMIN_ROLE_CODE) <= 1:
            raise HTTPException(status_code=400, detail="不能移除系统中最后一个管理员角色")
    roles = []
    if dto.role_codes:
        roles = (
            await db.execute(select(RoleModel).where(RoleModel.role_code.in_(dto.role_codes)))
        ).scalars().all()
        missing = set(dto.role_codes) - {role.role_code for role in roles}
        if missing:
            raise HTTPException(status_code=400, detail=f"角色编码不存在: {', '.join(sorted(missing))}")
    await db.execute(delete(UserRoleModel).where(UserRoleModel.user_id == str(dto.user_id)))
    for role in roles:
        db.add(UserRoleModel(user_id=str(dto.user_id), role_id=str(role.id)))
    await db.commit()
    return {"msg": "分配成功"}


@user_router.post('/register', response_model=UserRespDTO)
async def register_api(dto: RegisterDTO, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    username = dto.username.strip()
    email = dto.email.strip()
    if not username or not email:
        raise HTTPException(status_code=400, detail="用户名和邮箱不能为空")
    if len(dto.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")
    if await get_user_by_username(db, username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    stmt = select(UserModel).where(UserModel.email == email)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")
    user = UserModel(username=username, password=get_password_hash(dto.password), email=email)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@user_router.post('/create_user', response_model=UserRespDTO)
async def create_user_api(
    dto: CreateUserDTO,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """管理员创建用户并分配角色"""
    username = dto.username.strip()
    email = dto.email.strip()
    if not username or not email:
        raise HTTPException(status_code=400, detail="用户名和邮箱不能为空")
    if len(dto.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")
    if await get_user_by_username(db, username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    stmt = select(UserModel).where(UserModel.email == email)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已存在")
    roles = []
    if dto.role_codes:
        roles = (
            await db.execute(select(RoleModel).where(RoleModel.role_code.in_(dto.role_codes)))
        ).scalars().all()
        missing = set(dto.role_codes) - {role.role_code for role in roles}
        if missing:
            raise HTTPException(status_code=400, detail=f"角色编码不存在: {', '.join(sorted(missing))}")
    user = UserModel(username=username, password=get_password_hash(dto.password), email=email)
    db.add(user)
    await db.flush()
    for role in roles:
        db.add(UserRoleModel(user_id=str(user.id), role_id=str(role.id)))
    await db.commit()
    await db.refresh(user)
    return user


@user_router.post('/login')
async def login_api(dto: LoginDTO, db: AsyncSession = Depends(get_db)):
    """用户登录，返回 JWT token"""
    user = await get_user_by_username(db, dto.username)
    if not user or not verify_password(dto.password, user.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(user.id, user.username)
    return {
        "token": token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": UserRespDTO.model_validate(user),
    }


@user_router.post('/refresh')
async def refresh_token_api(dto: RefreshTokenDTO, db: AsyncSession = Depends(get_db)):
    """用 refresh token 换取新的 access token"""
    payload = decode_token(dto.refresh_token, "refresh")
    if not payload:
        raise HTTPException(status_code=401, detail="refresh token无效或已过期")
    user = await db.get(UserModel, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    token = create_access_token(user.id, user.username)
    return {"token": token, "token_type": "bearer"}


@user_router.delete('/del_user')
async def del_user_api(user_id: int, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """删除用户，同时清理其角色关联"""
    user = await db.get(UserModel, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user_id == admin_user.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")
    if ADMIN_ROLE_CODE in await get_user_role_codes(db, user) and await count_users_with_role(db, ADMIN_ROLE_CODE) <= 1:
        raise HTTPException(status_code=400, detail="不能删除系统中最后一个管理员账号")
    await db.execute(delete(UserRoleModel).where(UserRoleModel.user_id == str(user_id)))
    await db.delete(user)
    await db.commit()
    return {"msg": "删除成功"}


@user_router.put('/update_user', response_model=UserRespDTO)
async def update_user_api(user_id: int, dto: UpdateUserDTO, db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """修改用户，只更新传入的字段"""
    is_admin = await is_admin_user(db, current_user)
    if user_id != current_user.id and not is_admin:
        raise HTTPException(status_code=403, detail="仅系统管理员可修改其他用户")
    submitted_fields = set(dto.model_fields_set)
    if not is_admin and submitted_fields - {"email"}:
        raise HTTPException(status_code=403, detail="本人仅可修改邮箱")
    user = await db.get(UserModel, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    update_data = {k: v for k, v in dto.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要修改的字段")
    if "username" in update_data and update_data["username"] != user.username:
        if await get_user_by_username(db, update_data["username"]):
            raise HTTPException(status_code=400, detail="用户名已存在")
    if "email" in update_data and update_data["email"] != user.email:
        stmt = select(UserModel).where(UserModel.email == update_data["email"])
        if (await db.execute(stmt)).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已存在")
    if "password" in update_data:
        if len(update_data["password"]) < 6:
            raise HTTPException(status_code=400, detail="密码长度至少6位")
        update_data["password"] = get_password_hash(update_data["password"])
    for key, value in update_data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user
