from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROFILE = REPO / "agent_runtime_profile"
pytestmark = pytest.mark.unit


def test_video_unit_auto_edit_routes_to_hyperframes_not_compose() -> None:
    compose = (PROFILE / ".claude/skills/compose-video/SKILL.md").read_text(encoding="utf-8")
    hyperframes = (PROFILE / ".claude/skills/hyperframes-auto-edit/SKILL.md").read_text(encoding="utf-8")

    assert "自动剪辑" in hyperframes
    assert "Video Unit" in hyperframes
    assert "必须改用 hyperframes-auto-edit" in compose
    assert "禁止绕过脚本后用裸 `ffmpeg concat`" in compose
