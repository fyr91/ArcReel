from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.background_job_worker import BackgroundJobWorker, company_asset_sync_job_type
from lib.db.base import Base
from lib.db.repositories.background_job_repo import BackgroundJobRepository
from server.auth import CurrentUserInfo
from tests.conftest import make_translator


@pytest.mark.unit
async def test_background_job_enqueue_dedupes_active_job(db_factory) -> None:
    job_type = company_asset_sync_job_type("character")
    async with db_factory() as session:
        first, first_deduped = await BackgroundJobRepository(session).enqueue(
            job_type,
            owner_id="user-1",
            payload={"asset_type": "character"},
        )
    async with db_factory() as session:
        second, second_deduped = await BackgroundJobRepository(session).enqueue(
            job_type,
            owner_id="user-1",
            payload={"asset_type": "character"},
        )

    assert first_deduped is False
    assert second_deduped is True
    assert second["job_id"] == first["job_id"]
    assert second["owner_id"] == "user-1"
    assert second["payload"] == {"asset_type": "character"}

    async with db_factory() as session:
        other_user, other_deduped = await BackgroundJobRepository(session).enqueue(
            job_type,
            owner_id="user-2",
            payload={"asset_type": "character"},
        )
    assert other_deduped is False
    assert other_user["job_id"] != first["job_id"]


@pytest.mark.unit
async def test_background_worker_persists_progress_and_result(tmp_path, monkeypatch) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_progress: list[tuple[int, int, str]] = []

    async def fake_sync(_session, *, catalog, manager, user_id, asset_types, progress_callback):
        assert catalog is sentinel_catalog
        assert manager is sentinel_manager
        assert user_id == "user-1"
        assert asset_types == ("scene",)
        for current in (0, 1, 2):
            await progress_callback(current, 2, "scene")
            observed_progress.append((current, 2, "scene"))
        return {
            "added": 2,
            "updated": 0,
            "archived": 0,
            "unchanged": 0,
            "assetsDownloaded": 4,
        }

    sentinel_catalog = object()
    sentinel_manager = object()
    monkeypatch.setattr("lib.background_job_worker.sync_company_assets", fake_sync)
    job_type = company_asset_sync_job_type("scene")
    async with factory() as session:
        queued, _ = await BackgroundJobRepository(session).enqueue(
            job_type,
            owner_id="user-1",
            payload={"asset_type": "scene"},
        )

    worker = BackgroundJobWorker(
        session_factory=factory,
        catalog_factory=lambda: sentinel_catalog,
        project_manager_factory=lambda: sentinel_manager,
        poll_interval=0.01,
    )
    await worker.start()
    try:
        for _ in range(100):
            async with factory() as session:
                latest = await BackgroundJobRepository(session).get_latest(job_type, owner_id="user-1")
            if latest and latest["status"] == "succeeded":
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("background job did not finish")
    finally:
        await worker.stop()
        await engine.dispose()

    assert latest is not None
    assert latest["job_id"] == queued["job_id"]
    assert latest["progress_current"] == 2
    assert latest["progress_total"] == 2
    assert latest["result"]["added"] == 2
    assert observed_progress == [(0, 2, "scene"), (1, 2, "scene"), (2, 2, "scene")]


@pytest.mark.unit
async def test_recover_interrupted_job_returns_it_to_queue(db_factory) -> None:
    job_type = company_asset_sync_job_type("prop")
    async with db_factory() as session:
        queued, _ = await BackgroundJobRepository(session).enqueue(job_type, owner_id="user-1")
        claimed = await BackgroundJobRepository(session).claim_next()
        assert claimed and claimed["status"] == "running"

    async with db_factory() as session:
        recovered = await BackgroundJobRepository(session).recover_interrupted()
        latest = await BackgroundJobRepository(session).get_latest(job_type, owner_id="user-1")

    assert recovered == 1
    assert latest is not None
    assert latest["job_id"] == queued["job_id"]
    assert latest["status"] == "queued"
    assert latest["phase"] == "queued"


@pytest.mark.unit
async def test_character_catalog_route_enqueues_and_reports_status(db_factory, monkeypatch) -> None:
    from server.routers import character_catalog

    monkeypatch.setattr(character_catalog, "async_session_factory", db_factory)
    user = CurrentUserInfo(id="user-1", sub="alice", role="user")
    queued = await character_catalog.sync_catalog(make_translator(), user)
    status = await character_catalog.sync_catalog_status(make_translator(), user)

    assert queued["deduped"] is False
    assert queued["job"]["status"] == "queued"
    assert status["job"]["job_id"] == queued["job"]["job_id"]
    assert queued["job"]["updated_at"].endswith("+00:00")
    assert status["job"]["updated_at"].endswith("+00:00")


