from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, ConfigDict, Field


# 请求模型
class KnowledgeDoc(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: Optional[str] = None
    content_id: Optional[int] = None
    summary: Optional[str] = None
    category_id: Optional[int] = None
    team_id: Optional[int] = None
    author_id: Optional[int] = None
    cover_image: Optional[str] = None
    # tags ES是keyword类型，可以存数组，所以用List[str]
    tags: Optional[List[str]] = None
    status: Optional[int] = Field(default=None, description="状态 byte，范围 -128~127")
    remark: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    favorite_count: Optional[int] = None
    word_count: Optional[int] = None
    publish_time: Optional[datetime] = None
    is_public: Optional[bool] = None
    create_at: Optional[datetime] = None
    update_at: Optional[datetime] = None
    version: Optional[int] = None
    create_by: Optional[str] = None
    update_by: Optional[str] = None
    deleted: Optional[bool] = None
    content: Optional[str] = None
