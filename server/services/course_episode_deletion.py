"""Two-phase deletion for one independently sourced course episode.

Web and Agent boundaries both call this service.  The preview signs the exact
episode/file/Manifest snapshot; commit accepts only that short-lived snapshot,
so a destructive call cannot skip review or delete content that appeared after
the user confirmed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import jwt

from lib.artifact_activation import register_artifact_entries_atomically
from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
from lib.episode_paths import episode_drafts_dir
from lib.formal_write import formal_write_transaction
from lib.path_safety import PathTraversalError, safe_join
from lib.project_change_hints import emit_project_change_hint
from lib.project_manager import ProjectManager
from server.auth import get_token_secret

CONFIRMATION_EXPIRY_SECONDS = 300
_TOKEN_PURPOSE = "course_episode_delete"
_PROTECTED_RESOURCE_DIRS = frozenset({"characters", "scenes", "props", "products"})
_RUNTIME_LOCK_SUFFIX = ".lock"


class CourseEpisodeDeletionError(RuntimeError):
    """A safe deletion preview or commit could not be produced."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class CourseEpisodeDeletionPreview:
    episode: int
    title: str
    source_files: int
    scripts: int
    drafts: int
    generated_artifacts: int
    workspace_files: int
    total_files: int
    artifact_claims: int
    confirmation_token: str
    expires_in: int = CONFIRMATION_EXPIRY_SECONDS

    def to_dict(self) -> dict[str, object]:
        return {
            "episode": self.episode,
            "title": self.title,
            "effects": {
                "source_files": self.source_files,
                "scripts": self.scripts,
                "drafts": self.drafts,
                "generated_artifacts": self.generated_artifacts,
                "workspace_files": self.workspace_files,
            },
            "total_files": self.total_files,
            "artifact_claims": self.artifact_claims,
            "confirmation_token": self.confirmation_token,
            "expires_in": self.expires_in,
        }


@dataclass(frozen=True, slots=True)
class CourseEpisodeDeletionResult:
    episode: int
    title: str
    deleted_files: tuple[str, ...]
    removed_artifact_claims: int

    def to_dict(self) -> dict[str, object]:
        return {
            "success": True,
            "episode": self.episode,
            "title": self.title,
            "deleted_files": list(self.deleted_files),
            "deleted_file_count": len(self.deleted_files),
            "removed_artifact_claims": self.removed_artifact_claims,
        }


@dataclass(frozen=True, slots=True)
class _DeletionPlan:
    episode: int
    title: str
    episode_entry: Mapping[str, Any]
    files: tuple[Path, ...]
    relative_files: tuple[str, ...]
    manifest_entries: Mapping[ArtifactKey, ArtifactManifestEntry]
    fingerprint: str
    source_files: int
    scripts: int
    drafts: int
    generated_artifacts: int
    workspace_files: int
    cleanup_roots: tuple[Path, ...]


