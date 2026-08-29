from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.company_assets import (
    COMPANY_ASSET_SOURCE,
    CompanyAsset,
    CompanyAssetAdminItem,
    CompanyAssetAdminPage,
    CompanyAssetChange,
    CompanyAssetDeleteResult,
    CompanyAssetFile,
    CompanyAssetPage,
    CompanyAssetPublishResult,
    delete_company_catalog_asset,
    list_company_catalog_assets,
    publish_local_asset,
    sync_company_assets,
)
from lib.db.repositories.asset_repo import AssetRepository
from lib.db.repositories.asset_resource_repo import AssetResourceRepository
from lib.db.repositories.company_asset_checkpoint_repo import CompanyAssetCheckpointRepository
from lib.project_manager import ProjectManager


class _Catalog:
    def __init__(self, pages: dict[tuple[str, int], CompanyAssetPage], files: dict[str, bytes]) -> None:
        self.pages = pages
        self.files = files
        self.pull_calls: list[tuple[tuple[str, ...], int]] = []
        self.download_calls: list[str] = []

    async def pull_changes(
        self,
        *,
        user_id: str,
        asset_types: tuple[str, ...],
        after: int,
        limit: int = 100,
    ) -> CompanyAssetPage:
        del user_id, limit
        self.pull_calls.append((asset_types, after))
        assert len(asset_types) == 1
        return self.pages[(asset_types[0], after)]

    async def download_file(self, *, user_id: str, file: CompanyAssetFile) -> bytes:
        del user_id
        self.download_calls.append(file.object_path)
        return self.files[file.object_path]


@pytest.mark.unit
async def test_company_catalog_admin_operations_share_one_typed_boundary() -> None:
    item = CompanyAssetAdminItem(
        id="6bf51491-016c-42ed-bd35-458ca670b4f4",
        asset_type="character",
        origin="official",
        status="published",
        version=2,
        name="鳄鱼爸爸",
        description="温和的父亲",
        owner_name=None,
        source_name="人物资产渠道",
        files=(),
        created_at="2026-08-29T00:00:00Z",
        updated_at="2026-08-29T01:00:00Z",
    )
    expected_page = CompanyAssetAdminPage(
        items=(item,),
        total=1,
        totals={"character": 1, "scene": 0, "prop": 0},
    )
    calls: list[tuple[str, dict]] = []

    class _Administrator:
        async def list_assets(self, **kwargs):
            calls.append(("list", kwargs))
            return expected_page

        async def delete_asset(self, **kwargs):
            calls.append(("delete", kwargs))
            return CompanyAssetDeleteResult(
                asset_id=item.id,
                name=item.name,
                asset_type=item.asset_type,
                origin=item.origin,
                queued_file_count=2,
            )

        async def download_asset_preview(self, **kwargs):
            raise AssertionError(kwargs)

    administrator = _Administrator()
    page = await list_company_catalog_assets(
        administrator=administrator,
        user_id="local-admin",
        asset_type="character",
        origin="official",
        query="鳄鱼",
        limit=24,
        offset=0,
    )
    deleted = await delete_company_catalog_asset(
        administrator=administrator,
        user_id="local-admin",
        asset_id=item.id,
    )

    assert page is expected_page
    assert deleted.queued_file_count == 2
    assert calls == [
        (
            "list",
            {
                "user_id": "local-admin",
                "asset_type": "character",
                "origin": "official",
                "query": "鳄鱼",
                "limit": 24,
                "offset": 0,
            },
        ),
        ("delete", {"user_id": "local-admin", "asset_id": item.id}),
    ]


