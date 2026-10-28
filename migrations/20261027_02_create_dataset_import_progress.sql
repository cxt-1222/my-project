-- 阶段 3.2：为目录与现有检索链路记录可恢复的逐存储导入进度。
-- 仅新增表和索引；不修改或删除既有数据/索引/共享集合。

CREATE TABLE IF NOT EXISTS kh_dataset_import_progress (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES kh_dataset_import(id) ON DELETE CASCADE,
    storage_name VARCHAR(32) NOT NULL
        CHECK (storage_name IN (
            'postgres_catalog', 'postgres_documents', 'mongodb',
            'elasticsearch', 'milvus', 'neo4j'
        )),
    progress_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (progress_status IN ('pending', 'running', 'completed', 'failed')),
    processed_records INTEGER NOT NULL DEFAULT 0 CHECK (processed_records >= 0),
    skipped_records INTEGER NOT NULL DEFAULT 0 CHECK (skipped_records >= 0),
    failed_records INTEGER NOT NULL DEFAULT 0 CHECK (failed_records >= 0),
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(checkpoint) = 'object'),
    last_error TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_kh_dataset_import_progress_storage UNIQUE (import_id, storage_name)
);

CREATE INDEX IF NOT EXISTS ix_kh_dataset_import_progress_status
    ON kh_dataset_import_progress (import_id, progress_status);
