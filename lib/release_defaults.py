"""Pinned model defaults for the ready-to-run local release branch."""

from __future__ import annotations

RELEASE_VIDEO_BACKEND = "croco/minimax-h3"
RELEASE_IMAGE_BACKEND = "runware/openai:gpt-image@2"
RELEASE_STORYBOARD_IMAGE_BACKEND = "runware/openai:gpt-image@2"
# 内置 DeepSeek 已从用户可见目录移除。这些常量仅保留为显式调用 release defaults
# 的历史兼容值；新项目的请求默认值为空，实际继承系统设置（可指向自定义 Deepseek）。
RELEASE_TEXT_BACKEND = "deepseek/deepseek-v4-pro"
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