@pytest.mark.unit
async def test_company_catalog_agent_tools_use_the_shared_admin_operations(tmp_path, monkeypatch) -> None:
    from server.agent_runtime.sdk_tools import company_assets as tools_module
    from server.agent_runtime.sdk_tools._context import ToolContext
    from server.agent_runtime.sdk_tools.company_assets import (
        delete_company_catalog_asset_tool,
        list_company_catalog_assets_tool,
    )

    asset_id = "6bf51491-016c-42ed-bd35-458ca670b4f4"
    catalog = object()
    calls = []

    async def fake_list(**kwargs):
        calls.append(("list", kwargs))
        return CompanyAssetAdminPage(
            items=(
                CompanyAssetAdminItem(
                    id=asset_id,
                    asset_type="prop",
                    origin="user_shared",
                    status="published",
                    version=1,
                    name="测试道具",
                    description="",
                    owner_name="Alice",
                    source_name=None,
                    files=(),
                    created_at="2026-08-29T00:00:00Z",
                    updated_at="2026-08-29T00:00:00Z",
                ),
            ),
            total=1,
            totals={"character": 0, "scene": 0, "prop": 1},
        )

    async def fake_delete(**kwargs):
        calls.append(("delete", kwargs))
        return CompanyAssetDeleteResult(
            asset_id=asset_id,
            name="测试道具",
            asset_type="prop",
            origin="user_shared",
            queued_file_count=1,
        )

    monkeypatch.setattr(tools_module, "get_company_asset_catalog", lambda: catalog)
    monkeypatch.setattr(tools_module, "list_company_catalog_assets", fake_list)
    monkeypatch.setattr(tools_module, "delete_company_catalog_asset", fake_delete)
    ctx = ToolContext(project_name="demo", projects_root=tmp_path, user_id="admin-1")

    listed = await list_company_catalog_assets_tool(ctx).handler(
        {"asset_type": "prop", "origin": "user_shared", "query": "测试", "limit": 24, "offset": 0}
    )
    deleted = await delete_company_catalog_asset_tool(ctx).handler({"asset_id": asset_id})

    assert json.loads(listed["content"][0]["text"])["items"][0]["name"] == "测试道具"
    assert json.loads(deleted["content"][0]["text"])["queued_file_count"] == 1
    assert [call[0] for call in calls] == ["list", "delete"]


def _file(
    *,
    key: str,
    media_type: str,
    role: str,
    object_path: str,
    data: bytes,
    sort_order: int = 0,
) -> CompanyAssetFile:
    return CompanyAssetFile(
        id=f"file-{key}",
        key=key,
        role=role,
        media_type=media_type,
        mime_type="image/png" if media_type == "image" else "audio/wav",
        bucket_id="arcreel-assets",
        object_path=object_path,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        revision="1",
        sort_order=sort_order,
        source_fields=(key,),
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("asset_type", "primary_role"),
    (("character", "primary_image"), ("scene", "primary_image"), ("prop", "primary_image")),
)
async def test_sync_company_assets_materializes_only_the_requested_type(
    async_session,
    tmp_path: Path,
    asset_type: str,
    primary_role: str,
) -> None:
    image = f"{asset_type}-image".encode()
    image_file = _file(
        key="sheet",
        media_type="image",
        role=primary_role,
        object_path=f"shared/user/asset/version/{asset_type}.png",
        data=image,
    )
    files = (image_file,)
    if asset_type == "character":
        audio = b"character-audio"
        files += (
            _file(
                key="reference_audio",
                media_type="audio",
                role="reference_audio",
                object_path="shared/user/asset/version/voice.wav",
                data=audio,
                sort_order=1,
            ),
        )
    asset = CompanyAsset(
        id=f"company-{asset_type}",
        asset_type=asset_type,
        origin="user_shared",
        status="published",
        version=3,
        name=f"Shared {asset_type}",
        description="company description",
        voice_style="warm" if asset_type == "character" else "",
        voice_id="voice-1" if asset_type == "character" else None,
        owner_id="cloud-user",
        owner_name="Alice",
        aliases=(f"{asset_type} alias",),
        files=files,
    )
    page = CompanyAssetPage(
        changes=(CompanyAssetChange(revision=7, operation="upsert", asset=asset),),
        next_cursor=7,
        has_more=False,
    )
    payloads = {item.object_path: (image if item.media_type == "image" else b"character-audio") for item in files}
    catalog = _Catalog({(asset_type, 0): page}, payloads)

    result = await sync_company_assets(
        async_session,
        catalog=catalog,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=(asset_type,),
    )

    assert result == {
        "added": 1,
        "updated": 0,
        "archived": 0,
        "unchanged": 0,
        "assetsDownloaded": len(files),
    }
    assert catalog.pull_calls == [((asset_type,), 0)]
    local = await AssetRepository(async_session).get_by_external_identity(
        COMPANY_ASSET_SOURCE,
        asset.id,
    )
    assert local is not None
    assert local.type == asset_type
    assert local.external_origin == "user_shared"
    assert local.external_version == 3
    assert local.external_status == "published"
    assert local.external_owner_name == "Alice"
    assert local.image_path and local.image_path.startswith(f"_global_assets/{asset_type}/company/")
    assert (tmp_path / local.image_path).read_bytes() == image
    if asset_type == "character":
        assert local.audio_path and local.audio_path.startswith("_global_assets/character/company/")
        assert (tmp_path / local.audio_path).read_bytes() == b"character-audio"
    assert await CompanyAssetCheckpointRepository(async_session).get(COMPANY_ASSET_SOURCE, asset_type) == 7


