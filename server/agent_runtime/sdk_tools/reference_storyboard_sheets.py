"""Agent tools for sibling Storyboard Sheet and Keyframe production."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from lib.generation_queue_client import batch_enqueue_only
from lib.generation_result import normalize_requested_ids
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error, validate_script_filename
from server.services.image_model_selection import IMAGE_MODEL_TOOL_PROPERTIES, image_override_from_args
from server.services.reference_keyframe_tasks import reference_keyframe_task_specs
from server.services.reference_storyboard_sheet_tasks import reference_storyboard_sheet_task_specs


def _response(payload: object, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]
    }
    if is_error:
        result["is_error"] = True
    return result


def generate_reference_storyboard_sheets_tool(ctx: ToolContext):
    @tool(
        "generate_reference_storyboard_sheets",
        "为 reference_video 剧本生成必须审阅的 Video Unit Storyboard Sheet（每个单元一张多格叙事预览）。"
        "它与 Keyframes 都直接来自正式 Video Unit 文稿，互不作为输入，可以并行生成。"
        "每个 unit 的 storyboard_description 使用与正式文稿相同的 @[角色]/@[场景]/@[道具] 语法；"
        "这不是 generate_storyboards 的逐镜头分镜图。unit_ids 省略时仅补齐尚无 Sheet 的单元。",
        {
            "type": "object",
            "properties": {
                **IMAGE_MODEL_TOOL_PROPERTIES,
                "script": {"type": "string", "description": "剧本文件名，例如 episode_1.json"},
                "unit_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定生成或重生的 Video Unit ID；省略时只补齐缺失项",
                },
                "instructions": {
                    "type": "string",
                    "maxLength": 4000,
                    "description": "可选，本次生成/重生成必须落实的用户审核意见；只影响分镜表达，不得改写脚本事实",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_file = validate_script_filename(args["script"])
            requested = normalize_requested_ids(args.get("unit_ids"), field="unit_ids")
            script = ctx.pm.load_script(ctx.project_name, script_file)
            specs = reference_storyboard_sheet_task_specs(
                script,
                script_file,
                unit_ids=set(requested) if requested is not None else None,
                missing_only=requested is None,
                image_override=image_override_from_args(args),
                instructions=args.get("instructions"),
            )
            enqueued, failures = await batch_enqueue_only(
                project_name=ctx.project_name,
                specs=specs,
                user_id=ctx.user_id,
            )
            return _response(
                {
                    "requested": requested,
                    "tasks": [
                        {"unit_id": item.resource_id, "task_id": item.task_id, "deduped": item.deduped}
                        for item in enqueued
                    ],
                    "failures": [item.model_dump(mode="json") for item in failures],
                    "next_step": "可同时调用 generate_reference_keyframes；两者完成后分别审核，互不等待。",
                },
                is_error=bool(failures),
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_reference_storyboard_sheets", exc)

    return _handler


def generate_reference_keyframes_tool(ctx: ToolContext):
    @tool(
        "generate_reference_keyframes",
        "为 reference_video 正式文稿已提取的 Keyframes 生成或重试关键首帧。"
        "它与 Video Unit Storyboard Sheet 同级、互不作为输入，可以并行生成；"
        "每条 Keyframe description 使用与正式文稿相同的 @[角色]/@[场景]/@[道具] 语法；"
        "keyframe_ids 省略时只补齐尚无图片的关键帧。",
        {
            "type": "object",
            "properties": {
                **IMAGE_MODEL_TOOL_PROPERTIES,
                "script": {"type": "string", "description": "剧本文件名，例如 episode_1.json"},
                "keyframe_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "指定生成或重生的关键帧 ID；省略时只补齐缺失项",
                },
            },
            "required": ["script"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            script_file = validate_script_filename(args["script"])
            requested = normalize_requested_ids(args.get("keyframe_ids"), field="keyframe_ids")
            script = ctx.pm.load_script(ctx.project_name, script_file)
            specs = reference_keyframe_task_specs(
                script,
                script_file,
                keyframe_ids=set(requested) if requested is not None else None,
                missing_only=requested is None,
                image_override=image_override_from_args(args),
            )
            enqueued, failures = await batch_enqueue_only(
                project_name=ctx.project_name,
                specs=specs,
                user_id=ctx.user_id,
            )
            return _response(
                {
                    "requested": requested,
                    "tasks": [
                        {"keyframe_id": item.resource_id, "task_id": item.task_id, "deduped": item.deduped}
                        for item in enqueued
                    ],
                    "failures": [item.model_dump(mode="json") for item in failures],
                },
                is_error=bool(failures),
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_reference_keyframes", exc)

    return _handler


__all__ = [
    "generate_reference_keyframes_tool",
    "generate_reference_storyboard_sheets_tool",
]
