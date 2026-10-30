# Knowledge Agent

基于 FastAPI 的知识库与健身管理应用，包含文档解析、RAG 检索问答、知识图谱、团队权限、健身档案、训练计划/打卡、饮食记录和拍照识餐。前端为原生 HTML/CSS/JavaScript。

## 技术栈

| 类别 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn（异步） |
| 关系库 | PostgreSQL（SQLAlchemy 2.0 async） |
| 文档库 | MongoDB（Beanie ODM） |
| 向量检索 | Milvus |
| 全文检索 | Elasticsearch 8（IK 分词） |
| 知识图谱 | Neo4j |
| 消息队列 | RabbitMQ（aio_pika） |
| 对象存储 | RustFS（S3 兼容，预签名 URL） |
| LLM | 通义千问（Qwen，OpenAI 兼容接口）+ LangChain / LangGraph |
| Embedding / Rerank | 独立 embedding 模型 + rerank 服务 |
| 语音 | 腾讯云 ASR / TTS（WebSocket 流式） |
| 联网搜索 | BochaAI（知识库相关性不足时兜底） |
| 鉴权 | JWT（access + refresh）+ bcrypt |
| 缓存 | Redis |

## 项目结构

```
core/      config.py(统一 Settings)、database.py(统一 PG engine/Base)、security.py(鉴权依赖)
models/    纯 ORM：user、document、graph_document、content(Beanie)、team、permission、review、chat
schemas/   Pydantic DTO：user、document、content、graph、search、team、permission、review、chat
api/       全部路由：user、role、team、permission、review、document、mongo、file、publish、
           es、milvus、neo4j、ai、chat、voice
services/  document_service、content_service、graph_service、llm_service
clients/   rustfs、es_client、milvus_client、neo4j_client、rabbitmq/、tencent_speech、web_search
utils/     auth、hashing、split_file、parsers/(pdf、docx、xlsx、epub 等)
scripts/   本机启动、基础设施检查、数据导入、OpenAPI 导出及测试脚本
migrations/ PostgreSQL 增量 SQL 迁移
frontend/  原生 HTML/CSS/JavaScript 前端与本机静态服务器
main.py    路由挂载 + lifespan 初始化（RustFS、Mongo、Redis、Milvus、MQ、ES、Neo4j）
```

## 核心流程

```
上传文件(/restfs) → 解析切片 → 保存草稿(PG + Mongo)
→ 发布(/knowledge_doc) → RabbitMQ 三条队列:
     INDEX        → Elasticsearch 全文索引
     BY_DOC_IDS   → Embedding → Milvus 向量入库
     BUILD_BY_DOC_IDS → LLM 抽取实体关系 → Neo4j 知识图谱
→ 问答(/ai、/chat) → ES + Milvus(+ 图谱) 混合检索 → Rerank → LLM 生成
     知识库最高相关分低于 WEB_SEARCH_MIN_SCORE 时联网搜索兜底
```

各流程结果回写 `kh_document` 的 flow 状态字段，便于追踪发布进度。

## 路由前缀

| 模块 | 前缀 | 说明 |
|---|---|---|
| 认证/用户 | `/user`、`/role` | 登录、JWT、用户与角色 |
| 组织 | `/team`、`/permission` | 团队、权限 |
| 内容/发布 | `/knowledge_doc`、`/pg`、`/mongo` | 文档 CRUD、解析状态、审核后发布 |
| 文件 | `/restfs` | 上传/下载/预签名 URL |
| 检索 | `/es`、`/milvus`、`/neo4j` | 全文 / 向量 / 图谱 |
| AI | `/ai`、`/chat` | 问答调用、会话管理 |
| 审核 | `/review` | 内容审核流 |
| 语音 | `/voice` | TTS(HTTP/WS)、STT(WS)，WS 鉴权走 query token |
| 健身/饮食 | `/fitness`、`/training`、`/nutrition`、`/catalog` | 健身档案、训练计划/打卡、饮食记录与目录 |
| 知识维护 | `/admin/knowledge-maintenance` | 知识清理预览、执行和校验 |

后端同时挂载 `/api/voice` 别名，以兼容反向代理下的 WebSocket 路径。

## 本机快速开始

