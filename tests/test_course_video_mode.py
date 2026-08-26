from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from lib.course_video import (
    compose_explanation_keyframe,
    derive_course_dependencies,
    validate_course_assets,
)
from lib.profile_manifest import resolve_profile_files_for_mode
from lib.project_manager import ProjectManager
from lib.script_models import ReferenceVideoScript
from lib.workflow_rules import workflow_rule

pytestmark = pytest.mark.unit


def _unit(unit_id: str, unit_type: str, **extra: object) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "text": "课程单元正文",
        "duration_seconds": 5,
        **extra,
    }


def test_course_dependency_chains_reset_at_each_story() -> None:
    units = derive_course_dependencies(
        [
            _unit("E1U01", "opening"),
            _unit("E1U02", "story"),
            _unit("E1U03", "explanation"),
            _unit("E1U04", "explanation"),
            _unit("E1U05", "story"),
            _unit("E1U06", "explanation"),
            _unit("E1U07", "closing"),
        ]
    )
    assert [unit.get("depends_on_unit_id") for unit in units] == [
        None,
        None,
        "E1U02",
        "E1U03",
        None,
        "E1U05",
        None,
    ]


def test_course_requires_exactly_one_main_lecturer() -> None:
    validate_course_assets(
        {
            "characters": {
                "老师": {"course_role": "main_lecturer"},
                "嘉宾": {"course_role": "guest_lecturer"},
                "演员": {"course_role": "actor"},
            }
        }
    )
    with pytest.raises(ValueError, match="exactly one main lecturer"):
        validate_course_assets({"characters": {"甲": {"course_role": "actor"}}})


def test_course_script_validates_bookends_and_consecutive_explanations() -> None:
    script = ReferenceVideoScript.model_validate(
        {
            "title": "第一课",
            "content_mode": "course",
            "video_units": [
                _unit("E1U01", "opening", scenes=["教室"], presenters=["老师"]),
                _unit("E1U02", "story", scenes=["村庄"], characters=["学员"]),
                _unit(
                    "E1U03",
                    "explanation",
                    presenters=["老师"],
                    depends_on_unit_id="E1U02",
                ),
                _unit(
                    "E1U04",
                    "explanation",
                    presenters=["老师", "嘉宾"],
                    depends_on_unit_id="E1U03",
                ),
                _unit("E1U05", "closing", scenes=["教室"], presenters=["老师"]),
            ],
        }
    )
    assert script.video_units[3].depends_on_unit_id == "E1U03"


def test_explanation_keyframe_materializes_square_lecturer_and_overlay(tmp_path: Path) -> None:
    (tmp_path / "characters").mkdir()
    (tmp_path / "frames").mkdir()
    Image.new("RGB", (600, 900), "royalblue").save(tmp_path / "characters" / "teacher.png")
    Image.new("RGB", (1280, 720), "darkgreen").save(tmp_path / "frames" / "tail.png")
    relative = compose_explanation_keyframe(
        project_dir=tmp_path,
        tail_frame=tmp_path / "frames" / "tail.png",
        presenter_names=["老师"],
        characters={"老师": {"character_sheet": "characters/teacher.png"}},
        unit_id="E1U03",
    )
    assert relative == "keyframes/course/E1U03_composite.png"
    assert Image.open(tmp_path / "characters" / "lecturers" / "老师.png").size == (1024, 1024)
    assert Image.open(tmp_path / relative).size == (1280, 720)


def test_course_project_has_no_source_kind_and_uses_reference_video(tmp_path: Path) -> None:
    pm = ProjectManager(str(tmp_path / "projects"))
    pm.create_project("course", content_mode="course")
    pm.create_project_metadata(
        "course",
        "课程",
        "",
        "course",
        extras={"generation_mode": "reference_video"},
    )
    project = pm.load_project("course")
    assert "source_kind" not in project
    assert project["generation_mode"] == "reference_video"
    assert project["episodes"] == [
        {"episode": 1, "title": "", "script_file": "scripts/episode_1.json", "source_file": None}
    ]


def test_course_profile_and_workflow_variant_exist() -> None:
    repo = Path(__file__).resolve().parents[1]
    mapping = resolve_profile_files_for_mode(repo / "agent_runtime_profile", "course")
    assert mapping["CLAUDE.md"] == "CLAUDE.course.md"
    assert mapping[".claude/skills/video-workflow/SKILL.md"].endswith("SKILL.course.md")
    rule = workflow_rule("course", "reference_video")
    assert rule.preprocessor == "split-reference-video-units"
    assert not next(step for step in rule.steps if step.id == "episode_plan").applicable
