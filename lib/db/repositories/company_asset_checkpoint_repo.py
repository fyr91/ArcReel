"""Persistence for central catalog delta cursors."""

from __future__ import annotations

from lib.db.models.company_asset_checkpoint import CompanyAssetCheckpoint
from lib.db.repositories.base import BaseRepository


class CompanyAssetCheckpointRepository(BaseRepository):
    async def get(self, source: str, asset_type: str) -> int:
        row = await self.session.get(CompanyAssetCheckpoint, (source, asset_type))
        return row.cursor if row is not None else 0

    async def advance(self, source: str, asset_type: str, cursor: int) -> int:
        row = await self.session.get(CompanyAssetCheckpoint, (source, asset_type))
        if row is None:
            row = CompanyAssetCheckpoint(source=source, asset_type=asset_type, cursor=max(0, cursor))
            self.session.add(row)
        else:
            row.cursor = max(row.cursor, cursor)
        await self.session.flush()
        return row.cursor
