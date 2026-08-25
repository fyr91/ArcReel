"""Project-local background music generation for HyperFrames auto editing."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.audio_backends.base import AudioSynthesisRequest
from lib.audio_utils import probe_existing_media_duration_seconds
from lib.backend_assembly import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.json_io import atomic_write_bytes, atomic_write_json
from lib.path_safety import safe_join
from lib.project_manager import ProjectManager
from lib.providers import PROVIDER_CROCO
from server.services.hyperframes_workspace import HyperframesWorkspaceService

MUSIC_MODEL = "minimax-music-3"
BACKGROUND_MUSIC_VOLUME = 0.15
BACKGROUND_MUSIC_FADE_SECONDS = 2.5
MAX_MUSIC_DIRECTION_LENGTH = 2_000

_MUSIC_BLOCK_START = "<!-- arcreel-background-music:start -->"
_MUSIC_BLOCK_END = "<!-- arcreel-background-music:end -->"
_MUSIC_BLOCK_RE = re.compile(
    rf"\s*{re.escape(_MUSIC_BLOCK_START)}.*?{re.escape(_MUSIC_BLOCK_END)}\s*",
    re.DOTALL,
)
_UNMANAGED_MUSIC_RE = re.compile(
    r"\s*<audio\b(?=[^>]*\bdata-audio-group=(?:\"music\"|'music'))[^>]*>\s*</audio>\s*",
    re.IGNORECASE | re.DOTALL,
)
_COMPOSITION_ROOT_RE = re.compile(
    r"<div\b(?=[^>]*\bdata-composition-id=(?:\"[^\"]+\"|'[^']+'))[^>]*>",
    re.IGNORECASE,
)
_DIV_TAG_RE = re.compile(r"</?div\b[^>]*>", re.IGNORECASE)

BackendFactory = Callable[[], Awaitable[Any]]
DurationProbe = Callable[[Path], Awaitable[float | None]]


class HyperframesMusicUnavailable(RuntimeError):
    """The requested episode cannot currently receive generated background music."""


@dataclass(frozen=True, slots=True)
class HyperframesBackgroundMusic:
    episode: int
    path: Path
    relative_path: str
    metadata_path: str
    duration_seconds: float
    actual_duration_seconds: float | None
    volume: float
    seed: int
    html_snippet: str

    def to_dict(self) -> dict[str, object]:
        return {
            "episode": self.episode,
            "path": str(self.path),
            "relative_path": self.relative_path,
            "metadata_path": self.metadata_path,
            "duration_seconds": self.duration_seconds,
            "actual_duration_seconds": self.actual_duration_seconds,
            "volume": self.volume,
            "seed": self.seed,
            "html_snippet": self.html_snippet,
        }


def _music_caption(direction: str, duration_seconds: float) -> str:
    return f"""Global Metadata:
{direction}

Vocal Details:
Strictly instrumental. No vocals, spoken word, rap, choir, humming, or vocal samples.

Arrangement:
One continuous, cohesive background score lasting about {duration_seconds:.2f} seconds. Use a restrained intro, a smooth emotional arc, no abrupt style changes, and a clean natural ending.

