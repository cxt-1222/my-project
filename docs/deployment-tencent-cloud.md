# 腾讯云部署与生产准备说明

> 状态核对日期：2026-10-30
> 当前结论：项目已完成本机开发和个人测试库验证，但仓库当前配置还不是可直接部署到公网的生产方案。本指南以实际代码和 Compose 为准；生产阻断项在文末单独列出。

## 当前项目结构

项目目前由原生 HTML/CSS/JavaScript 前端、FastAPI 后端和 Docker Compose 中间件组成：

| 部分 | 当前实现 |
|---|---|
| 前端 | `frontend/` 原生静态文件；`frontend/server.js` 仅监听 `127.0.0.1:5173` |
| 后端 | FastAPI；`Dockerfile.app` 构建应用镜像，Compose 服务名为 `aiagent-end`，容器端口为 `8000` |
| 数据与检索 | PostgreSQL、MongoDB、Elasticsearch、Milvus、Neo4j |
| 可选缓存 | Redis 用于近期聊天上下文缓存；不可用时应用会退回 PostgreSQL |
| 队列与对象存储 | RabbitMQ、RustFS；Milvus 另依赖 etcd 和 MinIO |
| Elasticsearch 镜像 | 根目录 `Dockerfile` 用于 Elasticsearch 8.17.0 和 IK 插件，不是 Python 应用镜像 |
| 本地入口 | PyCharm 运行配置 `.run/Knowledge_Agent_Local_Dev.run.xml` 或 `scripts/run_local_dev.py` |

Compose 还包含 MySQL 和 pgAdmin、RedisInsight、Mongo Express、Kibana 等开发/排障服务。当前 Compose 将多个应用及中间件端口映射到宿主机；它适合本地测试，不应原样用于公网服务器。

## 本机运行与验收

以下是仓库当前支持的开发方式，不代表生产部署步骤。详细操作见[本机开发运行说明](local-development.md)。

环境要求：Windows PowerShell、Python 3.11、Node.js、Docker Desktop 和 Docker Compose v2。项目根目录需要本机自己的 `.env`；仓库没有 `.env.example`，不要把真实密钥粘贴到聊天、文档或 Git。

首次创建 Python 环境并安装依赖：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

推荐使用 PyCharm 的 `Knowledge Agent - Local Dev` 运行配置。也可以在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts/run_local_dev.py
```

脚本会启动本地测试所需的 Docker 基础设施、前端和带自动重载的 FastAPI。正常启动后：

- 前端：`http://localhost:5173`
- 后端文档页：`http://localhost:8000/docs`

停止本机应用后，基础设施容器会继续运行。检查容器状态可运行 `docker compose ps`；基础设施连通性可运行 `.\.venv\Scripts\python.exe scripts/check_infra_state.py`。Swagger 页面和 OpenAPI 描述目前不完整，特别是登录、流式问答和部分鉴权流程；不能只凭 `/docs` 页面可打开就判定功能验收通过，应以实际前端流程和项目测试为准。

本机开发启动脚本会覆盖若干中间件连接地址和开发连接参数。因此它只适用于本机测试数据，不能用于连接共享库或生产库。不要在云服务器上运行该脚本。

当前本机启动器不会启动 Redis；Redis 不可用时聊天缓存会退回 PostgreSQL。如需单独测试缓存，可运行 `docker compose up -d redis`。

## 数据库表与迁移

应用启动时会连接基础设施，但不会自动把所有新增 SQL 迁移应用到 PostgreSQL。基础表的创建入口为管理员保护的 `/pg/create_table`；已存在的表不会因为 `create_all` 自动补齐新增字段。

增量 SQL 位于 `migrations/`，文件名带日期，应在备份后按文件名顺序人工核对并执行。`scripts/migrate_add_parse_status.sql` 是单独的文档处理状态迁移。仓库尚无统一迁移工具、迁移版本台账或自动回滚机制，因此生产数据库升级流程仍未完成。不要在公网环境中用 Swagger 临时尝试建表或迁移。

严禁对需要保留数据的数据库调用 `/pg/drop_table`，也不要使用 `docker compose down -v`；后者会删除 Compose 数据卷。

## 当前健身与饮食数据范围

当前数据导入结果属于用户限定的本地个人测试范围，不能据此推定为公开发布或商业授权：

- 317 条动作文字已完成目录及知识检索存储导入。
- 1,657 条中国食物成分记录已导入本地结构化目录，计量基准为每 100 克。
- 95 条 USDA 近似食材、238 条菜谱和 119 个份量参考仍未启用或处于隔离状态。
- 动作视频和图片没有获批；视频 URL 未请求、下载或展示，按用户要求留作最后扩充。

