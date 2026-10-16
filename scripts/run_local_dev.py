"""一键启动本地开发环境。

供 PyCharm 的 Run 按钮使用：

1. 启动 Docker 基础设施（不启动 aiagent-end 应用容器）；
2. 将 Docker 内服务名改成本机映射端口；
3. 启动前端静态服务器；
4. 启动支持自动重载的 FastAPI。

停止 PyCharm 运行后，基础设施容器会继续运行，方便下次快速启动。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
# Compose 中暴露给 Windows 宿主机的端口。
REQUIRED_PORTS = {
    5433: "PostgreSQL",
    27018: "MongoDB",
    5672: "RabbitMQ",
    7687: "Neo4j",
    9010: "RustFS",
    9200: "Elasticsearch",
    19530: "Milvus",
}


LOCAL_ENV = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "5433",
    "POSTGRES_USER": "user",
    "POSTGRES_PASSWORD": "lyp82nlfxxlE",
    "POSTGRES_DB": "aiagent",
    "MONGO_URI": "mongodb://root:lyp82nlfxxlE@127.0.0.1:27018/?authSource=admin",
    "DB_NAME": "aiagent",
    "RABBITMQ_URL": "amqp://user:lyp82nlfxxlE@127.0.0.1:5672/aiagent",
    "ES_HOST": "http://127.0.0.1:9200",
    "MILVUS_URL": "http://127.0.0.1:19530",
    "NEO4J_URI": "bolt://127.0.0.1:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "password",
    # MinIO 是 9000，RustFS 是 9010；应用使用 RustFS。
    "RUSTFS_ENDPOINT": "http://127.0.0.1:9010",
    "PORT": "5173",
}


COMPOSE_SERVICES = (
    "postgres",
    "mongodb",
    "rabbitmq",
    "neo4j",
    "rustfs",
    "elasticsearch",
    "etcd",
    "minio",
    "milvus",
)


def configure_environment() -> None:
    """读取项目 .env，再覆盖为本机开发连接参数。"""
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ.update(LOCAL_ENV)
    os.environ["PYTHONUNBUFFERED"] = "1"


def run_compose(*args: str) -> None:
    command = ["docker", "compose", *args]
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def wait_for_ports(timeout: float = 90.0) -> None:
    """等待基础服务开始监听宿主机端口。"""
    deadline = time.monotonic() + timeout
    pending = dict(REQUIRED_PORTS)

    while pending and time.monotonic() < deadline:
        for port, service in list(pending.items()):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    pending.pop(port)
            except OSError:
                continue
        if pending:
            time.sleep(1)

    if pending:
        services = ", ".join(f"{name}({port})" for port, name in pending.items())
        raise RuntimeError(f"基础服务仍未就绪：{services}")


def _http_is_available(url: str, timeout: float = 1.0) -> bool:
    """检查本机开发服务，禁用系统代理避免 127.0.0.1 被代理接管。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def _wait_for_http(url: str, process: subprocess.Popen[str], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"前端进程启动后立即退出，退出码：{process.returncode}。"
                "请检查 Node.js 和 frontend/server.js。"
            )
        if _http_is_available(url):
            return
        time.sleep(0.25)
    raise RuntimeError(f"前端在 {timeout:.0f} 秒内没有响应：{url}")


def start_frontend() -> subprocess.Popen[str] | None:
    """启动前端；若 5173 已有可访问服务，则复用它。"""
    frontend_url = "http://127.0.0.1:5173/"
    if _http_is_available(frontend_url):
        print("检测到 5173 已有前端服务，本次复用现有服务。", flush=True)
        return None

    if _port_is_open(5173):
        raise RuntimeError(
            "5173 端口已被其他程序占用，但不是可访问的前端服务。"
            "请关闭占用 5173 的程序后再运行。"
        )

    node = shutil.which("node")
    if not node:
        raise RuntimeError("未找到 Node.js。请先安装 Node.js，并确认 node 已加入 PATH。")

    process = subprocess.Popen(
        [node, "server.js"],
        cwd=FRONTEND_ROOT,
        env=os.environ.copy(),
        text=True,
    )
    _wait_for_http(frontend_url, process)
    return process


def _port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def start_backend() -> None:
    # main.py 会在 Windows 上设置 SelectorEventLoopPolicy，适配 psycopg 异步连接。
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # 运行本脚本时 sys.path[0] 是 scripts 目录；显式设置 PYTHONPATH 和
    # app_dir，确保 Uvicorn reload 子进程也能导入项目根目录下的 main.py。
    project_path = str(PROJECT_ROOT)
    current_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        project_path
        if not current_pythonpath
        else os.pathsep.join((project_path, current_pythonpath))
    )

    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[project_path],
        app_dir=project_path,
        log_level="info",
    )


def main() -> None:
    os.chdir(PROJECT_ROOT)
    configure_environment()

    print("停止 Docker 中的 FastAPI 容器，释放 8000 端口...", flush=True)
    run_compose("stop", "aiagent-end")

    print("启动 Docker 基础设施（不启动 aiagent-end）...", flush=True)
    run_compose("up", "-d", "--no-build", *COMPOSE_SERVICES)

    print("等待基础服务就绪...", flush=True)
    wait_for_ports()

    frontend_process: subprocess.Popen[str] | None = None
    try:
        frontend_process = start_frontend()
        print("前端地址：http://localhost:5173", flush=True)
        print("后端地址：http://localhost:8000/docs", flush=True)
        print("修改 Python 后端代码后会自动 reload。按 Ctrl+C 停止本机应用。", flush=True)
        start_backend()
    finally:
        if frontend_process is not None and frontend_process.poll() is None:
            frontend_process.terminate()
            try:
                frontend_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                frontend_process.kill()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n本机开发服务已停止；Docker 基础设施保持运行。", flush=True)
    except Exception as exc:
        print(f"本机开发启动失败：{exc}", file=sys.stderr, flush=True)
        raise
