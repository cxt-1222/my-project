import hashlib
import json
from datetime import datetime, timezone

import httpx
import pytest

from utils.pinned_dataset_preview import (
    fetch_pinned_json,
    parse_source_lock,
    preview_pinned_sources,
    validate_reviewed_manifest,
)


COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _source_lock(files, *, metadata_license_status="pending_review", media_license_status="not_applicable"):
    return {
        "schema_version": 1,
        "locked_on": "2026-10-27",
        "sources": [{
            "dataset": "test-dataset",
            "repository": "example/dataset",
            "commit": COMMIT,
            "metadata_license_status": metadata_license_status,
            "media_license_status": media_license_status,
            "license_note": "preview fixture",
            "files": files,
        }],
    }


def _file_config(payload, path="data/records.json", kind="food_records", **overrides):
    return {
        "path": path,
        "kind": kind,
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        **overrides,
    }


def _client_for(payload, status_code=200, headers=None):
    def handler(request):
        return httpx.Response(status_code, headers=headers, content=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_source_lock_requires_full_commit_json_path_and_expected_hash():
    payload = b"[]"
    config = _source_lock([_file_config(payload)])

    files, locked_on = parse_source_lock(config)

    assert locked_on == "2026-10-27"
    assert files[0].url == (
        "https://raw.githubusercontent.com/example/dataset/"
        f"{COMMIT}/data/records.json"
    )

    config["sources"][0]["commit"] = "main"
    with pytest.raises(ValueError, match="完整的 40 位 Git commit SHA"):
        parse_source_lock(config)


@pytest.mark.parametrize("path", ["../secrets.json", "/data.json", "data\\records.json", "data/records.txt"])
def test_source_lock_rejects_non_whitelisted_or_unsafe_paths(path):
    config = _source_lock([_file_config(b"[]", path=path)])

    with pytest.raises(ValueError, match="相对 .json 路径"):
        parse_source_lock(config)


def test_fetch_verifies_exact_sha_and_never_follows_redirects():
    payload = b'[{"name":"Squat"}]'
    files, _ = parse_source_lock(_source_lock([_file_config(payload)]))
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        parsed, metadata = fetch_pinned_json(files[0], client)

    assert parsed == [{"name": "Squat"}]
    assert metadata["bytes"] == len(payload)
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    assert requested == [files[0].url]


def test_fetch_rejects_digest_mismatch_http_errors_and_oversized_files():
    payload = b'[{"name":"Squat"}]'
    lock = _source_lock([_file_config(b"[]")])
    files, _ = parse_source_lock(lock)

    with _client_for(payload) as client:
        with pytest.raises(RuntimeError, match="SHA-256 不匹配"):
            fetch_pinned_json(files[0], client)

    with _client_for(payload, status_code=302, headers={"Location": "https://example.invalid/video.mp4"}) as client:
        with pytest.raises(RuntimeError, match="HTTP 302"):
            fetch_pinned_json(files[0], client)

    correct_file, _ = parse_source_lock(_source_lock([_file_config(payload)]))
    with _client_for(payload) as client:
        with pytest.raises(RuntimeError, match="超过大小上限"):
            fetch_pinned_json(correct_file[0], client, max_bytes=4)


def test_exercise_preview_counts_duplicates_and_never_includes_video_urls(tmp_path):
    video_url = "https://media.example.invalid/movement.mp4"
    record = {
        "id": "squat-1",
        "name": "Squat",
        "instructions": ["Stand tall", "Bend the knees"],
        "videos": {"male": video_url},
    }
    payload = json.dumps([record, record, {"equipment": "Dumbbell"}]).encode()
    lock_data = _source_lock(
        [_file_config(payload, path="data/exercises.json", kind="exercise")],
        metadata_license_status="pending_review",
        media_license_status="unverified",
    )
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    files, _ = parse_source_lock(lock_data)

    with _client_for(payload) as client:
        report = preview_pinned_sources(lock_path, client, sample_count=2)

    preview = report["sources"][0]["files"][0]
    assert preview["counts"] == {
        "input_records": 3,
        "accepted_records": 1,
        "duplicate_records": 1,
        "invalid_records": 1,
        "quarantined_records": 1,
    }
    assert preview["video_url_count"] == 2
    assert preview["video_urls_requested"] == 0
    assert "Stand tall" in preview["normalized_samples"][0]["normalized_content"]
    assert preview["normalized_samples"][0]["media_reference_count"] == 1
    assert video_url not in json.dumps(report)
    assert report["database_accessed"] is False
    assert report["database_written"] is False
    assert report["media_urls_requested"] == 0
    assert files[0].url not in json.dumps(report)


def test_food_preview_runs_converter_but_keeps_unknown_units_quarantined(tmp_path):
    payload = json.dumps([
        {"name": "Oats", "source": "usda-approx", "protein": 13.2},
        {"name": "Rice", "source": "composition-table", "protein": 7.0},
        {"source": "missing-name"},
    ]).encode()
    lock_data = _source_lock([_file_config(payload, kind="food_records")])
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    with _client_for(payload) as client:
        report = preview_pinned_sources(lock_path, client)

    preview = report["sources"][0]["files"][0]
    assert preview["conversion_status"] == "normalized_by_pinned_food_converter"
    assert preview["counts"]["input_records"] == 3
    assert preview["counts"]["accepted_records"] == 2
    assert preview["counts"]["duplicate_records"] == 0
    assert preview["counts"]["invalid_records"] == 1
    assert preview["counts"]["quarantined_records"] == 2
    assert preview["metadata"]["source_distribution"] == {
        "usda-approx": 1,
        "composition-table": 1,
    }
    assert all(row["nutrition_basis"] == "unknown" for row in preview["normalized_samples"])


def test_recipe_preview_uses_food_converter_and_reports_estimates_as_non_authoritative(tmp_path):
    foods = [{"name": "Oats", "source": "usda-approx", "code": "oats-1", "protein": 13.2}]
    recipes = [{
        "id": "oats-bowl",
        "title": "Oats Bowl",
        "servings": 1,
        "source": {"name": "Example", "license": "Unlicense"},
        "ingredients": [{
            "name": "Oats", "unit": "g", "amount": 50,
            "food": {"name": "Oats", "source": "usda-approx", "code": "oats-1"},
            "match": "food",
        }],
        "nutrition": {"protein": 6.6},
        "health": {"confidence": "estimated"},
    }]
    food_payload = json.dumps(foods).encode()
    recipe_payload = json.dumps(recipes).encode()
    lock_data = _source_lock([
        _file_config(food_payload, path="data/foods.json", kind="food_records"),
        _file_config(recipe_payload, path="data/recipes.json", kind="recipe_records"),
    ])
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")

    def handler(request):
        payload = food_payload if request.url.path.endswith("foods.json") else recipe_payload
        return httpx.Response(200, content=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        report = preview_pinned_sources(lock_path, client)

    recipe_preview = report["sources"][0]["files"][1]
    assert recipe_preview["conversion_status"] == "normalized_by_pinned_recipe_converter"
    assert recipe_preview["counts"]["accepted_records"] == 1
    assert recipe_preview["counts"]["quarantined_records"] == 1
    assert recipe_preview["normalized_samples"][0]["nutrition_status"] == "estimated_not_authoritative"


def test_source_lock_rejects_missing_digest_and_non_json_kind():
    config = _source_lock([{"path": "data/records.json", "kind": "food_records"}])
    with pytest.raises(ValueError, match="expected_sha256"):
        parse_source_lock(config)

    config = _source_lock([_file_config(b"[]", kind="video")])
    with pytest.raises(ValueError, match="kind 必须是"):
        parse_source_lock(config)


def _write_report_and_approval(tmp_path, lock_data, payload, *, license_status="approved"):
    lock_data["sources"][0]["metadata_license_status"] = license_status
    lock_path = tmp_path / "lock.json"
    report_path = tmp_path / "preview.json"
    approval_path = tmp_path / "approval.json"
    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    with _client_for(payload) as client:
        report = preview_pinned_sources(lock_path, client)
    report_raw = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    report_path.write_bytes(report_raw)
    approval_path.write_text(json.dumps({
        "schema_version": 1,
        "approved": True,
        "reviewer": "test reviewer",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "preview_report_sha256": hashlib.sha256(report_raw).hexdigest(),
    }), encoding="utf-8")
    return lock_path, report_path, approval_path


def test_review_gate_rechecks_manifest_and_remote_bytes_before_import(tmp_path):
    payload = b'[{"name":"Oats","source":"usda-approx"}]'
    lock_data = _source_lock([_file_config(payload)])
    lock_path, report_path, approval_path = _write_report_and_approval(
        tmp_path, lock_data, payload
    )
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        result = validate_reviewed_manifest(lock_path, report_path, approval_path, client)

    assert result["approved"] is True
    assert result["database_accessed"] is False
    assert result["database_written"] is False
    assert result["media_urls_requested"] == 0
    assert result["files"][0]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert len(requested) == 1
    assert requested[0].endswith(f"/{COMMIT}/data/records.json")


def test_review_gate_rejects_unapproved_license_before_network_or_database(tmp_path):
    payload = b"[]"
    lock_data = _source_lock([_file_config(payload)])
    lock_path, report_path, approval_path = _write_report_and_approval(
        tmp_path, lock_data, payload, license_status="pending_review"
    )
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=payload, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="禁止进入正式导入"):
            validate_reviewed_manifest(lock_path, report_path, approval_path, client)

    assert requested == []


def test_review_gate_rejects_changed_report_lock_or_remote_content(tmp_path):
    payload = b"[]"
    lock_data = _source_lock([_file_config(payload)])
    lock_path, report_path, approval_path = _write_report_and_approval(
        tmp_path, lock_data, payload
    )
    original_report = report_path.read_bytes()
    report_path.write_bytes(original_report + b" ")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload, request=request))) as client:
        with pytest.raises(ValueError, match="未绑定当前预览报告"):
            validate_reviewed_manifest(lock_path, report_path, approval_path, client)

    report_path.write_bytes(original_report)
    lock_path.write_text(json.dumps({**lock_data, "locked_on": "2026-10-28"}), encoding="utf-8")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=payload, request=request))) as client:
        with pytest.raises(ValueError, match="来源锁定清单与已审阅预览不同"):
            validate_reviewed_manifest(lock_path, report_path, approval_path, client)

    lock_path.write_text(json.dumps(lock_data), encoding="utf-8")
    changed_payload = b'[{"name":"changed"}]'
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=changed_payload, request=request))) as client:
        with pytest.raises(RuntimeError, match="SHA-256 不匹配"):
            validate_reviewed_manifest(lock_path, report_path, approval_path, client)
