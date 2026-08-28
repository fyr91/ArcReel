from __future__ import annotations

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.patch_episode_meta import patch_episode_meta_tool
from server.services.episode_metadata import update_episode_metadata

pytestmark = pytest.mark.unit


def _course_manager(tmp_path) -> ProjectManager:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("course")
    manager.create_project_metadata(
        "course",
        "Course",
        content_mode="course",
        extras={"generation_mode": "reference_video"},
    )
    return manager


def test_course_episode_title_can_be_updated_before_formal_script_exists(tmp_path) -> None:
    manager = _course_manager(tmp_path)

    updated = update_episode_metadata(manager, "course", 1, {"title": "  景泰蓝制作工艺  "})

    assert updated == {"episode": 1, "title": "景泰蓝制作工艺"}
    assert manager.load_project("course")["episodes"][0]["title"] == "景泰蓝制作工艺"
    assert not (manager.get_project_path("course") / "scripts" / "episode_1.json").exists()


def test_course_episode_without_formal_script_rejects_non_title_metadata(tmp_path) -> None:
    manager = _course_manager(tmp_path)

    with pytest.raises(FileNotFoundError):
        update_episode_metadata(
            manager,
            "course",
            1,
            {"title": "新标题", "hook": "不应落盘"},
        )

    episode = manager.load_project("course")["episodes"][0]
    assert episode["title"] == ""
    assert "hook" not in episode


def test_course_episode_narrator_can_be_set_before_formal_script_exists(tmp_path) -> None:
    manager = _course_manager(tmp_path)
    manager.upsert_assets("course", "characters", {"讲师": {"description": "主讲人"}})

    updated = update_episode_metadata(manager, "course", 1, {"narrator_character": "讲师"})

    assert updated == {"episode": 1, "narrator_character": "讲师"}
    assert manager.load_project("course")["episodes"][0]["narrator_character"] == "讲师"
    assert not (manager.get_project_path("course") / "scripts" / "episode_1.json").exists()


@pytest.mark.asyncio
async def test_agent_can_rename_course_episode_before_formal_script_exists(tmp_path) -> None:
    manager = _course_manager(tmp_path)
    context = ToolContext(
        project_name="course",
        projects_root=manager.projects_root,
        pm=manager,
    )

    result = await patch_episode_meta_tool(context).handler(
        {"episode": 1, "updates": {"title": "课程单集标题"}},
    )

    assert result.get("is_error") is not True
    assert manager.load_project("course")["episodes"][0]["title"] == "课程单集标题"
