from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.services.project_path_links import (
    InvalidProjectPathError,
    LocalFileManagerUnavailableError,
    ProjectPathLinkService,
    ProjectPathNotFoundError,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def project(tmp_path: Path) -> tuple[ProjectManager, Path]:
    manager = ProjectManager(tmp_path / "projects")
    project_dir = manager.create_project("demo")
    (project_dir / "videos" / "clip one.mp4").write_bytes(b"video")
    return manager, project_dir


def test_resolve_returns_browser_safe_project_relative_links(project) -> None:
    manager, project_dir = project
    service = ProjectPathLinkService(manager)

    root = service.resolve("demo", ".")
    folder = service.resolve("demo", "videos")
    file = service.resolve("demo", "videos/clip one.mp4")

    assert root.relative_path == "."
    assert root.kind == "directory"
    assert root.href == "/__arcreel_open_project_path__?path=."
    assert folder.absolute_path == project_dir.resolve() / "videos"
    assert folder.kind == "directory"
    assert file.relative_path == "videos/clip one.mp4"
    assert file.kind == "file"
    assert file.href == "/__arcreel_open_project_path__?path=videos%2Fclip+one.mp4"


@pytest.mark.parametrize("relative_path", ["../outside", "videos/../../outside", "/tmp/outside", "C:\\outside"])
def test_resolve_rejects_non_project_relative_paths(project, relative_path: str) -> None:
    manager, _ = project

    with pytest.raises(InvalidProjectPathError):
        ProjectPathLinkService(manager).resolve("demo", relative_path)


def test_resolve_rejects_missing_path(project) -> None:
    manager, _ = project

    with pytest.raises(ProjectPathNotFoundError):
        ProjectPathLinkService(manager).resolve("demo", "videos/missing.mp4")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation may require elevated privileges")
def test_resolve_rejects_symlink_escape(project, tmp_path: Path) -> None:
    manager, project_dir = project
    outside = tmp_path / "outside"
    outside.mkdir()
    (project_dir / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidProjectPathError):
        ProjectPathLinkService(manager).resolve("demo", "escape")


@pytest.mark.parametrize(
    ("platform_name", "relative_path", "expected"),
    [
        ("Darwin", "videos", ["open", "{project}/videos"]),
        ("Darwin", "videos/clip one.mp4", ["open", "-R", "{project}/videos/clip one.mp4"]),
        ("Windows", "videos", ["explorer.exe", "{project}/videos"]),
        (
            "Windows",
            "videos/clip one.mp4",
            ["explorer.exe", "/select,", "{project}/videos/clip one.mp4"],
        ),
        ("Linux", "videos", ["xdg-open", "{project}/videos"]),
        ("Linux", "videos/clip one.mp4", ["xdg-open", "{project}/videos"]),
    ],
)
def test_reveal_uses_platform_file_manager_command(
    project,
    platform_name: str,
    relative_path: str,
    expected: list[str],
) -> None:
    manager, project_dir = project
    calls: list[tuple[list[str], dict]] = []

    class _Process:
        def wait(self, *, timeout):
            assert timeout == 2
            return 0

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return _Process()

    location = ProjectPathLinkService(
        manager,
        platform_name=platform_name,
        popen=fake_popen,
    ).reveal("demo", relative_path)

    project_path = str(project_dir.resolve())
    assert calls[0][0] == [part.format(project=project_path) for part in expected]
    assert calls[0][1]["stdin"] is not None
    assert location.relative_path == relative_path


def test_reveal_reports_unsupported_platform(project) -> None:
    manager, _ = project

    with pytest.raises(LocalFileManagerUnavailableError):
        ProjectPathLinkService(manager, platform_name="Plan9").reveal("demo", "videos")


def test_reveal_wraps_launcher_failure(project) -> None:
    manager, _ = project

    def fail_popen(*_args, **_kwargs):
        raise OSError("launcher missing")

    with pytest.raises(LocalFileManagerUnavailableError):
        ProjectPathLinkService(manager, platform_name="Darwin", popen=fail_popen).reveal("demo", "videos")


def test_reveal_reports_launcher_that_exits_with_error(project) -> None:
    manager, _ = project

    class _FailedProcess:
        @staticmethod
        def wait(*, timeout):
            assert timeout == 2
            return 3

    with pytest.raises(LocalFileManagerUnavailableError):
        ProjectPathLinkService(
            manager,
            platform_name="Linux",
            popen=lambda *_args, **_kwargs: _FailedProcess(),
        ).reveal("demo", "videos")


def test_reveal_accepts_file_manager_process_that_keeps_running(project) -> None:
    manager, _ = project

    class _RunningProcess:
        @staticmethod
        def wait(*, timeout):
            raise subprocess.TimeoutExpired("open", timeout)

    location = ProjectPathLinkService(
        manager,
        platform_name="Windows",
        popen=lambda *_args, **_kwargs: _RunningProcess(),
    ).reveal("demo", "videos")

    assert location.kind == "directory"
