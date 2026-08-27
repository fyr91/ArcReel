"""Alembic coverage for immutable episode-scoped Agent sessions."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

pytestmark = pytest.mark.unit

REVISION = "c7f49b8e2d10"
DOWN_REVISION = "78d31ac4f962"


@pytest.fixture
def alembic_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    repo_root = Path(__file__).resolve().parent.parent
    db_path = tmp_path / "episode-scoped-sessions.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    cfg = Config()
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    cfg.attributes["_test_db_path"] = str(db_path)
    return cfg


def _engine(cfg: Config) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{cfg.attributes['_test_db_path']}")


def test_upgrade_preserves_legacy_sessions_as_project_scope_and_downgrades(alembic_cfg: Config) -> None:
    command.upgrade(alembic_cfg, DOWN_REVISION)
    engine = _engine(alembic_cfg)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO agent_sessions "
                    "(id, sdk_session_id, project_name, created_at, updated_at) VALUES "
                    "('legacy-row', 'legacy-sdk', 'demo', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, REVISION)
    engine = _engine(alembic_cfg)
    try:
        inspector = sa.inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("agent_sessions")}
        indexes = {index["name"] for index in inspector.get_indexes("agent_sessions")}
        assert "episode" in columns
        assert "idx_agent_sessions_project_episode" in indexes
        with engine.connect() as conn:
            assert (
                conn.execute(
                    sa.text("SELECT episode FROM agent_sessions WHERE sdk_session_id='legacy-sdk'")
                ).scalar_one()
                is None
            )
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, DOWN_REVISION)
    engine = _engine(alembic_cfg)
    try:
        columns = {column["name"] for column in sa.inspect(engine).get_columns("agent_sessions")}
        assert "episode" not in columns
    finally:
        engine.dispose()
