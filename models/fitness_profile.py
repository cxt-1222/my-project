import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String

from core.database import Base


class FitnessProfileModel(Base):
    """每个账号一条健身档案；只存储前端当前采集的四个字段。"""

    __tablename__ = "kh_fitness_profile"
    __table_args__ = (
        CheckConstraint("height IS NULL OR (height >= 80 AND height <= 250)", name="ck_fitness_profile_height"),
        CheckConstraint("weight IS NULL OR (weight >= 25 AND weight <= 300)", name="ck_fitness_profile_weight"),
        CheckConstraint(
            "goal IS NULL OR goal IN ('增肌', '减脂', '体能提升', '保持健康')",
            name="ck_fitness_profile_goal",
        ),
        CheckConstraint(
            "experience IS NULL OR experience IN ('刚开始', '训练一段时间', '比较规律')",
            name="ck_fitness_profile_experience",
        ),
    )

    user_id = Column(
        Integer,
        ForeignKey("kh_user.id", ondelete="CASCADE"),
        primary_key=True,
        comment="账号ID；主键确保每个账号最多一份档案",
    )
    height = Column(Float, nullable=True, comment="身高，厘米")
    weight = Column(Float, nullable=True, comment="体重，千克")
    goal = Column(String(20), nullable=True, comment="训练目标")
    experience = Column(String(20), nullable=True, comment="训练经验")
    create_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    update_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )
