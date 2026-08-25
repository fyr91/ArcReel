"""Release branch project-default contract tests."""

from __future__ import annotations

import pytest

from lib.config.registry import PROVIDER_REGISTRY
from lib.release_defaults import (
    RELEASE_COMPLEX_TEXT_BACKEND,
    RELEASE_IMAGE_BACKEND,
    RELEASE_SIMPLE_TEXT_BACKEND,
    RELEASE_STORYBOARD_IMAGE_BACKEND,
    RELEASE_TEXT_BACKEND,
    RELEASE_VIDEO_BACKEND,
    RELEASE_VIDEO_RESOLUTION,
    release_project_model_settings,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("backend", "media_type"),
    [
        (RELEASE_VIDEO_BACKEND, "video"),
        (RELEASE_IMAGE_BACKEND, "image"),
        (RELEASE_STORYBOARD_IMAGE_BACKEND, "image"),
        (RELEASE_TEXT_BACKEND, "text"),
        (RELEASE_SIMPLE_TEXT_BACKEND, "text"),
        (RELEASE_COMPLEX_TEXT_BACKEND, "text"),
    ],
)
def test_release_backend_exists_with_expected_media_type(backend: str, media_type: str) -> None:
    provider_id, model_id = backend.split("/", 1)
    assert PROVIDER_REGISTRY[provider_id].models[model_id].media_type == media_type


def test_release_video_resolution_is_supported_and_mapping_is_fresh() -> None:
    provider_id, model_id = RELEASE_VIDEO_BACKEND.split("/", 1)
    assert RELEASE_VIDEO_RESOLUTION in PROVIDER_REGISTRY[provider_id].models[model_id].resolutions

    first = release_project_model_settings()
    first[RELEASE_VIDEO_BACKEND]["resolution"] = "720p"
    assert release_project_model_settings() == {RELEASE_VIDEO_BACKEND: {"resolution": RELEASE_VIDEO_RESOLUTION}}
