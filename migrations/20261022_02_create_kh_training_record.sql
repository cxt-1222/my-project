-- 阶段 6：账号训练打卡与统计来源。
-- 可重复执行；不会修改或删除现有计划和档案数据。
CREATE TABLE IF NOT EXISTS kh_training_record (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES kh_user(id) ON DELETE CASCADE,
    plan_id BIGINT NULL REFERENCES kh_training_plan(id) ON DELETE SET NULL,
    plan_title VARCHAR(120) NOT NULL CHECK (length(trim(plan_title)) > 0),
    plan_day VARCHAR(20) NOT NULL CHECK (length(trim(plan_day)) > 0),
    focus VARCHAR(120) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'completed', 'cancelled')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ NULL,
    cancelled_at TIMESTAMPTZ NULL,
    duration_seconds INTEGER NULL CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    body_weight_kg DOUBLE PRECISION NULL
        CHECK (body_weight_kg IS NULL OR (body_weight_kg >= 25 AND body_weight_kg <= 300)),
    exercises JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(exercises) = 'array'),
    create_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (status = 'in_progress' AND completed_at IS NULL AND cancelled_at IS NULL)
        OR (status = 'completed' AND completed_at IS NOT NULL AND cancelled_at IS NULL)
        OR (status = 'cancelled' AND completed_at IS NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_kh_training_record_user_started
    ON kh_training_record (user_id, started_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS ix_kh_training_record_user_completed
    ON kh_training_record (user_id, completed_at DESC)
    WHERE status = 'completed';
