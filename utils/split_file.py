"""
1. 通过id 从mongoDB中获取 正文信息
2. 正文信息split分割存入milvus向量数据库中
"""
from clients.milvus_client import milvus_insert
from utils.text_chunking import split_knowledge_text


async def split_doc(doc_id, meta, doc):
    doc_data = doc.dict()
    content = doc_data.get('content') or ''
    chunks = split_knowledge_text(content)
    await milvus_insert(doc_id, meta, chunks)
