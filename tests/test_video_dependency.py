from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from lib.script_models import ReferenceVideoScript
from lib.video_dependency import (
    derive_course_video_dependencies,
    derive_drama_video_dependencies,
    validate_video_dependencies,
)
from lib.visual_artifact_provenance import build_storyboard_video_artifact_visual_basis
from server.agent_runtime.sdk_tools.enqueue_videos import _build_reference_specs
from server.agent_runtime.sdk_tools.text_generation import _build_reference_units_from_flat

pytestmark = pytest.mark.unit


def test_drama_local_continuity_is_bound_to_final_unit_order() -> None:
    units = derive_drama_video_dependencies(
        [
            {"unit_id": "E1U01", "continues_previous": False},
            {"unit_id": "E1U02", "continues_previous": True},
            {"unit_id": "E1U03", "continues_previous": False},
        ]
    )
    assert units[0]["video_dependency"] is None
    assert units[1]["video_dependency"]["source_unit_id"] == "E1U01"
    assert units[2]["video_dependency"] is None
    assert all("continues_previous" not in unit for unit in units)


def test_course_and_drama_share_the_same_dependency_shape() -> None:
    course = derive_course_video_dependencies(
        [
            {"unit_id": "E1U01", "unit_type": "story"},
            {"unit_id": "E1U02", "unit_type": "explanation"},
        ]
    )
    dependency = course[1]["video_dependency"]
    assert dependency == {
        "source_unit_id": "E1U01",
        "relation": "continuation",
        "audio_policy": "none",
    }


def test_dependency_must_point_backward() -> None:
    with pytest.raises(ValueError, match="earlier unit"):
        validate_video_dependencies(
            [
                {
                    "unit_id": "E1U01",
                    "video_dependency": {
                        "source_unit_id": "E1U02",
                        "relation": "continuation",
                        "audio_policy": "none",
                    },
                },
                {"unit_id": "E1U02", "video_dependency": None},
            ]
        )


def test_persisted_drama_script_rejects_forward_dependency() -> None:
    with pytest.raises(ValidationError, match="earlier unit"):
        ReferenceVideoScript.model_validate(
            {
                "title": "剧情",
                "content_mode": "drama",
                "video_units": [
                    {
                        "unit_id": "E1U01",
                        "text": "第一段",
                        "duration_seconds": 5,
                        "video_dependency": {"source_unit_id": "E1U02"},
                    },
                    {"unit_id": "E1U02", "text": "第二段", "duration_seconds": 5},
                ],
            }
        )


def test_reference_split_materializes_drama_dependency_after_assigning_ids() -> None:
    units = _build_reference_units_from_flat(
        [
            {
                "text": "人物推开门。",
                "source_text": "人物推开门。",
                "duration_seconds": 5,
                "continues_previous": False,
            },
            {
                "text": "人物继续走入房间。",
                "source_text": "人物继续走入房间。",
                "duration_seconds": 5,
                "continues_previous": True,
            },
        ],
        {"content_mode": "drama", "characters": {}, "scenes": {}, "props": {}, "products": {}},
        episode=3,
        max_refs=None,
    )
    assert [unit["unit_id"] for unit in units] == ["E3U01", "E3U02"]
    assert units[1]["video_dependency"]["source_unit_id"] == "E3U01"


def test_reference_batch_materializes_same_batch_queue_edge() -> None:
    units = [
        {"unit_id": "E1U01", "text": "第一段画面", "duration_seconds": 5, "video_dependency": None},
        {
            "unit_id": "E1U02",
            "text": "第二段画面",
            "duration_seconds": 5,
            "video_dependency": {
                "source_unit_id": "E1U01",
                "relation": "continuation",
                "audio_policy": "none",
            },
        },
    ]
    specs, _order, refused = _build_reference_specs(
        units=units,
        script_filename="scripts/episode_1.json",
        skip_ids=None,
        content_mode="drama",
    )
    assert refused == []
    assert specs[1].dependency_resource_id == "E1U01"
    assert specs[1].dependency_group == "video-dependency-scripts/episode_1.json"


def test_source_version_change_changes_downstream_visual_basis(tmp_path: Path) -> None:
    storyboard = tmp_path / "storyboard.png"
    storyboard.write_bytes(b"storyboard")
    evidence = {
        "source_unit_id": "E1S01",
        "relation": "continuation",
        "audio_policy": "none",
        "source_version": 1,
        "source_execution_task_id": "task-1",
        "guide_frames": 22,
        "source_media": "original_video",
    }
    first = build_storyboard_video_artifact_visual_basis(
        resource_id="E1S02",
        visual_prompt="continue",
        storyboard_image=storyboard,
        end_frame_image=None,
        aspect_ratio="16:9",
        video_dependency=evidence,
    )
    second = build_storyboard_video_artifact_visual_basis(
        resource_id="E1S02",
        visual_prompt="continue",
        storyboard_image=storyboard,
        end_frame_image=None,
        aspect_ratio="16:9",
        video_dependency={**evidence, "source_version": 2, "source_execution_task_id": "task-2"},
    )
    assert first.digest != second.digest
