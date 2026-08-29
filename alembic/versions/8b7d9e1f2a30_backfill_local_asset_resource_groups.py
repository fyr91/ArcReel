"""backfill local asset resource groups

Revision ID: 8b7d9e1f2a30
Revises: 69e2f4c8a1bd
Create Date: 2026-08-30 01:40:00
"""

from __future__ import annotations

import mimetypes
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "8b7d9e1f2a30"
down_revision: str | Sequence[str] | None = "69e2f4c8a1bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESOURCE_KEY_PREFIX = "local:legacy-migration:"


def upgrade() -> None:
    """Represent pre-existing primary files in the resource-group table."""

    bind = op.get_bind()
    metadata = sa.MetaData()
    assets = sa.Table("assets", metadata, autoload_with=bind)
    resources = sa.Table("asset_resources", metadata, autoload_with=bind)

    existing_paths = set(bind.execute(sa.select(resources.c.asset_id, resources.c.path)).all())
    max_orders = dict(
        bind.execute(
            sa.select(resources.c.asset_id, sa.func.max(resources.c.sort_order)).group_by(resources.c.asset_id)
        ).all()
    )
    now = datetime.now(UTC)
    inserts: list[dict[str, object]] = []
    rows = bind.execute(
        sa.select(
            assets.c.id,
            assets.c.image_path,
            assets.c.audio_path,
            assets.c.external_source,
        )
    ).mappings()
    for asset in rows:
        current_max_order = max_orders.get(asset["id"])
        next_order = int(current_max_order) + 1 if current_max_order is not None else 0
        for media_type, path in (("image", asset["image_path"]), ("audio", asset["audio_path"])):
            if not path or (asset["id"], path) in existing_paths:
                continue
            resource_id = str(uuid.uuid4())
            inserts.append(
                {
                    "id": resource_id,
                    "asset_id": asset["id"],
                    "resource_key": f"{RESOURCE_KEY_PREFIX}{media_type}:{resource_id}",
                    "origin": "catalog" if asset["external_source"] else "local",
                    "media_type": media_type,
                    "mime_type": mimetypes.guess_type(path)[0],
                    "path": path,
                    "source_url": None,
                    "sha256": None,
                    "byte_size": None,
                    "revision": None,
                    "sort_order": next_order,
                    "source_fields_json": "[]",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            existing_paths.add((asset["id"], path))
            next_order += 1
    if inserts:
        bind.execute(resources.insert(), inserts)


def downgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    resources = sa.Table("asset_resources", metadata, autoload_with=bind)
    bind.execute(resources.delete().where(resources.c.resource_key.like(f"{RESOURCE_KEY_PREFIX}%")))
