"""Bundled custom-style catalog and idempotent startup synchronization."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.asset_repo import AssetRepository

BUILTIN_STYLE_SOURCE = "arcreel-builtin-style"
_STYLE_ASSET_TYPE = "style"
_ASSET_DIR = Path(__file__).with_name("builtin_style_assets")


@dataclass(frozen=True)
class BuiltinStyleDefinition:
    external_id: str
    name: str
    description: str
    image_filename: str
    legacy_names: tuple[str, ...] = ()

    @property
    def image_path(self) -> str:
        return f"_global_assets/style/builtin/{self.image_filename}"


BUILTIN_STYLES: tuple[BuiltinStyleDefinition, ...] = (
    BuiltinStyleDefinition(
        external_id="ziqi-pastoral",
        name="子柒田园风",
        description=(
            "photorealistic photography, bright dappled natural sunlight, warm earthy color palette, "
            "crisp fine detail, directional sun shadows, natural outdoor lighting, muted warm color grading, "
            "tactile realistic textures, warm lighthearted mood"
        ),
        image_filename="ziqi-pastoral.jpg",
        legacy_names=("鳄鱼爸爸的景泰蓝 · 风格",),
    ),
    BuiltinStyleDefinition(
        external_id="3d-animation",
        name="3D动画风格",
        description=(
            "cinematic stylized 3D cartoon animation, warm soft key lighting, clean rim light, gentle "
            "cool-warm depth separation, vibrant harmonious color palette, polished feature-animation "
            "rendering, rounded geometric forms, soft tactile materials, warm subsurface scattering, "
            "sculpted forms with delicate edge detail, crisp silhouettes, shallow depth of field, warm "
            "playful emotionally engaging mood, clean full-color finish"
        ),
        image_filename="3d-animation.png",
    ),
)

_ORDER_BY_EXTERNAL_ID = {style.external_id: index for index, style in enumerate(BUILTIN_STYLES)}


class BuiltinStyleConflictError(RuntimeError):
    """A catalog name is already owned by a different external source."""


def is_builtin_style_source(external_source: str | None) -> bool:
    return external_source == BUILTIN_STYLE_SOURCE


def builtin_style_order(external_id: str | None) -> int:
    return _ORDER_BY_EXTERNAL_ID.get(external_id or "", len(BUILTIN_STYLES))


def _atomic_copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and source.read_bytes() == target.read_bytes():
        return
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _materialize_images(projects_root: Path) -> None:
    for definition in BUILTIN_STYLES:
        _atomic_copy(_ASSET_DIR / definition.image_filename, projects_root / definition.image_path)


async def _find_promotable_style(repo: AssetRepository, definition: BuiltinStyleDefinition):
    for name in (definition.name, *definition.legacy_names):
        candidate = await repo.get_by_type_name(_STYLE_ASSET_TYPE, name)
        if candidate is None:
            continue
        if candidate.external_source not in {None, BUILTIN_STYLE_SOURCE}:
            raise BuiltinStyleConflictError(
                f"style name {name!r} belongs to external source {candidate.external_source!r}"
            )
        return candidate
    return None


async def sync_builtin_styles(session: AsyncSession, projects_root: Path) -> dict[str, int]:
    """Create or promote the bundled style cards without changing their IDs."""

    await asyncio.to_thread(_materialize_images, projects_root)
    repo = AssetRepository(session)
    result = {"added": 0, "promoted": 0, "updated": 0, "unchanged": 0}

    for definition in BUILTIN_STYLES:
        style = await repo.get_by_external_identity(BUILTIN_STYLE_SOURCE, definition.external_id)
        promoted = False
        if style is None:
            style = await _find_promotable_style(repo, definition)
            promoted = style is not None

        fields = {
            "name": definition.name,
            "description": definition.description,
            "image_path": definition.image_path,
            "source_project": None,
            "external_source": BUILTIN_STYLE_SOURCE,
            "external_id": definition.external_id,
        }
        if style is None:
            await repo.create(type=_STYLE_ASSET_TYPE, **fields)
            result["added"] += 1
            continue

        changed = any(getattr(style, key) != value for key, value in fields.items())
        if not changed:
            result["unchanged"] += 1
            continue
        await repo.update(style.id, **fields)
        result["promoted" if promoted else "updated"] += 1

    await session.commit()
    return result


__all__ = [
    "BUILTIN_STYLES",
    "BUILTIN_STYLE_SOURCE",
    "BuiltinStyleConflictError",
    "BuiltinStyleDefinition",
    "builtin_style_order",
    "is_builtin_style_source",
    "sync_builtin_styles",
]
