from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from lib.version_manager import VersionManager
from server.services import h3_refine_tasks as service

pytestmark = pytest.mark.unit


class _Queue:
    def __init__(self) -> None:
        self.enqueued: dict[str, Any] | None = None
        self.latest: dict[str, Any] | None = None

    async def get_task(self, task_id: str, *, user_id: str | None = None):
        del user_id
        assert task_id == "first-pass-task"
        return {"task_id": task_id, "provider_job_id": "first-pass-job"}

    async def enqueue_task(self, **kwargs: Any):
        self.enqueued = kwargs
        return {"task_id": "hd-task", "status": "queued", "deduped": False}

    async def get_latest_task_for_resource(self, **_kwargs: Any):
        return self.latest


def _project(tmp_path: Path, *, confirmed: bool = True, refined: bool = False) -> tuple[ProjectManager, Path]:
    projects = tmp_path / "projects"
    project_path = projects / "demo"
    (project_path / "scripts").mkdir(parents=True)
    (project_path / "reference_videos").mkdir()
    atomic_write_json(
        project_path / "project.json",
        {
            "schema_version": 12,
            "title": "Demo",
            "content_mode": "drama",
            "generation_mode": "reference_video",
            "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}],
        },
    )
    atomic_write_json(
        project_path / "scripts" / "episode_1.json",
        {
            "episode": 1,
            "content_mode": "drama",
            "video_units": [
                {
                    "unit_id": "E1U01",
                    "text": "shot",
                    "duration_seconds": 6,
                    "video_review_status": "confirmed" if confirmed else "pending_review",
                    "confirmed_video_version": 1 if confirmed else None,
                    "generated_assets": {
                        "video_clip": "reference_videos/E1U01.mp4",
                        "status": "completed",
                    },
                }
            ],
        },
    )
    current = project_path / "reference_videos" / "E1U01.mp4"
    current.write_bytes(b"preview")
    version = VersionManager(project_path).add_version(
        "reference_videos",
        "E1U01",
        "prompt",
        source_file=current,
        h3_manual_refine=not refined,
        h3_refined=refined,
        h3_refine_profile=service.H3_REFINE_PROFILE,
        execution_task_id="first-pass-task",
        execution_provider_id="croco",
        execution_backend_model_id="minimax-h3",
        execution_duration_seconds=6,
        execution_resolution=(service.H3_REFINED_RESOLUTION if refined else "480p"),
    )
    assert version == 1
    return ProjectManager(projects), project_path


async def test_enqueue_freezes_confirmed_preview_and_uses_shared_queue_contract(tmp_path: Path) -> None:
    pm, _path = _project(tmp_path)
    queue = _Queue()

    result = await service.enqueue_h3_refine_task(
        pm,
        "demo",
        1,
        "E1U01",
        source="webui",
        user_id="u1",
        queue=queue,  # type: ignore[arg-type]
    )

    assert result["task_id"] == "hd-task"
    assert queue.enqueued is not None
    assert queue.enqueued["task_type"] == service.H3_REFINE_TASK_TYPE
    assert queue.enqueued["media_type"] == "video"
    assert queue.enqueued["provider_id"] == "croco"
    assert queue.enqueued["payload"] == {
        "episode": 1,
        "source_version": 1,
        "source_task_id": "first-pass-task",
        "source_job_id": "first-pass-job",
        "duration_seconds": 6,
    }


async def test_enqueue_reuses_successful_provider_child_after_local_commit_failure(tmp_path: Path) -> None:
    pm, _path = _project(tmp_path)
    queue = _Queue()
    queue.latest = {
        "task_id": "failed-local-task",
        "status": "failed",
        "provider_job_id": "successful-paid-child",
        "payload": {
            "episode": 1,
            "source_version": 1,
            "source_task_id": "first-pass-task",
            "source_job_id": "first-pass-job",
            "duration_seconds": 6,
        },
        "execution_progress": {
            "kind": "minimax_h3",
            "phase": "completed",
            "provider_status": "succeeded",
            "progress": 100,
        },
    }

    await service.enqueue_h3_refine_task(
        pm,
        "demo",
        1,
        "E1U01",
        source="webui",
        queue=queue,  # type: ignore[arg-type]
    )

    assert queue.enqueued is not None
    assert queue.enqueued["payload"]["resume_provider_job_id"] == "successful-paid-child"


async def test_refined_version_metadata_does_not_duplicate_committer_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm, _path = _project(tmp_path)
    candidate = await service.resolve_h3_refine_candidate(
        pm,
        "demo",
        1,
        "E1U01",
        queue=_Queue(),  # type: ignore[arg-type]
    )

    @dataclass(frozen=True)
    class _Currency:
        parent_version: int = 0

        def to_dict(self) -> dict[str, int]:
            return {"parent_version": self.parent_version}

    monkeypatch.setattr(service.VideoArtifactCurrencyFacts, "from_dict", lambda _value: _Currency())

    metadata = service._version_metadata(candidate, "hd-task", "hd-child")

    assert "prompt" not in metadata
    assert "duration_seconds" not in metadata
    assert "file" not in metadata
    assert metadata["h3_refined"] is True
    assert metadata["h3_refine_job_id"] == "hd-child"


async def test_refined_asset_projection_retains_original_and_selects_hd(tmp_path: Path) -> None:
    pm, _path = _project(tmp_path)
    candidate = await service.resolve_h3_refine_candidate(
        pm,
        "demo",
        1,
        "E1U01",
        queue=_Queue(),  # type: ignore[arg-type]
    )
    unit = {
        "generated_assets": {
            "video_clip": "reference_videos/E1U01.mp4",
            "video_uri": "https://old.example/preview.mp4",
        }
    }

    service._apply_refined_assets(
        unit,
        candidate,
        selected_version=2,
        generated_at="2026-08-28T00:00:00+00:00",
        video_uri="https://example.test/hd.mp4",
        thumbnail_available=True,
    )

    assets = unit["generated_assets"]
    assert assets["original_video_clip"] == candidate.source_video_clip
    assert assets["video_clip"] == "reference_videos/E1U01.mp4"
    assert assets["hd_video_clip"] == "reference_videos/E1U01.mp4"
    assert assets["hd_video_uri"] == "https://example.test/hd.mp4"
    assert unit["confirmed_video_version"] == 2
    assert unit["video_review_status"] == "confirmed"


async def test_enqueue_requires_confirmation_before_hd(tmp_path: Path) -> None:
    pm, _path = _project(tmp_path, confirmed=False)

    with pytest.raises(service.H3RefineUnavailable, match="确认"):
        await service.enqueue_h3_refine_task(
            pm,
            "demo",
            1,
            "E1U01",
            source="webui",
            queue=_Queue(),  # type: ignore[arg-type]
        )


async def test_status_reports_selected_refined_version_as_completed(tmp_path: Path) -> None:
    pm, _path = _project(tmp_path, refined=True)

    status = await service.h3_refine_status(
        pm,
        "demo",
        1,
        "E1U01",
        queue=_Queue(),  # type: ignore[arg-type]
    )

    assert status == {"state": "completed", "unit_id": "E1U01", "version": 1}


async def test_hyperframes_gate_stops_when_h3_preview_has_no_usable_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm, _path = _project(tmp_path)

    async def _status(*_args: Any, **_kwargs: Any):
        return {"state": "unavailable", "code": "video_hd_checkpoint_unavailable", "params": {}}

    monkeypatch.setattr(service, "h3_refine_status", _status)

    with pytest.raises(service.H3RefineUnavailable, match="高清断点"):
        await service.ensure_episode_h3_hd(pm, "demo", 1, source="hyperframes")