部署或迁移数据前，请查看[非视频数据验收记录](fitness-nutrition-dataset-acceptance.md)和[数据许可审查记录](dataset-license-review.md)。不要把本机批准文件或个人测试数据库直接复制到公网环境。

## 腾讯云公网部署阻断项

下表是当前代码核对出的缺口。所有 P0 项完成前，不应按旧版部署指南将应用或中间件端口暴露到公网。

| 级别 | 缺口与当前证据 | 完成部署前需要补齐 |
|---|---|---|
| P0 | **密钥和默认凭据**：Compose、配置模块和本地启动脚本仍存在开发凭据默认值；配置中还存在静态第三方 API 密钥回退值。仓库没有 `.env.example` 或生产密钥管理方案。 | 轮换已写入代码/配置的凭据；移除密钥和弱默认值，改为缺少即启动失败；通过云端 Secret 管理注入生产密钥；确认历史 Git 中不再包含有效凭据。 |
| P0 | **网络暴露面**：Compose 将 PostgreSQL、MongoDB、RabbitMQ、Elasticsearch、Milvus、Neo4j、对象存储和管理页面等多个端口映射到宿主机。 | 新建独立生产 Compose；应用仅通过受控入口对外；数据库、向量库和管理服务仅在私有网络可达，不发布公网端口；安全组只开放确有需要的入口。 |
| P0 | **前端发布与 API 地址**：当前静态服务器只绑定回环地址；前端默认 API 地址是 `http://localhost:8000`，面向访问者时会指向访问者自己的电脑。 | 增加可配置的生产 API 基址；准备生产静态文件服务和 HTTPS 反向代理；配置 HTTP 到 HTTPS、SSE 流式响应及 WebSocket 转发；将浏览器实际来源纳入 CORS 配置或采用验证过的同源部署。 |
| P0 | **环境配置**：应用读取项目 `.env`，但仓库没有可安全复制的环境变量模板；Compose 也混有开发默认值。 | 提供不含秘密的环境变量模板和生产配置校验；区分本机、测试、生产环境；禁止生产配置回退到开发默认口令。 |
| P1 | **数据库迁移**：迁移为分散 SQL 文件，未集成迁移版本记录、自动顺序执行或回滚流程。 | 设计并演练可审计的迁移流程；先备份，再在预发布库验证；记录已执行版本和回滚/恢复方法。 |
| P1 | **API 安全与验收**：OpenAPI/Swagger 不完整；路由包含管理和基础设施操作，不能把文档页可执行等同于生产鉴权审计。 | 审查每个路由的认证、授权、限流和错误输出；对流式、WebSocket、文件上传下载及管理员操作补充可重复的集成验收。 |
| P1 | **运维能力**：仓库没有已验证的生产备份/恢复演练、监控告警、容量基线或高可用方案；Compose 也使用了未固定版本的部分镜像标签。 | 建立多存储一致性备份和恢复演练；配置磁盘、内存、队列积压、外部模型失败等监控告警；固定镜像版本并做资源与负载测试。 |
| P1 | **数据授权范围**：当前验收仅针对本地个人测试数据。部分食材、菜谱、份量和所有媒体仍未批准。 | 若部署会向他人开放，先重新审查每类数据的来源、许可证和允许用途；未审查的数据继续排除，视频维持最后扩充。 |

## 后续生产部署顺序

生产部署工程完成后，再按以下顺序形成可执行的腾讯云操作手册：

1. 为生产环境建立单独的 Compose、环境变量模板和 Secret 注入方式，并固定容器镜像版本。
2. 完成前端 API 地址、HTTPS 反向代理、CORS、SSE 和 WebSocket 配置。
3. 配置只开放必要入口的云安全组和主机防火墙，确认中间件端口无法从公网访问。
4. 在备份后的预发布数据库应用迁移，初始化检索索引/集合，并确认管理员账号和权限。
5. 执行登录、文档发布、检索问答、训练/饮食功能、流式响应、文件处理和权限隔离验收。
6. 完成备份恢复演练、监控告警和安全复核后，再切换域名流量。

本仓库当前尚未完成以上生产化改造，因此本文件不提供伪装成可直接执行的 CVM 公网部署命令。完成 P0 项后，应根据实际生产配置补充经过验证的部署步骤。

## 相关文档

- [本机开发运行说明](local-development.md)
- [健身与饮食数据非视频验收记录](fitness-nutrition-dataset-acceptance.md)
- [数据集许可审查记录](dataset-license-review.md)
- [私有化大模型方案](llm-private-deployment.md)
