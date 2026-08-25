import json
from pathlib import Path

import pytest

from lib.db.repositories.asset_repo import AssetRepository
from lib.project_manager import ProjectManager
from lib.reference_video.request_projection import resolve_reference_assets
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.project_asset_links import manage_project_asset_link_tool
from server.services.project_asset_links import backfill_linked_character_sheets

pytestmark = pytest.mark.integration


async def test_backfill_materializes_only_empty_linked_main_sheets(tmp_path: Path, db_factory) -> None:
    projects_root = tmp_path / "projects"
    pm = ProjectManager(projects_root)
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo")
    for name in ("鳄鱼爸爸", "鳄鱼妹妹"):
        pm.add_project_character("demo", name, "项目角色", "")
    global_image = projects_root / "_global_assets" / "character" / "dad.png"
    global_image.parent.mkdir(parents=True)
    global_image.write_bytes(b"global-dad")
    async with db_factory() as session:
        asset = await AssetRepository(session).create(
            type="character",
            name="鳄鱼爸爸",
            image_path="_global_assets/character/dad.png",
        )
        await session.commit()
        asset_id = asset.id
    for name in ("鳄鱼爸爸", "鳄鱼妹妹"):
        pm.update_asset_entry(
            "character",
            "demo",
            name,
            lambda entry: entry.update(
                global_asset_id=asset_id,
                matched_global_asset_id=asset_id,
                global_asset_image_usage="main",
            ),
        )
    sister_sheet = pm.get_project_path("demo") / "characters" / "鳄鱼妹妹.png"
    sister_sheet.write_bytes(b"project-sister")
    pm.update_project_character_sheet("demo", "鳄鱼妹妹", "characters/鳄鱼妹妹.png")

    first = await backfill_linked_character_sheets(manager=pm, session_factory=db_factory)
    second = await backfill_linked_character_sheets(manager=pm, session_factory=db_factory)

    assert first.materialized == 1
    assert first.skipped == 0
    assert second.materialized == 0
    characters = pm.load_project("demo")["characters"]
    assert (pm.get_project_path("demo") / characters["鳄鱼爸爸"]["character_sheet"]).read_bytes() == b"global-dad"
    assert (pm.get_project_path("demo") / characters["鳄鱼妹妹"]["character_sheet"]).read_bytes() == b"project-sister"


async def test_agent_can_link_configure_and_unlink_project_asset(
    tmp_path: Path, db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    pm = ProjectManager(str(projects_root))
    pm.create_project("demo")
    pm.create_project_metadata("demo", "Demo")
    pm.add_project_character("demo", "鳄鱼爸爸", "项目角色", "沉稳")
    global_image = projects_root / "_global_assets" / "character" / "dad.png"
    global_image.parent.mkdir(parents=True)
    global_image.write_bytes(b"global-dad")
    async with db_factory() as session:
        asset = await AssetRepository(session).create(
            type="character",
            name="鳄鱼爸爸",
            image_path="_global_assets/character/dad.png",
            audio_path="_global_assets/character/dad.wav",
            voice_id="dad-tts",
        )
        await session.commit()
        asset_id = asset.id
    monkeypatch.setattr("server.services.project_asset_links.async_session_factory", db_factory)
    tool = manage_project_asset_link_tool(ToolContext(project_name="demo", projects_root=projects_root, pm=pm))

    linked = await tool.handler(
        {"action": "link", "resource_type": "character", "resource_id": "鳄鱼爸爸", "asset_id": asset_id}
    )
    assert "is_error" not in linked
    linked_character = pm.load_project("demo")["characters"]["鳄鱼爸爸"]
    assert linked_character["global_asset_voice_source"] == "reference_audio"
    assert linked_character["character_sheet"] == "characters/鳄鱼爸爸.png"
    assert (pm.get_project_path("demo") / linked_character["character_sheet"]).read_bytes() == b"global-dad"
    references = resolve_reference_assets(
        pm.load_project("demo"),
        pm.get_project_path("demo"),
        {"text": "@[鳄鱼爸爸] 出场"},
    )
    assert [reference.path for reference in references] == [pm.get_project_path("demo") / "characters" / "鳄鱼爸爸.png"]

    configured = await tool.handler(
        {
            "action": "configure",
            "resource_type": "character",
            "resource_id": "鳄鱼爸爸",
            "voice_source": "voice_id",
        }
    )
    assert "is_error" not in configured
    entry = json.loads(configured["content"][0]["text"])["project_asset"]
    assert entry["global_asset_image_usage"] == "main"
    assert entry["global_asset_voice_source"] == "voice_id"

    unlinked = await tool.handler({"action": "unlink", "resource_type": "character", "resource_id": "鳄鱼爸爸"})
    assert "is_error" not in unlinked
    unlinked_character = pm.load_project("demo")["characters"]["鳄鱼爸爸"]
    assert "global_asset_id" not in unlinked_character
    assert (pm.get_project_path("demo") / unlinked_character["character_sheet"]).read_bytes() == b"global-dad"
