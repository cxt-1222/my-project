from utils.text_chunking import split_knowledge_text
from scripts.import_fitness_knowledge import _milvus_fields
from utils.fitness_knowledge import (
    build_exercise_documents,
    build_fitkg_documents,
    fitkg_record_to_fact,
)


def test_fitkg_entity_end_offset_is_inclusive():
    record = {
        "tokens": ["深", "蹲", "能", "锻", "炼", "股", "四", "头", "肌", "。"],
        "entities": [
            {"type": "健身动作", "start": 0, "end": 1},
            {"type": "身体部位", "start": 5, "end": 8},
        ],
        "relations": [{"type": "锻炼", "head": 0, "tail": 1}],
    }

    fact, issues = fitkg_record_to_fact(record)

    assert fact is not None
    assert fact["entities"] == [
        {"label": "健身动作", "name": "深蹲"},
        {"label": "身体部位", "name": "股四头肌"},
    ]
    assert fact["relationships"][0]["sourceName"] == "深蹲"
    assert fact["relationships"][0]["targetName"] == "股四头肌"
    assert issues == {"invalid_record": 0, "invalid_span": 0, "invalid_relation": 0}


def test_fitkg_invalid_spans_and_relation_indices_are_counted_and_skipped():
    record = {
        "tokens": ["胸", "推"],
        "entities": [
            {"type": "健身动作", "start": 0, "end": 4},
            {"type": "身体部位", "start": 1, "end": 1},
        ],
        "relations": [
            {"type": "锻炼", "head": 0, "tail": 1},
            {"type": "无效关系", "head": 3, "tail": 1},
        ],
    }

    fact, issues = fitkg_record_to_fact(record)

    assert fact is not None
    assert fact["entities"] == [{"label": "身体部位", "name": "推"}]
    assert fact["relationships"] == []
    assert issues["invalid_span"] == 1
    assert issues["invalid_relation"] == 2


def test_fitkg_builder_deduplicates_records_and_groups_documents():
    record = {
        "tokens": ["深", "蹲", "锻", "炼", "臀", "肌"],
        "entities": [
            {"type": "健身动作", "start": 0, "end": 1},
            {"type": "目标肌群", "start": 4, "end": 5},
        ],
        "relations": [{"type": "锻炼", "head": 0, "tail": 1}],
    }

    docs, stats = build_fitkg_documents(
        [record, record, {"tokens": ["bad"], "entities": [], "relations": []}],
        source_digest="abc123",
        group_size=1,
    )

    assert len(docs) == 1
    assert stats.total_records == 3
    assert stats.accepted_records == 1
    assert stats.duplicate_records == 1
    assert stats.invalid_records == 1
    assert len(docs[0].entities) == 2
    assert len(docs[0].relationships) == 1
    assert "原文：深蹲锻炼臀肌" in docs[0].content


def test_exercise_converter_prefers_chinese_instructions_and_omits_media():
    exercise = {
        "id": "squat-1",
        "name": "Barbell Squat",
        "category": "Upper Legs",
        "body_parts": ["Upper Legs"],
        "equipment": "Barbell",
        "primary_muscle": "Quadriceps",
        "secondary_muscles": ["Glutes"],
        "instruction_steps": {
            "zh": ["双脚与肩同宽站立", "屈髋屈膝下蹲后站起"],
            "en": ["Stand with feet shoulder-width apart", "Squat and stand up"],
        },
        "image": "https://example.test/squat.gif",
        "gif": "https://example.test/squat.gif",
    }

    docs, stats = build_exercise_documents([exercise], source_digest="exercise-hash")

    assert stats.accepted_records == 1
    assert len(docs) == 1
    assert "双脚与肩同宽站立" in docs[0].content
    assert "Stand with feet shoulder-width apart" not in docs[0].content
    assert "股四头肌（Quadriceps）" in docs[0].content
    assert "example.test" not in docs[0].content
    assert any(entity["label"] == "健身动作" for entity in docs[0].entities)
    assert any(rel["relName"] == "锻炼" for rel in docs[0].relationships)


def test_exercise_converter_handles_missing_optional_fields_and_duplicate_records():
    exercise = {"name": "Push-up"}
    docs, stats = build_exercise_documents(
        [exercise, exercise, {"equipment": "Dumbbell"}],
        source_digest="exercise-hash",
        group_size=1,
    )

    assert len(docs) == 1
    assert stats.accepted_records == 1
    assert stats.duplicate_records == 1
    assert stats.invalid_records == 1
    assert "动作名称：Push-up" in docs[0].content

def test_milvus_field_normalizer_accepts_current_sdk_and_legacy_shapes():
    fields = _milvus_fields({
        "fields": [
            {"name": "content_id", "type": "VarChar"},
            {"fieldName": "vector", "typeParams": [{"key": "dim", "value": "1024"}]},
        ]
    })

    assert "content_id" in fields
    assert fields["vector"]["params"]["dim"] == "1024"

    nested = _milvus_fields({
        "schema": {"fields": [{"field_name": "vector", "params": {"dim": 768}}]}
    })
    assert nested["vector"]["params"]["dim"] == 768


def test_action_chunking_repeats_name_and_target_muscle_in_every_chunk():
    content = "\n".join([
        "动作名称：dumbbell lateral raise",
        "动作分类：shoulders",
        "主要目标肌群：delts",
        "动作说明：",
        *[f"{i}. 将哑铃缓慢举起并控制动作节奏，保持躯干稳定。" for i in range(1, 15)],
        "动作名称：dumbbell kickback",
        "动作分类：upper arms",
        "主要目标肌群：triceps",
        "动作说明：",
        "1. 将手臂向后伸直。",
    ])

    chunks = split_knowledge_text(content, chunk_size=180, chunk_overlap=30)

    lateral_chunks = [chunk for chunk in chunks if "dumbbell lateral raise" in chunk]
    kickback_chunks = [chunk for chunk in chunks if "dumbbell kickback" in chunk]
    assert len(lateral_chunks) > 1
    assert all("主要目标肌群：delts" in chunk for chunk in lateral_chunks)
    assert len(kickback_chunks) == 1
    assert all("dumbbell kickback" not in chunk for chunk in lateral_chunks)