当前推荐的运行方式是 Docker 启动中间件，本机运行前后端。仓库没有 `.env.example`；先准备本机自己的 `.env`，再按[本机开发运行说明](docs/local-development.md)安装依赖并配置连接。不要把 `.env` 提交到 Git。

项目需要 Python 3.11、Node.js、Docker Desktop 和 Docker Compose v2。Windows 下可在项目根目录运行：

```powershell
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/run_local_dev.py
```

正常启动后，前端地址为 `http://localhost:5173`，后端为 `http://localhost:8000`。Swagger/OpenAPI 描述目前不完整，不能作为完整的登录、流式问答或鉴权验收依据。

本机启动配置默认不启动 Redis；它仅用于近期聊天上下文缓存，未连接时会回退到 PostgreSQL。需要测试缓存时见本机开发说明。

> Compose 是本机开发配置，包含开发默认值并映射多个中间件端口。不要将它直接用于公网生产部署，也不要把 `scripts/run_local_dev.py` 用于云服务器。

### 主要环境变量（.env）

| 分组 | 变量 | 说明 |
|---|---|---|
| LLM | `QWEN_API_KEY` `QWEN_BASE_URL` `QWEN_MODEL_NAME` | 通义千问 |
| | `EMBEDDINGS_MODEL_NAME` `RERANK_MODEL_NAME` `RERANK_URL` | 嵌入 / 重排 |
| 存储 | `POSTGRES_*` `MONGO_URI` `DB_NAME` | PG / Mongo |
| | `ES_HOST` `ES_BASIC_AUTH` `INDEX_NAME` | Elasticsearch |
| | `MILVUS_URL` `MILVUS_TOKEN` `COLLECTION_NAME` `DIMENSIONS` | Milvus |
| | `NEO4J_URI` `NEO4J_USER` `NEO4J_PASSWORD` | Neo4j |
| | `RUSTFS_ENDPOINT` `RUSTFS_ACCESS_KEY` `RUSTFS_SECRET_KEY` `RUSTFS_BUCKET` | 对象存储 |
| MQ | `RABBITMQ_URL` `QUEUE_INDEX` `QUEUE_RAG` `QUEUE_KG` | RabbitMQ |
| 鉴权 | `JWT_SECRET_KEY`（生产必改）`JWT_EXPIRE_MINUTES` | JWT |
| 搜索 | `BOCHAAI_KEY` `WEB_SEARCH_MIN_SCORE` `WEB_SEARCH_COUNT` | 联网兜底 |
| 语音 | `TENCENT_SECRET_ID` `TENCENT_SECRET_KEY` `TENCENT_APP_ID` | 留空时语音接口返回明确错误 |

## 开发辅助脚本

```bash
python scripts/check_infra_state.py     # 检查各中间件连通性
python scripts/test_fullchain_http.py   # 发布→MQ→ES/Milvus/KG 全链路测试
python scripts/test_regression.py       # 回归测试
python scripts/dump_openapi.py          # 导出 OpenAPI JSON
python scripts/test_chat.py             # 需要本地服务
python scripts/test_voice.py            # 需要本地语音服务配置
```

## 相关文档

- `docs/deployment-tencent-cloud.md` — 腾讯云部署指南
- `docs/llm-private-deployment.md` — LLM 私有化部署
- 前端目录：`frontend/`（原生 HTML/CSS/JavaScript）

## 部署状态与未完成项

当前验收面向本机个人测试。项目尚未达到直接公网部署条件，主要缺口包括：

- Compose、配置模块和本地启动脚本仍有开发凭据或默认值；需轮换已写入代码的凭据并改为外部 Secret 注入。
- Compose 会向宿主机发布多个数据库、检索和管理端口；尚无专用生产 Compose 和限制公网访问的配置。
- 前端默认 API 地址为 `http://localhost:8000`（页面可改本机连接地址），静态服务器只监听回环地址；尚无生产 API 基址、静态托管、HTTPS 反向代理及生产 CORS 配置。
- PostgreSQL 增量迁移尚未接入版本台账或自动部署流程；生产备份恢复演练、监控告警和容量测试也未完成。
- 健身与饮食数据只按本地个人测试范围验收；部分食材/菜谱/份量及所有图片、视频仍未获批。

部署事实、当前阻断项和数据范围见[腾讯云部署与生产准备说明](docs/deployment-tencent-cloud.md)。在 P0 项完成前，不要将当前 Compose 直接用于公网服务器。
