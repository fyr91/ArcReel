"""Portable, versioned configuration bundles for first-run local setup."""

from __future__ import annotations

import base64
import json
import os
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import PROVIDER_REGISTRY
from lib.config.service import ConfigService
from lib.db.repositories.agent_credential_repo import AgentCredentialRepository
from lib.db.repositories.credential_repository import CredentialRepository

CONFIG_BUNDLE_ENV_KEY = "ARCREEL_CONFIG_BUNDLE"
CONFIG_BUNDLE_VERSION = 1
CONFIG_IMPORT_ENABLED_ENV_KEY = "CONFIG_IMPORT_ENABLED"

_ENABLED_VALUES = frozenset({"true", "1", "yes", "on"})
_REQUIRED_MEDIA_TYPES = ("image", "video", "text")

# Instance preferences that are portable between local installs. User progress and
# machine-specific paths are intentionally excluded.
PORTABLE_SYSTEM_SETTING_KEYS = frozenset(
    {
        "default_video_backend",
        "default_video_backend_i2v",
        "default_video_backend_r2v",
        "default_image_backend",
        "default_image_backend_t2i",
        "default_image_backend_i2i",
        "default_text_backend",
        "default_audio_backend",
        "narration_voice",
        "narration_speed",
        "video_generate_audio",
        "anthropic_model",
        "anthropic_default_haiku_model",
        "anthropic_default_opus_model",
        "anthropic_default_sonnet_model",
        "claude_code_subagent_model",
        "agent_session_cleanup_delay_seconds",
        "agent_max_concurrent_sessions",
        "croco_characters_api_url",
        "croco_characters_api_token",
        "text_backend_simple",
        "text_backend_complex",
        "model_settings",
    }
)


