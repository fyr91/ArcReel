"""Shared cancellation for reference-video generation and HD tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from lib.db.base import DEFAULT_USER_ID
from lib.generation_queue import GenerationQueue, get_generation_queue
from lib.i18n import _ as translate
from lib.project_manager import ProjectManager, is_reference_video_project
from lib.video_backends.base import VideoCapabilityError

REFERENCE_VIDEO_TASK_TYPES = frozenset({"reference_video", "reference_video_refine"})
_ACTIVE_STATUSES = ("queued", "running", "cancelling")
_PAGE_SIZE = 500


class ReferenceVideoTaskCancellationUnavailable(VideoCapabilityError):
    """The requested episode or unit cannot be used as a cancellation scope."""

    def __str__(self) -> str:
        return translate(self.code, **self.params)


def _episode_script(project: Mapping[str, Any], episode: int) -> str:
    meta = next(
        (
            item
            for item in project.get("episodes") or []
            if isinstance(item, Mapping) and item.get("episode") == episode
        ),
        None,
    )
    script_file = meta.get("script_file") if isinstance(meta, Mapping) else None
    if not isinstance(script_file, str) or not script_file:
        raise ReferenceVideoTaskCancellationUnavailable("ref_episode_not_found", episode=episode)
    return script_file


def _normalize_script_file(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("scripts/")


async def _list_active_tasks(
    queue: GenerationQueue,
    *,
    project_name: str,
    script_file: str,
    unit_id: str | None,
    user_id: str,
) -> list[dict[str, Any]]:
    """List the complete active snapshot for the episode across both video task types."""
    normalized_script = _normalize_script_file(script_file)
    matched: dict[str, dict[str, Any]] = {}
    for task_type in sorted(REFERENCE_VIDEO_TASK_TYPES):
        for status in _ACTIVE_STATUSES:
            page = 1
            while True:
                result = await queue.list_tasks(
                    project_name=project_name,
                    status=status,
                    task_type=task_type,
                    page=page,
                    page_size=_PAGE_SIZE,
                    user_id=user_id,
                )
                items = result.get("items")
                if not isinstance(items, list):
                    break
                for task in items:
                    if not isinstance(task, dict):
                        continue
                    if _normalize_script_file(task.get("script_file")) != normalized_script:
                        continue
                    if unit_id is not None and task.get("resource_id") != unit_id:
                        continue
                    task_id = task.get("task_id")
                    if isinstance(task_id, str) and task_id:
                        matched[task_id] = task
                if len(items) < _PAGE_SIZE:
                    break
                page += 1
    return sorted(matched.values(), key=lambda task: str(task.get("queued_at") or task.get("task_id") or ""))


async def cancel_reference_video_tasks(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    *,
    unit_id: str | None = None,
    user_id: str = DEFAULT_USER_ID,
    queue: GenerationQueue | None = None,
) -> dict[str, Any]:
    """Cancel one unit or every active generation/HD task in an episode."""
    try:
        project = await asyncio.to_thread(project_manager.load_project, project_name)
    except FileNotFoundError as exc:
        raise ReferenceVideoTaskCancellationUnavailable("project_not_found", name=project_name) from exc
    if not is_reference_video_project(project):
        raise ReferenceVideoTaskCancellationUnavailable("ref_not_reference_video_mode")
    script_file = _episode_script(project, episode)

    normalized_unit_id = unit_id.strip() if isinstance(unit_id, str) else None
    if unit_id is not None and not normalized_unit_id:
        raise ReferenceVideoTaskCancellationUnavailable("ref_unit_not_found", unit_id=unit_id)
    if normalized_unit_id is not None:
        try:
            script = await asyncio.to_thread(project_manager.load_script, project_name, script_file)
        except FileNotFoundError as exc:
            raise ReferenceVideoTaskCancellationUnavailable("script_not_found", name=script_file) from exc
        units = script.get("video_units")
        if not isinstance(units, list) or not any(
            isinstance(item, Mapping) and item.get("unit_id") == normalized_unit_id for item in units
        ):
            raise ReferenceVideoTaskCancellationUnavailable("ref_unit_not_found", unit_id=normalized_unit_id)

    queue = queue or get_generation_queue()
    tasks = await _list_active_tasks(
        queue,
        project_name=project_name,
        script_file=script_file,
        unit_id=normalized_unit_id,
        user_id=user_id,
    )
    results = []
    already_cancelling = []
    for task in tasks:
        task_id = str(task["task_id"])
        if task.get("status") == "cancelling":
            already_cancelling.append(task_id)
            continue
        results.append(await queue.cancel_task(task_id, user_id=user_id))

    cancelled = [item for result in results for item in result.get("cancelled", [])]
    cancelling = [task_id for result in results for task_id in result.get("cancelling", [])]
    skipped_terminal = [item for result in results for item in result.get("skipped_terminal", [])]
    return {
        "success": True,
        "episode": episode,
        "unit_id": normalized_unit_id,
        "scope": "unit" if normalized_unit_id is not None else "episode",
        "matched_task_ids": [str(task["task_id"]) for task in tasks],
        "cancelled": cancelled,
        "cancelling": cancelling,
        "already_cancelling": already_cancelling,
        "skipped_terminal": skipped_terminal,
        "affected_count": len(cancelled) + len(cancelling) + len(already_cancelling),
    }


__all__ = [
    "REFERENCE_VIDEO_TASK_TYPES",
    "ReferenceVideoTaskCancellationUnavailable",
    "cancel_reference_video_tasks",
]
