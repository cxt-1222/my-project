# 阶段 7.1：手动营养记录迁移与验收

本步骤只适用于手动营养记录 MVP。当前功能不包含拍照识餐、自动估算或营养目标。

## 1. 执行数据库迁移

在 PowerShell 中运行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'

docker compose cp .\migrations\20261022_03_create_kh_nutrition_record.sql postgres:/tmp/20261022_03_create_kh_nutrition_record.sql

$pgUser = (docker compose exec postgres printenv POSTGRES_USER).Trim()
$pgDb = (docker compose exec postgres printenv POSTGRES_DB).Trim()
docker compose exec -T postgres psql -U $pgUser -d $pgDb -f /tmp/20261022_03_create_kh_nutrition_record.sql
```

成功后应看到 `CREATE TABLE` 和 `CREATE INDEX`（若表或索引已存在，可能显示跳过提示）。确认数据库中有表：

```powershell
docker compose exec -T postgres psql -U $pgUser -d $pgDb -c "SELECT to_regclass('public.kh_nutrition_record');"
```

结果应为 `kh_nutrition_record`。该迁移只创建新表和索引，不会清理或改写现有数据。

如果后端运行在 Docker Compose 中，迁移后重启 API：

```powershell
docker compose up -d --build aiagent-end
```

如果后端是本机运行，重启本机 FastAPI 进程即可。不要在数据库未备份或连错环境时执行迁移。

## 2. 页面验收

1. 登录应用，打开左侧 **营养记录** 页面。
2. 点击 **回到今天**：当日无记录时，热量、蛋白质、碳水、脂肪应均为 `0`，记录列表显示空状态。
3. 添加一条早餐：食物“燕麦”、份量 `50`、单位 `g`、热量 `190`、蛋白质 `6.5`、碳水 `32`、脂肪 `3.5`。保存后记录应出现，汇总应显示同样数值。
4. 编辑该记录，把热量改为 `200`。保存后列表显示 `200 kcal`，每日热量合计也变为 `200 kcal`。
5. 删除该记录。列表恢复空状态，四项每日合计恢复为 `0`。
6. 选择其他日期：只能看到所选日期的记录，切回今天仍能看到今天的数据（若此前未删除）。
7. 使用另一个账号登录并选择同一天：应只看到另一个账号自己的记录；不能通过当前账号的页面读取或修改前一账号的数据。

所有数值都是用户手动输入并保存的记录，不代表系统校验过营养准确性。跨账号验证最好在测试账号间进行，不要用真实隐私数据。

## 3. API 检查（可选）

- `GET /nutrition/daily?date=YYYY-MM-DD`：返回 `records` 和四项 `totals`。
- `POST /nutrition/records`：创建一条记录。
- `PUT /nutrition/records/{record_id}`：修改当前账号拥有的记录。
- `DELETE /nutrition/records/{record_id}`：删除当前账号拥有的记录，成功返回 `204`。

未登录请求应被拒绝；对其他账号记录的修改或删除应返回 `404`。请求体不能指定 `user_id`。