class ConfigBundleError(ValueError):
    """A safe, translatable configuration bundle validation failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ProviderCredentialBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    api_key: str | None = None
    base_url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    config: dict[str, str] = Field(default_factory=dict)

    @field_validator("provider", "name")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class AgentCredentialBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=4000)
    api_key: str = Field(min_length=1)
    model: str | None = Field(default=None, max_length=128)
    haiku_model: str | None = Field(default=None, max_length=128)
    sonnet_model: str | None = Field(default=None, max_length=128)
    opus_model: str | None = Field(default=None, max_length=128)
    subagent_model: str | None = Field(default=None, max_length=128)

    @field_validator("preset_id", "display_name", "base_url", "api_key")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class ReleaseConfigBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    agent: AgentCredentialBundle
    providers: list[ProviderCredentialBundle] = Field(default_factory=list, max_length=64)
    system_settings: dict[str, str] = Field(default_factory=dict)


class ConfigReadiness(BaseModel):
    enabled: bool
    ready: bool
    issues: list[str]


def is_config_import_enabled() -> bool:
    raw = os.environ.get(CONFIG_IMPORT_ENABLED_ENV_KEY, "false").strip().lower()
    return raw in _ENABLED_VALUES


def _encode_bundle(bundle: ReleaseConfigBundle) -> str:
    payload = json.dumps(
        bundle.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_bundle(raw: str) -> ReleaseConfigBundle:
    try:
        padding = "=" * (-len(raw) % 4)
        payload = base64.b64decode(raw + padding, altchars=b"-_", validate=True)
        data = json.loads(payload.decode("utf-8"))
        bundle = ReleaseConfigBundle.model_validate(data)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ConfigBundleError("config_bundle_invalid") from exc
    if bundle.version != CONFIG_BUNDLE_VERSION:
        raise ConfigBundleError("config_bundle_version_unsupported")
    return bundle


def parse_config_bundle_env(contents: str) -> ReleaseConfigBundle:
    """Parse a dotenv file without interpolation or executing shell syntax."""

    try:
        values = dotenv_values(stream=StringIO(contents), interpolate=False)
    except Exception as exc:
        raise ConfigBundleError("config_bundle_invalid") from exc
    raw = values.get(CONFIG_BUNDLE_ENV_KEY)
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigBundleError("config_bundle_missing")
    return _decode_bundle(raw.strip())


def render_config_bundle_env(bundle: ReleaseConfigBundle) -> str:
    return (
        "# ArcReel local release configuration bundle. Contains secrets.\n"
        "# Keep this file private and do not commit it to Git.\n"
        f"{CONFIG_BUNDLE_ENV_KEY}={_encode_bundle(bundle)}\n"
    )


def write_config_bundle_env(path: Path, bundle: ReleaseConfigBundle) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_config_bundle_env(bundle), encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)


def _validate_provider_bundle(provider: ProviderCredentialBundle) -> None:
    meta = PROVIDER_REGISTRY.get(provider.provider)
    if meta is None:
        raise ConfigBundleError("config_bundle_provider_unknown")
    if "credentials_path" in meta.required_keys:
        raise ConfigBundleError("config_bundle_file_credential_unsupported")

    allowed_config = set(meta.required_keys) | set(meta.optional_keys)
    if set(provider.config) - allowed_config:
        raise ConfigBundleError("config_bundle_provider_field_unknown")

    credential_values = {
        "api_key": provider.api_key,
        "access_key": provider.access_key,
        "secret_key": provider.secret_key,
    }
    secret_fields = [key for key in meta.required_keys if key in meta.secret_keys]
    groups = meta.credential_groups or ([secret_fields] if secret_fields else [])
    if groups and not any(all(credential_values.get(key) for key in group) for group in groups):
        raise ConfigBundleError("config_bundle_provider_credential_incomplete")
    required_config = set(meta.required_keys) - set(meta.secret_keys) - {"credentials_path"}
    if any(not provider.config.get(key, "").strip() for key in required_config):
        raise ConfigBundleError("config_bundle_provider_credential_incomplete")


async def export_release_config_bundle(session: AsyncSession) -> ReleaseConfigBundle:
    agent = await AgentCredentialRepository(session).get_active()
    if agent is None:
        raise ConfigBundleError("config_bundle_agent_missing")

    svc = ConfigService(session)
    all_provider_config = await svc.get_all_provider_configs()
    active_credentials = await CredentialRepository(session).get_active_credentials_bulk()
    if any(credential.credentials_path for credential in active_credentials.values()):
        raise ConfigBundleError("config_bundle_file_credential_unsupported")
    providers = [
        ProviderCredentialBundle(
            provider=provider_id,
            name=credential.name,
            api_key=credential.api_key,
            base_url=credential.base_url,
            access_key=credential.access_key,
            secret_key=credential.secret_key,
            config=all_provider_config.get(provider_id, {}),
        )
        for provider_id, credential in sorted(active_credentials.items())
    ]
    settings = await svc.get_all_settings()
    portable_settings = {key: value for key, value in settings.items() if key in PORTABLE_SYSTEM_SETTING_KEYS}
    return ReleaseConfigBundle(
        version=CONFIG_BUNDLE_VERSION,
        agent=AgentCredentialBundle(
            preset_id=agent.preset_id,
            display_name=agent.display_name,
            base_url=agent.base_url,
            api_key=agent.api_key,
            model=agent.model,
            haiku_model=agent.haiku_model,
            sonnet_model=agent.sonnet_model,
            opus_model=agent.opus_model,
            subagent_model=agent.subagent_model,
        ),
        providers=providers,
        system_settings=portable_settings,
    )


async def import_release_config_bundle(session: AsyncSession, bundle: ReleaseConfigBundle) -> None:
    if bundle.version != CONFIG_BUNDLE_VERSION:
        raise ConfigBundleError("config_bundle_version_unsupported")
    if set(bundle.system_settings) - PORTABLE_SYSTEM_SETTING_KEYS:
        raise ConfigBundleError("config_bundle_system_setting_unknown")
    for provider in bundle.providers:
        _validate_provider_bundle(provider)

    svc = ConfigService(session)
    provider_repo = CredentialRepository(session)
    for provider in bundle.providers:
        active = await provider_repo.get_active(provider.provider)
        if active is None:
            active = await provider_repo.create(
                provider=provider.provider,
                name=provider.name,
                api_key=provider.api_key,
                base_url=provider.base_url,
                access_key=provider.access_key,
                secret_key=provider.secret_key,
            )
        else:
            active.credentials_path = None
            await provider_repo.update(
                active.id,
                name=provider.name,
                api_key=provider.api_key,
                base_url=provider.base_url,
                access_key=provider.access_key,
                secret_key=provider.secret_key,
            )
        await provider_repo.activate(active.id, provider.provider)
        for key, value in provider.config.items():
            await svc.set_provider_config(provider.provider, key, value, flush=False)

    agent_repo = AgentCredentialRepository(session)
    active_agent = await agent_repo.get_active()
    agent_fields = bundle.agent.model_dump(exclude={"preset_id"})
    if active_agent is None:
        active_agent = await agent_repo.create(
            preset_id=bundle.agent.preset_id,
            **agent_fields,
        )
    else:
        await agent_repo.update(
            active_agent.id,
            preset_id=bundle.agent.preset_id,
            **agent_fields,
        )
    await agent_repo.set_active(active_agent.id)

    for key, value in bundle.system_settings.items():
        await svc.set_setting(key, value)


async def get_config_readiness(session: AsyncSession) -> ConfigReadiness:
    enabled = is_config_import_enabled()
    if not enabled:
        return ConfigReadiness(enabled=False, ready=True, issues=[])

    issues: list[str] = []
    if await AgentCredentialRepository(session).get_active() is None:
        issues.append("agent")

    svc = ConfigService(session)
    settings = await svc.get_all_settings()
    if (
        not settings.get("croco_characters_api_url", "").strip()
        or not settings.get("croco_characters_api_token", "").strip()
    ):
        issues.append("supabase")

    ready_media: set[str] = set()
    for status in await svc.get_all_providers_status():
        if status.status == "ready":
            ready_media.update(status.media_types)
    for media_type in _REQUIRED_MEDIA_TYPES:
        if media_type not in ready_media:
            issues.append(f"provider_{media_type}")

    return ConfigReadiness(enabled=True, ready=not issues, issues=issues)
