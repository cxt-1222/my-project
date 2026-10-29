import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import knowledge_cleanup_executor as cleanup


def test_document_cleanup_uses_exact_ids_and_keeps_shared_neo4j_nodes():
    events = []

    class Db:
        async def get(self, _model, document_id):
            assert document_id == 12
            return SimpleNamespace(status=1, is_public=1, publish_time="set")

        async def commit(self):
            events.append("postgres_commit")

        async def execute(self, _statement):
            return SimpleNamespace(rowcount=1)

        async def delete(self, _doc):
            events.append("postgres_delete")

    class Es:
        async def delete(self, **kwargs):
            assert kwargs["id"] == "12"
            events.append("elasticsearch_delete")
            return {"result": "deleted"}

    class Mongo:
        async def delete_many(self, query):
            assert query == {"$or": [{"_id": 120}, {"document_id": 12}]}
            events.append("mongodb_delete")
            return SimpleNamespace(deleted_count=1)

    class NeoResult:
        async def consume(self):
            return SimpleNamespace(counters=SimpleNamespace(relationships_deleted=2))

    class NeoSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run(self, query, **kwargs):
            assert "r.source_doc_id = $doc_id" in query
            assert "DELETE r" in query
            assert "DELETE n" not in query
            assert kwargs == {"doc_id": 12}
            events.append("neo4j_delete_relationships")
            return NeoResult()

    class NeoDriver:
        def session(self):
            return NeoSession()

    class Milvus:
        async def delete(self, *, collection_name, filter):
            assert filter == 'content_id like "12-%"'
            events.append("milvus_delete")
            return {"delete_count": 3}

        async def flush(self, *, collection_name):
            events.append("milvus_flush")

    counts = asyncio.run(cleanup.delete_knowledge_document(
        Db(),
        {"id": 12, "content_id": 120},
        es=Es(),
        mongo_collection=Mongo(),
        milvus=Milvus(),
        neo_driver=NeoDriver(),
    ))

    assert counts == {
        "elasticsearch_documents": 1,
        "mongodb_contents": 1,
        "milvus_vectors": 3,
        "neo4j_attributed_relationships": 2,
        "postgres_graph_mappings": 1,
        "postgres_documents": 1,
    }
    assert events.index("postgres_commit") < events.index("elasticsearch_delete")
    assert events.index("neo4j_delete_relationships") < events.index("postgres_delete")


def test_document_cleanup_retries_after_partial_store_failure():
    class Db:
        def __init__(self):
            self.document = SimpleNamespace(status=1, is_public=1, publish_time="set")

        async def get(self, _model, document_id):
            assert document_id == 12
            return self.document

        async def commit(self):
            return None

        async def execute(self, _statement):
            return SimpleNamespace(rowcount=0)

        async def delete(self, _document):
            return None

    class NotFoundError(Exception):
        meta = SimpleNamespace(status=404)

    class Es:
        def __init__(self):
            self.calls = 0

        async def delete(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"result": "deleted"}
            raise NotFoundError()

    class Mongo:
        def __init__(self):
            self.calls = 0

        async def delete_many(self, _query):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("temporary MongoDB failure")
            return SimpleNamespace(deleted_count=0)

    class NeoResult:
        async def consume(self):
            return SimpleNamespace(counters=SimpleNamespace(relationships_deleted=0))

    class NeoSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run(self, *_args, **_kwargs):
            return NeoResult()

    class NeoDriver:
        def session(self):
            return NeoSession()

    class Milvus:
        async def delete(self, **_kwargs):
            return {"delete_count": 0}

        async def flush(self, **_kwargs):
            return None

    db = Db()
    es = Es()
    mongo = Mongo()
    document = {"id": 12, "content_id": 120}

    with pytest.raises(ConnectionError, match="temporary MongoDB failure"):
        asyncio.run(cleanup.delete_knowledge_document(
            db,
            document,
            es=es,
            mongo_collection=mongo,
            milvus=Milvus(),
            neo_driver=NeoDriver(),
        ))

    counts = asyncio.run(cleanup.delete_knowledge_document(
        db,
        document,
        es=es,
        mongo_collection=mongo,
        milvus=Milvus(),
        neo_driver=NeoDriver(),
    ))

    assert es.calls == 2
    assert mongo.calls == 2
    assert counts["elasticsearch_documents"] == 0
    assert counts["mongodb_contents"] == 0
    assert counts["postgres_documents"] == 1


