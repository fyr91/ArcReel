"""Portable, versioned configuration bundles for first-run local setup."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.config.registry import PROVIDER_REGISTRY
from lib.config.service import (
    DEFAULT_AGENT_MAX_CONCURRENT_SESSIONS,
    MAX_AGENT_MAX_CONCURRENT_SESSIONS,
    MIN_AGENT_MAX_CONCURRENT_SESSIONS,
    ConfigService,
)
from lib.db.models.credential import ProviderCredential
from lib.db.repositories.agent_credential_repo import AgentCredentialRepository
from lib.db.repositories.credential_repository import CredentialRepository
from lib.db.repositories.custom_provider_repo import CustomProviderRepository

CONFIG_BUNDLE_ENV_KEY = "ARCREEL_CONFIG_BUNDLE"
CONFIG_BUNDLE_VERSION = 2
CONFIG_IMPORT_ENABLED_ENV_KEY = "CONFIG_IMPORT_ENABLED"

_ENABLED_VALUES = frozenset({"true", "1", "yes", "on"})
_REQUIRED_MEDIA_TYPES = ("image", "video", "text")

# 项目中会随运行环境切换的覆盖项。创作事实（内容、风格、画幅、路线、时长、素材）不在此列；
# 导入新环境只清掉这些执行配置，让项目重新继承导入后的系统默认。
PROJECT_ENVIRONMENT_OVERRIDE_KEYS = frozenset(
    {
        "video_backend",
        "video_provider_i2v",
        "video_provider_r2v",
        "default_image_backend",
        "image_provider_t2i",
        "image_provider_i2i",
        "image_provider_asset",
        "image_provider_reference",
        "image_provider_storyboard",
        "image_provider_keyframe",
        "default_text_backend",
        "text_backend_simple",
        "text_backend_complex",
        "audio_backend",
        "video_generate_audio",
        "narration_voice",
        "narration_speed",
        "model_settings",
        # 旧版分辨率覆盖；新环境导入后不得继续压过新的 model_settings。
        "video_model_settings",
    }
)

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


class CustomProviderModelBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=32)
    is_default: bool = False
    is_enabled: bool = True
    price_unit: str | None = None
    price_input: float | None = None
    price_output: float | None = None
    currency: str | None = None
    supported_durations: list[int] | None = None
    resolution: str | None = None
    capability_overrides: dict[str, object] | None = None


class CustomProviderBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=128)
    discovery_format: str = Field(pattern="^(openai|google)$")
    base_url: str = Field(min_length=1, max_length=4000)
    api_key: str = Field(min_length=1)
    image_max_workers: int | None = Field(default=None, ge=1)
    video_max_workers: int | None = Field(default=None, ge=1)
    audio_max_workers: int | None = Field(default=None, ge=1)
    models: list[CustomProviderModelBundle] = Field(default_factory=list, max_length=256)


class ReleaseConfigBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    agent: AgentCredentialBundle
    providers: list[ProviderCredentialBundle] = Field(default_factory=list, max_length=64)
    custom_providers: list[CustomProviderBundle] = Field(default_factory=list, max_length=64)
    system_settings: dict[str, str] = Field(default_factory=dict)


class ConfigImportPreview(BaseModel):
    version: int
    builtin_providers: int
    custom_providers: int
    system_settings: int
    projects_to_update: int


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
    if bundle.version not in (1, CONFIG_BUNDLE_VERSION):
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


def _validate_custom_provider_bundle(provider: CustomProviderBundle) -> None:
    from lib.custom_provider.endpoints import ENDPOINT_REGISTRY

    seen: set[str] = set()
    for model in provider.models:
        if model.endpoint not in ENDPOINT_REGISTRY:
            raise ConfigBundleError("config_bundle_custom_endpoint_unknown")
        normalized = model.model_id.strip()
        if not normalized or normalized in seen:
            raise ConfigBundleError("config_bundle_custom_model_invalid")
        seen.add(normalized)


def _validate_system_settings(settings: dict[str, str]) -> None:
    raw_max_concurrent = settings.get("agent_max_concurrent_sessions")
    if raw_max_concurrent is None:
        return
    if not re.fullmatch(r"(?:0|[1-9]\d*)", raw_max_concurrent):
        raise ConfigBundleError("config_bundle_system_setting_invalid")
    max_concurrent = int(raw_max_concurrent)
    if not MIN_AGENT_MAX_CONCURRENT_SESSIONS <= max_concurrent <= MAX_AGENT_MAX_CONCURRENT_SESSIONS:
        raise ConfigBundleError("config_bundle_system_setting_invalid")


def _custom_model_to_db(model: CustomProviderModelBundle) -> dict:
    return {
        "model_id": model.model_id.strip(),
        "display_name": model.display_name.strip(),
        "endpoint": model.endpoint,
        "is_default": model.is_default,
        "is_enabled": model.is_enabled,
        "price_unit": model.price_unit,
        "price_input": model.price_input,
        "price_output": model.price_output,
        "currency": model.currency,
        "supported_durations": (
            json.dumps(model.supported_durations, ensure_ascii=False) if model.supported_durations is not None else None
        ),
        "resolution": model.resolution,
        "capability_overrides": model.capability_overrides,
    }


def _rewrite_custom_provider_refs(value: str, id_map: dict[int, int]) -> str:
    """把 bundle 来源 custom-N 引用映射到目标实例的 custom-M。"""

    def replace(match: re.Match[str]) -> str:
        source_id = int(match.group(1))
        target_id = id_map.get(source_id)
        return f"custom-{target_id}/" if target_id is not None else match.group(0)

    return re.sub(r"custom-(\d+)/", replace, value)


def validate_release_config_bundle(bundle: ReleaseConfigBundle) -> None:
    """校验 bundle 的跨字段语义，供预览和实际导入共用。"""

    if bundle.version not in (1, CONFIG_BUNDLE_VERSION):
        raise ConfigBundleError("config_bundle_version_unsupported")
    if set(bundle.system_settings) - PORTABLE_SYSTEM_SETTING_KEYS:
        raise ConfigBundleError("config_bundle_system_setting_unknown")
    _validate_system_settings(bundle.system_settings)

    builtin_ids = [provider.provider for provider in bundle.providers]
    custom_ids = [provider.source_id for provider in bundle.custom_providers]
    if len(set(builtin_ids)) != len(builtin_ids):
        raise ConfigBundleError("config_bundle_provider_unknown")
    if len(set(custom_ids)) != len(custom_ids):
        raise ConfigBundleError("config_bundle_custom_model_invalid")
    for provider in bundle.providers:
        _validate_provider_bundle(provider)
    for provider in bundle.custom_providers:
        _validate_custom_provider_bundle(provider)


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
    portable_settings.setdefault("agent_max_concurrent_sessions", str(DEFAULT_AGENT_MAX_CONCURRENT_SESSIONS))
    custom_pairs = await CustomProviderRepository(session).list_providers_with_models()
    custom_providers = [
        CustomProviderBundle(
            source_id=provider.id,
            display_name=provider.display_name,
            discovery_format=provider.discovery_format,
            base_url=provider.base_url,
            api_key=provider.api_key,
            image_max_workers=provider.image_max_workers,
            video_max_workers=provider.video_max_workers,
            audio_max_workers=provider.audio_max_workers,
            models=[
                CustomProviderModelBundle(
                    model_id=model.model_id,
                    display_name=model.display_name,
                    endpoint=model.endpoint,
                    is_default=model.is_default,
                    is_enabled=model.is_enabled,
                    price_unit=model.price_unit,
                    price_input=model.price_input,
                    price_output=model.price_output,
                    currency=model.currency,
                    supported_durations=json.loads(model.supported_durations) if model.supported_durations else None,
                    resolution=model.resolution,
                    capability_overrides=model.capability_overrides,
                )
                for model in models
            ],
        )
        for provider, models in custom_pairs
    ]
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
        custom_providers=custom_providers,
        system_settings=portable_settings,
    )


async def import_release_config_bundle(
    session: AsyncSession,
    bundle: ReleaseConfigBundle,
    *,
    replace_existing: bool = False,
) -> None:
    validate_release_config_bundle(bundle)

    svc = ConfigService(session)
    provider_repo = CredentialRepository(session)
    incoming_builtin = {provider.provider for provider in bundle.providers}
    if replace_existing:
        # 旧凭证保留但停用，导入文件成为当前运行环境的活跃凭证集合。
        await session.execute(
            update(ProviderCredential)
            .where(
                ProviderCredential.user_id == provider_repo.user_id,
                ProviderCredential.is_active.is_(True),
                ProviderCredential.provider.not_in(incoming_builtin),
            )
            .values(is_active=False)
        )
        # 同时清除未包含渠道的本地非密钥配置，避免 RPM / 并发等旧环境值在日后
        # 重新激活凭证时悄悄恢复。托管配置层不在本地环境文件的所有权范围内。
        all_provider_config = await svc.get_all_provider_configs()
        for provider_id, values in all_provider_config.items():
            if provider_id in incoming_builtin or provider_id not in PROVIDER_REGISTRY:
                continue
            allowed_keys = set(PROVIDER_REGISTRY[provider_id].required_keys) | set(
                PROVIDER_REGISTRY[provider_id].optional_keys
            )
            for key in set(values) & allowed_keys:
                await svc.delete_provider_config(provider_id, key, flush=False)
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
        if replace_existing:
            current_keys = set((await svc.get_provider_config(provider.provider)).keys())
            for stale_key in current_keys - set(provider.config):
                if stale_key in set(PROVIDER_REGISTRY[provider.provider].required_keys) | set(
                    PROVIDER_REGISTRY[provider.provider].optional_keys
                ):
                    await svc.delete_provider_config(provider.provider, stale_key, flush=False)
        for key, value in provider.config.items():
            await svc.set_provider_config(provider.provider, key, value, flush=False)

    # 自定义供应商 ID 只在单个数据库内稳定。优先复用来源 ID；跨实例导入时创建新行并建立
    # source_id → target_id 映射，随后统一重写 system_settings 中的 custom-N/model 引用。
    custom_repo = CustomProviderRepository(session)
    existing_custom = {provider.id: provider for provider in await custom_repo.list_providers()}
    custom_id_map: dict[int, int] = {}
    imported_target_ids: set[int] = set()
    for provider in bundle.custom_providers:
        target = existing_custom.get(provider.source_id)
        if target is None:
            target = await custom_repo.create_provider(
                display_name=provider.display_name,
                discovery_format=provider.discovery_format,
                base_url=provider.base_url,
                api_key=provider.api_key,
                image_max_workers=provider.image_max_workers,
                video_max_workers=provider.video_max_workers,
                audio_max_workers=provider.audio_max_workers,
            )
        else:
            await custom_repo.update_provider(
                target.id,
                display_name=provider.display_name,
                discovery_format=provider.discovery_format,
                base_url=provider.base_url,
                api_key=provider.api_key,
                image_max_workers=provider.image_max_workers,
                video_max_workers=provider.video_max_workers,
                audio_max_workers=provider.audio_max_workers,
            )
        await custom_repo.replace_models(target.id, [_custom_model_to_db(model) for model in provider.models])
        custom_id_map[provider.source_id] = target.id
        imported_target_ids.add(target.id)

    if replace_existing:
        # 自定义供应商没有 provider 级 enabled 位；把未出现在新环境里的旧型号全部停用，
        # 保留定义与密钥供人工恢复，同时让它们退出新任务候选。
        for provider, models in await custom_repo.list_providers_with_models():
            if provider.id not in imported_target_ids:
                for model in models:
                    model.is_enabled = False

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

    if replace_existing:
        current_settings = await svc.get_all_settings()
        for stale_key in (set(current_settings) & PORTABLE_SYSTEM_SETTING_KEYS) - set(bundle.system_settings):
            await svc.delete_setting(stale_key)
    for key, value in bundle.system_settings.items():
        await svc.set_setting(key, _rewrite_custom_provider_refs(value, custom_id_map))


@dataclass
class ProjectEnvironmentRollback:
    """导入事务的项目文件补偿记录；数据库回滚时恢复已改写的 project.json。"""

    snapshots: dict[str, dict]

    def restore(self) -> None:
        from lib.config.resolver import get_project_manager

        manager = get_project_manager()
        for project_name, snapshot in self.snapshots.items():

            def _restore(project: dict, *, original: dict = snapshot) -> None:
                project.clear()
                project.update(original)

            manager.update_project(project_name, _restore)


def count_projects_with_environment_overrides() -> int:
    from lib.config.resolver import get_project_manager

    manager = get_project_manager()
    count = 0
    for project_name in manager.list_projects():
        try:
            project = manager.load_project_readonly(project_name)
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            continue
        if any(key in project for key in PROJECT_ENVIRONMENT_OVERRIDE_KEYS):
            count += 1
    return count


def reset_project_environment_overrides() -> ProjectEnvironmentRollback:
    """清除所有项目的运行环境覆盖，让其继承新系统默认；失败时补偿已完成的写入。"""

    from lib.config.resolver import get_project_manager

    manager = get_project_manager()
    snapshots: dict[str, dict] = {}
    rollback = ProjectEnvironmentRollback(snapshots)
    try:
        for project_name in manager.list_projects():
            try:
                current = manager.load_project_readonly(project_name)
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                continue
            if not any(key in current for key in PROJECT_ENVIRONMENT_OVERRIDE_KEYS):
                continue
            snapshots[project_name] = current

            def _clear(project: dict) -> None:
                for key in PROJECT_ENVIRONMENT_OVERRIDE_KEYS:
                    project.pop(key, None)

            manager.update_project(project_name, _clear)
    except Exception:
        rollback.restore()
        raise
    return rollback


def preview_config_import(bundle: ReleaseConfigBundle) -> ConfigImportPreview:
    validate_release_config_bundle(bundle)
    return ConfigImportPreview(
        version=bundle.version,
        builtin_providers=len(bundle.providers),
        custom_providers=len(bundle.custom_providers),
        system_settings=len(bundle.system_settings),
        projects_to_update=count_projects_with_environment_overrides(),
    )


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
