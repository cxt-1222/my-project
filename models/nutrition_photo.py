from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class NutritionPhotoModel(Base):
    """Account-owned meal image and its reviewable recognition preview."""

    __tablename__ = "kh_nutrition_photo"
    __table_args__ = (
        CheckConstraint(
            "status IN ('preview', 'confirmed', 'failed', 'cancelled')",
            name="ck_kh_nutrition_photo_status",
        ),
        Index("ix_kh_nutrition_photo_user_created", "user_id", "created_at", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("kh_user.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账号ID",
    )
    image_key = Column(String(255), nullable=False, comment="RustFS 对象键")
    content_type = Column(String(80), nullable=False, comment="图片 MIME 类型")
    status = Column(String(16), nullable=False, server_default="preview")
    recognized_payload = Column(JSONB, nullable=False, comment="规范化后的识别预览")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
