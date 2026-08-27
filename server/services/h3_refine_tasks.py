"""Shared MiniMax H3 preview-to-HD operation for Web, Agent, and HyperFrames."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from lib.backend_assembly import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.db.base import DEFAULT_USER_ID
from lib.generation_queue import GenerationQueue, get_generation_queue
from lib.generation_queue_client import wait_for_task
from lib.i18n import _ as translate
from lib.minimax_h3_prompt import is_minimax_h3_model
from lib.project_manager import ProjectManager, get_project_manager, is_reference_video_project
from lib.providers import PROVIDER_CROCO
from lib.resource_paths import resource_relative_path
from lib.thumbnail import extract_video_thumbnail
from lib.version_manager import VersionManager
from lib.video_artifact_facts import VideoArtifactCurrencyFacts
from lib.video_backends.base import VideoCapabilityError
from lib.video_backends.croco import CrocoVideoBackend
from server.services.video_artifact_currency import VideoArtifactCommitter, complete_video_artifact_commit

H3_REFINE_TASK_TYPE = "reference_video_refine"
H3_REFINE_PROFILE = "latent_upscale_2mp_v1"
H3_FIRST_PASS_RESOLUTION = "864x480"
H3_REFINED_RESOLUTION = "1920x1088"


class H3RefineUnavailable(VideoCapabilityError):
    """The selected unit is not an eligible confirmed H3 preview."""

    def __str__(self) -> str:
        return translate(self.code, **self.params)


@dataclass(frozen=True, slots=True)
class H3RefineCandidate:
    project_name: str
    episode: int
    script_file: str
    unit_id: str
    source_version: int
    source_task_id: str
    source_job_id: str
    duration_seconds: int
    prompt: str
    version_metadata: dict[str, Any]


def _episode_script(project: Mapping[str, Any], episode: int) -> str:
    for item in project.get("episodes") or []:
        if isinstance(item, Mapping) and item.get("episode") == episode:
            script_file = item.get("script_file")
            if isinstance(script_file, str) and script_file:
                return script_file
    raise H3RefineUnavailable("video_hd_source_changed")


def _find_unit(script: Mapping[str, Any], unit_id: str) -> dict[str, Any]:
    units = script.get("video_units")
    if not isinstance(units, list):
        raise H3RefineUnavailable("video_hd_source_changed")
    unit = next(
        (item for item in units if isinstance(item, dict) and item.get("unit_id") == unit_id),
        None,
    )
    if unit is None:
        raise H3RefineUnavailable("video_hd_source_changed")
    return unit


def _selected_record(versions: VersionManager, unit_id: str) -> tuple[int, dict[str, Any]]:
    history = versions.get_versions("reference_videos", unit_id)
    current = history.get("current_version")
    if type(current) is not int or current <= 0:
        raise H3RefineUnavailable("video_hd_source_changed")
    record = next(
        (item for item in history.get("versions") or [] if isinstance(item, dict) and item.get("version") == current),
        None,
    )
    if record is None:
        raise H3RefineUnavailable("video_hd_source_changed")
    return current, record


def _is_refined(record: Mapping[str, Any]) -> bool:
    return record.get("h3_refined") is True and record.get("h3_refine_profile") == H3_REFINE_PROFILE


async def resolve_h3_refine_candidate(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    unit_id: str,
    *,
    queue: GenerationQueue | None = None,
) -> H3RefineCandidate:
    """Freeze the exact confirmed preview and its provider job identity."""
    project = await asyncio.to_thread(project_manager.load_project, project_name)
    if not is_reference_video_project(project) or project.get("content_mode") not in {"drama", "course"}:
        raise H3RefineUnavailable("video_hd_project_unsupported")
    script_file = _episode_script(project, episode)
    script = await asyncio.to_thread(project_manager.load_script, project_name, script_file)
    unit = _find_unit(script, unit_id)
    project_path = project_manager.get_project_path(project_name)
    versions = VersionManager(project_path)
    source_version, record = await asyncio.to_thread(_selected_record, versions, unit_id)
    if unit.get("video_review_status") != "confirmed" or unit.get("confirmed_video_version") != source_version:
        raise H3RefineUnavailable("video_hd_confirm_first")
    if _is_refined(record):
        raise H3RefineUnavailable("video_hd_already_completed")
    if record.get("h3_manual_refine") is not True or record.get("h3_refine_profile") != H3_REFINE_PROFILE:
        raise H3RefineUnavailable("video_hd_checkpoint_unavailable")
    provider_id = record.get("execution_provider_id")
    model_id = record.get("execution_backend_model_id")
    if provider_id != PROVIDER_CROCO or not isinstance(model_id, str) or not is_minimax_h3_model(model_id):
        raise H3RefineUnavailable("video_hd_checkpoint_unavailable")
    source_task_id = record.get("execution_task_id")
    if not isinstance(source_task_id, str) or not source_task_id:
        raise H3RefineUnavailable("video_hd_checkpoint_unavailable")
    source_task = await (queue or get_generation_queue()).get_task(source_task_id)
    source_job_id = source_task.get("provider_job_id") if source_task else None
    if not isinstance(source_job_id, str) or not source_job_id:
        raise H3RefineUnavailable("video_hd_checkpoint_unavailable")
    duration = record.get("execution_duration_seconds", record.get("duration_seconds"))
    if type(duration) is not int or duration <= 0:
        raise H3RefineUnavailable("video_hd_checkpoint_unavailable")
    prompt = record.get("prompt")
    return H3RefineCandidate(
        project_name=project_name,
        episode=episode,
        script_file=script_file,
        unit_id=unit_id,
        source_version=source_version,
        source_task_id=source_task_id,
        source_job_id=source_job_id,
        duration_seconds=duration,
        prompt=prompt if isinstance(prompt, str) else "",
        version_metadata=dict(record),
    )


async def h3_refine_status(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    unit_id: str,
    *,
    user_id: str = DEFAULT_USER_ID,
    queue: GenerationQueue | None = None,
) -> dict[str, Any]:
    """Return the small UI projection used by the single “高清” button."""
    queue = queue or get_generation_queue()
    try:
        project = await asyncio.to_thread(project_manager.load_project, project_name)
        script_file = _episode_script(project, episode)
        script = await asyncio.to_thread(project_manager.load_script, project_name, script_file)
        unit = _find_unit(script, unit_id)
        version, record = await asyncio.to_thread(
            _selected_record, VersionManager(project_manager.get_project_path(project_name)), unit_id
        )
        if unit.get("confirmed_video_version") == version and _is_refined(record):
            return {"state": "completed", "unit_id": unit_id, "version": version}
    except (FileNotFoundError, H3RefineUnavailable):
        script_file = None
    latest = await queue.get_latest_task_for_resource(
        project_name=project_name,
        task_type=H3_REFINE_TASK_TYPE,
        resource_id=unit_id,
        user_id=user_id,
    )
    if latest and latest.get("status") in {"queued", "running", "cancelling"}:
        return {"state": "processing", "unit_id": unit_id, "task_id": latest["task_id"]}
    if latest and latest.get("status") == "failed":
        return {
            "state": "failed",
            "unit_id": unit_id,
            "task_id": latest["task_id"],
            "message": latest.get("error_message") or "高清处理失败",
        }
    try:
        await resolve_h3_refine_candidate(project_manager, project_name, episode, unit_id, queue=queue)
    except H3RefineUnavailable as exc:
        return {
            "state": "unavailable",
            "unit_id": unit_id,
            "code": exc.code,
            "params": exc.params,
        }
    return {"state": "available", "unit_id": unit_id}


async def enqueue_h3_refine_task(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    unit_id: str,
    *,
    source: str,
    user_id: str = DEFAULT_USER_ID,
    queue: GenerationQueue | None = None,
) -> dict[str, Any]:
    """Validate once and enqueue the shared Web/Agent/HyperFrames operation."""
    queue = queue or get_generation_queue()
    candidate = await resolve_h3_refine_candidate(
        project_manager,
        project_name,
        episode,
        unit_id,
        queue=queue,
    )
    task = await queue.enqueue_task(
        project_name=project_name,
        task_type=H3_REFINE_TASK_TYPE,
        media_type="video",
        resource_id=unit_id,
        script_file=candidate.script_file,
        payload={
            "episode": episode,
            "source_version": candidate.source_version,
            "source_task_id": candidate.source_task_id,
            "source_job_id": candidate.source_job_id,
            "duration_seconds": candidate.duration_seconds,
        },
        source=source,
        user_id=user_id,
        provider_id=PROVIDER_CROCO,
    )
    return {**task, "resource_id": unit_id, "episode": episode}


def _version_metadata(candidate: H3RefineCandidate, task_id: str, child_job_id: str) -> dict[str, Any]:
    ignored = {"version", "file", "file_url", "is_current", "created_at", "_previous_current_version"}
    metadata = {key: value for key, value in candidate.version_metadata.items() if key not in ignored}
    currency = VideoArtifactCurrencyFacts.from_dict(metadata.get("artifact_video_currency"))
    backend_model_id = str(candidate.version_metadata["execution_backend_model_id"])
    provider_model_id = candidate.version_metadata.get("execution_provider_model_id")
    if not isinstance(provider_model_id, str) or not provider_model_id:
        provider_model_id = backend_model_id
    metadata.update(
        {
            "artifact_video_currency": replace(currency, parent_version=candidate.source_version).to_dict(),
            "execution_task_id": task_id,
            "execution_provider_id": PROVIDER_CROCO,
            "execution_provider_model_id": provider_model_id,
            "execution_backend_model_id": backend_model_id,
            "execution_resolution": H3_REFINED_RESOLUTION,
            "h3_manual_refine": False,
            "h3_refined": True,
            "h3_refine_profile": H3_REFINE_PROFILE,
            "h3_refine_source_version": candidate.source_version,
            "h3_refine_source_task_id": candidate.source_task_id,
            "h3_refine_source_job_id": candidate.source_job_id,
            "h3_refine_job_id": child_job_id,
        }
    )
    return metadata


async def execute_h3_refine_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
    provider_job_id: str | None = None,
) -> dict[str, Any]:
    """Submit/resume, download, and atomically select one H3 HD child."""
    if not task_id:
        raise H3RefineUnavailable("video_hd_backend_unavailable")
    episode = payload.get("episode")
    if type(episode) is not int or episode <= 0:
        raise H3RefineUnavailable("video_hd_backend_unavailable")
    pm = get_project_manager()
    candidate = await resolve_h3_refine_candidate(pm, project_name, episode, resource_id)
    expected = {
        "source_version": candidate.source_version,
        "source_task_id": candidate.source_task_id,
        "source_job_id": candidate.source_job_id,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise H3RefineUnavailable("video_hd_source_changed")
    project_path = pm.get_project_path(project_name)
    current_file = project_path / resource_relative_path("reference_videos", resource_id)
    staged_file = current_file.with_name(f".{current_file.stem}.{task_id}.refine{current_file.suffix}")
    staged_file.unlink(missing_ok=True)
    source_model_id = str(candidate.version_metadata["execution_backend_model_id"])
    backend = await assemble_backend(
        provider_id=PROVIDER_CROCO,
        media_type="video",
        model_id=source_model_id,
        resolver=ConfigResolver(async_session_factory, user_id=user_id),
    )
    if not isinstance(backend, CrocoVideoBackend):
        raise H3RefineUnavailable("video_hd_backend_unavailable")
    committer = VideoArtifactCommitter(
        project_manager=pm,
        project_name=project_name,
        project_path=project_path,
        versions=VersionManager(project_path),
        resource_type="reference_videos",
        resource_id=resource_id,
        prompt=candidate.prompt,
    )
    try:
        result = await backend.refine_preview(
            candidate.source_job_id,
            output_path=staged_file,
            task_id=task_id,
            provider_job_id=provider_job_id,
            duration_seconds=candidate.duration_seconds,
        )
        child_job_id = provider_job_id
        if child_job_id is None:
            current_task = await get_generation_queue().get_task(task_id)
            child_job_id = current_task.get("provider_job_id") if current_task else None
        if not isinstance(child_job_id, str) or not child_job_id:
            raise H3RefineUnavailable("video_hd_backend_unavailable")
        metadata = _version_metadata(candidate, task_id, child_job_id)
        await committer.prepare_selection(staged_file, candidate.duration_seconds, metadata)
        outcome = await asyncio.to_thread(
            committer,
            staged_file,
            current_file,
            candidate.duration_seconds,
            metadata,
        )
        if not outcome.selected:
            raise H3RefineUnavailable("video_hd_source_changed")

        async def _finalize() -> dict[str, Any]:
            thumb_path = project_path / "reference_videos" / "thumbnails" / f"{resource_id}.jpg"
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            if not await extract_video_thumbnail(current_file, thumb_path):
                thumb_path.unlink(missing_ok=True)
            generated_at = datetime.now(UTC).isoformat()
            with pm.locked_script(project_name, candidate.script_file, validate=False) as script:
                unit = _find_unit(script, resource_id)
                assets = unit.setdefault("generated_assets", {})
                assets["video_clip"] = resource_relative_path("reference_videos", resource_id)
                assets["video_generated_at"] = generated_at
                assets["status"] = "completed"
                if result.video_uri:
                    assets["video_uri"] = result.video_uri
                else:
                    assets.pop("video_uri", None)
                if thumb_path.is_file():
                    assets["video_thumbnail"] = f"reference_videos/thumbnails/{resource_id}.jpg"
                else:
                    assets.pop("video_thumbnail", None)
                unit["video_review_status"] = "confirmed"
                unit["confirmed_video_version"] = outcome.version
            return {
                "resource_type": "reference_videos",
                "resource_id": resource_id,
                "version": outcome.version,
                "selected_current": True,
                "resolution": H3_REFINED_RESOLUTION,
                "video_uri": result.video_uri,
            }

        return await complete_video_artifact_commit(
            committer=committer,
            versions=VersionManager(project_path),
            resource_type="reference_videos",
            resource_id=resource_id,
            version=outcome.version,
            video_uri=result.video_uri,
            finalize=_finalize,
        )
    finally:
        await committer.release_admission_guard()
        staged_file.unlink(missing_ok=True)


async def ensure_episode_h3_hd(
    project_manager: ProjectManager,
    project_name: str,
    episode: int,
    *,
    source: str,
    user_id: str = DEFAULT_USER_ID,
) -> list[dict[str, Any]]:
    """Block HyperFrames materialization until every confirmed H3 preview is HD."""
    project = await asyncio.to_thread(project_manager.load_project, project_name)
    if not is_reference_video_project(project) or project.get("content_mode") not in {"drama", "course"}:
        return []
    script_file = _episode_script(project, episode)
    script = await asyncio.to_thread(project_manager.load_script, project_name, script_file)
    versions = VersionManager(project_manager.get_project_path(project_name))
    task_ids: list[str] = []
    results: list[dict[str, Any]] = []
    for unit in script.get("video_units") or []:
        if not isinstance(unit, dict) or unit.get("video_review_status") != "confirmed":
            continue
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str):
            continue
        _version, record = await asyncio.to_thread(_selected_record, versions, unit_id)
        if _is_refined(record):
            continue
        provider_id = record.get("execution_provider_id")
        model_id = record.get("execution_backend_model_id")
        is_h3_preview = (
            provider_id == PROVIDER_CROCO
            and isinstance(model_id, str)
            and is_minimax_h3_model(model_id)
            and (
                record.get("h3_manual_refine") is True
                or record.get("execution_resolution") in {"480p", H3_FIRST_PASS_RESOLUTION}
            )
        )
        if not is_h3_preview:
            continue
        status = await h3_refine_status(project_manager, project_name, episode, unit_id, user_id=user_id)
        if status["state"] == "completed":
            continue
        if status["state"] == "unavailable":
            code = status.get("code")
            params = status.get("params")
            raise H3RefineUnavailable(
                code if isinstance(code, str) else "video_hd_checkpoint_unavailable",
                **(params if isinstance(params, dict) else {}),
            )
        if status["state"] == "processing":
            task_ids.append(status["task_id"])
            continue
        task = await enqueue_h3_refine_task(
            project_manager,
            project_name,
            episode,
            unit_id,
            source=source,
            user_id=user_id,
        )
        task_ids.append(task["task_id"])
    if task_ids:
        completed = await asyncio.gather(*(wait_for_task(task_id, user_id=user_id) for task_id in task_ids))
        failures = [task for task in completed if task.get("status") != "succeeded"]
        if failures:
            failed_ids = ", ".join(str(task.get("resource_id") or task.get("task_id")) for task in failures)
            raise H3RefineUnavailable("video_hd_failed", unit_ids=failed_ids)
        results.extend(task.get("result") or {} for task in completed)
    return results


__all__ = [
    "H3_REFINE_TASK_TYPE",
    "H3RefineUnavailable",
    "enqueue_h3_refine_task",
    "ensure_episode_h3_hd",
    "execute_h3_refine_task",
    "h3_refine_status",
]
