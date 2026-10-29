import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RegisterDTO(BaseModel):
    username: str
    password: str
    email: str


class LoginDTO(BaseModel):
    username: str = Field(description="登录用户名")
    password: str = Field(description="登录密码")


class RefreshTokenDTO(BaseModel):
    refresh_token: str = Field(description="登录响应中的 refresh_token")


class UpdateUserDTO(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    email: Optional[str] = None


class AddRoleDTO(BaseModel):
    role_name: str
    role_code: str
    description: str


class BindRoleDTO(BaseModel):
    user_id: int
    role_id: int


class UserRespDTO(BaseModel):
    id: int
    username: str
    email: str
    create_at: datetime.datetime
    update_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


class LoginRespDTO(BaseModel):
    token: str = Field(description="用于访问受保护接口的 JWT access token")
    refresh_token: str = Field(description="用于刷新 access token 的 refresh token")
    token_type: Literal["bearer"] = Field(description="Authorization 认证方案")
    user: UserRespDTO = Field(description="当前登录用户")


class RefreshTokenRespDTO(BaseModel):
    token: str = Field(description="新的 JWT access token")
    token_type: Literal["bearer"] = Field(description="Authorization 认证方案")


class UserWithRolesRespDTO(UserRespDTO):
    role_codes: list[str] = []
    team_name: Optional[str] = None


class UserPageRespDTO(BaseModel):
    total: int
    page: int
    page_size: int
    list: list[UserWithRolesRespDTO]


class AssignRolesDTO(BaseModel):
    user_id: int
    role_codes: list[str]


class CreateUserDTO(BaseModel):
    username: str
    password: str
    email: str
    role_codes: list[str] = []


class UpdateRoleDTO(BaseModel):
    role_name: Optional[str] = None
    role_code: Optional[str] = None
    description: Optional[str] = None


class RoleRespDTO(BaseModel):
    id: int
    role_name: str
    role_code: str
    description: str
    create_at: datetime.datetime
    update_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


class RoleWithUsersRespDTO(RoleRespDTO):
    users: list[UserRespDTO] = []