Mix Intent:
Background underscore for narration and edited video. Keep the arrangement supportive and leave space for dialogue."""


class HyperframesMusicService:
    """Generate one continuous Music 3 bed without writing outside the episode workspace."""

    def __init__(
        self,
        project_manager: ProjectManager,
        *,
        backend_factory: BackendFactory | None = None,
        duration_probe: DurationProbe = probe_existing_media_duration_seconds,
    ) -> None:
        self._pm = project_manager
        self._backend_factory = backend_factory or self._build_backend
        self._duration_probe = duration_probe

    @staticmethod
    async def _build_backend() -> Any:
        return await assemble_backend(
            provider_id=PROVIDER_CROCO,
            media_type="audio",
            model_id=MUSIC_MODEL,
            resolver=ConfigResolver(async_session_factory),
        )

    async def generate(
        self,
        project_name: str,
        episode: int,
        *,
        direction: str,
        seed: int | None = None,
        task_id: str | None = None,
        provider_job_id: str | None = None,
    ) -> HyperframesBackgroundMusic:
        direction = direction.strip()
        if not direction:
            raise HyperframesMusicUnavailable("music direction must not be empty")
        if len(direction) > MAX_MUSIC_DIRECTION_LENGTH:
            raise HyperframesMusicUnavailable(f"music direction exceeds {MAX_MUSIC_DIRECTION_LENGTH} characters")
        workspace = HyperframesWorkspaceService(self._pm).status(project_name, episode)
        if workspace is None:
            raise HyperframesMusicUnavailable("prepare the HyperFrames episode workspace first")

        manifest_file = safe_join(workspace.path, "manifest.json", require_file=True)
        manifest = await asyncio.to_thread(lambda: json.loads(manifest_file.read_text(encoding="utf-8")))
        units = manifest.get("units")
        if not isinstance(units, list):
            raise HyperframesMusicUnavailable("HyperFrames manifest has no units")
        total_microseconds = sum(
            int(video.get("duration_microseconds", 0))
            for unit in units
            if isinstance(unit, dict) and isinstance((video := unit.get("video")), dict)
        )
        duration_seconds = total_microseconds / 1_000_000
        if duration_seconds <= 0:
            raise HyperframesMusicUnavailable("HyperFrames episode duration is unavailable")

        identity = json.dumps(
            {
                "project": project_name,
                "episode": episode,
                "direction": direction,
                "duration_seconds": round(duration_seconds, 6),
                "seed": seed,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()
        effective_seed = seed if seed is not None else int(digest[:8], 16)
        filename = f"background-music-{digest[:12]}.mp3"
        metadata_name = f"background-music-{digest[:12]}.json"
        media_dir = safe_join(workspace.path, "media")
        output_path = safe_join(media_dir, filename)
        metadata_path = safe_join(workspace.path, metadata_name)
        relative_path = output_path.relative_to(workspace.path).as_posix()
        element_id = f"background-music-{digest[:12]}"
        fade_seconds = min(BACKGROUND_MUSIC_FADE_SECONDS, duration_seconds / 4)
        fade_out_start = max(fade_seconds, duration_seconds - fade_seconds)
        points: list[dict[str, float]] = [
            {"t": 0.0, "v": 0.0},
            {"t": round(fade_seconds, 6), "v": BACKGROUND_MUSIC_VOLUME},
        ]
        if fade_out_start > fade_seconds:
            points.append({"t": round(fade_out_start, 6), "v": BACKGROUND_MUSIC_VOLUME})
        points.append({"t": round(duration_seconds, 6), "v": 0.0})
        automation = html.escape(
            json.dumps(
                {"version": 1, "lanes": [{"target": "volume", "points": points}]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            quote=True,
        )
        html_snippet = (
            f'<audio id="{element_id}" data-audio-group="music" data-start="0" '
            f'data-duration="{duration_seconds:.6f}" data-track-index="4" '
            f'data-automation="{automation}" src="{relative_path}"></audio>'
        )

        if not output_path.is_file():
            temp_path = safe_join(media_dir, f".{filename}.{uuid.uuid4().hex}.tmp.mp3")
            caption = _music_caption(direction, duration_seconds)
            backend = await self._backend_factory()
            try:
                await backend.synthesize(
                    AudioSynthesisRequest(
                        text=caption,
                        output_path=temp_path,
                        voice="",
                        lyrics="",
                        max_duration=duration_seconds,
                        seed=effective_seed,
                        tiled_decode=False,
                        output_format="mp3",
                        client_job_id=f"arcreel:hyperframes:bgm:{digest}",
                        task_id=task_id,
                        provider_job_id=provider_job_id,
                    )
                )
                if not temp_path.is_file() or temp_path.stat().st_size <= 0:
                    raise HyperframesMusicUnavailable("GPU music generation returned no audio file")

                def _commit() -> None:
                    with self._pm.file_lock(workspace.path):
                        if output_path.exists():
                            temp_path.unlink(missing_ok=True)
                        else:
                            temp_path.replace(output_path)

                await asyncio.to_thread(_commit)
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise

        actual_duration = await self._duration_probe(output_path)
        if actual_duration is not None and actual_duration + 0.25 < duration_seconds:
            raise HyperframesMusicUnavailable(
                "generated background music is shorter than the episode; regenerate with a longer duration"
            )
        atomic_write_json(
            metadata_path,
            {
                "schema_version": 1,
                "provider": PROVIDER_CROCO,
                "model": MUSIC_MODEL,
                "episode": episode,
                "direction": direction,
                "instrumental": True,
                "requested_duration_seconds": duration_seconds,
                "actual_duration_seconds": actual_duration,
                "volume": BACKGROUND_MUSIC_VOLUME,
                "fade_in_seconds": fade_seconds,
                "fade_out_seconds": fade_seconds,
                "seed": effective_seed,
                "media": relative_path,
            },
        )
        await asyncio.to_thread(
            self._upsert_composition_music,
            workspace.path,
            html_snippet,
        )
        return HyperframesBackgroundMusic(
            episode=episode,
            path=output_path,
            relative_path=relative_path,
            metadata_path=metadata_path.relative_to(workspace.path).as_posix(),
            duration_seconds=duration_seconds,
            actual_duration_seconds=actual_duration,
            volume=BACKGROUND_MUSIC_VOLUME,
            seed=effective_seed,
            html_snippet=html_snippet,
        )

    def _upsert_composition_music(self, workspace: Path, html_snippet: str) -> None:
        """Install one managed music bed without disturbing other Studio edits."""
        entry_file = safe_join(workspace, "index.html", require_file=True)
        with self._pm.file_lock(workspace):
            source = entry_file.read_text(encoding="utf-8")
            source = _MUSIC_BLOCK_RE.sub("\n", source)
            source = _UNMANAGED_MUSIC_RE.sub("\n", source)
            root_match = _COMPOSITION_ROOT_RE.search(source)
            root_close = None
            if root_match is not None:
                depth = 0
                for tag in _DIV_TAG_RE.finditer(source, root_match.start()):
                    if tag.group(0).lower().startswith("</"):
                        depth -= 1
                        if depth == 0:
                            root_close = tag.start()
                            break
                    else:
                        depth += 1
            if root_close is None:
                raise HyperframesMusicUnavailable("HyperFrames composition root is unavailable")
            block = f"  {_MUSIC_BLOCK_START}\n    {html_snippet}\n  {_MUSIC_BLOCK_END}\n"
            updated = f"{source[:root_close]}{block}{source[root_close:]}"
            atomic_write_bytes(entry_file, updated.encode("utf-8"))


__all__ = [
    "BACKGROUND_MUSIC_VOLUME",
    "BACKGROUND_MUSIC_FADE_SECONDS",
    "HyperframesBackgroundMusic",
    "HyperframesMusicService",
    "HyperframesMusicUnavailable",
    "MAX_MUSIC_DIRECTION_LENGTH",
    "MUSIC_MODEL",
]
