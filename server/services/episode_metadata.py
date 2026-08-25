"""Shared episode metadata update used by both Web and Agent boundaries."""

from __future__ import annotations

import copy
from typing import Any

from lib.project_manager import ProjectManager

EDITABLE_EPISODE_METADATA_FIELDS = ("title", "hook", "outline")
_OUTLINE_FIELDS = ("story_beats", "next_episode_teaser")


class EpisodeMetadataNotFoundError(LookupError):
    """The requested episode is absent or has no bound formal script."""


def normalize_episode_metadata_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the public episode metadata patch shape."""

    if not isinstance(updates, dict) or not updates:
        raise ValueError("updates 必须是非空字段映射")
    unknown = sorted(set(updates) - set(EDITABLE_EPISODE_METADATA_FIELDS))
    if unknown:
        raise ValueError(f"分集元数据字段 {unknown!r} 不在白名单 {list(EDITABLE_EPISODE_METADATA_FIELDS)} 内")

    normalized: dict[str, Any] = {}
    if "title" in updates:
        title = updates["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title 必须是非空字符串")
        normalized["title"] = title.strip()

    if "hook" in updates:
        hook = updates["hook"]
        if hook is not None and not isinstance(hook, str):
            raise ValueError("hook 必须是字符串或 null")
        normalized["hook"] = hook.strip() if isinstance(hook, str) else None

    if "outline" in updates:
        outline = updates["outline"]
        if outline is None:
            normalized["outline"] = None
        else:
            if not isinstance(outline, dict):
                raise ValueError("outline 必须是对象或 null")
            unknown_outline = sorted(set(outline) - set(_OUTLINE_FIELDS))
            if unknown_outline:
                raise ValueError(f"outline 字段 {unknown_outline!r} 不在白名单 {list(_OUTLINE_FIELDS)} 内")
            normalized_outline: dict[str, Any] = {}
            if "story_beats" in outline:
                beats = outline["story_beats"]
                if not isinstance(beats, list) or any(not isinstance(beat, str) or not beat.strip() for beat in beats):
                    raise ValueError("outline.story_beats 必须是非空字符串数组")
                normalized_outline["story_beats"] = [beat.strip() for beat in beats]
            if "next_episode_teaser" in outline:
                teaser = outline["next_episode_teaser"]
                if not isinstance(teaser, str):
                    raise ValueError("outline.next_episode_teaser 必须是字符串")
                normalized_outline["next_episode_teaser"] = teaser.strip()
            normalized["outline"] = normalized_outline

    return normalized


def update_episode_metadata(
    manager: ProjectManager,
    project_name: str,
    episode: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Atomically update formal-script metadata and its project episode mirror."""

    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode 必须是正整数")
    normalized = normalize_episode_metadata_updates(updates)

    def _resolve(project: dict[str, Any]) -> str:
        episodes = project.get("episodes") or []
        meta = next((entry for entry in episodes if entry.get("episode") == episode), None)
        if meta is None or not meta.get("script_file"):
            raise EpisodeMetadataNotFoundError(f"第 {episode} 集不存在或尚无正式文稿")
        return str(meta["script_file"])

    with manager.locked_episode_script(project_name, _resolve) as script:
        for field, value in normalized.items():
            script[field] = copy.deepcopy(value)

    return {"episode": episode, **copy.deepcopy(normalized)}


__all__ = [
    "EDITABLE_EPISODE_METADATA_FIELDS",
    "EpisodeMetadataNotFoundError",
    "normalize_episode_metadata_updates",
    "update_episode_metadata",
]
