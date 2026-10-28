from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import create_pg_tables as db_create_pg_tables
from core.database import get_db
from core.security import get_current_user, require_admin
from models import TeamMemberModel, TeamModel, UserModel
from schemas.team import AddTeamDTO, AddTeamMemberDTO, TeamMemberRespDTO, TeamPageRespDTO, TeamRespDTO, UpdateTeamDTO

team_router = APIRouter(prefix='/team', tags=['部门团队'])


# -------------------------- 建表 --------------------------
@team_router.get('/create_table')
async def create_pg_tables(admin_user: UserModel = Depends(require_admin)):
    return await db_create_pg_tables(
        tables=[TeamModel.__table__, TeamMemberModel.__table__]
    )


# -------------------------- 部门接口 --------------------------
@team_router.get('/query_team', response_model=TeamPageRespDTO)
async def query_team_api(
    team_name: str = Query('', description='部门名称，模糊匹配'),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """按部门名称分页查询"""
    stmt = select(TeamModel)
    if team_name:
        stmt = stmt.where(TeamModel.team_name.ilike(f'%{team_name}%'))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0
    rows = (
        await db.execute(stmt.order_by(TeamModel.id).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    return {
        'total': total,
        'page': page,
        'page_size': page_size,
        'list': [TeamRespDTO.model_validate(r) for r in rows],
    }


@team_router.post('/add_team', response_model=TeamRespDTO)
async def add_team_api(
    dto: AddTeamDTO,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """新增部门"""
    team_name = dto.team_name.strip()
    team_code = dto.team_code.strip()
    if not team_name or not team_code:
        raise HTTPException(status_code=400, detail="部门名称和编码不能为空")
    stmt = select(TeamModel).where(TeamModel.team_code == team_code)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="部门编码已存在")
    team = TeamModel(team_name=team_name, team_code=team_code, description=dto.description)
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return team


@team_router.put('/update_team', response_model=TeamRespDTO)
async def update_team_api(
    team_id: int,
    dto: UpdateTeamDTO,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """修改部门,只更新传入的字段"""
    team = await db.get(TeamModel, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="部门不存在")
    update_data = {k: v for k, v in dto.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要修改的字段")
    if 'team_code' in update_data and update_data['team_code'] != team.team_code:
        stmt = select(TeamModel).where(TeamModel.team_code == update_data['team_code'])
        if (await db.execute(stmt)).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="部门编码已存在")
    for key, value in update_data.items():
        setattr(team, key, value)
    await db.commit()
    await db.refresh(team)
    return team


@team_router.delete('/del_team')
async def del_team_api(team_id: int, db: AsyncSession = Depends(get_db), admin_user: UserModel = Depends(require_admin)):
    """删除部门,同时清理其成员关联"""
    team = await db.get(TeamModel, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="部门不存在")
    await db.execute(delete(TeamMemberModel).where(TeamMemberModel.team_id == str(team_id)))
    await db.delete(team)
    await db.commit()
    return {"msg": "删除成功"}


@team_router.get('/my_teams', response_model=list[TeamRespDTO])
async def my_teams_api(db: AsyncSession = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    """当前用户所属部门列表"""
    team_ids = (
        await db.execute(select(TeamMemberModel.team_id).where(TeamMemberModel.user_id == str(current_user.id)))
    ).scalars().all()
    if not team_ids:
        return []
    teams = (
        await db.execute(select(TeamModel).where(TeamModel.id.in_([int(x) for x in team_ids])))
    ).scalars().all()
    return teams


# -------------------------- 部门成员接口 --------------------------
@team_router.get('/query_members', response_model=list[TeamMemberRespDTO])
async def query_members_api(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """查询部门成员列表"""
    team = await db.get(TeamModel, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="部门不存在")
    stmt = (
        select(
            TeamMemberModel.team_id,
            TeamMemberModel.user_id,
            UserModel.username,
            UserModel.email,
            TeamMemberModel.create_at,
        )
        .join(UserModel, UserModel.id == TeamMemberModel.user_id.cast(Integer))
        .where(TeamMemberModel.team_id == str(team_id))
    )
    rows = (await db.execute(stmt)).all()
    return [
        TeamMemberRespDTO(
            team_id=int(r.team_id),
            user_id=int(r.user_id),
            username=r.username,
            email=r.email,
            create_at=r.create_at,
        )
        for r in rows
    ]


@team_router.post('/add_member')
async def add_member_api(
    dto: AddTeamMemberDTO,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """新增部门成员;一个用户只能属于一个部门,若已在其他部门则自动剔除后移入"""
    team = await db.get(TeamModel, dto.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="部门不存在")
    if not await db.get(UserModel, dto.user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    existing = (
        await db.execute(select(TeamMemberModel).where(TeamMemberModel.user_id == str(dto.user_id)))
    ).scalars().all()
    moved_from = None
    for rel in existing:
        if rel.team_id == str(dto.team_id):
            raise HTTPException(status_code=400, detail="该用户已在部门中")
        old_team = await db.get(TeamModel, int(rel.team_id)) if rel.team_id.isdigit() else None
        if old_team:
            old_team.member_count = max(old_team.member_count - 1, 0)
            moved_from = old_team.team_name
        await db.delete(rel)
    db.add(TeamMemberModel(team_id=str(dto.team_id), user_id=str(dto.user_id)))
    team.member_count += 1
    await db.commit()
    msg = f"已添加，并从部门「{moved_from}」移入" if moved_from else "添加成功"
    return {"msg": msg, "moved_from": moved_from}


@team_router.delete('/del_member')
async def del_member_api(
    team_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin_user: UserModel = Depends(require_admin),
):
    """删除部门成员"""
    team = await db.get(TeamModel, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="部门不存在")
    stmt = delete(TeamMemberModel).where(
        TeamMemberModel.team_id == str(team_id), TeamMemberModel.user_id == str(user_id)
    )
    res = await db.execute(stmt)
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="成员不存在")
    team.member_count = max(team.member_count - 1, 0)
    await db.commit()
    return {"msg": "删除成功"}
