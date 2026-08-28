from __future__ import annotations

from pathlib import Path

import pytest

from lib.json_io import atomic_write_json
from lib.project_manager import ProjectManager
from lib.version_manager import VersionManager
from server.services.reference_video_review import (
    ReferenceVideoReviewUnavailable,
    confirm_reference_video,
)

pytestmark = pytest.mark.unit


def _project(tmp_path: Path, *, with_video: bool = True) -> tuple[ProjectManager, Path]:
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
            "title": "Episode 1",
            "content_mode": "drama",
            "video_units": [
                {
                    "unit_id": "E1U01",
                    "text": "shot",
                    "duration_seconds": 6,
                    "generated_assets": {
                        "video_clip": "reference_videos/E1U01.mp4" if with_video else None,
                        "status": "completed" if with_video else "pending",
                    },
                }
            ],
        },
    )
    if with_video:
        current = project_path / "reference_videos" / "E1U01.mp4"
        current.write_bytes(b"preview")
        VersionManager(project_path).add_version(
            "reference_videos",
            "E1U01",
            "prompt",
            source_file=current,
        )
    return ProjectManager(projects), project_path


async def test_confirm_reference_video_selects_the_exact_current_version(tmp_path: Path) -> None:
    pm, project_path = _project(tmp_path)

    result = await confirm_reference_video(pm, "demo", 1, "E1U01")

    assert result["confirmed_video_version"] == 1
    unit = pm.load_script("demo", "scripts/episode_1.json")["video_units"][0]
    assert unit["video_review_status"] == "confirmed"
    assert unit["confirmed_video_version"] == 1
    assert VersionManager(project_path).get_current_version("reference_videos", "E1U01") == 1


async def test_confirm_reference_video_rejects_a_unit_without_generated_video(tmp_path: Path) -> None:
    pm, _project_path = _project(tmp_path, with_video=False)

    with pytest.raises(ReferenceVideoReviewUnavailable, match="尚未生成"):
        await confirm_reference_video(pm, "demo", 1, "E1U01")
