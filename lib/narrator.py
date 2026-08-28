"""Default narrator bindings for native-audio reference-video projects.

The stored value is a project character name, not a TTS voice id.  A project
default may be overridden by one episode; an absent episode field inherits the
project default.  Rendering keeps bare ``{voiceover}`` as off-screen speech and
uses this binding only to select the character reference audio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lib.asset_types import asset_name_comparison_key, resolve_asset_key

NARRATOR_CHARACTER_FIELD = "narrator_character"


@dataclass(frozen=True)
class NarratorSettingsError(ValueError):
    """A stable, localizable narrator-setting validation failure."""

    code: str
    params: dict[str, Any]

    def __str__(self) -> str:
        return f"{self.code}: {self.params}"


def _require_supported_project(project: dict[str, Any]) -> None:
    if project.get("content_mode") not in {"drama", "course"} or project.get("generation_mode") != "reference_video":
        raise NarratorSettingsError("narrator_reference_video_only", {})


def normalize_narrator_character(project: dict[str, Any], value: object) -> str | None:
    """Return the canonical registered character key, or ``None`` to clear."""

    _require_supported_project(project)
    if value is None:
        return None
    if not isinstance(value, str):
        raise NarratorSettingsError("narrator_character_invalid", {})
    name = asset_name_comparison_key(value)
    if not name:
        return None
    key = resolve_asset_key(project.get("characters"), name)
    if key is None:
        raise NarratorSettingsError("narrator_character_not_found", {"name": name})
    return key


def set_project_narrator(project: dict[str, Any], value: object) -> str | None:
    """Set or clear the project default narrator in-place."""

    narrator = normalize_narrator_character(project, value)
    if narrator is None:
        project.pop(NARRATOR_CHARACTER_FIELD, None)
    else:
        project[NARRATOR_CHARACTER_FIELD] = narrator
    return narrator


def set_episode_narrator(project: dict[str, Any], episode: int, value: object) -> str | None:
    """Set one episode override in-place; clearing restores project inheritance."""

    narrator = normalize_narrator_character(project, value)
    entries = project.get("episodes")
    entry = next(
        (item for item in entries or [] if isinstance(item, dict) and item.get("episode") == episode),
        None,
    )
    if entry is None:
        raise NarratorSettingsError("episode_not_found", {"episode": episode})
    if narrator is None:
        entry.pop(NARRATOR_CHARACTER_FIELD, None)
    else:
        entry[NARRATOR_CHARACTER_FIELD] = narrator
    return narrator


def resolve_effective_narrator(project: dict[str, Any], episode: int | None = None) -> str | None:
    """Resolve episode override → project default, normalized for asset matching."""

    value: object = None
    if episode is not None:
        entries = project.get("episodes")
        entry = next(
            (item for item in entries or [] if isinstance(item, dict) and item.get("episode") == episode),
            None,
        )
        if entry is not None and NARRATOR_CHARACTER_FIELD in entry:
            value = entry.get(NARRATOR_CHARACTER_FIELD)
    if value is None:
        value = project.get(NARRATOR_CHARACTER_FIELD)
    if not isinstance(value, str):
        return None
    normalized = asset_name_comparison_key(value)
    if not normalized:
        return None
    return resolve_asset_key(project.get("characters"), normalized)


def clear_narrator_references(project: dict[str, Any], character_name: str) -> int:
    """Clear project/episode narrator bindings that point at a deleted character."""

    target = asset_name_comparison_key(character_name)
    cleared = 0
    value = project.get(NARRATOR_CHARACTER_FIELD)
    if isinstance(value, str) and asset_name_comparison_key(value) == target:
        project.pop(NARRATOR_CHARACTER_FIELD, None)
        cleared += 1
    for entry in project.get("episodes") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get(NARRATOR_CHARACTER_FIELD)
        if isinstance(value, str) and asset_name_comparison_key(value) == target:
            entry.pop(NARRATOR_CHARACTER_FIELD, None)
            cleared += 1
    return cleared


def rename_narrator_references(project: dict[str, Any], old_name: str, new_name: str) -> int:
    """Rename project/episode narrator bindings after a character asset rename."""

    target = asset_name_comparison_key(old_name)
    renamed = 0
    value = project.get(NARRATOR_CHARACTER_FIELD)
    if isinstance(value, str) and asset_name_comparison_key(value) == target and value != new_name:
        project[NARRATOR_CHARACTER_FIELD] = new_name
        renamed += 1
    for entry in project.get("episodes") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get(NARRATOR_CHARACTER_FIELD)
        if isinstance(value, str) and asset_name_comparison_key(value) == target and value != new_name:
            entry[NARRATOR_CHARACTER_FIELD] = new_name
            renamed += 1
    return renamed


__all__ = [
    "NARRATOR_CHARACTER_FIELD",
    "NarratorSettingsError",
    "clear_narrator_references",
    "normalize_narrator_character",
    "rename_narrator_references",
    "resolve_effective_narrator",
    "set_episode_narrator",
    "set_project_narrator",
]
