from __future__ import annotations

import json

import pytest

from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.episode_overview import confirm_episode_overview_tool
from server.routers import projects
from server.services.episode_overview_review import (
    EpisodeOverviewRevisionConflictError,
    confirm_episode_overview,
)

pytestmark = pytest.mark.unit


def _manager_with_draft(tmp_path) -> tuple[ProjectManager, str]:
    manager = ProjectManager(tmp_path / "projects")
    manager.create_project("course")
    manager.create_project_metadata(
        "course",
        "Course",
        content_mode="course",
        extras={"generation_mode": "reference_video"},
    )
    source_path = manager.get_project_path("course") / "source" / "lesson.md"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("景泰蓝制作课程", encoding="utf-8")

    def _bind(project: dict) -> None:
        project["episodes"][0]["source_file"] = "source/lesson.md"

    manager.update_project("course", _bind)
    project = manager.load_project("course")
    revision = compute_source_revision(
        manager.get_project_path("course"),
        project,
        SourceScope(kind="files", files=["source/lesson.md"]),
    ).revision
    assert revision is not None

    def _draft(current: dict) -> None:
        entry = current["episodes"][0]
        entry["overview"] = {
            "synopsis": "AI 初稿",
            "genre": "工艺",
            "theme": "传承",
            "world_setting": "课堂",
            "language": "zh",
            "generated_at": "2026-08-27T00:00:00+00:00",
            "source_revision": revision,
        }
        entry["source_revision"] = revision
        entry["overview_status"] = "draft"

    manager.update_project("course", _draft)
    return manager, revision


def _reviewed() -> dict[str, str]:
    return {
        "synopsis": "  人工确认后的概述  ",
        "genre": " 传统工艺 ",
        "theme": " 非遗传承 ",
        "world_setting": " 北京工艺课堂 ",
    }


def test_confirm_episode_overview_saves_review_and_marks_confirmed(tmp_path) -> None:
    manager, revision = _manager_with_draft(tmp_path)

    result = confirm_episode_overview(
        manager,
        "course",
        1,
        _reviewed(),
        expected_source_revision=revision,
    )

    assert result["overview_status"] == "confirmed"
    saved = manager.load_project("course")
    entry = saved["episodes"][0]
    assert entry["overview_status"] == "confirmed"
    assert entry["overview"]["synopsis"] == "人工确认后的概述"
    assert entry["overview"]["language"] == "zh"
    assert entry["overview"]["source_revision"] == revision
    assert saved["overview"]["synopsis"] == "人工确认后的概述"
    assert "source_revision" not in saved["overview"]


def test_confirm_episode_overview_rejects_changed_source_without_writing(tmp_path) -> None:
    manager, revision = _manager_with_draft(tmp_path)
    source_path = manager.get_project_path("course") / "source" / "lesson.md"
    source_path.write_text("源文已经变化", encoding="utf-8")

    with pytest.raises(EpisodeOverviewRevisionConflictError):
        confirm_episode_overview(
            manager,
            "course",
            1,
            _reviewed(),
            expected_source_revision=revision,
        )

    entry = manager.load_project("course")["episodes"][0]
    assert entry["overview_status"] == "draft"
    assert entry["overview"]["synopsis"] == "AI 初稿"


@pytest.mark.asyncio
async def test_web_route_confirms_episode_overview_through_shared_operation(tmp_path, monkeypatch) -> None:
    manager, revision = _manager_with_draft(tmp_path)
    monkeypatch.setattr(projects, "get_project_manager", lambda: manager)
    request = projects.ConfirmEpisodeOverviewRequest(
        **_reviewed(),
        expected_source_revision=revision,
    )

    result = await projects.confirm_course_episode_overview(
        "course",
        1,
        request,
        lambda key, **_kwargs: key,
    )

    assert result["success"] is True
    assert manager.load_project("course")["episodes"][0]["overview_status"] == "confirmed"


@pytest.mark.asyncio
async def test_agent_confirms_episode_overview_through_shared_operation(tmp_path) -> None:
    manager, revision = _manager_with_draft(tmp_path)
    context = ToolContext(
        project_name="course",
        projects_root=manager.projects_root,
        pm=manager,
    )

    result = await confirm_episode_overview_tool(context).handler(
        {
            "episode": 1,
            "overview": _reviewed(),
            "expected_source_revision": revision,
        }
    )

    assert result.get("is_error") is not True
    payload = json.loads(result["content"][0]["text"])
    assert payload["overview_status"] == "confirmed"
    assert manager.load_project("course")["episodes"][0]["overview_status"] == "confirmed"
