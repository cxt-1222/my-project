import asyncio
import sys
from contextlib import asynccontextmanager
from clients.rustfs import init_rustfs_bucket
from services.content_service import init_mongodb
from clients.rabbitmq.mq import init_mq,close_mq
from clients.es_client import init_es,close_es
from clients.milvus_client import start_vector_writer, stop_vector_writer
from clients.neo4j_client import init_neo4j_driver, close_neo4j_driver
from clients.chat_cache import init_chat_cache, close_chat_cache
from clients.milvus_client import ensure_chat_memory_collection

if sys.platform == 'win32':
    # psycopg 异步模式不支持 Windows 默认的 ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.file import file_router
from api.publish import publish_router
from api.document import pg_router
from api.mongo import mongo_router
from api.es import es_router
from api.milvus import milvus_router
from api.neo4j import neo4j_router
from api.ai import ai_router
from api.user import user_router
from api.role import role_router
from api.team import team_router
from api.chat import chat_router
from api.permission import permission_router
from api.review import review_router
from api.voice import voice_router
from api.fitness import fitness_router
from api.training import training_router
from api.workout import workout_router
from api.nutrition import nutrition_router
from api.knowledge_maintenance import knowledge_maintenance_router
from api.catalog import catalog_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 在main的lifespan里调用抽出去的初始化函数
    await init_rustfs_bucket()
    await init_mongodb()
    await init_chat_cache()
    try:
        await ensure_chat_memory_collection()
    except Exception as exc:
        print(f"Chat memory collection unavailable; long-term memory disabled: {exc}")
    start_vector_writer()
    await init_mq()
    await init_es()
    await init_neo4j_driver()
    yield
    await stop_vector_writer()
    await close_mq()
    await close_es()
    await close_neo4j_driver()
    await close_chat_cache()
    print("App shutdown")

app = FastAPI(title="Knowledge",lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(user_router)
app.include_router(role_router)
app.include_router(team_router)
app.include_router(chat_router)
app.include_router(ai_router)
app.include_router(neo4j_router)
app.include_router(milvus_router)
app.include_router(es_router)
app.include_router(pg_router)
app.include_router(mongo_router)
app.include_router(file_router)
app.include_router(publish_router)
app.include_router(permission_router)
app.include_router(review_router)
app.include_router(voice_router)
app.include_router(fitness_router)
app.include_router(training_router)
app.include_router(workout_router)
app.include_router(nutrition_router)
app.include_router(knowledge_maintenance_router)
app.include_router(catalog_router)
# vite 代理的 rewrite 对 WebSocket upgrade 不生效，前端 WS 会以 /api/voice/* 原样到达；
# 挂一份 /api 前缀别名让两种路径都可用
app.include_router(voice_router, prefix="/api")
