"""Pure converter for the pinned free-exercise-db-api exercise records."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

from utils.fitness_knowledge import exercise_record_to_fact


@dataclass(slots=True)
class ExerciseCatalogItem:
    upstream_id: str
    name: str
    name_normalized: str
    aliases: list[str]
    normalized_fields: dict[str, Any]
    missing_fields: list[str]
    display_content: str
    media_refs: list[dict[str, str]] = field(default_factory=list)
    raw_record: dict[str, Any] = field(default_factory=dict)
    content_sha256: str = ""
    license_status: str = "pending_review"
    record_status: str = "quarantined"
    quarantine_reasons: list[str] = field(default_factory=lambda: ["动作文字许可尚未批准"])


@dataclass(slots=True)
class ExerciseCatalogStats:
    input_records: int = 0
    accepted_records: int = 0
    duplicate_records: int = 0
    invalid_records: int = 0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _text_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(text for item in values if (text := _text(item))))


def _name_key(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _content_hash(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


def _normalized_fields(record: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    field_map = {
        "body_part": "bodyPart",
        "target_muscle": "target",
        "secondary_muscles": "secondaryMuscles",
        "equipment": "equipment",
        "difficulty": "difficulty",
        "compound": "compound",
        "unilateral": "unilateral",
        "short_description": "shortDescription",
        "instructions": "instructions",
        "steps": "steps",
        "form_cues": "formCues",
        "common_mistakes": "commonMistakes",
        "breathing": "breathing",
    }
    normalized: dict[str, Any] = {}
    missing: list[str] = []
    for canonical, source_key in field_map.items():
        value = record.get(source_key)
        if value is None or value == "" or value == []:
            normalized[canonical] = None
            missing.append(source_key)
        elif canonical in {"secondary_muscles", "steps", "form_cues", "common_mistakes"}:
            normalized[canonical] = _text_list(value)
        elif canonical == "instructions" and isinstance(value, list):
            normalized[canonical] = "\n".join(_text_list(value))
        elif canonical in {"body_part", "target_muscle", "equipment", "difficulty", "short_description", "instructions", "breathing"}:
            normalized[canonical] = _text(value)
            if not normalized[canonical]:
                missing.append(source_key)
        else:
            normalized[canonical] = value if isinstance(value, bool) else None
            if not isinstance(value, bool):
                missing.append(source_key)
    return normalized, missing


def _media_refs(record: Mapping[str, Any]) -> list[dict[str, str]]:
    media: list[dict[str, str]] = []
    for field_name, kind in (("videos", "video"), ("thumbnails", "image")):
        variants = record.get(field_name)
        if not isinstance(variants, Mapping):
            continue
        for variant, value in variants.items():
            url = _text(value)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            media.append({
                "kind": kind,
                "variant": _text(variant) or "default",
                "source_url": url,
                "source_host": parsed.hostname.casefold(),
                "license_status": "unverified" if kind == "video" else "pending_review",
                "mapping_status": "pending_review",
                "allowed_use": "none",
            })
    return media


def _display_content(name: str, fields: Mapping[str, Any]) -> str:
    compatible = {
        "name": name,
        "body_parts": fields["body_part"],
        "equipment": fields["equipment"],
        "primary_muscle": fields["target_muscle"],
        "secondary_muscles": fields["secondary_muscles"],
        "instruction_steps": fields["steps"] or fields["instructions"] or fields["short_description"],
    }
    fact = exercise_record_to_fact(compatible)
    if fact is None:
        return ""
    lines = [fact["content"]]
    optional_sections = (
        ("難度", fields["difficulty"]),
        ("动作提示", fields["form_cues"]),
        ("常见错误", fields["common_mistakes"]),
        ("呼吸", fields["breathing"]),
    )
    for label, value in optional_sections:
        values = value if isinstance(value, list) else [value]
        values = [str(item).strip() for item in values if item is not None and str(item).strip()]
        if values:
            lines.append(f"{label}：" + "；".join(values))
    return "\n".join(lines)


def convert_exercise_records(
    records: Any,
    *,
    license_status: str = "pending_review",
) -> tuple[list[ExerciseCatalogItem], ExerciseCatalogStats]:
    """Normalize records while retaining raw source data and keeping media inert.

    The default source license is pending review. Media URLs are stored only as inert
    references; this function never fetches them or approves their use.
    """
    if license_status not in {"pending_review", "approved", "restricted"}:
        raise ValueError("动作文字许可状态无效")
    if isinstance(records, dict):
        for key in ("exercises", "data", "results", "items"):
            if isinstance(records.get(key), list):
                records = records[key]
                break
    if not isinstance(records, list):
        raise ValueError("动作数据顶层必须是数组，或包含 exercises/data/results/items 数组")

    stats = ExerciseCatalogStats(input_records=len(records))
    converted: list[ExerciseCatalogItem] = []
    seen: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            stats.invalid_records += 1
            continue
        name = _text(record.get("name"))
        if not name:
            stats.invalid_records += 1
            continue
        try:
            digest = _content_hash(record)
        except (TypeError, ValueError):
            stats.invalid_records += 1
            continue
        raw_id = _text(record.get("id"))
        upstream_id = raw_id or f"sha256:{digest}"
        previous_digest = seen.get(upstream_id)
        if previous_digest is not None:
            if previous_digest == digest:
                stats.duplicate_records += 1
            else:
                stats.invalid_records += 1
            continue
        seen[upstream_id] = digest

        aliases = _text_list(record.get("aliases"))
        normalized, missing_fields = _normalized_fields(record)
        quarantine_reasons = [] if license_status == "approved" else ["动作文字许可尚未批准"]
        converted.append(ExerciseCatalogItem(
            upstream_id=upstream_id,
            name=name,
            name_normalized=_name_key(name),
            aliases=aliases,
            normalized_fields=normalized,
            missing_fields=missing_fields,
            display_content=_display_content(name, normalized),
            media_refs=_media_refs(record),
            raw_record=record.copy(),
            content_sha256=digest,
            license_status=license_status,
            record_status="active" if not quarantine_reasons else "quarantined",
            quarantine_reasons=quarantine_reasons,
        ))
        stats.accepted_records += 1

    return converted, stats
