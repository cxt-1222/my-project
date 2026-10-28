import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, SmallInteger, String

from core.database import Base


class FitnessProfileModel(Base):
    """每个账号一条健身档案；供档案页、AI 问答和计划草稿使用。"""

    __tablename__ = "kh_fitness_profile"
    __table_args__ = (
        CheckConstraint("height IS NULL OR (height >= 80 AND height <= 250)", name="ck_fitness_profile_height"),
        CheckConstraint("weight IS NULL OR (weight >= 25 AND weight <= 300)", name="ck_fitness_profile_weight"),
        CheckConstraint("age IS NULL OR (age >= 13 AND age <= 100)", name="ck_fitness_profile_age"),
        CheckConstraint("sex IS NULL OR sex IN ('男', '女', '不愿透露')", name="ck_fitness_profile_sex"),
        CheckConstraint(
            "goal IS NULL OR goal IN ('增肌', '减脂', '体能提升', '保持健康')",
            name="ck_fitness_profile_goal",
        ),
        CheckConstraint(
            "experience IS NULL OR experience IN ('刚开始', '训练一段时间', '比较规律')",
            name="ck_fitness_profile_experience",
        ),
        CheckConstraint(
            "weekly_training_days IS NULL OR (weekly_training_days >= 1 AND weekly_training_days <= 7)",
            name="ck_fitness_profile_weekly_training_days",
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
    age = Column(SmallInteger, nullable=True, comment="年龄，岁")
    sex = Column(String(20), nullable=True, comment="用户自愿填写的性别")
    goal = Column(String(20), nullable=True, comment="训练目标")
    experience = Column(String(20), nullable=True, comment="训练经验")
    weekly_training_days = Column(SmallInteger, nullable=True, comment="每周可训练天数")
    equipment = Column(String(300), nullable=True, comment="可用训练器械")
    limitations = Column(String(500), nullable=True, comment="用户自述的身体限制或避开事项")
    create_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    update_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
        nullable=False,
    )
