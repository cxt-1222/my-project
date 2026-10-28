# 健身与饮食目录表结构验收

本步骤只应用新增 PostgreSQL 表结构，不导入数据、不访问视频/图片、不清理旧知识库。

## 1. 执行迁移

在 PowerShell 中运行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'

docker compose cp .\migrations\20261027_01_create_fitness_nutrition_catalog.sql postgres:/tmp/fitness-nutrition-catalog.sql

docker compose exec postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /tmp/fitness-nutrition-catalog.sql'
```

使用容器当前配置的 `POSTGRES_USER` / `POSTGRES_DB`，避免手动猜数据库角色。`ON_ERROR_STOP=1` 可确保 SQL 出错时命令返回失败。

## 2. 验收表已创建

```powershell
@'
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'kh_dataset_import', 'kh_exercise_catalog', 'kh_exercise_media',
    'kh_food_catalog', 'kh_recipe_catalog', 'kh_recipe_ingredient',
    'kh_knowledge_source_mapping'
  )
ORDER BY table_name;
'@ | docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

预期至少看到以下 7 张新表：

- `kh_dataset_import`
- `kh_exercise_catalog`
- `kh_exercise_media`
- `kh_food_catalog`
- `kh_recipe_catalog`
- `kh_recipe_ingredient`
- `kh_knowledge_source_mapping`

## 3. 验收表为空且重复执行安全

```powershell
@'
SELECT
  (SELECT count(*) FROM kh_dataset_import) AS imports,
  (SELECT count(*) FROM kh_exercise_catalog) AS exercises,
  (SELECT count(*) FROM kh_exercise_media) AS media,
  (SELECT count(*) FROM kh_food_catalog) AS foods,
  (SELECT count(*) FROM kh_recipe_catalog) AS recipes,
  (SELECT count(*) FROM kh_recipe_ingredient) AS ingredients,
  (SELECT count(*) FROM kh_knowledge_source_mapping) AS mappings;
'@ | docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

本次只是建表，预期 7 个数量均为 `0`。之后可再次执行第 1 步；命令应成功，且不会创建重复表或写入记录。

## 4. 安全边界

- 本迁移仅新增目录和来源映射表及索引，不修改已有业务数据。
- 新动作、食材和菜谱默认 `quarantined` / `pending_review`；视频默认 `unverified` 且 `allowed_use = none`。
- 该迁移不创建或删除 Milvus 集合，不读写 MongoDB、Elasticsearch、Neo4j，也不运行数据导入。
- 如果任一步出现 SQL 错误，停止后续操作并保留完整错误；不要改用 `DROP`、`TRUNCATE` 或删除数据库的命令。
