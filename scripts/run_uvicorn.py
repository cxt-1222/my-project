"""Windows 下正确启动 uvicorn。

直接 `uvicorn main:app` 时,uvicorn 在 win32 上强制用 ProactorEventLoop
(uvicorn/loops/asyncio.py 直接返回 ProactorEventLoop,绕过 policy),
psycopg 异步模式会报错。这里自己驱动 server.serve(),在 Selector 循环上跑。
"""
import asyncio
import sys
from pathlib import Path

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_local_dev import configure_environment

configure_environment()

import uvicorn

from main import app


async def serve():
    config = uvicorn.Config(app, host='127.0.0.1', port=8000)
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == '__main__':
    asyncio.run(serve())
