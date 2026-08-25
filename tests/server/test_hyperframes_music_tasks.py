"""Shared Web/Agent queue boundary for HyperFrames background music."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.services.hyperframes_music import HyperframesBackgroundMusic, HyperframesMusicUnavailable
from server.services.hyperframes_music_tasks import (
    enqueue_hyperframes_bgm_task,
    execute_hyperframes_bgm_task,
)

pytestmark = pytest.mark.unit


def _project(tmp_path: Path) -> ProjectManager:
    projects = tmp_path / "projects"
    project = projects / "demo"
    workspace = project / "hyperframes" / "episode_01"
    workspace.mkdir(parents=True)
    (project / "project.json").write_text("{}", encoding="utf-8")
    (workspace / "index.html").write_text("<div></div>", encoding="utf-8")
    (workspace / "manifest.json").write_text("{}", encoding="utf-8")
    return ProjectManager(projects)


async def test_enqueue_uses_one_shared_audio_task_contract(tmp_path: Path) -> None:
    pm = _project(tmp_path)
    calls = []

    class _Queue:
        async def enqueue_task(self, **kwargs):
            calls.append(kwargs)
            return {"task_id": "bgm-1", "status": "queued"}

    result = await enqueue_hyperframes_bgm_task(
        pm,
        "demo",
        1,
        direction="  restrained folk instrumental  ",
        seed=7,
        source="webui",
        user_id="user-1",
        queue=_Queue(),
    )

    assert result["task_id"] == "bgm-1"
    assert result["resource_id"] == "episode_01"
    assert calls == [
        {
            "project_name": "demo",
            "task_type": "hyperframes_bgm",
            "media_type": "audio",
            "resource_id": "episode_01",
            "payload": {"episode": 1, "direction": "restrained folk instrumental", "seed": 7},
            "source": "webui",
            "user_id": "user-1",
            "provider_id": "croco",
        }
    ]


async def test_enqueue_requires_prepared_workspace(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    project = projects / "demo"
    project.mkdir(parents=True)
    (project / "project.json").write_text("{}", encoding="utf-8")

    with pytest.raises(HyperframesMusicUnavailable, match="prepare"):
        await enqueue_hyperframes_bgm_task(
            ProjectManager(projects),
            "demo",
            1,
            direction="calm",
            source="agent",
        )


async def test_executor_passes_durable_task_and_provider_job_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pm = _project(tmp_path)
    workspace = pm.get_project_path("demo") / "hyperframes" / "episode_01"
    calls = []

    class _MusicService:
        def __init__(self, received_pm):
            assert received_pm is pm

        async def generate(self, project_name, episode, **kwargs):
            calls.append((project_name, episode, kwargs))
            return HyperframesBackgroundMusic(
                episode=1,
                path=workspace / "media" / "bgm.mp3",
                relative_path="media/bgm.mp3",
                metadata_path="background-music.json",
                duration_seconds=10,
                actual_duration_seconds=10,
                volume=0.15,
                seed=7,
                html_snippet="<audio></audio>",
            )

    monkeypatch.setattr("server.services.hyperframes_music_tasks.get_project_manager", lambda: pm)
    monkeypatch.setattr("server.services.hyperframes_music_tasks.HyperframesMusicService", _MusicService)

    result = await execute_hyperframes_bgm_task(
        "demo",
        "episode_01",
        {"episode": 1, "direction": "calm", "seed": 7},
        task_id="task-1",
        provider_job_id="job-1",
    )

    assert result["relative_path"] == "media/bgm.mp3"
    assert calls == [
        (
            "demo",
            1,
            {"direction": "calm", "seed": 7, "task_id": "task-1", "provider_job_id": "job-1"},
        )
    ]
