"""Approved pinned-dataset catalog import with resumable, idempotent progress."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.dataset_catalog import (
    DatasetImportModel,
    DatasetImportProgressModel,
    ExerciseCatalogModel,
    ExerciseMediaModel,
    FoodCatalogModel,
    RecipeCatalogModel,
    RecipeIngredientModel,
)
from utils.exercise_catalog import ExerciseCatalogItem, convert_exercise_records
from utils.nutrition_catalog import (
    FoodCatalogItem,
    RecipeCatalogItem,
    convert_food_records,
    convert_recipe_records,
)
from utils.pinned_dataset_preview import (
    DEFAULT_MAX_FILE_BYTES,
    PinnedFile,
    fetch_pinned_json,
    load_source_lock,
    validate_reviewed_manifest,
)


STORAGE_NAMES = (
    "postgres_catalog", "postgres_documents", "mongodb",
    "elasticsearch", "milvus", "neo4j",
)


@dataclass(slots=True)
class ApprovedImportPlan:
    locked_on: str
    files: list[dict[str, Any]]
    exercises: dict[str, list[ExerciseCatalogItem]]
    foods: dict[str, list[FoodCatalogItem]]
    recipes: dict[str, list[RecipeCatalogItem]]
    source_metadata: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def importable_count(self) -> int:
        items = [*self.exercises.values(), *self.foods.values(), *self.recipes.values()]
        return sum(sum(item.record_status == "active" and item.license_status == "approved" for item in rows) for rows in items)

    @property
    def skipped_count(self) -> int:
        items = [*self.exercises.values(), *self.foods.values(), *self.recipes.values()]
        return sum(sum(not (item.record_status == "active" and item.license_status == "approved") for item in rows) for rows in items)


def build_approved_import_plan(
    lock_path: Path,
    report_path: Path,
    approval_path: Path,
    client: httpx.Client,
    *,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> ApprovedImportPlan:
    """Validate the review gate, then fetch only the same pinned JSON files."""
    gate = validate_reviewed_manifest(
        lock_path,
        report_path,
        approval_path,
        client,
        max_bytes=max_bytes,
        allow_partial_licenses=True,
    )
    source_files, locked_on = load_source_lock(lock_path)
    files_by_key = {(item["dataset"], item["path"]): item for item in gate["files"]}
    fetched: list[tuple[PinnedFile, Any]] = []
    for source_file in source_files:
        parsed, metadata = fetch_pinned_json(source_file, client, max_bytes=max_bytes)
        expected = files_by_key[(source_file.dataset, source_file.path)]
        if metadata["bytes"] != expected["bytes"] or metadata["sha256"] != expected["sha256"]:
            raise RuntimeError(f"{source_file.dataset}/{source_file.path} 重复获取时摘要发生变化。")
        fetched.append((source_file, parsed))

    foods: dict[str, list[FoodCatalogItem]] = {}
    recipes_raw: dict[str, tuple[PinnedFile, Any]] = {}
    exercises: dict[str, list[ExerciseCatalogItem]] = {}
    source_metadata: dict[str, dict[str, str]] = {}
    file_records: list[dict[str, Any]] = []
    for source_file, data in fetched:
        source_metadata.setdefault(source_file.dataset, {
            "metadata_license_status": source_file.metadata_license_status,
            "media_license_status": source_file.media_license_status,
            "license_note": source_file.license_note,
        })
        if source_file.kind == "exercise":
            items, _ = convert_exercise_records(
                data, license_status=source_file.metadata_license_status
            )
            exercises[source_file.dataset] = items
        elif source_file.kind == "food_records":
            items, _ = convert_food_records(
                data,
                license_by_source=source_file.record_license_by_source,
                nutrition_basis_by_source=source_file.nutrition_basis_by_source,
            )
            foods[source_file.dataset] = items
        elif source_file.kind == "recipe_records":
            recipes_raw[source_file.dataset] = (source_file, data)
        file_records.append({
            "dataset": source_file.dataset,
            "repository": source_file.repository,
            "commit": source_file.commit,
            "path": source_file.path,
            "kind": source_file.kind,
            "bytes": files_by_key[(source_file.dataset, source_file.path)]["bytes"],
            "sha256": files_by_key[(source_file.dataset, source_file.path)]["sha256"],
        })

    recipes: dict[str, list[RecipeCatalogItem]] = {}
    for dataset, (source_file, data) in recipes_raw.items():
        recipe_file = source_file
        items, _ = convert_recipe_records(
            data,
            foods.get(dataset, []),
            recipe_license_by_source=recipe_file.recipe_license_by_source,
        )
        recipes[dataset] = items

    return ApprovedImportPlan(
        locked_on=locked_on,
        files=file_records,
        exercises=exercises,
        foods=foods,
        recipes=recipes,
        source_metadata=source_metadata,
    )


def importable_items(plan: ApprovedImportPlan) -> dict[str, list[Any]]:
    """Return only records that are both approved and active."""
    result: dict[str, list[Any]] = defaultdict(list)
    for dataset, rows in plan.exercises.items():
        approved_rows = [row for row in rows if row.record_status == "active" and row.license_status == "approved"]
        if approved_rows:
            result[dataset].extend(approved_rows)
    for dataset, rows in plan.foods.items():
        approved_rows = [row for row in rows if row.record_status == "active" and row.license_status == "approved"]
        if approved_rows:
            result[dataset].extend(approved_rows)
    for dataset, rows in plan.recipes.items():
        approved_rows = [row for row in rows if row.record_status == "active" and row.license_status == "approved"]
        if approved_rows:
            result[dataset].extend(approved_rows)
    return dict(result)


async def _get_or_create_import(session: AsyncSession, plan: ApprovedImportPlan, dataset: str) -> DatasetImportModel:
    source = next(item for item in plan.files if item["dataset"] == dataset)
    source_metadata = plan.source_metadata.get(dataset, {})
    row = await session.scalar(
        select(DatasetImportModel).where(
            DatasetImportModel.dataset == dataset,
            DatasetImportModel.revision == source["commit"],
        )
    )
    if row is None:
        row = DatasetImportModel(
            dataset=dataset,
            repository=source["repository"],
            revision=source["commit"],
            locked_on=date.fromisoformat(plan.locked_on),
            import_status="importing",
            metadata_license_status=source_metadata.get("metadata_license_status", "pending_review"),
            media_license_status=source_metadata.get("media_license_status", "not_applicable"),
            license_note=source_metadata.get("license_note", "已审阅固定来源报告；未批准记录保持隔离"),
            file_manifest=[item for item in plan.files if item["dataset"] == dataset],
        )
        session.add(row)
        await session.flush()
    else:
        row.metadata_license_status = source_metadata.get("metadata_license_status", "pending_review")
        row.media_license_status = source_metadata.get("media_license_status", "not_applicable")
        row.license_note = source_metadata.get("license_note", "已审阅固定来源报告；未批准记录保持隔离")
        row.file_manifest = [item for item in plan.files if item["dataset"] == dataset]
        row.updated_at = datetime.now(timezone.utc)
    return row


async def _ensure_progress(session: AsyncSession, import_id: int, storage_name: str) -> DatasetImportProgressModel:
    row = await session.scalar(
        select(DatasetImportProgressModel).where(
            DatasetImportProgressModel.import_id == import_id,
            DatasetImportProgressModel.storage_name == storage_name,
        )
    )
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
        await session.flush()
    return row


def _approved(item: Any) -> bool:
    return item.record_status == "active" and item.license_status == "approved"


def _source_record_key(item: Any) -> str:
    if isinstance(item, FoodCatalogItem):
        return f"food:{item.source_key}:{item.upstream_id}"
    if isinstance(item, ExerciseCatalogItem):
        return f"exercise:{item.upstream_id}"
    return f"recipe:{item.upstream_id}"


async def _upsert_exercise(session: AsyncSession, import_id: int, item: ExerciseCatalogItem) -> ExerciseCatalogModel:
    row = await session.scalar(select(ExerciseCatalogModel).where(
        ExerciseCatalogModel.import_id == import_id,
        ExerciseCatalogModel.upstream_id == item.upstream_id,
    ))
    values = {
        "import_id": import_id,
        "upstream_id": item.upstream_id,
        "name": item.name,
        "name_normalized": item.name_normalized,
        "aliases": item.aliases,
        "normalized_fields": item.normalized_fields,
        "raw_record": item.raw_record,
        "content_sha256": item.content_sha256,
        "license_status": item.license_status,
        "record_status": item.record_status,
    }
    if row is None:
        row = ExerciseCatalogModel(**values)
        session.add(row)
        await session.flush()
    else:
        for key, value in values.items():
            setattr(row, key, value)
    for media in item.media_refs:
        existing_media = await session.scalar(select(ExerciseMediaModel).where(
            ExerciseMediaModel.exercise_id == row.id,
            ExerciseMediaModel.media_kind == media["kind"],
            ExerciseMediaModel.variant == media["variant"],
            ExerciseMediaModel.source_url == media["source_url"],
        ))
        if existing_media is None:
            session.add(ExerciseMediaModel(
                exercise_id=row.id,
                media_kind=media["kind"],
                variant=media["variant"],
                source_url=media["source_url"],
                source_host=media["source_host"],
                allowed_use="none",
                license_status=media["license_status"],
                mapping_status=media["mapping_status"],
            ))
    return row


async def _upsert_food(session: AsyncSession, import_id: int, item: FoodCatalogItem) -> None:
    row = await session.scalar(select(FoodCatalogModel).where(
        FoodCatalogModel.import_id == import_id,
        FoodCatalogModel.source_key == item.source_key,
        FoodCatalogModel.upstream_id == item.upstream_id,
    ))
    values = {
        "import_id": import_id,
        "upstream_id": item.upstream_id,
        "source_key": item.source_key,
        "name": item.name,
        "nutrition_basis": item.nutrition_basis,
        "edible_value": item.edible_value,
        "nutrients_raw": {key: str(value) for key, value in item.nutrients_raw.items()},
        "raw_record": item.raw_record,
        "content_sha256": item.content_sha256,
        "license_status": item.license_status,
        "record_status": item.record_status,
    }
    if row is None:
        session.add(FoodCatalogModel(**values))
    else:
        for key, value in values.items():
            setattr(row, key, value)


async def _upsert_recipe(session: AsyncSession, import_id: int, item: RecipeCatalogItem) -> None:
    row = await session.scalar(select(RecipeCatalogModel).where(
        RecipeCatalogModel.import_id == import_id,
        RecipeCatalogModel.upstream_id == item.upstream_id,
    ))
    values = {
        "import_id": import_id,
        "upstream_id": item.upstream_id,
        "title": item.title,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "source_revision": item.source_revision,
        "source_license": item.source_license,
        "servings": item.servings,
        "recipe_data": item.recipe_data,
        "content_sha256": item.content_sha256,
        "license_status": item.license_status,
        "record_status": item.record_status,
    }
    if row is None:
        row = RecipeCatalogModel(**values)
        session.add(row)
        await session.flush()
    else:
        for key, value in values.items():
            setattr(row, key, value)
        await session.execute(delete(RecipeIngredientModel).where(RecipeIngredientModel.recipe_id == row.id))
    for ingredient in item.ingredients:
        session.add(RecipeIngredientModel(
            recipe_id=row.id,
            position=ingredient.position,
            name=ingredient.name,
            amount=ingredient.amount,
            unit=ingredient.unit,
            note=ingredient.note,
            food_source_key=ingredient.food_source_key,
            food_upstream_id=ingredient.food_upstream_id,
            match_status=ingredient.match_status,
            raw_record=ingredient.raw_record,
        ))


async def import_catalog(session: AsyncSession, plan: ApprovedImportPlan, *, batch_size: int = 100) -> dict[str, Any]:
    """Write only approved catalog rows; replaying the same plan is idempotent."""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    summary = {"processed": 0, "skipped": plan.skipped_count, "datasets": {}}
    for dataset in sorted({item["dataset"] for item in plan.files}):
        import_row = await _get_or_create_import(session, plan, dataset)
        progress_rows = {name: await _ensure_progress(session, import_row.id, name) for name in STORAGE_NAMES}
        progress = progress_rows["postgres_catalog"]
        import_id = import_row.id
        previously_imported = (
            import_row.import_status == "imported"
            and all(
                progress_rows[name].progress_status == "completed"
                for name in STORAGE_NAMES
                if name != "postgres_catalog"
            )
        )
        import_row.import_status = "importing"
        import_row.updated_at = datetime.now(timezone.utc)
        resuming = progress.progress_status in {"running", "failed"}
        resume_after = (progress.checkpoint or {}).get("last_record_key", "") if resuming else ""
        processed_before = progress.processed_records if resume_after else 0
        skipped_before = progress.skipped_records if resume_after else 0
        if not resume_after:
            progress.checkpoint = {}
            progress.processed_records = 0
            progress.skipped_records = 0
            progress.failed_records = 0
        progress.progress_status = "running"
        progress.last_error = ""
        progress.completed_at = None
        progress.started_at = progress.started_at or datetime.now(timezone.utc)
        await session.commit()

        rows: list[Any] = [
            *plan.exercises.get(dataset, []),
            *plan.foods.get(dataset, []),
            *plan.recipes.get(dataset, []),
        ]
        processed = 0
        skipped = 0
        try:
            resuming = bool(resume_after)
            checkpoint_found = not resuming
            for item in rows:
                source_key = _source_record_key(item)
                if resuming and not checkpoint_found:
                    if source_key == resume_after:
                        checkpoint_found = True
                        resuming = False
                    continue
                if not _approved(item):
                    skipped += 1
                    continue
                if isinstance(item, ExerciseCatalogItem):
                    await _upsert_exercise(session, import_id, item)
                elif isinstance(item, FoodCatalogItem):
                    await _upsert_food(session, import_id, item)
                elif isinstance(item, RecipeCatalogItem):
                    await _upsert_recipe(session, import_id, item)
                processed += 1
                if processed % batch_size == 0:
                    progress.processed_records = processed_before + processed
                    progress.skipped_records = skipped_before + skipped
                    progress.checkpoint = {"last_record_key": source_key}
                    progress.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            if not checkpoint_found:
                raise RuntimeError("保存的导入检查点不在当前固定版本中；为避免跳过记录，已停止，请人工核对后重试。")
            progress.progress_status = "completed"
            progress.processed_records = processed_before + processed
            progress.skipped_records = skipped_before + skipped
            progress.checkpoint = {"last_record_key": _source_record_key(rows[-1]) if rows else ""}
            progress.completed_at = datetime.now(timezone.utc)
            progress.updated_at = datetime.now(timezone.utc)
            import_row.import_status = "imported" if previously_imported else "importing"
            import_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            progress = await _ensure_progress(session, import_id, "postgres_catalog")
            progress.progress_status = "failed"
            progress.last_error = str(exc)[:2000]
            progress.updated_at = datetime.now(timezone.utc)
            import_row = await session.get(DatasetImportModel, import_id)
            import_row.import_status = "failed"
            import_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            raise
        summary["processed"] += processed
        summary["datasets"][dataset] = {"processed": processed, "skipped": skipped}
    return summary