@pytest.mark.unit
async def test_company_asset_route_scopes_jobs_by_user_and_type(db_factory, monkeypatch) -> None:
    from server.routers import company_assets

    monkeypatch.setattr(company_assets, "async_session_factory", db_factory)
    user = CurrentUserInfo(id="user-1", sub="alice", role="user")

    queued = await company_assets.sync_asset_type("prop", user, make_translator())
    status = await company_assets.sync_asset_type_status("prop", user, make_translator())
    all_types = await company_assets.sync_all_asset_types(user, make_translator())

    assert queued["job"]["job_type"] == company_asset_sync_job_type("prop")
    assert queued["job"]["owner_id"] == "user-1"
    assert queued["job"]["payload"] == {"asset_type": "prop", "trigger": "manual"}
    assert status["job"]["job_id"] == queued["job"]["job_id"]
    assert {item["job"]["payload"]["asset_type"] for item in all_types["jobs"]} == {
        "character",
        "scene",
        "prop",
    }


@pytest.mark.unit
async def test_company_asset_publish_route_uses_the_shared_domain_operation(db_factory, monkeypatch) -> None:
    from lib.company_assets import CompanyAssetPublishResult
    from server.routers import company_assets

    monkeypatch.setattr(company_assets, "async_session_factory", db_factory)
    sentinel_catalog = object()
    sentinel_manager = object()
    observed = {}

    async def fake_publish(session, *, publisher, manager, user_id, asset_id):
        observed.update(
            session=session,
            publisher=publisher,
            manager=manager,
            user_id=user_id,
            asset_id=asset_id,
        )
        return CompanyAssetPublishResult(asset_id="central", version_id="version", version=2)

    monkeypatch.setattr(company_assets, "get_company_asset_catalog", lambda: sentinel_catalog)
    monkeypatch.setattr(company_assets, "get_project_manager", lambda: sentinel_manager)
    monkeypatch.setattr(company_assets, "publish_local_asset", fake_publish)
    user = CurrentUserInfo(id="user-1", sub="alice", role="user")

    response = await company_assets.publish_asset("local-asset", user, make_translator())

    assert response == {"asset_id": "central", "version_id": "version", "version": 2}
    assert observed == {
        "session": observed["session"],
        "publisher": sentinel_catalog,
        "manager": sentinel_manager,
        "user_id": "user-1",
        "asset_id": "local-asset",
    }


@pytest.mark.unit
async def test_company_asset_publish_route_reports_ownership_denial(db_factory, monkeypatch) -> None:
    from fastapi import HTTPException

    from lib.company_assets import CompanyAssetSyncError
    from server.routers import company_assets

    async def fake_publish(*args, **kwargs):
        raise CompanyAssetSyncError("company_asset_not_owned")

    monkeypatch.setattr(company_assets, "async_session_factory", db_factory)
    monkeypatch.setattr(company_assets, "publish_local_asset", fake_publish)
    monkeypatch.setattr(company_assets, "get_company_asset_catalog", object)
    monkeypatch.setattr(company_assets, "get_project_manager", object)
    user = CurrentUserInfo(id="user-1", sub="alice", role="user")

    with pytest.raises(HTTPException) as raised:
        await company_assets.publish_asset("local-asset", user, make_translator())

    assert raised.value.status_code == 403
    assert raised.value.detail == "该公司资产由其他用户共享，你不能发布它的新版本"


@pytest.mark.unit
async def test_company_asset_admin_routes_use_the_shared_list_and_delete_operations(monkeypatch) -> None:
    from lib.company_assets import CompanyAssetAdminItem, CompanyAssetAdminPage, CompanyAssetDeleteResult
    from server.routers import company_assets

    item = CompanyAssetAdminItem(
        id="6bf51491-016c-42ed-bd35-458ca670b4f4",
        asset_type="character",
        origin="official",
        status="published",
        version=1,
        name="测试人物",
        description="",
        owner_name=None,
        source_name="人物资产渠道",
        files=(),
        created_at="2026-08-29T00:00:00Z",
        updated_at="2026-08-29T00:00:00Z",
    )
    catalog = object()
    calls = []

    async def fake_list(**kwargs):
        calls.append(("list", kwargs))
        return CompanyAssetAdminPage(
            items=(item,),
            total=1,
            totals={"character": 1, "scene": 0, "prop": 0},
        )

    async def fake_delete(**kwargs):
        calls.append(("delete", kwargs))
        return CompanyAssetDeleteResult(
            asset_id=item.id,
            name=item.name,
            asset_type=item.asset_type,
            origin=item.origin,
            queued_file_count=0,
        )

    monkeypatch.setattr(company_assets, "get_company_asset_catalog", lambda: catalog)
    monkeypatch.setattr(company_assets, "list_company_catalog_assets", fake_list)
    monkeypatch.setattr(company_assets, "delete_company_catalog_asset", fake_delete)
    user = CurrentUserInfo(id="admin-1", sub="alice", role="admin")

    page = await company_assets.list_source_assets(
        user,
        asset_type="character",
        origin="official",
        q="测试",
        limit=24,
        offset=0,
    )
    deleted = await company_assets.delete_source_asset(item.id, user)

    assert page["items"][0]["name"] == "测试人物"
    assert deleted["queued_file_count"] == 0
    assert calls == [
        (
            "list",
            {
                "administrator": catalog,
                "user_id": "admin-1",
                "asset_type": "character",
                "origin": "official",
                "query": "测试",
                "limit": 24,
                "offset": 0,
            },
        ),
        (
            "delete",
            {"administrator": catalog, "user_id": "admin-1", "asset_id": item.id},
        ),
    ]
