-- 阶段 3.1：每个登录账号一条健身档案。
-- 可重复执行；不会删除或改写现有表/数据。
CREATE TABLE IF NOT EXISTS kh_fitness_profile (
    user_id INTEGER PRIMARY KEY REFERENCES kh_user(id) ON DELETE CASCADE,
    height DOUBLE PRECISION NULL CHECK (height IS NULL OR (height >= 80 AND height <= 250)),
    weight DOUBLE PRECISION NULL CHECK (weight IS NULL OR (weight >= 25 AND weight <= 300)),
    goal VARCHAR(20) NULL CHECK (goal IS NULL OR goal IN ('增肌', '减脂', '体能提升', '保持健康')),
    experience VARCHAR(20) NULL CHECK (experience IS NULL OR experience IN ('刚开始', '训练一段时间', '比较规律')),
    create_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
