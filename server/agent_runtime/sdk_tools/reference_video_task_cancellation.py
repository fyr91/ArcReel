"""SDK MCP boundary for cancelling reference-video tasks."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.reference_video_task_cancellation import cancel_reference_video_tasks


def cancel_reference_video_tasks_tool(ctx: ToolContext):
    @tool(
        "cancel_reference_video_tasks",
        "取消当前项目一集内的视频生成/提示词优化/高清任务；传 unit_id 取消单元，不传则取消整集。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "unit_id": {"type": "string", "minLength": 1},
            },
            "required": ["episode"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        unit_id = args.get("unit_id")
        if type(episode) is not int or episode <= 0:
            return tool_error("cancel_reference_video_tasks", ValueError("episode 必须是正整数"))
        if unit_id is not None and (not isinstance(unit_id, str) or not unit_id.strip()):
            return tool_error("cancel_reference_video_tasks", ValueError("unit_id 必须是非空文本"))
        try:
            result = await cancel_reference_video_tasks(
                ctx.pm,
                ctx.project_name,
                episode,
                unit_id=unit_id.strip() if isinstance(unit_id, str) else None,
                user_id=ctx.user_id,
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("cancel_reference_video_tasks", exc)
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "cancellation": result,
        }

    return _handler


__all__ = ["cancel_reference_video_tasks_tool"]