@pytest.mark.unit
async def test_sync_company_assets_archives_without_deleting_the_local_copy(
    async_session,
    tmp_path: Path,
) -> None:
    repo = AssetRepository(async_session)
    local_path = "_global_assets/character/company/kept.png"
    (tmp_path / local_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / local_path).write_bytes(b"keep-me")
    local = await repo.create(
        type="character",
        name="Keep me",
        image_path=local_path,
        external_source=COMPANY_ASSET_SOURCE,
        external_id="company-character",
        external_origin="official",
        external_version=4,
        external_status="published",
    )
    await async_session.commit()
    page = CompanyAssetPage(
        changes=(
            CompanyAssetChange(
                revision=9,
                operation="archive",
                asset=CompanyAsset(
                    id="company-character",
                    asset_type="character",
                    origin="official",
                    status="archived",
                    version=4,
                    name="Keep me",
                    description="",
                    voice_style="",
                    voice_id=None,
                    owner_id=None,
                    owner_name=None,
                    aliases=(),
                    files=(),
                ),
            ),
        ),
        next_cursor=9,
        has_more=False,
    )
    catalog = _Catalog({("character", 0): page}, {})

    result = await sync_company_assets(
        async_session,
        catalog=catalog,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=("character",),
    )

    assert result["archived"] == 1
    refreshed = await repo.get_by_id(local.id)
    assert refreshed is not None
    assert refreshed.external_status == "archived"
    assert refreshed.image_path == local_path
    assert (tmp_path / local_path).read_bytes() == b"keep-me"


@pytest.mark.unit
async def test_sync_company_assets_updates_remote_owned_metadata(
    async_session,
    tmp_path: Path,
) -> None:
    repo = AssetRepository(async_session)
    local = await repo.create(
        type="character",
        name="Old company name",
        description="old description",
        voice_style="old voice",
        external_source=COMPANY_ASSET_SOURCE,
        external_id="company-character",
        external_origin="official",
        external_version=1,
        external_status="published",
        voice_id="old-voice-id",
    )
    await async_session.commit()
    page = CompanyAssetPage(
        changes=(
            CompanyAssetChange(
                revision=2,
                operation="upsert",
                asset=CompanyAsset(
                    id="company-character",
                    asset_type="character",
                    origin="official",
                    status="published",
                    version=2,
                    name="New company name",
                    description="new description",
                    voice_style="new voice",
                    voice_id="new-voice-id",
                    owner_id=None,
                    owner_name=None,
                    aliases=(),
                    files=(),
                ),
            ),
        ),
        next_cursor=2,
        has_more=False,
    )

    result = await sync_company_assets(
        async_session,
        catalog=_Catalog({("character", 0): page}, {}),
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=("character",),
    )

    refreshed = await repo.get_by_id(local.id)
    assert result["updated"] == 1
    assert refreshed is not None
    assert refreshed.name == "New company name"
    assert refreshed.description == "new description"
    assert refreshed.voice_style == "new voice"
    assert refreshed.voice_id == "new-voice-id"


