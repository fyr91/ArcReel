"""Shared episode metadata update used by both Web and Agent boundaries."""

from __future__ import annotations

import copy
from typing import Any

from lib.narrator import NARRATOR_CHARACTER_FIELD, normalize_narrator_character, set_episode_narrator
from lib.path_safety import safe_join
from lib.project_manager import EpisodeScriptReboundError, ProjectManager

EDITABLE_EPISODE_METADATA_FIELDS = ("title", "hook", "outline", NARRATOR_CHARACTER_FIELD)
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

    if NARRATOR_CHARACTER_FIELD in updates:
        narrator = updates[NARRATOR_CHARACTER_FIELD]
        if narrator is not None and (not isinstance(narrator, str) or not narrator.strip()):
            raise ValueError("narrator_character 必须是非空角色名或 null")
        normalized[NARRATOR_CHARACTER_FIELD] = narrator.strip() if isinstance(narrator, str) else None

    return normalized


def update_episode_metadata(
    manager: ProjectManager,
    project_name: str,
    episode: int,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Atomically update episode metadata across formal-script and course pre-script states."""

    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode 必须是正整数")
    normalized = normalize_episode_metadata_updates(updates)

    def _resolve(project: dict[str, Any]) -> str:
        episodes = project.get("episodes") or []
        meta = next((entry for entry in episodes if entry.get("episode") == episode), None)
        if meta is None or not meta.get("script_file"):
            raise EpisodeMetadataNotFoundError(f"第 {episode} 集不存在或尚无正式文稿")
        if NARRATOR_CHARACTER_FIELD in normalized:
            normalized[NARRATOR_CHARACTER_FIELD] = normalize_narrator_character(
                project,
                normalized[NARRATOR_CHARACTER_FIELD],
            )
        return str(meta["script_file"])

    try:
        with manager.locked_episode_script(project_name, _resolve) as script:
            for field, value in normalized.items():
                script[field] = copy.deepcopy(value)
    except FileNotFoundError as missing_script:
        # 课程分集在解析完成、正式 step2 文稿尚未生成时，title 的真相源只能暂存于
        # episodes[] 导览条目。脚本一旦存在仍必须走上面的正式文稿 → 镜像链路；hook / outline
        # 也从不允许在无文稿状态下制造第二份真相源。
        if not set(normalized) <= {"title", NARRATOR_CHARACTER_FIELD}:
            raise
        load_readonly = getattr(manager, "load_project_readonly", manager.load_project)
        project = load_readonly(project_name)
        entries = project.get("episodes") or []
        meta = next(
            (entry for entry in entries if isinstance(entry, dict) and entry.get("episode") == episode),
            None,
        )
        if meta is None:
            raise EpisodeMetadataNotFoundError(f"第 {episode} 集不存在") from missing_script
        if project.get("content_mode") != "course" or not meta.get("script_file"):
            raise
        if NARRATOR_CHARACTER_FIELD in normalized:
            normalized[NARRATOR_CHARACTER_FIELD] = normalize_narrator_character(
                project,
                normalized[NARRATOR_CHARACTER_FIELD],
            )

        norm = manager.normalize_script_filename(str(meta["script_file"]))
        script_path = safe_join(manager.get_project_path(project_name) / "scripts", norm)
        captured: dict[str, Any] = {}

        # 与正式脚本创建/保存共用同一把文件锁，并在项目锁内复核文件仍不存在。若脚本恰在
        # 两阶段之间出现，拒绝本次 ledger-only 写入，由调用方重试后走正式文稿链路。
        with manager.file_lock(script_path):

            def _mutate(current: dict[str, Any]) -> None:
                current_entries = current.get("episodes") or []
                current_meta = next(
                    (entry for entry in current_entries if isinstance(entry, dict) and entry.get("episode") == episode),
                    None,
                )
                if current.get("content_mode") != "course" or current_meta is None:
                    raise EpisodeMetadataNotFoundError(f"第 {episode} 集不存在")
                current_script = current_meta.get("script_file")
                if not current_script or manager.normalize_script_filename(str(current_script)) != norm:
                    raise EpisodeScriptReboundError(f"episode {episode} script binding changed")
                if script_path.is_file():
                    raise EpisodeScriptReboundError(f"episode {episode} script appeared during title update")
                captured["episode"] = episode
                if "title" in normalized:
                    current_meta["title"] = normalized["title"]
                    captured["title"] = normalized["title"]
                if NARRATOR_CHARACTER_FIELD in normalized:
                    captured[NARRATOR_CHARACTER_FIELD] = set_episode_narrator(
                        current,
                        episode,
                        normalized[NARRATOR_CHARACTER_FIELD],
                    )

            manager.update_project(project_name, _mutate)

        return captured

    return {"episode": episode, **copy.deepcopy(normalized)}


__all__ = [
    "EDITABLE_EPISODE_METADATA_FIELDS",
    "EpisodeMetadataNotFoundError",
    "normalize_episode_metadata_updates",
    "update_episode_metadata",
]
