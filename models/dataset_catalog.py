from sqlalchemy import (
    BigInteger,
    CHAR,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class DatasetImportModel(Base):
    __tablename__ = "kh_dataset_import"
    __table_args__ = (
        CheckConstraint(
            "import_status IN ('previewed', 'importing', 'imported', 'failed', 'disabled')",
            name="ck_dataset_import_status",
        ),
        CheckConstraint(
            "metadata_license_status IN ('pending_review', 'approved', 'restricted')",
            name="ck_dataset_import_metadata_license_status",
        ),
        CheckConstraint(
            "media_license_status IN ('not_applicable', 'pending_review', 'approved', 'restricted', 'unverified')",
            name="ck_dataset_import_media_license_status",
        ),
        UniqueConstraint("dataset", "revision", name="uq_kh_dataset_import_dataset_revision"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dataset = Column(String(80), nullable=False)
    repository = Column(String(255), nullable=False)
    revision = Column(String(64), nullable=False)
    locked_on = Column(Date, nullable=False)
    import_status = Column(String(16), nullable=False, server_default="previewed")
    metadata_license_status = Column(String(20), nullable=False, server_default="pending_review")
    media_license_status = Column(String(20), nullable=False, server_default="not_applicable")
    license_note = Column(Text, nullable=False, server_default="")
    file_manifest = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DatasetImportProgressModel(Base):
    __tablename__ = "kh_dataset_import_progress"
    __table_args__ = (
        CheckConstraint(
            "progress_status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_kh_dataset_import_progress_status",
        ),
        CheckConstraint(
            "storage_name IN ('postgres_catalog', 'postgres_documents', 'mongodb', 'elasticsearch', 'milvus', 'neo4j')",
            name="ck_kh_dataset_import_progress_storage",
        ),
        CheckConstraint("processed_records >= 0", name="ck_kh_dataset_import_progress_processed_nonnegative"),
        CheckConstraint("skipped_records >= 0", name="ck_kh_dataset_import_progress_skipped_nonnegative"),
        CheckConstraint("failed_records >= 0", name="ck_kh_dataset_import_progress_failed_nonnegative"),
        CheckConstraint("jsonb_typeof(checkpoint) = 'object'", name="ck_kh_dataset_import_progress_checkpoint_object"),
        UniqueConstraint("import_id", "storage_name", name="uq_kh_dataset_import_progress_storage"),
        Index("ix_kh_dataset_import_progress_status", "import_id", "progress_status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("kh_dataset_import.id", ondelete="CASCADE"), nullable=False)
    storage_name = Column(String(32), nullable=False)
    progress_status = Column(String(16), nullable=False, server_default="pending")
    processed_records = Column(Integer, nullable=False, server_default="0")
    skipped_records = Column(Integer, nullable=False, server_default="0")
    failed_records = Column(Integer, nullable=False, server_default="0")
    checkpoint = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_error = Column(Text, nullable=False, server_default="")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExerciseCatalogModel(Base):
    __tablename__ = "kh_exercise_catalog"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_exercise_catalog_name_nonempty"),
        CheckConstraint("jsonb_typeof(aliases) = 'array'", name="ck_exercise_catalog_aliases_array"),
        CheckConstraint("jsonb_typeof(normalized_fields) = 'object'", name="ck_exercise_catalog_fields_object"),
        CheckConstraint("jsonb_typeof(raw_record) = 'object'", name="ck_exercise_catalog_raw_object"),
        CheckConstraint(
            "license_status IN ('pending_review', 'approved', 'restricted')",
            name="ck_exercise_catalog_license_status",
        ),
        CheckConstraint("record_status IN ('quarantined', 'active', 'disabled')", name="ck_exercise_catalog_record_status"),
        UniqueConstraint("import_id", "upstream_id", name="uq_kh_exercise_catalog_import_upstream"),
        Index("ix_kh_exercise_catalog_name_normalized", "name_normalized"),
        Index("ix_kh_exercise_catalog_status", "record_status", "license_status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("kh_dataset_import.id", ondelete="CASCADE"), nullable=False)
    upstream_id = Column(String(160), nullable=False, comment="缺少上游 ID 时由转换器生成稳定内容摘要 ID")
    name = Column(Text, nullable=False)
    name_normalized = Column(Text, nullable=False)
    aliases = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    normalized_fields = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    raw_record = Column(JSONB, nullable=False)
    content_sha256 = Column(CHAR(64), nullable=False)
    license_status = Column(String(20), nullable=False, server_default="pending_review")
    record_status = Column(String(16), nullable=False, server_default="quarantined")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ExerciseMediaModel(Base):
    __tablename__ = "kh_exercise_media"
    __table_args__ = (
        CheckConstraint("media_kind IN ('video', 'image')", name="ck_exercise_media_kind"),
        CheckConstraint("allowed_use IN ('none', 'link', 'embed', 'host')", name="ck_exercise_media_allowed_use"),
        CheckConstraint(
            "license_status IN ('unverified', 'pending_review', 'approved', 'restricted')",
            name="ck_exercise_media_license_status",
        ),
        CheckConstraint(
            "mapping_status IN ('unverified', 'pending_review', 'verified', 'rejected')",
            name="ck_exercise_media_mapping_status",
        ),
        UniqueConstraint("exercise_id", "media_kind", "variant", "source_url", name="uq_kh_exercise_media_variant_url"),
        Index("ix_kh_exercise_media_visibility", "license_status", "mapping_status", "allowed_use"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exercise_id = Column(BigInteger, ForeignKey("kh_exercise_catalog.id", ondelete="CASCADE"), nullable=False)
    media_kind = Column(String(16), nullable=False)
    variant = Column(String(32), nullable=False, server_default="default")
    source_url = Column(Text, nullable=False)
    source_host = Column(String(255), nullable=False, server_default="")
    attribution = Column(Text, nullable=False, server_default="")
    rights_evidence = Column(Text, nullable=False, server_default="")
    allowed_use = Column(String(16), nullable=False, server_default="none")
    license_status = Column(String(20), nullable=False, server_default="unverified")
    mapping_status = Column(String(20), nullable=False, server_default="unverified")
    media_sha256 = Column(CHAR(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FoodCatalogModel(Base):
    __tablename__ = "kh_food_catalog"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_food_catalog_name_nonempty"),
        CheckConstraint(
            "nutrition_basis IN ('unknown', 'per_100g', 'per_serving', 'other')",
            name="ck_food_catalog_nutrition_basis",
        ),
        CheckConstraint("jsonb_typeof(nutrients_raw) = 'object'", name="ck_food_catalog_nutrients_object"),
        CheckConstraint("jsonb_typeof(raw_record) = 'object'", name="ck_food_catalog_raw_object"),
        CheckConstraint(
            "license_status IN ('pending_review', 'approved', 'restricted')",
            name="ck_food_catalog_license_status",
        ),
        CheckConstraint("record_status IN ('quarantined', 'active', 'disabled')", name="ck_food_catalog_record_status"),
        UniqueConstraint("import_id", "source_key", "upstream_id", name="uq_kh_food_catalog_import_source_upstream"),
        Index("ix_kh_food_catalog_name", "name"),
        Index("ix_kh_food_catalog_source_status", "source_key", "record_status", "license_status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("kh_dataset_import.id", ondelete="CASCADE"), nullable=False)
    upstream_id = Column(String(160), nullable=False, comment="缺少上游 code 时由转换器生成稳定内容摘要 ID")
    source_key = Column(String(120), nullable=False)
    name = Column(Text, nullable=False)
    nutrition_basis = Column(String(24), nullable=False, server_default="unknown")
    edible_value = Column(Numeric(12, 6), nullable=True)
    nutrients_raw = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    raw_record = Column(JSONB, nullable=False)
    content_sha256 = Column(CHAR(64), nullable=False)
    license_status = Column(String(20), nullable=False, server_default="pending_review")
    record_status = Column(String(16), nullable=False, server_default="quarantined")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecipeCatalogModel(Base):
    __tablename__ = "kh_recipe_catalog"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_recipe_catalog_title_nonempty"),
        CheckConstraint("servings IS NULL OR servings > 0", name="ck_recipe_catalog_servings_positive"),
        CheckConstraint("jsonb_typeof(recipe_data) = 'object'", name="ck_recipe_catalog_data_object"),
        CheckConstraint(
            "license_status IN ('pending_review', 'approved', 'restricted')",
            name="ck_recipe_catalog_license_status",
        ),
        CheckConstraint("record_status IN ('quarantined', 'active', 'disabled')", name="ck_recipe_catalog_record_status"),
        UniqueConstraint("import_id", "upstream_id", name="uq_kh_recipe_catalog_import_upstream"),
        Index("ix_kh_recipe_catalog_title", "title"),
        Index("ix_kh_recipe_catalog_status", "record_status", "license_status"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("kh_dataset_import.id", ondelete="CASCADE"), nullable=False)
    upstream_id = Column(String(160), nullable=False)
    title = Column(Text, nullable=False)
    source_name = Column(Text, nullable=False, server_default="")
    source_url = Column(Text, nullable=False, server_default="")
    source_revision = Column(String(160), nullable=False, server_default="")
    source_license = Column(String(160), nullable=False, server_default="")
    servings = Column(Numeric(12, 4), nullable=True)
    recipe_data = Column(JSONB, nullable=False)
    content_sha256 = Column(CHAR(64), nullable=False)
    license_status = Column(String(20), nullable=False, server_default="pending_review")
    record_status = Column(String(16), nullable=False, server_default="quarantined")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecipeIngredientModel(Base):
    __tablename__ = "kh_recipe_ingredient"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_recipe_ingredient_position_nonnegative"),
        CheckConstraint("length(trim(name)) > 0", name="ck_recipe_ingredient_name_nonempty"),
        CheckConstraint("amount IS NULL OR amount > 0", name="ck_recipe_ingredient_amount_positive"),
        CheckConstraint(
            "match_status IN ('unresolved', 'exact', 'approved_alias', 'fuzzy', 'missing')",
            name="ck_recipe_ingredient_match_status",
        ),
        CheckConstraint("jsonb_typeof(raw_record) = 'object'", name="ck_recipe_ingredient_raw_object"),
        UniqueConstraint("recipe_id", "position", name="uq_kh_recipe_ingredient_recipe_position"),
        Index("ix_kh_recipe_ingredient_food_id", "food_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    recipe_id = Column(BigInteger, ForeignKey("kh_recipe_catalog.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    name = Column(Text, nullable=False)
    amount = Column(Numeric(14, 6), nullable=True)
    unit = Column(String(40), nullable=False, server_default="")
    note = Column(Text, nullable=False, server_default="")
    food_source_key = Column(String(120), nullable=False, server_default="")
    food_upstream_id = Column(String(160), nullable=False, server_default="")
    food_id = Column(BigInteger, ForeignKey("kh_food_catalog.id", ondelete="SET NULL"), nullable=True)
    match_status = Column(String(20), nullable=False, server_default="unresolved")
    raw_record = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class KnowledgeSourceMappingModel(Base):
    __tablename__ = "kh_knowledge_source_mapping"
    __table_args__ = (
        CheckConstraint("record_kind IN ('exercise', 'recipe')", name="ck_knowledge_source_mapping_kind"),
        CheckConstraint(
            "mapping_status IN ('pending', 'active', 'disabled')",
            name="ck_knowledge_source_mapping_status",
        ),
        UniqueConstraint(
            "import_id", "record_kind", "source_record_id",
            name="uq_kh_knowledge_source_mapping_record",
        ),
        UniqueConstraint("import_id", "document_id", name="uq_kh_knowledge_source_mapping_document"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("kh_dataset_import.id", ondelete="CASCADE"), nullable=False)
    record_kind = Column(String(16), nullable=False)
    source_record_id = Column(String(160), nullable=False)
    document_id = Column(BigInteger, ForeignKey("kh_document.id", ondelete="CASCADE"), nullable=False)
    content_sha256 = Column(CHAR(64), nullable=False)
    mapping_status = Column(String(16), nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
