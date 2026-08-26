"""Project-scoped links that reveal files in the local file manager."""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlencode

from lib.path_safety import PathTraversalError, safe_join
from lib.project_manager import ProjectManager, get_project_manager

PROJECT_PATH_LINK_ROUTE = "/__arcreel_open_project_path__"


class ProjectPathLinkError(Exception):
    """Base error for project-local path link operations."""


class InvalidProjectPathError(ProjectPathLinkError):
    """The requested value is not a project-relative path."""


class ProjectPathNotFoundError(ProjectPathLinkError):
    """The requested project-local file or directory does not exist."""


class LocalFileManagerUnavailableError(ProjectPathLinkError):
    """The server host cannot launch a supported local file manager."""


@dataclass(frozen=True)
class ProjectPathLocation:
    """A validated project-local path and its browser-safe link projection."""

    relative_path: str
    absolute_path: Path
    kind: Literal["file", "directory"]
    href: str


PopenFactory = Callable[..., Any]


class ProjectPathLinkService:
    """Resolve and reveal paths while keeping every target inside one project."""

    def __init__(
        self,
        project_manager: ProjectManager | None = None,
        *,
        platform_name: str | None = None,
        popen: PopenFactory | None = None,
    ) -> None:
        self._pm = project_manager or get_project_manager()
        self._platform_name = platform_name or platform.system()
        self._popen = popen or subprocess.Popen

    def resolve(self, project_name: str, relative_path: str = ".") -> ProjectPathLocation:
        project_dir = self._pm.get_project_path(project_name).resolve()
        normalized = self._normalize_relative_path(relative_path)
        try:
            target = safe_join(
                project_dir,
                normalized,
                allow_base=True,
                must_exist=True,
            )
        except PathTraversalError as exc:
            raise InvalidProjectPathError(relative_path) from exc
        except FileNotFoundError as exc:
            raise ProjectPathNotFoundError(relative_path) from exc

        if target.is_dir():
            kind = "directory"
        elif target.is_file():
            kind = "file"
        else:
            raise ProjectPathNotFoundError(relative_path)

        canonical = target.relative_to(project_dir).as_posix()
        return ProjectPathLocation(
            relative_path=canonical,
            absolute_path=target,
            kind=kind,
            href=f"{PROJECT_PATH_LINK_ROUTE}?{urlencode({'path': canonical})}",
        )

    def reveal(self, project_name: str, relative_path: str = ".") -> ProjectPathLocation:
        location = self.resolve(project_name, relative_path)
        command = self._reveal_command(location)
        try:
            process = self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                return_code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return location
            if return_code != 0:
                raise LocalFileManagerUnavailableError(self._platform_name)
        except LocalFileManagerUnavailableError:
            raise
        except (OSError, ValueError) as exc:
            raise LocalFileManagerUnavailableError(self._platform_name) from exc
        return location

    @staticmethod
    def _normalize_relative_path(relative_path: str) -> str:
        if not isinstance(relative_path, str):
            raise InvalidProjectPathError(str(relative_path))
        value = relative_path.strip()
        if not value or value == ".":
            return "."

        portable = value.replace("\\", "/")
        if portable.startswith("/") or PureWindowsPath(value).is_absolute():
            raise InvalidProjectPathError(relative_path)
        parts = portable.split("/")
        if any(part == ".." for part in parts):
            raise InvalidProjectPathError(relative_path)
        return os.path.normpath(value)

    def _reveal_command(self, location: ProjectPathLocation) -> list[str]:
        path = str(location.absolute_path)
        if self._platform_name == "Darwin":
            return ["open", path] if location.kind == "directory" else ["open", "-R", path]
        if self._platform_name == "Windows":
            return ["explorer.exe", path] if location.kind == "directory" else ["explorer.exe", "/select,", path]
        if self._platform_name == "Linux":
            target = location.absolute_path if location.kind == "directory" else location.absolute_path.parent
            return ["xdg-open", str(target)]
        raise LocalFileManagerUnavailableError(self._platform_name)


__all__ = [
    "InvalidProjectPathError",
    "LocalFileManagerUnavailableError",
    "PROJECT_PATH_LINK_ROUTE",
    "ProjectPathLinkError",
    "ProjectPathLinkService",
    "ProjectPathLocation",
    "ProjectPathNotFoundError",
]
