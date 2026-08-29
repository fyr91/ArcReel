"""ArcReel cloud identity login and per-user provider configuration sync."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.app_data_dir import app_data_dir
from lib.db import async_session_factory
from lib.db.base import utc_now
from lib.db.models.user import ArcReelCloudSession, User
from lib.env_init import PROJECT_ROOT
from server.services.account_center_sync import _apply_snapshot

logger = logging.getLogger(__name__)
_access_token_locks: dict[str, asyncio.Lock] = {}


# These are public client coordinates, not privileged credentials. Keeping them
# in the product lets a distributed ArcReel installation use the managed account
# service without requiring every user to prepare a local .env file. Deployments
# can still replace both values together through environment variables.
DEFAULT_ARCREEL_CLOUD_ORIGIN = "https://47.108.223.84:50002"
DEFAULT_ARCREEL_CLOUD_AUTH_URL = f"{DEFAULT_ARCREEL_CLOUD_ORIGIN}/functions/v1/arcreel-auth"
DEFAULT_ARCREEL_CLOUD_PUBLISHABLE_KEY = "sb_publishable_ZfvSRL5e-PXNaDyAaOoss7_S5_qU0EN"
DEFAULT_ARCREEL_CLOUD_CA_BUNDLE = PROJECT_ROOT / "server" / "certs" / "arcreel-supabase-ca.crt"
_DISABLED_VALUES = {"0", "false", "no", "off"}


class ArcReelCloudError(Exception):
    def __init__(self, message: str, *, status_code: int = 503, code: str = "ARCREEL_CLOUD_UNAVAILABLE") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class ArcReelCloudConfig:
    auth_url: str
    publishable_key: str


@dataclass(frozen=True)
class ArcReelCloudIdentity:
    sub: str
    username: str
    display_name: str | None
    role: str


def cloud_config() -> ArcReelCloudConfig | None:
    enabled = os.environ.get("ARCREEL_CLOUD_ENABLED", "true").strip().lower()
    if enabled in _DISABLED_VALUES:
        return None
    configured_auth_url = os.environ.get("ARCREEL_CLOUD_AUTH_URL", "").strip()
    configured_publishable_key = os.environ.get("ARCREEL_CLOUD_PUBLISHABLE_KEY", "").strip()
    has_auth_override = bool(configured_auth_url)
    has_key_override = bool(configured_publishable_key)
    if has_auth_override != has_key_override:
        raise ArcReelCloudError("ArcReel 云端登录配置不完整", code="ARCREEL_CLOUD_CONFIG_INVALID")
    auth_url = configured_auth_url or DEFAULT_ARCREEL_CLOUD_AUTH_URL
    publishable_key = configured_publishable_key or DEFAULT_ARCREEL_CLOUD_PUBLISHABLE_KEY
    return ArcReelCloudConfig(auth_url=auth_url, publishable_key=publishable_key)


def cloud_enabled() -> bool:
    try:
        return cloud_config() is not None
    except ArcReelCloudError:
        return True


async def login_with_cloud(session: AsyncSession, username: str, password: str) -> User:
    config = cloud_config()
    if config is None:
        raise ArcReelCloudError("ArcReel 云端登录尚未配置", code="ARCREEL_CLOUD_NOT_CONFIGURED")
    response = await _request(
        "POST",
        f"{config.auth_url}/login",
        config,
        json={"username": username, "password": password},
    )
    payload = _payload(response)
    identity = _identity(payload.get("user"))
    access_token = str(payload.get("access_token") or "")
    refresh_token = str(payload.get("refresh_token") or "")
    if not access_token or not refresh_token:
        raise ArcReelCloudError("云端登录返回的数据不完整", code="ARCREEL_CLOUD_RESPONSE_INVALID")

    user = await _upsert_shadow_user(session, identity)
    config_response = await _request("GET", f"{config.auth_url}/config", config, access_token=access_token)
    config_payload = _payload(config_response)
    revision = _revision(config_payload.get("revision"))
    credentials = config_payload.get("credentials")
    if not isinstance(credentials, list):
        raise ArcReelCloudError("云端配置格式无效", code="ARCREEL_CLOUD_RESPONSE_INVALID")
    await _apply_snapshot(
        session,
        user.id,
        revision,
        credentials,
        management_source="arcreel_cloud",
        agent_credential=config_payload.get("agent_credential"),
        global_configs=config_payload.get("global_configs"),
    )
    cloud_session = await session.get(ArcReelCloudSession, user.id)
    if cloud_session is None:
        cloud_session = ArcReelCloudSession(
            user_id=user.id,
            cloud_user_sub=identity.sub,
            access_token_encrypted=_encrypt(access_token),
            access_token_expires_at=_token_expiry(payload),
            refresh_token_encrypted=_encrypt(refresh_token),
        )
        session.add(cloud_session)
    else:
        cloud_session.cloud_user_sub = identity.sub
        cloud_session.access_token_encrypted = _encrypt(access_token)
        cloud_session.access_token_expires_at = _token_expiry(payload)
        cloud_session.refresh_token_encrypted = _encrypt(refresh_token)
    cloud_session.config_revision = revision
    cloud_session.last_sync_at = utc_now()
    cloud_session.last_sync_status = "succeeded"
    cloud_session.last_sync_error = None
    await session.commit()
    return user


async def sync_cloud_user(user_id: str) -> bool:
    config = cloud_config()
    if config is None:
        return False
    async with async_session_factory() as session:
        cloud_session = await session.get(ArcReelCloudSession, user_id)
        if cloud_session is None:
            return False
        try:
            refresh_token = _decrypt(cloud_session.refresh_token_encrypted)
            refresh_response = await _request(
                "POST",
                f"{config.auth_url}/refresh",
                config,
                json={"refresh_token": refresh_token},
            )
            refresh_payload = _payload(refresh_response)
            identity = _identity(refresh_payload.get("user"))
            if identity.sub != cloud_session.cloud_user_sub:
                raise ArcReelCloudError("云端会话身份不匹配", status_code=401, code="CLOUD_IDENTITY_MISMATCH")
            access_token = str(refresh_payload.get("access_token") or "")
            next_refresh_token = str(refresh_payload.get("refresh_token") or "")
            if not access_token or not next_refresh_token:
                raise ArcReelCloudError("云端刷新返回的数据不完整", code="ARCREEL_CLOUD_RESPONSE_INVALID")
            config_payload = _payload(
                await _request("GET", f"{config.auth_url}/config", config, access_token=access_token)
            )
            credentials = config_payload.get("credentials")
            if not isinstance(credentials, list):
                raise ArcReelCloudError("云端配置格式无效", code="ARCREEL_CLOUD_RESPONSE_INVALID")
            revision = _revision(config_payload.get("revision"))
            await _apply_snapshot(
                session,
                user_id,
                revision,
                credentials,
                management_source="arcreel_cloud",
                agent_credential=config_payload.get("agent_credential"),
                global_configs=config_payload.get("global_configs"),
            )
            user = await session.get(User, user_id)
            if user is not None:
                user.username = identity.username
                user.display_name = identity.display_name
                user.role = identity.role
                user.is_active = True
            cloud_session.refresh_token_encrypted = _encrypt(next_refresh_token)
            cloud_session.access_token_encrypted = _encrypt(access_token)
            cloud_session.access_token_expires_at = _token_expiry(refresh_payload)
            cloud_session.config_revision = revision
            cloud_session.last_sync_at = utc_now()
            cloud_session.last_sync_status = "succeeded"
            cloud_session.last_sync_error = None
            await session.commit()
            return True
        except Exception as exc:
            await session.rollback()
            cloud_session = await session.get(ArcReelCloudSession, user_id)
            if cloud_session is not None:
                cloud_session.last_sync_at = utc_now()
                cloud_session.last_sync_status = "failed"
                cloud_session.last_sync_error = str(exc)[:500]
                if isinstance(exc, ArcReelCloudError) and exc.status_code == 403:
                    user = await session.get(User, user_id)
                    if user is not None:
                        user.is_active = False
                await session.commit()
            logger.warning("ArcReel 云端配置同步失败 user=%s: %s", user_id, exc)
            return False


async def cloud_access_token(user_id: str) -> str:
    """Return a valid Supabase access token without exposing it to the SPA."""

    lock = _access_token_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        config = cloud_config()
        if config is None:
            raise ArcReelCloudError("ArcReel 云端登录尚未配置", code="ARCREEL_CLOUD_NOT_CONFIGURED")
        async with async_session_factory() as session:
            cloud_session = await session.get(ArcReelCloudSession, user_id)
            if cloud_session is None:
                raise ArcReelCloudError("请重新登录后再同步公司资产", status_code=401, code="CLOUD_SESSION_MISSING")
            expires_at = cloud_session.access_token_expires_at
            encrypted_access_token = cloud_session.access_token_encrypted
            if (
                expires_at is not None
                and encrypted_access_token is not None
                and _as_utc(expires_at) > utc_now() + timedelta(seconds=60)
            ):
                return _decrypt(encrypted_access_token)

            refresh_token = _decrypt(cloud_session.refresh_token_encrypted)
            response = await _request(
                "POST",
                f"{config.auth_url}/refresh",
                config,
                json={"refresh_token": refresh_token},
            )
            payload = _payload(response)
            identity = _identity(payload.get("user"))
            if identity.sub != cloud_session.cloud_user_sub:
                raise ArcReelCloudError("云端会话身份不匹配", status_code=401, code="CLOUD_IDENTITY_MISMATCH")
            access_token = str(payload.get("access_token") or "")
            next_refresh_token = str(payload.get("refresh_token") or "")
            if not access_token or not next_refresh_token:
                raise ArcReelCloudError("云端刷新返回的数据不完整", code="ARCREEL_CLOUD_RESPONSE_INVALID")
            cloud_session.access_token_encrypted = _encrypt(access_token)
            cloud_session.access_token_expires_at = _token_expiry(payload)
            cloud_session.refresh_token_encrypted = _encrypt(next_refresh_token)
            await session.commit()
            return access_token


async def cloud_user_sub(user_id: str) -> str:
    """Resolve the durable Supabase Auth identity for a local shadow user."""

    async with async_session_factory() as session:
        cloud_session = await session.get(ArcReelCloudSession, user_id)
        if cloud_session is None:
            raise ArcReelCloudError("请重新登录后再访问公司资产", status_code=401, code="CLOUD_SESSION_MISSING")
        return cloud_session.cloud_user_sub


async def _upsert_shadow_user(session: AsyncSession, identity: ArcReelCloudIdentity) -> User:
    result = await session.execute(select(User).where(User.arcreel_cloud_sub == identity.sub))
    user = result.scalar_one_or_none()
    if user is None:
        same_name = await session.execute(select(User).where(User.username == identity.username))
        user = same_name.scalar_one_or_none()
        if user is not None and user.arcreel_cloud_sub not in (None, identity.sub):
            raise ArcReelCloudError(
                "本地已存在同名但属于其他云账号的用户", status_code=409, code="LOCAL_USERNAME_CONFLICT"
            )
        if user is None:
            user = User(id=str(uuid.uuid4()), username=identity.username)
            session.add(user)
    user.arcreel_cloud_sub = identity.sub
    user.username = identity.username
    user.display_name = identity.display_name
    user.role = identity.role
    user.is_active = True
    await session.flush()
    return user


async def _request(
    method: str,
    url: str,
    config: ArcReelCloudConfig,
    *,
    json: dict[str, str] | None = None,
    access_token: str | None = None,
) -> httpx.Response:
    headers = {"apikey": config.publishable_key, "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=cloud_tls_verify(url)) as client:
            response = await client.request(method, url, headers=headers, json=json)
    except httpx.HTTPError as exc:
        raise ArcReelCloudError("无法连接 ArcReel 云端登录服务") from exc
    if not response.is_success:
        detail = _safe_json(response).get("error")
        if isinstance(detail, dict):
            message = str(detail.get("message") or "云端登录失败")
            code = str(detail.get("code") or "ARCREEL_CLOUD_REQUEST_FAILED")
        else:
            message, code = "云端登录失败", "ARCREEL_CLOUD_REQUEST_FAILED"
        raise ArcReelCloudError(message, status_code=response.status_code, code=code)
    return response


def cloud_tls_verify(url: str | None = None) -> ssl.SSLContext | bool:
    """Return normal public trust plus the CA needed by the bundled deployment."""

    configured = os.environ.get("ARCREEL_CLOUD_CA_BUNDLE", "").strip()
    if configured:
        bundle = Path(configured).expanduser()
        if not bundle.is_absolute():
            bundle = PROJECT_ROOT / bundle
    elif url is not None and _uses_bundled_cloud_origin(url):
        bundle = DEFAULT_ARCREEL_CLOUD_CA_BUNDLE
    else:
        return True
    if not bundle.is_file():
        raise ArcReelCloudError("ArcReel 云端 CA 证书不存在", code="ARCREEL_CLOUD_CONFIG_INVALID")
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(bundle))
    return context


def _uses_bundled_cloud_origin(url: str) -> bool:
    try:
        candidate = urlsplit(url)
        bundled = urlsplit(DEFAULT_ARCREEL_CLOUD_ORIGIN)
        return (
            candidate.scheme == bundled.scheme
            and candidate.hostname == bundled.hostname
            and candidate.port == bundled.port
        )
    except ValueError:
        return False


def _payload(response: httpx.Response) -> dict[str, object]:
    return _safe_json(response)


def _safe_json(response: httpx.Response) -> dict[str, object]:
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _revision(value: object) -> int:
    if isinstance(value, (str, int)):
        try:
            return max(0, int(value))
        except ValueError:
            pass
    raise ArcReelCloudError("云端配置版本无效", code="ARCREEL_CLOUD_RESPONSE_INVALID")


def _token_expiry(payload: dict[str, object]) -> datetime:
    expires_at = payload.get("expires_at")
    if isinstance(expires_at, (int, float, str)):
        try:
            return datetime.fromtimestamp(float(expires_at), UTC)
        except (OSError, OverflowError, ValueError):
            pass
    expires_in = payload.get("expires_in")
    try:
        seconds = int(expires_in) if expires_in is not None else 3600
    except (TypeError, ValueError):
        seconds = 3600
    return utc_now() + timedelta(seconds=max(60, seconds))


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _identity(raw: object) -> ArcReelCloudIdentity:
    if not isinstance(raw, dict):
        raise ArcReelCloudError("云端用户身份无效", code="ARCREEL_CLOUD_RESPONSE_INVALID")
    sub = str(raw.get("id") or "")
    username = str(raw.get("username") or "").strip()
    role = str(raw.get("role") or "user")
    if not sub or not username or role not in {"admin", "user"}:
        raise ArcReelCloudError("云端用户身份无效", code="ARCREEL_CLOUD_RESPONSE_INVALID")
    display_name = str(raw.get("display_name") or "").strip() or None
    return ArcReelCloudIdentity(sub=sub, username=username, display_name=display_name, role=role)


def _fernet() -> Fernet:
    path = app_data_dir() / ".arcreel_cloud_session_key"
    if path.exists():
        key = path.read_bytes().strip()
    else:
        key = base64.urlsafe_b64encode(os.urandom(32))
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(key)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as exc:
        raise ArcReelCloudError(
            "本地云端会话无法解密，请重新登录", status_code=401, code="CLOUD_SESSION_INVALID"
        ) from exc
