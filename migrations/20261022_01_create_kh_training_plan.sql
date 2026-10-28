-- 阶段 4.1：账号训练计划存储。
-- 可重复执行；不会删除或改写现有表/数据。
CREATE TABLE IF NOT EXISTS kh_training_plan (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES kh_user(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL CHECK (length(trim(title)) > 0),
    goal VARCHAR(20) NULL CHECK (goal IS NULL OR goal IN ('增肌', '减脂', '体能提升', '保持健康')),
    experience VARCHAR(20) NULL CHECK (experience IS NULL OR experience IN ('刚开始', '训练一段时间', '比较规律')),
    plan_data JSONB NOT NULL CHECK (jsonb_typeof(plan_data) = 'array'),
    create_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_kh_training_plan_user_id ON kh_training_plan (user_id);
CREATE INDEX IF NOT EXISTS ix_kh_training_plan_user_update ON kh_training_plan (user_id, update_at DESC, id DESC);
