"""First-run release configuration import endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config_bundle import (
    ConfigBundleError,
    ConfigImportPreview,
    ConfigReadiness,
    get_config_readiness,
    import_release_config_bundle,
    is_config_import_enabled,
    parse_config_bundle_env,
    preview_config_import,
    reset_project_environment_overrides,
)
from lib.db import get_async_session
from lib.i18n import Translator

router = APIRouter(prefix="/config-import")

_MAX_CONFIG_FILE_BYTES = 1024 * 1024


async def _read_bundle(file: UploadFile, _t: Translator):
    try:
        contents = await file.read(_MAX_CONFIG_FILE_BYTES + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_t("config_bundle_read_failed")) from exc
    if len(contents) > _MAX_CONFIG_FILE_BYTES:
        raise HTTPException(status_code=413, detail=_t("config_bundle_too_large"))
    try:
        return parse_config_bundle_env(contents.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=_t("config_bundle_invalid_encoding")) from exc
    except ConfigBundleError as exc:
        raise HTTPException(status_code=422, detail=_t(exc.code)) from exc


@router.get("/status", response_model=ConfigReadiness)
async def config_import_status(
    session: AsyncSession = Depends(get_async_session),
) -> ConfigReadiness:
    return await get_config_readiness(session)


@router.post("/file", response_model=ConfigReadiness)
async def import_config_file(
    request: Request,
    _t: Translator,
    file: UploadFile = File(...),
    replace_existing: bool = False,
    update_projects: bool = False,
    session: AsyncSession = Depends(get_async_session),
) -> ConfigReadiness:
    # 首次启动 gate 沿用环境开关；系统设置页的显式“替换环境”操作始终可用。
    if not is_config_import_enabled() and not (replace_existing and update_projects):
        raise HTTPException(status_code=403, detail=_t("config_import_disabled"))

    project_rollback = None
    try:
        bundle = await _read_bundle(file, _t)
        await import_release_config_bundle(session, bundle, replace_existing=replace_existing)
        if update_projects:
            project_rollback = await asyncio.to_thread(reset_project_environment_overrides)
        await session.commit()
    except ConfigBundleError as exc:
        await session.rollback()
        if project_rollback is not None:
            await asyncio.to_thread(project_rollback.restore)
        raise HTTPException(status_code=422, detail=_t(exc.code)) from exc
    except HTTPException:
        await session.rollback()
        if project_rollback is not None:
            await asyncio.to_thread(project_rollback.restore)
        raise
    except Exception:
        await session.rollback()
        if project_rollback is not None:
            await asyncio.to_thread(project_rollback.restore)
        raise

    # Provider clients and worker capacity are cached. Reuse the same invalidation
    # boundary as the settings UI after the transaction is durable.
    from server.services.generation_context import invalidate_backend_cache

    invalidate_backend_cache()
    worker = getattr(request.app.state, "generation_worker", None)
    if worker is not None:
        await worker.reload_limits()
    return await get_config_readiness(session)


@router.post("/preview", response_model=ConfigImportPreview)
async def preview_config_file(
    _t: Translator,
    file: UploadFile = File(...),
) -> ConfigImportPreview:
    """只读解析环境文件并统计覆盖面；不受首次启动开关限制。"""

    bundle = await _read_bundle(file, _t)
    try:
        return await asyncio.to_thread(preview_config_import, bundle)
    except ConfigBundleError as exc:
        raise HTTPException(status_code=422, detail=_t(exc.code)) from exc
