from __future__ import annotations

import hashlib

import httpx
import pytest

from asset_sync_worker.models import SourceAsset, SourceFile, SourceSnapshot
from asset_sync_worker.sources.character_catalog_v1 import CharacterCatalogV1Adapter, CharacterSourceError
from asset_sync_worker.worker import AssetSyncWorker


@pytest.mark.unit
async def test_character_source_adapter_maps_current_catalog_shape_and_ignores_video() -> None:
    image = b"avatar"
    audio = b"voice"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/export"):
            assert request.headers["authorization"] == "Bearer source-token"
            assert request.headers["apikey"] == "source-token"
            return httpx.Response(
                200,
                json={
                    "schemaVersion": 1,
                    "publishVersion": {
                        "id": "release-7",
                        "name": "Release 7",
                        "activatedAt": "2026-08-29T00:00:00Z",
                    },
                    "characters": [
                        {
                            "id": "hero",
                            "name": "Hero",
                            "chineseName": "英雄",
                            "subtitle": "Lead",
                            "summary": "Main character",
                            "voice": {"ttsVoiceId": "voice-1"},
                            "assets": [
                                {
                                    "key": "avatarUrl",
                                    "relativePath": "hero/avatar.png",
                                    "url": "https://cdn.example/avatar.png",
                                    "mimeType": "image/png",
                                    "byteSize": len(image),
                                    "sha256": hashlib.sha256(image).hexdigest(),
                                    "revision": 2,
                                    "sourceFields": ["avatarUrl"],
                                },
                                {
                                    "key": "voice",
                                    "relativePath": "hero/voice.wav",
                                    "url": "https://cdn.example/voice.wav",
                                    "mimeType": "audio/wav",
                                    "byteSize": len(audio),
                                    "sha256": hashlib.sha256(audio).hexdigest(),
                                    "sourceFields": ["voice"],
                                },
                                {
                                    "key": "preview",
                                    "relativePath": "hero/preview.mp4",
                                    "url": "https://cdn.example/preview.mp4",
                                    "mimeType": "video/mp4",
                                },
                            ],
                        }
                    ],
                },
            )
        if request.url.path.endswith("avatar.png"):
            return httpx.Response(200, content=image)
        return httpx.Response(200, content=audio)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CharacterCatalogV1Adapter(client=client)
        snapshot = await adapter.fetch(
            endpoint="https://source.example/export",
            token="source-token",
        )
        character = snapshot.assets[0]
        downloaded = [await adapter.download(file) for file in character.files]

    assert snapshot.cursor == {"publish_version": "release-7", "activated_at": "2026-08-29T00:00:00Z"}
    assert character.source_key == "hero"
    assert character.name == "英雄"
    assert character.aliases == ("Hero", "Lead")
    assert character.voice_id == "voice-1"
    assert [(item.role, item.media_type) for item in character.files] == [
        ("primary_image", "image"),
        ("reference_audio", "audio"),
    ]
    assert downloaded == [image, audio]
    assert len(character.fingerprint) == 64


@pytest.mark.unit
async def test_character_source_adapter_classifies_upstream_authorization_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CharacterCatalogV1Adapter(client=client)
        with pytest.raises(CharacterSourceError, match="asset_source_upstream_unauthorized"):
            await adapter.fetch(endpoint="https://source.example/export", token="expired-token")


@pytest.mark.unit
async def test_monitor_run_imports_changed_assets_archives_missing_and_reports_success(tmp_path) -> None:
    file_path = tmp_path / "hero.png"
    file_path.write_bytes(b"hero")
    source_file = SourceFile(
        key="avatarUrl",
        role="primary_image",
        media_type="image",
        mime_type="image/png",
        url="https://cdn.example/hero.png",
        relative_path="hero.png",
        byte_size=4,
        sha256=None,
        revision="1",
        sort_order=0,
        source_fields=("avatarUrl",),
    )
    source_asset = SourceAsset(
        source_key="hero",
        asset_type="character",
        name="Hero",
        description="lead",
        voice_style="",
        voice_id=None,
        aliases=(),
        files=(source_file,),
        fingerprint="f" * 64,
    )

    class _Adapter:
        async def fetch(self, *, endpoint, token):
            assert endpoint == "https://source.example/export"
            assert token == "source-secret"
            return SourceSnapshot(cursor={"publish_version": "v1"}, assets=(source_asset,))

        async def download(self, file):
            assert file is source_file
            return b"hero"

    class _Client:
        uploads = []
        imports = []
        reports = []

        async def claim_asset_file_deletion(self, worker_id):
            assert worker_id == "worker-1"
            return None

        async def claim_run(self, worker_id):
            assert worker_id == "worker-1"
            return {
                "run": {"id": "run-1"},
                "source": {
                    "source_key": "existing-character-catalog",
                    "adapter": "character_catalog_v1",
                    "source_config": {"endpoint": "https://source.example/export"},
                },
            }

        async def heartbeat(self, run_id, worker_id):
            return "running"

        async def official_asset_state(self, source_key, source_asset_key):
            return None

        async def upload_official_file(self, object_path, payload, mime_type):
            self.uploads.append((object_path, payload, mime_type))

        async def import_official_asset(self, **kwargs):
            self.imports.append(kwargs)
            return {"outcome": "added", "asset_id": kwargs["asset_id"], "version": 1}

        async def archive_missing(self, source_key, seen_source_keys):
            assert seen_source_keys == ["hero"]
            return 2

        async def report_run(self, **kwargs):
            self.reports.append(kwargs)

        async def delete_object(self, object_path):
            raise AssertionError(f"unexpected cleanup: {object_path}")

    client = _Client()
    worker = AssetSyncWorker(
        client=client,
        worker_id="worker-1",
        source_tokens={"existing-character-catalog": "source-secret"},
        adapters={"character_catalog_v1": _Adapter()},
    )

    worked = await worker.run_once()

    assert worked is True
    assert len(client.uploads) == 1
    assert client.uploads[0][1] == b"hero"
    assert client.imports[0]["snapshot"]["name"] == "Hero"
    assert client.imports[0]["snapshot"]["files"][0]["sha256"] == hashlib.sha256(b"hero").hexdigest()
    assert client.reports == [
        {
            "run_id": "run-1",
            "worker_id": "worker-1",
            "status": "succeeded",
            "cursor": {"publish_version": "v1"},
            "imported_count": 1,
            "updated_count": 0,
            "unchanged_count": 0,
            "archived_count": 2,
            "seen_source_keys": ["hero"],
            "error_code": None,
            "error_detail": None,
        }
    ]


@pytest.mark.unit
async def test_monitor_worker_drains_a_storage_deletion_before_source_sync() -> None:
    class _Client:
        reports = []

        async def claim_asset_file_deletion(self, worker_id):
            assert worker_id == "worker-1"
            return {
                "id": 17,
                "bucket_id": "arcreel-assets",
                "object_path": "shared/user/test/version/avatar.png",
            }

        async def delete_object(self, object_path):
            assert object_path == "shared/user/test/version/avatar.png"

        async def report_asset_file_deletion(self, **kwargs):
            self.reports.append(kwargs)

        async def claim_run(self, worker_id):
            raise AssertionError(f"source sync must wait until the cleanup queue is drained: {worker_id}")

    client = _Client()
    worker = AssetSyncWorker(
        client=client,
        worker_id="worker-1",
        source_tokens={},
        adapters={},
    )

    worked = await worker.run_once()

    assert worked is True
    assert client.reports == [
        {
            "deletion_id": 17,
            "worker_id": "worker-1",
            "succeeded": True,
            "error": None,
        }
    ]
