"""Project and episode narrator-character binding semantics."""

import pytest

from lib.asset_rename import rewrite_payload_references
from lib.narrator import (
    NarratorSettingsError,
    resolve_effective_narrator,
    set_episode_narrator,
    set_project_narrator,
)
from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.patch_project import patch_project_tool

pytestmark = pytest.mark.unit


def _project(**overrides):
    project = {
        "content_mode": "drama",
        "generation_mode": "reference_video",
        "characters": {"旁白甲": {}, "旁白乙": {}},
        "episodes": [{"episode": 1, "title": "第一集", "script_file": "scripts/episode_1.json"}],
    }
    project.update(overrides)
    return project


def test_episode_override_wins_and_clear_restores_project_inheritance():
    project = _project()
    assert set_project_narrator(project, " 旁白甲 ") == "旁白甲"
    assert resolve_effective_narrator(project, 1) == "旁白甲"

    assert set_episode_narrator(project, 1, "旁白乙") == "旁白乙"
    assert resolve_effective_narrator(project, 1) == "旁白乙"

    assert set_episode_narrator(project, 1, None) is None
    assert "narrator_character" not in project["episodes"][0]
    assert resolve_effective_narrator(project, 1) == "旁白甲"


def test_narrator_must_be_a_registered_character():
    with pytest.raises(NarratorSettingsError) as exc_info:
        set_project_narrator(_project(), "路人")
    assert exc_info.value.code == "narrator_character_not_found"
    assert exc_info.value.params == {"name": "路人"}


def test_narrator_setting_is_rejected_outside_native_reference_video_routes():
    with pytest.raises(NarratorSettingsError) as exc_info:
        set_project_narrator(_project(generation_mode="storyboard"), "旁白甲")
    assert exc_info.value.code == "narrator_reference_video_only"


def test_character_reference_rewrite_includes_script_narrator_binding():
    payload = {"narrator_character": "旁白甲", "video_units": []}
    assert rewrite_payload_references(payload, "character", "旁白甲", "讲述者") == 1
    assert payload["narrator_character"] == "讲述者"


def _manager_with_narrator_bindings(tmp_path) -> ProjectManager:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("demo")
    manager.create_project_metadata(
        "demo",
        "Demo",
        "Anime",
        "drama",
        extras={"generation_mode": "reference_video"},
    )
    manager.upsert_assets("demo", "characters", {"旁白甲": {"description": "讲述者"}})
    manager.save_script(
        "demo",
        {
            "episode": 1,
            "title": "第一集",
            "content_mode": "drama",
            "generation_mode": "reference_video",
            "summary": "摘要",
            "novel": {"title": "故事", "chapter": "第一章"},
            "duration_seconds": 3,
            "narrator_character": "旁白甲",
            "video_units": [
                {
                    "unit_id": "E1U01",
                    "text": "{从前有座山。}",
                    "duration_seconds": 3,
                }
            ],
        },
        "episode_1.json",
    )

    def _set_default(project: dict) -> None:
        project["narrator_character"] = "旁白甲"

    manager.update_project("demo", _set_default)
    return manager


def test_character_rename_updates_project_episode_and_script_narrator_bindings(tmp_path):
    manager = _manager_with_narrator_bindings(tmp_path)
    manager.rename_asset("demo", "characters", "旁白甲", "讲述者")

    project = manager.load_project("demo")
    assert project["narrator_character"] == "讲述者"
    assert project["episodes"][0]["narrator_character"] == "讲述者"
    assert manager.load_script("demo", "episode_1.json")["narrator_character"] == "讲述者"


def test_character_delete_clears_project_and_episode_narrator_bindings(tmp_path):
    manager = _manager_with_narrator_bindings(tmp_path)
    manager.delete_asset("demo", "characters", "旁白甲")

    project = manager.load_project("demo")
    assert "narrator_character" not in project
    assert "narrator_character" not in project["episodes"][0]
    assert resolve_effective_narrator(project, 1) is None


@pytest.mark.asyncio
async def test_agent_project_patch_uses_the_same_narrator_validation(tmp_path):
    manager = _manager_with_narrator_bindings(tmp_path)
    manager.update_project("demo", lambda project: project.pop("narrator_character", None))
    context = ToolContext(project_name="demo", projects_root=manager.projects_root, pm=manager)

    result = await patch_project_tool(context).handler({"settings": {"narrator_character": "旁白甲"}})

    assert result.get("is_error") is not True
    assert manager.load_project("demo")["narrator_character"] == "旁白甲"
