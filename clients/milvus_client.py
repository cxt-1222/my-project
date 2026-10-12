import asyncio

from pymilvus import AsyncMilvusClient
from langchain_openai import OpenAIEmbeddings

from core.config import settings

# 创建 集合
milvus_client = AsyncMilvusClient(
    uri=settings.MILVUS_URL,
    token=settings.MILVUS_TOKEN,
    db_name=settings.DB_NAME
)

# content 内容转向量
embddings_model = OpenAIEmbeddings(
    model=settings.EMBEDDINGS_MODEL_NAME,
    api_key=settings.QWEN_API_KEY,
    base_url=settings.QWEN_BASE_URL,
    dimensions=settings.DIMENSIONS,
    check_embedding_ctx_length=False
)

async def embedding_text(txt:str):
    # 必须用异步版本，同步 embed_query 会阻塞整个事件循环
    return await embddings_model.aembed_query(txt)

# 攒批写入：每条消息单独 insert+flush 会产生大量小 segment，
# 触发频繁 compaction 导致查询抖动，这里合并为批量 insert + 批量 flush
_vector_queue: asyncio.Queue[tuple[list[dict], asyncio.Future]] = asyncio.Queue()
_writer_task: asyncio.Task | None = None


async def _flush_vector_batch(batch: list[tuple[list[dict], asyncio.Future]]):
    rows = [row for rows, _ in batch for row in rows]
    try:
        await milvus_client.insert(collection_name=settings.COLLECTION_NAME, data=rows)
        await milvus_client.flush(collection_name=settings.COLLECTION_NAME)
    except Exception as e:
        for _, fut in batch:
            if not fut.done():
                fut.set_exception(e)
        return
    for _, fut in batch:
        if not fut.done():
            fut.set_result(None)


async def _vector_writer_loop():
    loop = asyncio.get_running_loop()
    batch: list[tuple[list[dict], asyncio.Future]] = []
    n_rows = 0
    deadline: float | None = None
    while True:
        timeout = None if not batch else max(0.0, deadline - loop.time())
        try:
            item = await asyncio.wait_for(_vector_queue.get(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            item = None
        if item is not None:
            batch.append(item)
            n_rows += len(item[0])
            if deadline is None:
                deadline = loop.time() + settings.MILVUS_BATCH_INTERVAL
            if n_rows < settings.MILVUS_BATCH_SIZE:
                continue
        if not batch:
            continue
        await _flush_vector_batch(batch)
        batch, n_rows, deadline = [], 0, None


def start_vector_writer():
    global _writer_task
    if _writer_task is None or _writer_task.done():
        _writer_task = asyncio.get_running_loop().create_task(_vector_writer_loop())


async def stop_vector_writer():
    global _writer_task
    if _writer_task is not None:
        _writer_task.cancel()
        try:
            await _writer_task
        except asyncio.CancelledError:
            pass
        _writer_task = None
    # 排空队列里未落库的数据
    batch = []
    while not _vector_queue.empty():
        batch.append(_vector_queue.get_nowait())
    if batch:
        await _flush_vector_batch(batch)


async def milvus_insert(doc_id,meta,chunks):
    # 集合 id 是 auto_id，插入时不能带主键字段
    meta = dict(meta)
    meta.pop('id', None)

    # Qwen embedding 接口单次请求有文本条数上限，按批请求
    batch_size = 10
    vectors = []
    for i in range(0, len(chunks), batch_size):
        vectors.extend(await embddings_model.aembed_documents(chunks[i:i + batch_size]))

    table_data = [
        {
            'title': meta.get('title'),
            'content_id': f'{doc_id}-{index}',
            'content': chunk,
            'vector': vector,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]

    # 交给写批任务，等真正 insert+flush 落库后再返回，
    # 保证调用方(消费者)在数据落库前不会 ack 消息、不会回写成功状态
    fut = asyncio.get_running_loop().create_future()
    await _vector_queue.put((table_data, fut))
    await fut


# 从向量数据库中进行查询相似度最接近的数据
async def search_milvus_data(query: str, doc_ids: list[int] | None = None):
    """向量召回;doc_ids 为可见文档ID列表(None=不过滤,空列表=直接返回空)"""
    if doc_ids is not None and not doc_ids:
        return {'msg': '向量查询成功', 'data': []}
    filter_expr = None
    if doc_ids:
        # content_id 形如 "{doc_id}-{chunk_index}",按前缀匹配限定可见文档
        filter_expr = ' or '.join(f'(content_id like "{d}-%")' for d in doc_ids)
    vector_query = await embedding_text(query)
    res = await milvus_client.search(
        collection_name=settings.COLLECTION_NAME,
        data=[vector_query],  # 查询向量
        anns_field="vector",  # 向量字段名
        search_params={
            "metric_type": "COSINE",  # 度量类型应与创建索引时一致
            "params": {"nprobe": 16}  # 搜索时考虑的聚类数量
        },
        limit=10,  # 返回 Top-10 最相似的结果
        output_fields=["id",'title','content_id','content'],  # 指定返回的标量字段
        filter=filter_expr,
    )
    return {
        'msg':'向量查询成功',
        'data':res[0]
    }
