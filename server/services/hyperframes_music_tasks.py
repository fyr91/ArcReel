"""ArcReel queue operations for project-local HyperFrames background music."""

from __future__ import annotations

from typing import Any

from lib.db.base import DEFAULT_USER_ID
from lib.generation_queue import GenerationQueue, get_generation_queue
from lib.project_manager import ProjectManager, get_project_manager
from lib.providers import PROVIDER_CROCO
from server.services.hyperframes_music import (
    MAX_MUSIC_DIRECTION_LENGTH,
    HyperframesMusicService,
    HyperframesMusicUnavailable,
)
from server.services.hyperframes_workspace import HyperframesWorkspaceService

HYPERFRAMES_BGM_TASK_TYPE = "hyperframes_bgm"


def hyperframes_bgm_resource_id(episode: int) -> str:
    if type(episode) is not int or episode <= 0:
        raise HyperframesMusicUnavailable("episode must be a positive integer")
    return f"episode_{episode:02d}"


def _validated_direction(direction: object) -> str:
    if not isinstance(direction, str) or not direction.strip():
        raise HyperframesMusicUnavailable("music direction must not be empty")
    normalized = direction.strip()
    if len(normalized) > MAX_MUSIC_DIRECTION_LENGTH:
        raise HyperframesMusicUnavailable(f"music direction exceeds {MAX_MUSIC_DIRECTION_LENGTH} characters")
    return normalized


async def enqueue_hyperframes_bgm_task(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    *,
    direction: str,
    seed: int | None = None,
    source: str,
    user_id: str = DEFAULT_USER_ID,
    queue: GenerationQueue | None = None,
) -> dict[str, Any]:
    """Validate once and enqueue the Web/Agent shared music operation."""
    resource_id = hyperframes_bgm_resource_id(episode)
    direction = _validated_direction(direction)
    if seed is not None and (type(seed) is not int or seed < 0):
        raise HyperframesMusicUnavailable("seed must be a non-negative integer")
    if HyperframesWorkspaceService(project_manager).status(project_name, episode) is None:
        raise HyperframesMusicUnavailable("prepare the HyperFrames episode workspace first")

    task = await (queue or get_generation_queue()).enqueue_task(
        project_name=project_name,
        task_type=HYPERFRAMES_BGM_TASK_TYPE,
        media_type="audio",
        resource_id=resource_id,
        payload={"episode": episode, "direction": direction, "seed": seed},
        source=source,
        user_id=user_id,
        provider_id=PROVIDER_CROCO,
    )
    # GenerationQueue intentionally returns only queue identity/status. Enrich the
    # shared Web/Agent response with the deterministic episode resource instead of
    # requiring each boundary adapter to assume repository row shape.
    return {**task, "resource_id": resource_id}


async def execute_hyperframes_bgm_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
    provider_job_id: str | None = None,
) -> dict[str, object]:
    """Generate, validate, and attach one continuous music bed to the edit."""
    del user_id
    episode = payload.get("episode")
    if type(episode) is not int or hyperframes_bgm_resource_id(episode) != resource_id:
        raise HyperframesMusicUnavailable("HyperFrames music task episode does not match its resource")
    direction = _validated_direction(payload.get("direction"))
    seed = payload.get("seed")
    if seed is not None and (type(seed) is not int or seed < 0):
        raise HyperframesMusicUnavailable("seed must be a non-negative integer")

    music = await HyperframesMusicService(get_project_manager()).generate(
        project_name,
        episode,
        direction=direction,
        seed=seed,
        task_id=task_id,
        provider_job_id=provider_job_id,
    )
    return music.to_dict()


__all__ = [
    "HYPERFRAMES_BGM_TASK_TYPE",
    "enqueue_hyperframes_bgm_task",
    "execute_hyperframes_bgm_task",
    "hyperframes_bgm_resource_id",
]
