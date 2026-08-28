"""SDK MCP boundary for confirming generated reference videos."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.reference_video_review import confirm_reference_video


def confirm_reference_video_tool(ctx: ToolContext):
    @tool(
        "confirm_reference_video",
        "确认当前项目指定视频单元的当前成片版本；仅在用户明确认可该视频后调用。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "unit_id": {"type": "string", "minLength": 1},
            },
            "required": ["episode", "unit_id"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        unit_id = args.get("unit_id")
        if type(episode) is not int or episode <= 0:
            return tool_error("confirm_reference_video", ValueError("episode 必须是正整数"))
        if not isinstance(unit_id, str) or not unit_id.strip():
            return tool_error("confirm_reference_video", ValueError("unit_id 必须是非空文本"))
        try:
            result = await confirm_reference_video(
                ctx.pm,
                ctx.project_name,
                episode,
                unit_id.strip(),
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("confirm_reference_video", exc)
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "confirmation": result,
        }

    return _handler


__all__ = ["confirm_reference_video_tool"]
