from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace

import pytest

from models.dataset_catalog import DatasetImportModel, DatasetImportProgressModel, KnowledgeSourceMappingModel
from models.document import KhDocument
from scripts import import_pinned_knowledge as importer
from utils.fitness_knowledge import KnowledgeDocument


class MemoryDatabase:
    def __init__(self):
        self.rows = defaultdict(list)
        self.next_ids = defaultdict(lambda: 1)


class MemoryAsyncSession:
    def __init__(self, database: MemoryDatabase):
        self.database = database

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def scalar(self, statement):
        model = statement.column_descriptions[0]["entity"]
        criteria = {}
        for expression in statement._where_criteria:
            expressions = getattr(expression, "clauses", [expression])
            for item in expressions:
                if hasattr(item, "left") and hasattr(item.right, "value"):
                    criteria[item.left.name] = item.right.value
        return next(
            (row for row in self.database.rows[model]
             if all(getattr(row, key) == value for key, value in criteria.items())),
            None,
        )

    def add(self, row):
        self.database.rows[type(row)].append(row)

    async def flush(self):
        for model, rows in self.database.rows.items():
            for row in rows:
                if hasattr(row, "id") and row.id is None:
                    row.id = self.database.next_ids[model]
                    self.database.next_ids[model] += 1

    async def commit(self):
        await self.flush()

    async def rollback(self):
        return None

    async def get(self, model, row_id):
        return next(
            (row for row in self.database.rows[model] if row.id == row_id),
            None,
        )

    async def refresh(self, _row):
        return None


def _fixture():
    doc = KnowledgeDocument(
        source="fixture:exercise",
        source_key="revision-1:exercise:squat-1",
        title="健身动作：深蹲",
        content="动作名称：深蹲\n动作要点：保持躯干稳定。",
        entities=[{"label": "健身动作", "name": "深蹲"}],
    )
    record = SimpleNamespace(
        dataset="fixture",
        revision="revision-1",
        record_kind="exercise",
        source_record_id="squat-1",
        content_sha256="a" * 64,
        document=doc,
    )
    plan = SimpleNamespace(files=[{"dataset": "fixture", "commit": "revision-1"}])
    return record, plan


def _database():
    database = MemoryDatabase()
    database.rows[DatasetImportModel].append(SimpleNamespace(
        id=7,
        dataset="fixture",
        revision="revision-1",
        import_status="imported",
        updated_at=None,
    ))
    return database


def test_preflight_failure_writes_no_rag_data_and_closes_resources(monkeypatch, tmp_path):
    database = _database()
    monkeypatch.setattr("core.database.SessionLocal", lambda: MemoryAsyncSession(database))
    cleanup_calls = []

    async def fail_preflight(_author_id, resources):
        resources["partial_client"] = object()
        raise RuntimeError("Milvus 集合不兼容")

    async def cleanup(resources):
        cleanup_calls.append(resources.copy())

    async def unexpected_write(*_args, **_kwargs):
        raise AssertionError("预检查失败后不应写入知识存储")

    monkeypatch.setattr(importer, "_preflight", fail_preflight)
    monkeypatch.setattr(importer, "_cleanup_resources", cleanup)
    for name in ("_ensure_document", "_upsert_mongo", "_replace_milvus_vectors", "_upsert_es", "_upsert_graph"):
        monkeypatch.setattr(importer, name, unexpected_write)

    record, plan = _fixture()
    with pytest.raises(RuntimeError, match="Milvus 集合不兼容"):
        asyncio.run(importer.import_knowledge_records([record], plan, 9, tmp_path / "manifest.json"))

    assert database.rows[KhDocument] == []
    assert database.rows[KnowledgeSourceMappingModel] == []
    assert database.rows[DatasetImportProgressModel] == []
    assert database.rows[DatasetImportModel][0].import_status == "failed"
    assert len(cleanup_calls) == 1


