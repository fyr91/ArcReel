"""Evidence-based classification of a HyperFrames assembly versus an authored edit."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from lib.path_safety import safe_join

_EPSILON_SECONDS = 0.003
_VISUAL_TREATMENT_PATTERNS = (
    re.compile(r"\bdata-arcreel-edit-operation\s*=", re.IGNORECASE),
    re.compile(r"\bdata-color-grading\s*=", re.IGNORECASE),
    re.compile(r"\bdata-transition\s*=", re.IGNORECASE),
    re.compile(r"\bgsap\.timeline\s*\(", re.IGNORECASE),
    re.compile(r"\bwindow\.__timelines\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class HyperframesEditingAnalysis:
    state: str
    picture_edit_count: int
    source_unit_count: int
    video_clip_count: int
    timing_changes: int
    split_ranges: int
    reordered_units: int
    overlapping_handoffs: int
    retimed_clips: int
    visual_treatments: int
    audio_automations: int

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "picture_edit_count": self.picture_edit_count,
            "source_unit_count": self.source_unit_count,
            "video_clip_count": self.video_clip_count,
            "timing_changes": self.timing_changes,
            "split_ranges": self.split_ranges,
            "reordered_units": self.reordered_units,
            "overlapping_handoffs": self.overlapping_handoffs,
            "retimed_clips": self.retimed_clips,
            "visual_treatments": self.visual_treatments,
            "audio_automations": self.audio_automations,
        }


class _CompositionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.videos: list[dict[str, str]] = []
        self.audio_automations = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag.lower() == "video" and values.get("data-unit-id"):
            self.videos.append(values)
        if tag.lower() == "audio" and values.get("data-automation"):
            self.audio_automations += 1


def _number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def analyze_hyperframes_editing(workspace: Path) -> HyperframesEditingAnalysis:
    """Classify structural picture edits without trusting prose in the edit plan.

    Removing captions, adding music, or rewriting ``EDITING_PLAN.md`` is useful
    editorial work, but it does not turn the picture assembly into an AI edit.
    The state changes only when the composition contains evidence of source-range,
    timing, overlap, retime, reorder, or visual-treatment decisions.
    """

    manifest = json.loads(safe_join(workspace, "manifest.json", require_file=True).read_text(encoding="utf-8"))
    source = safe_join(workspace, "index.html", require_file=True).read_text(encoding="utf-8")
    units = manifest.get("units")
    if not isinstance(units, list):
        units = []

    expected: list[tuple[str, float, float]] = []
    cursor = 0.0
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("unit_id"), str):
            continue
        video = unit.get("video")
        if not isinstance(video, dict):
            continue
        duration = _number(video.get("duration_microseconds")) / 1_000_000
        expected.append((unit["unit_id"], cursor, duration))
        cursor += duration

    parser = _CompositionParser()
    parser.feed(source)
    clips_by_unit: dict[str, list[dict[str, str]]] = {}
    for clip in parser.videos:
        clips_by_unit.setdefault(clip["data-unit-id"], []).append(clip)

    split_ranges = sum(max(0, len(clips) - 1) for clips in clips_by_unit.values())
    timing_changes = 0
    retimed_clips = 0
    intervals: list[tuple[float, float, str]] = []
    for clip in parser.videos:
        start = _number(clip.get("data-start"))
        duration = _number(clip.get("data-duration"))
        intervals.append((start, start + max(0.0, duration), clip["data-unit-id"]))
        if abs(_number(clip.get("data-playback-rate"), 1.0) - 1.0) > _EPSILON_SECONDS:
            retimed_clips += 1

    for unit_id, baseline_start, baseline_duration in expected:
        clips = clips_by_unit.get(unit_id, [])
        if len(clips) != 1:
            timing_changes += 1
            continue
        clip = clips[0]
        if (
            abs(_number(clip.get("data-start")) - baseline_start) > _EPSILON_SECONDS
            or abs(_number(clip.get("data-duration")) - baseline_duration) > _EPSILON_SECONDS
            or abs(_number(clip.get("data-media-start"))) > _EPSILON_SECONDS
        ):
            timing_changes += 1

    ordered_units = [unit_id for _, _, unit_id in sorted(intervals)]
    expected_units = [unit_id for unit_id, _, _ in expected]
    reordered_units = sum(left != right for left, right in zip(ordered_units, expected_units, strict=False)) + abs(
        len(ordered_units) - len(expected_units)
    )

    overlapping_handoffs = 0
    latest_end = -math.inf
    for start, end, _ in sorted(intervals):
        if start < latest_end - _EPSILON_SECONDS:
            overlapping_handoffs += 1
        latest_end = max(latest_end, end)

    visual_treatments = sum(1 for pattern in _VISUAL_TREATMENT_PATTERNS if pattern.search(source))
    picture_edit_count = (
        timing_changes + split_ranges + reordered_units + overlapping_handoffs + retimed_clips + visual_treatments
    )
    if expected and not parser.videos:
        state = "unknown"
    else:
        state = "edited" if picture_edit_count else "assembly_draft"
    return HyperframesEditingAnalysis(
        state=state,
        picture_edit_count=picture_edit_count,
        source_unit_count=len(expected),
        video_clip_count=len(parser.videos),
        timing_changes=timing_changes,
        split_ranges=split_ranges,
        reordered_units=reordered_units,
        overlapping_handoffs=overlapping_handoffs,
        retimed_clips=retimed_clips,
        visual_treatments=visual_treatments,
        audio_automations=parser.audio_automations,
    )


__all__ = ["HyperframesEditingAnalysis", "analyze_hyperframes_editing"]
