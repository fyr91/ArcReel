from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from lib.company_assets import CompanyAssetPublication, CompanyAssetPublicationFile, CompanyAssetSyncError
from server.services.arcreel_cloud import ArcReelCloudError
from server.services.company_asset_supabase import SupabaseCompanyAssetCatalog, get_company_asset_catalog


@pytest.mark.unit
async def test_supabase_catalog_maps_delta_and_downloads_authenticated_file() -> None:
    image = b"company-image"
    digest = hashlib.sha256(image).hexdigest()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/rpc/arcreel_pull_asset_changes"):
            return httpx.Response(
                200,
                json={
                    "changes": [
                        {
                            "revision": 12,
                            "operation": "upsert",
                            "asset": {
                                "id": "6bf51491-016c-42ed-bd35-458ca670b4f4",
                                "asset_type": "prop",
                                "origin": "user_shared",
                                "status": "published",
                                "version": 2,
                                "name": "Magic lamp",
                                "description": "gold",
                                "voice_style": "",
                                "voice_id": None,
                                "owner_id": "8156e216-6272-4fea-af43-c74735b3ca6f",
                                "owner_name": "Alice",
                                "aliases": ["Lamp"],
                                "files": [
                                    {
                                        "id": "f39f2caa-1364-4010-b1eb-b213614ae87c",
                                        "key": "sheet",
                                        "role": "primary_image",
                                        "media_type": "image",
                                        "mime_type": "image/png",
                                        "bucket_id": "arcreel-assets",
                                        "object_path": "shared/alice/asset/version/lamp.png",
                                        "byte_size": len(image),
                                        "sha256": digest,
                                        "revision": "2",
                                        "sort_order": 0,
                                        "source_fields": ["prop_sheet"],
                                    }
                                ],
                            },
                        }
                    ],
                    "next_cursor": 12,
                    "has_more": False,
                },
            )
        return httpx.Response(200, content=image)

    async def token_provider(user_id: str) -> str:
        assert user_id == "local-user"
        return "access-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            client=client,
        )
        page = await catalog.pull_changes(
            user_id="local-user",
            asset_types=("prop",),
            after=7,
            limit=50,
        )
        payload = await catalog.download_file(user_id="local-user", file=page.changes[0].asset.files[0])

    assert page.next_cursor == 12
    assert page.has_more is False
    assert page.changes[0].asset.name == "Magic lamp"
    assert payload == image
    assert requests[0].headers["authorization"] == "Bearer access-token"
    assert requests[0].headers["apikey"] == "publishable-key"
    assert requests[0].read() == b'{"p_asset_types":["prop"],"p_after":7,"p_limit":50}'
    assert requests[1].url.path.endswith(
        "/storage/v1/object/authenticated/arcreel-assets/shared/alice/asset/version/lamp.png"
    )


@pytest.mark.unit
async def test_supabase_catalog_maps_a_missing_cloud_session_to_a_catalog_error() -> None:
    async def token_provider(_user_id: str) -> str:
        raise ArcReelCloudError("请重新登录", status_code=401, code="CLOUD_SESSION_MISSING")

    catalog = SupabaseCompanyAssetCatalog(
        base_url="https://cloud.example",
        publishable_key="publishable-key",
        token_provider=token_provider,
    )

    with pytest.raises(CompanyAssetSyncError) as raised:
        await catalog.pull_changes(
            user_id="local-user",
            asset_types=("character",),
            after=0,
        )

    assert raised.value.code == "company_asset_request_failed"
    assert raised.value.detail == "CLOUD_SESSION_MISSING"


@pytest.mark.unit
def test_supabase_catalog_factory_maps_an_incomplete_cloud_override(monkeypatch) -> None:
    monkeypatch.setenv("ARCREEL_CLOUD_AUTH_URL", "https://cloud.example/functions/v1/arcreel-auth")
    monkeypatch.delenv("ARCREEL_CLOUD_PUBLISHABLE_KEY", raising=False)

    with pytest.raises(CompanyAssetSyncError) as raised:
        get_company_asset_catalog()

    assert raised.value.code == "company_asset_cloud_not_configured"
    assert raised.value.detail == "ARCREEL_CLOUD_CONFIG_INVALID"


