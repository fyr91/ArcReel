"""Pinned model defaults for the ready-to-run local release branch."""

from __future__ import annotations

RELEASE_VIDEO_BACKEND = "croco/minimax-h3"
RELEASE_IMAGE_BACKEND = "runware/google:nano-banana@2-lite"
RELEASE_STORYBOARD_IMAGE_BACKEND = "runware/google:nano-banana@2-lite"
RELEASE_TEXT_BACKEND = "deepseek/deepseek-v4-flash-vision-exp"
RELEASE_SIMPLE_TEXT_BACKEND = "deepseek/deepseek-v4-flash-vision-exp"
RELEASE_COMPLEX_TEXT_BACKEND = "deepseek/deepseek-v4-pro"
RELEASE_VIDEO_RESOLUTION = "480p"
RELEASE_IMAGE_RESOLUTION = "1K"


def release_project_model_settings() -> dict[str, dict[str, str]]:
    """Return fresh project-level resolution settings for the release defaults."""

    return {
        RELEASE_VIDEO_BACKEND: {"resolution": RELEASE_VIDEO_RESOLUTION},
        RELEASE_IMAGE_BACKEND: {"resolution": RELEASE_IMAGE_RESOLUTION},
    }