@pytest.mark.unit
async def test_sync_company_assets_relocates_legacy_company_resources_into_the_asset_type_directory(
    async_session,
    tmp_path: Path,
) -> None:
    image = b"company-image"
    digest = hashlib.sha256(image).hexdigest()
    legacy_path = "_global_assets/company/local-character/sheet.png"
    (tmp_path / legacy_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / legacy_path).write_bytes(image)
    asset_repo = AssetRepository(async_session)
    local = await asset_repo.create(
        type="character",
        name="Company character",
        image_path=legacy_path,
        external_source=COMPANY_ASSET_SOURCE,
        external_id="company-character",
        external_origin="official",
        external_version=1,
        external_status="published",
    )
    remote_file = _file(
        key="sheet",
        media_type="image",
        role="primary_image",
        object_path="official/character/sheet.png",
        data=image,
    )
    await AssetResourceRepository(async_session).create(
        asset_id=local.id,
        resource_key="company:78af7bdb5626eb0a046772b3",
        origin="catalog",
        media_type="image",
        mime_type="image/png",
        path=legacy_path,
        source_url=None,
        sha256=digest,
        byte_size=len(image),
        revision="1",
        sort_order=0,
        source_fields_json='["primary_image","sheet"]',
    )
    await async_session.commit()
    remote = CompanyAsset(
        id="company-character",
        asset_type="character",
        origin="official",
        status="published",
        version=1,
        name="Company character",
        description="",
        voice_style="",
        voice_id=None,
        owner_id=None,
        owner_name=None,
        aliases=(),
        files=(remote_file,),
    )
    page = CompanyAssetPage(
        changes=(CompanyAssetChange(revision=1, operation="upsert", asset=remote),),
        next_cursor=1,
        has_more=False,
    )
    catalog = _Catalog({("character", 0): page}, {remote_file.object_path: image})

    result = await sync_company_assets(
        async_session,
        catalog=catalog,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=("character",),
    )

    refreshed = await asset_repo.get_by_id(local.id)
    assert refreshed is not None
    assert refreshed.image_path and refreshed.image_path.startswith("_global_assets/character/company/")
    assert (tmp_path / refreshed.image_path).read_bytes() == image
    assert not (tmp_path / legacy_path).exists()
    assert result["assetsDownloaded"] == 1


@pytest.mark.unit
async def test_sync_company_assets_restores_a_locally_deleted_asset_from_the_current_catalog_snapshot(
    async_session,
    tmp_path: Path,
) -> None:
    image = b"restored-image"
    remote_file = _file(
        key="avatarUrl",
        media_type="image",
        role="primary_image",
        object_path="official/character/avatar.png",
        data=image,
    )
    remote = CompanyAsset(
        id="company-character",
        asset_type="character",
        origin="official",
        status="published",
        version=1,
        name="Restored character",
        description="server snapshot",
        voice_style="",
        voice_id=None,
        owner_id=None,
        owner_name=None,
        aliases=("Restored",),
        files=(remote_file,),
    )
    await CompanyAssetCheckpointRepository(async_session).advance(COMPANY_ASSET_SOURCE, "character", 13)
    local_only = await AssetRepository(async_session).create(
        type="character",
        name="Local only",
        description="must not be removed by reconciliation",
    )
    await async_session.commit()

    class _ReconciliationCatalog:
        snapshot_calls: list[tuple[tuple[str, ...], str | None, int | None]] = []
        pull_calls: list[tuple[tuple[str, ...], int]] = []
        download_calls: list[str] = []

        async def pull_snapshot(
            self,
            *,
            user_id: str,
            asset_types: tuple[str, ...],
            after_id: str | None,
            snapshot_cursor: int | None,
            limit: int = 100,
        ):
            del user_id, limit
            self.snapshot_calls.append((asset_types, after_id, snapshot_cursor))
            return SimpleNamespace(
                assets=(remote,),
                snapshot_cursor=13,
                next_page_token=None,
                has_more=False,
            )

        async def pull_changes(
            self,
            *,
            user_id: str,
            asset_types: tuple[str, ...],
            after: int,
            limit: int = 100,
        ) -> CompanyAssetPage:
            del user_id, limit
            self.pull_calls.append((asset_types, after))
            return CompanyAssetPage(changes=(), next_cursor=after, has_more=False)

        async def download_file(self, *, user_id: str, file: CompanyAssetFile) -> bytes:
            del user_id
            self.download_calls.append(file.object_path)
            return image

    catalog = _ReconciliationCatalog()
    result = await sync_company_assets(
        async_session,
        catalog=catalog,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=("character",),
    )

    restored = await AssetRepository(async_session).get_by_external_identity(
        COMPANY_ASSET_SOURCE,
        remote.id,
    )
    assert restored is not None
    assert restored.name == "Restored character"
    assert restored.image_path and (tmp_path / restored.image_path).read_bytes() == image
    assert result["added"] == 1
    assert result["assetsDownloaded"] == 1
    assert catalog.snapshot_calls == [(("character",), None, None)]
    assert catalog.pull_calls == [(("character",), 13)]
    assert await AssetRepository(async_session).get_by_id(local_only.id) is not None

    second = await sync_company_assets(
        async_session,
        catalog=catalog,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_types=("character",),
    )

    assert second == {
        "added": 0,
        "updated": 0,
        "archived": 0,
        "unchanged": 1,
        "assetsDownloaded": 0,
    }
    assert catalog.download_calls == [remote_file.object_path]
    assert await AssetRepository(async_session).get_by_id(local_only.id) is not None


