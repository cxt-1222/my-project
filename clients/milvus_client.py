import asyncio
import threading

from pymilvus import AsyncMilvusClient, DataType, MilvusClient
from langchain_openai import OpenAIEmbeddings

from core.config import settings

MILVUS_DOC_ID_FILTER_BATCH_SIZE = 20
MILVUS_SEARCH_LIMIT = 10
MILVUS_COLLECTION_LOAD_TIMEOUT_SECONDS = 300

# 创建 集合
milvus_client = AsyncMilvusClient(
    uri=settings.MILVUS_URL,
    token=settings.MILVUS_TOKEN,
    db_name=settings.DB_NAME
)
_knowledge_collection_loaded = False
_metadata_client_lock = threading.Lock()
_metadata_client: MilvusClient | None = None


def _get_metadata_client() -> MilvusClient:
    global _metadata_client
    with _metadata_client_lock:
        if _metadata_client is None:
            _metadata_client = MilvusClient(
                uri=settings.MILVUS_URL,
                token=settings.MILVUS_TOKEN,
                db_name=settings.DB_NAME,
                timeout=settings.MILVUS_SEARCH_TIMEOUT_SECONDS,
            )
        return _metadata_client


def _has_milvus_collection(collection_name: str) -> bool:
    return _get_metadata_client().has_collection(
        collection_name=collection_name,
        timeout=settings.MILVUS_SEARCH_TIMEOUT_SECONDS,
    )


def _describe_milvus_collection(collection_name: str) -> dict:
    return _get_metadata_client().describe_collection(
        collection_name=collection_name,
        timeout=settings.MILVUS_SEARCH_TIMEOUT_SECONDS,
    )


def _get_milvus_load_state(collection_name: str) -> dict:
    return _get_metadata_client().get_load_state(
        collection_name=collection_name,
        timeout=settings.MILVUS_SEARCH_TIMEOUT_SECONDS,
    )


async def has_milvus_collection(collection_name: str) -> bool:
    """Run collection metadata checks through the SDK's synchronous admin API."""
    return await asyncio.to_thread(_has_milvus_collection, collection_name)


async def describe_milvus_collection(collection_name: str) -> dict:
    return await asyncio.to_thread(_describe_milvus_collection, collection_name)


async def get_milvus_load_state(collection_name: str) -> dict:
    return await asyncio.to_thread(_get_milvus_load_state, collection_name)


async def close_milvus_metadata_client() -> None:
    global _metadata_client
    with _metadata_client_lock:
        client, _metadata_client = _metadata_client, None
    if client is not None:
        await asyncio.to_thread(client.close)


def _load_state_name(result) -> str:
    state = result.get("state") if isinstance(result, dict) else result
    return (getattr(state, "name", None) or str(state)).replace(" ", "").lower()


async def _ensure_collection_loaded(collection_name: str) -> None:
    state = _load_state_name(await get_milvus_load_state(collection_name))
    if "loaded" in state and "notload" not in state:
        return
    if "notload" in state:
        await milvus_client.load_collection(
            collection_name=collection_name,
            timeout=MILVUS_COLLECTION_LOAD_TIMEOUT_SECONDS,
        )
        state = _load_state_name(await get_milvus_load_state(collection_name))

    deadline = asyncio.get_running_loop().time() + MILVUS_COLLECTION_LOAD_TIMEOUT_SECONDS
    while "loading" in state:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"Milvus collection load timed out: {collection_name}")
        await asyncio.sleep(1)
        state = _load_state_name(await get_milvus_load_state(collection_name))

    if "loaded" not in state or "notload" in state:
        raise RuntimeError(f"Milvus collection is not loadable: {collection_name} ({state})")

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


def _chunk_doc_ids(doc_ids: list[int], batch_size: int = MILVUS_DOC_ID_FILTER_BATCH_SIZE) -> list[list[int]]:
    """Split visible document IDs into filter expressions small enough for Milvus."""
    return [doc_ids[i:i + batch_size] for i in range(0, len(doc_ids), batch_size)]


def _merge_search_hits(hit_batches: list[list[dict]], limit: int = MILVUS_SEARCH_LIMIT) -> list[dict]:
    """Merge COSINE search results from multiple filters into one global Top-K."""
    hits = [hit for batch in hit_batches for hit in batch]
    hits.sort(key=lambda hit: hit.get("distance", float("-inf")), reverse=True)
    return hits[:limit]


