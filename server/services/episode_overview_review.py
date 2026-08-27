"""Shared confirmation operation for editable course episode overviews."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision

EPISODE_OVERVIEW_FIELDS = ("synopsis", "genre", "theme", "world_setting")


class EpisodeOverviewNotFoundError(LookupError):
    """The requested course episode has no generated overview draft."""


class EpisodeOverviewRevisionConflictError(RuntimeError):
    """The overview draft no longer matches the episode source revision."""


def normalize_episode_overview(updates: Mapping[str, Any]) -> dict[str, str]:
    """Validate the complete editable overview payload and trim its text fields."""

    if not isinstance(updates, Mapping):
        raise ValueError("overview 必须是对象")
    missing = [field for field in EPISODE_OVERVIEW_FIELDS if field not in updates]
    unknown = sorted(set(updates) - set(EPISODE_OVERVIEW_FIELDS))
    if missing or unknown:
        raise ValueError(f"overview 必须且只能包含字段 {list(EPISODE_OVERVIEW_FIELDS)}")

    normalized: dict[str, str] = {}
    for field in EPISODE_OVERVIEW_FIELDS:
        value = updates[field]
        if not isinstance(value, str):
            raise ValueError(f"overview.{field} 必须是字符串")
        normalized[field] = value.strip()
    if not normalized["synopsis"]:
        raise ValueError("overview.synopsis 不能为空")
    return normalized


def confirm_episode_overview(
    manager: ProjectManager,
    project_name: str,
    episode: int,
    overview: Mapping[str, Any],
    *,
    expected_source_revision: str,
) -> dict[str, Any]:
    """Save reviewed fields and atomically mark one course episode overview confirmed."""

    if isinstance(episode, bool) or not isinstance(episode, int) or episode < 1:
        raise ValueError("episode 必须是正整数")
    if not isinstance(expected_source_revision, str) or not expected_source_revision:
        raise ValueError("expected_source_revision 必须是非空字符串")
    normalized = normalize_episode_overview(overview)
    project_path = manager.get_project_path(project_name)
    captured: dict[str, Any] = {}

    def _mutate(project: dict[str, Any]) -> None:
        if project.get("content_mode") != "course":
            raise ValueError("仅课程项目支持确认单集概述")
        entries = project.get("episodes")
        entry = (
            next(
                (item for item in entries if isinstance(item, dict) and item.get("episode") == episode),
                None,
            )
            if isinstance(entries, list)
            else None
        )
        if entry is None or not isinstance(entry.get("overview"), Mapping):
            raise EpisodeOverviewNotFoundError(f"第 {episode} 集尚无可确认的解析结果")
        source_file = entry.get("source_file")
        if not isinstance(source_file, str) or not source_file:
            raise EpisodeOverviewNotFoundError(f"第 {episode} 集没有绑定源文")

        current_revision = compute_source_revision(
            project_path,
            project,
            SourceScope(kind="files", files=[source_file]),
        ).revision
        if current_revision != expected_source_revision or entry.get("source_revision") != expected_source_revision:
            raise EpisodeOverviewRevisionConflictError(f"第 {episode} 集源文或解析结果已变化")

        saved_overview = copy.deepcopy(dict(entry["overview"]))
        saved_overview.update(normalized)
        saved_overview["source_revision"] = expected_source_revision
        entry["overview"] = saved_overview
        entry["overview_status"] = "confirmed"
        if episode == 1:
            project["overview"] = {
                key: copy.deepcopy(value) for key, value in saved_overview.items() if key != "source_revision"
            }
        captured.update(
            episode=episode,
            overview=copy.deepcopy(saved_overview),
            overview_status="confirmed",
        )

    manager.update_project(project_name, _mutate)
    return captured


__all__ = [
    "EPISODE_OVERVIEW_FIELDS",
    "EpisodeOverviewNotFoundError",
    "EpisodeOverviewRevisionConflictError",
    "confirm_episode_overview",
    "normalize_episode_overview",
]
