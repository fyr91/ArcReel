"""Atomic exact-text replacements for formal reference-video manuscripts."""

from __future__ import annotations

import copy
from typing import Any

from lib.project_manager import ProjectManager
from lib.script_batch_edit import (
    ScriptBatchEditCommand,
    ScriptBatchEditor,
    ScriptBatchEditResult,
)


class ReferenceTextReplacementError(ValueError):
    """One requested exact replacement cannot be applied unambiguously."""

    def __init__(self, index: int, message: str) -> None:
        super().__init__(f"replacements[{index}]: {message}")
        self.index = index


def replace_reference_script_text(
    manager: ProjectManager,
    project_name: str,
    episode: int,
    expected_revision: str,
    replacements: list[dict[str, Any]],
) -> ScriptBatchEditResult:
    """Apply exact unit-text / Keyframe-description replacements in one CAS commit.

    Every ``old`` fragment must occur exactly once in its target. The service
    builds ordinary ``update`` operations from a read snapshot, then delegates
    schema, reference, speech, manifest, binding, and revision admission to the
    canonical :class:`ScriptBatchEditor`.
    """

    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode 必须是正整数")
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("replacements 必须是非空数组")

    project = manager.load_project_readonly(project_name)
    episodes = project.get("episodes") or []
    meta = next(
        (entry for entry in episodes if isinstance(entry, dict) and entry.get("episode") == episode),
        None,
    )
    if meta is None or not isinstance(meta.get("script_file"), str):
        raise FileNotFoundError(f"episode {episode} has no formal script")
    script_file = manager.normalize_script_filename(meta["script_file"])
    candidate = copy.deepcopy(manager.load_script(project_name, script_file))
    units = candidate.get("video_units")
    if project.get("generation_mode") != "reference_video" or not isinstance(units, list):
        raise ValueError("当前正式文稿不是 reference_video Video Unit 剧本")

    unit_by_id = {
        str(unit.get("unit_id")): unit
        for unit in units
        if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str)
    }
    affected_order: list[str] = []
    affected_fields: dict[str, set[str]] = {}

    for index, replacement in enumerate(replacements):
        if not isinstance(replacement, dict):
            raise ReferenceTextReplacementError(index, "条目必须是对象")
        unknown = sorted(set(replacement) - {"unit_id", "field", "keyframe_id", "old", "new"})
        if unknown:
            raise ReferenceTextReplacementError(index, f"未知字段 {unknown!r}")
        unit_id = replacement.get("unit_id")
        field = replacement.get("field")
        old = replacement.get("old")
        new = replacement.get("new")
        if not all(isinstance(value, str) for value in (unit_id, field, old, new)):
            raise ReferenceTextReplacementError(index, "unit_id/field/old/new 必须是字符串")
        if not old or old == new:
            raise ReferenceTextReplacementError(index, "old 必须非空且 new 必须与 old 不同")
        unit = unit_by_id.get(unit_id)
        if unit is None:
            raise ReferenceTextReplacementError(index, f"未找到 Video Unit {unit_id}")

        target: dict[str, Any]
        target_key: str
        operation_field: str
        if field in {"text", "storyboard_description"}:
            if "keyframe_id" in replacement:
                raise ReferenceTextReplacementError(index, f"{field} 替换不得提供 keyframe_id")
            target = unit
            target_key = field
            operation_field = field
        elif field == "keyframe_description":
            keyframe_id = replacement.get("keyframe_id")
            if not isinstance(keyframe_id, str) or not keyframe_id:
                raise ReferenceTextReplacementError(index, "keyframe_description 必须提供 keyframe_id")
            keyframes = unit.get("keyframes")
            if not isinstance(keyframes, list):
                raise ReferenceTextReplacementError(index, f"{unit_id} 没有 Keyframes")
            target = next(
                (
                    keyframe
                    for keyframe in keyframes
                    if isinstance(keyframe, dict) and keyframe.get("keyframe_id") == keyframe_id
                ),
                None,
            )
            if target is None:
                raise ReferenceTextReplacementError(index, f"{unit_id} 未找到 Keyframe {keyframe_id}")
            target_key = "description"
            operation_field = "keyframes"
        else:
            raise ReferenceTextReplacementError(
                index,
                "field 仅支持 text、storyboard_description 或 keyframe_description",
            )

        value = target.get(target_key)
        if not isinstance(value, str):
            raise ReferenceTextReplacementError(index, f"目标字段 {target_key} 不是字符串")
        occurrences = value.count(old)
        if occurrences != 1:
            raise ReferenceTextReplacementError(index, f"old 在目标中出现 {occurrences} 次，必须恰好 1 次")
        target[target_key] = value.replace(old, new, 1)
        if unit_id not in affected_fields:
            affected_order.append(unit_id)
            affected_fields[unit_id] = set()
        affected_fields[unit_id].add(operation_field)

    operations = []
    for unit_id in affected_order:
        unit = unit_by_id[unit_id]
        fields = {field: copy.deepcopy(unit[field]) for field in sorted(affected_fields[unit_id])}
        operations.append({"op": "update", "id": unit_id, "fields": fields})

    command = ScriptBatchEditCommand.model_validate(
        {
            "episode": episode,
            "expected_script_file": script_file,
            "expected_revision": expected_revision,
            "operations": operations,
        }
    )
    return ScriptBatchEditor(manager).execute(project_name, command)


__all__ = ["ReferenceTextReplacementError", "replace_reference_script_text"]
