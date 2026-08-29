"""Alembic coverage for legacy global-asset resource-group backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

REVISION = "8b7d9e1f2a30"
DOWN_REVISION = "69e2f4c8a1bd"


def test_upgrade_backfills_primary_image_and_audio_without_duplication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "resource-groups.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg = Config()
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, DOWN_REVISION)

    engine = sa.create_engine(f"sqlite:///{db_path}")
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO assets (
                    id, type, name, description, voice_style, image_path, audio_path,
                    source_project, created_at, updated_at
                ) VALUES (
                    :id, 'character', '旧人物', '', '', :image_path, :audio_path,
                    NULL, :created_at, :updated_at
                )
                """
            ),
            {
                "id": "legacy-character",
                "image_path": "_global_assets/character/legacy.png",
                "audio_path": "_global_assets/character/legacy.wav",
                "created_at": now,
                "updated_at": now,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO asset_resources (
                    id, asset_id, resource_key, origin, media_type, mime_type, path,
                    source_url, sha256, byte_size, revision, sort_order,
                    source_fields_json, created_at, updated_at
                ) VALUES (
                    'existing-image', 'legacy-character', 'existing:image', 'local',
                    'image', 'image/png', '_global_assets/character/legacy.png',
                    NULL, NULL, NULL, NULL, 0, '[]', :created_at, :updated_at
                )
                """
            ),
            {"created_at": now, "updated_at": now},
        )

    command.upgrade(cfg, REVISION)
    with engine.begin() as connection:
        rows = connection.execute(
            sa.text(
                """
                SELECT resource_key, origin, media_type, path, sort_order
                FROM asset_resources WHERE asset_id = 'legacy-character'
                ORDER BY sort_order
                """
            )
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["resource_key"] == "existing:image"
    assert rows[1]["origin"] == "local"
    assert rows[1]["media_type"] == "audio"
    assert rows[1]["path"].endswith("legacy.wav")
    assert rows[1]["sort_order"] == 1

    command.downgrade(cfg, DOWN_REVISION)
    with engine.begin() as connection:
        remaining = connection.execute(
            sa.text("SELECT resource_key FROM asset_resources WHERE asset_id = 'legacy-character'")
        ).scalars().all()
    engine.dispose()
    assert remaining == ["existing:image"]
