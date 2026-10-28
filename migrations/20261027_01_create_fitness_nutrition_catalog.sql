-- 阶段 2.1：健身/饮食目录与来源追踪结构。
-- 仅新增表和索引；不导入数据、不修改既有业务表或共享检索集合。

CREATE TABLE IF NOT EXISTS kh_dataset_import (
    id BIGSERIAL PRIMARY KEY,
    dataset VARCHAR(80) NOT NULL,
    repository VARCHAR(255) NOT NULL,
    revision VARCHAR(64) NOT NULL,
    locked_on DATE NOT NULL,
    import_status VARCHAR(16) NOT NULL DEFAULT 'previewed'
        CHECK (import_status IN ('previewed', 'importing', 'imported', 'failed', 'disabled')),
    metadata_license_status VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (metadata_license_status IN ('pending_review', 'approved', 'restricted')),
    media_license_status VARCHAR(20) NOT NULL DEFAULT 'not_applicable'
        CHECK (media_license_status IN ('not_applicable', 'pending_review', 'approved', 'restricted', 'unverified')),
    license_note TEXT NOT NULL DEFAULT '',
    file_manifest JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(file_manifest) = 'array'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_dataset_import_dataset_revision UNIQUE (dataset, revision)
);

CREATE TABLE IF NOT EXISTS kh_exercise_catalog (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES kh_dataset_import(id) ON DELETE CASCADE,
    upstream_id VARCHAR(160) NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_normalized TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(aliases) = 'array'),
    normalized_fields JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(normalized_fields) = 'object'),
    raw_record JSONB NOT NULL CHECK (jsonb_typeof(raw_record) = 'object'),
    content_sha256 CHAR(64) NOT NULL,
    license_status VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (license_status IN ('pending_review', 'approved', 'restricted')),
    record_status VARCHAR(16) NOT NULL DEFAULT 'quarantined'
        CHECK (record_status IN ('quarantined', 'active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_exercise_catalog_import_upstream UNIQUE (import_id, upstream_id)
);

CREATE INDEX IF NOT EXISTS ix_kh_exercise_catalog_name_normalized
    ON kh_exercise_catalog (name_normalized);
CREATE INDEX IF NOT EXISTS ix_kh_exercise_catalog_status
    ON kh_exercise_catalog (record_status, license_status);

CREATE TABLE IF NOT EXISTS kh_exercise_media (
    id BIGSERIAL PRIMARY KEY,
    exercise_id BIGINT NOT NULL REFERENCES kh_exercise_catalog(id) ON DELETE CASCADE,
    media_kind VARCHAR(16) NOT NULL CHECK (media_kind IN ('video', 'image')),
    variant VARCHAR(32) NOT NULL DEFAULT 'default',
    source_url TEXT NOT NULL,
    source_host VARCHAR(255) NOT NULL DEFAULT '',
    attribution TEXT NOT NULL DEFAULT '',
    rights_evidence TEXT NOT NULL DEFAULT '',
    allowed_use VARCHAR(16) NOT NULL DEFAULT 'none'
        CHECK (allowed_use IN ('none', 'link', 'embed', 'host')),
    license_status VARCHAR(20) NOT NULL DEFAULT 'unverified'
        CHECK (license_status IN ('unverified', 'pending_review', 'approved', 'restricted')),
    mapping_status VARCHAR(20) NOT NULL DEFAULT 'unverified'
        CHECK (mapping_status IN ('unverified', 'pending_review', 'verified', 'rejected')),
    media_sha256 CHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_exercise_media_variant_url UNIQUE (exercise_id, media_kind, variant, source_url)
);

CREATE INDEX IF NOT EXISTS ix_kh_exercise_media_visibility
    ON kh_exercise_media (license_status, mapping_status, allowed_use);

CREATE TABLE IF NOT EXISTS kh_food_catalog (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES kh_dataset_import(id) ON DELETE CASCADE,
    upstream_id VARCHAR(160) NOT NULL,
    source_key VARCHAR(120) NOT NULL,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    nutrition_basis VARCHAR(24) NOT NULL DEFAULT 'unknown'
        CHECK (nutrition_basis IN ('unknown', 'per_100g', 'per_serving', 'other')),
    edible_value NUMERIC(12, 6) NULL,
    nutrients_raw JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(nutrients_raw) = 'object'),
    raw_record JSONB NOT NULL CHECK (jsonb_typeof(raw_record) = 'object'),
    content_sha256 CHAR(64) NOT NULL,
    license_status VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (license_status IN ('pending_review', 'approved', 'restricted')),
    record_status VARCHAR(16) NOT NULL DEFAULT 'quarantined'
        CHECK (record_status IN ('quarantined', 'active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_food_catalog_import_source_upstream UNIQUE (import_id, source_key, upstream_id)
);

CREATE INDEX IF NOT EXISTS ix_kh_food_catalog_name
    ON kh_food_catalog (name);
CREATE INDEX IF NOT EXISTS ix_kh_food_catalog_source_status
    ON kh_food_catalog (source_key, record_status, license_status);

CREATE TABLE IF NOT EXISTS kh_recipe_catalog (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES kh_dataset_import(id) ON DELETE CASCADE,
    upstream_id VARCHAR(160) NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    source_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_revision VARCHAR(160) NOT NULL DEFAULT '',
    source_license VARCHAR(160) NOT NULL DEFAULT '',
    servings NUMERIC(12, 4) NULL CHECK (servings IS NULL OR servings > 0),
    recipe_data JSONB NOT NULL CHECK (jsonb_typeof(recipe_data) = 'object'),
    content_sha256 CHAR(64) NOT NULL,
    license_status VARCHAR(20) NOT NULL DEFAULT 'pending_review'
        CHECK (license_status IN ('pending_review', 'approved', 'restricted')),
    record_status VARCHAR(16) NOT NULL DEFAULT 'quarantined'
        CHECK (record_status IN ('quarantined', 'active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_recipe_catalog_import_upstream UNIQUE (import_id, upstream_id)
);

CREATE INDEX IF NOT EXISTS ix_kh_recipe_catalog_title
    ON kh_recipe_catalog (title);
CREATE INDEX IF NOT EXISTS ix_kh_recipe_catalog_status
    ON kh_recipe_catalog (record_status, license_status);

CREATE TABLE IF NOT EXISTS kh_recipe_ingredient (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES kh_recipe_catalog(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK (position >= 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    amount NUMERIC(14, 6) NULL CHECK (amount IS NULL OR amount > 0),
    unit VARCHAR(40) NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    food_source_key VARCHAR(120) NOT NULL DEFAULT '',
    food_upstream_id VARCHAR(160) NOT NULL DEFAULT '',
    food_id BIGINT NULL REFERENCES kh_food_catalog(id) ON DELETE SET NULL,
    match_status VARCHAR(20) NOT NULL DEFAULT 'unresolved'
        CHECK (match_status IN ('unresolved', 'exact', 'approved_alias', 'fuzzy', 'missing')),
    raw_record JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(raw_record) = 'object'),
    CONSTRAINT uq_kh_recipe_ingredient_recipe_position UNIQUE (recipe_id, position)
);

CREATE INDEX IF NOT EXISTS ix_kh_recipe_ingredient_food_id
    ON kh_recipe_ingredient (food_id);

CREATE TABLE IF NOT EXISTS kh_knowledge_source_mapping (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES kh_dataset_import(id) ON DELETE CASCADE,
    record_kind VARCHAR(16) NOT NULL CHECK (record_kind IN ('exercise', 'recipe')),
    source_record_id VARCHAR(160) NOT NULL,
    document_id BIGINT NOT NULL REFERENCES kh_document(id) ON DELETE CASCADE,
    content_sha256 CHAR(64) NOT NULL,
    mapping_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (mapping_status IN ('pending', 'active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_knowledge_source_mapping_record
        UNIQUE (import_id, record_kind, source_record_id),
    CONSTRAINT uq_kh_knowledge_source_mapping_document
        UNIQUE (import_id, document_id)
);

