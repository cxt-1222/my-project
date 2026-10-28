import datetime

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func

from core.database import Base


class NutritionRecordModel(Base):
    """One account-owned, manually entered food and its nutrition values."""

    __tablename__ = "kh_nutrition_record"
    __table_args__ = (
        CheckConstraint(
            "meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_nutrition_record_meal_type",
        ),
        CheckConstraint("amount > 0", name="ck_nutrition_record_amount_positive"),
        CheckConstraint("calories_kcal >= 0", name="ck_nutrition_record_calories_nonnegative"),
        CheckConstraint("protein_g >= 0", name="ck_nutrition_record_protein_nonnegative"),
        CheckConstraint("carbohydrate_g >= 0", name="ck_nutrition_record_carbohydrate_nonnegative"),
        CheckConstraint("fat_g >= 0", name="ck_nutrition_record_fat_nonnegative"),
        CheckConstraint(
            "source IN ('manual', 'photo')",
            name="ck_nutrition_record_source",
        ),
        Index("ix_kh_nutrition_record_user_date", "user_id", "record_date", "created_at", "id"),
        Index("ix_kh_nutrition_record_photo_id", "photo_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("kh_user.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属账号ID",
    )
    record_date = Column(Date, nullable=False, comment="用户选择的饮食日期，不做时区换算")
    meal_type = Column(String(16), nullable=False, comment="餐次：breakfast/lunch/dinner/snack")
    food_name = Column(String(120), nullable=False, comment="用户手动填写的食物名称")
    amount = Column(Numeric(12, 3), nullable=False, comment="食物份量")
    unit = Column(String(20), nullable=False, comment="份量单位")
    calories_kcal = Column(Numeric(12, 2), nullable=False, comment="热量，千卡")
    protein_g = Column(Numeric(12, 2), nullable=False, comment="蛋白质，克")
    carbohydrate_g = Column(Numeric(12, 2), nullable=False, comment="碳水化合物，克")
    fat_g = Column(Numeric(12, 2), nullable=False, comment="脂肪，克")
    source = Column(String(16), nullable=False, server_default="manual", comment="manual/photo")
    photo_id = Column(
        Integer,
        ForeignKey("kh_nutrition_photo.id", ondelete="SET NULL"),
        nullable=True,
        comment="确认来源图片ID",
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