@pytest.mark.unit
@pytest.mark.parametrize("asset_type", ("character", "scene", "prop"))
async def test_publish_local_asset_uses_the_same_operation_for_all_supported_types(
    async_session,
    tmp_path: Path,
    asset_type: str,
) -> None:
    relative = f"_global_assets/{asset_type}/sheet.png"
    (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / relative).write_bytes(f"{asset_type}-sheet".encode())
    repo = AssetRepository(async_session)
    asset = await repo.create(
        type=asset_type,
        name=f"Local {asset_type}",
        description="shared description",
        voice_style="warm" if asset_type == "character" else "",
        image_path=relative,
        voice_id="voice-a" if asset_type == "character" else None,
    )
    await async_session.commit()

    class _Publisher:
        publication = None

        async def publish_asset(self, *, user_id, publication):
            assert user_id == "local-user"
            self.publication = publication
            return CompanyAssetPublishResult(
                asset_id="b47da8b5-b6a2-44d6-b4e0-30498f041eee",
                version_id="aee4012f-115f-4026-894e-ac0f454ba53b",
                version=1,
            )

    publisher = _Publisher()
    result = await publish_local_asset(
        async_session,
        publisher=publisher,
        manager=ProjectManager(tmp_path),
        user_id="local-user",
        asset_id=asset.id,
    )

    assert result.version == 1
    assert publisher.publication is not None
    assert publisher.publication.asset_type == asset_type
    assert publisher.publication.name == f"Local {asset_type}"
    assert [(item.role, item.media_type, item.path) for item in publisher.publication.files] == [
        ("primary_image", "image", tmp_path / relative)
    ]
    refreshed = await repo.get_by_id(asset.id)
    assert refreshed is not None
    assert refreshed.external_source == COMPANY_ASSET_SOURCE
    assert refreshed.external_origin == "user_shared"
    assert refreshed.external_version == 1


@pytest.mark.unit
async def test_publish_local_asset_rejects_an_official_asset(async_session, tmp_path: Path) -> None:
    asset = await AssetRepository(async_session).create(
        type="character",
        name="Official",
        external_source=COMPANY_ASSET_SOURCE,
        external_id="b47da8b5-b6a2-44d6-b4e0-30498f041eee",
        external_origin="official",
        external_version=1,
        external_status="published",
    )
    await async_session.commit()

    with pytest.raises(Exception, match="company_asset_official_read_only"):
        await publish_local_asset(
            async_session,
            publisher=object(),
            manager=ProjectManager(tmp_path),
            user_id="local-user",
            asset_id=asset.id,
        )
