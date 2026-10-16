"""
审核之后。文件就发布，概念状态为已发布
1.使用RabbitMQ 进行异步队列操作
    - Search 队列：INDEX （整篇元数据 + 正文）
    - RAG 队列： BY_DOC_IDS （文档ID列表）
    - KG 队列：BUILD_BY_DOC_IDS （文档 ID）
"""
from datetime import datetime

from clients.rabbitmq.producer import publish_index,publish_rag,publish_kg
from core.database import SessionLocal
from fastapi import APIRouter
from schemas.document import KhDocumentRespDTOUpdate
from services.content_service import get_mongo_doc
from services.document_service import mark_parsing, update_kh_doc
publish_router = APIRouter(prefix='/knowledge_doc',tags=['发布文档'])

@publish_router.post('/publish')
async def publish_api(doc_id:int):
    #改变pg 中文档的状态
    dto = KhDocumentRespDTOUpdate(status=1, publish_time=datetime.now())
    async with SessionLocal() as session:
        pg_data = await update_kh_doc(session,dto,doc_id)
        # 标记 3 个 MQ 流程为「解析中」,消费端各自回写结果
        await mark_parsing(session, doc_id)
        mondb_data = await get_mongo_doc(doc_id)
        # 审核 发布成功
        # 存入 es 模块
        meta = {c.name: getattr(pg_data, c.name) for c in pg_data.__table__.columns}
        meta = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in meta.items()}
        # ES 索引 is_public 为 boolean 类型,PG 为 0/1 整型,转换避免写入报错
        if 'is_public' in meta and meta['is_public'] is not None:
            meta['is_public'] = bool(meta['is_public'])
        await mq_publish_es(doc_id,meta, mondb_data.content)

        return {
            'status':1,
            'meta':meta,
            'mondb_data':mondb_data,
            'msg':'文档发布成功！'
        }

async def mq_publish_es(doc_id,meta,content):
    await publish_index(meta, content)
    await publish_rag(doc_id, meta)
    #await publish_kg(doc_id,content)
