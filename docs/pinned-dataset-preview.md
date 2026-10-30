# 固定版本数据只读预览

## 目的

`scripts/preview_pinned_datasets.py` 只从来源锁定清单中的 Git commit 读取指定 JSON 文件，验证文件 SHA-256，并生成统计和少量样例。该命令没有数据库连接或写入路径，也不请求视频、图片等媒体 URL。

目前固定的两个来源：

| 数据域 | 仓库 / commit | 白名单 JSON | 核查到的记录数 |
|---|---|---|---:|
| 健身动作 | `luisaraujoc/free-exercise-db-api` / `38c5670c3210f69268a0255bdb2cb3edcb596c46` | `data/exercises.json` | 317 个动作；593 个视频 URL，仅计数、不访问 |
| 饮食食材 | `Fission21/chisha` / `ac659028f37913d7f622f5598efd25957d696b2c` | `data/processed/foods.json` | 1,752 条 |
| 饮食菜谱 | 同上 | `data/processed/recipes.json` | 238 条 |
| 饮食份量参考 | 同上 | `data/processed/food_portions.json` | `profiles` 结构；仅供检查 |

版本、路径和预期 SHA-256 保存在 `config/fitness_dataset_sources.json`。来源许可目前仍标为待审核；锁定版本不等于批准导入。动作视频仍为来源未核实状态。动作、食材和菜谱均有专用转换器，但许可、字段缺失或数据质量未通过的记录仍保持隔离，不会声称可导入。

2026-10-27 的固定版本核查得到：食材 1,752 条，其中 1,657 条标记为《中国食物成分表（第 6 版）》来源、95 条标记为 `usda-approx`；菜谱 238 条，其中 144 条的许可字段为 `Unlicense`、94 条许可字段缺失；份量参考有 119 个 profile。许可字段统计只反映 JSON 当前写入的内容，不等同于授权审核结论。

来源身份仍需人工确认：`luisaraujoc/free-exercise-db-api` 的 README 快速开始部分把克隆地址指向 `amiinwani/free-exercise-db-with-videos`。本项目当前锁定的是用户此前指定且在该固定提交中实际含有 `data/exercises.json` 的 `luisaraujoc` 仓库；在来源清单最终确认前，不应把动作数据或视频作为已批准内容开放。

## 运行

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/preview_pinned_datasets.py
```

默认报告写到用户目录下的 `.knowledge-agent\fitness-dataset-preview.json`。也可以指定输出路径或缩减样例数：

```powershell
.\.venv\Scripts\python.exe scripts/preview_pinned_datasets.py `
  --output "$HOME\Desktop\fitness-dataset-preview.json" `
  --samples 2
```

如果上游不可用、HTTP 状态异常、文件超限、JSON 格式错误或 SHA-256 与锁定值不符，命令会失败且不生成新的完整预览报告。更新上游版本时，必须重新固定 commit、复核每个允许路径及摘要；不要改用 `main`、`master` 或 `latest`。

## 预览结果含义

- 动作数据使用当前动作转换器输出接受、重复、无效数量及标准化样例。动作许可未批准时，接受的文字记录仍列为隔离。
- 食材、菜谱和份量文件目前只有 JSON/基础字段结构检查；重复检测和标准化尚未实现，记录全部隔离。
- 报告中的视频 URL 数量只用于风险盘点；工具不会访问或输出视频 URL。
- dry-run 只会写本地预览报告，不会写 PostgreSQL、MongoDB、Elasticsearch、Milvus 或 Neo4j。
- 本次真实远程 dry-run 汇总：4 个 JSON 文件、2,426 个输入条目、动作转换器接受 317 条；食材和菜谱由专用转换器处理。由于来源许可仍待审核，2,426 条全部处于隔离状态。`accepted_records` 表示格式/转换器接受，不表示已获准导入。

## 正式导入前的人工审阅绑定

当前版本的预览报告包含完整文件清单（数据集、仓库、commit、锁定日期、相对路径、字节数和 SHA-256），以及来源锁定文件自身的 SHA-256。若报告、许可状态、commit、白名单路径或来源锁有变化，必须重新生成并重新审阅。

人工审阅批准记录是单独的 JSON 文件，不应提交到仓库。其格式如下；只能在有可审计许可依据且完成数据/媒体范围审查后填写，不能为了让命令通过而直接复制模板：

```json
{
  "schema_version": 1,
  "approved": true,
  "reviewer": "实际审查人",
  "reviewed_at": "2026-10-27T12:00:00+08:00",
  "preview_report_sha256": "预览报告文件的 SHA-256"
}
```

重新验证命令只访问锁定清单内的 JSON 文件，不访问数据库或媒体 URL：

```powershell
.\.venv\Scripts\python.exe scripts/verify_pinned_dataset_review.py `
  --report "$HOME\.knowledge-agent\fitness-dataset-preview.json" `
  --approval "$HOME\.knowledge-agent\fitness-dataset-approval.json"
```

校验成功仅表示批准记录绑定到当前报告，且当前远程文件版本/大小/摘要与预览一致；不会执行正式导入。后续正式导入实现必须在创建数据库连接或写入前调用 `validate_reviewed_manifest`。当前来源锁为 `pending_review`，所以现阶段运行此命令应拒绝，直到许可审查真实完成并更新来源锁、重新预览和审阅。

## 目录正式导入（阶段 3.2）

正式目录导入还需要一次独立增量迁移。它只创建进度表，不改变前一迁移或现有业务表：

```powershell
docker compose cp .\migrations\20261027_02_create_dataset_import_progress.sql postgres:/tmp/dataset-import-progress.sql
docker compose exec postgres sh -lc 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/dataset-import-progress.sql'
```

正式导入命令默认只构建导入计划；只有同时满足人工审阅批准、许可状态批准、报告和来源锁一致、远程 JSON 摘要复验通过，并显式传入 `--apply`，才会连接 PostgreSQL 写入目录：

```powershell
.\.venv\Scripts\python.exe scripts/import_pinned_datasets.py `
  --report "$HOME\.knowledge-agent\fitness-dataset-preview.json" `
  --approval "$HOME\.knowledge-agent\fitness-dataset-approval.json" `
  --apply
```

当前 `config/fitness_dataset_sources.json` 将仓库级 `metadata_license_status` 标为 `approved`，但这不代表每条饮食记录已获准。食材的 `record_license_by_source`、`nutrition_basis_by_source` 和菜谱的 `recipe_license_by_source` 映射仍为空；最新只读预览中 1,752 条食材、238 条菜谱和 119 个份量 profile 仍处于隔离状态。食材许可和计量基准必须按来源记录经审查的结论，菜谱许可也必须按来源记录；不能为了通过门禁而直接改成 `approved`。缺少许可、计量依据、字段或精确食材匹配的记录不会写入用户可见目录。正式导入仍须使用绑定当前预览报告的人工审阅批准记录。

导入进度表针对 PostgreSQL 目录、PostgreSQL 文档、MongoDB、Elasticsearch、Milvus、Neo4j 分别记录状态。3.2 只完成 `postgres_catalog`；其余存储状态仍为 `pending`，待 3.3 的知识文档及现有检索链路实现。目录写入按数据集版本和上游 ID 幂等，失败后使用同一锁定版本重跑会从最近一个已提交的目录检查点继续。不要用旧的 `scripts/import_fitness_knowledge.py` 导入本数据集，它不是本目录导入流程。
