from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.services import video_dependency_tasks as service

pytestmark = pytest.mark.unit


def _unit() -> dict[str, object]:
    return {
        "unit_id": "E1U02",
        "video_dependency": {
            "source_unit_id": "E1U01",
            "relation": "continuation",
            "audio_policy": "none",
        },
    }


async def test_resolve_video_continuation_guide_uses_selected_version_task_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = MagicMock()
    versions.get_versions.return_value = {
        "current_version": 2,
        "versions": [
            {
                "version": 2,
                "execution_task_id": "task-source",
                "execution_provider_id": "croco",
            }
        ],
    }
    monkeypatch.setattr(service, "VersionManager", lambda _path: versions)
    queue = MagicMock()
    queue.get_task = AsyncMock(
        return_value={
            "status": "succeeded",
            "provider_id": "croco",
            "provider_job_id": "gpu-job-source",
        }
    )
    monkeypatch.setattr(service, "get_generation_queue", lambda: queue)

    guide, evidence = await service.resolve_video_continuation_guide(
        project_path=tmp_path,
        unit=_unit(),
        resource_type="reference_videos",
        user_id="u1",
    )

    assert guide is not None and guide.source_job_id == "gpu-job-source"
    assert evidence is not None and evidence["source_version"] == 2
    assert evidence["source_execution_task_id"] == "task-source"
    queue.get_task.assert_awaited_once_with("task-source", user_id="u1")


async def test_manual_source_version_must_be_regenerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    versions = MagicMock()
    versions.get_versions.return_value = {
        "current_version": 1,
        "versions": [{"version": 1, "source": "manual_upload"}],
    }
    monkeypatch.setattr(service, "VersionManager", lambda _path: versions)

    with pytest.raises(ValueError, match="regenerate it first"):
        await service.resolve_video_continuation_guide(
            project_path=tmp_path,
            unit=_unit(),
            resource_type="videos",
            user_id="u1",
        )
