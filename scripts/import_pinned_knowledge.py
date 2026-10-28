"""Import approved pinned exercise/recipe descriptions through the existing RAG chain."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_fitness_knowledge import (  # noqa: E402
    _chunk_text,
    _cleanup_resources,
    _ensure_document,
    _preflight,
    _read_manifest,
    _replace_milvus_vectors,
    _set_flow,
    _upsert_es,
    _upsert_graph,
    _upsert_mongo,
    _write_manifest,
)
from services.pinned_dataset_import_service import (  # noqa: E402
    build_approved_import_plan,
    import_catalog,
)
from sqlalchemy import select  # noqa: E402
from utils.pinned_dataset_preview import DEFAULT_LOCK_PATH, DEFAULT_MAX_FILE_BYTES  # noqa: E402
from utils.pinned_dataset_knowledge import build_approved_knowledge_records  # noqa: E402

RAG_STORAGE_NAMES = ("postgres_documents", "mongodb", "milvus", "elasticsearch", "neo4j")
RAG_STAGE_LABELS = {
    "postgres_documents": "PostgreSQL 文档和来源映射",
    "mongodb": "MongoDB 正文",
    "milvus": "Milvus 向量",
    "elasticsearch": "Elasticsearch 索引",
    "neo4j": "Neo4j 图谱",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入已批准固定版本的动作/菜谱说明到现有知识检索链路。")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--author-id", type=int, required=True, help="现有 PostgreSQL 用户 ID")
    parser.add_argument("--manifest", type=Path, default=Path.home() / ".knowledge-agent" / "pinned-knowledge-import-manifest.json")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--apply", action="store_true", help="明确写入现有 PostgreSQL/MongoDB/ES/Milvus/Neo4j")
    return parser.parse_args(argv)


async def _ensure_mapping(import_id: int, record: Any, document_id: int) -> None:
    from core.database import SessionLocal
    from models.dataset_catalog import KnowledgeSourceMappingModel

    async with SessionLocal() as session:
        row = await session.scalar(select(KnowledgeSourceMappingModel).where(
            KnowledgeSourceMappingModel.import_id == import_id,
            KnowledgeSourceMappingModel.record_kind == record.record_kind,
            KnowledgeSourceMappingModel.source_record_id == record.source_record_id,
        ))
        if row is None:
            session.add(KnowledgeSourceMappingModel(
                import_id=import_id,
                record_kind=record.record_kind,
                source_record_id=record.source_record_id,
                document_id=document_id,
                content_sha256=record.content_sha256,
                mapping_status="active",
            ))
        else:
            row.document_id = document_id
            row.content_sha256 = record.content_sha256
            row.mapping_status = "active"
        await session.commit()


async def _update_import_progress(
    import_id: int,
    storage_name: str,
    *,
    progress_status: str,
    processed_records: int | None = None,
    failed_records: int | None = None,
    checkpoint: dict[str, Any] | None = None,
    last_error: str | None = None,
    start: bool = False,
) -> None:
    from core.database import SessionLocal
    from models.dataset_catalog import DatasetImportProgressModel

    now = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        row = await session.scalar(select(DatasetImportProgressModel).where(
            DatasetImportProgressModel.import_id == import_id,
            DatasetImportProgressModel.storage_name == storage_name,
        ))
        if row is None:
            row = DatasetImportProgressModel(
                import_id=import_id,
                storage_name=storage_name,
                progress_status="pending",
                processed_records=0,
                skipped_records=0,
                failed_records=0,
                checkpoint={},
                last_error="",
            )
            session.add(row)
        row.progress_status = progress_status
        if processed_records is not None:
            row.processed_records = processed_records
        if failed_records is not None:
            row.failed_records = failed_records
        if checkpoint is not None:
            row.checkpoint = checkpoint
        if last_error is not None:
            row.last_error = last_error[:2000]
        if start:
            row.started_at = now
            row.completed_at = None
        elif progress_status == "completed":
            row.completed_at = now
        row.updated_at = now
        await session.commit()


async def _set_dataset_import_status(import_id: int, status: str) -> None:
    from core.database import SessionLocal
    from models.dataset_catalog import DatasetImportModel

    async with SessionLocal() as session:
        row = await session.get(DatasetImportModel, import_id)
        if row is None:
            raise RuntimeError(f"找不到数据集导入记录 id={import_id}。")
        row.import_status = status
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def _set_document_published(document_id: int, published: bool) -> None:
    from core.database import SessionLocal
    from models import KhDocument

    async with SessionLocal() as session:
        row = await session.get(KhDocument, document_id)
        if row is None:
            raise RuntimeError(f"找不到知识文档 doc_id={document_id}，无法更新发布状态。")
        row.status = 1 if published else 0
        row.publish_time = datetime.now() if published else None
        row.is_public = 1 if published else 0
        await session.commit()


async def _set_es_document_published(document_id: int, es: Any, published: bool) -> None:
    from core.config import settings

    await es.update(
        index=settings.INDEX_NAME,
        id=document_id,
        doc={
            "status": 1 if published else 0,
            "is_public": published,
            "publish_time": datetime.now().isoformat() if published else None,
        },
    )
    await es.indices.refresh(index=settings.INDEX_NAME)


async def import_knowledge_records(records: list[Any], plan: Any, author_id: int, manifest_path: Path) -> dict[str, Any]:
    from core.database import SessionLocal
    from models.dataset_catalog import DatasetImportModel

    imports: dict[tuple[str, str], int] = {}
    async with SessionLocal() as session:
        for file in plan.files:
            row = await session.scalar(select(DatasetImportModel).where(
                DatasetImportModel.dataset == file["dataset"],
                DatasetImportModel.revision == file["commit"],
            ))
            if row is None:
                raise RuntimeError(f"找不到目录导入记录：{file['dataset']}@{file['commit']}；请先完成目录导入。")
            imports[(file["dataset"], file["commit"])] = int(row.id)

    import_ids = sorted(set(imports.values()))
    processed_counts = {import_id: {name: 0 for name in RAG_STORAGE_NAMES} for import_id in import_ids}
    manifest = _read_manifest(manifest_path)
    resources: dict[str, Any] = {}
    processed = 0
    try:
        try:
            await _preflight(author_id, resources)
        except Exception:
            for import_id in import_ids:
                await _set_dataset_import_status(import_id, "failed")
            raise

        for import_id in import_ids:
            await _set_dataset_import_status(import_id, "importing")
            for storage_name in RAG_STORAGE_NAMES:
                await _update_import_progress(
                    import_id,
                    storage_name,
                    progress_status="running",
                    processed_records=0,
                    failed_records=0,
                    checkpoint={},
                    last_error="",
                    start=True,
                )

        for record in records:
            file = next(item for item in plan.files if item["dataset"] == record.dataset and item["commit"] == record.revision)
            import_id = imports[(file["dataset"], file["commit"])]
            storage_name = "postgres_documents"
            doc_id: int | None = None
            try:
                doc_id = await _ensure_document(
                    record.document,
                    author_id,
                    manifest,
                    manifest_path,
                    published=False,
                )

                storage_name = "mongodb"
                await _upsert_mongo(doc_id, record.document)
                processed_counts[import_id][storage_name] += 1
                await _update_import_progress(
                    import_id, storage_name, progress_status="running",
                    processed_records=processed_counts[import_id][storage_name],
                    checkpoint={"last_record_key": record.source_record_id},
                )

                storage_name = "milvus"
                chunks = _chunk_text(record.document.content)
                await _replace_milvus_vectors(doc_id, record.document, chunks)
                await _set_flow(doc_id, "rag", 1)
                processed_counts[import_id][storage_name] += 1
                await _update_import_progress(
                    import_id, storage_name, progress_status="running",
                    processed_records=processed_counts[import_id][storage_name],
                    checkpoint={"last_record_key": record.source_record_id},
                )

                storage_name = "elasticsearch"
                await _upsert_es(
                    doc_id,
                    author_id,
                    record.document,
                    resources["es"],
                    published=False,
                )
                await _set_flow(doc_id, "index", 1)
                processed_counts[import_id][storage_name] += 1
                await _update_import_progress(
                    import_id, storage_name, progress_status="running",
                    processed_records=processed_counts[import_id][storage_name],
                    checkpoint={"last_record_key": record.source_record_id},
                )

                storage_name = "neo4j"
                await _upsert_graph(doc_id, record.document, resources["neo_driver"])
                await _set_flow(doc_id, "kg", 1)
                await _ensure_mapping(import_id, record, doc_id)
                processed_counts[import_id][storage_name] += 1
                await _update_import_progress(
                    import_id, storage_name, progress_status="running",
                    processed_records=processed_counts[import_id][storage_name],
                    checkpoint={"last_record_key": record.source_record_id},
                )

                storage_name = "postgres_documents"
                await _set_document_published(doc_id, True)
                storage_name = "elasticsearch"
                try:
                    await _set_es_document_published(doc_id, resources["es"], True)
                except Exception as publish_exc:
                    compensation_errors = []
                    try:
                        await _set_es_document_published(doc_id, resources["es"], False)
                    except Exception as compensation_exc:
                        compensation_errors.append(f"Elasticsearch 隐藏失败：{compensation_exc}")
                    try:
                        await _set_document_published(doc_id, False)
                    except Exception as compensation_exc:
                        compensation_errors.append(f"PostgreSQL 隐藏失败：{compensation_exc}")
                    if compensation_errors:
                        raise RuntimeError(
                            f"Elasticsearch 发布失败：{publish_exc}；回退失败：{'；'.join(compensation_errors)}"
                        ) from publish_exc
                    raise

                storage_name = "postgres_documents"
                processed_counts[import_id][storage_name] += 1
                await _update_import_progress(
                    import_id, storage_name, progress_status="running",
                    processed_records=processed_counts[import_id][storage_name],
                    checkpoint={"last_record_key": record.source_record_id},
                )
                processed += 1
            except Exception as exc:
                checkpoint = {"failed_record_key": record.source_record_id}
                try:
                    await _update_import_progress(
                        import_id,
                        storage_name,
                        progress_status="failed",
                        processed_records=processed_counts[import_id][storage_name],
                        failed_records=1,
                        checkpoint=checkpoint,
                        last_error=str(exc),
                    )
                    await _set_dataset_import_status(import_id, "failed")
                except Exception as progress_exc:
                    raise RuntimeError(
                        f"{RAG_STAGE_LABELS[storage_name]}失败（doc_id={doc_id or record.source_record_id}）：{exc}；"
                        f"写入失败状态时也发生错误：{progress_exc}"
                    ) from exc
                raise RuntimeError(
                    f"{RAG_STAGE_LABELS[storage_name]}失败（doc_id={doc_id or record.source_record_id}）：{exc}"
                ) from exc
    finally:
        await _cleanup_resources(resources)

    for import_id in import_ids:
        for storage_name in RAG_STORAGE_NAMES:
            await _update_import_progress(
                import_id,
                storage_name,
                progress_status="completed",
                processed_records=processed_counts[import_id][storage_name],
                failed_records=0,
                last_error="",
            )
        await _set_dataset_import_status(import_id, "imported")
    return {"processed": processed, "database_written": True, "media_urls_requested": 0}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.batch_size < 1:
        print("错误：--batch-size 必须大于 0", file=sys.stderr)
        return 2
    try:
        with httpx.Client(
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=False,
            headers={"User-Agent": "knowledge-agent-pinned-knowledge-import/1.0"},
        ) as client:
            plan = build_approved_import_plan(args.lock, args.report, args.approval, client, max_bytes=args.max_bytes)
        records = build_approved_knowledge_records(plan)
        print(f"可导入知识文档：{len(records)}；视频 URL 请求：0。")
        if not args.apply:
            print("当前为预览：未连接或写入应用数据库。增加 --apply 才会正式写入。")
            return 0
        if not records:
            print("错误：没有已批准的动作/菜谱说明可导入；未连接或写入数据库。", file=sys.stderr)
            return 1

        from core.database import SessionLocal

        async def run() -> dict[str, Any]:
            async with SessionLocal() as session:
                await import_catalog(session, plan, batch_size=args.batch_size)
            return await import_knowledge_records(records, plan, args.author_id, args.manifest.expanduser().resolve())

        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        print(asyncio.run(run()))
        return 0
    except Exception as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
