"""Import the selected fitness datasets into this project's existing RAG/graph stores.

Dry-run is the default. No database client is imported or initialized unless --apply
is explicitly supplied. Existing Milvus collections/indexes are never created,
dropped, or rebuilt by this script.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow the documented ``python scripts/import_fitness_knowledge.py`` invocation
# to import project packages when Python sets sys.path[0] to the scripts folder.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.text_chunking import split_knowledge_text
from utils.fitness_knowledge import (
    KnowledgeDocument,
    build_exercise_documents,
    build_fitkg_documents,
    load_json_file,
)


def default_manifest_path() -> Path:
    """Keep the resume manifest outside the repository and away from Git commits."""
    return Path.home() / ".knowledge-agent" / "fitness-knowledge-import-manifest.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"导入清单不可读取，请先备份并修复：{path} ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("items"), dict):
        raise RuntimeError(f"导入清单格式不受支持：{path}")
    return data


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def _format_stats(name: str, stats: Any, docs: list[KnowledgeDocument]) -> None:
    print(
        f"{name}: 输入 {stats.total_records} 条，转换 {stats.accepted_records} 条，"
        f"去重 {stats.duplicate_records} 条，跳过异常 {stats.invalid_records} 条，"
        f"无效实体跨度 {stats.invalid_spans} 个，无效关系 {stats.invalid_relations} 条，"
        f"生成 {len(docs)} 个文档。"
    )
    print(
        f"  图谱实体 {sum(len(doc.entities) for doc in docs)} 个，"
        f"关系 {sum(len(doc.relationships) for doc in docs)} 条。"
    )


def build_import_documents(args: argparse.Namespace) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    if args.exercises_json:
        data, digest = load_json_file(args.exercises_json)
        current, stats = build_exercise_documents(
            data, source_digest=digest, group_size=args.exercise_group_size
        )
        print(f"数据文件：{Path(args.exercises_json).resolve()}")
        _format_stats("exercises-dataset", stats, current)
        documents.extend(current)

    for partition, raw_path in (("train", args.fitkg_train), ("dev", args.fitkg_dev)):
        if not raw_path:
            continue
        data, digest = load_json_file(raw_path)
        current, stats = build_fitkg_documents(
            data, source_digest=digest, partition=partition, group_size=args.fitkg_group_size
        )
        print(f"数据文件：{Path(raw_path).resolve()}")
        _format_stats(f"FitKG-CN/{partition}", stats, current)
        documents.extend(current)

    if args.max_docs is not None:
        if args.max_docs < 1:
            raise ValueError("--max-docs 必须大于 0")
        documents = documents[:args.max_docs]
        print(f"试运行限制：本次最多处理前 {len(documents)} 个文档。")
    if not documents:
        raise ValueError("没有生成可导入文档；请确认 JSON 路径和数据内容。")
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将动作库/FitKG-CN 转成中文知识文档，导入 Elasticsearch、Milvus、MongoDB、PostgreSQL 和 Neo4j。"
    )
    parser.add_argument("--exercises-json", help="exercises-dataset 的 JSON 文件路径")
    parser.add_argument("--fitkg-train", help="FitKG-CN train.json 文件路径")
    parser.add_argument("--fitkg-dev", help="可选：FitKG-CN dev.json 文件路径")
    parser.add_argument("--exercise-group-size", type=int, default=25, help="每个动作库文档合并的动作数（默认 25）")
    parser.add_argument("--fitkg-group-size", type=int, default=100, help="每个 FitKG 文档合并的样例数（默认 100）")
    parser.add_argument("--author-id", type=int, help="现有 PostgreSQL 用户 ID；正式导入必填")
    parser.add_argument("--manifest", type=Path, default=default_manifest_path(), help="断点续跑清单路径")
    parser.add_argument("--max-docs", type=int, help="仅处理前 N 个文档，可用于正式导入前做小批试运行")
    parser.add_argument("--apply", action="store_true", help="正式写入数据库；默认仅 dry-run")
    args = parser.parse_args()
    if not any((args.exercises_json, args.fitkg_train, args.fitkg_dev)):
        parser.error("至少提供 --exercises-json、--fitkg-train 或 --fitkg-dev 之一")
    if args.apply and args.author_id is None:
        parser.error("正式导入必须指定现有用户 --author-id")
    if args.exercise_group_size < 1 or args.fitkg_group_size < 1:
        parser.error("group-size 必须大于 0")
    return args


def _chunk_text(content: str) -> list[str]:
    """Use the same metadata-preserving chunking as the normal document pipeline."""
    return split_knowledge_text(content)


def _entity_key(entity: dict[str, Any]) -> str:
    label = str(entity.get("label") or "Entity").strip()
    name = str(entity.get("name") or "").strip()
    return hashlib.sha256(f"{label}\0{name}".encode("utf-8")).hexdigest()


def _neo4j_entities_and_relationships(doc: KnowledgeDocument) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    entities = [
        {"key": _entity_key(entity), "name": str(entity["name"]), "label": str(entity.get("label") or "Entity")}
        for entity in doc.entities
        if entity.get("name")
    ]
    key_by_label_name = {
        (item["label"], item["name"]): item["key"] for item in entities
    }
    relationships: list[dict[str, str]] = []
    for rel in doc.relationships:
        source_label = str(rel.get("sourceLabel") or "Entity")
        source_name = str(rel.get("sourceName") or "")
        target_label = str(rel.get("targetLabel") or "Entity")
        target_name = str(rel.get("targetName") or "")
        source_key = key_by_label_name.get((source_label, source_name))
        target_key = key_by_label_name.get((target_label, target_name))
        if not source_key or not target_key:
            continue
        relationships.append({
            "source_key": source_key,
            "target_key": target_key,
            "name": str(rel.get("relName") or "RELATED_TO"),
        })
    return entities, relationships


async def _close_maybe_async(obj: Any) -> None:
    if obj is None:
        return
    close = getattr(obj, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _milvus_fields(description: Any) -> dict[str, dict[str, Any]]:
    """Normalize MilvusClient describe_collection field shapes across SDK versions."""
    if not isinstance(description, dict):
        raise RuntimeError("Milvus describe_collection 返回格式不是对象；为避免误写，已停止。")
    raw_fields = description.get("fields")
    if not isinstance(raw_fields, list):
        schema = description.get("schema")
        raw_fields = schema.get("fields") if isinstance(schema, dict) else None
    if not isinstance(raw_fields, list):
        raise RuntimeError("无法从 Milvus 集合描述中读取 fields；为避免误写，已停止。")

    normalized: dict[str, dict[str, Any]] = {}
    for field in raw_fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name") or field.get("fieldName") or field.get("field_name")
        if not name:
            continue
        params = field.get("params") or field.get("type_params") or field.get("typeParams") or {}
        if isinstance(params, list):
            params = {
                item.get("key"): item.get("value")
                for item in params
                if isinstance(item, dict) and item.get("key") is not None
            }
        normalized[str(name)] = {**field, "params": params if isinstance(params, dict) else {}}
    return normalized


async def _preflight(author_id: int, resources: dict[str, Any]) -> None:
    """Connect and verify existing stores without creating or dropping schema.

    Populate ``resources`` immediately as clients are created so run_apply can close
    everything even when a later connection or compatibility check fails.
    """
    from sqlalchemy import select, text

    from clients import es_client, neo4j_client
    from clients.milvus_client import (
        describe_milvus_collection,
        has_milvus_collection,
        milvus_client,
    )
    from clients.es_client import init_es
    from core.config import settings
    from core.database import SessionLocal, engine
    from models import GraphDocModel, KHDocument, UserModel
    from beanie import init_beanie
    from pymongo import AsyncMongoClient

    resources["engine"] = engine
    resources["milvus_client"] = milvus_client
    resources["es_module"] = es_client
    resources["neo4j_module"] = neo4j_client

    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
        user = await session.get(UserModel, author_id)
        if user is None:
            raise RuntimeError(f"PostgreSQL 中不存在 author-id={author_id} 的用户。")
        # A SELECT confirms the graph metadata table exists; migrations are never
        # run implicitly by this importer.
        await session.execute(select(GraphDocModel.id).limit(1))

    mongo_client = AsyncMongoClient(settings.MONGO_URI)
    resources["mongo_client"] = mongo_client
    await init_beanie(database=mongo_client[settings.DB_NAME], document_models=[KHDocument])
    await mongo_client.admin.command("ping")

    try:
        resources["es"] = await init_es()
    except Exception:
        # init_es stores its client before pinging; retain it for cleanup on failure.
        resources["es"] = es_client.es
        raise
    if not await resources["es"].indices.exists(index=settings.INDEX_NAME):
        raise RuntimeError(
            f"Elasticsearch 索引 {settings.INDEX_NAME!r} 不存在；请先按项目现有方式初始化 ES 索引。"
        )

    if not await has_milvus_collection(collection_name=settings.COLLECTION_NAME):
        raise RuntimeError(
            f"Milvus 集合 {settings.COLLECTION_NAME!r} 不存在；请先用项目现有流程创建。"
        )
    fields = _milvus_fields(
        await describe_milvus_collection(collection_name=settings.COLLECTION_NAME)
    )
    required_fields = {"vector", "title", "content_id", "content"}
    missing = required_fields - fields.keys()
    if missing:
        raise RuntimeError(f"Milvus 集合字段不兼容，缺少：{', '.join(sorted(missing))}；不会重建集合。")
    vector_params = fields["vector"].get("params") or {}
    vector_dim = vector_params.get("dim")
    if vector_dim is None:
        raise RuntimeError("无法确认 Milvus vector 维度；为避免写入不兼容向量，已停止。")
    if int(vector_dim) != int(settings.DIMENSIONS):
        raise RuntimeError(
            f"Milvus vector 维度为 {vector_dim}，配置 DIMENSIONS={settings.DIMENSIONS}；不会重建集合。"
        )

    try:
        resources["neo_driver"] = await neo4j_client.init_neo4j_driver()
    except Exception:
        # The project client stores the driver before verifying connectivity.
        resources["neo_driver"] = neo4j_client.driver
        raise
    print(
        f"预检查通过：PostgreSQL、MongoDB、Elasticsearch[{settings.INDEX_NAME}]、"
        f"Milvus[{settings.COLLECTION_NAME}]、Neo4j。"
    )
    print("安全检查：不会创建/删除 Milvus 集合；不会清空或覆盖现有知识库。")


async def _ensure_document(
    doc: KnowledgeDocument,
    author_id: int,
    manifest: dict[str, Any],
    manifest_path: Path,
    *,
    published: bool = True,
) -> int:
    from core.database import SessionLocal
    from models import KhDocument

    import_key = doc.import_key
    existing_id = manifest["items"].get(import_key)
    async with SessionLocal() as session:
        row = await session.get(KhDocument, int(existing_id)) if existing_id else None
        if row is None:
            now = datetime.now()
            row = KhDocument(
                title=doc.title[:50],
                content_id=None,
                summary=doc.content[:100],
                doc_type="nutrition" if doc.knowledge_domain == "饮食知识" else "fitness",
                status=1 if published else 0,
                publish_time=now if published else None,
                create_at=now,
                author_id=author_id,
                team_id=None,
                is_public=1 if published else 0,
                idx_status=0,
                rag_status=0,
                kg_status=0,
            )
            session.add(row)
            await session.flush()
            row.content_id = row.id
            await session.commit()
            await session.refresh(row)
            manifest["items"][import_key] = int(row.id)
            _write_manifest(manifest_path, manifest)
            return int(row.id)

        # The manifest maps one stable source-content key to the same DB document
        # on every retry. Refresh the metadata without changing its document ID.
        row.title = doc.title[:50]
        row.summary = doc.content[:100]
        row.doc_type = "nutrition" if doc.knowledge_domain == "饮食知识" else "fitness"
        row.status = 1 if published else 0
        row.publish_time = datetime.now() if published else None
        row.is_public = 1 if published else 0
        row.author_id = author_id
        await session.commit()
        return int(row.id)


async def _upsert_mongo(doc_id: int, doc: KnowledgeDocument) -> None:
    from datetime import datetime

    from models import KHDocument

    now = datetime.now()
    current = await KHDocument.get(doc_id)
    if current is None:
        current = KHDocument(
            id=doc_id,
            document_id=doc_id,
            content=doc.content,
            content_len=len(doc.content),
            content_summary=doc.content[:500],
            create_at=now,
            update_at=now,
        )
        await current.insert()
        return
    current.document_id = doc_id
    current.content = doc.content
    current.content_len = len(doc.content)
    current.content_summary = doc.content[:500]
    current.update_at = now
    await current.save()


async def _replace_milvus_vectors(doc_id: int, doc: KnowledgeDocument, chunks: list[str]) -> int:
    from clients.milvus_client import embddings_model, milvus_client
    from core.config import settings

    if not chunks:
        raise RuntimeError(f"文档 {doc.title} 没有可向量化的文本块。")
    # Delete only this imported document's own {doc_id}-{chunk_index} rows, so a
    # retry after a partial insert is idempotent and other documents are untouched.
    prefix_filter = f'content_id like "{doc_id}-%"'
    await milvus_client.delete(collection_name=settings.COLLECTION_NAME, filter=prefix_filter)
    await milvus_client.flush(collection_name=settings.COLLECTION_NAME)

    vectors: list[list[float]] = []
    for offset in range(0, len(chunks), 10):
        vectors.extend(await embddings_model.aembed_documents(chunks[offset:offset + 10]))
    if len(vectors) != len(chunks):
        raise RuntimeError(f"Embedding 返回数量 {len(vectors)} 与文本块数量 {len(chunks)} 不一致。")
    rows = [
        {
            "title": doc.title[:1000],
            "content_id": f"{doc_id}-{index}",
            "content": chunk,
            "vector": vector,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    # Bounded batches avoid a giant Milvus request when importing a full corpus.
    for offset in range(0, len(rows), 100):
        await milvus_client.insert(
            collection_name=settings.COLLECTION_NAME,
            data=rows[offset:offset + 100],
        )
    await milvus_client.flush(collection_name=settings.COLLECTION_NAME)
    return len(rows)


async def _upsert_es(
    doc_id: int,
    author_id: int,
    doc: KnowledgeDocument,
    es: Any,
    *,
    published: bool = True,
) -> None:
    from clients.es_client import add_data
    from core.config import settings
    from schemas.search import KnowledgeDoc

    now = datetime.now()
    payload = KnowledgeDoc(
        title=doc.title[:1000],
        content_id=doc_id,
        summary=doc.content[:1000],
        author_id=author_id,
        tags=[doc.knowledge_domain, doc.source],
        status=1 if published else 0,
        is_public=published,
        publish_time=now if published else None,
        create_at=now,
        update_at=now,
        word_count=len(doc.content),
        create_by="fitness-knowledge-import",
        content=doc.content,
    )
    await add_data(payload, doc_id, es)
    await es.indices.refresh(index=settings.INDEX_NAME)


async def _upsert_graph(doc_id: int, doc: KnowledgeDocument, neo_driver: Any) -> None:
    from sqlalchemy import select

    from core.database import SessionLocal
    from models import GraphDocModel

    entities, relationships = _neo4j_entities_and_relationships(doc)
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(GraphDocModel).where(GraphDocModel.doc_id == doc_id))
        ).scalar_one_or_none()
        if existing is None:
            existing = GraphDocModel(
                doc_id=doc_id,
                entities=doc.entities,
                relationships=doc.relationships,
                query_cypher=(
                    "MATCH (s:FitnessEntity)-[r:FITNESS_RELATION]->(t:FitnessEntity) "
                    "WHERE r.source_doc_id = $doc_id RETURN s, r, t"
                ),
                cypher=(
                    "UNWIND $entities AS e MERGE (n:FitnessEntity {key: e.key}) "
                    "SET n.name=e.name, n.label=e.label"
                ),
            )
            session.add(existing)
        else:
            existing.entities = doc.entities
            existing.relationships = doc.relationships
        await session.commit()

    # Static, parameterized Cypher avoids dynamic labels/relationship names and
    # makes retries safe. Each edge carries its source document ID.
    async with neo_driver.session() as session:
        result = await session.run(
            "UNWIND $entities AS e "
            "MERGE (n:FitnessEntity {key: e.key}) "
            "SET n.name = e.name, n.label = e.label",
            entities=entities,
        )
        await result.consume()
        result = await session.run(
            "MATCH ()-[r:FITNESS_RELATION {source_doc_id: $doc_id}]-() DELETE r",
            doc_id=doc_id,
        )
        await result.consume()
        if relationships:
            result = await session.run(
                "UNWIND $relationships AS rel "
                "MATCH (s:FitnessEntity {key: rel.source_key}) "
                "MATCH (t:FitnessEntity {key: rel.target_key}) "
                "MERGE (s)-[r:FITNESS_RELATION {source_doc_id: $doc_id, name: rel.name}]->(t) "
                "SET r.source_doc_id = $doc_id",
                relationships=relationships,
                doc_id=doc_id,
            )
            await result.consume()


async def _set_flow(doc_id: int, flow: str, status: int) -> None:
    from sqlalchemy import update

    from core.database import SessionLocal
    from models import KhDocument

    column_name = {"index": "idx_status", "rag": "rag_status", "kg": "kg_status"}[flow]
    async with SessionLocal() as session:
        await session.execute(
            update(KhDocument).where(KhDocument.id == doc_id).values({column_name: status})
        )
        await session.commit()


async def _cleanup_resources(resources: dict[str, Any]) -> None:
    """Close any initialized clients; cleanup failures must not hide the import error."""
    cleanup_steps = []
    es_client = resources.get("es")
    es_module = resources.get("es_module")
    if es_client is None and es_module is not None:
        es_client = getattr(es_module, "es", None)
    cleanup_steps.append(("Elasticsearch", es_client))
    cleanup_steps.append(("MongoDB", resources.get("mongo_client")))
    cleanup_steps.append(("Neo4j", resources.get("neo_driver")))
    cleanup_steps.append(("Milvus", resources.get("milvus_client")))

    for name, client in cleanup_steps:
        try:
            await _close_maybe_async(client)
        except Exception as exc:
            print(f"警告：关闭{name}客户端失败：{exc}")
    if es_module is not None:
        es_module.es = None
    neo4j_module = resources.get("neo4j_module")
    if neo4j_module is not None:
        neo4j_module.driver = None
    engine = resources.get("engine")
    if engine is not None:
        try:
            await engine.dispose()
        except Exception as exc:
            print(f"警告：关闭PostgreSQL连接池失败：{exc}")


async def run_apply(documents: list[KnowledgeDocument], args: argparse.Namespace) -> None:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = _read_manifest(manifest_path)
    resources: dict[str, Any] = {}
    try:
        await _preflight(args.author_id, resources)
        for index, doc in enumerate(documents, start=1):
            doc_id: int | None = None
            stage = "PostgreSQL metadata"
            try:
                doc_id = await _ensure_document(doc, args.author_id, manifest, manifest_path)
                stage = "MongoDB content"
                await _upsert_mongo(doc_id, doc)
                stage = "Milvus vectors"
                chunks = _chunk_text(doc.content)
                vector_count = await _replace_milvus_vectors(doc_id, doc, chunks)
                await _set_flow(doc_id, "rag", 1)
                stage = "Elasticsearch index"
                await _upsert_es(doc_id, args.author_id, doc, resources["es"])
                await _set_flow(doc_id, "index", 1)
                stage = "Neo4j graph and PostgreSQL graph metadata"
                await _upsert_graph(doc_id, doc, resources["neo_driver"])
                await _set_flow(doc_id, "kg", 1)
                print(
                    f"[{index}/{len(documents)}] 已导入 doc_id={doc_id}: {doc.title} "
                    f"({len(chunks)} 个文本块 / {vector_count} 条向量)"
                )
            except Exception as exc:
                location = f"doc_id={doc_id}" if doc_id is not None else doc.title
                raise RuntimeError(f"导入在阶段“{stage}”失败（{location}）：{exc}") from exc
        print(f"导入完成：{len(documents)} 个知识文档。清单：{manifest_path}")
    finally:
        await _cleanup_resources(resources)


def main() -> int:
    args = parse_args()
    try:
        documents = build_import_documents(args)
        relation_count = sum(len(doc.relationships) for doc in documents)
        entity_count = sum(len(doc.entities) for doc in documents)
        print(
            f"\n汇总：{len(documents)} 个知识文档，约 {entity_count} 个图谱实体、"
            f"{relation_count} 条关系。"
        )
        if not args.apply:
            print("\n当前为 dry-run：没有连接或写入任何数据库。")
            print("确认数据和范围后，增加 --apply --author-id <现有用户ID> 才会正式导入。")
            return 0
        # Psycopg async requires SelectorEventLoop on Windows; the default
        # ProactorEventLoop otherwise fails before the database preflight.
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(run_apply(documents, args))
        return 0
    except Exception as exc:
        print(f"错误：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
