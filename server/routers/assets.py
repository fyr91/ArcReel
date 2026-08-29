"""assets 全局资产库路由。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from lib.api_errors import NotFoundError
from lib.artifact_activation import register_artifact_entries_atomically, resolve_current_artifact_target
from lib.artifact_manifest import ArtifactKey
from lib.asset_types import (
    BUCKET_KEY,
    GLOBAL_LIBRARY_ASSET_TYPES,
    SHEET_KEY,
    ProjectAssetNameConflictError,
    asset_name_comparison_key,
    ensure_project_asset_name_available,
    find_project_asset_name,
    localize_asset_type,
    resolve_asset_key,
    validate_asset_name,
)
from lib.db import async_session_factory
from lib.db.models.user import ArcReelCloudSession
from lib.db.repositories.asset_repo import AssetRepository
from lib.db.repositories.asset_resource_repo import AssetResourceRepository
from lib.i18n import Translator
from lib.project_manager import ProjectManager, get_project_manager
from server.auth import CurrentUser
from server.routers._asset_router_factory import localize_project_asset_name_conflict
from server.services.project_asset_links import (
    ProjectAssetLinkError,
    ProjectAssetLinkNotFound,
)
from server.services.project_asset_links import (
    configure_project_asset_link as configure_project_asset_link_service,
)
from server.services.project_asset_links import (
    link_project_asset as link_project_asset_service,
)
from server.services.project_asset_links import (
    unlink_project_asset as unlink_project_asset_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["全局资产库"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ASSET_RESOURCES = 20
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}


def _validate_asset_name(name: str, _t: Translator) -> str:
    """HTTP 边界包装：路径不安全的名字（分隔符 / 空字节 / ..）返回 400。"""
    try:
        return validate_asset_name(name)
    except ValueError:
        raise HTTPException(status_code=400, detail=_t("asset_invalid_name", name=name))


def _company_publish_state(asset, current_cloud_sub: str | None) -> str:
    if asset.external_source != "company_asset_catalog":
        return "publish"
    if asset.external_origin == "official":
        return "read_only_official"
    if asset.external_origin == "user_shared":
        # Older locally-published rows predate owner persistence. Keep their
        # update entry available; Supabase remains the final ownership guard.
        if asset.external_owner_id is None or asset.external_owner_id == current_cloud_sub:
            return "update"
    return "read_only_other"


def _serialize(asset, *, current_cloud_sub: str | None = None, include_publish_state: bool = False) -> dict:
    resources = [
        {
            "id": resource.id,
            "key": resource.resource_key,
            "origin": resource.origin,
            "media_type": resource.media_type,
            "mime_type": resource.mime_type,
            "path": resource.path,
            "byte_size": resource.byte_size,
            "is_primary": resource.path in {asset.image_path, asset.audio_path},
        }
        for resource in asset.resources
    ]
    payload = {
        "id": asset.id,
        "type": asset.type,
        "name": asset.name,
        "description": asset.description,
        "voice_style": asset.voice_style,
        "image_path": asset.image_path,
        "audio_path": asset.audio_path,
        "source_project": asset.source_project,
        "external_source": asset.external_source,
        "external_id": asset.external_id,
        "external_origin": asset.external_origin,
        "external_version": asset.external_version,
        "external_status": asset.external_status,
        "external_owner_id": asset.external_owner_id,
        "external_owner_name": asset.external_owner_name,
        "voice_id": asset.voice_id,
        "aliases": [alias.alias for alias in asset.aliases],
        "resources": resources,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
    if include_publish_state:
        payload["company_publish_state"] = _company_publish_state(asset, current_cloud_sub)
    return payload


async def _save_upload(file: UploadFile, asset_type: str, _t: Translator) -> str:
    path, _size = await _save_media_upload(file, asset_type, "image", _t)
    return path


async def _save_media_upload(
    file: UploadFile,
    asset_type: str,
    media_type: str,
    _t: Translator,
) -> tuple[str, int]:
    ext = Path(file.filename or "").suffix.lower()
    allowed_exts = ALLOWED_EXTS if media_type == "image" else ALLOWED_AUDIO_EXTS
    if ext not in allowed_exts:
        key = "asset_unsupported_format" if media_type == "image" else "asset_audio_unsupported_format"
        raise HTTPException(status_code=415, detail=_t(key))

    limit = MAX_UPLOAD_BYTES if media_type == "image" else MAX_AUDIO_UPLOAD_BYTES
    data = await file.read(limit + 1)
    if len(data) > limit:
        key = "asset_upload_too_large" if media_type == "image" else "asset_audio_upload_too_large"
        raise HTTPException(status_code=413, detail=_t(key))

    root = get_project_manager().get_global_assets_root() / asset_type
    uid = uuid.uuid4().hex
    target = root / f"{uid}{ext}"
    await asyncio.to_thread(target.write_bytes, data)
    # 存相对路径（相对 projects_root）
    return f"_global_assets/{asset_type}/{uid}{ext}", len(data)


def _nonempty_uploads(files: list[UploadFile] | None) -> list[UploadFile]:
    return [file for file in files or [] if file.filename]


def _validate_primary_index(index: int, files: list[UploadFile], _t: Translator) -> None:
    if files and not 0 <= index < len(files):
        raise HTTPException(status_code=422, detail=_t("asset_primary_resource_invalid"))


def _validate_resource_count(count: int, _t: Translator) -> None:
    if count > MAX_ASSET_RESOURCES:
        raise HTTPException(
            status_code=422,
            detail=_t("asset_resource_limit", limit=MAX_ASSET_RESOURCES),
        )


def _delete_global_asset_file(rel_path: str) -> None:
    path = get_project_manager().projects_root / rel_path
    try:
        path.unlink()
    except FileNotFoundError:
        # 文件已不存在（并发删除或 create 回滚）视为成功，忽略即可
        return
    except OSError:
        logger.warning("delete global asset file failed: %s", rel_path)


@router.get("")
async def list_assets(
    _t: Translator,
    user: CurrentUser,
    type: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    async with async_session_factory() as s:
        items = await AssetRepository(s).list(type=type, q=q, limit=limit, offset=offset)
        cloud_session = await s.get(ArcReelCloudSession, user.id)
        current_cloud_sub = cloud_session.cloud_user_sub if cloud_session is not None else None
        return {
            "items": [
                _serialize(a, current_cloud_sub=current_cloud_sub, include_publish_state=True)
                for a in items
            ]
        }


class ProjectAssetLinkRequest(BaseModel):
    project_name: str
    resource_type: str
    resource_id: str
    asset_id: str


@router.post("/project-links")
async def link_project_asset(req: ProjectAssetLinkRequest, _t: Translator):
    try:
        entry, asset = await link_project_asset_service(
            req.project_name,
            req.resource_type,
            req.resource_id,
            req.asset_id,
            manager=get_project_manager(),
            session_factory=async_session_factory,
        )
    except ProjectAssetLinkNotFound as exc:
        raise HTTPException(status_code=404, detail=_t("asset_not_found", name=str(exc))) from exc
    except ProjectAssetLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("asset_target_project_not_found", project=req.project_name) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("asset_not_found", name=req.resource_id)) from exc
    return {"success": True, "project_asset": entry, "asset": _serialize(asset)}


@router.delete("/project-links/{project_name}/{resource_type}/{resource_id}")
async def unlink_project_asset(project_name: str, resource_type: str, resource_id: str, _t: Translator):
    """Remove both the confirmed link and its stale extraction match."""

    try:
        entry = await unlink_project_asset_service(
            project_name, resource_type, resource_id, manager=get_project_manager()
        )
    except ProjectAssetLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("asset_target_project_not_found", project=project_name) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("asset_not_found", name=resource_id)) from exc
    return {"success": True, "project_asset": entry}


class ProjectAssetLinkConfigRequest(BaseModel):
    project_name: str
    resource_type: str
    resource_id: str
    image_usage: str | None = None
    voice_source: str | None = None


@router.patch("/project-links")
async def configure_project_asset_link(req: ProjectAssetLinkConfigRequest, _t: Translator):
    try:
        entry, asset = await configure_project_asset_link_service(
            req.project_name,
            req.resource_type,
            req.resource_id,
            image_usage=req.image_usage,
            voice_source=req.voice_source,
            manager=get_project_manager(),
            session_factory=async_session_factory,
        )
    except ProjectAssetLinkNotFound as exc:
        raise HTTPException(status_code=404, detail=_t("asset_not_found", name=str(exc))) from exc
    except ProjectAssetLinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("asset_target_project_not_found", project=req.project_name) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_t("asset_not_found", name=req.resource_id)) from exc
    return {"success": True, "project_asset": entry, "asset": _serialize(asset)}


@router.get("/{asset_id}")
async def get_asset(asset_id: str, _t: Translator):
    async with async_session_factory() as s:
        a = await AssetRepository(s).get_by_id(asset_id)
        if not a:
            raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))
        return {"asset": _serialize(a)}


@router.post("")
async def create_asset(
    _t: Translator,
    type: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    voice_style: str = Form(""),
    voice_id: str = Form(""),
    image: UploadFile | None = File(None),
    images: list[UploadFile] | None = File(None),
    audios: list[UploadFile] | None = File(None),
    primary_image_index: int = Form(0),
    primary_audio_index: int = Form(0),
):
    if type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise HTTPException(status_code=400, detail=_t("asset_invalid_type"))
    name = _validate_asset_name(name, _t)

    # ``image`` 是旧客户端的单图字段；``images`` / ``audios`` 是新资源组字段。
    image_files = ([image] if image is not None and image.filename else []) + _nonempty_uploads(images)
    audio_files = _nonempty_uploads(audios)
    if type != "character" and audio_files:
        raise HTTPException(status_code=422, detail=_t("asset_audio_character_only"))
    _validate_resource_count(len(image_files) + len(audio_files), _t)
    _validate_primary_index(primary_image_index, image_files, _t)
    _validate_primary_index(primary_audio_index, audio_files, _t)

    # 1) 先落盘再 create；所有失败路径都清理 orphan。
    saved: list[tuple[str, UploadFile, str, int]] = []
    try:
        for media_type, files in (("image", image_files), ("audio", audio_files)):
            for file in files:
                path, byte_size = await _save_media_upload(file, type, media_type, _t)
                saved.append((media_type, file, path, byte_size))
    except Exception:
        for _media_type, _file, path, _byte_size in saved:
            _delete_global_asset_file(path)
        raise

    image_paths = [path for media_type, _file, path, _size in saved if media_type == "image"]
    audio_paths = [path for media_type, _file, path, _size in saved if media_type == "audio"]
    image_path = image_paths[primary_image_index] if image_paths else None
    audio_path = audio_paths[primary_audio_index] if audio_paths else None

    # 2) 真正 create；任何失败路径都必须清理已落盘文件，保证 DB/磁盘一致
    try:
        async with async_session_factory() as s:
            repo = AssetRepository(s)
            try:
                a = await repo.create(
                    type=type,
                    name=name,
                    description=description,
                    voice_style=voice_style if type == "character" else "",
                    image_path=image_path,
                    audio_path=audio_path,
                    source_project=None,
                    voice_id=voice_id.strip() or None if type == "character" else None,
                )
                resource_repo = AssetResourceRepository(s)
                for sort_order, (media_type, file, path, byte_size) in enumerate(saved):
                    await resource_repo.create(
                        asset_id=a.id,
                        resource_key=f"local:{media_type}:{uuid.uuid4().hex}",
                        origin="local",
                        media_type=media_type,
                        mime_type=file.content_type,
                        path=path,
                        byte_size=byte_size,
                        sort_order=sort_order,
                    )
                await s.commit()
                a = await repo.get_by_id(a.id)
                assert a is not None
            except IntegrityError:
                await s.rollback()
                for _media_type, _file, path, _byte_size in saved:
                    _delete_global_asset_file(path)
                saved.clear()
                raise HTTPException(status_code=409, detail=_t("asset_already_exists", name=name))
    except HTTPException:
        raise
    except Exception:
        # 其它错误路径也不留 orphan
        for _media_type, _file, path, _byte_size in saved:
            _delete_global_asset_file(path)
        raise

    return {"asset": _serialize(a)}


class UpdateAssetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    voice_style: str | None = None
    voice_id: str | None = None


@router.patch("/{asset_id}")
async def update_asset(
    asset_id: str,
    req: UpdateAssetRequest,
    _t: Translator,
):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if "name" in patch:
        patch["name"] = _validate_asset_name(patch["name"], _t)
    async with async_session_factory() as s:
        repo = AssetRepository(s)
        a = await repo.get_by_id(asset_id)
        if not a:
            raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))
        if a.type != "character":
            patch.pop("voice_style", None)
            patch.pop("voice_id", None)
        elif "voice_id" in patch:
            patch["voice_id"] = patch["voice_id"].strip() or None
        if "name" in patch and patch["name"] != a.name:
            if await repo.exists(a.type, patch["name"]):
                raise HTTPException(status_code=409, detail=_t("asset_already_exists", name=patch["name"]))
        try:
            a = await repo.update(asset_id, **patch)
            await s.commit()
            await s.refresh(a)
        except IntegrityError:
            await s.rollback()
            raise HTTPException(status_code=409, detail=_t("asset_already_exists", name=patch.get("name", "")))
    return {"asset": _serialize(a)}


@router.delete("/{asset_id}", status_code=204)
async def delete_asset(asset_id: str, _t: Translator):
    async with async_session_factory() as s:
        repo = AssetRepository(s)
        a = await repo.get_by_id(asset_id)
        if a:
            file_paths = {resource.path for resource in a.resources}
            file_paths.update(path for path in (a.image_path, a.audio_path) if path)
            for path in file_paths:
                _delete_global_asset_file(path)
            await repo.delete(asset_id)
            await s.commit()
    return None


@router.post("/{asset_id}/image")
async def replace_image(
    asset_id: str,
    _t: Translator,
    image: UploadFile = File(...),
):
    # 1) 先取资产并校验存在
    async with async_session_factory() as s:
        repo = AssetRepository(s)
        a = await repo.get_by_id(asset_id)
        if not a:
            raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))
        old_path = a.image_path
        asset_type = a.type
        old_path_is_resource = any(resource.path == old_path for resource in a.resources)
        keeps_image_variants = a.type == "character" and a.external_source is not None

    # 2) 先保存新图（会触发 415/413 校验）—— 旧文件仍完好
    new_path = await _save_upload(image, asset_type, _t)

    # 3) 更新 DB；若写入失败则清理已落盘的新文件（旧文件保留）
    try:
        async with async_session_factory() as s:
            repo = AssetRepository(s)
            a = await repo.update(asset_id, image_path=new_path)
            if keeps_image_variants:
                await AssetResourceRepository(s).create(
                    asset_id=asset_id,
                    resource_key=f"local:{uuid.uuid4().hex}",
                    origin="local",
                    media_type="image",
                    mime_type=image.content_type,
                    path=new_path,
                    sort_order=len(a.resources),
                )
            await s.commit()
            # create() 通过 asset_id 写入，已装载的 relationship 不会自动追加；显式
            # 过期后重查，保证响应立即包含用户刚上传的本地图片资源。
            s.expire(a, ["resources"])
            a = await repo.get_by_id(asset_id)
            assert a is not None
    except Exception:
        _delete_global_asset_file(new_path)
        raise

    # 4) DB 更新成功后才删除旧文件
    if old_path and old_path != new_path and not old_path_is_resource:
        _delete_global_asset_file(old_path)

    return {"asset": _serialize(a)}


class SetPrimaryResourceRequest(BaseModel):
    resource_id: str


@router.put("/{asset_id}/primary-resource/{media_type}")
async def set_primary_resource(
    asset_id: str,
    media_type: str,
    req: SetPrimaryResourceRequest,
    _t: Translator,
):
    if media_type not in {"image", "audio"}:
        raise HTTPException(status_code=400, detail=_t("asset_primary_resource_invalid_type"))
    async with async_session_factory() as s:
        asset_repo = AssetRepository(s)
        asset = await asset_repo.get_by_id(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))
        resource = await AssetResourceRepository(s).get_by_id(req.resource_id)
        if resource is None or resource.asset_id != asset_id or resource.media_type != media_type:
            raise HTTPException(status_code=422, detail=_t("asset_primary_resource_invalid"))
        field = "image_path" if media_type == "image" else "audio_path"
        await asset_repo.update(asset_id, **{field: resource.path})
        await s.commit()
        asset = await asset_repo.get_by_id(asset_id)
        assert asset is not None
    return {"asset": _serialize(asset)}


@router.put("/{asset_id}/resources")
async def update_asset_resources(
    asset_id: str,
    _t: Translator,
    name: str | None = Form(None),
    description: str | None = Form(None),
    voice_style: str | None = Form(None),
    voice_id: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    audios: list[UploadFile] | None = File(None),
    remove_resource_ids: str = Form("[]"),
    primary_image_resource_id: str = Form(""),
    primary_audio_resource_id: str = Form(""),
    primary_image_upload_index: int = Form(-1),
    primary_audio_upload_index: int = Form(-1),
):
    """Atomically update the locally managed image/audio groups of one asset.

    Catalog resources are immutable here: the upstream synchronizer owns them. Local
    additions can coexist with catalog files and can be removed again by the user.
    """

    image_files = _nonempty_uploads(images)
    audio_files = _nonempty_uploads(audios)
    try:
        parsed_remove_ids = json.loads(remove_resource_ids)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=_t("asset_resource_selection_invalid")) from exc
    if not isinstance(parsed_remove_ids, list) or not all(isinstance(value, str) for value in parsed_remove_ids):
        raise HTTPException(status_code=422, detail=_t("asset_resource_selection_invalid"))
    remove_ids = set(parsed_remove_ids)
    normalized_name = _validate_asset_name(name, _t) if name is not None else None

    async with async_session_factory() as s:
        asset = await AssetRepository(s).get_by_id(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))
        if normalized_name is not None and normalized_name != asset.name:
            if await AssetRepository(s).exists(asset.type, normalized_name):
                raise HTTPException(status_code=409, detail=_t("asset_already_exists", name=normalized_name))
        if asset.type != "character" and audio_files:
            raise HTTPException(status_code=422, detail=_t("asset_audio_character_only"))
        by_id = {resource.id: resource for resource in asset.resources}
        if not remove_ids.issubset(by_id):
            raise HTTPException(status_code=422, detail=_t("asset_resource_selection_invalid"))
        if any(by_id[resource_id].origin != "local" for resource_id in remove_ids):
            raise HTTPException(status_code=422, detail=_t("asset_catalog_resource_read_only"))
        remaining_count = len(asset.resources) - len(remove_ids) + len(image_files) + len(audio_files)
        # A pre-resource-group local asset can still have one legacy image/audio path.
        for legacy_path in (asset.image_path, asset.audio_path):
            if legacy_path and all(resource.path != legacy_path for resource in asset.resources):
                remaining_count += 1
        _validate_resource_count(remaining_count, _t)
        asset_type = asset.type

    if primary_image_upload_index >= 0 and not 0 <= primary_image_upload_index < len(image_files):
        raise HTTPException(status_code=422, detail=_t("asset_primary_resource_invalid"))
    if primary_audio_upload_index >= 0 and not 0 <= primary_audio_upload_index < len(audio_files):
        raise HTTPException(status_code=422, detail=_t("asset_primary_resource_invalid"))

    saved: list[tuple[str, UploadFile, str, int]] = []
    try:
        for media_type, files in (("image", image_files), ("audio", audio_files)):
            for file in files:
                path, byte_size = await _save_media_upload(file, asset_type, media_type, _t)
                saved.append((media_type, file, path, byte_size))
    except Exception:
        for _media_type, _file, path, _byte_size in saved:
            _delete_global_asset_file(path)
        raise

    removed_paths: set[str] = set()
    try:
        async with async_session_factory() as s:
            asset_repo = AssetRepository(s)
            resource_repo = AssetResourceRepository(s)
            asset = await asset_repo.get_by_id(asset_id)
            if asset is None:
                raise HTTPException(status_code=404, detail=_t("asset_not_found", name=asset_id))

            # Promote old single-file assets into the same resource-group model lazily,
            # preserving compatibility without a data migration or a service restart.
            resources = list(asset.resources)
            next_sort_order = max((resource.sort_order for resource in resources), default=-1) + 1
            for media_type, path in (("image", asset.image_path), ("audio", asset.audio_path)):
                if path and all(resource.path != path for resource in resources):
                    legacy = await resource_repo.create(
                        asset_id=asset.id,
                        resource_key=f"local:{media_type}:legacy:{uuid.uuid4().hex}",
                        origin="local",
                        media_type=media_type,
                        path=path,
                        sort_order=next_sort_order,
                    )
                    next_sort_order += 1
                    resources.append(legacy)

            by_id = {resource.id: resource for resource in resources}
            if not remove_ids.issubset(by_id):
                raise HTTPException(status_code=422, detail=_t("asset_resource_selection_invalid"))
            if any(by_id[resource_id].origin != "local" for resource_id in remove_ids):
                raise HTTPException(status_code=422, detail=_t("asset_catalog_resource_read_only"))

            for resource_id in remove_ids:
                resource = by_id[resource_id]
                removed_paths.add(resource.path)
                await resource_repo.delete(resource)
            remaining = [resource for resource in resources if resource.id not in remove_ids]

            created_by_media: dict[str, list] = {"image": [], "audio": []}
            for media_type, file, path, byte_size in saved:
                resource = await resource_repo.create(
                    asset_id=asset.id,
                    resource_key=f"local:{media_type}:{uuid.uuid4().hex}",
                    origin="local",
                    media_type=media_type,
                    mime_type=file.content_type,
                    path=path,
                    byte_size=byte_size,
                    sort_order=next_sort_order,
                )
                next_sort_order += 1
                remaining.append(resource)
                created_by_media[media_type].append(resource)

            def resolve_primary_path(
                media_type: str,
                existing_resource_id: str,
                upload_index: int,
                current_path: str | None,
            ) -> str | None:
                media_resources = [resource for resource in remaining if resource.media_type == media_type]
                if upload_index >= 0:
                    return created_by_media[media_type][upload_index].path
                if existing_resource_id:
                    selected = next(
                        (resource for resource in media_resources if resource.id == existing_resource_id),
                        None,
                    )
                    if selected is None:
                        raise HTTPException(status_code=422, detail=_t("asset_primary_resource_invalid"))
                    return selected.path
                if any(resource.path == current_path for resource in media_resources):
                    return current_path
                return media_resources[0].path if media_resources else None

            image_path = resolve_primary_path(
                "image",
                primary_image_resource_id,
                primary_image_upload_index,
                asset.image_path,
            )
            audio_path = resolve_primary_path(
                "audio",
                primary_audio_resource_id,
                primary_audio_upload_index,
                asset.audio_path,
            ) if asset.type == "character" else None
            metadata_patch = {
                "image_path": image_path,
                "audio_path": audio_path,
            }
            if normalized_name is not None:
                metadata_patch["name"] = normalized_name
            if description is not None:
                metadata_patch["description"] = description
            if asset.type == "character":
                if voice_style is not None:
                    metadata_patch["voice_style"] = voice_style
                if voice_id is not None:
                    metadata_patch["voice_id"] = voice_id.strip() or None
            await asset_repo.update(asset.id, **metadata_patch)
            await s.commit()
            s.expire(asset, ["resources"])
            asset = await asset_repo.get_by_id(asset.id)
            assert asset is not None
    except IntegrityError as exc:
        for _media_type, _file, path, _byte_size in saved:
            _delete_global_asset_file(path)
        raise HTTPException(
            status_code=409,
            detail=_t("asset_already_exists", name=normalized_name or ""),
        ) from exc
    except Exception:
        for _media_type, _file, path, _byte_size in saved:
            _delete_global_asset_file(path)
        raise

    live_paths = {resource.path for resource in asset.resources}
    live_paths.update(path for path in (asset.image_path, asset.audio_path) if path)
    for path in removed_paths - live_paths:
        _delete_global_asset_file(path)

    return {"asset": _serialize(asset)}


class FromProjectRequest(BaseModel):
    project_name: str
    resource_type: str
    resource_id: str
    override_name: str | None = None
    overwrite: bool = False


@router.post("/from-project")
async def from_project(
    req: FromProjectRequest,
    _t: Translator,
):
    # 1) 类型合法性
    if req.resource_type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise HTTPException(status_code=400, detail=_t("asset_invalid_type"))

    # 2) 加载项目
    try:
        project = get_project_manager().load_project(req.project_name)
    except FileNotFoundError as exc:
        raise NotFoundError("asset_target_project_not_found", project=req.project_name) from exc
    except Exception:
        logger.exception("Failed to load project '%s' for from-project", req.project_name)
        raise HTTPException(status_code=500, detail=_t("asset_load_project_failed"))

    # 3) 从对应 bucket 中读取资源
    bucket_key = BUCKET_KEY[req.resource_type]
    bucket = project.get(bucket_key) or {}
    # 存量 key 与请求名可能是 NFC/NFD 中的任一形态，按坐标系解析
    resource_key = resolve_asset_key(bucket, req.resource_id)
    resource = bucket.get(resource_key) if resource_key is not None else None
    if resource is None:
        raise HTTPException(
            status_code=404,
            detail=_t(
                "asset_source_resource_not_found",
                project=req.project_name,
                kind=localize_asset_type(req.resource_type, _t),
                name=req.resource_id,
            ),
        )

    asset_name = _validate_asset_name(req.override_name or req.resource_id, _t)
    description = resource.get("description") or ""
    voice_style = resource.get("voice_style", "") if req.resource_type == "character" else ""

    sheet_rel = resource.get(SHEET_KEY[req.resource_type]) or ""
    source_sheet_path: Path | None = None
    if sheet_rel:
        try:
            project_dir = get_project_manager().get_project_path(req.project_name)
            ProjectManager._safe_subpath(project_dir, sheet_rel)
            candidate = project_dir / sheet_rel
            if candidate.exists() and candidate.is_file():
                source_sheet_path = candidate
        except (ValueError, FileNotFoundError):
            # 非法路径或项目丢失：视作无源图继续流程
            source_sheet_path = None

    # 音频只有 character 类型有意义（reference_audio，不是 sheet 概念）；缺失/路径非法同图片一样
    # 静默降级为「无源音频」，不中断入库流程。
    audio_rel = resource.get("reference_audio") or "" if req.resource_type == "character" else ""
    source_audio_path: Path | None = None
    if audio_rel:
        try:
            project_dir = get_project_manager().get_project_path(req.project_name)
            ProjectManager._safe_subpath(project_dir, audio_rel)
            candidate = project_dir / audio_rel
            # reference_audio 可经通用角色 PATCH 被写成项目内任意字符串（extra_string_fields
            # 只做类型校验），仅 _safe_subpath 防越界不足以防止把 project.json 等其它项目
            # 文件当作音频复制进全局库；额外校验父目录命中 characters/refs_audio，与
            # server/routers/files.py::_resolve_audio_ref_path 同一口径。
            audio_refs_dir = project_dir / "characters" / "refs_audio"
            if (
                candidate.exists()
                and candidate.is_file()
                and os.path.realpath(candidate.parent) == os.path.realpath(audio_refs_dir)
            ):
                source_audio_path = candidate
        except (ValueError, FileNotFoundError):
            source_audio_path = None

    # 4) DB 预检查（orphan-safe：先查再拷贝文件）
    async with async_session_factory() as s:
        repo = AssetRepository(s)
        existing = await repo.get_by_type_name(req.resource_type, asset_name)

    if existing is not None and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail={
                "message": _t("asset_already_exists", name=asset_name),
                "existing": _serialize(existing),
            },
        )

    # 5) 拷贝源 sheet / 参考音频到 _global_assets/{type}/{uuid}.{ext}
    # 两次拷贝共用一个失败边界：任一失败都清理已落盘的另一个文件，不留孤儿。
    new_image_path: str | None = None
    new_audio_path: str | None = None
    try:
        if source_sheet_path is not None:
            ext = source_sheet_path.suffix.lower() or ".png"
            root = get_project_manager().get_global_assets_root() / req.resource_type
            uid = uuid.uuid4().hex
            target = root / f"{uid}{ext}"
            await asyncio.to_thread(shutil.copyfile, source_sheet_path, target)
            new_image_path = f"_global_assets/{req.resource_type}/{uid}{ext}"

        if source_audio_path is not None:
            ext = source_audio_path.suffix.lower() or ".wav"
            root = get_project_manager().get_global_assets_root() / req.resource_type
            uid = uuid.uuid4().hex
            target = root / f"{uid}{ext}"
            await asyncio.to_thread(shutil.copyfile, source_audio_path, target)
            new_audio_path = f"_global_assets/{req.resource_type}/{uid}{ext}"
    except Exception:
        if new_image_path:
            _delete_global_asset_file(new_image_path)
        if new_audio_path:
            _delete_global_asset_file(new_audio_path)
        raise

    # 6) 写 DB：失败路径清理拷贝文件
    try:
        async with async_session_factory() as s:
            repo = AssetRepository(s)
            if existing is not None:
                # overwrite：先记下旧文件路径，commit 成功后再删；回滚时旧文件保留
                old_image = (
                    existing.image_path if existing.image_path and existing.image_path != new_image_path else None
                )
                old_audio = (
                    existing.audio_path if existing.audio_path and existing.audio_path != new_audio_path else None
                )
                a = await repo.update(
                    existing.id,
                    description=description,
                    voice_style=voice_style,
                    image_path=new_image_path,
                    audio_path=new_audio_path,
                    source_project=req.project_name,
                )
                await s.commit()
                await s.refresh(a)
                if old_image:
                    _delete_global_asset_file(old_image)
                if old_audio:
                    _delete_global_asset_file(old_audio)
            else:
                try:
                    a = await repo.create(
                        type=req.resource_type,
                        name=asset_name,
                        description=description,
                        voice_style=voice_style,
                        image_path=new_image_path,
                        audio_path=new_audio_path,
                        source_project=req.project_name,
                    )
                    await s.commit()
                    await s.refresh(a)
                except IntegrityError:
                    await s.rollback()
                    if new_image_path:
                        _delete_global_asset_file(new_image_path)
                    if new_audio_path:
                        _delete_global_asset_file(new_audio_path)
                    raise HTTPException(
                        status_code=409,
                        detail=_t("asset_already_exists", name=asset_name),
                    )
    except HTTPException:
        raise
    except Exception:
        if new_image_path:
            _delete_global_asset_file(new_image_path)
        if new_audio_path:
            _delete_global_asset_file(new_audio_path)
        raise

    return {"asset": _serialize(a)}


class ApplyToProjectRequest(BaseModel):
    asset_ids: list[str]
    target_project: str
    conflict_policy: str = "skip"  # 'skip' | 'overwrite' | 'rename'


@router.post("/apply-to-project")
async def apply_to_project(
    req: ApplyToProjectRequest,
    _t: Translator,
):
    # 1) 校验冲突策略（400 先于其它检查）
    if req.conflict_policy not in {"skip", "overwrite", "rename"}:
        raise HTTPException(status_code=400, detail=_t("asset_invalid_conflict_policy"))
    asset_ids = list(dict.fromkeys(req.asset_ids))

    # 2) 校验目标项目存在
    project_manager = get_project_manager()
    try:
        project = project_manager.load_project(req.target_project)
    except ProjectAssetNameConflictError as exc:
        raise HTTPException(status_code=409, detail=localize_project_asset_name_conflict(exc, _t)) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("asset_target_project_not_found", project=req.target_project) from exc

    succeeded: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    # 3) 批量读取所有请求的 asset，缺失的直接归入 failed
    async with async_session_factory() as s:
        assets = await AssetRepository(s).get_by_ids(asset_ids)
    assets_by_id = {a.id: a for a in assets}
    for asset_id in asset_ids:
        if asset_id not in assets_by_id:
            failed.append({"id": asset_id, "reason": "not_found"})

    # 4) 先在内存里算好每条 asset 的目标名 + 是否需要拷贝文件，
    #    再一次性执行文件拷贝和 project.json 写回
    project_dir = project_manager.get_project_path(req.target_project)
    # 四类资产共用一份名称占用表；owner 用于区分同类 overwrite 与不可覆盖的跨类型冲突。
    occupied: dict[str, tuple[str, str]] = {}
    for asset_type, bucket_key in BUCKET_KEY.items():
        bucket = project.get(bucket_key)
        if isinstance(bucket, dict):
            for raw_name in bucket:
                if isinstance(raw_name, str):
                    occupied[asset_name_comparison_key(raw_name)] = (asset_type, raw_name)
    plans: list[dict] = []
    for asset_id in asset_ids:
        a = assets_by_id.get(asset_id)
        if a is None:
            continue  # 已在 failed

        bucket_key = BUCKET_KEY[a.type]
        sheet_key = SHEET_KEY[a.type]
        try:
            desired_name = _validate_asset_name(a.name, _t)
        except HTTPException:
            failed.append({"id": a.id, "reason": "invalid_name"})
            continue

        existing = occupied.get(asset_name_comparison_key(desired_name))
        if existing is not None:
            same_type = existing[0] == a.type
            if req.conflict_policy == "skip":
                skipped.append({"id": a.id, "name": a.name})
                continue
            if req.conflict_policy == "rename":
                base_name = desired_name
                i = 2
                while asset_name_comparison_key(f"{base_name} ({i})") in occupied:
                    i += 1
                desired_name = f"{base_name} ({i})"
            elif not same_type:
                failed.append({"id": a.id, "reason": "project_name_conflict"})
                continue
            # overwrite 只能覆盖同类型条目。

        # 规划图片拷贝
        target_sheet: str | None = None
        copy_src: Path | None = None
        copy_dst: Path | None = None
        if a.image_path:
            src = project_manager.projects_root / a.image_path
            if src.exists() and src.is_file():
                ext = src.suffix.lower() or ".png"
                rel_sheet = f"{bucket_key}/{desired_name}{ext}"
                try:
                    ProjectManager._safe_subpath(project_dir, rel_sheet)
                except ValueError:
                    failed.append({"id": a.id, "reason": "invalid_name"})
                    continue
                target_sheet = rel_sheet
                copy_src = src
                copy_dst = project_dir / rel_sheet
            else:
                logger.warning(
                    "apply_to_project: asset %s image file missing on disk: %s",
                    a.id,
                    a.image_path,
                )
                failed.append({"id": a.id, "reason": "image_missing"})
                continue

        # 规划参考音频拷贝：与图片同口径（缺失即整条 failed，不中断整批）；只有 character 有意义
        target_audio: str | None = None
        copy_audio_src: Path | None = None
        copy_audio_dst: Path | None = None
        if a.type == "character" and a.audio_path:
            audio_src = project_manager.projects_root / a.audio_path
            if audio_src.exists() and audio_src.is_file():
                audio_ext = audio_src.suffix.lower() or ".wav"
                rel_audio = f"characters/refs_audio/{desired_name}{audio_ext}"
                try:
                    ProjectManager._safe_subpath(project_dir, rel_audio)
                except ValueError:
                    failed.append({"id": a.id, "reason": "invalid_name"})
                    continue
                target_audio = rel_audio
                copy_audio_src = audio_src
                copy_audio_dst = project_dir / rel_audio
            else:
                logger.warning(
                    "apply_to_project: asset %s audio file missing on disk: %s",
                    a.id,
                    a.audio_path,
                )
                failed.append({"id": a.id, "reason": "audio_missing"})
                continue

        occupied[asset_name_comparison_key(desired_name)] = (a.type, desired_name)
        plans.append(
            {
                "asset": a,
                "requested_name": _validate_asset_name(a.name, _t),
                "bucket_key": bucket_key,
                "sheet_key": sheet_key,
                "desired_name": desired_name,
                "target_sheet": target_sheet,
                "copy_src": copy_src,
                "copy_dst": copy_dst,
                "target_audio": target_audio,
                "copy_audio_src": copy_audio_src,
                "copy_audio_dst": copy_audio_dst,
            }
        )

    # 5) 单次事务把所有文件替换与 bucket 变更一次性写回。锁外规划只用于快速失败；
    #    锁内必须从 requested_name 重施策略，覆盖快照之后出现的同类型占用。
    file_copies: list[tuple[Path, Path]] = []

    def _apply_all(data: dict) -> None:
        applied_plans: list[dict] = []
        for plan in plans:
            a_ = plan["asset"]
            bk = plan["bucket_key"]
            sk = plan["sheet_key"]
            name_ = plan["requested_name"]
            existing = find_project_asset_name(data, name_)
            if existing is not None:
                if req.conflict_policy == "skip":
                    skipped.append({"id": a_.id, "name": a_.name})
                    continue
                if req.conflict_policy == "rename":
                    base_name = name_
                    index = 2
                    while find_project_asset_name(data, f"{base_name} ({index})") is not None:
                        index += 1
                    name_ = f"{base_name} ({index})"
                    existing = None
                elif existing.asset_type != a_.type:
                    raise ProjectAssetNameConflictError(name_, existing, a_.type)

            plan["desired_name"] = name_
            if plan["copy_src"] is not None:
                extension = plan["copy_src"].suffix.lower() or ".png"
                plan["target_sheet"] = f"{bk}/{name_}{extension}"
                plan["copy_dst"] = project_dir / plan["target_sheet"]
                file_copies.append((plan["copy_src"], plan["copy_dst"]))
            if plan["copy_audio_src"] is not None:
                extension = plan["copy_audio_src"].suffix.lower() or ".wav"
                plan["target_audio"] = f"characters/refs_audio/{name_}{extension}"
                plan["copy_audio_dst"] = project_dir / plan["target_audio"]
                file_copies.append((plan["copy_audio_src"], plan["copy_audio_dst"]))

            ts = plan["target_sheet"]
            ta = plan["target_audio"]
            ensure_project_asset_name_available(
                data,
                name_,
                requested_asset_type=a_.type,
                exclude_asset_type=a_.type,
                exclude_name=existing.name if existing is not None and existing.asset_type == a_.type else None,
            )
            payload: dict = {"description": a_.description or ""}
            if a_.type == "character":
                payload["voice_style"] = a_.voice_style or ""
                if a_.voice_id:
                    payload["voice_id"] = a_.voice_id
                if ta:
                    payload["reference_audio"] = ta
                    # 资产即开关：导入即等效「设置了这个声音」，存量过渡横幅计数须能感知
                    payload["voice_updated_at"] = datetime.now(UTC).isoformat()
            if ts:
                payload[sk] = ts
            if bk not in data or not isinstance(data.get(bk), dict):
                data[bk] = {}
            # overwrite 策略要落在存量真实 key 上（可能是 NFD），否则会并存两条视觉同名条目
            key = existing.name if existing is not None and existing.asset_type == a_.type else name_
            data[bk][key] = payload
            applied_plans.append(plan)

        plans[:] = applied_plans

    if plans:

        def _register_imported_sheet_claims(_project_file: Path) -> None:
            keys = {ArtifactKey.asset_sheet(plan["asset"].type, plan["desired_name"]) for plan in plans}
            register_artifact_entries_atomically(
                project_dir,
                {key: resolve_current_artifact_target(project_dir, key) for key in keys},
            )

        try:
            await asyncio.to_thread(
                project_manager.update_project_with_file_copies,
                req.target_project,
                _apply_all,
                file_copies,
                on_commit=_register_imported_sheet_claims,
            )
        except ProjectAssetNameConflictError as exc:
            raise HTTPException(status_code=409, detail=localize_project_asset_name_conflict(exc, _t)) from exc

    for plan in plans:
        succeeded.append({"id": plan["asset"].id, "name": plan["desired_name"]})

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}
