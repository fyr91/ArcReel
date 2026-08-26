"""Runtime services for course-video explanation chains."""

from __future__ import annotations

import asyncio
from typing import Any

from lib.course_video import compose_explanation_keyframe
from lib.path_safety import safe_join
from lib.project_manager import ProjectManager
from lib.thumbnail import extract_video_last_frame
from lib.video_dependency import dependency_source_unit_id


def _find_unit(script: dict[str, Any], unit_id: str) -> dict[str, Any]:
    for unit in script.get("video_units") or []:
        if isinstance(unit, dict) and unit.get("unit_id") == unit_id:
            return unit
    raise ValueError(f"course dependency unit not found: {unit_id}")


async def prepare_explanation_keyframe(
    pm: ProjectManager,
    *,
    project_name: str,
    script_file: str,
    project: dict[str, Any],
    script: dict[str, Any],
    unit_id: str,
) -> dict[str, Any]:
    """Materialize an explanation reference keyframe from its dependency tail."""

    if project.get("content_mode") != "course":
        return _find_unit(script, unit_id)
    unit = _find_unit(script, unit_id)
    if unit.get("unit_type") != "explanation":
        return unit
    predecessor_id = dependency_source_unit_id(unit)
    if not isinstance(predecessor_id, str) or not predecessor_id:
        raise ValueError(f"explanation unit {unit_id} has no dependency")
    predecessor = _find_unit(script, predecessor_id)
    predecessor_assets = predecessor.get("generated_assets")
    predecessor_clip = predecessor_assets.get("video_clip") if isinstance(predecessor_assets, dict) else None
    if not isinstance(predecessor_clip, str) or not predecessor_clip:
        raise ValueError(f"explanation dependency {predecessor_id} has no completed video")
    if predecessor.get("unit_type") == "story" and predecessor.get("video_review_status") != "confirmed":
        raise ValueError(f"story dependency {predecessor_id} must be confirmed before explanation generation")

    project_dir = pm.get_project_path(project_name)
    video_path = safe_join(project_dir, predecessor_clip, require_file=True)
    tail_path = safe_join(project_dir, f"keyframes/course/{predecessor_id}_tail.png")
    extracted = await extract_video_last_frame(video_path, tail_path)
    if extracted is None:
        raise ValueError(f"could not extract tail frame from {predecessor_id}")
    relative = await asyncio.to_thread(
        compose_explanation_keyframe,
        project_dir=project_dir,
        tail_frame=extracted,
        presenter_names=list(unit.get("presenters") or []),
        characters=project.get("characters") or {},
        unit_id=unit_id,
    )

    def _write() -> dict[str, Any]:
        with pm.locked_script(project_name, script_file, validate=True) as current:
            target = _find_unit(current, unit_id)
            frames = target.get("keyframes")
            if not isinstance(frames, list) or not frames or not isinstance(frames[0], dict):
                raise ValueError(f"explanation unit {unit_id} has no formal entry keyframe")
            frames[0]["image_path"] = relative
            frames[0]["generation_input_changed"] = False
            assets = target.setdefault("generated_assets", {})
            if not isinstance(assets, dict):
                raise ValueError(f"explanation unit {unit_id} generated_assets is invalid")
            assets["course_composite_keyframe"] = relative
            target["video_review_status"] = "pending_review"
            target["confirmed_video_version"] = None
            return dict(target)

    return await asyncio.to_thread(_write)


__all__ = ["prepare_explanation_keyframe"]
