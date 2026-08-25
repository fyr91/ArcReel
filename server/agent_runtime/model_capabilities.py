"""Capability decisions for the model that powers the interactive Agent.

The Claude Agent SDK exposes an Anthropic-compatible transport, but a custom
endpoint may route that transport to a text-only model. In that case the
SDK's built-in ``Read`` tool can return an image block that the model rejects;
the same block is then replayed from the transcript on every later turn.
"""

from __future__ import annotations

from pathlib import Path

_TEXT_ONLY_MODEL_PREFIXES = ("deepseek-",)

_IMAGE_SUFFIXES = frozenset(
    {
        ".avif",
        ".bmp",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)


def supports_agent_image_input(model: str) -> bool:
    """Return whether ``model`` may receive image content blocks.

    Unknown models stay enabled so custom multimodal endpoints do not lose
    functionality. Add a family only after its endpoint explicitly rejects
    image input.
    """

    normalized = model.strip().lower()
    if not normalized:
        return True
    return not normalized.startswith(_TEXT_ONLY_MODEL_PREFIXES)


def is_image_path(path: object) -> bool:
    """Return whether a Read-tool path names a supported raster image."""

    if not isinstance(path, str) or not path.strip():
        return False
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


__all__ = ["is_image_path", "supports_agent_image_input"]
