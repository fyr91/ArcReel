"""Claude SDK tool boundary for HyperFrames authoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext
from server.agent_runtime.sdk_tools.hyperframes import (
    generate_hyperframes_bgm_tool,
    inspect_hyperframes_episode_tool,
    prepare_hyperframes_episode_tool,
)
from server.services.hyperframes_editing import HyperframesEditingAnalysis
from server.services.hyperframes_workspace import HyperframesWorkspace

pytestmark = pytest.mark.unit


class _Service:
    def __init__(self, _pm: ProjectManager, workspace: HyperframesWorkspace) -> None:
        self.workspace = workspace
        self.calls: list[tuple[str, int, str]] = []

    async def prepare(self, project_name: str, episode: int, *, variant: str):
        self.calls.append((project_name, episode, variant))
        return self.workspace


async def test_tool_returns_one_explicit_project_local_write_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "demo" / "hyperframes" / "episode_01"
    workspace = HyperframesWorkspace(
        project_name="demo",
        episode=1,
        path=workspace_path,
        relative_path="hyperframes/episode_01",
        composition_path="hyperframes/episode_01/index.html",
        manifest_path="hyperframes/episode_01/manifest.json",
    )
    service = _Service(ProjectManager(tmp_path), workspace)
    monkeypatch.setattr(
        "server.agent_runtime.sdk_tools.hyperframes.HyperframesWorkspaceService",
        lambda _pm: service,
    )
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path))

    result = await prepare_hyperframes_episode_tool(ctx).handler(
        {"episode": 1, "narration_delivery": "post_production"}
    )

    assert result.get("is_error") is not True
    assert result["workspace"]["write_boundary"] == str(workspace_path)
    assert result["workspace"]["entry_file"] == str(workspace_path / "index.html")
    assert result["workspace"]["assembly_contract"]["baseline_only"] is True
    assert service.calls == [("demo", 1, "post_production")]


async def test_inspection_tool_reports_structural_edit_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_path = tmp_path / "demo" / "hyperframes" / "episode_01"
    analysis = HyperframesEditingAnalysis(
        state="edited",
        picture_edit_count=3,
        source_unit_count=2,
        video_clip_count=2,
        timing_changes=2,
        split_ranges=0,
        reordered_units=0,
        overlapping_handoffs=1,
        retimed_clips=0,
        visual_treatments=0,
        audio_automations=2,
    )
    workspace = HyperframesWorkspace(
        project_name="demo",
        episode=1,
        path=workspace_path,
        relative_path="hyperframes/episode_01",
        composition_path="hyperframes/episode_01/index.html",
        manifest_path="hyperframes/episode_01/manifest.json",
        editing_analysis=analysis,
    )
    monkeypatch.setattr(
        "server.agent_runtime.sdk_tools.hyperframes.HyperframesWorkspaceService",
        lambda _pm: type("Service", (), {"status": lambda self, _project, _episode: workspace})(),
    )
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path))

    result = await inspect_hyperframes_episode_tool(ctx).handler({"episode": 1})

    assert result["inspection"]["editing_state"] == "edited"
    assert result["inspection"]["editing_analysis"]["picture_edit_count"] == 3


async def test_tool_rejects_invalid_episode_before_touching_workspace(tmp_path: Path) -> None:
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path))

    result = await prepare_hyperframes_episode_tool(ctx).handler({"episode": 0})

    assert result["is_error"] is True
    assert "正整数" in result["content"][0]["text"]


async def test_music_tool_enqueues_and_returns_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls = []

    async def _enqueue(pm, project_name, episode, *, direction, seed, source):
        calls.append((pm, project_name, episode, direction, seed, source))
        return {
            "task_id": "task-bgm",
            "status": "queued",
            "resource_id": "episode_01",
            "deduped": False,
        }

    monkeypatch.setattr(
        "server.agent_runtime.sdk_tools.hyperframes.enqueue_hyperframes_bgm_task",
        _enqueue,
    )
    ctx = ToolContext("demo", tmp_path, pm=ProjectManager(tmp_path))

    result = await generate_hyperframes_bgm_tool(ctx).handler(
        {"episode": 1, "direction": "calm instrumental", "seed": 7}
    )

    assert result.get("is_error") is not True
    assert result["task"]["task_id"] == "task-bgm"
    assert result["task"]["status"] == "queued"
    assert "无需等待" in result["task"]["message"]
    assert calls == [(ctx.pm, "demo", 1, "calm instrumental", 7, "agent")]
