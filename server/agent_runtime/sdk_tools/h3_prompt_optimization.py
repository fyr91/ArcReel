"""Agent adapters for the same MiniMax H3 prompt operation used by the Web UI."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from lib.narration_delivery import video_workflow_uses_narration_delivery
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.h3_prompt_optimization import H3PromptOptimizationService

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode": {"type": "integer", "minimum": 1},
        "unit_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "narration_delivery": {
            "type": "string",
            "enum": ["post_production", "use_tts"],
            "default": "post_production",
        },
        "confirmed_request_durations": {
            "type": "object",
            "additionalProperties": {"type": "integer", "minimum": 1},
        },
    },
    "required": ["episode"],
    "additionalProperties": False,
}

_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "episode": {"type": "integer", "minimum": 1},
        "unit_id": {"type": "string", "minLength": 1},
        "rendered_prompt": {"type": "string", "minLength": 1},
        "narration_delivery": {
            "type": "string",
            "enum": ["post_production", "use_tts"],
            "default": "post_production",
        },
        "confirmed_request_duration_seconds": {"type": "integer", "minimum": 1},
    },
    "required": ["episode", "unit_id", "rendered_prompt"],
    "additionalProperties": False,
}


def _content_mode(ctx: ToolContext) -> str | None:
    try:
        project = ctx.pm.load_project(ctx.project_name)
    except FileNotFoundError:
        return None
    value = project.get("content_mode")
    return value if isinstance(value, str) else None


def _schema_for_context(ctx: ToolContext, schema: dict[str, Any]) -> dict[str, Any]:
    if video_workflow_uses_narration_delivery(_content_mode(ctx)):
        return schema
    properties = dict(schema["properties"])
    properties.pop("narration_delivery", None)
    return {**schema, "properties": properties}


def _args(args: dict[str, Any], *, content_mode: str | None) -> dict[str, Any]:
    episode = args.get("episode")
    if not isinstance(episode, int) or isinstance(episode, bool) or episode < 1:
        raise ValueError("episode must be a positive integer")
    unit_ids = args.get("unit_ids")
    if unit_ids is not None and (
        not isinstance(unit_ids, list) or any(not isinstance(item, str) or not item.strip() for item in unit_ids)
    ):
        raise ValueError("unit_ids must be a list of non-empty strings")
    durations = args.get("confirmed_request_durations") or {}
    if not isinstance(durations, dict):
        raise ValueError("confirmed_request_durations must be an object")
    uses_delivery = video_workflow_uses_narration_delivery(content_mode)
    if not uses_delivery and "narration_delivery" in args:
        raise ValueError(f"{content_mode} H3 视频提示词工作流已移除 narration_delivery 参数")
    return {
        "episode": episode,
        "unit_ids": unit_ids,
        "narration_delivery": (args.get("narration_delivery") or "post_production") if uses_delivery else None,
        "confirmed_request_durations": durations,
    }


def _response(key: str, values: list[Any]) -> dict[str, Any]:
    items = [value.model_dump(mode="json") for value in values]
    for item in items:
        if isinstance(item, dict) and item.get("narration_delivery") is None:
            item.pop("narration_delivery", None)
    payload = {key: items}
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], **payload}


def optimize_h3_video_prompts_tool(ctx: ToolContext):
    @tool(
        "optimize_h3_video_prompts",
        "基于最终 MiniMax H3 请求事实生成六段式视频提示词并保存为待审核；不会提交付费视频任务。",
        _schema_for_context(ctx, _SCHEMA),
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = _args(args, content_mode=_content_mode(ctx))
            values = await H3PromptOptimizationService(ctx.pm).optimize(ctx.project_name, **request)
            return _response("artifacts", values)
        except Exception as exc:  # noqa: BLE001 - MCP adapters return a controlled error envelope
            return tool_error("optimize_h3_video_prompts", exc)

    return _handler


def confirm_h3_video_prompts_tool(ctx: ToolContext):
    @tool(
        "confirm_h3_video_prompts",
        "确认一批已经人工审核且仍有效的 MiniMax H3 六段式视频提示词；不会提交视频任务。",
        _schema_for_context(ctx, _SCHEMA),
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            request = _args(args, content_mode=_content_mode(ctx))
            values = await H3PromptOptimizationService(ctx.pm).confirm(ctx.project_name, **request)
            return _response("artifacts", values)
        except Exception as exc:  # noqa: BLE001 - MCP adapters return a controlled error envelope
            return tool_error("confirm_h3_video_prompts", exc)

    return _handler


def update_h3_video_prompt_tool(ctx: ToolContext):
    @tool(
        "update_h3_video_prompt",
        "按用户要求编辑一个已有且仍有效的 MiniMax H3 六段式视频提示词；保存前会按当前时长和参考素材重新校验，并回到待审核状态。",
        _schema_for_context(ctx, _UPDATE_SCHEMA),
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            episode = args.get("episode")
            unit_id = args.get("unit_id")
            rendered_prompt = args.get("rendered_prompt")
            if not isinstance(episode, int) or isinstance(episode, bool) or episode < 1:
                raise ValueError("episode must be a positive integer")
            if not isinstance(unit_id, str) or not unit_id.strip():
                raise ValueError("unit_id must be a non-empty string")
            if not isinstance(rendered_prompt, str) or not rendered_prompt.strip():
                raise ValueError("rendered_prompt must be a non-empty string")
            duration = args.get("confirmed_request_duration_seconds")
            if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration < 1):
                raise ValueError("confirmed_request_duration_seconds must be a positive integer")
            content_mode = _content_mode(ctx)
            uses_delivery = video_workflow_uses_narration_delivery(content_mode)
            if not uses_delivery and "narration_delivery" in args:
                raise ValueError(f"{content_mode} H3 视频提示词工作流已移除 narration_delivery 参数")
            artifact = await H3PromptOptimizationService(ctx.pm).update_prompt(
                ctx.project_name,
                episode,
                unit_id=unit_id,
                rendered_prompt=rendered_prompt,
                narration_delivery=(args.get("narration_delivery") or "post_production") if uses_delivery else None,
                confirmed_request_duration_seconds=duration,
            )
            return _response("artifacts", [artifact])
        except Exception as exc:  # noqa: BLE001 - MCP adapters return a controlled error envelope
            return tool_error("update_h3_video_prompt", exc)

    return _handler


__all__ = [
    "confirm_h3_video_prompts_tool",
    "optimize_h3_video_prompts_tool",
    "update_h3_video_prompt_tool",
]
