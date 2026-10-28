import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class TrainingRecordModel(Base):
    """Account-owned workout instance, distinct from its reusable plan template."""

    __tablename__ = "kh_training_record"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'cancelled')",
            name="ck_training_record_status",
        ),
        CheckConstraint(
            "(status = 'in_progress' AND completed_at IS NULL AND cancelled_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL AND cancelled_at IS NULL) "
            "OR (status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL)",
            name="ck_training_record_lifecycle_timestamps",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_training_record_duration",
        ),
        CheckConstraint(
            "body_weight_kg IS NULL OR (body_weight_kg >= 25 AND body_weight_kg <= 300)",
            name="ck_training_record_body_weight",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("kh_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属账号ID",
    )
    plan_id = Column(
        BigInteger,
        ForeignKey("kh_training_plan.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联的可复用训练计划",
    )
    plan_title = Column(String(120), nullable=False, comment="开始训练时的计划名称快照")
    plan_day = Column(String(20), nullable=False, comment="训练计划日标签快照")
    focus = Column(String(120), nullable=True, comment="本次训练重点")
    status = Column(String(16), nullable=False, default="in_progress")
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    body_weight_kg = Column(Float, nullable=True, comment="本次训练时记录的体重，千克")
    exercises = Column(JSONB, nullable=False, default=list, comment="动作计划快照及实际完成数据")
    create_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.datetime.now(datetime.timezone.utc))
