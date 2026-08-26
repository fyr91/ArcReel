from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lib.project_migrations.runner import migrate_project_dir
from lib.project_migrations.v7_to_v8_artifact_manifest import migrate_v7_to_v8
from server.auth import CurrentUserInfo, get_current_user
from server.error_handlers import register_error_handlers
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fakes import fake_reference_request_projector


def _unit(unit_id: str, unit_type: str, **extra: object) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "text": "课程正文",
        "duration_seconds": 5,
        "generated_assets": {},
        **extra,
    }


@pytest.fixture
def course_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    projects_root = tmp_path / "projects"
    project_dir = projects_root / "course-demo"
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 7,
                "title": "课程",
                "content_mode": "course",
                "generation_mode": "reference_video",
                "grid_storyboard": False,
                "characters": {
                    "老师": {"description": "主讲", "course_role": "main_lecturer"},
                    "学员": {"description": "演员", "course_role": "actor"},
                },
                "scenes": {"教室": {"description": "课程教室"}, "村庄": {"description": "故事场景"}},
                "props": {},
                "episodes": [{"episode": 1, "title": "第一课", "script_file": "scripts/episode_1.json"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_dir / "scripts" / "episode_1.json").write_text(
        json.dumps(
            {
                "episode": 1,
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
                    _unit("E1U04", "closing", scenes=["教室"], presenters=["老师"]),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    migrate_v7_to_v8(project_dir)
    migrate_project_dir(project_dir)

    from lib.project_manager import ProjectManager
    from server.routers import reference_videos as router_mod

    pm = ProjectManager(projects_root)
    monkeypatch.setattr(router_mod, "get_project_manager", lambda: pm)
    monkeypatch.setattr(router_mod, "tts_task_in_progress", AsyncMock(return_value=False))
    monkeypatch.setattr(
        router_mod,
        "project_reference_unit_request",
        fake_reference_request_projector(durations=(5,)),
    )

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router_mod.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.dependency_overrides[get_current_user] = lambda: CurrentUserInfo(id="u1", sub="test", role="admin")
    client = TestClient(app)
    client.project_dir = project_dir  # type: ignore[attr-defined]
    return client


@pytest.mark.integration
def test_course_add_unit_reuses_crud_and_inserts_before_closing(course_client: TestClient) -> None:
    response = course_client.post(
        "/api/v1/projects/course-demo/reference-videos/episodes/1/units",
        json={"prompt": "第二段故事", "duration_seconds": 5, "unit_type": "story", "scenes": ["村庄"]},
    )
    assert response.status_code == 201, response.text

    units = course_client.get("/api/v1/projects/course-demo/reference-videos/episodes/1/units").json()["units"]
    assert [unit["unit_type"] for unit in units] == ["opening", "story", "explanation", "story", "closing"]
    assert units[2]["video_dependency"]["source_unit_id"] == "E1U02"
    assert units[3]["video_dependency"] is None


@pytest.mark.integration
def test_course_bookend_patch_updates_both_units_atomically(course_client: TestClient) -> None:
    response = course_client.patch(
        "/api/v1/projects/course-demo/reference-videos/episodes/1/course-bookends",
        json={"scenes": ["教室"], "characters": ["学员"], "presenters": ["老师"]},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["units"]) == 2
    for unit in response.json()["units"]:
        assert unit["scenes"] == ["教室"]
        assert unit["characters"] == ["学员"]
        assert unit["presenters"] == ["老师"]


@pytest.mark.integration
def test_course_explanation_generation_waits_for_confirmed_base_videos(course_client: TestClient) -> None:
    response = course_client.post(
        "/api/v1/projects/course-demo/reference-videos/episodes/1/units/E1U03/generate",
        json={},
    )
    assert response.status_code == 409
    assert "确认" in response.json()["detail"]


@pytest.mark.integration
def test_course_cannot_confirm_a_video_that_does_not_exist(course_client: TestClient) -> None:
    response = course_client.post("/api/v1/projects/course-demo/reference-videos/episodes/1/units/E1U02/confirm-video")
    assert response.status_code == 409
    assert "尚未生成" in response.json()["detail"]
