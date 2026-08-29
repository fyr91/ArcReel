"""Croco 角色目录同步 API。"""

from fastapi import APIRouter

from lib.background_job_worker import CHARACTER_CATALOG_SYNC_JOB
from lib.db import async_session_factory
from lib.db.repositories.background_job_repo import BackgroundJobRepository
from lib.i18n import Translator
from server.auth import CurrentUser

router = APIRouter(prefix="/character-catalog", tags=["角色目录"])


@router.post("/sync", status_code=202)
async def sync_catalog(_t: Translator, user: CurrentUser):
    async with async_session_factory() as session:
        job, deduped = await BackgroundJobRepository(session).enqueue(
            CHARACTER_CATALOG_SYNC_JOB,
            owner_id=user.id,
            payload={"asset_type": "character", "trigger": "legacy_manual"},
        )
    return {"job": _localized_job(job, _t), "deduped": deduped}


@router.get("/sync/status")
async def sync_catalog_status(_t: Translator, user: CurrentUser):
    async with async_session_factory() as session:
        job = await BackgroundJobRepository(session).get_latest(CHARACTER_CATALOG_SYNC_JOB, owner_id=user.id)
    return {"job": _localized_job(job, _t) if job else None}


def _localized_job(job: dict, _t: Translator) -> dict:
    payload = dict(job)
    code = payload.get("error_code")
    if code:
        payload["error_message"] = _t(code, status=payload.get("error_detail") or "")
    else:
        payload["error_message"] = None
    return payload
