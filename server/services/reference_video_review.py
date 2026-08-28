"""Shared reference-video review operations for Web and Agent callers."""

from __future__ import annotations

import asyncio
from typing import Any

from lib.generation_admission import generation_admission_lock
from lib.i18n import _ as translate
from lib.project_manager import ProjectManager, is_reference_video_project
from lib.version_manager import VersionManager
from lib.video_backends.base import VideoCapabilityError


class ReferenceVideoReviewUnavailable(VideoCapabilityError):
    """The requested video unit cannot be confirmed in its current state."""

    def __str__(self) -> str:
        return translate(self.code, **self.params)


def _script_file(project: dict[str, Any], episode: int) -> str:
    meta = next(
        (item for item in project.get("episodes") or [] if isinstance(item, dict) and item.get("episode") == episode),
        None,
    )
    script_file = meta.get("script_file") if isinstance(meta, dict) else None
    if not isinstance(script_file, str) or not script_file:
        raise ReferenceVideoReviewUnavailable("ref_episode_not_found", episode=episode)
    return script_file


def _unit(script: dict[str, Any], unit_id: str) -> dict[str, Any]:
    unit = next(
        (item for item in script.get("video_units") or [] if isinstance(item, dict) and item.get("unit_id") == unit_id),
        None,
    )
    if unit is None:
        raise ReferenceVideoReviewUnavailable("ref_unit_not_found", unit_id=unit_id)
    return unit


async def confirm_reference_video(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    unit_id: str,
) -> dict[str, Any]:
    """Confirm the exact current reference-video version under the unit write guard."""

    try:
        project = await asyncio.to_thread(project_manager.load_project, project_name)
    except FileNotFoundError as exc:
        raise ReferenceVideoReviewUnavailable("project_not_found", name=project_name) from exc
    if not is_reference_video_project(project):
        raise ReferenceVideoReviewUnavailable("ref_not_reference_video_mode")
    script_file = _script_file(project, episode)

    async with generation_admission_lock(
        project_name=project_name,
        script_file=script_file,
        resource_id=unit_id,
    ):
        try:
            script = await asyncio.to_thread(project_manager.load_script, project_name, script_file)
        except FileNotFoundError as exc:
            raise ReferenceVideoReviewUnavailable("script_not_found", name=script_file) from exc
        unit = _unit(script, unit_id)
        assets = unit.get("generated_assets")
        if not isinstance(assets, dict) or not assets.get("video_clip"):
            raise ReferenceVideoReviewUnavailable("video_confirm_not_generated")

        versions = VersionManager(project_manager.get_project_path(project_name))
        version = await asyncio.to_thread(versions.get_current_version, "reference_videos", unit_id)
        if version <= 0:
            raise ReferenceVideoReviewUnavailable("video_confirm_version_missing")

        with project_manager.locked_script(project_name, script_file, validate=True) as current:
            target = _unit(current, unit_id)
            current_assets = target.get("generated_assets")
            if not isinstance(current_assets, dict) or not current_assets.get("video_clip"):
                raise ReferenceVideoReviewUnavailable("video_confirm_not_generated")
            target["video_review_status"] = "confirmed"
            target["confirmed_video_version"] = version

    return {
        "success": True,
        "episode": episode,
        "unit_id": unit_id,
        "confirmed_video_version": version,
        "content_mode": project.get("content_mode"),
    }


__all__ = [
    "ReferenceVideoReviewUnavailable",
    "confirm_reference_video",
]