def test_es_not_found_is_idempotent_and_other_errors_fail_closed():
    class NotFoundError(Exception):
        meta = SimpleNamespace(status=404)

    class MissingEs:
        async def delete(self, **_kwargs):
            raise NotFoundError()

    assert asyncio.run(cleanup._delete_es_document(MissingEs(), 12)) == 0

    class BrokenEs:
        def __init__(self):
            self.hidden = False

        async def delete(self, **_kwargs):
            raise RuntimeError("connection failed")

        async def update(self, **kwargs):
            assert kwargs["doc"]["is_public"] is False
            self.hidden = True

    es = BrokenEs()
    with pytest.raises(RuntimeError, match="connection failed"):
        asyncio.run(cleanup._delete_es_document(es, 12))
    assert es.hidden is True


def test_verification_ignores_relationships_owned_by_documents_outside_cleanup_batch(monkeypatch):
    class NeoResult:
        def __init__(self, *, rows=None, count=0):
            self.rows = rows or []
            self.count = count

        async def data(self):
            return self.rows

        async def single(self):
            return {"record_count": self.count}

    class NeoSession:
        def __init__(self):
            self.non_null_calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run(self, query):
            if "IS NOT NULL" in query:
                self.non_null_calls += 1
                return NeoResult(rows=[
                    {"doc_id": "12", "record_count": 0},
                    {"doc_id": "99", "record_count": 4},
                ])
            if "IS NULL" in query:
                return NeoResult(count=0)
            if "MATCH (n)" in query:
                return NeoResult(count=8)
            return NeoResult(count=4)

    class NeoDriver:
        def session(self):
            return NeoSession()

    class Db:
        async def scalar(self, _statement):
            return 0

    monkeypatch.setattr(cleanup, "_count_mongo_contents", AsyncMock(return_value=({}, 0)))
    monkeypatch.setattr(cleanup, "_count_elasticsearch_documents", AsyncMock(return_value={}))
    monkeypatch.setattr(cleanup, "_count_milvus_vectors", AsyncMock(return_value={}))

    result = asyncio.run(cleanup._verify_targets(
        Db(),
        [{"id": 12, "content_id": 120}],
        es=object(),
        mongo_collection=object(),
        milvus=object(),
        neo_driver=NeoDriver(),
    ))

    assert result["passed"] is True
    assert result["remaining"]["neo4j_attributed_relationships"] == 0
    assert result["remaining"]["unattributed_neo4j_relationships"] == 0


def _preview(*, available=True, digest="a" * 64):
    return {
        "preview_sha256": digest,
        "cleanup_execution_available": available,
        "documents": [{
            "document_id": 12,
            "content_id": 120,
            "cleanup_target": True,
        }],
        "cleanup_target_totals": {"postgres_documents": 1},
        "neo4j_global_counts": {"nodes": 3},
    }


class _ExecutionDb:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        return None

    async def refresh(self, row):
        row.id = 44


class _MongoClient:
    def __getitem__(self, _name):
        return self

    async def close(self):
        return None


def _install_execution_fakes(monkeypatch, db, delete_document):
    mongo_client = _MongoClient()
    monkeypatch.setattr("pymongo.AsyncMongoClient", lambda _uri: mongo_client)
    monkeypatch.setattr(cleanup.es_client, "get_es", AsyncMock(return_value=object()))
    monkeypatch.setattr(cleanup.neo4j_client, "driver", object())
    monkeypatch.setattr(cleanup, "delete_knowledge_document", delete_document)
    monkeypatch.setattr(cleanup, "_verify_targets", AsyncMock(return_value={
        "passed": True,
        "remaining": {"postgres_documents": 0},
    }))


