"""Pure converters for the fitness datasets used by the knowledge-base importer.

This module deliberately has no database, network, or application-config imports so
its parsing and data-quality checks can be tested offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable


@dataclass(slots=True)
class KnowledgeDocument:
    """One publishable document plus the graph facts derived from the same source."""

    source: str
    source_key: str
    title: str
    content: str
    knowledge_domain: str = "健身知识"
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)

    @property
    def import_key(self) -> str:
        payload = "\0".join((self.source, self.source_key, self.title, self.content))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ConversionStats:
    total_records: int = 0
    accepted_records: int = 0
    invalid_records: int = 0
    invalid_spans: int = 0
    invalid_relations: int = 0
    duplicate_records: int = 0


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _localized_text(value: Any, preferred: tuple[str, ...] = ("zh", "zh-CN", "zh_cn", "cn", "en", "english")) -> str:
    """Read plain, list, or language-keyed values, preferring Chinese then English."""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        parts = [_localized_text(item, preferred) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        lowered = {str(key).lower(): item for key, item in value.items()}
        for key in preferred:
            candidate = lowered.get(key.lower())
            text = _localized_text(candidate, preferred) if candidate is not None else ""
            if text:
                return text
        # Some sources wrap a localized value as {"text": "..."}.
        for key in ("text", "value", "description"):
            if key in lowered:
                text = _localized_text(lowered[key], preferred)
                if text:
                    return text
    return ""


_MUSCLE_ZH = {
    "pectorals": "胸肌", "chest": "胸肌", "pectoralis major": "胸大肌",
    "lats": "背阔肌", "latissimus dorsi": "背阔肌", "middle back": "中背部",
    "lower back": "下背部", "traps": "斜方肌", "shoulders": "肩部",
    "deltoids": "三角肌", "biceps": "肱二头肌", "triceps": "肱三头肌",
    "forearms": "前臂", "abdominals": "腹肌", "abs": "腹肌",
    "quadriceps": "股四头肌", "quads": "股四头肌", "hamstrings": "腘绳肌",
    "glutes": "臀肌", "calves": "小腿", "adductors": "内收肌",
    "abductors": "外展肌", "hip flexors": "髋屈肌",
}
_BODY_PART_ZH = {
    "chest": "胸部", "back": "背部", "shoulders": "肩部", "upper arms": "上臂",
    "lower arms": "前臂", "upper legs": "大腿", "lower legs": "小腿",
    "waist": "腰腹", "hips": "髋部", "neck": "颈部", "cardio": "心肺",
}
_EQUIPMENT_ZH = {
    "body only": "徒手", "body weight": "徒手", "dumbbell": "哑铃", "barbell": "杠铃",
    "cable": "绳索器械", "machine": "固定器械", "kettlebell": "壶铃",
    "bands": "弹力带", "resistance band": "弹力带", "medicine ball": "药球",
    "ez bar": "曲杆", "foam roll": "泡沫轴", "none": "无器械",
}


def _with_english_label(value: str, mapping: dict[str, str]) -> str:
    text = _clean(value)
    translated = mapping.get(text.casefold())
    return f"{translated}（{text}）" if translated and translated.casefold() != text.casefold() else (translated or text)


def _list_text(value: Any, mapping: dict[str, str] | None = None) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = _localized_text(item)
        if not text:
            continue
        # Localized arrays may already contain multiple line-separated values.
        for part in text.splitlines():
            part = _clean(part)
            if part:
                result.append(_with_english_label(part, mapping) if mapping else part)
    return list(dict.fromkeys(result))


def exercise_record_to_fact(record: Any) -> dict[str, Any] | None:
    """Convert one exercises-dataset record; media URLs are intentionally ignored."""
    if not isinstance(record, dict):
        return None
    name = _localized_text(record.get("name") or record.get("title") or record.get("name_zh"))
    if not name:
        return None

    category = _list_text(record.get("category") or record.get("movement_group"))
    body_parts = _list_text(record.get("body_parts") or record.get("body_part"), _BODY_PART_ZH)
    equipment = _list_text(record.get("equipment"), _EQUIPMENT_ZH)
    primary = _list_text(
        record.get("primary_muscle") or record.get("primary_muscles") or record.get("target_muscles") or record.get("target"),
        _MUSCLE_ZH,
    )
    secondary = _list_text(record.get("secondary_muscles") or record.get("secondary_muscle"), _MUSCLE_ZH)
    instructions = (
        _localized_text(record.get("instruction_steps"))
        or _localized_text(record.get("instructions"))
        or _localized_text(record.get("description"))
        or _localized_text(record.get("steps"))
    )

    lines = [f"动作名称：{name}"]
    if category:
        lines.append(f"动作分类：{'、'.join(category)}")
    if body_parts:
        lines.append(f"涉及身体部位：{'、'.join(body_parts)}")
    if equipment:
        lines.append(f"所需器械：{'、'.join(equipment)}")
    if primary:
        lines.append(f"主要目标肌群：{'、'.join(primary)}")
    if secondary:
        lines.append(f"辅助肌群：{'、'.join(secondary)}")
    if instructions:
        lines.append("动作说明：")
        steps = [line.strip(" \t-•") for line in instructions.splitlines() if line.strip(" \t-•")]
        if len(steps) > 1:
            lines.extend(f"{index}. {step}" for index, step in enumerate(steps, 1))
        else:
            lines.append(instructions)

    entities: list[dict[str, Any]] = [{"label": "健身动作", "name": name}]
    relationships: list[dict[str, Any]] = []

    def add_links(label: str, values: list[str], relation: str) -> None:
        for value in values:
            # The graph overview is keyed by name within a document; keep entity names unique.
            if not any(item["name"] == value for item in entities):
                entities.append({"label": label, "name": value})
            relationships.append({
                "sourceLabel": "健身动作", "sourceName": name,
                "relName": relation, "targetLabel": label, "targetName": value,
                "relProps": {"source": "exercises-dataset"},
            })

    add_links("目标肌群", primary, "锻炼")
    add_links("目标肌群", secondary, "辅助锻炼")
    add_links("身体部位", body_parts, "涉及")
    add_links("器械工具", equipment, "使用")
    if category:
        add_links("动作分类", category, "属于")

    return {
        "name": name,
        "content": "\n".join(lines),
        "entities": entities,
        "relationships": relationships,
    }


def _unique_entities(facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for fact in facts:
        for entity in fact.get("entities", []):
            key = (str(entity.get("label", "Entity")), str(entity.get("name", "")))
            if key[1] and key not in seen:
                seen.add(key)
                result.append({"label": key[0], "name": key[1]})
    return result


def _unique_relationships(facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for fact in facts:
        for rel in fact.get("relationships", []):
            key = tuple(str(rel.get(field, "")) for field in (
                "sourceLabel", "sourceName", "relName", "targetLabel", "targetName"
            ))
            if key[1] and key[4] and key not in seen:
                seen.add(key)
                result.append({
                    "sourceLabel": key[0], "sourceName": key[1], "relName": key[2],
                    "targetLabel": key[3], "targetName": key[4],
                    "relProps": dict(rel.get("relProps") or {}),
                })
    return result


def _group(items: list[dict[str, Any]], group_size: int) -> Iterable[tuple[int, list[dict[str, Any]]]]:
    if group_size < 1:
        raise ValueError("group_size 必须大于 0")
    for offset in range(0, len(items), group_size):
        yield offset // group_size + 1, items[offset:offset + group_size]


def build_exercise_documents(
    records: Any, *, source_digest: str, group_size: int = 25
) -> tuple[list[KnowledgeDocument], ConversionStats]:
    if isinstance(records, dict):
        for key in ("exercises", "data", "results", "items"):
            if isinstance(records.get(key), list):
                records = records[key]
                break
    if not isinstance(records, list):
        raise ValueError("exercises JSON 顶层必须是数组，或包含 exercises/data/results/items 数组")

    stats = ConversionStats(total_records=len(records))
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        fact = exercise_record_to_fact(record)
        if fact is None:
            stats.invalid_records += 1
            continue
        signature = hashlib.sha256((fact["name"] + "\0" + fact["content"]).encode("utf-8")).hexdigest()
        if signature in seen:
            stats.duplicate_records += 1
            continue
        seen.add(signature)
        facts.append(fact)
        stats.accepted_records += 1

    docs: list[KnowledgeDocument] = []
    for group_number, group in _group(facts, group_size):
        content = "\n\n---\n\n".join(fact["content"] for fact in group)
        docs.append(KnowledgeDocument(
            source="exercises-dataset",
            source_key=f"{source_digest}:group-{group_number:05d}",
            title=f"动作知识库 {group_number:03d}（{len(group)}项）",
            content=content,
            entities=_unique_entities(group),
            relationships=_unique_relationships(group),
        ))
    return docs, stats


def fitkg_record_to_fact(record: Any) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """Convert one FitKG-CN row. Span end offsets in this corpus are inclusive."""
    issues = {"invalid_record": 0, "invalid_span": 0, "invalid_relation": 0}
    if not isinstance(record, dict) or not isinstance(record.get("tokens"), list):
        issues["invalid_record"] = 1
        return None, issues
    tokens = record["tokens"]
    if any(not isinstance(token, str) for token in tokens):
        issues["invalid_record"] = 1
        return None, issues
    sentence = _clean("".join(tokens))
    if not sentence:
        issues["invalid_record"] = 1
        return None, issues

    raw_entities = record.get("entities") or []
    if not isinstance(raw_entities, list):
        issues["invalid_record"] = 1
        return None, issues
    entities: list[dict[str, Any] | None] = []
    for entity in raw_entities:
        if not isinstance(entity, dict):
            issues["invalid_span"] += 1
            entities.append(None)
            continue
        start, end = entity.get("start"), entity.get("end")
        if (
            isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, int) or not isinstance(end, int)
            or start < 0 or end < start or end >= len(tokens)
        ):
            issues["invalid_span"] += 1
            entities.append(None)
            continue
        name = _clean("".join(tokens[start:end + 1]))
        label = _clean(str(entity.get("type") or "实体"))
        if not name:
            issues["invalid_span"] += 1
            entities.append(None)
            continue
        entities.append({"label": label, "name": name})

    relationships: list[dict[str, Any]] = []
    raw_relations = record.get("relations") or []
    if not isinstance(raw_relations, list):
        raw_relations = []
        issues["invalid_relation"] += 1
    for rel in raw_relations:
        if not isinstance(rel, dict):
            issues["invalid_relation"] += 1
            continue
        head, tail = rel.get("head"), rel.get("tail")
        if (
            isinstance(head, bool) or isinstance(tail, bool)
            or not isinstance(head, int) or not isinstance(tail, int)
            or head < 0 or tail < 0 or head >= len(entities) or tail >= len(entities)
            or entities[head] is None or entities[tail] is None
        ):
            issues["invalid_relation"] += 1
            continue
        source = entities[head]
        target = entities[tail]
        assert source is not None and target is not None
        relationships.append({
            "sourceLabel": source["label"], "sourceName": source["name"],
            "relName": _clean(str(rel.get("type") or "关联")),
            "targetLabel": target["label"], "targetName": target["name"],
            "relProps": {"source": "FitKG-CN"},
        })

    valid_entities = [entity for entity in entities if entity is not None]
    if not valid_entities:
        issues["invalid_record"] = 1
        return None, issues

    lines = [f"原文：{sentence}"]
    lines.append("识别实体：" + "；".join(f"{item['name']}（{item['label']}）" for item in valid_entities))
    if relationships:
        lines.append("知识关系：" + "；".join(
            f"{rel['sourceName']}（{rel['sourceLabel']}）—{rel['relName']}→"
            f"{rel['targetName']}（{rel['targetLabel']}）"
            for rel in relationships
        ))
    return {"content": "\n".join(lines), "entities": valid_entities, "relationships": relationships}, issues


def build_fitkg_documents(
    records: Any, *, source_digest: str, partition: str = "train", group_size: int = 100
) -> tuple[list[KnowledgeDocument], ConversionStats]:
    if not isinstance(records, list):
        raise ValueError("FitKG JSON 顶层必须是数组")
    stats = ConversionStats(total_records=len(records))
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        fact, issues = fitkg_record_to_fact(record)
        stats.invalid_spans += issues["invalid_span"]
        stats.invalid_relations += issues["invalid_relation"]
        stats.invalid_records += issues["invalid_record"]
        if fact is None:
            continue
        signature = hashlib.sha256(fact["content"].encode("utf-8")).hexdigest()
        if signature in seen:
            stats.duplicate_records += 1
            continue
        seen.add(signature)
        facts.append(fact)
        stats.accepted_records += 1

    docs: list[KnowledgeDocument] = []
    for group_number, group in _group(facts, group_size):
        content = "\n\n".join(fact["content"] for fact in group)
        docs.append(KnowledgeDocument(
            source=f"FitKG-CN-{partition}",
            source_key=f"{source_digest}:group-{group_number:05d}",
            title=f"FitKG-CN 健身知识 {partition} {group_number:03d}",
            content=content,
            entities=_unique_entities(group),
            relationships=_unique_relationships(group),
        ))
    return docs, stats


def load_json_file(path: str) -> tuple[Any, str]:
    """Read UTF-8 JSON and return its parsed value and SHA-256 of the exact file bytes."""
    from pathlib import Path

    file_path = Path(path)
    raw = file_path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 JSON 文件 {file_path}: {exc}") from exc
    return data, hashlib.sha256(raw).hexdigest()
