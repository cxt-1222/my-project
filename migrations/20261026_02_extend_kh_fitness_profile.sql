-- 阶段 2：为 AI 教练补充可选的个性化档案字段。
-- 增量且可重复执行；不改写已有账号档案。
ALTER TABLE kh_fitness_profile
    ADD COLUMN IF NOT EXISTS age SMALLINT NULL,
    ADD COLUMN IF NOT EXISTS sex VARCHAR(20) NULL,
    ADD COLUMN IF NOT EXISTS weekly_training_days SMALLINT NULL,
    ADD COLUMN IF NOT EXISTS equipment VARCHAR(300) NULL,
    ADD COLUMN IF NOT EXISTS limitations VARCHAR(500) NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_fitness_profile_age'
          AND conrelid = 'kh_fitness_profile'::regclass
    ) THEN
        ALTER TABLE kh_fitness_profile
            ADD CONSTRAINT ck_fitness_profile_age
            CHECK (age IS NULL OR (age >= 13 AND age <= 100));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_fitness_profile_sex'
          AND conrelid = 'kh_fitness_profile'::regclass
    ) THEN
        ALTER TABLE kh_fitness_profile
            ADD CONSTRAINT ck_fitness_profile_sex
            CHECK (sex IS NULL OR sex IN ('男', '女', '不愿透露'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_fitness_profile_weekly_training_days'
          AND conrelid = 'kh_fitness_profile'::regclass
    ) THEN
        ALTER TABLE kh_fitness_profile
            ADD CONSTRAINT ck_fitness_profile_weekly_training_days
            CHECK (weekly_training_days IS NULL OR (weekly_training_days >= 1 AND weekly_training_days <= 7));
    END IF;
END $$;
