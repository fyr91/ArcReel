"""Worker for durable, non-generation background jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from lib.company_assets import CompanyAssetSyncError, sync_company_assets
from lib.db import safe_session_factory
from lib.db.repositories.background_job_repo import BackgroundJobRepository
from lib.project_manager import get_project_manager
from server.services.company_asset_supabase import get_company_asset_catalog

logger = logging.getLogger(__name__)

COMPANY_ASSET_SYNC_JOB_PREFIX = "company_asset_sync:"


def company_asset_sync_job_type(asset_type: str) -> str:
    if asset_type not in {"character", "scene", "prop"}:
        raise ValueError(f"Unsupported company asset type: {asset_type}")
    return f"{COMPANY_ASSET_SYNC_JOB_PREFIX}{asset_type}"


# Kept as a compatibility import for older extensions; it now targets the
# company catalog instead of contacting the source catalog directly.
CHARACTER_CATALOG_SYNC_JOB = company_asset_sync_job_type("character")


class BackgroundJobWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Any] = safe_session_factory,
        catalog_factory: Callable[[], Any] = get_company_asset_catalog,
        project_manager_factory: Callable[[], Any] = get_project_manager,
        poll_interval: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._catalog_factory = catalog_factory
        self._project_manager_factory = project_manager_factory
        self._poll_interval = poll_interval
        self._stopping = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async with self._session_factory() as session:
            recovered = await BackgroundJobRepository(session).recover_interrupted()
        if recovered:
            logger.info("Recovered %d interrupted background job(s)", recovered)
        self._stopping.clear()
        self._runner = asyncio.create_task(self._run(), name="background-job-worker")

    async def stop(self) -> None:
        self._stopping.set()
        if self._runner is not None:
            await self._runner
            self._runner = None

    async def _run(self) -> None:
        while not self._stopping.is_set():
            async with self._session_factory() as session:
                job = await BackgroundJobRepository(session).claim_next()
            if job is None:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_interval)
                except TimeoutError:
                    pass
                continue
            await self._execute(job)

    async def _execute(self, job: dict[str, Any]) -> None:
        job_id = job["job_id"]
        if not job["job_type"].startswith(COMPANY_ASSET_SYNC_JOB_PREFIX):
            await self._fail(job_id, "background_job_unsupported")
            return
        asset_type = job["job_type"][len(COMPANY_ASSET_SYNC_JOB_PREFIX) :]
        if asset_type not in {"character", "scene", "prop"}:
            await self._fail(job_id, "background_job_unsupported")
            return

        async def report_progress(current: int, total: int, progress_asset_type: str) -> None:
            async with self._session_factory() as progress_session:
                await BackgroundJobRepository(progress_session).update_progress(
                    job_id,
                    phase=f"syncing_{progress_asset_type}",
                    current=current,
                    total=total,
                )

        try:
            async with self._session_factory() as sync_session:
                result = await sync_company_assets(
                    sync_session,
                    catalog=self._catalog_factory(),
                    manager=self._project_manager_factory(),
                    user_id=job["owner_id"],
                    asset_types=(asset_type,),
                    progress_callback=report_progress,
                )
            async with self._session_factory() as complete_session:
                await BackgroundJobRepository(complete_session).mark_succeeded(job_id, result)
        except CompanyAssetSyncError as exc:
            await self._fail(job_id, exc.code, exc.detail)
        except Exception:  # noqa: BLE001
            logger.exception("Background job failed job_id=%s type=%s", job_id, job["job_type"])
            await self._fail(job_id, "company_asset_sync_failed")

    async def _fail(self, job_id: str, code: str, detail: str | None = None) -> None:
        async with self._session_factory() as session:
            await BackgroundJobRepository(session).mark_failed(job_id, error_code=code, error_detail=detail)
