from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.project_path_links import get_project_path_link_tool

pytestmark = pytest.mark.unit


@pytest.fixture
def tool(tmp_path: Path):
    projects_root = tmp_path / "projects"
    manager = ProjectManager(projects_root)
    project_dir = manager.create_project("demo")
    (project_dir / "videos" / "clip.mp4").write_bytes(b"video")
    context = ToolContext(project_name="demo", projects_root=projects_root, pm=manager)
    return get_project_path_link_tool(context)


async def test_tool_returns_validated_markdown_link(tool) -> None:
    result = await tool.handler({"path": "videos/clip.mp4", "label": "视频片段"})

    assert "is_error" not in result
    payload = json.loads(result["content"][0]["text"])
    assert payload == {
        "relative_path": "videos/clip.mp4",
        "kind": "file",
        "href": "/__arcreel_open_project_path__?path=videos%2Fclip.mp4",
        "markdown_link": "[视频片段](/__arcreel_open_project_path__?path=videos%2Fclip.mp4)",
    }


async def test_tool_rejects_missing_or_escaping_path(tool) -> None:
    missing = await tool.handler({"path": "videos/missing.mp4"})
    escaping = await tool.handler({"path": "../other-project"})

    assert missing["is_error"] is True
    assert json.loads(missing["content"][0]["text"])["error"] == "project_path_not_found"
    assert escaping["is_error"] is True
    assert json.loads(escaping["content"][0]["text"])["error"] == "invalid_project_path"
