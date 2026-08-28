from __future__ import annotations

from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools import ARCREEL_MCP_TOOL_IDS, MIGRATION_BLOCKED_TOOL_IDS
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.reference_video_task_cancellation import (
    cancel_reference_video_tasks_tool,
)

pytestmark = pytest.mark.unit


async def test_cancel_reference_video_tasks_tool_uses_shared_operation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = []

    async def _cancel(pm, project_name, episode, *, unit_id, user_id):
        calls.append((pm, project_name, episode, unit_id, user_id))
        return {"success": True, "episode": episode, "unit_id": unit_id, "affected_count": 2}

    monkeypatch.setattr(
        "server.agent_runtime.sdk_tools.reference_video_task_cancellation.cancel_reference_video_tasks",
        _cancel,
    )
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path), user_id="u1")

    result = await cancel_reference_video_tasks_tool(ctx).handler({"episode": 1, "unit_id": "E1U01"})

    assert result.get("is_error") is not True
    assert result["cancellation"]["affected_count"] == 2
    assert calls == [(ctx.pm, "demo", 1, "E1U01", "u1")]


def test_cancel_reference_video_tasks_tool_is_catalogued_but_not_migration_blocked() -> None:
    assert "cancel_reference_video_tasks" in ARCREEL_MCP_TOOL_IDS
    assert "cancel_reference_video_tasks" not in MIGRATION_BLOCKED_TOOL_IDS
