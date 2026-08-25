"""Shared project/global asset link operations for REST and Agent tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.artifact_activation import register_current_resource_artifact
from lib.asset_types import (
    ASSET_SPECS,
    GLOBAL_ASSET_ID_FIELD,
    GLOBAL_ASSET_IMAGE_USAGE_FIELD,
    GLOBAL_ASSET_IMAGE_USAGES,
    GLOBAL_ASSET_VOICE_SOURCE_FIELD,
    GLOBAL_ASSET_VOICE_SOURCES,
    GLOBAL_LIBRARY_ASSET_TYPES,
    MATCHED_GLOBAL_ASSET_ID_FIELD,
    resolve_asset_key,
)
from lib.character_sheet_materialization import plan_character_sheet_materialization
from lib.db import async_session_factory
from lib.db.models.asset import Asset
from lib.db.repositories.asset_repo import AssetRepository
from lib.path_safety import safe_resolve
from lib.project_change_hints import ProjectChangeSource, project_change_source
from lib.project_manager import ProjectManager, get_project_manager


class ProjectAssetLinkError(ValueError):
    pass


class ProjectAssetLinkNotFound(ProjectAssetLinkError):
    pass


@dataclass(frozen=True, slots=True)
class LinkedCharacterSheetBackfill:
    materialized: int = 0
    skipped: int = 0


async def _asset(asset_id: str, session_factory=None):
    factory = session_factory or async_session_factory
    async with factory() as session:
        return await AssetRepository(session).get_by_id(asset_id)


async def link_project_asset(
    project_name: str,
    resource_type: str,
    resource_id: str,
    asset_id: str,
    *,
    manager: ProjectManager | None = None,
    source: ProjectChangeSource = "webui",
    session_factory=None,
) -> tuple[dict[str, Any], Any]:
    if resource_type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise ProjectAssetLinkError("invalid asset type")
    asset = await _asset(asset_id, session_factory)
    if asset is None:
        raise ProjectAssetLinkNotFound(asset_id)
    if asset.type != resource_type:
        raise ProjectAssetLinkError("global asset type does not match project asset type")
    pm = manager or get_project_manager()
    project_dir = pm.get_project_path(project_name)
    global_image_path = (
        asset.image_path
        if resource_type == "character"
        and isinstance(asset.image_path, str)
        and safe_resolve(pm.projects_root, asset.image_path) is not None
        else None
    )

    def _sync() -> dict[str, Any]:
        copies: list[tuple[Path, Path]] = []
        linked_entry: dict[str, Any] = {}
        materialized_name: str | None = None

        def _mutate(project: dict[str, Any]) -> None:
            nonlocal materialized_name
            spec = ASSET_SPECS[resource_type]
            bucket = project.get(spec.bucket_key)
            key = resolve_asset_key(bucket, resource_id)
            if not isinstance(bucket, dict) or key is None or not isinstance(bucket.get(key), dict):
                raise KeyError(resource_id)
            entry = bucket[key]
            entry[GLOBAL_ASSET_ID_FIELD] = asset.id
            entry[MATCHED_GLOBAL_ASSET_ID_FIELD] = asset.id
            entry[GLOBAL_ASSET_IMAGE_USAGE_FIELD] = "main"
            if resource_type == "character":
                entry[GLOBAL_ASSET_VOICE_SOURCE_FIELD] = (
                    "reference_audio" if asset.audio_path else "voice_id" if asset.voice_id else "none"
                )
                materialized = plan_character_sheet_materialization(
                    project_dir=project_dir,
                    projects_root=pm.projects_root,
                    character_name=key,
                    entry=entry,
                    global_image_path=global_image_path,
                    copies=copies,
                )
                if materialized is not None:
                    materialized_name = key
            linked_entry.update(entry)

        def _register_sheet(_project_file: Path) -> None:
            if materialized_name is not None:
                register_current_resource_artifact(
                    project_dir,
                    resource_type="characters",
                    resource_id=materialized_name,
                )

        with project_change_source(source):
            pm.update_project_with_file_copies(
                project_name,
                _mutate,
                copies,
                on_commit=_register_sheet,
            )
        return linked_entry

    return await asyncio.to_thread(_sync), asset


async def materialize_linked_character_sheet(
    project_name: str,
    character_name: str,
    asset: Asset | None,
    *,
    manager: ProjectManager | None = None,
    source: ProjectChangeSource = "filesystem",
) -> bool:
    """Backfill one linked Global Asset main image into an empty project sheet."""

    pm = manager or get_project_manager()
    if (
        asset is None
        or asset.type != "character"
        or not isinstance(asset.image_path, str)
        or safe_resolve(pm.projects_root, asset.image_path) is None
    ):
        return False
    project = await asyncio.to_thread(pm.load_project, project_name)
    characters = project.get("characters")
    key = resolve_asset_key(characters, character_name)
    entry = characters.get(key) if isinstance(characters, dict) and key is not None else None
    if (
        not isinstance(entry, dict)
        or entry.get("character_sheet")
        or (entry.get(GLOBAL_ASSET_ID_FIELD) or entry.get(MATCHED_GLOBAL_ASSET_ID_FIELD)) != asset.id
        or entry.get(GLOBAL_ASSET_IMAGE_USAGE_FIELD, "main") != "main"
    ):
        return False

    project_dir = pm.get_project_path(project_name)

    def _sync() -> bool:
        copies: list[tuple[Path, Path]] = []
        materialized_name: str | None = None

        def _mutate(locked_project: dict[str, Any]) -> None:
            nonlocal materialized_name
            locked_characters = locked_project.get("characters")
            locked_key = resolve_asset_key(locked_characters, character_name)
            current = (
                locked_characters.get(locked_key)
                if isinstance(locked_characters, dict) and locked_key is not None
                else None
            )
            if (
                locked_key is None
                or not isinstance(current, dict)
                or current.get("character_sheet")
                or (current.get(GLOBAL_ASSET_ID_FIELD) or current.get(MATCHED_GLOBAL_ASSET_ID_FIELD)) != asset.id
                or current.get(GLOBAL_ASSET_IMAGE_USAGE_FIELD, "main") != "main"
            ):
                return
            materialized = plan_character_sheet_materialization(
                project_dir=project_dir,
                projects_root=pm.projects_root,
                character_name=locked_key,
                entry=current,
                global_image_path=asset.image_path,
                copies=copies,
            )
            if materialized is not None:
                materialized_name = locked_key

        def _register_sheet(_project_file: Path) -> None:
            if materialized_name is not None:
                register_current_resource_artifact(
                    project_dir,
                    resource_type="characters",
                    resource_id=materialized_name,
                )

        with project_change_source(source):
            pm.update_project_with_file_copies(
                project_name,
                _mutate,
                copies,
                on_commit=_register_sheet,
            )
        return materialized_name is not None

    return await asyncio.to_thread(_sync)


async def backfill_linked_character_sheets(
    *,
    manager: ProjectManager | None = None,
    session_factory=None,
) -> LinkedCharacterSheetBackfill:
    """Repair historical linked-main characters whose project sheet is empty."""

    pm = manager or get_project_manager()
    factory = session_factory or async_session_factory
    pending: list[tuple[str, str, str]] = []
    for project_name in pm.list_projects():
        try:
            project = await asyncio.to_thread(pm.load_project, project_name)
        except (FileNotFoundError, ValueError):
            continue
        characters = project.get("characters")
        if not isinstance(characters, dict):
            continue
        for character_name, entry in characters.items():
            if not isinstance(character_name, str) or not isinstance(entry, dict) or entry.get("character_sheet"):
                continue
            asset_id = entry.get(GLOBAL_ASSET_ID_FIELD) or entry.get(MATCHED_GLOBAL_ASSET_ID_FIELD)
            if isinstance(asset_id, str) and asset_id and entry.get(GLOBAL_ASSET_IMAGE_USAGE_FIELD, "main") == "main":
                pending.append((project_name, character_name, asset_id))
    if not pending:
        return LinkedCharacterSheetBackfill()

    async with factory() as session:
        assets = await AssetRepository(session).get_by_ids(list(dict.fromkeys(item[2] for item in pending)))
    assets_by_id = {asset.id: asset for asset in assets}
    materialized = 0
    for project_name, character_name, asset_id in pending:
        if await materialize_linked_character_sheet(
            project_name,
            character_name,
            assets_by_id.get(asset_id),
            manager=pm,
        ):
            materialized += 1
    return LinkedCharacterSheetBackfill(materialized=materialized, skipped=len(pending) - materialized)


async def unlink_project_asset(
    project_name: str,
    resource_type: str,
    resource_id: str,
    *,
    manager: ProjectManager | None = None,
    source: ProjectChangeSource = "webui",
) -> dict[str, Any]:
    if resource_type not in GLOBAL_LIBRARY_ASSET_TYPES:
        raise ProjectAssetLinkError("invalid asset type")
    pm = manager or get_project_manager()

    def _sync() -> dict[str, Any]:
        def _mutate(entry: dict[str, Any]) -> None:
            for field in (
                GLOBAL_ASSET_ID_FIELD,
                MATCHED_GLOBAL_ASSET_ID_FIELD,
                GLOBAL_ASSET_IMAGE_USAGE_FIELD,
                GLOBAL_ASSET_VOICE_SOURCE_FIELD,
            ):
                entry.pop(field, None)

        with project_change_source(source):
            return pm.update_asset_entry(resource_type, project_name, resource_id, _mutate)

    return await asyncio.to_thread(_sync)


async def configure_project_asset_link(
    project_name: str,
    resource_type: str,
    resource_id: str,
    *,
    image_usage: str | None = None,
    voice_source: str | None = None,
    manager: ProjectManager | None = None,
    source: ProjectChangeSource = "webui",
    session_factory=None,
) -> tuple[dict[str, Any], Any]:
    if image_usage is not None and image_usage not in GLOBAL_ASSET_IMAGE_USAGES:
        raise ProjectAssetLinkError("image_usage must be main or reference")
    if resource_type == "character" and image_usage is not None:
        raise ProjectAssetLinkError("character image slots must use move_character_main_to_reference")
    if voice_source is not None and voice_source not in GLOBAL_ASSET_VOICE_SOURCES:
        raise ProjectAssetLinkError("voice_source must be reference_audio, voice_id, or none")
    pm = manager or get_project_manager()
    project = await asyncio.to_thread(pm.load_project, project_name)
    bucket = {"character": "characters", "scene": "scenes", "prop": "props"}.get(resource_type)
    entry = project.get(bucket, {}).get(resource_id) if bucket else None
    asset_id = (
        entry.get(GLOBAL_ASSET_ID_FIELD) or entry.get(MATCHED_GLOBAL_ASSET_ID_FIELD)
        if isinstance(entry, dict)
        else None
    )
    if not isinstance(asset_id, str) or not asset_id:
        raise ProjectAssetLinkError("project asset is not linked")
    asset = await _asset(asset_id, session_factory)
    if asset is None:
        raise ProjectAssetLinkNotFound(asset_id)
    if voice_source is not None:
        if resource_type != "character":
            raise ProjectAssetLinkError("voice source only applies to characters")
        if voice_source == "reference_audio" and not asset.audio_path:
            raise ProjectAssetLinkError("linked asset has no reference audio")
        if voice_source == "voice_id" and not asset.voice_id:
            raise ProjectAssetLinkError("linked asset has no TTS voice ID")

    def _sync() -> dict[str, Any]:
        def _mutate(current: dict[str, Any]) -> None:
            current[GLOBAL_ASSET_ID_FIELD] = asset.id
            current[MATCHED_GLOBAL_ASSET_ID_FIELD] = asset.id
            if image_usage is not None:
                current[GLOBAL_ASSET_IMAGE_USAGE_FIELD] = image_usage
            if voice_source is not None:
                current[GLOBAL_ASSET_VOICE_SOURCE_FIELD] = voice_source

        with project_change_source(source):
            return pm.update_asset_entry(resource_type, project_name, resource_id, _mutate)

    return await asyncio.to_thread(_sync), asset


__all__ = [
    "LinkedCharacterSheetBackfill",
    "ProjectAssetLinkError",
    "ProjectAssetLinkNotFound",
    "backfill_linked_character_sheets",
    "configure_project_asset_link",
    "link_project_asset",
    "materialize_linked_character_sheet",
    "unlink_project_asset",
]
