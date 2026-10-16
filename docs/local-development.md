# 本机开发运行说明

## 推荐运行方式

本项目开发时采用“Docker 运行基础设施，本机运行代码”的方式：

```text
Docker：PostgreSQL、MongoDB、RabbitMQ、Neo4j、Elasticsearch、Milvus、RustFS
本机：FastAPI 后端、原生 HTML/CSS/JavaScript 前端
```

这样修改 Python、HTML、CSS、JavaScript 后，不需要重新构建 `aiagent-end` 镜像。

## 首次配置 Python 本机环境

只需要首次执行一次。如果 `.venv` 已存在，直接执行依赖安装即可：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'
if (-not (Test-Path '.venv\Scripts\python.exe')) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --index-url https://pypi.org/simple
```

如果默认镜像源返回 `403`，使用上面的 `https://pypi.org/simple`。安装完成后，本机 FastAPI 需要的 `aioboto3`、`aio-pika`、`neo4j`、`psycopg[binary]`、文档解析依赖等才会齐全。

## 启动后端

在项目根目录执行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start-local-backend.ps1
```

脚本会自动完成两件事：

1. 使用 `docker compose up -d --no-build` 启动后端依赖服务；
2. 使用 `.venv` 启动本机 FastAPI，并启用 `--reload`。

后端地址：

```text
http://localhost:8000
http://localhost:8000/docs
```

## 启动前端

另开一个 PowerShell：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent\frontend'
node .\server.js
```

前端地址：

```text
http://localhost:5173
```

## 本机运行时的关键配置

Docker 容器之间使用服务名，例如 `postgres`、`mongodb`；本机运行 FastAPI 时必须使用 `127.0.0.1` 和宿主机映射端口：

| 配置 | 本机开发值 |
|---|---|
| PostgreSQL | `127.0.0.1:5433` |
| MongoDB | `127.0.0.1:27018` |
| RabbitMQ | `127.0.0.1:5672` |
| Elasticsearch | `127.0.0.1:9200` |
| Milvus | `127.0.0.1:19530` |
| Neo4j | `127.0.0.1:7687` |
| RustFS | `127.0.0.1:9010` |

`start-local-backend.ps1` 已经将这些配置设置为本机模式，并覆盖 `.env` 中不适用于本机运行的地址。

## 切换回 Docker 运行后端

先在本机 FastAPI 窗口按 `Ctrl + C`，然后执行：

```powershell
Set-Location 'E:\健身项目开发\knowledge-agent'
docker compose up -d --no-build aiagent-end
```

## 常见问题

### MongoDB 连接失败

本机不能使用 `mongodb://mongodb:27017`，应使用：

```text
mongodb://root:lyp82nlfxxlE@127.0.0.1:27018/?authSource=admin
```

### PostgreSQL 用户认证失败

当前 Compose 的默认 PostgreSQL 用户是 `user`，本机配置应使用：

```text
POSTGRES_USER=user
POSTGRES_PASSWORD=lyp82nlfxxlE
POSTGRES_PORT=5433
```

### 不要执行的命令

开发时不要每次修改代码都执行：

```powershell
docker compose up -d --build
```

只有修改 Dockerfile、requirements.txt、系统依赖或需要重建镜像时，才需要重新构建。







## PyCharm 一键启动

项目根目录已经提供共享运行配置：

```text
.run/Knowledge_Agent_Local_Dev.run.xml
```

在 PyCharm 中：

1. 用 PyCharm 打开 `E:\健身项目开发\knowledge-agent`；
2. 确认项目解释器选择项目下的 `.venv\Scripts\python.exe`；
3. 等待 PyCharm 识别 `.run/Knowledge_Agent_Local_Dev.run.xml`；
4. 在右上角运行配置下拉框选择 `Knowledge Agent - Local Dev`；
5. 点击绿色三角形 **Run**。

这个运行配置会自动：

- 停止 Docker 中的 `aiagent-end`；
- 启动 PostgreSQL、MongoDB、RabbitMQ、Neo4j、Elasticsearch、Milvus、RustFS 等基础设施；
- 启动前端 `http://localhost:5173`；
- 启动本机 FastAPI `http://localhost:8000`；
- Python 文件修改后自动 reload。

对应的启动脚本是：

```text
scripts/run_local_dev.py
```

如果 PyCharm 没有自动显示运行配置，可以手动创建一个 **Python** 配置：

- **Script path**：`$PROJECT_DIR$/scripts/run_local_dev.py`
- **Working directory**：`$PROJECT_DIR$`
- **Python interpreter**：`$PROJECT_DIR$/.venv/Scripts/python.exe`

停止时点击 PyCharm 控制台左上角的红色停止按钮即可。停止的是本机前后端，Docker 基础设施会保留运行。
