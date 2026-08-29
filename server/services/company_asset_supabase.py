"""Authenticated Supabase adapter for the company asset catalog."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from lib.company_assets import (
    CompanyAsset,
    CompanyAssetAdminItem,
    CompanyAssetAdminPage,
    CompanyAssetAdminPreview,
    CompanyAssetChange,
    CompanyAssetDeleteResult,
    CompanyAssetFile,
    CompanyAssetPage,
    CompanyAssetPublication,
    CompanyAssetPublishResult,
    CompanyAssetSnapshotPage,
    CompanyAssetSyncError,
)
from server.services.arcreel_cloud import (
    ArcReelCloudError,
    cloud_access_token,
    cloud_config,
    cloud_tls_verify,
    cloud_user_sub,
)

TokenProvider = Callable[[str], Awaitable[str]]
IdentityProvider = Callable[[str], Awaitable[str]]


class SupabaseCompanyAssetCatalog:
    def __init__(
        self,
        *,
        base_url: str,
        publishable_key: str,
        token_provider: TokenProvider = cloud_access_token,
        identity_provider: IdentityProvider = cloud_user_sub,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Company asset Supabase URL must be HTTPS")
        self._base_url = base_url.rstrip("/")
        self._publishable_key = publishable_key
        self._token_provider = token_provider
        self._identity_provider = identity_provider
        self._client = client

    async def pull_snapshot(
        self,
        *,
        user_id: str,
        asset_types: tuple[str, ...],
        after_id: str | None,
        snapshot_cursor: int | None,
        limit: int = 100,
    ) -> CompanyAssetSnapshotPage:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_pull_asset_snapshot",
            user_id=user_id,
            json={
                "p_asset_types": list(asset_types),
                "p_after_id": after_id,
                "p_snapshot_cursor": snapshot_cursor,
                "p_limit": limit,
            },
        )
        raw = self._json_object(response)
        raw_assets = raw.get("assets")
        if not isinstance(raw_assets, list):
            raise CompanyAssetSyncError("company_asset_invalid_payload", "assets must be a list")
        try:
            cursor = int(raw["snapshot_cursor"])
            next_page_token = raw.get("next_page_token")
            if cursor < 0 or (next_page_token is not None and not isinstance(next_page_token, str)):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid snapshot cursor") from exc
        has_more = raw.get("has_more") is True
        if has_more and not next_page_token:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "missing snapshot page token")
        return CompanyAssetSnapshotPage(
            assets=tuple(self._asset(item) for item in raw_assets),
            snapshot_cursor=cursor,
            next_page_token=next_page_token,
            has_more=has_more,
        )

    async def pull_changes(
        self,
        *,
        user_id: str,
        asset_types: tuple[str, ...],
        after: int,
        limit: int = 100,
    ) -> CompanyAssetPage:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_pull_asset_changes",
            user_id=user_id,
            json={"p_asset_types": list(asset_types), "p_after": max(0, after), "p_limit": limit},
        )
        raw = self._json_object(response)
        raw_changes = raw.get("changes")
        if not isinstance(raw_changes, list):
            raise CompanyAssetSyncError("company_asset_invalid_payload", "changes must be a list")
        changes = tuple(self._change(item) for item in raw_changes)
        try:
            next_cursor = max(after, int(raw.get("next_cursor", after)))
        except (TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid next cursor") from exc
        return CompanyAssetPage(changes=changes, next_cursor=next_cursor, has_more=raw.get("has_more") is True)

    async def download_file(self, *, user_id: str, file: CompanyAssetFile) -> bytes:
        response = await self._request(
            "GET",
            self._storage_url(file.bucket_id, file.object_path),
            user_id=user_id,
        )
        return response.content

    async def publish_asset(
        self,
        *,
        user_id: str,
        publication: CompanyAssetPublication,
    ) -> CompanyAssetPublishResult:
        try:
            cloud_sub = await self._identity_provider(user_id)
        except ArcReelCloudError as exc:
            raise CompanyAssetSyncError("company_asset_request_failed", exc.code) from exc
        if publication.owner_id is not None and publication.owner_id != cloud_sub:
            raise CompanyAssetSyncError("company_asset_not_owned")
        uploaded_paths: list[str] = []
        file_payloads: list[dict[str, Any]] = []
        try:
            for index, file in enumerate(publication.files):
                suffix = file.path.suffix.lower()
                safe_key = re.sub(r"[^a-zA-Z0-9._-]+", "-", file.key).strip(".-") or "asset"
                object_path = (
                    f"shared/{cloud_sub}/{publication.asset_id}/{publication.version_id}/{index:03d}-{safe_key}{suffix}"
                )
                data = await asyncio.to_thread(file.path.read_bytes)
                if len(data) != file.byte_size or hashlib.sha256(data).hexdigest() != file.sha256.lower():
                    raise CompanyAssetSyncError("company_asset_file_changed", str(file.path))
                await self._request(
                    "POST",
                    f"/storage/v1/object/arcreel-assets/{quote(object_path, safe='/')}",
                    user_id=user_id,
                    content=data,
                    extra_headers={
                        "Content-Type": file.mime_type or "application/octet-stream",
                        "x-upsert": "false",
                    },
                )
                uploaded_paths.append(object_path)
                file_payloads.append(
                    {
                        "key": file.key,
                        "role": file.role,
                        "media_type": file.media_type,
                        "mime_type": file.mime_type,
                        "bucket_id": "arcreel-assets",
                        "object_path": object_path,
                        "byte_size": file.byte_size,
                        "sha256": file.sha256,
                        "revision": file.revision,
                        "sort_order": file.sort_order,
                        "source_fields": list(file.source_fields),
                    }
                )

            response = await self._request(
                "POST",
                "/rest/v1/rpc/arcreel_publish_asset",
                user_id=user_id,
                json={
                    "p_asset_id": publication.asset_id,
                    "p_version_id": publication.version_id,
                    "p_client_asset_id": publication.client_asset_id,
                    "p_asset_type": publication.asset_type,
                    "p_name": publication.name,
                    "p_description": publication.description,
                    "p_voice_style": publication.voice_style,
                    "p_voice_id": publication.voice_id,
                    "p_aliases": list(publication.aliases),
                    "p_metadata": {},
                    "p_files": file_payloads,
                },
            )
            raw = self._json_object(response)
            return CompanyAssetPublishResult(
                asset_id=str(raw["asset_id"]),
                version_id=str(raw["version_id"]),
                version=int(raw["version"]),
                owner_id=cloud_sub,
            )
        except Exception:
            await self._delete_uploaded(user_id, uploaded_paths)
            raise

    async def source_sync_dashboard(self, *, user_id: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_asset_sync_dashboard",
            user_id=user_id,
            json={},
        )
        return self._json_object(response)

    async def list_assets(
        self,
        *,
        user_id: str,
        asset_type: str | None,
        origin: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> CompanyAssetAdminPage:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_admin_list_assets",
            user_id=user_id,
            json={
                "p_asset_type": asset_type,
                "p_origin": origin,
                "p_query": query,
                "p_limit": limit,
                "p_offset": offset,
            },
        )
        raw = self._json_object(response)
        items_raw = raw.get("items")
        totals_raw = raw.get("totals")
        if not isinstance(items_raw, list) or not isinstance(totals_raw, dict):
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid admin asset page")
        try:
            total = int(raw["total"])
            totals = {asset_type: int(totals_raw.get(asset_type, 0)) for asset_type in ("character", "scene", "prop")}
            if total < 0 or any(count < 0 for count in totals.values()):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid admin asset totals") from exc
        return CompanyAssetAdminPage(
            items=tuple(self._admin_item(item) for item in items_raw),
            total=total,
            totals=totals,
        )

    async def delete_asset(self, *, user_id: str, asset_id: str) -> CompanyAssetDeleteResult:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_admin_delete_asset",
            user_id=user_id,
            json={"p_asset_id": asset_id},
        )
        raw = self._json_object(response)
        try:
            origin = str(raw["origin"])
            asset_type = str(raw["asset_type"])
            queued_file_count = int(raw["queued_file_count"])
            if origin not in {"official", "user_shared"} or asset_type not in {"character", "scene", "prop"}:
                raise ValueError
            return CompanyAssetDeleteResult(
                asset_id=str(raw["asset_id"]),
                name=str(raw["name"]),
                asset_type=asset_type,
                origin=origin,
                queued_file_count=queued_file_count,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid asset deletion") from exc

    async def download_asset_preview(self, *, user_id: str, asset_id: str) -> CompanyAssetAdminPreview:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_admin_get_asset_preview",
            user_id=user_id,
            json={"p_asset_id": asset_id},
        )
        raw = self._json_object(response)
        try:
            bucket_id = str(raw["bucket_id"])
            object_path = str(raw["object_path"])
            mime_type = str(raw.get("mime_type") or "application/octet-stream")
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid asset preview") from exc
        file_response = await self._request(
            "GET",
            self._storage_url(bucket_id, object_path),
            user_id=user_id,
        )
        return CompanyAssetAdminPreview(content=file_response.content, mime_type=mime_type)

    async def request_source_sync(self, *, user_id: str, source_key: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_request_asset_sync_run",
            user_id=user_id,
            json={"p_source_key": source_key, "p_trigger_kind": "manual"},
        )
        return self._json_object(response)

    async def update_source_sync(
        self,
        *,
        user_id: str,
        source_key: str,
        action: str,
        interval_seconds: int | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_update_asset_sync_source",
            user_id=user_id,
            json={
                "p_source_key": source_key,
                "p_action": action,
                "p_interval_seconds": interval_seconds,
            },
        )
        return self._json_object(response)

    async def cancel_source_sync(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_cancel_asset_sync_run",
            user_id=user_id,
            json={"p_run_id": run_id},
        )
        return self._json_object(response)

    async def retry_source_sync(self, *, user_id: str, run_id: str) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/rest/v1/rpc/arcreel_retry_asset_sync_run",
            user_id=user_id,
            json={"p_run_id": run_id},
        )
        return self._json_object(response)

    def _storage_url(self, bucket_id: str, object_path: str) -> str:
        if bucket_id != "arcreel-assets":
            raise ValueError("Unsupported company asset bucket")
        if "\\" in object_path:
            raise ValueError("Unsafe company asset path")
        path = PurePosixPath(object_path)
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("Unsafe company asset path")
        return f"/storage/v1/object/authenticated/{quote(bucket_id, safe='')}/{quote(path.as_posix(), safe='/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: str,
        json: dict[str, Any] | None = None,
        content: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            access_token = await self._token_provider(user_id)
        except ArcReelCloudError as exc:
            raise CompanyAssetSyncError("company_asset_request_failed", exc.code) from exc
        headers = {
            "apikey": self._publishable_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        client = self._client
        owns_client = client is None
        if client is None:
            try:
                verify = cloud_tls_verify(self._base_url)
            except ArcReelCloudError as exc:
                raise CompanyAssetSyncError("company_asset_request_failed", exc.code) from exc
            client = httpx.AsyncClient(timeout=60.0, verify=verify)
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=json,
                content=content,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                try:
                    payload = exc.response.json()
                except ValueError:
                    payload = None
                if isinstance(payload, dict) and "ARCREEL_ASSET_NOT_OWNED" in str(payload.get("message") or ""):
                    raise CompanyAssetSyncError("company_asset_not_owned") from exc
            raise CompanyAssetSyncError(
                "company_asset_request_failed",
                f"HTTP {exc.response.status_code}",
            ) from exc
        except httpx.HTTPError as exc:
            raise CompanyAssetSyncError("company_asset_request_failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _delete_uploaded(self, user_id: str, object_paths: list[str]) -> None:
        for object_path in object_paths:
            try:
                await self._request(
                    "DELETE",
                    f"/storage/v1/object/arcreel-assets/{quote(object_path, safe='/')}",
                    user_id=user_id,
                )
            except Exception:  # noqa: BLE001
                # Files remain user-owned orphans and are not visible in the
                # catalog. A maintenance task can safely remove them later.
                pass

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "response is not JSON") from exc
        if not isinstance(value, dict):
            raise CompanyAssetSyncError("company_asset_invalid_payload", "response must be an object")
        return value

    @classmethod
    def _change(cls, raw: Any) -> CompanyAssetChange:
        try:
            if not isinstance(raw, dict) or not isinstance(raw.get("asset"), dict):
                raise ValueError
            asset = cls._asset(raw["asset"])
            operation = str(raw["operation"])
            if operation not in {"upsert", "archive"}:
                raise ValueError
            return CompanyAssetChange(revision=int(raw["revision"]), operation=operation, asset=asset)
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid change") from exc

    @classmethod
    def _asset(cls, raw: Any) -> CompanyAsset:
        try:
            if not isinstance(raw, dict):
                raise ValueError
            files_raw = raw.get("files") or []
            aliases_raw = raw.get("aliases") or []
            if not isinstance(files_raw, list) or not isinstance(aliases_raw, list):
                raise ValueError
            asset_type = str(raw["asset_type"])
            origin = str(raw["origin"])
            status = str(raw["status"])
            version = int(raw["version"])
            if (
                asset_type not in {"character", "scene", "prop"}
                or origin not in {"official", "user_shared"}
                or status not in {"published", "archived"}
                or version < 0
            ):
                raise ValueError
            return CompanyAsset(
                id=str(raw["id"]),
                asset_type=asset_type,
                origin=origin,
                status=status,
                version=version,
                name=str(raw["name"]),
                description=str(raw.get("description") or ""),
                voice_style=str(raw.get("voice_style") or ""),
                voice_id=str(raw["voice_id"]) if raw.get("voice_id") is not None else None,
                owner_id=str(raw["owner_id"]) if raw.get("owner_id") is not None else None,
                owner_name=str(raw["owner_name"]) if raw.get("owner_name") is not None else None,
                aliases=tuple(str(alias) for alias in aliases_raw),
                files=tuple(cls._file(item) for item in files_raw),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid asset") from exc

    @staticmethod
    def _file(raw: Any) -> CompanyAssetFile:
        try:
            if not isinstance(raw, dict):
                raise ValueError
            source_fields = raw.get("source_fields") or []
            if not isinstance(source_fields, list):
                raise ValueError
            media_type = str(raw["media_type"])
            if media_type not in {"image", "audio"}:
                raise ValueError
            return CompanyAssetFile(
                id=str(raw["id"]),
                key=str(raw["key"]),
                role=str(raw["role"]),
                media_type=media_type,
                mime_type=str(raw["mime_type"]) if raw.get("mime_type") is not None else None,
                bucket_id=str(raw["bucket_id"]),
                object_path=str(raw["object_path"]),
                byte_size=int(raw["byte_size"]) if raw.get("byte_size") is not None else None,
                sha256=str(raw["sha256"]) if raw.get("sha256") is not None else None,
                revision=str(raw["revision"]) if raw.get("revision") is not None else None,
                sort_order=int(raw.get("sort_order") or 0),
                source_fields=tuple(str(field) for field in source_fields),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid file") from exc

    @classmethod
    def _admin_item(cls, raw: Any) -> CompanyAssetAdminItem:
        try:
            if not isinstance(raw, dict):
                raise ValueError
            files_raw = raw.get("files") or []
            if not isinstance(files_raw, list):
                raise ValueError
            asset_type = str(raw["asset_type"])
            origin = str(raw["origin"])
            status = str(raw["status"])
            version = int(raw["version"])
            if (
                asset_type not in {"character", "scene", "prop"}
                or origin not in {"official", "user_shared"}
                or status not in {"published", "archived"}
                or version < 0
            ):
                raise ValueError
            return CompanyAssetAdminItem(
                id=str(raw["id"]),
                asset_type=asset_type,
                origin=origin,
                status=status,
                version=version,
                name=str(raw["name"]),
                description=str(raw.get("description") or ""),
                owner_name=str(raw["owner_name"]) if raw.get("owner_name") is not None else None,
                source_name=str(raw["source_name"]) if raw.get("source_name") is not None else None,
                files=tuple(cls._file(item) for item in files_raw),
                created_at=str(raw["created_at"]),
                updated_at=str(raw["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid admin asset") from exc


def get_company_asset_catalog() -> SupabaseCompanyAssetCatalog:
    try:
        config = cloud_config()
    except ArcReelCloudError as exc:
        raise CompanyAssetSyncError("company_asset_cloud_not_configured", exc.code) from exc
    if config is None:
        raise CompanyAssetSyncError("company_asset_cloud_not_configured")
    base_url, separator, _suffix = config.auth_url.partition("/functions/v1/")
    if not separator:
        raise CompanyAssetSyncError("company_asset_cloud_not_configured")
    return SupabaseCompanyAssetCatalog(base_url=base_url, publishable_key=config.publishable_key)


__all__ = ["SupabaseCompanyAssetCatalog", "get_company_asset_catalog"]
