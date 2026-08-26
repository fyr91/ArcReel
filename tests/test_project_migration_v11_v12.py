from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.project_migrations.v11_to_v12_video_dependencies import migrate_v11_to_v12

pytestmark = pytest.mark.unit


def _unit(unit_id: str, unit_type: str, **extra: object) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "text": "课程正文",
        "duration_seconds": 5,
        **extra,
    }


def test_v11_course_dependency_is_migrated_to_shared_shape(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 11,
                "generation_mode": "reference_video",
                "content_mode": "course",
                "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}],
            }
        ),
        encoding="utf-8",
    )
    script_path = tmp_path / "scripts" / "episode_1.json"
    script_path.write_text(
        json.dumps(
            {
                "title": "课",
                "content_mode": "course",
                "video_units": [
                    _unit("E1U01", "opening", scenes=["教室"], presenters=["老师"]),
                    _unit("E1U02", "story"),
                    _unit("E1U03", "explanation", presenters=["老师"], depends_on_unit_id="E1U02"),
                    _unit("E1U04", "closing", scenes=["教室"], presenters=["老师"]),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    migrate_v11_to_v12(tmp_path)

    project = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    script = json.loads(script_path.read_text(encoding="utf-8"))
    assert project["schema_version"] == 12
    assert script["video_units"][2]["video_dependency"] == {
        "source_unit_id": "E1U02",
        "relation": "continuation",
        "audio_policy": "none",
    }
    assert all("depends_on_unit_id" not in unit for unit in script["video_units"])


def test_v11_storyboard_drama_derives_dependency_from_segment_break(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 11,
                "generation_mode": "storyboard",
                "content_mode": "drama",
                "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}],
            }
        ),
        encoding="utf-8",
    )
    scene = {
        "duration_seconds": 5,
        "characters_in_scene": [],
        "scenes": [],
        "props": [],
        "image_prompt": {
            "scene": "人物站在庭院中",
            "composition": {"shot_type": "Wide Shot", "lighting": "day", "ambiance": "calm"},
        },
        "video_prompt": {"action": "move", "camera_motion": "Static", "ambiance_audio": ""},
        "utterances": [],
    }
    script_path = tmp_path / "scripts" / "episode_1.json"
    script_path.write_text(
        json.dumps(
            {
                "title": "剧",
                "content_mode": "drama",
                "scenes": [
                    {**scene, "scene_id": "E1S01", "segment_break": False},
                    {**scene, "scene_id": "E1S02", "segment_break": False},
                    {**scene, "scene_id": "E1S03", "segment_break": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    migrate_v11_to_v12(tmp_path)

    scenes = json.loads(script_path.read_text(encoding="utf-8"))["scenes"]
    assert scenes[1]["video_dependency"]["source_unit_id"] == "E1S01"
    assert scenes[2]["video_dependency"] is None
