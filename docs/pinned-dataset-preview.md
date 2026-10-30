# 固定版本数据只读预览

## 当前实施状态（2026-10-30）

非视频个人测试导入已完成。PostgreSQL 只读核对结果为：317 条动作、1,657 条中国食物成分记录均为 `active/approved`，食材计量基准为 `per_100g`；目录进度分别为 317 processed 和 1,657 processed / 333 skipped。动作知识文档已完成 317 条的多存储导入。当前数据库中动作媒体记录均未获批。

本阶段范围由用户限定为本地个人测试。许可状态和来源备注不能据此推定为公开、分发或商用授权。95 条 USDA 近似食材、238 条菜谱和 119 个份量 profile 仍未进入可用目录；视频作为最后扩充功能处理。

## 目的

`scripts/preview_pinned_datasets.py` 只从来源锁定清单中的 Git commit 读取指定 JSON 文件，验证文件 SHA-256，并生成统计和少量样例。该命令没有数据库连接或写入路径，也不请求视频、图片等媒体 URL。

目前固定的两个来源：

| 数据域 | 仓库 / commit | 白名单 JSON | 核查到的记录数 |
|---|---|---|---:|
| 健身动作 | `luisaraujoc/free-exercise-db-api` / `38c5670c3210f69268a0255bdb2cb3edcb596c46` | `data/exercises.json` | 317 个动作；593 个视频 URL，仅计数、不访问 |
| 饮食食材 | `Fission21/chisha` / `ac659028f37913d7f622f5598efd25957d696b2c` | `data/processed/foods.json` | 1,752 条 |
| 饮食菜谱 | 同上 | `data/processed/recipes.json` | 238 条 |
| 饮食份量参考 | 同上 | `data/processed/food_portions.json` | `profiles` 结构；仅供检查 |

版本、路径和预期 SHA-256 保存在 `config/fitness_dataset_sources.json`。锁定版本只保证可复现，不等于自动批准。当前实际导入使用了操作人员本机的已审阅锁定文件；该文件不提交到仓库。仓库默认锁未包含食材逐来源许可和计量基准映射，因此它不能重现本机批准的中国食材导入范围。动作视频仍为来源未核实状态；其他未批准或字段不完整的记录保持隔离。

2026-10-27 的固定版本核查得到：食材 1,752 条，其中 1,657 条标记为《中国食物成分表（第 6 版）》来源、95 条标记为 `usda-approx`；菜谱 238 条，其中 144 条的许可字段为 `Unlicense`、94 条许可字段缺失；份量参考有 119 个 profile。许可字段统计只反映 JSON 当前写入的内容，不等同于授权审核结论。

来源身份仍有待复核：`luisaraujoc/free-exercise-db-api` 的 README 快速开始部分把克隆地址指向 `amiinwani/free-exercise-db-with-videos`。该来源差异不改变本次已导入的个人测试范围；扩大用途前应先核清来源身份。它也不能作为视频权利或视频内容匹配的依据。

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

- 动作数据通过专用转换器检查并保留来源、字段状态和媒体引用；媒体许可与动作文字许可分别判断。
- 食材和菜谱由专用转换器执行重复、字段、单位、来源及引用检查；不能确认许可或计量基准的记录保持隔离。
- 报告中的视频 URL 数量只用于风险盘点；工具不会访问或输出视频 URL。
- dry-run 只会写本地预览报告，不会写 PostgreSQL、MongoDB、Elasticsearch、Milvus 或 Neo4j。
- 首次预览曾得到 4 个 JSON 文件、2,426 个输入条目且全部隔离；后续操作人员使用本机审阅锁将 317 条动作文字和 1,657 条中国食材列入个人测试批准范围。`accepted_records` 只表示格式/转换器接受，许可范围仍以锁定文件备注和记录级状态为准。

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

校验成功仅表示批准记录绑定到当前报告，且当前远程文件版本/大小/摘要与预览一致；不会执行正式导入。正式导入在创建数据库连接或写入前调用 `validate_reviewed_manifest`。更改锁文件后必须重新生成并审阅预览；本机许可锁和批准文件留在用户目录，不应提交到仓库。

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

当前仓库默认锁的 `metadata_license_status` 只代表数据集级元数据状态，不能替代食材和菜谱的记录级许可。仓库默认锁没有记录级映射；本机实际导入使用的已审阅锁记录了个人测试范围和计量基准。数据库核对显示 1,657 条中国食材为 `active/approved/per_100g`；95 条 USDA 食材和 238 条菜谱仍隔离，119 个份量 profile 未导入。未核实的来源不应仅为通过门禁而改为批准。导入重试须继续使用原本机锁、报告和批准文件；不得用仓库默认锁替代。

进度表按 PostgreSQL 目录、PostgreSQL 文档、MongoDB、Elasticsearch、Milvus 和 Neo4j 分别记录状态。当前动作导入的六个存储阶段均为 completed（317 条）；食材导入完成 PostgreSQL 目录阶段（1,657 条，333 条跳过）。食材知识文档尚未导入，避免将未经许可/计量审查的营养数据作为 RAG 权威依据。目录写入按来源版本和上游 ID 幂等；失败后使用同一锁定版本重跑会从已提交检查点继续。不要用旧的 `scripts/import_fitness_knowledge.py` 导入本数据集。
