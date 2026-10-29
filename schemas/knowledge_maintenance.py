from typing import Literal

from pydantic import BaseModel, Field


class CleanupStoreCounts(BaseModel):
    postgres_documents: int
    mongodb_contents: int
    elasticsearch_documents: int
    milvus_vectors: int
    postgres_graph_mappings: int
    postgres_graph_entities: int
    postgres_graph_relationships: int
    neo4j_attributed_relationships: int


class CleanupPreviewDocument(BaseModel):
    document_id: int
    content_id: int | str | None
    title: str | None
    author_id: int | None
    team_id: int | None
    cleanup_classification: str
    cleanup_target: bool
    stores: CleanupStoreCounts


class Neo4jGlobalCounts(BaseModel):
    nodes: int
    relationships: int


class KnowledgeCleanupPreviewResponse(BaseModel):
    mode: Literal["read_only_preview"]
    destructive: bool
    cleanup_execution_available: bool
    cleanup_target_classification_available: bool
    document_count: int
    cleanup_target_count: int
    documents: list[CleanupPreviewDocument]
    totals: dict[str, int]
    cleanup_target_totals: dict[str, int]
    unattributed_neo4j_relationships: int
    neo4j_global_counts: Neo4jGlobalCounts
    ambiguous_mongodb_records: int
    orphan_postgres_graph_mappings: int
    unclassified_document_mappings: int
    blockers: list[str]
    notice: str
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeCleanupRequest(BaseModel):
    preview_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="cleanup-preview 返回的 preview_sha256；预览变化后需重新获取",
    )
    confirmation_phrase: str = Field(
        description="必须填写：确认清理预览中的全部旧知识文档",
    )


class CleanupVerificationResponse(BaseModel):
    passed: bool
    remaining: dict[str, int]


class KnowledgeCleanupResult(BaseModel):
    execution_id: int
    execution_status: Literal["completed"]
    target_document_ids: list[int]
    expected_counts: dict[str, int]
    deleted_counts: dict[str, int]
    completed_document_ids: list[int]
    verification: CleanupVerificationResponse
    preserved_shared_neo4j_nodes: int
