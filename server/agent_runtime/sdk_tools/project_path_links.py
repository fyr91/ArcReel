"""Agent adapter for validated project-local file and directory links."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.project_path_links import (
    InvalidProjectPathError,
    ProjectPathLinkService,
    ProjectPathNotFoundError,
)


def _error(code: str, relative_path: object) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"error": code, "relative_path": str(relative_path)},
                    ensure_ascii=False,
                ),
            }
        ],
        "is_error": True,
    }


def _markdown_label(value: object, fallback: str) -> str:
    label = " ".join(str(value or fallback).split())
    return label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def get_project_path_link_tool(ctx: ToolContext):
    @tool(
        "get_project_path_link",
        "为当前项目内已存在的文件或文件夹生成可点击的本地定位链接。用户要求定位、打开或发出文件位置时使用；path 必须是项目相对路径。",
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对当前项目根的路径；项目根使用 .",
                    "default": ".",
                },
                "label": {
                    "type": "string",
                    "description": "链接显示文字，应使用用户当前语言",
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        relative_path = args.get("path", ".")
        try:
            location = ProjectPathLinkService(ctx.pm).resolve(ctx.project_name, relative_path)
        except InvalidProjectPathError:
            return _error("invalid_project_path", relative_path)
        except (FileNotFoundError, ProjectPathNotFoundError):
            return _error("project_path_not_found", relative_path)
        except Exception as exc:  # noqa: BLE001
            return tool_error("get_project_path_link", exc)

        fallback = "项目文件夹" if location.relative_path == "." else location.relative_path
        label = _markdown_label(args.get("label"), fallback)
        payload = {
            "relative_path": location.relative_path,
            "kind": location.kind,
            "href": location.href,
            "markdown_link": f"[{label}]({location.href})",
        }
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}

    return _handler


__all__ = ["get_project_path_link_tool"]