@pytest.mark.unit
async def test_supabase_catalog_maps_a_missing_ca_bundle_to_a_catalog_error(monkeypatch, tmp_path) -> None:
    async def token_provider(_user_id: str) -> str:
        return "access-token"

    monkeypatch.setenv("ARCREEL_CLOUD_CA_BUNDLE", str(tmp_path / "missing-ca.crt"))
    catalog = SupabaseCompanyAssetCatalog(
        base_url="https://47.108.223.84:50002",
        publishable_key="publishable-key",
        token_provider=token_provider,
    )

    with pytest.raises(CompanyAssetSyncError) as raised:
        await catalog.pull_changes(
            user_id="local-user",
            asset_types=("character",),
            after=0,
        )

    assert raised.value.code == "company_asset_request_failed"
    assert raised.value.detail == "ARCREEL_CLOUD_CONFIG_INVALID"


@pytest.mark.unit
async def test_supabase_catalog_maps_a_stable_current_asset_snapshot_page() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "assets": [
                    {
                        "id": "6bf51491-016c-42ed-bd35-458ca670b4f4",
                        "asset_type": "character",
                        "origin": "official",
                        "status": "published",
                        "version": 2,
                        "name": "鳄鱼爸爸",
                        "description": "温和的父亲",
                        "voice_style": "",
                        "voice_id": "voice-1",
                        "owner_id": None,
                        "owner_name": None,
                        "aliases": ["Croco Dad", "Father"],
                        "files": [
                            {
                                "id": "f39f2caa-1364-4010-b1eb-b213614ae87c",
                                "key": "avatarUrl",
                                "role": "primary_image",
                                "media_type": "image",
                                "mime_type": "image/png",
                                "bucket_id": "arcreel-assets",
                                "object_path": "official/characters/croco/avatar.png",
                                "byte_size": 6,
                                "sha256": hashlib.sha256(b"avatar").hexdigest(),
                                "revision": "2",
                                "sort_order": 0,
                                "source_fields": ["avatarUrl"],
                            },
                            {
                                "id": "ab49faaa-2c1e-431b-9307-ae246018d691",
                                "key": "voice",
                                "role": "reference_audio",
                                "media_type": "audio",
                                "mime_type": "audio/wav",
                                "bucket_id": "arcreel-assets",
                                "object_path": "official/characters/croco/voice.wav",
                                "byte_size": 5,
                                "sha256": hashlib.sha256(b"voice").hexdigest(),
                                "revision": "1",
                                "sort_order": 1,
                                "source_fields": ["voice"],
                            },
                        ],
                    }
                ],
                "snapshot_cursor": 13,
                "next_page_token": "6bf51491-016c-42ed-bd35-458ca670b4f4",
                "has_more": True,
            },
        )

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            client=client,
        )
        page = await catalog.pull_snapshot(
            user_id="local-user",
            asset_types=("character",),
            after_id=None,
            snapshot_cursor=None,
            limit=50,
        )

    assert page.snapshot_cursor == 13
    assert page.next_page_token == "6bf51491-016c-42ed-bd35-458ca670b4f4"
    assert page.has_more is True
    assert page.assets[0].name == "鳄鱼爸爸"
    assert page.assets[0].aliases == ("Croco Dad", "Father")
    assert [(item.media_type, item.role) for item in page.assets[0].files] == [
        ("image", "primary_image"),
        ("audio", "reference_audio"),
    ]
    assert requests[0].url.path.endswith("/rpc/arcreel_pull_asset_snapshot")
    assert requests[0].read() == (
        b'{"p_asset_types":["character"],"p_after_id":null,"p_snapshot_cursor":null,"p_limit":50}'
    )


@pytest.mark.unit
async def test_supabase_catalog_rejects_untrusted_file_coordinates() -> None:
    async def token_provider(_user_id: str) -> str:
        return "access-token"

    catalog = SupabaseCompanyAssetCatalog(
        base_url="https://cloud.example",
        publishable_key="publishable-key",
        token_provider=token_provider,
    )
    with pytest.raises(ValueError):
        catalog._storage_url("arcreel-assets", "../secrets")


