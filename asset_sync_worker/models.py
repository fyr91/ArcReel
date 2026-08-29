"""Source-neutral records used by asset source adapters and the monitor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SourceFile:
    key: str
    role: str
    media_type: Literal["image", "audio"]
    mime_type: str | None
    url: str
    relative_path: str
    byte_size: int | None
    sha256: str | None
    revision: str | None
    sort_order: int
    source_fields: tuple[str, ...]


@dataclass(frozen=True)
class SourceAsset:
    source_key: str
    asset_type: Literal["character", "scene", "prop"]
    name: str
    description: str
    voice_style: str
    voice_id: str | None
    aliases: tuple[str, ...]
    files: tuple[SourceFile, ...]
    fingerprint: str


@dataclass(frozen=True)
class SourceSnapshot:
    cursor: dict[str, str]
    assets: tuple[SourceAsset, ...]
