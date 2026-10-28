import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class TrainingPlanModel(Base):
    """账号拥有的训练计划；一周的训练日和动作以已校验 JSON 结构保存。"""

    __tablename__ = "kh_training_plan"
    __table_args__ = (
        CheckConstraint(
            "goal IS NULL OR goal IN ('增肌', '减脂', '体能提升', '保持健康')",
            name="ck_training_plan_goal",
        ),
        CheckConstraint(
            "experience IS NULL OR experience IN ('刚开始', '训练一段时间', '比较规律')",
            name="ck_training_plan_experience",
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
    title = Column(String(120), nullable=False, comment="训练计划名称")
    goal = Column(String(20), nullable=True, comment="计划目标")
    experience = Column(String(20), nullable=True, comment="适用训练经验")
    days = Column("plan_data", JSONB, nullable=False, comment="按天保存的训练安排和动作明细")
    create_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    update_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )
