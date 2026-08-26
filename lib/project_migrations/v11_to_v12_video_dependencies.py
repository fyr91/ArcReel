"""v11→v12: replace route-specific dependency fields with video_dependency."""

from __future__ import annotations

import copy
import shutil
import time
from pathlib import Path
from typing import Any

from lib.course_video import derive_course_dependencies
from lib.json_io import atomic_write_json, load_json
from lib.path_safety import safe_join
from lib.script_review import REFERENCE_VIDEO_STEP1_FILENAME, episode_drafts_dir
from lib.video_dependency import derive_drama_video_dependencies, validate_video_dependencies

_TARGET_VERSION = 12


def _ensure_backup(path: Path) -> None:
    if any(path.parent.glob(f"{path.name}.bak.v11-*")):
        return
    shutil.copy2(path, path.with_name(f"{path.name}.bak.v11-{time.time_ns()}"))


def _episode_entries(project_dir: Path, project: dict[str, Any]) -> list[tuple[Path, int]]:
    result: list[tuple[Path, int]] = []
    for entry in project.get("episodes") or []:
        if not isinstance(entry, dict):
            raise ValueError("project.episodes entries must be objects")
        episode = entry.get("episode")
        script_file = entry.get("script_file")
        if type(episode) is not int or episode <= 0 or not isinstance(script_file, str) or not script_file:
            raise ValueError("project episode binding is invalid")
        result.append((safe_join(project_dir, script_file), episode))
    return result


def _migrate_reference_units(payload: dict[str, Any], *, content_mode: str, draft: bool) -> dict[str, Any]:
    key = "units" if draft else "video_units"
    units = payload.get(key)
    if not isinstance(units, list):
        raise ValueError(f"{key} must be an array")
    migrated = copy.deepcopy(payload)
    copied = [dict(unit) if isinstance(unit, dict) else unit for unit in units]
    if any(not isinstance(unit, dict) for unit in copied):
        raise ValueError(f"{key} entries must be objects")
    if content_mode == "course":
        migrated[key] = derive_course_dependencies(copied)
    else:
        for unit in copied:
            unit.pop("depends_on_unit_id", None)
            unit.setdefault("video_dependency", None)
        migrated[key] = copied
    validate_video_dependencies(migrated[key])
    return migrated


def _migrate_storyboard_drama(payload: dict[str, Any]) -> dict[str, Any]:
    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        raise ValueError("scenes must be an array")
    migrated = copy.deepcopy(payload)
    migrated["scenes"] = derive_drama_video_dependencies(scenes, break_field="segment_break")
    validate_video_dependencies(migrated["scenes"])
    return migrated


def migrate_v11_to_v12(project_dir: Path) -> None:
    project_file = Path(project_dir) / "project.json"
    if not project_file.is_file():
        return
    project = load_json(project_file)
    if not isinstance(project, dict):
        raise ValueError("project.json must contain an object")
    if int(project.get("schema_version") or 0) >= _TARGET_VERSION:
        return

    plans: list[tuple[Path, dict[str, Any]]] = []
    generation_mode = project.get("generation_mode")
    content_mode = str(project.get("content_mode") or "drama")
    for script_path, episode in _episode_entries(project_dir, project):
        if script_path.is_file():
            payload = load_json(script_path)
            if not isinstance(payload, dict):
                raise ValueError(f"script {script_path.name} must contain an object")
            if generation_mode == "reference_video":
                plans.append((script_path, _migrate_reference_units(payload, content_mode=content_mode, draft=False)))
            elif content_mode == "drama":
                plans.append((script_path, _migrate_storyboard_drama(payload)))
        if generation_mode == "reference_video":
            draft_path = episode_drafts_dir(project_dir, episode) / REFERENCE_VIDEO_STEP1_FILENAME
            if draft_path.is_file():
                payload = load_json(draft_path)
                if not isinstance(payload, dict):
                    raise ValueError(f"draft {draft_path.name} must contain an object")
                plans.append((draft_path, _migrate_reference_units(payload, content_mode=content_mode, draft=True)))

    for path, _payload in plans:
        _ensure_backup(path)
    for path, payload in plans:
        atomic_write_json(path, payload)
    migrated_project = copy.deepcopy(project)
    migrated_project["schema_version"] = _TARGET_VERSION
    atomic_write_json(project_file, migrated_project)


__all__ = ["migrate_v11_to_v12"]
