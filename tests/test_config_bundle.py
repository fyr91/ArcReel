"""Release configuration bundle import/export tests."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lib.config.service import ConfigService
from lib.config_bundle import (
    AgentCredentialBundle,
    ConfigBundleError,
    CustomProviderBundle,
    CustomProviderModelBundle,
    ProviderCredentialBundle,
    ReleaseConfigBundle,
    export_release_config_bundle,
    get_config_readiness,
    import_release_config_bundle,
    parse_config_bundle_env,
    render_config_bundle_env,
    reset_project_environment_overrides,
    validate_release_config_bundle,
)
from lib.db import get_async_session
from lib.db.repositories.agent_credential_repo import AgentCredentialRepository
from lib.db.repositories.credential_repository import CredentialRepository
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.project_manager import ProjectManager
from server.routers import config_import

pytestmark = pytest.mark.unit


def _bundle() -> ReleaseConfigBundle:
    return ReleaseConfigBundle(
        version=1,
        agent=AgentCredentialBundle(
            preset_id="__custom__",
            display_name="Release Agent",
            base_url="https://agent.example.test/api",
            api_key="agent-secret",
            model="model-1",
        ),
        providers=[
            ProviderCredentialBundle(
                provider="ark-agent-plan",
                name="Release Channel",
                api_key="provider-secret",
                config={"image_max_workers": "2"},
            )
        ],
        system_settings={
            "croco_characters_api_url": "https://example.supabase.co/functions/v1/catalog",
            "croco_characters_api_token": "catalog-secret",
            "default_text_backend": "ark-agent-plan/deepseek-v4-pro",
        },
    )


def test_env_round_trip_keeps_secrets_out_of_plaintext() -> None:
    rendered = render_config_bundle_env(_bundle())
    assert "agent-secret" not in rendered
    assert "provider-secret" not in rendered
    parsed = parse_config_bundle_env(rendered)
    assert parsed == _bundle()


def test_env_requires_bundle_variable() -> None:
    with pytest.raises(ConfigBundleError, match="config_bundle_missing"):
        parse_config_bundle_env("AUTH_ENABLED=false\n")


@pytest.mark.asyncio
async def test_import_is_idempotent_and_becomes_ready(db_factory, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_IMPORT_ENABLED", "true")
    async with db_factory() as session:
        await import_release_config_bundle(session, _bundle())
        await session.commit()
        await import_release_config_bundle(session, _bundle())
        await session.commit()

        readiness = await get_config_readiness(session)
        assert readiness.ready is True
        assert readiness.issues == []

        provider_credentials = await CredentialRepository(session).list_by_provider("ark-agent-plan")
        assert len(provider_credentials) == 1
        assert provider_credentials[0].api_key == "provider-secret"
        assert provider_credentials[0].is_active is True

        agent_credentials = await AgentCredentialRepository(session).list_for_user()
        assert len(agent_credentials) == 1
        assert agent_credentials[0].api_key == "agent-secret"
        assert agent_credentials[0].is_active is True

        svc = ConfigService(session)
        assert await svc.get_setting("croco_characters_api_token") == "catalog-secret"
        assert (await svc.get_provider_config("ark-agent-plan"))["image_max_workers"] == "2"


@pytest.mark.asyncio
async def test_export_omits_user_progress_settings(db_factory) -> None:
    async with db_factory() as session:
        await import_release_config_bundle(session, _bundle())
        svc = ConfigService(session)
        await svc.set_setting("onboarding_seen", "true")
        await session.commit()

        exported = await export_release_config_bundle(session)

    assert exported.agent.api_key == "agent-secret"
    assert {provider.provider for provider in exported.providers} == {"ark-agent-plan"}
    assert "onboarding_seen" not in exported.system_settings


@pytest.mark.asyncio
async def test_upload_endpoint_imports_without_persisting_the_file(db_factory, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_IMPORT_ENABLED", "true")
    async with db_factory() as session:
        app = FastAPI()

        async def override_session():
            yield session

        app.dependency_overrides[get_async_session] = override_session
        app.include_router(config_import.router, prefix="/api/v1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/config-import/file",
                files={"file": (".env.release", render_config_bundle_env(_bundle()), "text/plain")},
            )

        assert response.status_code == 200
        assert response.json() == {"enabled": True, "ready": True, "issues": []}


@pytest.mark.asyncio
async def test_preview_endpoint_is_available_without_first_run_gate(db_factory, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_IMPORT_ENABLED", "false")
    monkeypatch.setattr("lib.config_bundle.count_projects_with_environment_overrides", lambda: 5)
    async with db_factory() as session:
        app = FastAPI()

        async def override_session():
            yield session

        app.dependency_overrides[get_async_session] = override_session
        app.include_router(config_import.router, prefix="/api/v1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/config-import/preview",
                files={"file": (".env.release", render_config_bundle_env(_bundle()), "text/plain")},
            )

        assert response.status_code == 200
        assert response.json() == {
            "version": 1,
            "builtin_providers": 1,
            "custom_providers": 0,
            "system_settings": 3,
            "projects_to_update": 5,
        }


@pytest.mark.asyncio
async def test_preview_endpoint_translates_semantic_validation_errors(db_factory, monkeypatch) -> None:
    monkeypatch.setenv("CONFIG_IMPORT_ENABLED", "false")
    invalid = _bundle().model_copy(
        update={"providers": [ProviderCredentialBundle(provider="unknown", name="Unknown", api_key="secret")]}
    )
    async with db_factory() as session:
        app = FastAPI()

        async def override_session():
            yield session

        app.dependency_overrides[get_async_session] = override_session
        app.include_router(config_import.router, prefix="/api/v1")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/config-import/preview",
                files={"file": (".env.release", render_config_bundle_env(invalid), "text/plain")},
            )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_replace_import_deactivates_absent_credentials_and_clears_stale_settings(db_factory) -> None:
    async with db_factory() as session:
        stale = await CredentialRepository(session).create("grok", "old", api_key="old-secret")
        assert stale.is_active is True
        svc = ConfigService(session)
        await svc.set_provider_config("grok", "image_max_workers", "7")
        await svc.set_setting("default_image_backend", "grok/grok-imagine-image")
        await svc.set_setting("onboarding_seen", "true")

        await import_release_config_bundle(session, _bundle(), replace_existing=True)
        await session.commit()

        assert await CredentialRepository(session).get_active("grok") is None
        assert await svc.get_provider_config("grok") == {}
        assert await svc.get_setting("default_image_backend", "") == ""
        # 非可移植的用户进度不属于环境替换范围。
        assert await svc.get_setting("onboarding_seen", "") == "true"


@pytest.mark.asyncio
async def test_v2_custom_provider_import_rewrites_dynamic_provider_id(db_factory) -> None:
    bundle = _bundle().model_copy(
        update={
            "version": 2,
            "custom_providers": [
                CustomProviderBundle(
                    source_id=99,
                    display_name="Deepseek",
                    discovery_format="openai",
                    base_url="https://deepseek.example/v1",
                    api_key="custom-secret",
                    models=[
                        CustomProviderModelBundle(
                            model_id="deepseek-chat",
                            display_name="DeepSeek Chat",
                            endpoint="openai-chat",
                            is_default=True,
                        )
                    ],
                )
            ],
            "system_settings": {**_bundle().system_settings, "default_text_backend": "custom-99/deepseek-chat"},
        }
    )

    async with db_factory() as session:
        await import_release_config_bundle(session, bundle, replace_existing=True)
        await session.commit()
        providers = await CustomProviderRepository(session).list_providers()
        assert len(providers) == 1
        target_id = providers[0].id
        assert providers[0].api_key == "custom-secret"
        assert await ConfigService(session).get_setting("default_text_backend") == f"custom-{target_id}/deepseek-chat"


def test_preview_validation_rejects_duplicate_custom_provider_ids() -> None:
    custom = CustomProviderBundle(
        source_id=1,
        display_name="One",
        discovery_format="openai",
        base_url="https://example.test/v1",
        api_key="secret",
    )
    bundle = _bundle().model_copy(update={"version": 2, "custom_providers": [custom, custom.model_copy()]})

    with pytest.raises(ConfigBundleError, match="config_bundle_custom_model_invalid"):
        validate_release_config_bundle(bundle)


def test_project_environment_reset_preserves_creative_content(tmp_path, monkeypatch) -> None:
    manager = ProjectManager(tmp_path)
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    original = {
        "title": "Keep me",
        "style": "film",
        "aspect_ratio": "16:9",
        "generation_mode": "storyboard",
        "characters": {"A": {"description": "hero"}},
        "video_backend": "old/video",
        "default_image_backend": "old/image",
        "image_provider_storyboard": "old/storyboard",
        "default_text_backend": "old/text",
        "audio_backend": "old/audio",
        "model_settings": {"old/image": {"resolution": "2K"}},
    }
    (project_dir / "project.json").write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr("lib.config.resolver.get_project_manager", lambda: manager)

    rollback = reset_project_environment_overrides()
    updated = manager.load_project_readonly("demo")
    assert updated["title"] == "Keep me"
    assert updated["characters"] == original["characters"]
    assert updated["aspect_ratio"] == "16:9"
    for key in (
        "video_backend",
        "default_image_backend",
        "image_provider_storyboard",
        "default_text_backend",
        "audio_backend",
        "model_settings",
    ):
        assert key not in updated

    rollback.restore()
    restored = manager.load_project_readonly("demo")
    for key, value in original.items():
        assert restored[key] == value


def test_project_environment_reset_rolls_back_all_prior_projects_on_failure(tmp_path, monkeypatch) -> None:
    manager = ProjectManager(tmp_path)
    originals: dict[str, dict] = {}
    for name in ("first", "second"):
        project_dir = tmp_path / name
        project_dir.mkdir()
        original = {"title": name, "default_image_backend": "old/image"}
        originals[name] = original
        (project_dir / "project.json").write_text(json.dumps(original), encoding="utf-8")

    real_update = manager.update_project
    failed_once = False

    def fail_second_once(project_name, mutate_fn):
        nonlocal failed_once
        if project_name == "second" and not failed_once:
            failed_once = True
            raise OSError("disk full")
        return real_update(project_name, mutate_fn)

    monkeypatch.setattr(manager, "update_project", fail_second_once)
    monkeypatch.setattr("lib.config.resolver.get_project_manager", lambda: manager)

    with pytest.raises(OSError, match="disk full"):
        reset_project_environment_overrides()

    for name, original in originals.items():
        restored = manager.load_project_readonly(name)
        assert restored["title"] == original["title"]
        assert restored["default_image_backend"] == original["default_image_backend"]
