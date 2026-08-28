from __future__ import annotations

from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools import ARCREEL_MCP_TOOL_IDS, MIGRATION_BLOCKED_TOOL_IDS
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.reference_video_review import confirm_reference_video_tool

pytestmark = pytest.mark.unit


async def test_confirm_reference_video_tool_uses_shared_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = []

    async def _confirm(pm, project_name, episode, unit_id):
        calls.append((pm, project_name, episode, unit_id))
        return {"success": True, "unit_id": unit_id, "confirmed_video_version": 3}

    monkeypatch.setattr(
        "server.agent_runtime.sdk_tools.reference_video_review.confirm_reference_video",
        _confirm,
    )
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path))

    result = await confirm_reference_video_tool(ctx).handler({"episode": 1, "unit_id": "E1U01"})

    assert result.get("is_error") is not True
    assert result["confirmation"]["confirmed_video_version"] == 3
    assert calls == [(ctx.pm, "demo", 1, "E1U01")]


def test_confirm_reference_video_tool_is_catalogued_and_migration_guarded() -> None:
    assert "confirm_reference_video" in ARCREEL_MCP_TOOL_IDS
    assert "confirm_reference_video" in MIGRATION_BLOCKED_TOOL_IDS
