"""Claim and execute monitored source-sync runs."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from pathlib import PurePosixPath
from typing import Any

from asset_sync_worker.models import SourceAsset


class RunCancelled(RuntimeError):
    pass


class AssetSyncWorker:
    def __init__(
        self,
        *,
        client: Any,
        worker_id: str,
        source_tokens: dict[str, str],
        adapters: dict[str, Any],
        poll_interval: float = 5.0,
    ) -> None:
        self._client = client
        self._worker_id = worker_id
        self._source_tokens = source_tokens
        self._adapters = adapters
        self._poll_interval = poll_interval

    async def run_once(self) -> bool:
        deletion = await self._client.claim_asset_file_deletion(self._worker_id)
        if deletion is not None:
            await self._delete_queued_file(deletion)
            return True
        claimed = await self._client.claim_run(self._worker_id)
        if claimed is None:
            return False
        run = claimed["run"]
        source = claimed["source"]
        run_id = str(run["id"])
        source_key = str(source["source_key"])
        counts = {"imported": 0, "updated": 0, "unchanged": 0, "archived": 0}
        cursor: dict[str, Any] = {}
        seen: list[str] = []
        status = "succeeded"
        error_code = None
        error_detail = None
        try:
            adapter_name = str(source["adapter"])
            adapter = self._adapters.get(adapter_name)
            if adapter is None:
                raise RuntimeError("asset_source_adapter_unavailable")
            token = self._source_tokens.get(source_key, "")
            if not token:
                raise RuntimeError("asset_source_token_missing")
            source_config = source.get("source_config")
            if not isinstance(source_config, dict) or not source_config.get("endpoint"):
                raise RuntimeError("asset_source_endpoint_missing")
            snapshot = await adapter.fetch(endpoint=str(source_config["endpoint"]), token=token)
            cursor = snapshot.cursor
            for asset in snapshot.assets:
                await self._ensure_running(run_id)
                seen.append(asset.source_key)
                outcome = await self._import_asset(source_key, asset, adapter)
                if outcome == "added":
                    counts["imported"] += 1
                elif outcome == "updated":
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1
            await self._ensure_running(run_id)
            counts["archived"] = await self._client.archive_missing(source_key, seen)
        except RunCancelled:
            status = "cancelled"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_code = str(exc) if str(exc).startswith("asset_") else "asset_source_sync_failed"
            error_detail = str(exc)[:1000]
        await self._client.report_run(
            run_id=run_id,
            worker_id=self._worker_id,
            status=status,
            cursor=cursor,
            imported_count=counts["imported"],
            updated_count=counts["updated"],
            unchanged_count=counts["unchanged"],
            archived_count=counts["archived"],
            seen_source_keys=seen,
            error_code=error_code,
            error_detail=error_detail,
        )
        return True

    async def _delete_queued_file(self, deletion: dict[str, Any]) -> None:
        deletion_id = int(deletion["id"])
        object_path = str(deletion["object_path"])
        succeeded = False
        error = None
        try:
            await self._client.delete_object(object_path)
            succeeded = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:1000]
        await self._client.report_asset_file_deletion(
            deletion_id=deletion_id,
            worker_id=self._worker_id,
            succeeded=succeeded,
            error=error,
        )

    async def run_forever(self) -> None:
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self._poll_interval)

    async def _ensure_running(self, run_id: str) -> None:
        status = await self._client.heartbeat(run_id, self._worker_id)
        if status == "cancelling":
            raise RunCancelled
        if status != "running":
            raise RuntimeError("asset_sync_run_lost")

    async def _import_asset(self, source_key: str, asset: SourceAsset, adapter: Any) -> str:
        state = await self._client.official_asset_state(source_key, asset.source_key)
        if (
            isinstance(state, dict)
            and state.get("source_fingerprint") == asset.fingerprint
            and state.get("status") == "published"
        ):
            return "unchanged"
        asset_id = (
            str(state["asset_id"])
            if isinstance(state, dict) and state.get("asset_id")
            else str(uuid.uuid5(uuid.NAMESPACE_URL, f"arcreel:{source_key}:{asset.source_key}"))
        )
        version_id = str(uuid.uuid4())
        uploaded: list[str] = []
        files: list[dict[str, Any]] = []
        try:
            for index, source_file in enumerate(asset.files):
                payload = await adapter.download(source_file)
                suffix = PurePosixPath(source_file.relative_path).suffix.lower()
                safe_key = re.sub(r"[^a-zA-Z0-9._-]+", "-", source_file.key).strip(".-") or "asset"
                object_path = f"official/{source_key}/{asset_id}/{version_id}/{index:03d}-{safe_key}{suffix}"
                await self._client.upload_official_file(object_path, payload, source_file.mime_type)
                uploaded.append(object_path)
                files.append(
                    {
                        "key": source_file.key,
                        "role": source_file.role,
                        "media_type": source_file.media_type,
                        "mime_type": source_file.mime_type,
                        "bucket_id": "arcreel-assets",
                        "object_path": object_path,
                        "byte_size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "revision": source_file.revision,
                        "sort_order": source_file.sort_order,
                        "source_fields": list(source_file.source_fields),
                    }
                )
            result = await self._client.import_official_asset(
                source_key=source_key,
                source_asset_key=asset.source_key,
                asset_id=asset_id,
                version_id=version_id,
                source_fingerprint=asset.fingerprint,
                snapshot={
                    "asset_type": asset.asset_type,
                    "name": asset.name,
                    "description": asset.description,
                    "voice_style": asset.voice_style,
                    "voice_id": asset.voice_id,
                    "aliases": list(asset.aliases),
                    "metadata": {},
                    "files": files,
                },
            )
            return str(result.get("outcome") or "updated")
        except Exception:
            for object_path in uploaded:
                try:
                    await self._client.delete_object(object_path)
                except Exception:  # noqa: BLE001
                    pass
            raise


__all__ = ["AssetSyncWorker", "RunCancelled"]
