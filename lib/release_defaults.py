"""Pinned model defaults for the ready-to-run local release branch."""

from __future__ import annotations

RELEASE_VIDEO_BACKEND = "croco/minimax-h3"
RELEASE_IMAGE_BACKEND = "ark-agent-plan/doubao-seedream-5.0-lite"
RELEASE_STORYBOARD_IMAGE_BACKEND = "runware/google:nano-banana@2-lite"
RELEASE_TEXT_BACKEND = "ark-agent-plan/deepseek-v4-pro"
RELEASE_SIMPLE_TEXT_BACKEND = "ark-agent-plan/minimax-m3"
RELEASE_COMPLEX_TEXT_BACKEND = "ark-agent-plan/deepseek-v4-pro"
RELEASE_VIDEO_RESOLUTION = "480p"


def release_project_model_settings() -> dict[str, dict[str, str]]:
    """Return a fresh project-level settings mapping for the H3 default."""

    return {RELEASE_VIDEO_BACKEND: {"resolution": RELEASE_VIDEO_RESOLUTION}}
