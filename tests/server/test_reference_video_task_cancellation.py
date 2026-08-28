from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from server.services.reference_video_task_cancellation import (
    ReferenceVideoTaskCancellationUnavailable,
    cancel_reference_video_tasks,
)

pytestmark = pytest.mark.unit


class _Queue:
    def __init__(self, tasks: list[dict[str, Any]]) -> None:
        self.tasks = tasks
        self.cancelled: list[str] = []

    async def list_tasks(self, **filters: Any) -> dict[str, Any]:
        items = [
            task for task in self.tasks if all(task.get(key) == value for key, value in filters.items() if key in task)
        ]
        return {"items": items, "page": 1, "page_size": filters["page_size"], "total": len(items)}

    async def cancel_task(self, task_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.cancelled.append(task_id)
        task = next(item for item in self.tasks if item["task_id"] == task_id)
        if task["status"] == "running":
            return {"cancelled": [], "cancelling": [task_id], "skipped_terminal": []}
        return {
            "cancelled": [{**task, "status": "cancelled"}],
            "cancelling": [],
            "skipped_terminal": [],
        }


def _project(tmp_path: Path) -> ProjectManager:
    projects = tmp_path / "projects"
    project_path = projects / "demo"
    (project_path / "scripts").mkdir(parents=True)
    atomic_write_json(
        project_path / "project.json",
        {
            "schema_version": 12,
            "title": "Demo",
            "content_mode": "drama",
            "generation_mode": "reference_video",
            "episodes": [
                {"episode": 1, "script_file": "scripts/episode_1.json"},
                {"episode": 2, "script_file": "scripts/episode_2.json"},
            ],
        },
    )
    for episode in (1, 2):
        atomic_write_json(
            project_path / "scripts" / f"episode_{episode}.json",
            {
                "episode": episode,
                "content_mode": "drama",
                "video_units": [
                    {"unit_id": f"E{episode}U01", "text": "shot", "duration_seconds": 6},
                    {"unit_id": f"E{episode}U02", "text": "shot", "duration_seconds": 6},
                ],
            },
        )
    return ProjectManager(projects)


def _task(
    task_id: str,
    *,
    task_type: str = "reference_video",
    resource_id: str = "E1U01",
    status: str = "queued",
    script_file: str = "scripts/episode_1.json",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "project_name": "demo",
        "task_type": task_type,
        "resource_id": resource_id,
        "status": status,
        "script_file": script_file,
        "queued_at": task_id,
    }


async def test_unit_scope_cancels_generation_and_hd_only_for_the_exact_unit(tmp_path: Path) -> None:
    queue = _Queue(
        [
            _task("generation", status="running"),
            _task("hd", task_type="reference_video_refine"),
            _task("other-unit", resource_id="E1U02"),
            _task("other-episode", resource_id="E2U01", script_file="episode_2.json"),
            _task("audio", task_type="tts"),
        ]
    )

    result = await cancel_reference_video_tasks(
        _project(tmp_path),
        "demo",
        1,
        unit_id="E1U01",
        user_id="u1",
        queue=queue,  # type: ignore[arg-type]
    )

    assert result["matched_task_ids"] == ["generation", "hd"]
    assert result["affected_count"] == 2
    assert queue.cancelled == ["generation", "hd"]


async def test_episode_scope_is_idempotent_and_does_not_cross_episode(tmp_path: Path) -> None:
    queue = _Queue(
        [
            _task("one"),
            _task("two", resource_id="E1U02", status="cancelling"),
            _task("other-episode", resource_id="E2U01", script_file="episode_2.json"),
        ]
    )

    result = await cancel_reference_video_tasks(
        _project(tmp_path),
        "demo",
        1,
        user_id="u1",
        queue=queue,  # type: ignore[arg-type]
    )

    assert result["matched_task_ids"] == ["one", "two"]
    assert result["already_cancelling"] == ["two"]
    assert result["affected_count"] == 2
    assert queue.cancelled == ["one"]


async def test_unit_scope_rejects_unknown_unit(tmp_path: Path) -> None:
    with pytest.raises(ReferenceVideoTaskCancellationUnavailable) as exc_info:
        await cancel_reference_video_tasks(
            _project(tmp_path),
            "demo",
            1,
            unit_id="missing",
            queue=_Queue([]),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == "ref_unit_not_found"
