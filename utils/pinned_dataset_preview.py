"""Fetch pinned public JSON files and build a read-only review report.

This module has no application database imports and never follows media URLs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any

import httpx

from utils.exercise_catalog import convert_exercise_records
from utils.nutrition_catalog import convert_food_records, convert_recipe_records, portion_profile_map

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = PROJECT_ROOT / "config" / "fitness_dataset_sources.json"
DEFAULT_REPORT_PATH = Path.home() / ".knowledge-agent" / "fitness-dataset-preview.json"
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ALLOWED_FILE_BYTES = 100 * 1024 * 1024
_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_LICENSE_STATUSES = {"pending_review", "approved", "restricted"}
_MEDIA_LICENSE_STATUSES = {"unverified", "pending_review", "approved", "restricted", "not_applicable"}
_KINDS = {"exercise", "food_records", "recipe_records", "portion_profiles"}
_NUTRIENT_FIELDS = {
    "energyKCal", "energyKJ", "protein", "fat", "CHO", "dietaryFiber", "sodium", "Na",
    "cholesterol", "vitaminA", "vitaminC", "vitaminE", "Ca", "P", "K", "Mg", "Fe", "Zn", "Se",
}


@dataclass(frozen=True, slots=True)
class PinnedFile:
    dataset: str
    repository: str
    commit: str
    metadata_license_status: str
    media_license_status: str
    license_note: str
    path: str
    kind: str
    expected_sha256: str
    max_bytes: int
    record_license_by_source: dict[str, str] = field(default_factory=dict)
    nutrition_basis_by_source: dict[str, str] = field(default_factory=dict)
    recipe_license_by_source: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        owner, repo = self.repository.split("/", maxsplit=1)
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{self.commit}/{self.path}"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON 含有非标准数值：{value}")


def _parse_json(raw: bytes, label: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} 不是有效 UTF-8 JSON：{exc}") from exc


def parse_source_lock(data: Any) -> tuple[list[PinnedFile], str]:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("来源锁定清单必须是 schema_version=1 的 JSON 对象。")
    locked_on = data.get("locked_on")
    if not isinstance(locked_on, str):
        raise ValueError("来源锁定清单缺少 locked_on 日期。")
    try:
        datetime.strptime(locked_on, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("locked_on 日期格式必须为 YYYY-MM-DD。") from exc

    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("来源锁定清单的 sources 必须是非空数组。")

    files: list[PinnedFile] = []
    seen_datasets: set[str] = set()
    seen_files: set[tuple[str, str]] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("每个来源必须是 JSON 对象。")
        dataset = source.get("dataset")
        repository = source.get("repository")
        commit = source.get("commit")
        license_status = source.get("metadata_license_status")
        media_status = source.get("media_license_status")
        license_note = source.get("license_note", "")

        if not isinstance(dataset, str) or not _NAME_RE.fullmatch(dataset):
            raise ValueError("dataset 只能包含英文字母、数字、点、下划线或连字符。")
        if dataset in seen_datasets:
            raise ValueError(f"来源名称重复：{dataset}")
        seen_datasets.add(dataset)
        if not isinstance(repository, str) or len(repository.split("/")) != 2:
            raise ValueError(f"{dataset}: repository 必须为 owner/repository。")
        if any(not _NAME_RE.fullmatch(part) or part in {".", ".."} for part in repository.split("/")):
            raise ValueError(f"{dataset}: repository 格式无效。")
        if not isinstance(commit, str) or not _SHA1_RE.fullmatch(commit) or set(commit) == {"0"}:
            raise ValueError(f"{dataset}: commit 必须是完整的 40 位 Git commit SHA，不能使用分支名。")
        if license_status not in _LICENSE_STATUSES:
            raise ValueError(f"{dataset}: metadata_license_status 无效。")
        if media_status not in _MEDIA_LICENSE_STATUSES:
            raise ValueError(f"{dataset}: media_license_status 无效。")
        if not isinstance(license_note, str):
            raise ValueError(f"{dataset}: license_note 必须是字符串。")

        source_files = source.get("files")
        if not isinstance(source_files, list) or not source_files:
            raise ValueError(f"{dataset}: files 必须是非空白名单数组。")
        for item in source_files:
            if not isinstance(item, dict):
                raise ValueError(f"{dataset}: 每个文件配置必须是 JSON 对象。")
            path = item.get("path")
            kind = item.get("kind")
            expected_sha256 = item.get("expected_sha256")
            max_bytes = item.get("max_bytes", DEFAULT_MAX_FILE_BYTES)
            record_licenses = item.get("record_license_by_source", {})
            nutrition_bases = item.get("nutrition_basis_by_source", {})
            recipe_licenses = item.get("recipe_license_by_source", {})
            if (
                not isinstance(path, str)
                or "\\" in path
                or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or PurePosixPath(path).suffix.lower() != ".json"
            ):
                raise ValueError(f"{dataset}: 仅允许无路径穿越的相对 .json 路径：{path!r}")
            if kind not in _KINDS:
                raise ValueError(f"{dataset}/{path}: kind 必须是 {', '.join(sorted(_KINDS))} 之一。")
            if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
                raise ValueError(f"{dataset}/{path}: 必须提供完整 SHA-256 expected_sha256。")
            if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_ALLOWED_FILE_BYTES:
                raise ValueError(f"{dataset}/{path}: max_bytes 必须在 1 至 {MAX_ALLOWED_FILE_BYTES} 之间。")
            if not isinstance(record_licenses, dict) or any(
                not isinstance(key, str) or value not in _LICENSE_STATUSES
                for key, value in record_licenses.items()
            ):
                raise ValueError(f"{dataset}/{path}: record_license_by_source 的值必须是受支持的许可状态。")
            if not isinstance(recipe_licenses, dict) or any(
                not isinstance(key, str) or value not in _LICENSE_STATUSES
                for key, value in recipe_licenses.items()
            ):
                raise ValueError(f"{dataset}/{path}: recipe_license_by_source 的值必须是受支持的许可状态。")
            if not isinstance(nutrition_bases, dict) or any(
                not isinstance(key, str) or value not in {"unknown", "per_100g", "per_serving", "other"}
                for key, value in nutrition_bases.items()
            ):
                raise ValueError(f"{dataset}/{path}: nutrition_basis_by_source 的值无效。")
            key = (dataset, path)
            if key in seen_files:
                raise ValueError(f"来源文件重复：{dataset}/{path}")
            seen_files.add(key)
            files.append(PinnedFile(
                dataset=dataset,
                repository=repository,
                commit=commit.lower(),
                metadata_license_status=license_status,
                media_license_status=media_status,
                license_note=license_note,
                path=path,
                kind=kind,
                expected_sha256=expected_sha256.lower(),
                max_bytes=max_bytes,
                record_license_by_source=dict(record_licenses),
                nutrition_basis_by_source=dict(nutrition_bases),
                recipe_license_by_source=dict(recipe_licenses),
            ))
    return files, locked_on


def load_source_lock(path: Path) -> tuple[list[PinnedFile], str]:
    try:
        lock_data = _parse_json(path.read_bytes(), f"来源锁定清单 {path}")
    except OSError as exc:
        raise ValueError(f"无法读取来源锁定清单 {path}: {exc}") from exc
    return parse_source_lock(lock_data)


def fetch_pinned_json(
    source_file: PinnedFile,
    client: httpx.Client,
    *,
    max_bytes: int | None = None,
    staging_dir: Path | None = None,
) -> tuple[Any, dict[str, Any]]:
    limit = min(source_file.max_bytes, max_bytes or source_file.max_bytes)
    body = bytearray()
    try:
        with client.stream("GET", source_file.url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise RuntimeError(
                    f"获取 {source_file.dataset}/{source_file.path} 失败：HTTP {response.status_code}。"
                )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > limit:
                        raise RuntimeError(f"{source_file.dataset}/{source_file.path} 超过大小上限 {limit} 字节。")
                except ValueError as exc:
                    raise RuntimeError("上游返回了无效的 Content-Length。") from exc
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > limit:
                    raise RuntimeError(f"{source_file.dataset}/{source_file.path} 超过大小上限 {limit} 字节。")
    except httpx.HTTPError as exc:
        raise RuntimeError(f"获取 {source_file.dataset}/{source_file.path} 网络失败：{exc}") from exc

    raw = bytes(body)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source_file.expected_sha256:
        raise RuntimeError(
            f"{source_file.dataset}/{source_file.path} SHA-256 不匹配："
            f"期望 {source_file.expected_sha256}，实际 {digest}。"
        )
    if staging_dir is not None:
        staged_path = staging_dir / source_file.dataset / PurePosixPath(source_file.path)
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(raw)
        raw = staged_path.read_bytes()
    parsed = _parse_json(raw, f"{source_file.dataset}/{source_file.path}")
    return parsed, {"bytes": len(raw), "sha256": digest, "hash_verified": True}


def _extract_list(value: Any, label: str, envelope_keys: tuple[str, ...] = ()) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in envelope_keys:
            if isinstance(value.get(key), list):
                return value[key]
    raise ValueError(f"{label} 顶层必须是数组或包含预期数组字段。")


def _url_count(records: list[Any]) -> int:
    count = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        videos = record.get("videos")
        if isinstance(videos, dict):
            count += sum(
                isinstance(value, str) and value.strip().lower().startswith(("http://", "https://"))
                for value in videos.values()
            )
    return count


def _exercise_preview(source_file: PinnedFile, data: Any, sample_count: int) -> dict[str, Any]:
    records = _extract_list(data, source_file.path, ("exercises", "data", "results", "items"))
    items, stats = convert_exercise_records(records)
    samples = [{
        "upstream_id": item.upstream_id,
        "name": item.name,
        "missing_fields": item.missing_fields,
        "normalized_content": item.display_content[:1400],
        "media_reference_count": len(item.media_refs),
    } for item in items[:sample_count]]

    quarantined = stats.accepted_records if source_file.metadata_license_status != "approved" else 0
    return {
        "conversion_status": "normalized_by_existing_exercise_converter",
        "counts": {
            "input_records": stats.input_records,
            "accepted_records": stats.accepted_records,
            "duplicate_records": stats.duplicate_records,
            "invalid_records": stats.invalid_records,
            "quarantined_records": quarantined,
        },
        "quarantine_reasons": (
            ["动作文字许可尚未批准"] if quarantined else []
        ),
        "video_url_count": _url_count(records),
        "video_urls_requested": 0,
        "normalized_samples": samples,
    }


def _raw_dataset_preview(
    source_file: PinnedFile,
    data: Any,
    sample_count: int,
    *,
    foods: list[Any] | None = None,
) -> dict[str, Any]:
    if source_file.kind == "food_records":
        items, stats = convert_food_records(
            data,
            license_by_source=source_file.record_license_by_source,
            nutrition_basis_by_source=source_file.nutrition_basis_by_source,
        )
        samples = [{
            "upstream_id": item.upstream_id,
            "name": item.name[:160],
            "source": item.source_key[:120],
            "nutrition_basis": item.nutrition_basis,
            "nutrient_fields": sorted(item.nutrients_raw),
            "missing_fields": item.missing_fields,
            "record_status": item.record_status,
            "quarantine_reasons": item.quarantine_reasons,
        } for item in items[:sample_count]]
        quarantined_count = sum(item.record_status == "quarantined" for item in items)
        invalid_count = stats.invalid_records
        counts = {
            "input_records": stats.input_records,
            "accepted_records": stats.accepted_records,
            "duplicate_records": stats.duplicate_records,
            "invalid_records": invalid_count,
            "quarantined_records": quarantined_count,
        }
        source_distribution = Counter(item.source_key for item in items)
        metadata = {"source_distribution": dict(sorted(source_distribution.items()))}
        return {
            "conversion_status": "normalized_by_pinned_food_converter",
            "counts": counts,
            "quarantine_reasons": sorted({reason for item in items for reason in item.quarantine_reasons}),
            "metadata": metadata,
            "normalized_samples": samples,
            "raw_review_samples": [],
            "deduplication_status": "checked",
        }
    elif source_file.kind == "recipe_records":
        items, stats = convert_recipe_records(
            data,
            foods or [],
            recipe_license_by_source=source_file.recipe_license_by_source,
        )
        samples = [{
            "upstream_id": item.upstream_id,
            "title": item.title[:160],
            "source_name": item.source_name[:120] or "missing",
            "source_license": item.source_license[:120] or "missing",
            "servings": str(item.servings) if item.servings is not None else None,
            "ingredient_count": len(item.ingredients),
            "ingredient_match_statuses": dict(Counter(ingredient.match_status for ingredient in item.ingredients)),
            "nutrition_status": item.nutrition_status,
            "record_status": item.record_status,
            "quarantine_reasons": item.quarantine_reasons,
        } for item in items[:sample_count]]
        quarantined_count = sum(item.record_status == "quarantined" for item in items)
        counts = {
            "input_records": stats.input_records,
            "accepted_records": stats.accepted_records,
            "duplicate_records": stats.duplicate_records,
            "invalid_records": stats.invalid_records,
            "quarantined_records": quarantined_count,
        }
        distribution = Counter(item.source_license or "missing" for item in items)
        metadata = {"source_license_distribution": dict(sorted(distribution.items()))}
        return {
            "conversion_status": "normalized_by_pinned_recipe_converter",
            "counts": counts,
            "quarantine_reasons": sorted({reason for item in items for reason in item.quarantine_reasons}),
            "metadata": metadata,
            "normalized_samples": samples,
            "raw_review_samples": [],
            "deduplication_status": "checked",
        }
    else:
        profiles = portion_profile_map(data)
        records = list(profiles.values())
        samples = [
            {key: str(row[key])[:120] for key in ("foodName", "name", "unit") if row.get(key) is not None}
            for row in records
        ][:sample_count]
        metadata = {"profile_source": data.get("source")}
        invalid_count = len(data["profiles"]) - len(records)
        return {
            "conversion_status": "validated_portion_profiles_pending_review",
            "counts": {
                "input_records": len(data["profiles"]),
                "accepted_records": len(records),
                "duplicate_records": len(data["profiles"]) - len(records) - invalid_count,
                "invalid_records": invalid_count,
                "quarantined_records": len(records),
                "structurally_valid_records": len(records),
            },
            "quarantine_reasons": ["份量换算为估算参考，许可与适用范围仍待审核"],
            "metadata": metadata,
            "normalized_samples": [],
            "raw_review_samples": samples,
            "deduplication_status": "profile_keys_checked",
        }

    # Kept unreachable as a defensive guard if another raw kind is added.
    reasons = ["未配置对应转换器"]
    return {
        "conversion_status": "pending_dedicated_converter",
        "counts": {"input_records": 0, "accepted_records": 0, "duplicate_records": 0, "invalid_records": 0, "quarantined_records": 0},
        "quarantine_reasons": reasons,
        "metadata": metadata,
        "normalized_samples": [],
        "raw_review_samples": samples,
        "deduplication_status": "not_checked_until_dedicated_converter_exists",
    }


def _file_preview(
    source_file: PinnedFile,
    data: Any,
    fetch_meta: dict[str, Any],
    sample_count: int,
    *,
    foods: list[Any] | None = None,
) -> dict[str, Any]:
    if source_file.kind == "exercise":
        details = _exercise_preview(source_file, data, sample_count)
    else:
        details = _raw_dataset_preview(source_file, data, sample_count, foods=foods)
    return {
        "path": source_file.path,
        "kind": source_file.kind,
        "file_bytes": fetch_meta["bytes"],
        "expected_sha256": source_file.expected_sha256,
        "sha256": fetch_meta["sha256"],
        "hash_verified": fetch_meta["hash_verified"],
        "metadata_license_status": source_file.metadata_license_status,
        "media_license_status": source_file.media_license_status,
        "record_license_by_source": source_file.record_license_by_source,
        "nutrition_basis_by_source": source_file.nutrition_basis_by_source,
        "recipe_license_by_source": source_file.recipe_license_by_source,
        **details,
    }


def preview_pinned_sources(
    lock_path: Path,
    client: httpx.Client,
    *,
    sample_count: int = 3,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, Any]:
    if sample_count < 0:
        raise ValueError("--samples 不能小于 0。")
    if not 1 <= max_bytes <= MAX_ALLOWED_FILE_BYTES:
        raise ValueError(f"--max-bytes 必须在 1 至 {MAX_ALLOWED_FILE_BYTES} 之间。")
    lock_raw = lock_path.expanduser().read_bytes()
    source_files, locked_on = parse_source_lock(_parse_json(lock_raw, f"来源锁定清单 {lock_path}"))

    # Fetch and validate every file before constructing a report; a partial source
    # set must not look like a complete preview.
    fetched: list[tuple[PinnedFile, Any, dict[str, Any]]] = []
    with tempfile.TemporaryDirectory(prefix="knowledge-agent-dataset-preview-") as staging:
        for source_file in source_files:
            parsed, fetch_meta = fetch_pinned_json(
                source_file,
                client,
                max_bytes=max_bytes,
                staging_dir=Path(staging),
            )
            fetched.append((source_file, parsed, fetch_meta))

        sources_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        food_items_by_source: dict[tuple[str, str], list[Any]] = {}
        for source_file, data, _ in fetched:
            if source_file.kind == "food_records":
                food_items_by_source[(source_file.dataset, source_file.commit)], _ = convert_food_records(
                    data,
                    license_by_source=source_file.record_license_by_source,
                    nutrition_basis_by_source=source_file.nutrition_basis_by_source,
                )

        for source_file, data, fetch_meta in fetched:
            key = (source_file.dataset, source_file.repository, source_file.commit)
            source = sources_by_key.setdefault(key, {
                "dataset": source_file.dataset,
                "repository": source_file.repository,
                "commit": source_file.commit,
                "metadata_license_status": source_file.metadata_license_status,
                "media_license_status": source_file.media_license_status,
                "license_note": source_file.license_note,
                "files": [],
            })
            source["files"].append(_file_preview(
                source_file,
                data,
                fetch_meta,
                sample_count,
                foods=food_items_by_source.get((source_file.dataset, source_file.commit)),
            ))

        all_files = [file for source in sources_by_key.values() for file in source["files"]]
        counts = [file["counts"] for file in all_files]
        manifest = [
            {
                "dataset": source_file.dataset,
                "repository": source_file.repository,
                "commit": source_file.commit,
                "locked_on": locked_on,
                "path": source_file.path,
                "bytes": fetch_meta["bytes"],
                "sha256": fetch_meta["sha256"],
            }
            for source_file, _, fetch_meta in fetched
        ]
        return {
            "schema_version": 2,
            "run_mode": "dry_run_only",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "locked_on": locked_on,
            "source_lock_sha256": hashlib.sha256(lock_raw).hexdigest(),
            "file_manifest": manifest,
            "database_accessed": False,
            "database_written": False,
            "media_urls_requested": 0,
            "summary": {
                "source_files": len(all_files),
                "input_records": sum(item["input_records"] for item in counts),
                "accepted_records": sum(item["accepted_records"] for item in counts),
                "duplicates_detected": sum(item["duplicate_records"] or 0 for item in counts),
                "files_without_deduplication": sum(item["duplicate_records"] is None for item in counts),
                "invalid_records": sum(item["invalid_records"] for item in counts),
                "quarantined_records": sum(item["quarantined_records"] for item in counts),
            },
            "sources": list(sources_by_key.values()),
        }


def _load_json_file(path: Path, label: str) -> Any:
    try:
        return _parse_json(path.expanduser().read_bytes(), label)
    except OSError as exc:
        raise ValueError(f"无法读取{label} {path}: {exc}") from exc


def _flatten_report_files(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for source in report.get("sources", []):
        for file in source.get("files", []):
            key = (source.get("dataset"), file.get("path"))
            if key in result:
                raise ValueError(f"预览报告中存在重复文件：{key[0]}/{key[1]}")
            result[key] = {
                "repository": source.get("repository"),
                "commit": source.get("commit"),
                "metadata_license_status": source.get("metadata_license_status"),
                "bytes": file.get("file_bytes"),
                "sha256": file.get("sha256"),
                "hash_verified": file.get("hash_verified"),
            }
    return result


def validate_reviewed_manifest(
    lock_path: Path,
    report_path: Path,
    approval_path: Path,
    client: httpx.Client,
    *,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
    allow_partial_licenses: bool = False,
) -> dict[str, Any]:
    """Re-fetch and verify an explicitly approved preview before any import writes."""
    report_path = report_path.expanduser().resolve()
    report_raw = report_path.read_bytes()
    report_sha256 = hashlib.sha256(report_raw).hexdigest()
    report = _parse_json(report_raw, f"预览报告 {report_path}")
    approval = _load_json_file(approval_path, "审阅批准记录")
    if not isinstance(report, dict) or report.get("schema_version") != 2 or report.get("run_mode") != "dry_run_only":
        raise ValueError("预览报告格式不受支持；请重新生成当前版本的只读预览。")
    if report.get("database_accessed") is not False or report.get("database_written") is not False:
        raise ValueError("预览报告必须明确记录未访问且未写入数据库。")
    if not isinstance(approval, dict) or approval.get("schema_version") != 1:
        raise ValueError("审阅批准记录必须是 schema_version=1 的 JSON 对象。")
    if approval.get("approved") is not True:
        raise ValueError("审阅批准记录未明确批准该预览。")
    if approval.get("preview_report_sha256") != report_sha256:
        raise ValueError("审阅批准记录未绑定当前预览报告；报告变化后必须重新审阅。")
    if not isinstance(approval.get("reviewer"), str) or not approval["reviewer"].strip():
        raise ValueError("审阅批准记录缺少 reviewer。")
    try:
        datetime.fromisoformat(approval["reviewed_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError("审阅批准记录的 reviewed_at 必须是 ISO 8601 日期时间。") from exc

    lock_raw = lock_path.expanduser().read_bytes()
    lock_files, locked_on = parse_source_lock(_parse_json(lock_raw, f"来源锁定清单 {lock_path}"))
    if report.get("source_lock_sha256") != hashlib.sha256(lock_raw).hexdigest():
        raise ValueError("当前来源锁定清单与已审阅预览不同；请重新生成并审阅预览。")
    if report.get("locked_on") != locked_on:
        raise ValueError("当前来源锁定日期与已审阅预览不同；请重新生成并审阅预览。")
    report_files = _flatten_report_files(report)
    expected_keys = {(item.dataset, item.path) for item in lock_files}
    if set(report_files) != expected_keys:
        raise ValueError("当前来源锁中的文件集合与已审阅预览不一致。")

    results = []
    for source_file in lock_files:
        key = (source_file.dataset, source_file.path)
        reviewed = report_files[key]
        if (
            reviewed["repository"] != source_file.repository
            or reviewed["commit"] != source_file.commit
            or reviewed["metadata_license_status"] != source_file.metadata_license_status
        ):
            raise ValueError(f"{source_file.dataset}/{source_file.path} 来源版本或许可状态与已审阅预览不一致。")
        if source_file.metadata_license_status != "approved" and not allow_partial_licenses:
            raise ValueError(
                f"{source_file.dataset}/{source_file.path} 许可状态为 {source_file.metadata_license_status}，禁止进入正式导入。"
            )
        if reviewed["hash_verified"] is not True or reviewed["sha256"] != source_file.expected_sha256:
            raise ValueError(f"{source_file.dataset}/{source_file.path} 预览摘要未通过来源锁校验。")
        parsed, actual = fetch_pinned_json(source_file, client, max_bytes=max_bytes)
        del parsed
        if actual["bytes"] != reviewed["bytes"] or actual["sha256"] != reviewed["sha256"]:
            raise ValueError(f"{source_file.dataset}/{source_file.path} 当前文件与已审阅预览不一致。")
        results.append({
            "dataset": source_file.dataset,
            "path": source_file.path,
            "commit": source_file.commit,
            "bytes": actual["bytes"],
            "sha256": actual["sha256"],
            "verified": True,
        })

    return {
        "approved": True,
        "partial_licenses_allowed": allow_partial_licenses,
        "reviewer": approval["reviewer"].strip(),
        "preview_report_sha256": report_sha256,
        "database_accessed": False,
        "database_written": False,
        "media_urls_requested": 0,
        "files": results,
    }


def write_preview_report(path: Path, report: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从固定 Git commit 读取白名单 JSON，生成只读预览报告；不会连接或写入应用数据库。"
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH, help="来源/文件/SHA-256 锁定清单")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH, help="预览报告输出位置")
    parser.add_argument("--samples", type=int, default=3, help="每个文件最多输出的样例数")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES, help="单个 JSON 文件最大字节数")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次 HTTPS 请求超时秒数")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=False,
            headers={"User-Agent": "knowledge-agent-dataset-preview/1.0"},
        ) as client:
            report = preview_pinned_sources(
                args.lock,
                client,
                sample_count=args.samples,
                max_bytes=args.max_bytes,
            )
        write_preview_report(args.output, report)
        print(f"只读预览完成：{args.output.expanduser().resolve()}")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print("未连接或写入数据库；未请求任何视频/图片 URL。")
        return 0
    except Exception as exc:
        print(f"预览失败：{exc}", file=sys.stderr)
        print("本次没有连接或写入应用数据库，也没有请求媒体 URL。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