def test_cleanup_requires_phrase_fresh_preview_and_no_blockers(monkeypatch):
    db = _ExecutionDb()
    preview = AsyncMock(return_value=_preview(digest="b" * 64))
    monkeypatch.setattr(cleanup, "create_knowledge_cleanup_preview", preview)

    with pytest.raises(cleanup.CleanupConflict, match="二次确认"):
        asyncio.run(cleanup.execute_knowledge_cleanup(
            db,
            preview_sha256="b" * 64,
            confirmation_phrase="wrong",
            requested_by=7,
        ))
    preview.assert_not_awaited()

    with pytest.raises(cleanup.CleanupConflict, match="预览已变化"):
        asyncio.run(cleanup.execute_knowledge_cleanup(
            db,
            preview_sha256="a" * 64,
            confirmation_phrase=cleanup.CLEANUP_CONFIRMATION_PHRASE,
            requested_by=7,
        ))
    assert db.rows == []

    monkeypatch.setattr(cleanup, "create_knowledge_cleanup_preview", AsyncMock(return_value=_preview(available=False)))
    with pytest.raises(cleanup.CleanupConflict, match="安全阻断"):
        asyncio.run(cleanup.execute_knowledge_cleanup(
            db,
            preview_sha256="a" * 64,
            confirmation_phrase=cleanup.CLEANUP_CONFIRMATION_PHRASE,
            requested_by=7,
        ))
    assert db.rows == []


def test_cleanup_records_success_without_knowledge_body(monkeypatch):
    db = _ExecutionDb()
    monkeypatch.setattr(cleanup, "create_knowledge_cleanup_preview", AsyncMock(return_value=_preview()))

    async def delete_document(*_args, **_kwargs):
        return {"postgres_documents": 1, "milvus_vectors": 2}

    _install_execution_fakes(monkeypatch, db, delete_document)
    result = asyncio.run(cleanup.execute_knowledge_cleanup(
        db,
        preview_sha256="a" * 64,
        confirmation_phrase=cleanup.CLEANUP_CONFIRMATION_PHRASE,
        requested_by=7,
    ))

    assert result["execution_id"] == 44
    assert result["execution_status"] == "completed"
    assert result["deleted_counts"] == {"postgres_documents": 1, "milvus_vectors": 2}
    assert result["verification"]["passed"] is True
    assert db.rows[0].requested_by == 7
    assert "content" not in str(db.rows[0].result).lower()


def test_cleanup_records_partial_failure_for_safe_retry(monkeypatch):
    db = _ExecutionDb()
    monkeypatch.setattr(cleanup, "create_knowledge_cleanup_preview", AsyncMock(return_value=_preview()))

    async def fail_delete(*_args, **_kwargs):
        raise ConnectionError("store unavailable")

    _install_execution_fakes(monkeypatch, db, fail_delete)
    with pytest.raises(cleanup.CleanupExecutionFailure) as error:
        asyncio.run(cleanup.execute_knowledge_cleanup(
            db,
            preview_sha256="a" * 64,
            confirmation_phrase=cleanup.CLEANUP_CONFIRMATION_PHRASE,
            requested_by=7,
        ))

    assert error.value.execution_id == 44
    assert db.rows[0].execution_status == "failed"
    assert db.rows[0].result["failed_document_id"] == 12
    assert db.rows[0].result["failed_stage"] == "delete_document_stores"
    assert db.rows[0].result["failure_type"] == "ConnectionError"


def test_cleanup_records_verification_failure_without_attributing_it_to_last_document(monkeypatch):
    db = _ExecutionDb()
    monkeypatch.setattr(cleanup, "create_knowledge_cleanup_preview", AsyncMock(return_value=_preview()))

    async def delete_document(*_args, **_kwargs):
        return {"postgres_documents": 1}

    _install_execution_fakes(monkeypatch, db, delete_document)
    monkeypatch.setattr(cleanup, "_verify_targets", AsyncMock(return_value={
        "passed": False,
        "remaining": {"elasticsearch_documents": 1},
    }))

    with pytest.raises(cleanup.CleanupExecutionFailure) as error:
        asyncio.run(cleanup.execute_knowledge_cleanup(
            db,
            preview_sha256="a" * 64,
            confirmation_phrase=cleanup.CLEANUP_CONFIRMATION_PHRASE,
            requested_by=7,
        ))

    assert error.value.stage == "verify_deletions"
    assert db.rows[0].result["failed_document_id"] is None
    assert db.rows[0].result["verification"]["remaining"] == {"elasticsearch_documents": 1}
