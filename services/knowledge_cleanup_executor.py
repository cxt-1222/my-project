"""Explicit, per-document cleanup across the existing knowledge stores."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from clients import es_client, neo4j_client
from clients.milvus_client import milvus_client
from core.config import settings
from models import GraphDocModel, KhDocument
from models.dataset_catalog import KnowledgeCleanupExecutionModel
from services.knowledge_cleanup_service import (
    _count_elasticsearch_documents,
    _count_milvus_vectors,
    _count_mongo_contents,
    _count_neo4j_relationships,
    create_knowledge_cleanup_preview,
)

CLEANUP_CONFIRMATION_PHRASE = "确认清理预览中的全部旧知识文档"


class CleanupConflict(RuntimeError):
    pass


class CleanupExecutionFailure(RuntimeError):
    def __init__(self, execution_id: int, stage: str):
        super().__init__(f"清理执行记录 {execution_id} 在阶段 {stage} 失败；可重新预览后重试。")
        self.execution_id = execution_id
        self.stage = stage


def _deleted_count(response: Any, key: str) -> int:
    if isinstance(response, dict):
        value = response.get(key, 0)
    else:
        value = getattr(response, key, 0)
    return int(value or 0)


async def _delete_es_document(es: Any, document_id: int) -> int:
    try:
        response = await es.delete(
            index=settings.INDEX_NAME,
            id=str(document_id),
            refresh=True,
        )
    except Exception as exc:
        status = getattr(getattr(exc, "meta", None), "status", None)
        if status == 404 or type(exc).__name__ == "NotFoundError":
            return 0
        try:
            await es.update(
                index=settings.INDEX_NAME,
                id=str(document_id),
                doc={"status": 0, "is_public": False, "publish_time": None},
                refresh=True,
            )
        except Exception:
            pass
        raise
    return int(response.get("result") == "deleted") if isinstance(response, dict) else 1


async def delete_knowledge_document(
    db: AsyncSession,
    document: dict[str, Any],
    *,
    es: Any,
    mongo_collection: Any,
    milvus: Any,
    neo_driver: Any,
) -> dict[str, int]:
    """Delete one document's copies; shared Neo4j entity nodes are retained."""
    document_id = int(document["id"])
    doc = await db.get(KhDocument, document_id)
    if doc is None:
        raise RuntimeError("PostgreSQL 文档在清理过程中发生变化。")

    doc.status = 0
    doc.is_public = 0
    doc.publish_time = None
    await db.commit()

    counts: dict[str, int] = {}
    counts["elasticsearch_documents"] = await _delete_es_document(es, document_id)

    content_id = document.get("content_id")
    mongo_query: dict[str, Any] = {"document_id": document_id}
    if content_id is not None:
        mongo_query = {"$or": [{"_id": content_id}, {"document_id": document_id}]}
    mongo_result = await mongo_collection.delete_many(mongo_query)
    counts["mongodb_contents"] = _deleted_count(mongo_result, "deleted_count")

    milvus_response = await milvus.delete(
        collection_name=settings.COLLECTION_NAME,
        filter=f'content_id like "{document_id}-%"',
    )
    await milvus.flush(collection_name=settings.COLLECTION_NAME)
    counts["milvus_vectors"] = _deleted_count(milvus_response, "delete_count")

    async with neo_driver.session() as neo_session:
        neo_result = await neo_session.run(
            "MATCH ()-[r]->() WHERE r.source_doc_id = $doc_id DELETE r",
            doc_id=document_id,
        )
        summary = await neo_result.consume()
        counters = getattr(summary, "counters", None)
        counts["neo4j_attributed_relationships"] = int(
            getattr(counters, "relationships_deleted", 0) or 0
        )

    graph_result = await db.execute(
        delete(GraphDocModel).where(GraphDocModel.doc_id == document_id)
    )
    counts["postgres_graph_mappings"] = int(graph_result.rowcount or 0)
    await db.delete(doc)
    counts["postgres_documents"] = 1
    await db.commit()
    return counts


