"""Non-destructive transcript view for text-only Agent models."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

IMAGE_OMITTED_TEXT = (
    "[Image omitted: the current Agent model does not support image input. "
    "Use file metadata or ask the user to perform the visual review.]"
)


def omit_images_for_text_model(entries: list[dict] | None) -> list[dict] | None:
    """Return a replay-safe copy with image blocks replaced by text.

    The durable SessionStore remains lossless. Only the list returned to the
    SDK is transformed, so an image-capable model can still resume the original
    transcript later.
    """

    if entries is None:
        return None
    return [_omit_images(deepcopy(entry)) for entry in entries]


def _omit_images(value: Any) -> Any:
    if isinstance(value, list):
        return [_omit_images(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "image":
        return {"type": "text", "text": IMAGE_OMITTED_TEXT}
    return {key: _omit_images(item) for key, item in value.items()}


class TextOnlySessionStore:
    """SessionStore adapter that filters images only while loading history."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def append(self, key: dict, entries: list[dict]) -> None:
        await self._store.append(key, entries)

    async def load(self, key: dict) -> list[dict] | None:
        return omit_images_for_text_model(await self._store.load(key))

    async def list_sessions(self, project_key: str) -> list[dict]:
        return await self._store.list_sessions(project_key)

    async def list_session_summaries(self, project_key: str) -> list[dict]:
        return await self._store.list_session_summaries(project_key)

    async def delete(self, key: dict) -> None:
        await self._store.delete(key)

    async def list_subkeys(self, key: dict) -> list[str]:
        return await self._store.list_subkeys(key)


__all__ = ["IMAGE_OMITTED_TEXT", "TextOnlySessionStore", "omit_images_for_text_model"]
