-- 阶段 7.2：拍照识餐预览和营养记录来源关联。可重复执行，不改写既有手动记录。
CREATE TABLE IF NOT EXISTS kh_nutrition_photo (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES kh_user(id) ON DELETE CASCADE,
    image_key VARCHAR(255) NOT NULL,
    content_type VARCHAR(80) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'preview'
        CHECK (status IN ('preview', 'confirmed', 'failed', 'cancelled')),
    recognized_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_kh_nutrition_photo_user_created
    ON kh_nutrition_photo (user_id, created_at, id);

ALTER TABLE kh_nutrition_record
    ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'manual';

ALTER TABLE kh_nutrition_record
    ADD COLUMN IF NOT EXISTS photo_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_nutrition_record_source'
          AND conrelid = 'kh_nutrition_record'::regclass
    ) THEN
        ALTER TABLE kh_nutrition_record
            ADD CONSTRAINT ck_nutrition_record_source
            CHECK (source IN ('manual', 'photo'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_kh_nutrition_record_photo_id'
          AND conrelid = 'kh_nutrition_record'::regclass
    ) THEN
        ALTER TABLE kh_nutrition_record
            ADD CONSTRAINT fk_kh_nutrition_record_photo_id
            FOREIGN KEY (photo_id) REFERENCES kh_nutrition_photo(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_kh_nutrition_record_photo_id
    ON kh_nutrition_record (photo_id);