class CourseEpisodeDeletionService:
    """Preview and commit deletion of one course episode."""

    def __init__(self, project_manager: ProjectManager):
        self._pm = project_manager

    def preview(self, project_name: str, episode: int) -> CourseEpisodeDeletionPreview:
        _require_episode(episode)
        project_dir = self._pm.get_project_path(project_name)
        project = self._pm.load_project(project_name)
        plan = _build_plan(project_dir, project, episode)
        now = time.time()
        token = jwt.encode(
            {
                "purpose": _TOKEN_PURPOSE,
                "project": project_name,
                "episode": episode,
                "fingerprint": plan.fingerprint,
                "iat": now,
                "exp": now + CONFIRMATION_EXPIRY_SECONDS,
            },
            get_token_secret(),
            algorithm="HS256",
        )
        return CourseEpisodeDeletionPreview(
            episode=episode,
            title=plan.title,
            source_files=plan.source_files,
            scripts=plan.scripts,
            drafts=plan.drafts,
            generated_artifacts=plan.generated_artifacts,
            workspace_files=plan.workspace_files,
            total_files=len(plan.files),
            artifact_claims=len(plan.manifest_entries),
            confirmation_token=token,
        )

    def delete(
        self,
        project_name: str,
        episode: int,
        confirmation_token: str,
    ) -> CourseEpisodeDeletionResult:
        _require_episode(episode)
        expected_fingerprint = _verify_confirmation_token(
            confirmation_token,
            project_name=project_name,
            episode=episode,
        )
        project_dir = self._pm.get_project_path(project_name)
        initial_plan = _build_plan(project_dir, self._pm.load_project(project_name), episode)
        if initial_plan.fingerprint != expected_fingerprint:
            raise CourseEpisodeDeletionError(
                "course_episode_delete_confirmation_stale",
                "episode content changed after deletion was confirmed",
            )

        committed_plan: _DeletionPlan | None = None
        # Writers use per-file locks before the project metadata lock.  Acquire
        # the same order for every current episode file so deletion cannot race
        # a script/step1/media replacement and cannot deadlock with one.
        with ExitStack() as locks:
            for path in initial_plan.files:
                if _needs_writer_lock(project_dir, path):
                    locks.enter_context(self._pm.file_lock(path))

            def _remove_episode(project: dict[str, Any]) -> None:
                nonlocal committed_plan
                current = _build_plan(project_dir, project, episode)
                if current.fingerprint != expected_fingerprint:
                    raise CourseEpisodeDeletionError(
                        "course_episode_delete_confirmation_stale",
                        "episode content changed after deletion was confirmed",
                    )
                episodes = project.get("episodes")
                if not isinstance(episodes, list):  # guarded by _build_plan
                    raise CourseEpisodeDeletionError(
                        "course_episode_delete_invalid_project",
                        "project episodes must be an array",
                    )
                project["episodes"] = [
                    entry for entry in episodes if not (isinstance(entry, Mapping) and entry.get("episode") == episode)
                ]
                workflow = project.get("workflow")
                per_episode = workflow.get("asset_inventory_by_episode") if isinstance(workflow, dict) else None
                if isinstance(per_episode, dict):
                    per_episode.pop(str(episode), None)
                    per_episode.pop(episode, None)
                if episode == 1:
                    project.pop("overview", None)
                committed_plan = current

            def _delete_files_and_claims(_project_file: Path) -> None:
                if committed_plan is None:  # pragma: no cover - update_project callback contract
                    raise RuntimeError("course episode deletion plan was not committed")
                with formal_write_transaction(*committed_plan.files):
                    for path in committed_plan.files:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            raise CourseEpisodeDeletionError(
                                "course_episode_delete_confirmation_stale",
                                "episode content changed while deletion was committing",
                            ) from None
                    if committed_plan.manifest_entries:
                        register_artifact_entries_atomically(
                            project_dir,
                            dict.fromkeys(committed_plan.manifest_entries),
                            expected_entries=committed_plan.manifest_entries,
                        )

            self._pm.update_project(
                project_name,
                _remove_episode,
                on_commit=_delete_files_and_claims,
            )

        if committed_plan is None:  # pragma: no cover - update_project callback contract
            raise RuntimeError("course episode deletion did not produce a committed plan")
        for root in committed_plan.cleanup_roots:
            _prune_empty_tree(root, stop=project_dir)
        emit_project_change_hint(
            project_name,
            changed_paths=["project.json", *committed_plan.relative_files],
        )
        return CourseEpisodeDeletionResult(
            episode=episode,
            title=committed_plan.title,
            deleted_files=committed_plan.relative_files,
            removed_artifact_claims=len(committed_plan.manifest_entries),
        )

    async def delete_async(
        self,
        project_name: str,
        episode: int,
        confirmation_token: str,
    ) -> CourseEpisodeDeletionResult:
        """Stop the episode's live editor, then run the durable deletion."""

        import asyncio

        _verify_confirmation_token(
            confirmation_token,
            project_name=project_name,
            episode=episode,
        )
        project_dir = self._pm.get_project_path(project_name)
        from server.services.hyperframes_workspace import get_hyperframes_studio_manager

        await get_hyperframes_studio_manager().stop(project_dir / "hyperframes" / f"episode_{episode:02d}")
        return await asyncio.to_thread(
            self.delete,
            project_name,
            episode,
            confirmation_token,
        )


