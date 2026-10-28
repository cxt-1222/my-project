from pathlib import Path

from models import (
    DatasetImportModel,
    DatasetImportProgressModel,
    ExerciseCatalogModel,
    ExerciseMediaModel,
    FoodCatalogModel,
    KnowledgeSourceMappingModel,
    RecipeCatalogModel,
    RecipeIngredientModel,
)


def test_catalog_models_register_all_additive_tables():
    expected = {
        "kh_dataset_import",
        "kh_dataset_import_progress",
        "kh_exercise_catalog",
        "kh_exercise_media",
        "kh_food_catalog",
        "kh_recipe_catalog",
        "kh_recipe_ingredient",
        "kh_knowledge_source_mapping",
    }

    assert expected <= set(DatasetImportModel.metadata.tables)


def test_catalog_records_default_to_quarantine_and_pending_review():
    for model in (ExerciseCatalogModel, FoodCatalogModel, RecipeCatalogModel):
        assert model.__table__.c.license_status.server_default is not None
        assert model.__table__.c.record_status.server_default is not None

    media = ExerciseMediaModel.__table__
    assert str(media.c.license_status.server_default.arg) == "unverified"
    assert str(media.c.mapping_status.server_default.arg) == "unverified"
    assert str(media.c.allowed_use.server_default.arg) == "none"


def test_catalog_foreign_keys_preserve_existing_document_ownership_and_cleanup_scope():
    mapping_fks = {fk.target_fullname for fk in KnowledgeSourceMappingModel.__table__.foreign_keys}
    ingredient_fks = {fk.target_fullname for fk in RecipeIngredientModel.__table__.foreign_keys}

    assert "kh_document.id" in mapping_fks
    assert "kh_dataset_import.id" in mapping_fks
    assert "kh_recipe_catalog.id" in ingredient_fks
    assert "kh_food_catalog.id" in ingredient_fks


def test_catalog_migration_only_creates_new_tables_and_indexes():
    migration = Path("migrations/20261027_01_create_fitness_nutrition_catalog.sql").read_text(encoding="utf-8")
    progress_migration = Path("migrations/20261027_02_create_dataset_import_progress.sql").read_text(encoding="utf-8")
    upper = migration.upper()
    progress_upper = progress_migration.upper()

    assert "CREATE TABLE IF NOT EXISTS KH_DATASET_IMPORT" in upper
    assert "CREATE TABLE IF NOT EXISTS KH_KNOWLEDGE_SOURCE_MAPPING" in upper
    assert "DROP TABLE" not in upper
    assert "TRUNCATE" not in upper
    assert "CREATE TABLE IF NOT EXISTS KH_DATASET_IMPORT_PROGRESS" in progress_upper
    assert "DROP TABLE" not in progress_upper
    assert "TRUNCATE" not in progress_upper
    assert "DROP COLLECTION" not in upper


def test_import_progress_tracks_each_storage_and_has_idempotent_key():
    table = DatasetImportProgressModel.__table__
    assert {column.name for column in table.columns} >= {
        "import_id", "storage_name", "progress_status", "processed_records",
        "skipped_records", "failed_records", "checkpoint", "last_error",
    }
    assert any(
        constraint.name == "uq_kh_dataset_import_progress_storage"
        for constraint in table.constraints
    )
    storage_check = next(
        constraint for constraint in table.constraints
        if constraint.name == "ck_kh_dataset_import_progress_storage"
    )
    assert "postgres_catalog" in str(storage_check.sqltext)
