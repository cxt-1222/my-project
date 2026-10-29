import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.knowledge_maintenance import knowledge_maintenance_router
from core.security import require_admin
from services import knowledge_cleanup_service
from services.knowledge_cleanup_service import _build_report


def test_cleanup_preview_contains_counts_without_document_bodies():
    report = _build_report(
        [{"id": 12, "title": "动作知识库 023", "author_id": 3, "team_id": 5}],
        mongo_counts={12: 1},
        elasticsearch_counts={12: 1},
        milvus_counts={12: 4},
        graph_mappings={12: {"mappings": 1, "entities": 3, "relationships": 2}},
        neo4j_relationship_counts={12: 2},
        unattributed_neo4j_relationships=0,
        neo4j_total_nodes=8,
        neo4j_total_relationships=5,
        ambiguous_mongo_records=0,
        orphan_graph_mappings=0,
    )

    assert report["mode"] == "read_only_preview"
    assert report["destructive"] is False
    assert report["cleanup_execution_available"] is False
    assert report["cleanup_target_classification_available"] is False
    assert report["document_count"] == 1
    assert report["documents"][0]["stores"] == {
        "postgres_documents": 1,
        "mongodb_contents": 1,
        "elasticsearch_documents": 1,
        "milvus_vectors": 4,
        "postgres_graph_mappings": 1,
        "postgres_graph_entities": 3,
        "postgres_graph_relationships": 2,
        "neo4j_attributed_relationships": 2,
    }
    assert report["totals"]["milvus_vectors"] == 4
    assert report["neo4j_global_counts"] == {"nodes": 8, "relationships": 5}
    assert "content" not in report["documents"][0]
    assert report["documents"][0]["cleanup_classification"] == "unclassified"
    assert any("来源映射不明确" in blocker for blocker in report["blockers"])
    assert len(report["preview_sha256"]) == 64


def test_cleanup_preview_flags_neo4j_relationships_without_document_ownership():
    report = _build_report(
        [],
        mongo_counts={},
        elasticsearch_counts={},
        milvus_counts={},
        graph_mappings={},
        neo4j_relationship_counts={},
        unattributed_neo4j_relationships=7,
        neo4j_total_nodes=0,
        neo4j_total_relationships=7,
        ambiguous_mongo_records=0,
        orphan_graph_mappings=0,
    )

    assert report["cleanup_execution_available"] is False
    assert report["unattributed_neo4j_relationships"] == 7
    assert any("source_doc_id" in blocker for blocker in report["blockers"])


def test_cleanup_preview_flags_graph_mappings_without_documents():
    report = _build_report(
        [],
        mongo_counts={},
        elasticsearch_counts={},
        milvus_counts={},
        graph_mappings={},
        neo4j_relationship_counts={},
        unattributed_neo4j_relationships=0,
        neo4j_total_nodes=0,
        neo4j_total_relationships=0,
        ambiguous_mongo_records=0,
        orphan_graph_mappings=2,
    )

    assert report["orphan_postgres_graph_mappings"] == 2
    assert any("找不到对应知识文档" in blocker for blocker in report["blockers"])


def test_neo4j_counts_are_not_duplicated_and_unknown_owners_are_blocked():
    class Result:
        def __init__(self, *, rows=None, single=None):
            self.rows = rows or []
            self.single_row = single

        async def data(self):
            return self.rows

        async def single(self):
            return self.single_row

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def run(self, query):
            if "IS NOT NULL" in query:
                return Result(rows=[
                    {"doc_id": "12", "record_count": 2},
                    {"doc_id": "999", "record_count": 3},
                    {"doc_id": "unknown", "record_count": 1},
                ])
            if "IS NULL" in query:
                return Result(single={"record_count": 4})
            if "MATCH (n)" in query:
                return Result(single={"record_count": 9})
            return Result(single={"record_count": 14})

    class Driver:
        def session(self):
            return Session()

    original_driver = knowledge_cleanup_service.neo4j_client.driver
    knowledge_cleanup_service.neo4j_client.driver = Driver()
    try:
        counts, unresolved, node_total, relationship_total = asyncio.run(
            knowledge_cleanup_service._count_neo4j_relationships({12})
        )
    finally:
        knowledge_cleanup_service.neo4j_client.driver = original_driver

    assert counts == {12: 2}
    assert unresolved == 8
    assert node_total == 9
    assert relationship_total == 14