def _build_plan(project_dir: Path, project: Mapping[str, Any], episode: int) -> _DeletionPlan:
    if project.get("content_mode") != "course":
        raise CourseEpisodeDeletionError(
            "course_episode_delete_not_course",
            "only course projects support deleting an individual episode",
        )
    raw_episodes = project.get("episodes")
    if not isinstance(raw_episodes, list):
        raise CourseEpisodeDeletionError(
            "course_episode_delete_invalid_project",
            "project episodes must be an array",
        )
    matches = [entry for entry in raw_episodes if isinstance(entry, Mapping) and entry.get("episode") == episode]
    if not matches:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_not_found",
            f"course episode {episode} does not exist",
        )
    if len(matches) != 1:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_invalid_project",
            f"course episode {episode} has duplicate metadata entries",
        )
    entry = matches[0]
    files_by_category: dict[str, set[Path]] = {
        "source": set(),
        "script": set(),
        "draft": set(),
        "generated": set(),
        "workspace": set(),
    }
    cleanup_roots: list[Path] = []

    source_file = entry.get("source_file")
    if isinstance(source_file, str) and source_file:
        source_path = _safe_owned_path(project_dir, source_file, required_root="source")
        _assert_unshared_binding(raw_episodes, entry, "source_file", source_file)
        _add_present(files_by_category["source"], source_path)
        raw_dir = project_dir / "source" / "raw"
        if raw_dir.is_dir():
            for candidate in raw_dir.iterdir():
                if candidate.stem == source_path.stem:
                    _add_present(files_by_category["source"], candidate)

    script_file = entry.get("script_file")
    if isinstance(script_file, str) and script_file:
        script_path = _safe_owned_path(project_dir, script_file, required_root="scripts")
        _assert_unshared_binding(raw_episodes, entry, "script_file", script_file)
        _add_present(files_by_category["script"], script_path)

    directory_categories = (
        (episode_drafts_dir(project_dir, episode), "draft"),
        (project_dir / "subtitles" / f"episode_{episode}", "generated"),
        (project_dir / "presentations" / f"episode_{episode}", "generated"),
        (project_dir / "hyperframes" / f"episode_{episode:02d}", "workspace"),
    )
    for root, category in directory_categories:
        cleanup_roots.append(root)
        files_by_category[category].update(_tree_files(root))

    adapter = ProjectArtifactManifestAdapter(project_dir)
    snapshot = adapter.snapshot_entries()
    manifest_entries = {key: value for key, value in snapshot.items() if key.episode_number == episode}
    for manifest_entry in manifest_entries.values():
        relative = PurePosixPath(manifest_entry.artifact_path)
        if relative.parts and relative.parts[0] in _PROTECTED_RESOURCE_DIRS:
            raise CourseEpisodeDeletionError(
                "course_episode_delete_protected_resource",
                f"episode claim points into protected resource library: {manifest_entry.artifact_path}",
            )
        artifact_path = _safe_owned_path(project_dir, manifest_entry.artifact_path)
        _add_present(files_by_category["generated"], artifact_path)

    # A path can be discovered through both its canonical binding and Manifest.
    # Assign it to the most user-meaningful category exactly once.
    ordered_categories = ("source", "script", "draft", "workspace", "generated")
    seen: set[Path] = set()
    categorized: dict[str, tuple[Path, ...]] = {}
    for category in ordered_categories:
        unique = tuple(sorted(files_by_category[category] - seen, key=lambda path: path.as_posix()))
        categorized[category] = unique
        seen.update(unique)
    files = tuple(path for category in ordered_categories for path in categorized[category])
    relative_files = tuple(path.relative_to(project_dir).as_posix() for path in files)
    fingerprint = _plan_fingerprint(
        episode=episode,
        episode_entry=entry,
        project=project,
        files=files,
        manifest_entries=manifest_entries,
    )
    title = entry.get("title")
    return _DeletionPlan(
        episode=episode,
        title=title if isinstance(title, str) else "",
        episode_entry=dict(entry),
        files=files,
        relative_files=relative_files,
        manifest_entries=manifest_entries,
        fingerprint=fingerprint,
        source_files=len(categorized["source"]),
        scripts=len(categorized["script"]),
        drafts=len(categorized["draft"]),
        generated_artifacts=len(categorized["generated"]),
        workspace_files=len(categorized["workspace"]),
        cleanup_roots=tuple(cleanup_roots),
    )


def _verify_confirmation_token(token: str, *, project_name: str, episode: int) -> str:
    if not isinstance(token, str) or not token:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_confirmation_required",
            "a deletion preview and explicit confirmation are required",
        )
    try:
        payload = jwt.decode(token, get_token_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_confirmation_expired",
            "deletion confirmation expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_confirmation_invalid",
            "deletion confirmation is invalid",
        ) from exc
    if (
        payload.get("purpose") != _TOKEN_PURPOSE
        or payload.get("project") != project_name
        or payload.get("episode") != episode
        or not isinstance(payload.get("fingerprint"), str)
    ):
        raise CourseEpisodeDeletionError(
            "course_episode_delete_confirmation_invalid",
            "deletion confirmation does not match this episode",
        )
    return str(payload["fingerprint"])


