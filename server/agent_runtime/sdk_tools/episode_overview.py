"""SDK MCP tool for generating one course episode's isolated story context."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.episode_overview_review import confirm_episode_overview


def generate_episode_overview_tool(ctx: ToolContext):
    @tool(
        "generate_episode_overview",
        "仅分析课程项目指定集绑定的 source_file，并保存该集独立 overview 待复核草稿；"
        "不会读取其他集原文。第 1 集首次解析会在项目尚无配置时一并创建统一视频风格，"
        "后续集只复用现有风格、不重新分析；用户确认概述后再调用 confirm_episode_overview。",
        {
            "type": "object",
            "properties": {"episode": {"type": "integer", "minimum": 1}},
            "required": ["episode"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            episode = args.get("episode")
            if type(episode) is not int or episode < 1:
                raise ValueError("episode must be a positive integer")
            overview = await ctx.pm.generate_episode_overview(ctx.project_name, episode)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"success": True, "overview": overview},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                ]
            }
        except Exception as exc:
            return tool_error("generate_episode_overview", exc)

    return _handler


def confirm_episode_overview_tool(ctx: ToolContext):
    @tool(
        "confirm_episode_overview",
        "保存用户复核后的课程单集概述并标记完成。必须使用 generate_episode_overview 返回的 "
        "source_revision；源文或解析结果变化时整笔拒绝。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "overview": {
                    "type": "object",
                    "properties": {
                        "synopsis": {"type": "string"},
                        "genre": {"type": "string"},
                        "theme": {"type": "string"},
                        "world_setting": {"type": "string"},
                    },
                    "required": ["synopsis", "genre", "theme", "world_setting"],
                    "additionalProperties": False,
                },
                "expected_source_revision": {"type": "string"},
            },
            "required": ["episode", "overview", "expected_source_revision"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = confirm_episode_overview(
                ctx.pm,
                ctx.project_name,
                args["episode"],
                args["overview"],
                expected_source_revision=args["expected_source_revision"],
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"success": True, **result}, ensure_ascii=False, sort_keys=True),
                    }
                ]
            }
        except Exception as exc:
            return tool_error("confirm_episode_overview", exc)

    return _handler
