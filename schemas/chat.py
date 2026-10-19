import datetime

from pydantic import BaseModel, ConfigDict


class SessionCreateDTO(BaseModel):
    title: str


class SessionUpdateDTO(BaseModel):
    title: str


class SessionRespDTO(BaseModel):
    id: int
    user_id: int
    title: str
    create_at: datetime.datetime
    update_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)


class MessageRespDTO(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    sources: list | dict
    create_at: datetime.datetime
    model_config = ConfigDict(from_attributes=True)
