"""Canonical video-unit dependency derivation and validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

VIDEO_DEPENDENCY_RELATION = "continuation"
VIDEO_DEPENDENCY_AUDIO_POLICIES = frozenset({"none", "continue"})


def continuation_dependency(source_unit_id: str, *, audio_policy: str = "none") -> dict[str, str]:
    source = str(source_unit_id or "").strip()
    if not source:
        raise ValueError("video dependency source_unit_id must not be empty")
    if audio_policy not in VIDEO_DEPENDENCY_AUDIO_POLICIES:
        raise ValueError(f"unsupported video dependency audio_policy: {audio_policy!r}")
    return {
        "source_unit_id": source,
        "relation": VIDEO_DEPENDENCY_RELATION,
        "audio_policy": audio_policy,
    }


def dependency_source_unit_id(unit: Mapping[str, Any]) -> str | None:
    raw = unit.get("video_dependency")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("video_dependency must be an object or null")
    source = raw.get("source_unit_id")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("video_dependency.source_unit_id must be a non-empty string")
    return source.strip()


def derive_course_video_dependencies(units: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Recompute the course story/explanation continuation chain from final order."""

    result: list[dict[str, Any]] = []
    chain_tail: str | None = None
    story_seen = False
    for raw in units:
        unit = dict(raw)
        unit_type = unit.get("unit_type", "story")
        unit_id = str(unit.get("unit_id") or "")
        if unit_type == "story":
            story_seen = True
            chain_tail = unit_id
            unit["video_dependency"] = None
        elif unit_type == "explanation":
            if not story_seen or not chain_tail:
                raise ValueError(f"explanation unit {unit_id or '<missing>'} must follow a story unit")
            unit["video_dependency"] = continuation_dependency(chain_tail)
            chain_tail = unit_id
        else:
            unit["video_dependency"] = None
        unit.pop("depends_on_unit_id", None)
        result.append(unit)
    validate_video_dependencies(result)
    return result


def derive_drama_video_dependencies(
    units: Sequence[Mapping[str, Any]],
    *,
    continuity_field: str = "continues_previous",
    break_field: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve local drama continuity intent to stable preceding-unit IDs."""

    result: list[dict[str, Any]] = []
    previous_id: str | None = None
    for raw in units:
        unit = dict(raw)
        unit_id = str(unit.get("unit_id") or unit.get("scene_id") or "").strip()
        continues = bool(unit.get(continuity_field))
        if break_field is not None:
            continues = not bool(unit.get(break_field))
        unit["video_dependency"] = continuation_dependency(previous_id) if previous_id and continues else None
        unit.pop(continuity_field, None)
        unit.pop("depends_on_unit_id", None)
        result.append(unit)
        previous_id = unit_id
    validate_video_dependencies(result)
    return result


def validate_video_dependencies(units: Sequence[Mapping[str, Any]]) -> None:
    """Require one backward direct dependency at most, with no self/cycle references."""

    seen: set[str] = set()
    for raw in units:
        unit_id = str(raw.get("unit_id") or raw.get("scene_id") or "").strip()
        if not unit_id:
            raise ValueError("video dependency validation requires a stable unit ID")
        if unit_id in seen:
            raise ValueError(f"duplicate video unit ID: {unit_id}")
        source = dependency_source_unit_id(raw)
        if source == unit_id:
            raise ValueError(f"video unit {unit_id} cannot depend on itself")
        if source is not None and source not in seen:
            raise ValueError(f"video unit {unit_id} dependency must reference an earlier unit: {source}")
        seen.add(unit_id)


__all__ = [
    "VIDEO_DEPENDENCY_AUDIO_POLICIES",
    "VIDEO_DEPENDENCY_RELATION",
    "continuation_dependency",
    "dependency_source_unit_id",
    "derive_course_video_dependencies",
    "derive_drama_video_dependencies",
    "validate_video_dependencies",
]
