"""Shared batch operation for Keyframe-description asset mentions."""

from __future__ import annotations

from typing import Any

from lib.asset_types import ASSET_SPECS, normalize_asset_bucket
from lib.project_manager import ProjectManager
from lib.reference_video.text_parser import wrap_registered_asset_mentions


class EpisodeReferenceScriptNotFoundError(LookupError):
    """The requested episode is absent or has no bound formal script."""


class _NoMentionChanges(RuntimeError):
    pass


def normalize_episode_keyframe_mentions(
    manager: ProjectManager,
    project_name: str,
    episode: int,
) -> dict[str, int]:
    """Normalize all literal asset references in an episode's Keyframes at once.

    Project assets and the bound formal script are resolved under the same
    canonical script -> project lock transaction. The operation changes only
    ``video_units[].keyframes[].description`` and never invents or rewrites
    visual content.
    """

    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode 必须是正整数")

    asset_names: set[str] = set()
    project_generation_mode: str | None = None

    def _resolve(project: dict[str, Any]) -> str:
        nonlocal project_generation_mode
        project_generation_mode = project.get("generation_mode")
        asset_names.clear()
        for spec in ASSET_SPECS.values():
            asset_names.update(normalize_asset_bucket(project.get(spec.bucket_key)).keys())
        episodes = project.get("episodes") or []
        meta = next(
            (entry for entry in episodes if isinstance(entry, dict) and entry.get("episode") == episode),
            None,
        )
        if meta is None or not meta.get("script_file"):
            raise EpisodeReferenceScriptNotFoundError(f"第 {episode} 集不存在或尚无正式文稿")
        return str(meta["script_file"])

    result = {"episode": episode, "units_changed": 0, "keyframes_changed": 0, "replacements": 0}
    try:
        with manager.locked_episode_script(project_name, _resolve) as script:
            if project_generation_mode != "reference_video" or not isinstance(script.get("video_units"), list):
                raise ValueError("当前正式文稿不是 reference_video Video Unit 剧本")
            for unit in script["video_units"]:
                if not isinstance(unit, dict) or not isinstance(unit.get("keyframes"), list):
                    continue
                unit_changed = False
                for keyframe in unit["keyframes"]:
                    if not isinstance(keyframe, dict) or not isinstance(keyframe.get("description"), str):
                        continue
                    normalized, replacements = wrap_registered_asset_mentions(keyframe["description"], asset_names)
                    if normalized == keyframe["description"]:
                        continue
                    keyframe["description"] = normalized
                    result["keyframes_changed"] += 1
                    result["replacements"] += replacements
                    unit_changed = True
                if unit_changed:
                    result["units_changed"] += 1
            if result["keyframes_changed"] == 0:
                raise _NoMentionChanges
    except _NoMentionChanges:
        pass
    return result


__all__ = ["EpisodeReferenceScriptNotFoundError", "normalize_episode_keyframe_mentions"]
