
from pymilvus import CollectionSchema, FieldSchema, DataType
from clients.milvus_client import has_milvus_collection, milvus_client, search_milvus_data
from core.config import settings
from fastapi import APIRouter
milvus_router = APIRouter(prefix='/milvus',tags=['向量数据库'])


@milvus_router.get('/create_table',description='创建milvus向量数据库')
async def create_milvus_database():
    try:
        if await has_milvus_collection(collection_name=settings.COLLECTION_NAME):
            return {'msg': '集合已存在；现有向量数据已保留，未执行重建。'}

        schema = CollectionSchema(fields=[
            FieldSchema(name='id', dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name='vector', dtype=DataType.FLOAT_VECTOR, dim=settings.DIMENSIONS),
            FieldSchema(name='title', dtype=DataType.VARCHAR, max_length=1000, nullable=True),
            FieldSchema(name='content_id',dtype=DataType.VARCHAR, max_length=1000, nullable=True),
            FieldSchema(name='content', dtype=DataType.VARCHAR, max_length=20000)
        ])
        index_params = milvus_client.prepare_index_params()
        index_params.add_index(field_name='vector', index_type='IVF_FLAT', metric_type='COSINE', params={'nlist': 1024})
        await milvus_client.create_collection(
            collection_name=settings.COLLECTION_NAME,
            schema=schema,
            index_params=index_params
        )
        await milvus_client.flush(collection_name=settings.COLLECTION_NAME)
        return {'msg': '创建milvus向量数据库成功'}
    except Exception as e:
        return {
            'msg':f'创建失败：{e}'
        }


@milvus_router.post('/search')
async def search_milvus(query:str):
    res = await search_milvus_data(query)
    return res
