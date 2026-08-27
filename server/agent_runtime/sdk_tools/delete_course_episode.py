"""SDK MCP adapter for two-phase course episode deletion."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from claude_agent_sdk import tool

from lib.project_change_hints import project_change_source
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.course_episode_deletion import CourseEpisodeDeletionService


def delete_course_episode_tool(ctx: ToolContext):
    @tool(
        "delete_course_episode",
        "删除当前课程项目中的一个分集及其源文、草稿、剧本和集级生成产物；不会删除项目资源库、"
        "全局资源库、其他分集、任务历史或费用历史。必须分两次调用：第一次只传 episode 获取影响范围"
        "和 confirmation_token，把影响范围展示给用户并等待用户明确确认；只有用户确认后才能第二次带"
        "原 token 调用。严禁自行确认或在同一轮连续调用两次。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "confirmation_token": {
                    "type": "string",
                    "description": "第一次预览返回的短时确认凭据；仅在用户已明确确认后传入",
                },
            },
            "required": ["episode"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        if type(episode) is not int or episode < 1:
            return tool_error("delete_course_episode", ValueError("episode 必须是正整数"))
        service = CourseEpisodeDeletionService(ctx.pm)
        token = args.get("confirmation_token")
        try:
            if token is None:
                preview = await asyncio.to_thread(service.preview, ctx.project_name, episode)
                payload = preview.to_dict()
                payload.update(
                    {
                        "requires_confirmation": True,
                        "message": (
                            "尚未删除任何内容。请向用户说明：本操作会永久删除该集源文、草稿、剧本及"
                            "集级生成产物，但保留项目/全局资源库、其他分集、任务与费用历史。"
                            "等待用户明确确认后，再原样传回 confirmation_token。"
                        ),
                    }
                )
                return {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "preview": payload,
                }
            if not isinstance(token, str) or not token:
                return tool_error("delete_course_episode", ValueError("confirmation_token 必须是非空字符串"))
            with project_change_source("agent"):
                result = await service.delete_async(ctx.project_name, episode, token)
            payload = result.to_dict()
            payload["message"] = f"已删除课程第 {episode} 集；资源库、其他分集及历史记录均已保留。"
            return {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                "result": payload,
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("delete_course_episode", exc)

    return _handler


__all__ = ["delete_course_episode_tool"]
