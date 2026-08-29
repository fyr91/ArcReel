"""Adapter for the current published character catalog contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from asset_sync_worker.models import SourceAsset, SourceFile, SourceSnapshot

_MAX_FILE_BYTES = 200 * 1024 * 1024
_MEDIA_BY_SUFFIX = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".aac": "audio",
    ".flac": "audio",
    ".ogg": "audio",
}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
_IMAGE_RANK = {"avatarUrl": 0, "fullBodyImageUrl": 1, "halfBodyImageUrl": 2, "chestImageUrl": 3}


class CharacterSourceError(RuntimeError):
    pass


class _Voice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tts_voice_id: str | None = Field(default=None, alias="ttsVoiceId")


class _Asset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str = Field(min_length=1, max_length=300)
    relative_path: str = Field(alias="relativePath", min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=4000)
    source_fields: list[str] = Field(default_factory=list, alias="sourceFields")
    revision: str | int | None = None
    sha256: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    byte_size: int | None = Field(default=None, alias="byteSize", ge=0, le=_MAX_FILE_BYTES)


class _Character(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    chinese_name: str | None = Field(default=None, alias="chineseName", max_length=200)
    subtitle: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=20_000)
    voice: _Voice | None = None
    assets: list[_Asset] = Field(default_factory=list, max_length=200)


class _Version(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    activated_at: str = Field(alias="activatedAt")


class _Catalog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: int = Field(alias="schemaVersion")
    publish_version: _Version = Field(alias="publishVersion")
    characters: list[_Character] = Field(max_length=10_000)


class CharacterCatalogV1Adapter:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def fetch(self, *, endpoint: str, token: str) -> SourceSnapshot:
        url = _https_url(endpoint)
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "apikey": token, "Accept": "application/json"},
            )
            response.raise_for_status()
            catalog = _Catalog.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                raise CharacterSourceError("asset_source_upstream_unauthorized") from exc
            if exc.response.status_code >= 500:
                raise CharacterSourceError("asset_source_upstream_unavailable") from exc
            raise CharacterSourceError("asset_source_upstream_request_failed") from exc
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            raise CharacterSourceError("character_source_fetch_failed") from exc
        finally:
            if owns_client:
                await client.aclose()
        if catalog.schema_version != 1:
            raise CharacterSourceError("character_source_schema_unsupported")
        return SourceSnapshot(
            cursor={
                "publish_version": catalog.publish_version.id,
                "activated_at": catalog.publish_version.activated_at,
            },
            assets=tuple(_map_character(character) for character in catalog.characters),
        )

    async def download(self, source_file: SourceFile) -> bytes:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        try:
            response = await client.get(_https_url(source_file.url))
            response.raise_for_status()
            payload = response.content
        except httpx.HTTPError as exc:
            raise CharacterSourceError("character_source_file_download_failed") from exc
        finally:
            if owns_client:
                await client.aclose()
        if len(payload) > _MAX_FILE_BYTES:
            raise CharacterSourceError("character_source_file_too_large")
        if source_file.byte_size is not None and len(payload) != source_file.byte_size:
            raise CharacterSourceError("character_source_file_size_mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if source_file.sha256 is not None and digest != source_file.sha256:
            raise CharacterSourceError("character_source_file_hash_mismatch")
        return payload


def _map_character(character: _Character) -> SourceAsset:
    files: list[SourceFile] = []
    seen_keys: set[str] = set()
    for order, remote in enumerate(character.assets):
        if remote.key in seen_keys:
            raise CharacterSourceError("character_source_duplicate_file")
        seen_keys.add(remote.key)
        relative = _relative_path(remote.relative_path)
        media_type = _media_type(remote, relative)
        if media_type is None:
            continue
        digest = _sha256(remote.sha256)
        files.append(
            SourceFile(
                key=remote.key,
                role="attachment",
                media_type=media_type,
                mime_type=remote.mime_type,
                url=_https_url(remote.url),
                relative_path=relative.as_posix(),
                byte_size=remote.byte_size,
                sha256=digest,
                revision=str(remote.revision) if remote.revision is not None else None,
                sort_order=order,
                source_fields=tuple(remote.source_fields),
            )
        )
    primary_image_key = min(
        (item for item in files if item.media_type == "image"),
        key=lambda item: (_IMAGE_RANK.get(item.key, 100), item.sort_order),
        default=None,
    )
    primary_audio_key = min(
        (item for item in files if item.media_type == "audio"),
        key=lambda item: item.sort_order,
        default=None,
    )
    files = [
        SourceFile(
            **{
                **item.__dict__,
                "role": (
                    "primary_image"
                    if primary_image_key is not None and item.key == primary_image_key.key
                    else "reference_audio"
                    if primary_audio_key is not None and item.key == primary_audio_key.key
                    else "attachment"
                ),
            }
        )
        for item in files
    ]
    canonical_name = (character.chinese_name or character.name).strip()
    aliases = _aliases(canonical_name, character.name, character.subtitle)
    fingerprint_payload = {
        "source_key": character.id,
        "name": canonical_name,
        "description": character.summary or character.subtitle or "",
        "voice_id": character.voice.tts_voice_id if character.voice else None,
        "aliases": aliases,
        "files": [item.__dict__ for item in files],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SourceAsset(
        source_key=character.id,
        asset_type="character",
        name=canonical_name,
        description=character.summary or character.subtitle or "",
        voice_style="",
        voice_id=character.voice.tts_voice_id if character.voice else None,
        aliases=aliases,
        files=tuple(files),
        fingerprint=fingerprint,
    )


def _aliases(canonical: str, *candidates: str | None) -> tuple[str, ...]:
    seen = {canonical.casefold()}
    result: list[str] = []
    for candidate in candidates:
        normalized = (candidate or "").strip()
        key = normalized.casefold()
        if normalized and len(normalized) <= 200 and key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def _https_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CharacterSourceError("character_source_invalid_url")
    return parsed.geturl()


def _relative_path(value: str) -> PurePosixPath:
    if "\\" in value:
        raise CharacterSourceError("character_source_invalid_path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise CharacterSourceError("character_source_invalid_path")
    return path


def _media_type(asset: _Asset, path: PurePosixPath) -> str | None:
    if path.suffix.lower() in _VIDEO_SUFFIXES:
        return None
    mime = (asset.mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return _MEDIA_BY_SUFFIX.get(path.suffix.lower())


def _sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise CharacterSourceError("character_source_invalid_hash")
    return normalized


__all__ = ["CharacterCatalogV1Adapter", "CharacterSourceError"]
