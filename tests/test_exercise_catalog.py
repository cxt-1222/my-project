from utils.exercise_catalog import convert_exercise_records


def test_converter_preserves_source_and_quarantines_media():
    record = {
        "id": "raise-1",
        "name": "Dumbbell Lateral Raise",
        "bodyPart": "shoulders",
        "target": "delts",
        "equipment": "dumbbell",
        "steps": ["Stand tall", "Raise the dumbbells"],
        "videos": {"male": "https://media.example/raise.mp4"},
        "thumbnails": {"male": "https://media.example/raise.jpg"},
    }

    items, stats = convert_exercise_records([record])

    assert stats.input_records == 1
    assert stats.accepted_records == 1
    assert stats.invalid_records == 0
    assert len(items) == 1
    item = items[0]
    assert item.upstream_id == "raise-1"
    assert item.raw_record == record
    assert item.normalized_fields["body_part"] == "shoulders"
    assert item.normalized_fields["target_muscle"] == "delts"
    assert "Dumbbell Lateral Raise" in item.display_content
    assert {media["kind"] for media in item.media_refs} == {"video", "image"}
    assert all(media["allowed_use"] == "none" for media in item.media_refs)
    assert all(media["mapping_status"] == "pending_review" for media in item.media_refs)
    assert all(media["license_status"] in {"unverified", "pending_review"} for media in item.media_refs)


def test_converter_generates_stable_id_when_upstream_id_is_missing():
    record = {"name": "Push-up", "instructions": "Keep the body straight."}

    first, _ = convert_exercise_records([record])
    second, _ = convert_exercise_records([record.copy()])

    assert first[0].upstream_id.startswith("sha256:")
    assert first[0].upstream_id == second[0].upstream_id
    assert first[0].content_sha256 == second[0].content_sha256


def test_converter_retains_missing_optional_fields_without_inventing_values():
    items, stats = convert_exercise_records([{"id": "minimal", "name": "Minimal"}])

    assert stats.accepted_records == 1
    item = items[0]
    assert item.normalized_fields["body_part"] is None
    assert item.normalized_fields["target_muscle"] is None
    assert "bodyPart" in item.missing_fields
    assert "target" in item.missing_fields
    assert item.license_status == "pending_review"
    assert item.record_status == "quarantined"


def test_converter_deduplicates_same_source_id_and_rejects_conflicting_content():
    first = {"id": "same", "name": "Squat", "instructions": "A"}
    same = {"id": "same", "name": "Squat", "instructions": "A"}
    conflict = {"id": "same", "name": "Squat", "instructions": "B"}

    items, stats = convert_exercise_records([first, same, conflict])

    assert len(items) == 1
    assert stats.duplicate_records == 1
    assert stats.invalid_records == 1


def test_converter_activates_text_only_after_explicit_license_approval():
    items, _ = convert_exercise_records(
        [{
            "id": "squat-1",
            "name": "Squat",
            "videos": {"male": "https://media.example/squat.mp4"},
        }],
        license_status="approved",
    )

    assert items[0].record_status == "active"
    assert items[0].license_status == "approved"
    assert items[0].media_refs[0]["license_status"] == "unverified"
    assert items[0].media_refs[0]["allowed_use"] == "none"
