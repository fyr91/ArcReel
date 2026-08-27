"""SDK MCP tool for generating one course episode's isolated story context."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error


def generate_episode_overview_tool(ctx: ToolContext):
    @tool(
        "generate_episode_overview",
        "仅分析课程项目指定集绑定的 source_file，并保存该集独立 overview；不会读取其他集原文。",
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