def _plan_fingerprint(
    *,
    episode: int,
    episode_entry: Mapping[str, Any],
    project: Mapping[str, Any],
    files: tuple[Path, ...],
    manifest_entries: Mapping[ArtifactKey, ArtifactManifestEntry],
) -> str:
    file_state: list[dict[str, object]] = []
    for path in files:
        try:
            state = path.lstat()
        except FileNotFoundError as exc:
            raise CourseEpisodeDeletionError(
                "course_episode_delete_confirmation_stale",
                f"episode file changed while previewing: {path.name}",
            ) from exc
        item: dict[str, object] = {
            "path": path.as_posix(),
            "device": state.st_dev,
            "inode": state.st_ino,
            "mode": state.st_mode,
            "size": state.st_size,
            "mtime_ns": state.st_mtime_ns,
            "ctime_ns": state.st_ctime_ns,
        }
        if path.is_symlink():
            item["symlink_target"] = os.readlink(path)
        file_state.append(item)
    manifest_state = [
        {
            "key": key.encode(),
            "artifact_path": value.artifact_path,
            "basis_digest": value.basis_digest,
        }
        for key, value in sorted(manifest_entries.items(), key=lambda item: item[0].encode())
    ]
    workflow = project.get("workflow")
    per_episode = workflow.get("asset_inventory_by_episode") if isinstance(workflow, Mapping) else None
    payload = {
        "episode": episode,
        "episode_entry": episode_entry,
        "asset_inventory": (per_episode.get(str(episode)) if isinstance(per_episode, Mapping) else None),
        "project_overview": project.get("overview") if episode == 1 else None,
        "files": file_state,
        "manifest": manifest_state,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_owned_path(project_dir: Path, relative: str, *, required_root: str | None = None) -> Path:
    try:
        normalized = PurePosixPath(relative)
        path = safe_join(project_dir, relative)
    except (PathTraversalError, ValueError) as exc:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_invalid_project",
            f"episode owns an unsafe path: {relative!r}",
        ) from exc
    if required_root is not None and (not normalized.parts or normalized.parts[0] != required_root):
        raise CourseEpisodeDeletionError(
            "course_episode_delete_protected_resource",
            f"episode binding is outside {required_root}/: {relative}",
        )
    return path


def _assert_unshared_binding(
    episodes: list[object],
    selected: Mapping[str, Any],
    field: str,
    value: str,
) -> None:
    if any(
        isinstance(candidate, Mapping) and candidate is not selected and candidate.get(field) == value
        for candidate in episodes
    ):
        raise CourseEpisodeDeletionError(
            "course_episode_delete_shared_file",
            f"episode {field} is shared by another episode: {value}",
        )


def _add_present(target: set[Path], path: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            raise CourseEpisodeDeletionError(
                "course_episode_delete_invalid_project",
                f"episode-owned file path is a directory: {path}",
            )
        target.add(path)


def _needs_writer_lock(project_dir: Path, path: Path) -> bool:
    relative = path.relative_to(project_dir)
    if relative.parts and relative.parts[0] in {"scripts", "drafts"}:
        return True
    return (path.parent / f".{path.name}.lock").exists()


def _tree_files(root: Path) -> set[Path]:
    if root.is_symlink():
        return {root}
    if not root.exists():
        return set()
    if not root.is_dir():
        raise CourseEpisodeDeletionError(
            "course_episode_delete_invalid_project",
            f"episode-owned directory path is not a directory: {root}",
        )
    files: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            raise CourseEpisodeDeletionError(
                "course_episode_delete_invalid_project",
                f"episode-owned directory is unreadable: {current}",
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.name.startswith(".") and entry.name.endswith(_RUNTIME_LOCK_SUFFIX):
                continue
            if entry.is_symlink():
                files.add(path)
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.add(path)
            else:
                raise CourseEpisodeDeletionError(
                    "course_episode_delete_invalid_project",
                    f"episode-owned path is not a regular file: {path}",
                )
    return files


def _prune_empty_tree(root: Path, *, stop: Path) -> None:
    if root == stop or not root.exists() or root.is_symlink():
        return
    for current, _dirs, _files in os.walk(root, topdown=False, followlinks=False):
        path = Path(current)
        try:
            path.rmdir()
        except OSError:
            pass


def _require_episode(episode: int) -> None:
    if type(episode) is not int or episode < 1:
        raise CourseEpisodeDeletionError(
            "course_episode_delete_not_found",
            "episode must be a positive integer",
        )


__all__ = [
    "CONFIRMATION_EXPIRY_SECONDS",
    "CourseEpisodeDeletionError",
    "CourseEpisodeDeletionPreview",
    "CourseEpisodeDeletionResult",
    "CourseEpisodeDeletionService",
]