# 从向量数据库中进行查询相似度最接近的数据
async def search_milvus_data(query: str, doc_ids: list[int] | None = None):
    """向量召回;doc_ids 为可见文档ID列表(None=不过滤,空列表=直接返回空)"""
    if doc_ids is not None and not doc_ids:
        return {'msg': '向量查询成功', 'data': []}

    if not _knowledge_collection_loaded:
        return {'msg': '向量查询降级：knowledge 集合尚未加载', 'data': []}

    vector_query = await embedding_text(query)
    id_batches = _chunk_doc_ids(doc_ids) if doc_ids is not None else [None]
    hit_batches = []

    for id_batch in id_batches:
        # content_id 形如 "{doc_id}-{chunk_index}"，按前缀匹配限定可见文档。
        # 分批构造 OR 条件，避免可见文档很多时 Milvus 过滤表达式过长而解析失败。
        filter_expr = (
            ' or '.join(f'(content_id like "{doc_id}-%")' for doc_id in id_batch)
            if id_batch is not None
            else None
        )
        res = await asyncio.wait_for(
            milvus_client.search(
                collection_name=settings.COLLECTION_NAME,
                data=[vector_query],  # 查询向量
                anns_field="vector",  # 向量字段名
                search_params={
                    "metric_type": "COSINE",  # 度量类型应与创建索引时一致
                    "params": {"nprobe": 16}  # 搜索时考虑的聚类数量
                },
                limit=MILVUS_SEARCH_LIMIT,
                output_fields=["id", 'title', 'content_id', 'content'],
                filter=filter_expr,
            ),
            timeout=settings.MILVUS_SEARCH_TIMEOUT_SECONDS,
        )
        hit_batches.append(res[0] if res else [])

    return {
        'msg': '向量查询成功',
        'data': _merge_search_hits(hit_batches),
    }


async def ensure_chat_memory_collection():
    """Create a separate collection for user memories without touching document vectors."""
    name = settings.CHAT_MEMORY_COLLECTION
    if not await has_milvus_collection(collection_name=name):
        schema = milvus_client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(field_name="user_id", datatype=DataType.INT64)
        schema.add_field(field_name="source_session_id", datatype=DataType.INT64)
        schema.add_field(field_name="category", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=2000)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=settings.DIMENSIONS)
        index_params = milvus_client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 128},
        )
        await milvus_client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )
    await _ensure_collection_loaded(name)


async def ensure_knowledge_collection():
    """Load the existing document-vector collection without modifying its data."""
    global _knowledge_collection_loaded
    _knowledge_collection_loaded = False
    name = settings.COLLECTION_NAME
    if not await has_milvus_collection(collection_name=name):
        raise RuntimeError(f"Required Milvus collection does not exist: {name}")
    await _ensure_collection_loaded(name)
    _knowledge_collection_loaded = True


async def search_chat_memories(query: str, user_id: int, limit: int | None = None) -> list[dict]:
    """Recall only the current user's long-term memories."""
    name = settings.CHAT_MEMORY_COLLECTION
    if not await has_milvus_collection(collection_name=name):
        return []
    vector = await embedding_text(query)
    result = await milvus_client.search(
        collection_name=name,
        data=[vector],
        anns_field="vector",
        search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
        limit=limit or settings.CHAT_MEMORY_RECALL_LIMIT,
        filter=f"user_id == {int(user_id)}",
        output_fields=["user_id", "source_session_id", "category", "content"],
    )
    memories = []
    seen = set()
    for hit in (result[0] if result else []):
        entity = hit.get("entity", {})
        content = entity.get("content", "")
        if content and content not in seen:
            seen.add(content)
            memories.append(entity)
    return memories


async def upsert_chat_memory(user_id: int, session_id: int, category: str, content: str) -> None:
    """Upsert one deduplicated user fact in the dedicated memory collection."""
    import hashlib

    normalized = " ".join(content.split())
    memory_id = hashlib.sha256(f"{user_id}:{category}:{normalized}".encode("utf-8")).hexdigest()
    vector = await embedding_text(normalized)
    await milvus_client.upsert(
        collection_name=settings.CHAT_MEMORY_COLLECTION,
        data=[{
            "id": memory_id,
            "user_id": int(user_id),
            "source_session_id": int(session_id),
            "category": category[:64],
            "content": normalized[:2000],
            "vector": vector,
        }],
    )
    await milvus_client.flush(collection_name=settings.CHAT_MEMORY_COLLECTION)


async def delete_chat_memories_for_session(user_id: int, session_id: int) -> None:
    name = settings.CHAT_MEMORY_COLLECTION
    if await has_milvus_collection(collection_name=name):
        await milvus_client.delete(
            collection_name=name,
            filter=f"user_id == {int(user_id)} and source_session_id == {int(session_id)}",
        )
        await milvus_client.flush(collection_name=name)
