"""Agent boundary for exact atomic reference-manuscript replacements."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.agent_runtime.sdk_tools.patch_script import tool_edit_result
from server.services.reference_script_text_replacements import replace_reference_script_text

_REPLACEMENT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "minItems": 1,
    "maxItems": 64,
    "items": {
        "type": "object",
        "properties": {
            "unit_id": {"type": "string"},
            "field": {"enum": ["text", "storyboard_description", "keyframe_description"]},
            "keyframe_id": {"type": "string"},
            "old": {"type": "string", "minLength": 1},
            "new": {"type": "string"},
        },
        "required": ["unit_id", "field", "old", "new"],
        "additionalProperties": False,
    },
}


def replace_reference_script_text_tool(ctx: ToolContext):
    @tool(
        "replace_reference_script_text",
        "按 revision 对正式 reference_video 文稿做一次原子精确替换。"
        "支持 unit text、Storyboard description 与 Keyframe description；每个 old 必须在目标中恰好出现一次。"
        "服务端组装完整字段后委托 patch_episode_script 同一事务编辑核心统一校验，"
        "适合集中审核时避免回传整段长文；不是模糊改写工具。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "expected_revision": {
                    "type": "string",
                    "pattern": "^sha256-v1:[0-9a-f]{64}$",
                },
                "replacements": _REPLACEMENT_SCHEMA,
            },
            "required": ["episode", "expected_revision", "replacements"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = replace_reference_script_text(
                ctx.pm,
                ctx.project_name,
                args["episode"],
                args["expected_revision"],
                args["replacements"],
            )
            return tool_edit_result("replace_reference_script_text", result)
        except Exception as exc:  # noqa: BLE001
            return tool_error("replace_reference_script_text", exc)

    return _handler


__all__ = ["replace_reference_script_text_tool"]
