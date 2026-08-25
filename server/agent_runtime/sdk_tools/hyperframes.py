"""SDK MCP adapter for project-local HyperFrames workspaces."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import tool

from lib.narration_delivery import POST_PRODUCTION, USE_TTS
from lib.path_safety import safe_join
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.hyperframes_music import MAX_MUSIC_DIRECTION_LENGTH
from server.services.hyperframes_music_tasks import enqueue_hyperframes_bgm_task
from server.services.hyperframes_workspace import HyperframesWorkspaceService


def prepare_hyperframes_episode_tool(ctx: ToolContext):
    @tool(
        "prepare_hyperframes_episode",
        "把当前项目一集已生成的视频物化为项目内 HyperFrames 工程；返回允许编辑的唯一工作区路径。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "narration_delivery": {
                    "type": "string",
                    "enum": [POST_PRODUCTION, USE_TTS],
                    "default": POST_PRODUCTION,
                },
            },
            "required": ["episode"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        variant = args.get("narration_delivery", POST_PRODUCTION)
        if type(episode) is not int or episode <= 0:
            return tool_error("prepare_hyperframes_episode", ValueError("episode 必须是正整数"))
        if variant not in {POST_PRODUCTION, USE_TTS}:
            return tool_error(
                "prepare_hyperframes_episode",
                ValueError("narration_delivery 必须是 post_production 或 use_tts"),
            )
        try:
            workspace = await HyperframesWorkspaceService(ctx.pm).prepare(
                ctx.project_name,
                episode,
                variant=variant,
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("prepare_hyperframes_episode", exc)

        payload = {
            **workspace.to_dict(),
            "editable_root": str(workspace.path),
            "entry_file": str(workspace.path / "index.html"),
            "editing_plan_file": str(workspace.path / "EDITING_PLAN.md"),
            "write_boundary": str(workspace.path),
            "assembly_contract": {
                "baseline_only": workspace.editing_analysis is None
                or workspace.editing_analysis.state == "assembly_draft",
                "message": (
                    "prepare_hyperframes_episode 只物化顺序拼接底稿，不等于 AI 剪辑完成。"
                    "除非用户明确要求原样拼接，否则必须分析媒体并在 index.html 落实可核验的画面剪辑。"
                ),
            },
        }
        try:
            manifest = json.loads((workspace.path / "manifest.json").read_text(encoding="utf-8"))
            script_file = manifest.get("script_file")
            if isinstance(script_file, str) and script_file:
                payload["source_script"] = str(safe_join(ctx.project_path, script_file, require_file=True))
        except (OSError, ValueError, TypeError):
            pass
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "workspace": payload,
        }

    return _handler


def inspect_hyperframes_episode_tool(ctx: ToolContext):
    @tool(
        "inspect_hyperframes_episode",
        "检查 HyperFrames 工程是顺序拼接底稿还是已有可核验的画面剪辑，并返回结构化剪辑证据。",
        {
            "type": "object",
            "properties": {"episode": {"type": "integer", "minimum": 1}},
            "required": ["episode"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        if type(episode) is not int or episode <= 0:
            return tool_error("inspect_hyperframes_episode", ValueError("episode 必须是正整数"))
        try:
            workspace = HyperframesWorkspaceService(ctx.pm).status(ctx.project_name, episode)
        except Exception as exc:  # noqa: BLE001
            return tool_error("inspect_hyperframes_episode", exc)
        if workspace is None:
            return tool_error("inspect_hyperframes_episode", ValueError("HyperFrames 工程不存在"))
        payload = workspace.to_dict()
        payload["message"] = (
            "AI 画面剪辑已检测到。"
            if payload["editing_state"] == "edited"
            else "当前仍是顺序拼接底稿；删除字幕、增加音乐或改写计划不算画面剪辑。"
        )
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "inspection": payload,
        }

    return _handler


def generate_hyperframes_bgm_tool(ctx: ToolContext):
    @tool(
        "generate_hyperframes_bgm",
        "异步提交 ArcReel MiniMax Music 3 连续纯器乐背景音乐任务；立即返回 task_id，完成后自动写入该集 HyperFrames 工程。",
        {
            "type": "object",
            "properties": {
                "episode": {"type": "integer", "minimum": 1},
                "direction": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_MUSIC_DIRECTION_LENGTH,
                    "description": "根据剧本情绪弧线总结的曲风、节奏、乐器与编排方向；不要写歌词。",
                },
                "seed": {"type": "integer", "minimum": 0},
            },
            "required": ["episode", "direction"],
            "additionalProperties": False,
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        episode = args.get("episode")
        direction = args.get("direction")
        seed = args.get("seed")
        if type(episode) is not int or episode <= 0:
            return tool_error("generate_hyperframes_bgm", ValueError("episode 必须是正整数"))
        if not isinstance(direction, str) or not direction.strip():
            return tool_error("generate_hyperframes_bgm", ValueError("direction 必须是非空文本"))
        if len(direction) > MAX_MUSIC_DIRECTION_LENGTH:
            return tool_error(
                "generate_hyperframes_bgm",
                ValueError(f"direction 上限为 {MAX_MUSIC_DIRECTION_LENGTH} 字符"),
            )
        if seed is not None and (type(seed) is not int or seed < 0):
            return tool_error("generate_hyperframes_bgm", ValueError("seed 必须是非负整数"))
        try:
            task = await enqueue_hyperframes_bgm_task(
                ctx.pm,
                ctx.project_name,
                episode,
                direction=direction,
                seed=seed,
                source="agent",
            )
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_hyperframes_bgm", exc)
        payload = {
            "task_id": task["task_id"],
            "status": task["status"],
            "deduped": bool(task.get("deduped", False)),
            "episode": episode,
            "resource_id": task["resource_id"],
            "message": "背景音乐任务已异步提交；无需等待。任务完成后会自动加入 HyperFrames 时间线。",
        }
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
            "task": payload,
        }

    return _handler


__all__ = [
    "generate_hyperframes_bgm_tool",
    "inspect_hyperframes_episode_tool",
    "prepare_hyperframes_episode_tool",
]
