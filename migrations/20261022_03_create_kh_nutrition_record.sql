-- 阶段 7 第一版：手动营养记录。可重复执行，不写入或修改既有业务数据。
CREATE TABLE IF NOT EXISTS kh_nutrition_record (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES kh_user(id) ON DELETE CASCADE,
    record_date DATE NOT NULL,
    meal_type VARCHAR(16) NOT NULL
        CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    food_name VARCHAR(120) NOT NULL CHECK (length(trim(food_name)) > 0),
    amount NUMERIC(12, 3) NOT NULL CHECK (amount > 0),
    unit VARCHAR(20) NOT NULL CHECK (length(trim(unit)) > 0),
    calories_kcal NUMERIC(12, 2) NOT NULL CHECK (calories_kcal >= 0),
    protein_g NUMERIC(12, 2) NOT NULL CHECK (protein_g >= 0),
    carbohydrate_g NUMERIC(12, 2) NOT NULL CHECK (carbohydrate_g >= 0),
    fat_g NUMERIC(12, 2) NOT NULL CHECK (fat_g >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_kh_nutrition_record_user_date
    ON kh_nutrition_record (user_id, record_date, created_at, id);