@pytest.mark.unit
async def test_supabase_catalog_uploads_then_finalizes_a_publication(tmp_path) -> None:
    source = tmp_path / "scene.png"
    source.write_bytes(b"scene")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/rpc/arcreel_publish_asset"):
            return httpx.Response(
                200,
                json={
                    "asset_id": "028f7edb-0848-4aef-95b8-cc7352baf6ab",
                    "version_id": "7ac5cc93-ae2d-4551-bc1d-671613907c83",
                    "version": 3,
                },
            )
        return httpx.Response(200, json={"Key": request.url.path})

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async def identity_provider(_user_id: str) -> str:
        return "f18dfa5e-15f4-43e1-a19c-7617db84f645"

    publication = CompanyAssetPublication(
        asset_id="028f7edb-0848-4aef-95b8-cc7352baf6ab",
        version_id="7ac5cc93-ae2d-4551-bc1d-671613907c83",
        client_asset_id="df24cc9b-e45e-46de-aaf5-c57c5101819c",
        asset_type="scene",
        name="Office",
        description="daylight",
        voice_style="",
        voice_id=None,
        aliases=("Studio",),
        files=(
            CompanyAssetPublicationFile(
                key="primary_image",
                role="primary_image",
                media_type="image",
                mime_type="image/png",
                path=source,
                byte_size=5,
                sha256=hashlib.sha256(b"scene").hexdigest(),
                revision=None,
                sort_order=0,
                source_fields=("scene_sheet",),
            ),
        ),
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            identity_provider=identity_provider,
            client=client,
        )
        result = await catalog.publish_asset(user_id="local-user", publication=publication)

    assert result.version == 3
    assert requests[0].method == "POST"
    assert requests[0].headers["content-type"] == "image/png"
    assert requests[0].read() == b"scene"
    assert requests[0].url.path.endswith(
        "/storage/v1/object/arcreel-assets/shared/f18dfa5e-15f4-43e1-a19c-7617db84f645/"
        "028f7edb-0848-4aef-95b8-cc7352baf6ab/7ac5cc93-ae2d-4551-bc1d-671613907c83/"
        "000-primary_image.png"
    )
    assert requests[1].url.path.endswith("/rpc/arcreel_publish_asset")
    assert result.owner_id == "f18dfa5e-15f4-43e1-a19c-7617db84f645"


@pytest.mark.unit
async def test_supabase_catalog_rejects_another_users_asset_before_upload(tmp_path) -> None:
    source = tmp_path / "scene.png"
    source.write_bytes(b"scene")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async def identity_provider(_user_id: str) -> str:
        return "f18dfa5e-15f4-43e1-a19c-7617db84f645"

    publication = CompanyAssetPublication(
        asset_id="028f7edb-0848-4aef-95b8-cc7352baf6ab",
        version_id="7ac5cc93-ae2d-4551-bc1d-671613907c83",
        client_asset_id="df24cc9b-e45e-46de-aaf5-c57c5101819c",
        asset_type="scene",
        name="Office",
        description="daylight",
        voice_style="",
        voice_id=None,
        aliases=(),
        files=(
            CompanyAssetPublicationFile(
                key="primary_image",
                role="primary_image",
                media_type="image",
                mime_type="image/png",
                path=source,
                byte_size=5,
                sha256=hashlib.sha256(b"scene").hexdigest(),
                revision=None,
                sort_order=0,
            ),
        ),
        owner_id="8156e216-6272-4fea-af43-c74735b3ca6f",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            identity_provider=identity_provider,
            client=client,
        )
        with pytest.raises(CompanyAssetSyncError) as raised:
            await catalog.publish_asset(user_id="local-user", publication=publication)

    assert raised.value.code == "company_asset_not_owned"
    assert requests == []


@pytest.mark.unit
async def test_supabase_catalog_maps_rpc_ownership_denial_and_cleans_uploaded_files(tmp_path) -> None:
    source = tmp_path / "scene.png"
    source.write_bytes(b"scene")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/rpc/arcreel_publish_asset"):
            return httpx.Response(403, json={"code": "42501", "message": "ARCREEL_ASSET_NOT_OWNED"})
        return httpx.Response(200, json={})

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async def identity_provider(_user_id: str) -> str:
        return "f18dfa5e-15f4-43e1-a19c-7617db84f645"

    publication = CompanyAssetPublication(
        asset_id="028f7edb-0848-4aef-95b8-cc7352baf6ab",
        version_id="7ac5cc93-ae2d-4551-bc1d-671613907c83",
        client_asset_id="df24cc9b-e45e-46de-aaf5-c57c5101819c",
        asset_type="scene",
        name="Office",
        description="daylight",
        voice_style="",
        voice_id=None,
        aliases=(),
        files=(
            CompanyAssetPublicationFile(
                key="primary_image",
                role="primary_image",
                media_type="image",
                mime_type="image/png",
                path=source,
                byte_size=5,
                sha256=hashlib.sha256(b"scene").hexdigest(),
                revision=None,
                sort_order=0,
            ),
        ),
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            identity_provider=identity_provider,
            client=client,
        )
        with pytest.raises(CompanyAssetSyncError) as raised:
            await catalog.publish_asset(user_id="local-user", publication=publication)

    assert raised.value.code == "company_asset_not_owned"
    assert [request.method for request in requests] == ["POST", "POST", "DELETE"]


