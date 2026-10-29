import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import rollback_pinned_dataset as rollback


REVISION = "a" * 40


class _Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def all(self):
        return self.rows


class _Session:
    def __init__(self, *, documents=None):
        self.source = SimpleNamespace(
            id=7,
            dataset="fixture",
            revision=REVISION,
            import_status="imported",
            updated_at=None,
        )
        self.documents = documents if documents is not None else [SimpleNamespace(
            document_id=12,
            content_id=120,
            title="动作：深蹲",
            mapping_status="active",
        )]
        self.progress_rows = [SimpleNamespace(
            checkpoint={"import_cursor": "record-4"},
            progress_status="completed",
            last_error="",
            completed_at="import-completed",
            updated_at=None,
        )]
        self.execute_calls = []
        self.reset_query_results()
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def scalar(self, _statement):
        return next(self.scalar_results)

    def reset_query_results(self):
        self.scalar_results = iter([self.source, 0, 2, 0, 0])
        self.execute_calls.clear()

    async def execute(self, statement):
        self.execute_calls.append(statement)
        if len(self.execute_calls) == 1:
            return _Result(self.documents)
        return SimpleNamespace(rowcount=1)

    async def get(self, model, row_id):
        assert row_id == 7
        return self.source

    async def scalars(self, _statement):
        return self.progress_rows

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def test_rollback_preview_is_read_only_and_contains_hash(monkeypatch):
    session = _Session()
    monkeypatch.setattr(rollback, "SessionLocal", lambda: session)

    result = asyncio.run(rollback.rollback_pinned_dataset(
        "fixture",
        REVISION,
        apply=False,
    ))

    assert result["mode"] == "read_only_preview"
    assert result["apply_available"] is True
    assert result["document_count"] == 1
    assert result["preview_sha256"]
    assert "content" not in str(result).lower()
    assert session.commits == 0


def test_rollback_requires_exact_confirmation_and_fresh_preview(monkeypatch):
    session = _Session()
    monkeypatch.setattr(rollback, "SessionLocal", lambda: session)
    with pytest.raises(ValueError, match="--confirm"):
        asyncio.run(rollback.rollback_pinned_dataset(
            "fixture",
            REVISION,
            apply=True,
            preview_sha256="unused",
            confirmation="wrong",
        ))
    assert session.commits == 0

    session.reset_query_results()
    with pytest.raises(ValueError, match="预览已变化"):
        asyncio.run(rollback.rollback_pinned_dataset(
            "fixture",
            REVISION,
            apply=True,
            preview_sha256="0" * 64,
            confirmation=rollback._confirmation("fixture", REVISION),
        ))
    assert session.commits == 0


def test_rollback_disables_only_pinned_revision_and_deletes_mapped_docs(monkeypatch):
    session = _Session()
    monkeypatch.setattr(rollback, "SessionLocal", lambda: session)

    class _MongoClient:
        admin = SimpleNamespace(command=AsyncMock())

        def __getitem__(self, _name):
            return self

        async def close(self):
            return None

    mongo = _MongoClient()
    es = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("pymongo.AsyncMongoClient", lambda _uri: mongo)
    monkeypatch.setattr(rollback.es_client, "get_es", AsyncMock(return_value=es))
    monkeypatch.setattr(rollback.neo4j_client, "driver", object())
    monkeypatch.setattr(rollback.milvus_client, "close", AsyncMock())

    deleted = []

    async def delete_document(_session, document, **_kwargs):
        deleted.append(document["id"])
        return {"elasticsearch_documents": 1, "milvus_vectors": 2}

    monkeypatch.setattr(rollback, "delete_knowledge_document", delete_document)
    preview = asyncio.run(rollback.rollback_pinned_dataset(
        "fixture",
        REVISION,
        apply=False,
    ))
    session.commits = 0
    session.reset_query_results()

    result = asyncio.run(rollback.rollback_pinned_dataset(
        "fixture",
        REVISION,
        apply=True,
        preview_sha256=preview["preview_sha256"],
        confirmation=rollback._confirmation("fixture", REVISION),
    ))

    assert session.source.import_status == "disabled"
    assert deleted == [12]
    assert result["completed_document_ids"] == [12]
    assert result["deleted_counts"] == {"elasticsearch_documents": 1, "milvus_vectors": 2}
    assert session.commits >= 2
    progress = session.progress_rows[0]
    assert progress.progress_status == "completed"
    assert progress.completed_at == "import-completed"
    assert progress.checkpoint == {
        "import_cursor": "record-4",
        "rollback": {
            "status": "completed",
            "completed_document_ids": [12],
            "deleted_counts": {"elasticsearch_documents": 1, "milvus_vectors": 2},
        },
    }


def test_rollback_rejects_non_commit_revision():
    with pytest.raises(ValueError, match="完整的 40 位"):
        asyncio.run(rollback.rollback_pinned_dataset(
            "fixture",
            "main",
            apply=False,
        ))
