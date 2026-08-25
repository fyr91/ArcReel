"""Agent boundary for the shared Keyframe mention normalization operation."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.reference_keyframe_mentions import normalize_episode_keyframe_mentions


def normalize_reference_keyframe_mentions_tool(ctx: ToolContext):
    @tool(
        "normalize_reference_keyframe_mentions",
        "批量把本集全部 Keyframe description 中已登记资产的字面名称规范为 @[名称]。"
        "Web API 与 Agent 共用同一业务操作；只补引用语法，不猜别名、不改画面语义。",
        {
            "type": "object",
            "properties": {"episode": {"type": "integer", "minimum": 1}},
            "required": ["episode"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = normalize_episode_keyframe_mentions(
                ctx.pm,
                ctx.project_name,
                args["episode"],
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, sort_keys=True),
                    }
                ]
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("normalize_reference_keyframe_mentions", exc)

    return _handler


__all__ = ["normalize_reference_keyframe_mentions_tool"]
