# 健身知识库数据导入操作说明

本文说明如何把本地健身动作数据或 FitKG-CN 标注数据转换为项目现有知识文档，并经现有流程写入 PostgreSQL、MongoDB、Elasticsearch、Milvus 和 Neo4j。

> **默认安全模式是 dry-run。** 不加 `--apply` 时只读取本地 JSON、转换和统计数据，不导入应用数据库。本文本次验证只运行 dry-run，没有写入数据库。

## 1. 数据准备

### FitKG-CN

准备仓库提供的 JSON 分区文件，例如：

- `data/fitkg-cn/train.json`
- `data/fitkg-cn/dev.json`（可选）

转换器按 FitKG-CN 的 token/entity/relation 标注格式读取数据；实体结束位置按包含式处理。无效实体跨度或关系会计数并跳过，不会伪造关系。

本机曾检查到的文件位置如下；如果你将文件放在其他位置，运行命令时替换成自己的路径：

```text
C:\Temp\fitness-dataset-review\fitkg\NYN921-FitKG-CN-41b1142\data\fitkg-cn\train.json
C:\Temp\fitness-dataset-review\fitkg\NYN921-FitKG-CN-41b1142\data\fitkg-cn\dev.json
```

### exercises-dataset 动作库

脚本也支持 `--exercises-json`。每条记录应至少包含动作名称；可选字段包括分类、身体部位、器械、目标/辅助肌群和动作说明。名称或说明有多语言版本时优先中文、没有中文时回退英文。图片/GIF/视频 URL 不会被导入文本。

导入前应检查数据集及媒体资源各自的许可证、来源和再分发要求；不要因为文本许可而默认媒体也可复用。当前工作区没有检测到该动作库 JSON，因此本次只对本地 FitKG-CN 执行验证。

## 2. 环境准备

在项目根目录打开 PowerShell，激活项目虚拟环境（若尚未激活）：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 阻止激活脚本，也可直接使用 `\.venv\Scripts\python.exe` 运行下面命令。

## 3. 先运行 dry-run（不会连接数据库）

```powershell
.\.venv\Scripts\python.exe scripts/import_fitness_knowledge.py `
  --fitkg-train 'C:\Temp\fitness-dataset-review\fitkg\NYN921-FitKG-CN-41b1142\data\fitkg-cn\train.json' `
  --fitkg-dev 'C:\Temp\fitness-dataset-review\fitkg\NYN921-FitKG-CN-41b1142\data\fitkg-cn\dev.json'
```

先检查每个文件的输入记录数、有效/重复/异常数量、生成文档数，以及图谱实体和关系数量。也可以加 `--max-docs 2` 只预览前两个知识文档的导入规模；这仍然是 dry-run。

还可以选动作库文件一并预览：

```powershell
.\.venv\Scripts\python.exe scripts/import_fitness_knowledge.py `
  --exercises-json 'D:\datasets\exercises.json' `
  --fitkg-train 'D:\datasets\fitkg-cn\train.json'
```

默认每 25 个动作记录合并成一个文档、每 100 条 FitKG 记录合并成一个文档，可通过 `--exercise-group-size` 和 `--fitkg-group-size` 调整。

## 4. 正式导入前的检查

正式执行前必须确认：

1. 数据来源和许可证允许当前用途，内容适合面向用户展示；
2. dry-run 的记录统计、抽样文本、分组大小符合预期；
3. `.env` 中的数据库连接指向**预期的开发/测试环境**，不要误连生产库；
4. PostgreSQL 中存在 `--author-id` 指定的用户；
5. PostgreSQL 图谱元数据表、MongoDB、ES 索引、Milvus 集合、Neo4j 已按项目当前方式准备好；
6. Milvus 集合需要含 `vector`、`title`、`content_id`、`content` 字段，且向量维度与 `.env` 的 `DIMENSIONS` 一致。

脚本预检查只读取/验证上述资源，不会建表、建索引或重建 Milvus 集合。任一检查失败会中止。

## 5. 正式导入命令（需人工确认后再执行）

以下只是操作模板，本次没有执行。把用户 ID 和数据路径换成自己的值；正式模式会写入所有目标存储：

```powershell
.\.venv\Scripts\python.exe scripts/import_fitness_knowledge.py `
  --fitkg-train 'D:\datasets\fitkg-cn\train.json' `
  --fitkg-dev 'D:\datasets\fitkg-cn\dev.json' `
  --author-id 1 `
  --apply
```

动作库同样可添加 `--exercises-json 'D:\datasets\exercises.json'`。如需先做少量正式试导入，可加 `--max-docs 2`，但**带 `--apply` 的命令依然会实际写数据库**。

## 6. 幂等和断点续跑

- 正式导入时，脚本在用户主目录创建 `~/.knowledge-agent/fitness-knowledge-import-manifest.json`，记录输入内容对应的 PostgreSQL 文档 ID。
- 相同文件内容和分组设置重新运行时，会复用清单中的文档 ID，并更新该文档在各存储中的内容；Milvus 只删除/重建该文档 ID 对应的 `{doc_id}-*` 向量，不删除其他文档或整个集合。
- 导入中断后，可用同样参数重跑继续处理；不要随意删除或手工编辑清单。更换数据内容或分组大小会生成新的导入键和新文档。
- 多个数据库没有跨库事务。若某一阶段失败，错误会标出阶段和文档 ID；修复原因后以同样参数重试。

## 7. 重要边界

本工具将知识文本送入项目现有 RAG 链路：MongoDB 保存全文，Elasticsearch 提供关键词检索，Milvus 保存切块向量供语义检索，PostgreSQL 保存文档状态/权限元数据，Neo4j 和 PostgreSQL 图谱元数据保存抽取出的实体关系。脚本不会清空用户数据，也不会创建或替换 Milvus 主集合。

FitKG-CN 的实体关系属于数据集标注，不代表经过医学或运动科学审核的个性化训练建议；对外使用前仍需做数据抽样、事实核验和健康安全审查。
