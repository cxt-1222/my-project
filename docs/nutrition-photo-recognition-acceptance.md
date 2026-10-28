# 阶段 7.2：拍照识餐配置与验收记录

本功能会把上传图片发送到你配置的视觉模型服务，并保存到 RustFS 私有对象存储。模型返回的份量和营养值都是估算值；只有用户核对并点击“确认并保存”后，才会建立营养记录。

## 1. 配置视觉模型

当前开发环境已验收的视觉模型配置如下，沿用项目现有公司的百炼 API Key 和 Base URL；不要将 API Key 写入文档或提交到 Git：

```dotenv
QWEN_VISION_MODEL_NAME=qwen3.7-plus
```

留空或未配置时，应用仍可使用手动营养记录；拍照识别接口会返回明确的“尚未配置”错误。不要把 API Key 发到聊天或提交到 Git。

## 2. 执行数据库迁移

PowerShell：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'

$pgUser = (docker compose exec postgres printenv POSTGRES_USER).Trim()
$pgDb = (docker compose exec postgres printenv POSTGRES_DB).Trim()
docker compose exec -T postgres psql -U $pgUser -d $pgDb -c "SELECT to_regclass('public.kh_user') AS user_table, to_regclass('public.kh_nutrition_record') AS nutrition_record_table;"

docker compose cp .\migrations\20261023_01_create_kh_nutrition_photo.sql postgres:/tmp/20261023_01_create_kh_nutrition_photo.sql

docker compose exec -T postgres psql -U $pgUser -d $pgDb -f /tmp/20261023_01_create_kh_nutrition_photo.sql

docker compose exec -T postgres psql -U $pgUser -d $pgDb -c "SELECT to_regclass('public.kh_nutrition_photo');"
docker compose exec -T postgres psql -U $pgUser -d $pgDb -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'kh_nutrition_record' AND column_name IN ('source', 'photo_id') ORDER BY column_name;"
```

应看到 `kh_nutrition_photo`，以及 `photo_id`、`source` 两列。迁移仅增加照片预览表、索引和营养记录来源列；原手动记录默认标为 `manual`，不会删除或重写。

配置 `.env` 并完成迁移后，重建后端：

```powershell
docker compose up -d --build aiagent-end
```

## 3. 页面验收

1. 登录后打开“营养记录”，确认页面说明图片会发送给视觉模型并保存到私有对象存储。
2. 上传一张 JPG、PNG 或 WebP 餐食图片。识别过程中应显示“尚未保存营养记录”。
3. 识别完成后，应显示图片及可编辑的食物、餐次、份量、单位、热量、蛋白质、碳水和脂肪；标记为估算值。
   图片通过带登录令牌的后端代理读取；浏览器网络请求应为 `GET /nutrition/photos/{preview_id}/image`，不能直接暴露 RustFS 地址或预签名地址。
4. 在不确认的情况下刷新页面。待确认预览应恢复，营养记录列表和每日合计不得因预览产生变化。
5. 修改至少一个食物名称或数值，点击“确认并保存”。列表应出现修改后的记录，每日合计应按确认值更新，并显示“图片识别后确认”。
6. 再次请求同一预览的确认接口应返回 `409`，不能生成重复记录。
7. 重新识别一张图片后点击“取消本次识别”。预览应消失，后端不应创建营养记录。
8. 测试 GIF、伪造 MIME 的非图片内容和超过 10 MB 的图片：分别应被拒绝，不创建识别预览或营养记录。
9. 使用另一个账号请求前一账号的预览 ID，应返回 `404`；第二个账号不得看到其图片、预览项目或营养记录。
10. 临时清空 `QWEN_VISION_MODEL_NAME` 后重启 API 再上传图片：应显示明确配置错误，RustFS 和数据库不得产生该请求的预览记录。

## 4. API 验收（可选）

- `POST /nutrition/photos/preview`：multipart 上传 `file`，返回 `id`、`status=preview`、`image_url`、`is_estimate=true` 和可编辑 `items`；不创建营养记录。
- `GET /nutrition/photos/{preview_id}`：仅所有者可读，用于恢复待确认预览。
- `GET /nutrition/photos/{preview_id}/image`：携带登录令牌，仅所有者可读取；跨账号请求返回 `404`，不得触发 RustFS 对象读取。
- `POST /nutrition/photos/{preview_id}/confirm`：提交 `date` 和修正后的 `items`，原子创建营养记录并确认预览。
- `DELETE /nutrition/photos/{preview_id}`：取消尚未确认的预览并清理其图片；其他账号返回 `404`，已确认预览返回 `409`。
- `GET /nutrition/daily?date=YYYY-MM-DD`：确认保存后可看到关联后的营养记录和更新的合计。

视觉模型可能识错食物或估错份量，结果不得直接用于医疗或精确膳食判断。手动营养记录功能不依赖视觉模型配置。

## 5. 已完成的核心验收（2026-10-23）

- 用户确认使用 `qwen3.7-plus` 成功获取餐食识别预览。
- 视觉识别沿用当前项目公司的 `QWEN_API_KEY` 和 `QWEN_BASE_URL`；普通聊天模型配置保持不变。
- 本记录仅确认当时核心识别预览通过；本轮补充的取消/确认状态保护和边界自动化测试见下节。

## 6. 本轮完善记录（2026-10-26）

- 预览取消与确认都通过 PostgreSQL 行锁读取并变更预览状态，确保同一预览只能有一个终态获胜；确认成功后取消返回 `409`，取消成功后确认不再创建记录。
- 取消先持久化 `cancelled` 状态再清理对象。若对象存储暂时失败，接口返回明确错误；重复取消可重试对象清理，不会重复改变状态或创建营养记录。
- 自动化测试覆盖 GIF、伪造图片内容、超 10 MB 文件在调用视觉模型/存储前被拒绝；跨账号读取图片、确认和取消均返回 `404`，且不读取或删除对象；已确认预览不可取消、重复确认不可重复写入。
- 本轮未连接或修改用户数据库，也未重新执行照片表迁移。阶段 9 仍负责系统级集成、部署和回归，不再把本节已覆盖的边界用例视为尚未实现。

本轮代码和自动化测试已完成，待用户按第 3 节确认正常预览、编辑后确认、取消流程；核心图片识别此前已由用户验收。
