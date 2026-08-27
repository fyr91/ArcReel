from __future__ import annotations

from pathlib import Path

import pytest

from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
from lib.project_manager import ProjectManager
from server.services.course_episode_deletion import (
    CourseEpisodeDeletionError,
    CourseEpisodeDeletionService,
)

pytestmark = pytest.mark.integration


def _write(path: Path, content: bytes = b"content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _course_project(tmp_path: Path) -> tuple[ProjectManager, Path]:
    pm = ProjectManager(tmp_path / "projects")
    project_dir = pm.create_project("course", content_mode="course")
    pm.create_project_metadata(
        "course",
        "Course",
        "Anime",
        "course",
        extras={"generation_mode": "reference_video", "grid_storyboard": False},
    )

    def _seed(project: dict) -> None:
        project["overview"] = {"synopsis": "episode one mirror"}
        project["episodes"] = [
            {
                "episode": 1,
                "title": "Lesson One",
                "script_file": "scripts/episode_1.json",
                "source_file": "source/lesson-one.txt",
                "overview": {"synopsis": "lesson one"},
            },
            {
                "episode": 2,
                "title": "Lesson Two",
                "script_file": "scripts/episode_2.json",
                "source_file": "source/lesson-two.txt",
            },
        ]
        project["workflow"] = {
            "asset_inventory_by_episode": {
                "1": {"scope": ["source/lesson-one.txt"]},
                "2": {"scope": ["source/lesson-two.txt"]},
            }
        }

    pm.update_project("course", _seed)
    return pm, project_dir


def test_delete_removes_only_confirmed_episode_outputs_and_preserves_libraries(tmp_path: Path) -> None:
    pm, project_dir = _course_project(tmp_path)
    episode_files = [
        _write(project_dir / "source" / "lesson-one.txt"),
        _write(project_dir / "source" / "raw" / "lesson-one.md"),
        _write(project_dir / "scripts" / "episode_1.json", b"{}"),
        _write(project_dir / "drafts" / "episode_1" / "step1_reference_units.json", b"{}"),
        _write(project_dir / "videos" / "E1U01.mp4"),
        _write(project_dir / "subtitles" / "episode_1" / "E1U01.post_production.json"),
        _write(project_dir / "hyperframes" / "episode_01" / "index.html"),
    ]
    other_episode_file = _write(project_dir / "source" / "lesson-two.txt")
    other_script = _write(project_dir / "scripts" / "episode_2.json", b"{}")
    library_file = _write(project_dir / "characters" / "Teacher.png")
    adapter = ProjectArtifactManifestAdapter(project_dir)
    episode_claim = ArtifactManifestEntry("videos/E1U01.mp4", "sha256-v1:" + "a" * 64)
    other_claim = ArtifactManifestEntry("scripts/episode_2.json", "sha256-v1:" + "b" * 64)
    library_claim = ArtifactManifestEntry("characters/Teacher.png", "sha256-v1:" + "c" * 64)
    adapter.put_entry(ArtifactKey.episode_video(1, "E1U01"), episode_claim)
    adapter.put_entry(ArtifactKey.episode_script(2), other_claim)
    adapter.put_entry(ArtifactKey.asset_sheet("character", "Teacher"), library_claim)

    service = CourseEpisodeDeletionService(pm)
    preview = service.preview("course", 1)

    assert preview.total_files == len(episode_files)
    assert preview.artifact_claims == 1
    assert all(path.exists() for path in episode_files)

    result = service.delete("course", 1, preview.confirmation_token)

    assert result.episode == 1
    assert all(not path.exists() for path in episode_files)
    assert other_episode_file.exists()
    assert other_script.exists()
    assert library_file.exists()
    project = pm.load_project("course")
    assert [entry["episode"] for entry in project["episodes"]] == [2]
    assert "overview" not in project
    assert project["workflow"]["asset_inventory_by_episode"] == {"2": {"scope": ["source/lesson-two.txt"]}}
    remaining = adapter.snapshot_entries()
    assert ArtifactKey.episode_video(1, "E1U01") not in remaining
    assert remaining[ArtifactKey.episode_script(2)] == other_claim
    assert remaining[ArtifactKey.asset_sheet("character", "Teacher")] == library_claim


def test_delete_rejects_confirmation_when_episode_changes_after_preview(tmp_path: Path) -> None:
    pm, project_dir = _course_project(tmp_path)
    source = _write(project_dir / "source" / "lesson-one.txt")
    draft = _write(project_dir / "drafts" / "episode_1" / "step1_reference_units.json", b"before")
    service = CourseEpisodeDeletionService(pm)
    preview = service.preview("course", 1)
    draft.write_bytes(b"after")

    with pytest.raises(CourseEpisodeDeletionError, match="changed") as raised:
        service.delete("course", 1, preview.confirmation_token)

    assert raised.value.code == "course_episode_delete_confirmation_stale"
    assert source.exists()
    assert draft.exists()
    assert [entry["episode"] for entry in pm.load_project("course")["episodes"]] == [1, 2]


def test_preview_refuses_an_episode_claim_pointing_into_resource_library(tmp_path: Path) -> None:
    pm, project_dir = _course_project(tmp_path)
    _write(project_dir / "source" / "lesson-one.txt")
    _write(project_dir / "characters" / "Teacher.png")
    ProjectArtifactManifestAdapter(project_dir).put_entry(
        ArtifactKey.episode_storyboard(1, "E1U01"),
        ArtifactManifestEntry("characters/Teacher.png", "sha256-v1:" + "a" * 64),
    )

    with pytest.raises(CourseEpisodeDeletionError, match="protected resource") as raised:
        CourseEpisodeDeletionService(pm).preview("course", 1)

    assert raised.value.code == "course_episode_delete_protected_resource"
    assert (project_dir / "characters" / "Teacher.png").exists()
