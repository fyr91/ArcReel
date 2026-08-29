"""Alembic coverage for local company-asset sync state."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.unit

REVISION = "69e2f4c8a1bd"
DOWN_REVISION = "78d31ac4f962"


@pytest.fixture
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    repo_root = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "company-assets.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg = Config()
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.attributes["_test_db_path"] = str(db_path)
    return cfg


def _engine(cfg: Config) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{cfg.attributes['_test_db_path']}")


def test_upgrade_adds_catalog_metadata_checkpoints_and_owner_scoped_jobs(
    alembic_cfg: Config,
) -> None:
    command.upgrade(alembic_cfg, REVISION)
    engine = _engine(alembic_cfg)
    try:
        inspector = sa.inspect(engine)
        assert {
            "external_origin",
            "external_version",
            "external_status",
            "external_owner_id",
            "external_owner_name",
        } <= {column["name"] for column in inspector.get_columns("assets")}
        assert {
            "access_token_encrypted",
            "access_token_expires_at",
        } <= {column["name"] for column in inspector.get_columns("arcreel_cloud_sessions")}
        assert "company_asset_checkpoints" in inspector.get_table_names()
        assert {"owner_id", "payload_json"} <= {
            column["name"] for column in inspector.get_columns("background_jobs")
        }
        active_index = next(
            index
            for index in inspector.get_indexes("background_jobs")
            if index["name"] == "idx_background_jobs_one_active_per_type"
        )
        assert active_index["column_names"] == ["job_type", "owner_id"]
        assert active_index["unique"] == 1
    finally:
        engine.dispose()


def test_downgrade_removes_company_asset_state(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, REVISION)
    command.downgrade(alembic_cfg, DOWN_REVISION)
    engine = _engine(alembic_cfg)
    try:
        inspector = sa.inspect(engine)
        assert "company_asset_checkpoints" not in inspector.get_table_names()
        assert "external_origin" not in {
            column["name"] for column in inspector.get_columns("assets")
        }
        assert "access_token_encrypted" not in {
            column["name"] for column in inspector.get_columns("arcreel_cloud_sessions")
        }
        assert "owner_id" not in {
            column["name"] for column in inspector.get_columns("background_jobs")
        }
        active_index = next(
            index
            for index in inspector.get_indexes("background_jobs")
            if index["name"] == "idx_background_jobs_one_active_per_type"
        )
        assert active_index["column_names"] == ["job_type"]
    finally:
        engine.dispose()
