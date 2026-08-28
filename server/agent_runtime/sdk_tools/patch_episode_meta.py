"""SDK MCP tool for editing formal-script episode metadata."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.episode_metadata import EDITABLE_EPISODE_METADATA_FIELDS, update_episode_metadata


def patch_episode_meta_tool(ctx: ToolContext):
    @tool(
        "patch_episode_meta",
        "批量编辑分集元数据，与 Web API 共用同一业务操作；正式文稿存在时原子镜像到 episodes[]，"
        "课程分集尚无正式文稿时也可单独修改 title。"
        f"updates 白名单字段 {list(EDITABLE_EPISODE_METADATA_FIELDS)}：title 为非空字符串；hook 为字符串或 null；"
        "narrator_character 为已登记角色名，null 表示清除本集覆盖并继承项目默认；"
        "outline 为 {story_beats: string[], next_episode_teaser: string} 或 null。一次调用可同时修改多个字段；"
        "分镜内部字段仍使用 patch_episode_script。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1, "description": "分集编号"},
                "updates": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "非空分集标题"},
                        "hook": {"type": ["string", "null"], "description": "本集结尾钩子；null 表示清除"},
                        "narrator_character": {
                            "type": ["string", "null"],
                            "description": "本集默认旁白角色；null 表示继承项目默认",
                        },
                        "outline": {
                            "type": ["object", "null"],
                            "description": "本集导览；null 表示清除",
                            "properties": {
                                "story_beats": {"type": "array", "items": {"type": "string"}},
                                "next_episode_teaser": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                    "minProperties": 1,
                },
            },
            "required": ["episode", "updates"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            updated = update_episode_metadata(
                ctx.pm,
                ctx.project_name,
                args["episode"],
                args["updates"],
            )
            fields = ", ".join(field for field in EDITABLE_EPISODE_METADATA_FIELDS if field in updated)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"✅ 已批量更新第 {updated['episode']} 集元数据：{fields}",
                    }
                ]
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("patch_episode_meta", exc)

    return _handler


__all__ = ["patch_episode_meta_tool"]
