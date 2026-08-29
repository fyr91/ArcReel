"""Administrator tools for inspecting and cleaning the central company catalog."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from claude_agent_sdk import tool

from lib.company_assets import delete_company_catalog_asset, list_company_catalog_assets
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error
from server.services.company_asset_supabase import get_company_asset_catalog


def list_company_catalog_assets_tool(ctx: ToolContext):
    @tool(
        "list_company_catalog_assets",
        "查询服务器 Supabase 公司资产总库中的人物、场景和道具。可按类型、来源和名称筛选。",
        {
            "type": "object",
            "properties": {
                "asset_type": {"type": "string", "enum": ["character", "scene", "prop"]},
                "origin": {"type": "string", "enum": ["official", "user_shared"]},
                "query": {"type": "string", "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 24},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            page = await list_company_catalog_assets(
                administrator=get_company_asset_catalog(),
                user_id=ctx.user_id,
                asset_type=args.get("asset_type"),
                origin=args.get("origin"),
                query=args.get("query"),
                limit=int(args.get("limit", 24)),
                offset=int(args.get("offset", 0)),
            )
            payload = {
                "items": [asdict(item) for item in page.items],
                "total": page.total,
                "totals": page.totals,
            }
            return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("list_company_catalog_assets", exc)

    return _handler


def delete_company_catalog_asset_tool(ctx: ToolContext):
    @tool(
        "delete_company_catalog_asset",
        "永久删除服务器 Supabase 公司资产总库中的一个资产及其云端图片、音频。"
        "仅在用户明确要求删除且已先查询核对资产 ID 后调用；ArcReel 本地副本不会被删除。",
        {
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "list_company_catalog_assets 返回的资产 UUID",
                }
            },
            "required": ["asset_id"],
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await delete_company_catalog_asset(
                administrator=get_company_asset_catalog(),
                user_id=ctx.user_id,
                asset_id=str(args["asset_id"]),
            )
            return {"content": [{"type": "text", "text": json.dumps(asdict(result), ensure_ascii=False)}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("delete_company_catalog_asset", exc)

    return _handler


__all__ = ["delete_company_catalog_asset_tool", "list_company_catalog_assets_tool"]
