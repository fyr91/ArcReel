from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.episode_overview import generate_episode_overview_tool
from server.routers import projects

pytestmark = pytest.mark.unit


class _OverviewOperationProbe:
    def __init__(self, root: Path) -> None:
        self.projects_root = root
        self.saved: dict[tuple[str, int], dict[str, str]] = {}

    def get_project_path(self, project_name: str) -> Path:
        path = self.projects_root / project_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def generate_episode_overview(self, project_name: str, episode: int) -> dict[str, str]:
        result = {
            "synopsis": f"episode-{episode}",
            "source_revision": "sha256-v1:" + "a" * 64,
        }
        self.saved[(project_name, episode)] = result
        return result


@pytest.mark.asyncio
async def test_web_and_agent_episode_overview_share_the_same_operation_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_probe = _OverviewOperationProbe(tmp_path / "web")
    monkeypatch.setattr(projects, "get_project_manager", lambda: web_probe)
    web_result = await projects.generate_episode_overview("demo", 2, lambda key, **_kwargs: key)

    agent_probe = _OverviewOperationProbe(tmp_path / "agent")
    ctx = ToolContext(
        project_name="demo",
        projects_root=agent_probe.projects_root,
        pm=agent_probe,  # type: ignore[arg-type]
    )
    agent_result = await generate_episode_overview_tool(ctx).handler({"episode": 2})
    agent_payload = json.loads(agent_result["content"][0]["text"])

    assert web_result["overview"] == agent_payload["overview"]
    assert web_probe.saved == agent_probe.saved
