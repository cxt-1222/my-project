"""Build traceable RAG documents from approved pinned catalog records.

The document builders are deliberately pure. They do not fetch media, access a
database, or calculate nutrition values; structured nutrition remains owned by
the catalog tables and deterministic calculation service.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from utils.exercise_catalog import ExerciseCatalogItem
from utils.fitness_knowledge import KnowledgeDocument
from utils.nutrition_catalog import RecipeCatalogItem


@dataclass(frozen=True, slots=True)
class KnowledgeSourceRecord:
    dataset: str
    revision: str
    record_kind: str
    source_record_id: str
    content_sha256: str
    document: KnowledgeDocument


def _approved(item: Any) -> bool:
    return item.record_status == "active" and item.license_status == "approved"


def _recipe_text(item: RecipeCatalogItem) -> str:
    raw = item.recipe_data
    lines = [f"菜谱名称：{item.title}"]
    if item.source_name:
        lines.append(f"资料来源：{item.source_name}")
    if item.source_url:
        lines.append(f"来源链接：{item.source_url}")
    if item.servings is not None:
        lines.append(f"成品份量：{item.servings}")

    instructions = raw.get("instructions") or raw.get("steps") or raw.get("method")
    if isinstance(instructions, list):
        instructions = "\n".join(str(value).strip() for value in instructions if str(value).strip())
    if isinstance(instructions, str) and instructions.strip():
        lines.append("制作说明：")
        lines.extend(
            f"{index}. {part.strip()}"
            for index, part in enumerate(instructions.splitlines(), 1)
            if part.strip()
        )

    lines.append("食材：")
    for ingredient in item.ingredients:
        amount = f"{ingredient.amount:g}" if ingredient.amount is not None else "未提供"
        unit = ingredient.unit or "未提供"
        line = f"- {ingredient.name}：{amount}{unit}"
        if ingredient.note:
            line += f"（{ingredient.note}）"
        lines.append(line)

    lines.append("营养说明：营养数值不在本知识文档中作为权威事实；请通过结构化食材目录和确定性计算获取。")
    return "\n".join(lines)


def exercise_to_knowledge_record(item: ExerciseCatalogItem, *, dataset: str, revision: str) -> KnowledgeSourceRecord | None:
    if not _approved(item) or not item.display_content.strip():
        return None
    content = f"{item.display_content.rstrip()}\n资料来源记录：{dataset}@{revision} / {item.upstream_id}"
    document = KnowledgeDocument(
        source=f"{dataset}:exercise",
        source_key=f"{revision}:exercise:{item.upstream_id}",
        title=f"健身动作：{item.name}",
        content=content,
        knowledge_domain="健身知识",
        entities=[{"label": "健身动作", "name": item.name}],
    )
    fields = item.normalized_fields
    for label, key in (("身体部位", "body_part"), ("器械工具", "equipment"), ("目标肌群", "target_muscle")):
        value = fields.get(key)
        if value:
            document.entities.append({"label": label, "name": str(value)})
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return KnowledgeSourceRecord(dataset, revision, "exercise", item.upstream_id, digest, document)


def recipe_to_knowledge_record(item: RecipeCatalogItem, *, dataset: str, revision: str) -> KnowledgeSourceRecord | None:
    if not _approved(item):
        return None
    content = f"{_recipe_text(item)}\n资料来源记录：{dataset}@{revision} / {item.upstream_id}"
    document = KnowledgeDocument(
        source=f"{dataset}:recipe",
        source_key=f"{revision}:recipe:{item.upstream_id}",
        title=f"饮食菜谱：{item.title}",
        content=content,
        knowledge_domain="饮食知识",
        entities=[{"label": "菜谱", "name": item.title}],
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return KnowledgeSourceRecord(dataset, revision, "recipe", item.upstream_id, digest, document)


def build_approved_knowledge_records(plan: Any) -> list[KnowledgeSourceRecord]:
    """Build one RAG document per approved exercise or recipe record."""
    records: list[KnowledgeSourceRecord] = []
    for file in plan.files:
        dataset = file["dataset"]
        revision = file["commit"]
        for item in plan.exercises.get(dataset, []):
            record = exercise_to_knowledge_record(item, dataset=dataset, revision=revision)
            if record is not None:
                records.append(record)
        for item in plan.recipes.get(dataset, []):
            record = recipe_to_knowledge_record(item, dataset=dataset, revision=revision)
            if record is not None:
                records.append(record)
    return records