@pytest.mark.unit
async def test_supabase_catalog_rejects_same_size_file_replacement_before_upload(tmp_path) -> None:
    source = tmp_path / "scene.png"
    source.write_bytes(b"after")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async def identity_provider(_user_id: str) -> str:
        return "f18dfa5e-15f4-43e1-a19c-7617db84f645"

    publication = CompanyAssetPublication(
        asset_id="028f7edb-0848-4aef-95b8-cc7352baf6ab",
        version_id="7ac5cc93-ae2d-4551-bc1d-671613907c83",
        client_asset_id="df24cc9b-e45e-46de-aaf5-c57c5101819c",
        asset_type="scene",
        name="Office",
        description="daylight",
        voice_style="",
        voice_id=None,
        aliases=(),
        files=(
            CompanyAssetPublicationFile(
                key="primary_image",
                role="primary_image",
                media_type="image",
                mime_type="image/png",
                path=source,
                byte_size=5,
                sha256=hashlib.sha256(b"before").hexdigest(),
                revision=None,
                sort_order=0,
            ),
        ),
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            identity_provider=identity_provider,
            client=client,
        )
        with pytest.raises(CompanyAssetSyncError) as raised:
            await catalog.publish_asset(user_id="local-user", publication=publication)

    assert raised.value.code == "company_asset_file_changed"
    assert requests == []


@pytest.mark.unit
async def test_supabase_catalog_lists_deletes_and_previews_admin_assets() -> None:
    requests: list[httpx.Request] = []
    asset_id = "6bf51491-016c-42ed-bd35-458ca670b4f4"
    image_path = f"official/characters/{asset_id}/version/avatar.png"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/rpc/arcreel_admin_list_assets"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": asset_id,
                            "asset_type": "character",
                            "origin": "official",
                            "status": "published",
                            "version": 2,
                            "name": "鳄鱼爸爸",
                            "description": "温和的父亲",
                            "owner_name": None,
                            "source_name": "人物资产渠道",
                            "created_at": "2026-08-29T00:00:00Z",
                            "updated_at": "2026-08-29T01:00:00Z",
                            "files": [
                                {
                                    "id": "f39f2caa-1364-4010-b1eb-b213614ae87c",
                                    "key": "avatarUrl",
                                    "role": "primary_image",
                                    "media_type": "image",
                                    "mime_type": "image/png",
                                    "bucket_id": "arcreel-assets",
                                    "object_path": image_path,
                                    "byte_size": 6,
                                    "sha256": hashlib.sha256(b"avatar").hexdigest(),
                                    "revision": "2",
                                    "sort_order": 0,
                                    "source_fields": ["avatarUrl"],
                                }
                            ],
                        }
                    ],
                    "total": 1,
                    "totals": {"character": 1, "scene": 0, "prop": 0},
                },
            )
        if request.url.path.endswith("/rpc/arcreel_admin_get_asset_preview"):
            return httpx.Response(
                200,
                json={"bucket_id": "arcreel-assets", "object_path": image_path, "mime_type": "image/png"},
            )
        if request.url.path.endswith("/rpc/arcreel_admin_delete_asset"):
            return httpx.Response(
                200,
                json={
                    "asset_id": asset_id,
                    "name": "鳄鱼爸爸",
                    "asset_type": "character",
                    "origin": "official",
                    "queued_file_count": 1,
                },
            )
        return httpx.Response(200, content=b"avatar", headers={"content-type": "image/png"})

    async def token_provider(_user_id: str) -> str:
        return "access-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = SupabaseCompanyAssetCatalog(
            base_url="https://cloud.example",
            publishable_key="publishable-key",
            token_provider=token_provider,
            client=client,
        )
        page = await catalog.list_assets(
            user_id="local-admin",
            asset_type="character",
            origin="official",
            query="鳄鱼",
            limit=24,
            offset=0,
        )
        preview = await catalog.download_asset_preview(user_id="local-admin", asset_id=asset_id)
        deleted = await catalog.delete_asset(user_id="local-admin", asset_id=asset_id)

    assert page.total == 1
    assert page.items[0].name == "鳄鱼爸爸"
    assert page.items[0].files[0].role == "primary_image"
    assert preview.content == b"avatar"
    assert preview.mime_type == "image/png"
    assert deleted.queued_file_count == 1
    assert json.loads(requests[0].read()) == {
        "p_asset_type": "character",
        "p_origin": "official",
        "p_query": "鳄鱼",
        "p_limit": 24,
        "p_offset": 0,
    }
    assert requests[1].url.path.endswith("/rpc/arcreel_admin_get_asset_preview")
    assert requests[2].url.path.endswith(f"/storage/v1/object/authenticated/arcreel-assets/{image_path}")
    assert requests[3].url.path.endswith("/rpc/arcreel_admin_delete_asset")
