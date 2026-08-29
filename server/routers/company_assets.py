"""Local pull endpoints for the central company asset catalog."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from lib.background_job_worker import company_asset_sync_job_type
from lib.company_assets import (
    CompanyAssetSyncError,
    delete_company_catalog_asset,
    download_company_catalog_asset_preview,
    list_company_catalog_assets,
    publish_local_asset,
)
from lib.db import async_session_factory
from lib.db.repositories.background_job_repo import BackgroundJobRepository
from lib.i18n import Translator
from lib.project_manager import get_project_manager
from server.auth import CurrentUser
from server.services.company_asset_supabase import get_company_asset_catalog

AssetType = Literal["character", "scene", "prop"]

router = APIRouter(prefix="/company-assets", tags=["公司资产库"])


class SourceControlRequest(BaseModel):
    action: Literal["pause", "resume", "set_interval"]
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)


@router.post("/sync/{asset_type}", status_code=202)
async def sync_asset_type(asset_type: AssetType, user: CurrentUser, _t: Translator):
    async with async_session_factory() as session:
        job, deduped = await BackgroundJobRepository(session).enqueue(
            company_asset_sync_job_type(asset_type),
            owner_id=user.id,
            payload={"asset_type": asset_type, "trigger": "manual"},
        )
    return {"job": _localized_job(job, _t), "deduped": deduped}


@router.get("/sync/{asset_type}/status")
async def sync_asset_type_status(asset_type: AssetType, user: CurrentUser, _t: Translator):
    async with async_session_factory() as session:
        job = await BackgroundJobRepository(session).get_latest(
            company_asset_sync_job_type(asset_type),
            owner_id=user.id,
        )
    return {"job": _localized_job(job, _t) if job else None}


@router.post("/sync-all", status_code=202)
async def sync_all_asset_types(user: CurrentUser, _t: Translator):
    jobs = []
    async with async_session_factory() as session:
        repository = BackgroundJobRepository(session)
        for asset_type in ("character", "scene", "prop"):
            job, deduped = await repository.enqueue(
                company_asset_sync_job_type(asset_type),
                owner_id=user.id,
                payload={"asset_type": asset_type, "trigger": "login"},
            )
            jobs.append({"job": _localized_job(job, _t), "deduped": deduped})
    return {"jobs": jobs}


@router.post("/{asset_id}/publish")
async def publish_asset(asset_id: str, user: CurrentUser, _t: Translator):
    try:
        async with async_session_factory() as session:
            result = await publish_local_asset(
                session,
                publisher=get_company_asset_catalog(),
                manager=get_project_manager(),
                user_id=user.id,
                asset_id=asset_id,
            )
    except CompanyAssetSyncError as exc:
        if exc.code == "company_asset_local_not_found":
            status_code = 404
        elif exc.code == "company_asset_not_owned":
            status_code = 403
        elif exc.code == "company_asset_official_read_only":
            status_code = 409
        elif exc.code in {"company_asset_request_failed", "company_asset_cloud_not_configured"}:
            status_code = 503
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=_t(exc.code)) from exc
    return {
        "asset_id": result.asset_id,
        "version_id": result.version_id,
        "version": result.version,
    }


@router.get("/source-sync/dashboard")
async def source_sync_dashboard(user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        return await get_company_asset_catalog().source_sync_dashboard(user_id=user.id)
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc


@router.get("/source-sync/assets")
async def list_source_assets(
    user: CurrentUser,
    _t: Translator,
    asset_type: AssetType | None = None,
    origin: Literal["official", "user_shared"] | None = None,
    q: str | None = None,
    limit: int = 24,
    offset: int = 0,
):
    _require_admin(user)
    try:
        page = await list_company_catalog_assets(
            administrator=get_company_asset_catalog(),
            user_id=user.id,
            asset_type=asset_type,
            origin=origin,
            query=q,
            limit=limit,
            offset=offset,
        )
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc
    return {
        "items": [asdict(item) for item in page.items],
        "total": page.total,
        "totals": page.totals,
    }


@router.get("/source-sync/assets/{asset_id}/preview")
async def preview_source_asset(asset_id: str, user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        preview = await download_company_catalog_asset_preview(
            administrator=get_company_asset_catalog(),
            user_id=user.id,
            asset_id=asset_id,
        )
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc
    return Response(
        content=preview.content,
        media_type=preview.mime_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/source-sync/assets/{asset_id}")
async def delete_source_asset(asset_id: str, user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        result = await delete_company_catalog_asset(
            administrator=get_company_asset_catalog(),
            user_id=user.id,
            asset_id=asset_id,
        )
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc
    return asdict(result)


@router.post("/source-sync/sources/{source_key}/run", status_code=202)
async def run_source_sync(source_key: str, user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        return await get_company_asset_catalog().request_source_sync(user_id=user.id, source_key=source_key)
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc


@router.post("/source-sync/sources/{source_key}/control")
async def control_source_sync(source_key: str, request: SourceControlRequest, user: CurrentUser, _t: Translator):
    _require_admin(user)
    if request.action == "set_interval" and request.interval_seconds is None:
        raise HTTPException(status_code=422, detail="interval_seconds is required")
    try:
        return await get_company_asset_catalog().update_source_sync(
            user_id=user.id,
            source_key=source_key,
            action=request.action,
            interval_seconds=request.interval_seconds,
        )
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc


@router.post("/source-sync/runs/{run_id}/cancel")
async def cancel_source_sync(run_id: str, user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        return await get_company_asset_catalog().cancel_source_sync(user_id=user.id, run_id=run_id)
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc


@router.post("/source-sync/runs/{run_id}/retry", status_code=202)
async def retry_source_sync(run_id: str, user: CurrentUser, _t: Translator):
    _require_admin(user)
    try:
        return await get_company_asset_catalog().retry_source_sync(user_id=user.id, run_id=run_id)
    except CompanyAssetSyncError as exc:
        raise _catalog_http_error(exc, _t) from exc


def _require_admin(user) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _catalog_http_error(exc: CompanyAssetSyncError, _t: Translator) -> HTTPException:
    if exc.code in {"company_asset_request_failed", "company_asset_cloud_not_configured"}:
        status_code = 503
    elif exc.code == "company_asset_not_owned":
        status_code = 403
    elif exc.code == "company_asset_local_not_found":
        status_code = 404
    else:
        status_code = 400
    return HTTPException(status_code=status_code, detail=_t(exc.code))


def _localized_job(job: dict, _t: Translator) -> dict:
    payload = dict(job)
    code = payload.get("error_code")
    payload["error_message"] = _t(code, status=payload.get("error_detail") or "") if code else None
    return payload


__all__ = ["router"]
