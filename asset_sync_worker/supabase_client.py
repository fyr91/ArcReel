"""Minimal service-role Supabase client for the monitor container."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class SupabaseWorkerClient:
    def __init__(self, *, base_url: str, service_role_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_role_key = service_role_key
        self._client = client or httpx.AsyncClient(timeout=120.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def claim_run(self, worker_id: str) -> dict[str, Any] | None:
        return await self._rpc("arcreel_claim_asset_sync_run", {"p_worker_id": worker_id})

    async def claim_asset_file_deletion(self, worker_id: str) -> dict[str, Any] | None:
        result = await self._rpc(
            "arcreel_claim_asset_file_deletion",
            {"p_worker_id": worker_id},
        )
        return result if isinstance(result, dict) else None

    async def report_asset_file_deletion(
        self,
        *,
        deletion_id: int,
        worker_id: str,
        succeeded: bool,
        error: str | None,
    ) -> None:
        await self._rpc(
            "arcreel_report_asset_file_deletion",
            {
                "p_deletion_id": deletion_id,
                "p_worker_id": worker_id,
                "p_succeeded": succeeded,
                "p_error": error,
            },
        )

    async def heartbeat(self, run_id: str, worker_id: str) -> str | None:
        value = await self._rpc(
            "arcreel_heartbeat_asset_sync_run",
            {"p_run_id": run_id, "p_worker_id": worker_id},
        )
        return str(value) if value is not None else None

    async def official_asset_state(self, source_key: str, source_asset_key: str) -> dict[str, Any] | None:
        return await self._rpc(
            "arcreel_official_asset_state",
            {"p_source_key": source_key, "p_source_asset_key": source_asset_key},
        )

    async def upload_official_file(self, object_path: str, payload: bytes, mime_type: str | None) -> None:
        await self._request(
            "POST",
            f"/storage/v1/object/arcreel-assets/{quote(object_path, safe='/')}",
            content=payload,
            headers={"Content-Type": mime_type or "application/octet-stream", "x-upsert": "false"},
        )

    async def delete_object(self, object_path: str) -> None:
        try:
            await self._request("DELETE", f"/storage/v1/object/arcreel-assets/{quote(object_path, safe='/')}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

    async def import_official_asset(self, **payload: Any) -> dict[str, Any]:
        result = await self._rpc(
            "arcreel_import_official_asset",
            {
                "p_source_key": payload["source_key"],
                "p_source_asset_key": payload["source_asset_key"],
                "p_asset_id": payload["asset_id"],
                "p_version_id": payload["version_id"],
                "p_source_fingerprint": payload["source_fingerprint"],
                "p_snapshot": payload["snapshot"],
            },
        )
        return result if isinstance(result, dict) else {}

    async def archive_missing(self, source_key: str, seen_source_keys: list[str]) -> int:
        result = await self._rpc(
            "arcreel_archive_missing_official_assets",
            {"p_source_key": source_key, "p_seen_source_keys": seen_source_keys},
        )
        return int(result or 0)

    async def report_run(self, **payload: Any) -> None:
        await self._rpc(
            "arcreel_report_asset_sync_run",
            {
                "p_run_id": payload["run_id"],
                "p_worker_id": payload["worker_id"],
                "p_status": payload["status"],
                "p_cursor": payload["cursor"],
                "p_imported_count": payload["imported_count"],
                "p_updated_count": payload["updated_count"],
                "p_unchanged_count": payload["unchanged_count"],
                "p_archived_count": payload["archived_count"],
                "p_seen_source_keys": payload["seen_source_keys"],
                "p_error_code": payload["error_code"],
                "p_error_detail": payload["error_detail"],
            },
        )

    async def _rpc(self, name: str, payload: dict[str, Any]) -> Any:
        response = await self._request("POST", f"/rest/v1/rpc/{name}", json=payload)
        if not response.content:
            return None
        return response.json()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = {
            "apikey": self._service_role_key,
            "Authorization": f"Bearer {self._service_role_key}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)
        response = await self._client.request(
            method,
            f"{self._base_url}{path}",
            headers=request_headers,
            json=json,
            content=content,
        )
        response.raise_for_status()
        return response


__all__ = ["SupabaseWorkerClient"]
