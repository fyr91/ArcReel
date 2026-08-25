"""Release configuration bundle import/export tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from lib.config.service import ConfigService
from lib.config_bundle import (
    AgentCredentialBundle,
    ConfigBundleError,
    ProviderCredentialBundle,
    ReleaseConfigBundle,
    export_release_config_bundle,
    get_config_readiness,
    import_release_config_bundle,
    parse_config_bundle_env,
    render_config_bundle_env,
)
from lib.db import get_async_session
from lib.db.repositories.agent_credential_repo import AgentCredentialRepository
from lib.db.repositories.credential_repository import CredentialRepository
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