def test_partial_storage_failure_can_be_retried_with_same_document_id(monkeypatch, tmp_path):
    database = _database()
    monkeypatch.setattr("core.database.SessionLocal", lambda: MemoryAsyncSession(database))
    cleanup_calls = []
    mongo_document_ids = []
    events = []
    es_attempts = 0

    class FakeEsIndices:
        async def refresh(self, *, index):
            return None

    class FakeEs:
        def __init__(self):
            self.docs = {}
            self.indices = FakeEsIndices()
            self.fail_publication = False

        async def update(self, *, index, id, doc):
            if doc["is_public"] and self.fail_publication:
                self.fail_publication = False
                raise RuntimeError("temporary ES publish failure")
            self.docs[id].update(doc)
            events.append("es_publish" if doc["is_public"] else "es_unpublish")

    fake_es = FakeEs()

    async def preflight(_author_id, resources):
        resources.update(es=fake_es, neo_driver=object())

    async def cleanup(resources):
        cleanup_calls.append(resources.copy())

    async def mongo_upsert(doc_id, _doc):
        mongo_document_ids.append(doc_id)

    async def milvus_replace(_doc_id, _doc, chunks):
        return len(chunks)

    async def flow_status(_doc_id, _flow, _status):
        return None

    async def es_upsert(doc_id, _author_id, _doc, _es, *, published):
        nonlocal es_attempts
        assert published is False
        es_attempts += 1
        if es_attempts == 1:
            raise RuntimeError("temporary ES write failure")
        fake_es.docs[doc_id] = {"status": 0, "is_public": False, "publish_time": None}
        events.append("es_content")

    async def graph_upsert(_doc_id, _doc, _driver):
        events.append("neo4j")

    real_set_document_published = importer._set_document_published

    async def set_document_published(doc_id, published):
        if published:
            events.append("pg_publish")
        await real_set_document_published(doc_id, published)

    real_ensure_mapping = importer._ensure_mapping

    async def ensure_mapping(import_id, record, document_id):
        events.append("source_mapping")
        await real_ensure_mapping(import_id, record, document_id)

    monkeypatch.setattr(importer, "_preflight", preflight)
    monkeypatch.setattr(importer, "_cleanup_resources", cleanup)
    monkeypatch.setattr(importer, "_upsert_mongo", mongo_upsert)
    monkeypatch.setattr(importer, "_replace_milvus_vectors", milvus_replace)
    monkeypatch.setattr(importer, "_set_flow", flow_status)
    monkeypatch.setattr(importer, "_upsert_es", es_upsert)
    monkeypatch.setattr(importer, "_upsert_graph", graph_upsert)
    monkeypatch.setattr(importer, "_set_document_published", set_document_published)
    monkeypatch.setattr(importer, "_ensure_mapping", ensure_mapping)

    record, plan = _fixture()
    manifest_path = tmp_path / "manifest.json"
    with pytest.raises(RuntimeError, match="Elasticsearch 索引失败.*temporary ES write failure"):
        asyncio.run(importer.import_knowledge_records([record], plan, 9, manifest_path))

    progress = {row.storage_name: row for row in database.rows[DatasetImportProgressModel]}
    assert progress["mongodb"].processed_records == 1
    assert progress["milvus"].processed_records == 1
    assert progress["elasticsearch"].progress_status == "failed"
    assert progress["elasticsearch"].failed_records == 1
    assert progress["elasticsearch"].checkpoint == {"failed_record_key": "squat-1"}
    assert progress["neo4j"].processed_records == 0
    assert database.rows[KhDocument][0].id == 1
    assert database.rows[KhDocument][0].status == 0
    assert database.rows[KhDocument][0].is_public == 0
    assert database.rows[DatasetImportModel][0].import_status == "failed"

    result = asyncio.run(importer.import_knowledge_records([record], plan, 9, manifest_path))
    result_again = asyncio.run(importer.import_knowledge_records([record], plan, 9, manifest_path))

    fake_es.fail_publication = True
    with pytest.raises(RuntimeError, match="Elasticsearch 索引失败.*temporary ES publish failure"):
        asyncio.run(importer.import_knowledge_records([record], plan, 9, manifest_path))
    assert database.rows[KhDocument][0].status == 0
    assert database.rows[KhDocument][0].is_public == 0
    assert fake_es.docs[1]["is_public"] is False

    recovered = asyncio.run(importer.import_knowledge_records([record], plan, 9, manifest_path))

    assert result["processed"] == result_again["processed"] == 1
    assert recovered["processed"] == 1
    assert mongo_document_ids == [1, 1, 1, 1, 1]
    assert len(database.rows[KhDocument]) == 1
    assert len(database.rows[KnowledgeSourceMappingModel]) == 1
    assert database.rows[KnowledgeSourceMappingModel][0].document_id == 1
    assert database.rows[DatasetImportModel][0].import_status == "imported"
    assert database.rows[KhDocument][0].status == 1
    assert database.rows[KhDocument][0].is_public == 1
    assert fake_es.docs[1]["status"] == 1
    assert fake_es.docs[1]["is_public"] is True
    assert events.index("neo4j") < events.index("source_mapping") < events.index("pg_publish") < events.index("es_publish")
    assert all(row.progress_status == "completed" for row in progress.values())
    assert all(row.processed_records == 1 for row in progress.values())
    assert len(cleanup_calls) == 5


def test_milvus_retry_filter_preserves_other_documents(monkeypatch):
    from clients import milvus_client as milvus_module

    class FakeMilvus:
        def __init__(self):
            self.rows = [
                {"content_id": "42-0", "content": "old imported chunk"},
                {"content_id": "999-0", "content": "unrelated document"},
            ]
            self.filters = []

        async def delete(self, *, collection_name, filter):
            self.filters.append(filter)
            prefix = filter.split('"')[1].removesuffix("%")
            self.rows = [row for row in self.rows if not row["content_id"].startswith(prefix)]

        async def flush(self, *, collection_name):
            return None

        async def insert(self, *, collection_name, data):
            self.rows.extend(data)

    class FakeEmbeddings:
        async def aembed_documents(self, chunks):
            return [[0.1, 0.2] for _ in chunks]

    milvus = FakeMilvus()
    monkeypatch.setattr(milvus_module, "milvus_client", milvus)
    monkeypatch.setattr(milvus_module, "embddings_model", FakeEmbeddings())
    record, _ = _fixture()

    asyncio.run(importer._replace_milvus_vectors(42, record.document, ["new imported chunk"]))

    assert milvus.filters == ['content_id like "42-%"']
    assert {row["content_id"] for row in milvus.rows} == {"42-0", "999-0"}
    assert next(row for row in milvus.rows if row["content_id"] == "999-0")["content"] == "unrelated document"
