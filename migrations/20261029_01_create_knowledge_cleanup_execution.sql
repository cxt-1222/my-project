-- 记录旧知识清理操作的状态和计数，不存储知识正文。
CREATE TABLE IF NOT EXISTS kh_knowledge_cleanup_execution (
    id BIGSERIAL PRIMARY KEY,
    preview_sha256 CHAR(64) NOT NULL,
    requested_by INTEGER NOT NULL,
    execution_status VARCHAR(16) NOT NULL DEFAULT 'running'
        CHECK (execution_status IN ('running', 'completed', 'failed')),
    result JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(result) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS ix_kh_knowledge_cleanup_execution_created_at
    ON kh_knowledge_cleanup_execution (created_at);
