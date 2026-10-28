"""Read-only inventory for a future, explicitly confirmed knowledge cleanup."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clients import es_client, neo4j_client
from clients.milvus_client import milvus_client
from core.config import settings
from models import GraphDocModel, KhDocument

_MILVUS_BATCH_SIZE = 20
_MILVUS_PAGE_SIZE = 1000
_MILVUS_MAX_OFFSET = 16384


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _build_report(
    documents: list[dict[str, Any]],
    *,
    mongo_counts: dict[int, int],
    elasticsearch_counts: dict[int, int],
    milvus_counts: dict[int, int],
    graph_mappings: dict[int, dict[str, int]],
    neo4j_relationship_counts: dict[int, int],
    unattributed_neo4j_relationships: int,
    neo4j_total_nodes: int,
    neo4j_total_relationships: int,
    ambiguous_mongo_records: int,
    orphan_graph_mappings: int,
) -> dict[str, Any]:
    rows = []
    totals: Counter[str] = Counter()
    for doc in documents:
        doc_id = int(doc["id"])
        graph = graph_mappings.get(doc_id, {})
        stores = {
            "postgres_documents": 1,
            "mongodb_contents": mongo_counts.get(doc_id, 0),
            "elasticsearch_documents": elasticsearch_counts.get(doc_id, 0),
            "milvus_vectors": milvus_counts.get(doc_id, 0),
            "postgres_graph_mappings": graph.get("mappings", 0),
            "postgres_graph_entities": graph.get("entities", 0),
            "postgres_graph_relationships": graph.get("relationships", 0),
            "neo4j_attributed_relationships": neo4j_relationship_counts.get(doc_id, 0),
        }
        totals.update(stores)
        rows.append({
            "document_id": doc_id,
            "title": doc.get("title"),
            "author_id": doc.get("author_id"),
            "team_id": doc.get("team_id"),
            "cleanup_classification": "unclassified",
            "stores": stores,
        })

    blockers = []
    if unattributed_neo4j_relationships:
        blockers.append(
            "Neo4j 中存在无法映射到当前知识文档的关系（缺少或不匹配 source_doc_id），不能安全清理。"
        )
    if ambiguous_mongo_records:
        blockers.append(
            f"有 {ambiguous_mongo_records} 条 MongoDB 正文记录同时匹配多个文档映射，需先核对映射。"
        )
    if orphan_graph_mappings:
        blockers.append(
            f"PostgreSQL 中有 {orphan_graph_mappings} 条图谱映射找不到对应知识文档，需先核对。"
        )
    blockers.append(
        "来源记录到知识文档的稳定映射尚未实现，无法区分新健身/饮食目录与待清理旧文档。"
    )
    blockers.append(
        "Neo4j 实体节点按名称跨文档共享合并，当前没有节点级文档归属，不能按文档安全清理。"
    )

    return {
        "mode": "read_only_preview",
        "destructive": False,
        "cleanup_execution_available": False,
        "cleanup_target_classification_available": False,
        "document_count": len(rows),
        "documents": rows,
        "totals": dict(totals),
        "unattributed_neo4j_relationships": unattributed_neo4j_relationships,
        "neo4j_global_counts": {
            "nodes": neo4j_total_nodes,
            "relationships": neo4j_total_relationships,
        },
        "ambiguous_mongodb_records": ambiguous_mongo_records,
        "orphan_postgres_graph_mappings": orphan_graph_mappings,
        "blockers": blockers,
        "notice": "本接口只是全量盘点，不是可执行的删除清单；只读取元数据和存储计数，不读取知识正文，也不执行删除。预览不是锁定快照。",
    }


async def _count_mongo_contents(
    documents: list[dict[str, Any]],
) -> tuple[dict[int, int], int]:
    from pymongo import AsyncMongoClient

    doc_ids = {int(doc["id"]) for doc in documents}
    content_id_owners: dict[int, set[int]] = {}
    for doc in documents:
        content_id = _as_int(doc.get("content_id"))
        if content_id is not None:
            content_id_owners.setdefault(content_id, set()).add(int(doc["id"]))

    client = AsyncMongoClient(settings.MONGO_URI)
    try:
        collection = client[settings.DB_NAME]["document_content"]
        query = {"$or": [
            {"_id": {"$in": list(content_id_owners)}},
            {"document_id": {"$in": list(doc_ids)}},
        ]}
        cursor = collection.find(query, {"_id": 1, "document_id": 1})
        counts: Counter[int] = Counter()
        ambiguous = 0
        async for row in cursor:
            owners = set(content_id_owners.get(_as_int(row.get("_id")), set()))
            linked_doc_id = _as_int(row.get("document_id"))
            if linked_doc_id in doc_ids:
                owners.add(linked_doc_id)
            if len(owners) > 1:
                ambiguous += 1
            elif owners:
                counts[next(iter(owners))] += 1
        return dict(counts), ambiguous
    finally:
        await client.close()


async def _count_elasticsearch_documents(doc_ids: list[int]) -> dict[int, int]:
    if not doc_ids:
        return {}
    es = await es_client.get_es()
    response = await es.mget(
        index=settings.INDEX_NAME,
        ids=[str(doc_id) for doc_id in doc_ids],
        source=False,
    )
    return {
        doc_id: 1
        for doc_id, item in zip(doc_ids, response.get("docs", []))
        if item.get("found")
    }


async def _count_milvus_vectors(doc_ids: list[int]) -> dict[int, int]:
    counts: Counter[int] = Counter()
    doc_id_by_prefix = {str(doc_id): doc_id for doc_id in doc_ids}
    for start in range(0, len(doc_ids), _MILVUS_BATCH_SIZE):
        batch = doc_ids[start:start + _MILVUS_BATCH_SIZE]
        expression = " or ".join(
            f'(content_id like "{doc_id}-%")' for doc_id in batch
        )
        offset = 0
        while offset < _MILVUS_MAX_OFFSET:
            page_limit = min(_MILVUS_PAGE_SIZE, _MILVUS_MAX_OFFSET - offset)
            rows = await milvus_client.query(
                collection_name=settings.COLLECTION_NAME,
                filter=expression,
                output_fields=["content_id"],
                limit=page_limit,
                offset=offset,
            )
            if not isinstance(rows, list):
                raise RuntimeError("Milvus query 返回了非列表结果，无法生成完整预览。")
            for row in rows:
                content_id = str(row.get("content_id") or "")
                prefix, separator, _ = content_id.partition("-")
                doc_id = doc_id_by_prefix.get(prefix) if separator else None
                if doc_id is not None:
                    counts[doc_id] += 1
            if len(rows) < page_limit:
                break
            offset += page_limit
        else:
            raise RuntimeError(
                "单批 Milvus 结果达到安全分页上限，无法确认准确数量；预览已停止。"
            )
    return dict(counts)


async def _count_neo4j_relationships(
    doc_ids: set[int],
) -> tuple[dict[int, int], int, int, int]:
    driver = neo4j_client.driver
    if driver is None:
        raise RuntimeError("Neo4j driver 未初始化。")

    counts: Counter[int] = Counter()
    async with driver.session() as session:
        result = await session.run(
            "MATCH ()-[r]->() "
            "WHERE r.source_doc_id IS NOT NULL "
            "RETURN toString(r.source_doc_id) AS doc_id, count(r) AS record_count"
        )
        rows = await result.data()
        result = await session.run(
            "MATCH ()-[r]->() "
            "WHERE r.source_doc_id IS NULL "
            "RETURN count(r) AS record_count"
        )
        unattributed = await result.single()
        result = await session.run("MATCH (n) RETURN count(n) AS record_count")
        node_total = await result.single()
        result = await session.run("MATCH ()-[r]->() RETURN count(r) AS record_count")
        relationship_total = await result.single()

        unresolved = int((unattributed or {}).get("record_count") or 0)
    for row in rows:
        doc_id = _as_int(row.get("doc_id"))
        record_count = int(row.get("record_count") or 0)
        if doc_id in doc_ids:
            counts[doc_id] += record_count
        else:
            unresolved += record_count

    return (
        dict(counts),
        unresolved,
        int((node_total or {}).get("record_count") or 0),
        int((relationship_total or {}).get("record_count") or 0),
    )


async def create_knowledge_cleanup_preview(db: AsyncSession) -> dict[str, Any]:
    result = await db.execute(
        select(
            KhDocument.id,
            KhDocument.title,
            KhDocument.content_id,
            KhDocument.author_id,
            KhDocument.team_id,
        ).order_by(KhDocument.id)
    )
    documents = [
        {
            "id": int(row.id),
            "title": row.title,
            "content_id": row.content_id,
            "author_id": row.author_id,
            "team_id": row.team_id,
        }
        for row in result.all()
    ]
    doc_ids = [doc["id"] for doc in documents]
    doc_id_set = set(doc_ids)

    graph_result = await db.execute(
        select(
            GraphDocModel.doc_id,
            GraphDocModel.entities,
            GraphDocModel.relationships,
        )
    )
    graph_rows = graph_result.all()
    graph_mappings: dict[int, dict[str, int]] = {}
    orphan_graph_mappings = 0
    for row in graph_rows:
        graph_doc_id = int(row.doc_id)
        if graph_doc_id not in doc_id_set:
            orphan_graph_mappings += 1
            continue
        graph_mappings[graph_doc_id] = {
            "mappings": 1,
            "entities": len(row.entities or []),
            "relationships": len(row.relationships or []),
        }

    mongo_counts, ambiguous_mongo = await _count_mongo_contents(documents)
    es_counts = await _count_elasticsearch_documents(doc_ids)
    milvus_counts = await _count_milvus_vectors(doc_ids)
    (
        neo4j_counts,
        unattributed_neo4j,
        neo4j_node_total,
        neo4j_relationship_total,
    ) = await _count_neo4j_relationships(doc_id_set)

    return _build_report(
        documents,
        mongo_counts=mongo_counts,
        elasticsearch_counts=es_counts,
        milvus_counts=milvus_counts,
        graph_mappings=graph_mappings,
        neo4j_relationship_counts=neo4j_counts,
        unattributed_neo4j_relationships=unattributed_neo4j,
        neo4j_total_nodes=neo4j_node_total,
        neo4j_total_relationships=neo4j_relationship_total,
        ambiguous_mongo_records=ambiguous_mongo,
        orphan_graph_mappings=orphan_graph_mappings,
    )