def test_cleanup_preview_route_requires_system_admin_role():
    route = next(
        route for route in knowledge_maintenance_router.routes
        if route.path.endswith("/cleanup-preview")
    )

    assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)
    assert "GET" in route.methods
    assert "DELETE" not in route.methods

    cleanup_route = next(
        route for route in knowledge_maintenance_router.routes
        if route.path.endswith("/cleanup")
    )
    assert any(dependency.call is require_admin for dependency in cleanup_route.dependant.dependencies)
    assert "POST" in cleanup_route.methods


def test_cleanup_preview_reads_all_stores_without_fetching_knowledge_bodies():
    async def run_preview():
        document = SimpleNamespace(
            id=12, title="动作知识库 023", content_id=120,
            author_id=3, team_id=5,
        )
        graph_mapping = SimpleNamespace(
            doc_id=12,
            entities=[{"name": "侧平举"}],
            relationships=[{"sourceName": "侧平举", "targetName": "三角肌"}],
        )
        source_mapping = SimpleNamespace(
            document_id=12,
            mapping_status="active",
            import_status="imported",
            metadata_license_status="approved",
        )

        class Db:
            def __init__(self):
                self.calls = 0

            async def execute(self, _statement):
                self.calls += 1
                rows = {
                    1: [document],
                    2: [source_mapping],
                    3: [graph_mapping],
                }[self.calls]
                return SimpleNamespace(all=lambda: rows)

        class Cursor:
            def __init__(self, rows):
                self.rows = iter(rows)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.rows)
                except StopIteration:
                    raise StopAsyncIteration

        class Collection:
            def find(self, query, projection):
                assert query["$or"]
                assert set(projection) == {"_id", "document_id"}
                assert "content" not in projection
                return Cursor([{"_id": 120, "document_id": 12}])

        class MongoClient:
            def __getitem__(self, _name):
                return {"document_content": Collection()}

            async def close(self):
                return None

        class NeoResult:
            def __init__(self, rows=None, single=None):
                self.rows = rows or []
                self.single_row = single

            async def data(self):
                return self.rows

            async def single(self):
                return self.single_row

        class NeoSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def run(self, query):
                if "IS NOT NULL" in query:
                    return NeoResult(rows=[{"doc_id": "12", "record_count": 2}])
                if "IS NULL" in query or "MATCH (n)" in query:
                    return NeoResult(single={"record_count": 0})
                return NeoResult(single={"record_count": 2})

        class NeoDriver:
            def session(self):
                return NeoSession()

        es = SimpleNamespace(mget=AsyncMock(return_value={
            "docs": [{"_id": "12", "found": True}],
        }))
        milvus = SimpleNamespace(query=AsyncMock(return_value=[
            {"content_id": "12-0"},
            {"content_id": "12-1"},
        ]))
        mongo = MongoClient()

        with (
            patch("pymongo.AsyncMongoClient", return_value=mongo),
            patch.object(knowledge_cleanup_service.es_client, "get_es", AsyncMock(return_value=es)),
            patch.object(knowledge_cleanup_service, "milvus_client", milvus),
            patch.object(knowledge_cleanup_service.neo4j_client, "driver", NeoDriver()),
        ):
            report = await knowledge_cleanup_service.create_knowledge_cleanup_preview(Db())

        assert report["document_count"] == 1
        assert report["cleanup_target_count"] == 0
        assert report["cleanup_execution_available"] is True
        assert report["documents"][0]["cleanup_classification"] == "approved_catalog_document"
        assert report["documents"][0]["cleanup_target"] is False
        assert report["neo4j_global_counts"] == {"nodes": 0, "relationships": 2}
        assert report["documents"][0]["stores"] == {
            "postgres_documents": 1,
            "mongodb_contents": 1,
            "elasticsearch_documents": 1,
            "milvus_vectors": 2,
            "postgres_graph_mappings": 1,
            "postgres_graph_entities": 1,
            "postgres_graph_relationships": 1,
            "neo4j_attributed_relationships": 2,
        }
        es.mget.assert_awaited_once_with(
            index=knowledge_cleanup_service.settings.INDEX_NAME,
            ids=["12"],
            source=False,
        )
        milvus.query.assert_awaited_once()

    asyncio.run(run_preview())
