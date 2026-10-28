from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import KhDocument, RoleModel, TeamMemberModel, UserModel, UserRoleModel
from utils.auth import decode_token

ADMIN_ROLE_CODE = 'ROLE_ADMIN'
REVIEWER_ROLE_CODE = 'ROLE_SH'


async def get_current_user(authorization: Optional[str] = Header(None), db: AsyncSession = Depends(get_db)) -> UserModel:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少token")
    payload = decode_token(authorization[7:], "access")
    if not payload:
        raise HTTPException(status_code=401, detail="token无效或已过期")
    user = await db.get(UserModel, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


async def is_admin_user(db: AsyncSession, user: UserModel) -> bool:
    """判断用户是否具有 ROLE_ADMIN 角色"""
    return ADMIN_ROLE_CODE in await get_user_role_codes(db, user)


async def get_user_team_ids(db: AsyncSession, user: UserModel) -> set[str]:
    """查询用户所属团队 ID"""
    return set(
        (await db.execute(select(TeamMemberModel.team_id).where(TeamMemberModel.user_id == str(user.id))))
        .scalars()
        .all()
    )


async def get_user_role_codes(db: AsyncSession, user: UserModel) -> set[str]:
    """查询用户的全部角色编码"""
    stmt = (
        select(RoleModel.role_code)
        .join(UserRoleModel, UserRoleModel.role_id == cast(RoleModel.id, String))
        .where(UserRoleModel.user_id == str(user.id))
    )
    return set((await db.execute(stmt)).scalars().all())


async def count_users_with_role(db: AsyncSession, role_code: str) -> int:
    """统计绑定指定角色的用户数量，用于保护关键角色的最后一个持有者。"""
    role_lock = select(RoleModel.id).where(RoleModel.role_code == role_code).with_for_update()
    await db.execute(role_lock)
    stmt = (
        select(func.count(func.distinct(UserRoleModel.user_id)))
        .select_from(UserRoleModel)
        .join(RoleModel, UserRoleModel.role_id == cast(RoleModel.id, String))
        .where(RoleModel.role_code == role_code)
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def can_review_doc(db: AsyncSession, user: UserModel, doc: KhDocument | None) -> bool:
    """审核权限:ROLE_ADMIN 可审全部;ROLE_SH 仅可审与自己同部门的文档"""
    roles = await get_user_role_codes(db, user)
    if ADMIN_ROLE_CODE in roles:
        return True
    if REVIEWER_ROLE_CODE not in roles:
        return False
    if not doc or not doc.team_id:
        return False
    my_team_ids = await get_user_team_ids(db, user)
    return str(doc.team_id) in my_team_ids


async def can_download_doc(db: AsyncSession, user: UserModel, doc: KhDocument | None) -> bool:
    """上传文件下载权限:公开文档 / 作者本人 / 与文档同部门的用户"""
    if not doc:
        return False
    if doc.is_public == 1 or doc.author_id == user.id:
        return True
    if doc.team_id:
        my_team_ids = set(
            (await db.execute(select(TeamMemberModel.team_id).where(TeamMemberModel.user_id == str(user.id)))).scalars().all()
        )
        return str(doc.team_id) in my_team_ids
    return False


async def require_admin(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """系统管理员角色校验:kh_user_role 关联的 kh_role 中必须包含 ROLE_ADMIN"""
    if not await is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="仅系统管理员可执行此操作")
    return current_user


async def require_reviewer_or_admin(
    db: AsyncSession = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """审核队列仅对系统管理员和审核员开放"""
    roles = await get_user_role_codes(db, current_user)
    if not roles.intersection({ADMIN_ROLE_CODE, REVIEWER_ROLE_CODE}):
        raise HTTPException(status_code=403, detail="仅系统管理员或审核员可访问审核工作台")
    return current_user
