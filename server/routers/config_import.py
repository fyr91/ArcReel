"""First-run release configuration import endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config_bundle import (
    ConfigBundleError,
    ConfigReadiness,
    get_config_readiness,
    import_release_config_bundle,
    is_config_import_enabled,
    parse_config_bundle_env,
)
from lib.db import get_async_session
from lib.i18n import Translator

router = APIRouter(prefix="/config-import")

_MAX_CONFIG_FILE_BYTES = 1024 * 1024


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
    session: AsyncSession = Depends(get_async_session),
) -> ConfigReadiness:
    if not is_config_import_enabled():
        raise HTTPException(status_code=403, detail=_t("config_import_disabled"))

    try:
        contents = await file.read(_MAX_CONFIG_FILE_BYTES + 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_t("config_bundle_read_failed")) from exc
    if len(contents) > _MAX_CONFIG_FILE_BYTES:
        raise HTTPException(status_code=413, detail=_t("config_bundle_too_large"))
    try:
        text = contents.decode("utf-8-sig")
        bundle = parse_config_bundle_env(text)
        await import_release_config_bundle(session, bundle)
        await session.commit()
    except UnicodeDecodeError as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=_t("config_bundle_invalid_encoding")) from exc
    except ConfigBundleError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=_t(exc.code)) from exc
    except Exception:
        await session.rollback()
        raise

    # Provider clients and worker capacity are cached. Reuse the same invalidation
    # boundary as the settings UI after the transaction is durable.
    from server.services.generation_context import invalidate_backend_cache

    invalidate_backend_cache()
    worker = getattr(request.app.state, "generation_worker", None)
    if worker is not None:
        await worker.reload_limits()
    return await get_config_readiness(session)
