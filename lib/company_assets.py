"""Synchronize the central company asset catalog into ArcReel's local library.

The public seam is :class:`CompanyAssetCatalog`: HTTP/Supabase details stay in
an adapter while local database and file behavior is exercised through
``sync_company_assets`` by Web, background jobs, Agent tools, and tests alike.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from lib.asset_types import GLOBAL_LIBRARY_ASSET_TYPES, validate_asset_name
from lib.db.models.asset import AssetResource
from lib.db.repositories.asset_alias_repo import AssetAliasRepository
from lib.db.repositories.asset_repo import AssetRepository
from lib.db.repositories.asset_resource_repo import AssetResourceRepository
from lib.db.repositories.company_asset_checkpoint_repo import CompanyAssetCheckpointRepository
from lib.project_manager import ProjectManager

COMPANY_ASSET_SOURCE = "company_asset_catalog"
AssetType = Literal["character", "scene", "prop"]
CatalogOrigin = Literal["official", "user_shared"]
CatalogStatus = Literal["published", "archived"]


class CompanyAssetSyncError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CompanyAssetFile:
    id: str
    key: str
    role: str
    media_type: Literal["image", "audio"]
    mime_type: str | None
    bucket_id: str
    object_path: str
    byte_size: int | None
    sha256: str | None
    revision: str | None
    sort_order: int
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyAsset:
    id: str
    asset_type: str
    origin: CatalogOrigin
    status: CatalogStatus
    version: int
    name: str
    description: str
    voice_style: str
    voice_id: str | None
    owner_id: str | None
    owner_name: str | None
    aliases: tuple[str, ...]
    files: tuple[CompanyAssetFile, ...]


@dataclass(frozen=True)
class CompanyAssetChange:
    revision: int
    operation: Literal["upsert", "archive"]
    asset: CompanyAsset


@dataclass(frozen=True)
class CompanyAssetPage:
    changes: tuple[CompanyAssetChange, ...]
    next_cursor: int
    has_more: bool


@dataclass(frozen=True)
class CompanyAssetSnapshotPage:
    assets: tuple[CompanyAsset, ...]
    snapshot_cursor: int
    next_page_token: str | None
    has_more: bool


@dataclass(frozen=True)
class CompanyAssetPublicationFile:
    key: str
    role: str
    media_type: Literal["image", "audio"]
    mime_type: str | None
    path: Path
    byte_size: int
    sha256: str
    revision: str | None
    sort_order: int
    source_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyAssetPublication:
    asset_id: str
    version_id: str
    client_asset_id: str
    asset_type: AssetType
    name: str
    description: str
    voice_style: str
    voice_id: str | None
    aliases: tuple[str, ...]
    files: tuple[CompanyAssetPublicationFile, ...]


@dataclass(frozen=True)
class CompanyAssetPublishResult:
    asset_id: str
    version_id: str
    version: int


@dataclass(frozen=True)
class CompanyAssetAdminItem:
    """One central Supabase catalog row shown in the administrator monitor."""

    id: str
    asset_type: str
    origin: CatalogOrigin
    status: CatalogStatus
    version: int
    name: str
    description: str
    owner_name: str | None
    source_name: str | None
    files: tuple[CompanyAssetFile, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CompanyAssetAdminPage:
    items: tuple[CompanyAssetAdminItem, ...]
    total: int
    totals: dict[str, int]


@dataclass(frozen=True)
class CompanyAssetDeleteResult:
    asset_id: str
    name: str
    asset_type: str
    origin: CatalogOrigin
    queued_file_count: int


@dataclass(frozen=True)
class CompanyAssetAdminPreview:
    content: bytes
    mime_type: str


class CompanyAssetCatalog(Protocol):
    async def pull_snapshot(
        self,
        *,
        user_id: str,
        asset_types: tuple[str, ...],
        after_id: str | None,
        snapshot_cursor: int | None,
        limit: int = 100,
    ) -> CompanyAssetSnapshotPage: ...

    async def pull_changes(
        self,
        *,
        user_id: str,
        asset_types: tuple[str, ...],
        after: int,
        limit: int = 100,
    ) -> CompanyAssetPage: ...

    async def download_file(self, *, user_id: str, file: CompanyAssetFile) -> bytes: ...


class CompanyAssetPublisher(Protocol):
    async def publish_asset(
        self,
        *,
        user_id: str,
        publication: CompanyAssetPublication,
    ) -> CompanyAssetPublishResult: ...


class CompanyAssetAdministrator(Protocol):
    async def list_assets(
        self,
        *,
        user_id: str,
        asset_type: str | None,
        origin: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> CompanyAssetAdminPage: ...

    async def delete_asset(self, *, user_id: str, asset_id: str) -> CompanyAssetDeleteResult: ...

    async def download_asset_preview(self, *, user_id: str, asset_id: str) -> CompanyAssetAdminPreview: ...


async def list_company_catalog_assets(
    *,
    administrator: CompanyAssetAdministrator,
    user_id: str,
    asset_type: str | None,
    origin: str | None,
    query: str | None,
    limit: int,
    offset: int,
) -> CompanyAssetAdminPage:
    """List the actual central catalog through the shared Web/Agent operation."""

    if asset_type is not None and asset_type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise CompanyAssetSyncError("company_asset_invalid_type")
    if origin is not None and origin not in {"official", "user_shared"}:
        raise CompanyAssetSyncError("company_asset_invalid_origin")
    if not 1 <= limit <= 100 or offset < 0:
        raise CompanyAssetSyncError("company_asset_invalid_query")
    normalized_query = query.strip() if query else None
    if normalized_query and len(normalized_query) > 200:
        raise CompanyAssetSyncError("company_asset_invalid_query")
    return await administrator.list_assets(
        user_id=user_id,
        asset_type=asset_type,
        origin=origin,
        query=normalized_query or None,
        limit=limit,
        offset=offset,
    )


async def delete_company_catalog_asset(
    *,
    administrator: CompanyAssetAdministrator,
    user_id: str,
    asset_id: str,
) -> CompanyAssetDeleteResult:
    """Hard-delete one central asset; local ArcReel copies remain independent."""

    try:
        normalized_id = str(uuid.UUID(asset_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CompanyAssetSyncError("company_asset_invalid_identity") from exc
    return await administrator.delete_asset(user_id=user_id, asset_id=normalized_id)


async def download_company_catalog_asset_preview(
    *,
    administrator: CompanyAssetAdministrator,
    user_id: str,
    asset_id: str,
) -> CompanyAssetAdminPreview:
    try:
        normalized_id = str(uuid.UUID(asset_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CompanyAssetSyncError("company_asset_invalid_identity") from exc
    return await administrator.download_asset_preview(user_id=user_id, asset_id=normalized_id)


async def publish_local_asset(
    session: AsyncSession,
    *,
    publisher: CompanyAssetPublisher,
    manager: ProjectManager,
    user_id: str,
    asset_id: str,
) -> CompanyAssetPublishResult:
    """Publish one local-library asset through the central catalog boundary."""

    repository = AssetRepository(session)
    asset = await repository.get_by_id(asset_id)
    if asset is None:
        raise CompanyAssetSyncError("company_asset_local_not_found")
    if asset.type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise CompanyAssetSyncError("company_asset_invalid_type")
    if asset.external_source == COMPANY_ASSET_SOURCE and asset.external_origin == "official":
        raise CompanyAssetSyncError("company_asset_official_read_only")

    central_asset_id = asset.external_id if asset.external_source == COMPANY_ASSET_SOURCE else None
    try:
        central_asset_id = str(uuid.UUID(central_asset_id or asset.id))
        client_asset_id = str(uuid.UUID(asset.id))
    except ValueError as exc:
        raise CompanyAssetSyncError("company_asset_invalid_identity") from exc

    files = await asyncio.to_thread(_publication_files, manager, asset)
    publication = CompanyAssetPublication(
        asset_id=central_asset_id,
        version_id=str(uuid.uuid4()),
        client_asset_id=client_asset_id,
        asset_type=asset.type,
        name=asset.name,
        description=asset.description,
        voice_style=asset.voice_style if asset.type == "character" else "",
        voice_id=asset.voice_id if asset.type == "character" else None,
        aliases=tuple(alias.alias for alias in asset.aliases),
        files=files,
    )
    result = await publisher.publish_asset(user_id=user_id, publication=publication)
    await repository.update(
        asset.id,
        external_source=COMPANY_ASSET_SOURCE,
        external_id=result.asset_id,
        external_origin="user_shared",
        external_version=result.version,
        external_status="published",
    )
    await session.commit()
    return result


def _publication_files(manager: ProjectManager, asset) -> tuple[CompanyAssetPublicationFile, ...]:
    entries: list[tuple[str, str, str, str | None, str, str | None, int, tuple[str, ...]]] = []
    seen_paths: set[str] = set()
    for resource in asset.resources:
        role = "attachment"
        if resource.path == asset.image_path:
            role = "primary_image"
        elif resource.path == asset.audio_path:
            role = "reference_audio"
        try:
            raw_source_fields = json.loads(resource.source_fields_json or "[]")
        except (TypeError, ValueError):
            raw_source_fields = []
        source_fields = tuple(str(field) for field in raw_source_fields) if isinstance(raw_source_fields, list) else ()
        entries.append(
            (
                resource.resource_key,
                role,
                resource.media_type,
                resource.mime_type,
                resource.path,
                resource.revision,
                resource.sort_order,
                source_fields,
            )
        )
        seen_paths.add(resource.path)
    if asset.image_path and asset.image_path not in seen_paths:
        entries.append(("primary_image", "primary_image", "image", None, asset.image_path, None, 0, ("sheet",)))
        seen_paths.add(asset.image_path)
    if asset.audio_path and asset.audio_path not in seen_paths:
        entries.append(
            ("reference_audio", "reference_audio", "audio", None, asset.audio_path, None, 1, ("reference_audio",))
        )

    files: list[CompanyAssetPublicationFile] = []
    root = manager.projects_root.resolve()
    for key, role, media_type, mime_type, relative_path, revision, sort_order, source_fields in entries:
        candidate = (manager.projects_root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise CompanyAssetSyncError("company_asset_file_invalid") from exc
        if not candidate.is_file():
            raise CompanyAssetSyncError("company_asset_file_missing", relative_path)
        size = candidate.stat().st_size
        if size > 200 * 1024 * 1024:
            raise CompanyAssetSyncError("company_asset_file_too_large", relative_path)
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        files.append(
            CompanyAssetPublicationFile(
                key=key,
                role=role,
                media_type=media_type,
                mime_type=mime_type or mimetypes.guess_type(candidate.name)[0],
                path=candidate,
                byte_size=size,
                sha256=digest,
                revision=revision,
                sort_order=sort_order,
                source_fields=source_fields,
            )
        )
    return tuple(files)


async def sync_company_assets(
    session: AsyncSession,
    *,
    catalog: CompanyAssetCatalog,
    manager: ProjectManager,
    user_id: str,
    asset_types: tuple[str, ...],
    progress_callback=None,
) -> dict[str, int]:
    """Reconcile selected catalog types, then catch up changes after the snapshot."""

    normalized_types = tuple(dict.fromkeys(asset_types))
    if not normalized_types or any(asset_type not in GLOBAL_LIBRARY_ASSET_TYPES for asset_type in normalized_types):
        raise CompanyAssetSyncError("company_asset_invalid_type")

    result = {"added": 0, "updated": 0, "archived": 0, "unchanged": 0, "assetsDownloaded": 0}
    processed = 0
    for asset_type in normalized_types:
        checkpoints = CompanyAssetCheckpointRepository(session)
        cursor = await checkpoints.get(COMPANY_ASSET_SOURCE, asset_type)
        pull_snapshot = getattr(catalog, "pull_snapshot", None)
        if pull_snapshot is not None:
            page_token: str | None = None
            snapshot_cursor: int | None = None
            while True:
                snapshot_page = await pull_snapshot(
                    user_id=user_id,
                    asset_types=(asset_type,),
                    after_id=page_token,
                    snapshot_cursor=snapshot_cursor,
                )
                if snapshot_cursor is None:
                    snapshot_cursor = snapshot_page.snapshot_cursor
                elif snapshot_page.snapshot_cursor != snapshot_cursor:
                    raise CompanyAssetSyncError("company_asset_invalid_payload", "snapshot cursor changed")
                for remote in snapshot_page.assets:
                    if remote.asset_type != asset_type:
                        raise CompanyAssetSyncError(
                            "company_asset_invalid_payload", "snapshot type does not match request"
                        )
                    change = CompanyAssetChange(
                        revision=snapshot_cursor,
                        operation="archive" if remote.status == "archived" else "upsert",
                        asset=remote,
                    )
                    outcome, downloads = await _apply_change(
                        session,
                        catalog=catalog,
                        manager=manager,
                        user_id=user_id,
                        change=change,
                    )
                    result[outcome] += 1
                    result["assetsDownloaded"] += downloads
                    processed += 1
                    if progress_callback is not None:
                        await progress_callback(
                            processed,
                            processed + (1 if snapshot_page.has_more else 0),
                            asset_type,
                        )
                if not snapshot_page.has_more:
                    break
                if not snapshot_page.next_page_token or snapshot_page.next_page_token == page_token:
                    raise CompanyAssetSyncError("company_asset_invalid_payload", "invalid snapshot page token")
                page_token = snapshot_page.next_page_token
            cursor = snapshot_cursor if snapshot_cursor is not None else cursor
            await checkpoints.advance(COMPANY_ASSET_SOURCE, asset_type, cursor)
            await session.commit()
        while True:
            page = await catalog.pull_changes(
                user_id=user_id,
                asset_types=(asset_type,),
                after=cursor,
            )
            for change in page.changes:
                if change.asset.asset_type != asset_type:
                    raise CompanyAssetSyncError("company_asset_invalid_payload", "change type does not match request")
                outcome, downloads = await _apply_change(
                    session,
                    catalog=catalog,
                    manager=manager,
                    user_id=user_id,
                    change=change,
                )
                result[outcome] += 1
                result["assetsDownloaded"] += downloads
                processed += 1
                if progress_callback is not None:
                    await progress_callback(processed, processed + (1 if page.has_more else 0), asset_type)
            cursor = max(cursor, page.next_cursor)
            await checkpoints.advance(COMPANY_ASSET_SOURCE, asset_type, cursor)
            await session.commit()
            if not page.has_more:
                break
    return result


async def _apply_change(
    session: AsyncSession,
    *,
    catalog: CompanyAssetCatalog,
    manager: ProjectManager,
    user_id: str,
    change: CompanyAssetChange,
) -> tuple[Literal["added", "updated", "archived", "unchanged"], int]:
    asset_repo = AssetRepository(session)
    alias_repo = AssetAliasRepository(session)
    resource_repo = AssetResourceRepository(session)
    remote = change.asset
    existing = await asset_repo.get_by_external_identity(COMPANY_ASSET_SOURCE, remote.id)

    if change.operation == "archive" or remote.status == "archived":
        if existing is None:
            return "unchanged", 0
        if existing.external_status == "archived":
            return "unchanged", 0
        await asset_repo.update(existing.id, external_status="archived")
        return "archived", 0

    is_new = existing is None
    changed = is_new
    if existing is None:
        existing = await asset_repo.create(
            type=remote.asset_type,
            name=await _available_name(asset_repo, remote.asset_type, remote.name),
            description=remote.description,
            voice_style=remote.voice_style if remote.asset_type == "character" else "",
            external_source=COMPANY_ASSET_SOURCE,
            external_id=remote.id,
            external_origin=remote.origin,
            external_version=remote.version,
            external_status="published",
            external_owner_id=remote.owner_id,
            external_owner_name=remote.owner_name,
            voice_id=remote.voice_id if remote.asset_type == "character" else None,
        )
    else:
        remote_name = await _available_name(
            asset_repo,
            remote.asset_type,
            remote.name,
            current_asset_id=existing.id,
        )
        patch = {
            "name": remote_name,
            "description": remote.description,
            "voice_style": remote.voice_style if remote.asset_type == "character" else "",
            "external_origin": remote.origin,
            "external_version": remote.version,
            "external_status": "published",
            "external_owner_id": remote.owner_id,
            "external_owner_name": remote.owner_name,
            "voice_id": remote.voice_id if remote.asset_type == "character" else None,
        }
        if any(getattr(existing, key) != value for key, value in patch.items()):
            await asset_repo.update(existing.id, **patch)
            changed = True

    aliases = (remote.name, *remote.aliases)
    if await alias_repo.sync_catalog_aliases(existing.id, aliases):
        changed = True

    previous_resources = [] if is_new else list(existing.resources)
    selected_image_id = next(
        (resource.id for resource in previous_resources if resource.path == existing.image_path),
        None,
    )
    selected_audio_id = next(
        (resource.id for resource in previous_resources if resource.path == existing.audio_path),
        None,
    )
    previous_by_key = {
        resource.resource_key: resource for resource in previous_resources if resource.origin == "catalog"
    }
    active_resources = [resource for resource in previous_resources if resource.origin != "catalog"]
    remote_by_resource_key: dict[str, CompanyAssetFile] = {}
    live_paths = {resource.path for resource in active_resources}
    obsolete_paths: set[str] = set()
    created_paths: set[str] = set()
    downloads = 0

    try:
        for remote_file in remote.files:
            if remote_file.media_type not in {"image", "audio"}:
                raise CompanyAssetSyncError("company_asset_invalid_payload", "unsupported media type")
            resource_key = _local_resource_key(remote_file.key)
            if resource_key in remote_by_resource_key:
                raise CompanyAssetSyncError("company_asset_invalid_payload", "duplicate resource key")
            remote_by_resource_key[resource_key] = remote_file
            current = previous_by_key.get(resource_key)
            source_fields_json = json.dumps(
                [remote_file.role, *remote_file.source_fields],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if current is not None and _resource_is_current(
                manager,
                current,
                remote_file,
                asset_type=remote.asset_type,
                local_asset_id=existing.id,
            ):
                metadata_patch = {
                    "media_type": remote_file.media_type,
                    "mime_type": remote_file.mime_type,
                    "byte_size": remote_file.byte_size,
                    "revision": remote_file.revision,
                    "sort_order": remote_file.sort_order,
                    "source_fields_json": source_fields_json,
                }
                if any(getattr(current, key) != value for key, value in metadata_patch.items()):
                    await resource_repo.update(current, **metadata_patch)
                    changed = True
                active_resources.append(current)
                live_paths.add(current.path)
                continue

            payload = await catalog.download_file(user_id=user_id, file=remote_file)
            digest = _verify_payload(payload, remote_file)
            target = _company_file_target(manager, remote.asset_type, existing.id, remote_file, digest)
            target_existed = target.exists()
            await asyncio.to_thread(_atomic_write, target, payload)
            relative_path = target.relative_to(manager.projects_root).as_posix()
            if not target_existed:
                created_paths.add(relative_path)
            live_paths.add(relative_path)
            fields = {
                "media_type": remote_file.media_type,
                "mime_type": remote_file.mime_type,
                "path": relative_path,
                "source_url": None,
                "sha256": digest,
                "byte_size": len(payload),
                "revision": remote_file.revision,
                "sort_order": remote_file.sort_order,
                "source_fields_json": source_fields_json,
            }
            if current is None:
                current = await resource_repo.create(
                    asset_id=existing.id,
                    resource_key=resource_key,
                    origin="catalog",
                    **fields,
                )
            else:
                if current.path != relative_path:
                    obsolete_paths.add(current.path)
                await resource_repo.update(current, **fields)
            active_resources.append(current)
            downloads += 1
            changed = True

        for key, resource in previous_by_key.items():
            if key not in remote_by_resource_key:
                obsolete_paths.add(resource.path)
                await resource_repo.delete(resource)
                changed = True

        selected_image = next(
            (
                resource
                for resource in active_resources
                if resource.id == selected_image_id and resource.media_type == "image"
            ),
            None,
        )
        selected_audio = next(
            (
                resource
                for resource in active_resources
                if resource.id == selected_audio_id and resource.media_type == "audio"
            ),
            None,
        )
        primary_image = selected_image or _primary_resource(active_resources, remote_by_resource_key, "image")
        primary_audio = selected_audio or _primary_resource(active_resources, remote_by_resource_key, "audio")
        primary_patch = {
            "image_path": primary_image.path if primary_image else None,
            "audio_path": primary_audio.path if primary_audio else None,
        }
        if any(getattr(existing, key) != value for key, value in primary_patch.items()):
            await asset_repo.update(existing.id, **primary_patch)
            changed = True

        await session.commit()
        for path in obsolete_paths - live_paths:
            _unlink_local_file(manager, path)
    except Exception:
        await session.rollback()
        for path in created_paths:
            _unlink_local_file(manager, path)
        raise

    if is_new:
        return "added", downloads
    return ("updated" if changed else "unchanged"), downloads


async def _available_name(
    repo: AssetRepository,
    asset_type: str,
    preferred: str,
    *,
    current_asset_id: str | None = None,
) -> str:
    try:
        base = validate_asset_name(preferred)
    except ValueError:
        base = f"Company asset {uuid.uuid4().hex[:8]}"
    occupant = await repo.get_by_type_name(asset_type, base)
    if occupant is None or occupant.id == current_asset_id:
        return base
    candidate = f"{base} (Company)"
    index = 2
    occupant = await repo.get_by_type_name(asset_type, candidate)
    while occupant is not None and occupant.id != current_asset_id:
        candidate = f"{base} (Company {index})"
        index += 1
        occupant = await repo.get_by_type_name(asset_type, candidate)
    return validate_asset_name(candidate)


def _local_resource_key(remote_key: str) -> str:
    return f"company:{hashlib.sha256(remote_key.encode('utf-8')).hexdigest()[:24]}"


def _resource_is_current(
    manager: ProjectManager,
    resource: AssetResource,
    remote: CompanyAssetFile,
    *,
    asset_type: str,
    local_asset_id: str,
) -> bool:
    if not resource.path.startswith(f"_global_assets/{asset_type}/company/{local_asset_id}/"):
        return False
    if remote.sha256 and resource.sha256 != remote.sha256.lower():
        return False
    if remote.revision is not None and resource.revision != remote.revision:
        return False
    try:
        info = (manager.projects_root / resource.path).stat()
    except OSError:
        return False
    return remote.byte_size is None or info.st_size == remote.byte_size


def _verify_payload(payload: bytes, remote: CompanyAssetFile) -> str:
    if remote.byte_size is not None and len(payload) != remote.byte_size:
        raise CompanyAssetSyncError("company_asset_file_size_mismatch")
    digest = hashlib.sha256(payload).hexdigest()
    if remote.sha256 is not None and digest != remote.sha256.lower():
        raise CompanyAssetSyncError("company_asset_file_hash_mismatch")
    return digest


def _company_file_target(
    manager: ProjectManager,
    asset_type: str,
    local_asset_id: str,
    remote: CompanyAssetFile,
    digest: str,
) -> Path:
    suffix = PurePosixPath(remote.object_path).suffix.lower()
    if not suffix or len(suffix) > 12 or any(char not in ".abcdefghijklmnopqrstuvwxyz0123456789" for char in suffix):
        suffix = ".bin"
    key_hash = hashlib.sha256(remote.key.encode("utf-8")).hexdigest()[:18]
    return (
        manager.get_global_assets_root() / asset_type / "company" / local_asset_id / f"{key_hash}-{digest[:16]}{suffix}"
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _unlink_local_file(manager: ProjectManager, relative_path: str) -> None:
    try:
        (manager.projects_root / relative_path).unlink()
    except FileNotFoundError:
        pass


def _primary_resource(
    resources: list[AssetResource],
    remote_by_key: dict[str, CompanyAssetFile],
    media_type: str,
) -> AssetResource | None:
    candidates = [resource for resource in resources if resource.media_type == media_type]
    if not candidates:
        return None

    def rank(resource: AssetResource) -> tuple[int, int]:
        remote = remote_by_key.get(resource.resource_key)
        if remote is None:
            return (3, resource.sort_order)
        preferred = remote.role in (
            {"primary_image", "sheet"} if media_type == "image" else {"primary_audio", "reference_audio"}
        )
        return (1 if preferred else 2, remote.sort_order)

    return min(candidates, key=rank)


__all__ = [
    "COMPANY_ASSET_SOURCE",
    "CompanyAsset",
    "CompanyAssetAdminItem",
    "CompanyAssetAdminPage",
    "CompanyAssetAdminPreview",
    "CompanyAssetAdministrator",
    "CompanyAssetCatalog",
    "CompanyAssetChange",
    "CompanyAssetDeleteResult",
    "CompanyAssetFile",
    "CompanyAssetPage",
    "CompanyAssetSnapshotPage",
    "CompanyAssetPublication",
    "CompanyAssetPublicationFile",
    "CompanyAssetPublishResult",
    "CompanyAssetPublisher",
    "CompanyAssetSyncError",
    "delete_company_catalog_asset",
    "download_company_catalog_asset_preview",
    "list_company_catalog_assets",
    "publish_local_asset",
    "sync_company_assets",
]