async def _verify_targets(
    db: AsyncSession,
    documents: list[dict[str, Any]],
    *,
    es: Any,
    mongo_collection: Any,
    milvus: Any,
    neo_driver: Any,
) -> dict[str, Any]:
    document_ids = [int(document["id"]) for document in documents]
    if not document_ids:
        return {"passed": True, "remaining": {}}

    pg_documents = await db.scalar(
        select(func.count()).select_from(KhDocument).where(KhDocument.id.in_(document_ids))
    )
    pg_graph = await db.scalar(
        select(func.count()).select_from(GraphDocModel).where(GraphDocModel.doc_id.in_(document_ids))
    )
    mongo_counts, ambiguous_mongo = await _count_mongo_contents(
        documents,
        collection=mongo_collection,
    )
    es_counts = await _count_elasticsearch_documents(document_ids, es=es)
    milvus_counts = await _count_milvus_vectors(document_ids)
    neo_counts, unattributed, _, _ = await _count_neo4j_relationships(
        set(document_ids),
        driver=neo_driver,
        include_foreign_document_ids=False,
    )

    remaining = {
        "postgres_documents": int(pg_documents or 0),
        "postgres_graph_mappings": int(pg_graph or 0),
        "mongodb_contents": sum(mongo_counts.values()),
        "elasticsearch_documents": sum(es_counts.values()),
        "milvus_vectors": sum(milvus_counts.values()),
        "neo4j_attributed_relationships": sum(neo_counts.values()),
        "ambiguous_mongodb_records": ambiguous_mongo,
        "unattributed_neo4j_relationships": unattributed,
    }
    return {"passed": not any(remaining.values()), "remaining": remaining}


async def execute_knowledge_cleanup(
    db: AsyncSession,
    *,
    preview_sha256: str,
    confirmation_phrase: str,
    requested_by: int,
) -> dict[str, Any]:
    if confirmation_phrase != CLEANUP_CONFIRMATION_PHRASE:
        raise CleanupConflict("二次确认文本不匹配；没有执行清理。")

    report = await create_knowledge_cleanup_preview(db)
    if preview_sha256 != report["preview_sha256"]:
        raise CleanupConflict("清理预览已变化；没有执行清理，请刷新预览后重新确认。")
    if not report["cleanup_execution_available"]:
        raise CleanupConflict("清理预览存在安全阻断项；没有执行清理。")

    targets = [document for document in report["documents"] if document["cleanup_target"]]
    result: dict[str, Any] = {
        "target_document_ids": [int(document["document_id"]) for document in targets],
        "expected_counts": report["cleanup_target_totals"],
        "deleted_counts": {},
        "completed_document_ids": [],
        "verification": None,
        "preserved_shared_neo4j_nodes": report["neo4j_global_counts"]["nodes"],
    }
    execution = KnowledgeCleanupExecutionModel(
        preview_sha256=preview_sha256,
        requested_by=requested_by,
        execution_status="running",
        result=result,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    from pymongo import AsyncMongoClient

    mongo_client = None
    stage = "connect_stores"
    current_document_id: int | None = None
    try:
        es = await es_client.get_es()
        mongo_client = AsyncMongoClient(settings.MONGO_URI)
        mongo_collection = mongo_client[settings.DB_NAME]["document_content"]
        neo_driver = neo4j_client.driver
        if neo_driver is None:
            raise RuntimeError("Neo4j driver 未初始化。")

        deleted_totals: Counter[str] = Counter()
        for target in targets:
            current_document_id = int(target["document_id"])
            stage = "delete_document_stores"
            per_document_counts = await delete_knowledge_document(
                db,
                {
                    "id": current_document_id,
                    "content_id": target.get("content_id"),
                },
                es=es,
                mongo_collection=mongo_collection,
                milvus=milvus_client,
                neo_driver=neo_driver,
            )
            deleted_totals.update(per_document_counts)
            result["deleted_counts"] = dict(deleted_totals)
            result["completed_document_ids"].append(current_document_id)
            execution.result = result
            await db.commit()

        current_document_id = None
        stage = "verify_deletions"
        inventory = [
            {"id": int(item["document_id"]), "content_id": item.get("content_id")}
            for item in targets
        ]
        verification = await _verify_targets(
            db,
            inventory,
            es=es,
            mongo_collection=mongo_collection,
            milvus=milvus_client,
            neo_driver=neo_driver,
        )
        result["verification"] = verification
        if not verification["passed"]:
            raise RuntimeError("清理后仍发现文档副本或无法归属的关系。")

        execution.execution_status = "completed"
        execution.result = result
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "execution_id": int(execution.id),
            "execution_status": execution.execution_status,
            **result,
        }
    except CleanupConflict:
        raise
    except Exception as exc:
        result["failed_document_id"] = current_document_id
        result["failed_stage"] = stage
        result["failure_type"] = type(exc).__name__
        execution.execution_status = "failed"
        execution.result = result
        execution.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise CleanupExecutionFailure(int(execution.id), stage) from exc
    finally:
        if mongo_client is not None:
            await mongo_client.close()
