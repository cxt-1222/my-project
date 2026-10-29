"""Disable one pinned dataset revision and remove only its mapped RAG documents."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import func, select, update

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clients import es_client, neo4j_client  # noqa: E402
from clients.milvus_client import milvus_client  # noqa: E402
from core.config import settings  # noqa: E402
from core.database import SessionLocal, engine  # noqa: E402
from models import (  # noqa: E402
    DatasetImportModel,
    ExerciseCatalogModel,
    ExerciseMediaModel,
    FoodCatalogModel,
    KnowledgeSourceMappingModel,
    KhDocument,
    RecipeCatalogModel,
)
from models.dataset_catalog import DatasetImportProgressModel  # noqa: E402
from services.knowledge_cleanup_executor import delete_knowledge_document  # noqa: E402


def _confirmation(dataset: str, revision: str) -> str:
    return f"ROLLBACK {dataset}@{revision}"


def _sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _build_preview(session: Any, dataset: str, revision: str) -> dict[str, Any]:
    source = await session.scalar(select(DatasetImportModel).where(
        DatasetImportModel.dataset == dataset,
        DatasetImportModel.revision == revision,
    ))
    if source is None:
        raise ValueError("找不到指定的数据集固定版本。")
    if source.import_status == "importing":
        raise ValueError("该固定版本仍在导入中，不能回滚。")
    if source.import_status not in {"imported", "failed", "disabled"}:
        raise ValueError("该固定版本没有可回滚的目录导入记录。")

    mapping_result = await session.execute(
        select(
            KnowledgeSourceMappingModel.document_id,
            KnowledgeSourceMappingModel.mapping_status,
            KhDocument.content_id,
            KhDocument.title,
        )
        .join(KhDocument, KhDocument.id == KnowledgeSourceMappingModel.document_id)
        .where(KnowledgeSourceMappingModel.import_id == source.id)
        .order_by(KnowledgeSourceMappingModel.document_id)
    )
    documents = [
        {
            "document_id": int(row.document_id),
            "content_id": row.content_id,
            "title": row.title,
            "mapping_status": row.mapping_status,
        }
        for row in mapping_result.all()
    ]
    document_ids = [row["document_id"] for row in documents]

    shared_mappings = 0
    if document_ids:
        shared_mappings = int(await session.scalar(
            select(func.count()).select_from(KnowledgeSourceMappingModel).where(
                KnowledgeSourceMappingModel.document_id.in_(document_ids),
                KnowledgeSourceMappingModel.import_id != source.id,
                KnowledgeSourceMappingModel.mapping_status == "active",
            )
        ) or 0)

    counts = {
        "exercise_records": int(await session.scalar(
            select(func.count()).select_from(ExerciseCatalogModel).where(
                ExerciseCatalogModel.import_id == source.id
            )
        ) or 0),
        "food_records": int(await session.scalar(
            select(func.count()).select_from(FoodCatalogModel).where(
                FoodCatalogModel.import_id == source.id
            )
        ) or 0),
        "recipe_records": int(await session.scalar(
            select(func.count()).select_from(RecipeCatalogModel).where(
                RecipeCatalogModel.import_id == source.id
            )
        ) or 0),
    }
    blockers = []
    if shared_mappings:
        blockers.append("有目录知识文档同时映射到其他来源版本，不能安全回滚。")
    report = {
        "mode": "read_only_preview",
        "destructive": False,
        "dataset": source.dataset,
        "revision": source.revision,
        "import_id": int(source.id),
        "import_status": source.import_status,
        "document_count": len(documents),
        "documents": [
            {"document_id": item["document_id"], "title": item["title"], "mapping_status": item["mapping_status"]}
            for item in documents
        ],
        "catalog_record_counts": counts,
        "shared_active_mappings": shared_mappings,
        "blockers": blockers,
        "apply_available": not blockers,
    }
    report["preview_sha256"] = _sha256(report)
    report["_documents"] = documents
    return report


async def rollback_pinned_dataset(
    dataset: str,
    revision: str,
    *,
    apply: bool,
    preview_sha256: str | None = None,
    confirmation: str | None = None,
) -> dict[str, Any]:
    from pymongo import AsyncMongoClient

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision 必须是完整的 40 位小写 commit SHA。")

    async with SessionLocal() as session:
        report = await _build_preview(session, dataset, revision)
        if not apply:
            report.pop("_documents", None)
            return report
        if confirmation != _confirmation(dataset, revision):
            raise ValueError(f"正式回滚需要 --confirm '{_confirmation(dataset, revision)}'。")
        if preview_sha256 != report["preview_sha256"]:
            raise ValueError("回滚预览已变化；未执行任何操作，请重新预览并确认。")
        if not report["apply_available"]:
            raise ValueError("预览存在安全阻断项；未执行回滚。")

        mongo_client = None
        es = None
        initialized_neo4j = False
        deleted_by_store: Counter[str] = Counter()
        completed_document_ids: list[int] = []
        failed_document_id: int | None = None
        try:
            es = await es_client.get_es()
            mongo_client = AsyncMongoClient(settings.MONGO_URI)
            await mongo_client.admin.command("ping")
            if neo4j_client.driver is None:
                await neo4j_client.init_neo4j_driver()
                initialized_neo4j = True
            neo_driver = neo4j_client.driver
            if neo_driver is None:
                raise RuntimeError("Neo4j driver 未初始化。")

            source = await session.get(DatasetImportModel, report["import_id"])
            source.import_status = "disabled"
            source.updated_at = datetime.now(timezone.utc)
            await session.execute(update(ExerciseCatalogModel).where(
                ExerciseCatalogModel.import_id == source.id
            ).values(record_status="disabled"))
            await session.execute(update(FoodCatalogModel).where(
                FoodCatalogModel.import_id == source.id
            ).values(record_status="disabled"))
            await session.execute(update(RecipeCatalogModel).where(
                RecipeCatalogModel.import_id == source.id
            ).values(record_status="disabled"))
            await session.execute(update(ExerciseMediaModel).where(
                ExerciseMediaModel.exercise_id.in_(
                    select(ExerciseCatalogModel.id).where(ExerciseCatalogModel.import_id == source.id)
                )
            ).values(allowed_use="none"))
            await session.execute(update(KnowledgeSourceMappingModel).where(
                KnowledgeSourceMappingModel.import_id == source.id
            ).values(mapping_status="disabled"))
            await session.commit()

            mongo_collection = mongo_client[settings.DB_NAME]["document_content"]
            for document in report["_documents"]:
                failed_document_id = document["document_id"]
                counts = await delete_knowledge_document(
                    session,
                    {"id": document["document_id"], "content_id": document["content_id"]},
                    es=es,
                    mongo_collection=mongo_collection,
                    milvus=milvus_client,
                    neo_driver=neo_driver,
                )
                deleted_by_store.update(counts)
                completed_document_ids.append(document["document_id"])
            failed_document_id = None

            progress = await session.scalars(select(DatasetImportProgressModel).where(
                DatasetImportProgressModel.import_id == source.id
            ))
            now = datetime.now(timezone.utc)
            for row in progress:
                row.checkpoint = {
                    **(row.checkpoint or {}),
                    "rollback": {
                        "status": "completed",
                        "completed_document_ids": completed_document_ids,
                        "deleted_counts": dict(deleted_by_store),
                    },
                }
                row.updated_at = now
            await session.commit()
            return {
                "mode": "applied",
                "destructive": True,
                "dataset": dataset,
                "revision": revision,
                "import_status": "disabled",
                "completed_document_ids": completed_document_ids,
                "deleted_counts": dict(deleted_by_store),
                "failed_document_id": None,
            }
        except Exception as exc:
            await session.rollback()
            source = await session.get(DatasetImportModel, report["import_id"])
            if source is not None:
                source.import_status = "disabled"
                source.updated_at = datetime.now(timezone.utc)
                progress_rows = await session.scalars(select(DatasetImportProgressModel).where(
                    DatasetImportProgressModel.import_id == source.id
                ))
                for row in progress_rows:
                    row.checkpoint = {
                        **(row.checkpoint or {}),
                        "rollback": {
                            "status": "failed",
                            "failed_document_id": failed_document_id,
                            "completed_document_ids": completed_document_ids,
                            "deleted_counts": dict(deleted_by_store),
                            "error_type": type(exc).__name__,
                        },
                    }
                    row.updated_at = datetime.now(timezone.utc)
                await session.commit()
            raise RuntimeError(
                f"回滚未完整完成；数据版本已停用。失败文档：{failed_document_id or '未开始'}；"
                f"错误类型：{type(exc).__name__}。可使用同一固定版本重新预览并重试。"
            ) from exc
        finally:
            if mongo_client is not None:
                await mongo_client.close()
            if es is not None:
                await es.close()
            if initialized_neo4j:
                await neo4j_client.close_neo4j_driver()
            await milvus_client.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按固定来源版本停用目录并删除其映射知识文档。")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--revision", required=True, help="固定版本的完整 commit SHA")
    parser.add_argument("--preview-sha256", help="当前 dry-run 报告的 SHA-256")
    parser.add_argument("--confirm", help="精确输入 ROLLBACK <dataset>@<revision>")
    parser.add_argument("--apply", action="store_true", help="正式停用并清理该来源版本")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    try:
        result = await rollback_pinned_dataset(
            args.dataset,
            args.revision,
            apply=args.apply,
            preview_sha256=args.preview_sha256,
            confirmation=args.confirm,
        )
        result.pop("_documents", None)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
