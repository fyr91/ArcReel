from __future__ import annotations

import pytest

from server.agent_runtime.model_capabilities import is_image_path, supports_agent_image_input

pytestmark = pytest.mark.unit


def test_observed_deepseek_agent_family_is_text_only() -> None:
    assert not supports_agent_image_input("deepseek-v4-pro-ga-260813")


def test_unknown_custom_model_remains_image_enabled() -> None:
    assert supports_agent_image_input("custom-multimodal-model")


@pytest.mark.parametrize("path", ["frame.PNG", "/tmp/photo.jpeg", "asset.webp"])
def test_image_path_extensions_are_case_insensitive(path: str) -> None:
    assert is_image_path(path)


def test_non_image_path_is_not_blocked() -> None:
    assert not is_image_path("episode_1.json")
