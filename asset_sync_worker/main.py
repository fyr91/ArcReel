"""Container entry point for the company asset source monitor."""

from __future__ import annotations

import asyncio
import os
import socket

from asset_sync_worker.sources.character_catalog_v1 import CharacterCatalogV1Adapter
from asset_sync_worker.supabase_client import SupabaseWorkerClient
from asset_sync_worker.worker import AssetSyncWorker


async def main() -> None:
    base_url = os.environ["SUPABASE_URL"]
    service_role_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    source_token = os.environ.get("ASSET_SOURCE_EXISTING_CHARACTER_CATALOG_TOKEN", "").strip()
    client = SupabaseWorkerClient(base_url=base_url, service_role_key=service_role_key)
    worker = AssetSyncWorker(
        client=client,
        worker_id=os.environ.get("ASSET_SYNC_WORKER_ID", socket.gethostname()),
        source_tokens={"existing-character-catalog": source_token},
        adapters={"character_catalog_v1": CharacterCatalogV1Adapter()},
        poll_interval=float(os.environ.get("ASSET_SYNC_POLL_SECONDS", "5")),
    )
    try:
        await worker.run_forever()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
