from __future__ import annotations

from types import SimpleNamespace

import pytest

from lib.narration_delivery import (
    POST_PRODUCTION,
    NarrationDeliveryRequestOptions,
    narration_delivery_for_video_workflow,
    video_workflow_uses_narration_delivery,
)
from lib.workflow_plan import WorkflowStepState, build_workflow_plan
from lib.workflow_state import WorkflowActionType, WorkflowNextAction, WorkflowProject, WorkflowStatus, WorkflowTarget
from server.agent_runtime.sdk_tools.enqueue_videos import _reference_request_options, _tool_schema_for_context

pytestmark = pytest.mark.unit


def _video_status(content_mode: str, generation_mode: str) -> WorkflowStatus:
    return WorkflowStatus.model_validate(
        {
            "schema_version": 1,
            "project_revision": "sha256-v1:project",
            "source_revision": "sha256-v1:source",
            "project": WorkflowProject(
                content_mode=content_mode,
                generation_mode=generation_mode,
                grid_storyboard=False,
            ),
            "target": WorkflowTarget(
                episode=1,
                script="scripts/episode_1.json",
                script_filename="episode_1.json",
                source="source/episode_1.txt",
            ),
            "state": "VIDEO",
            "blockers": [],
            "gates": {},
            "artifacts": {
                "script": {"state": "current", "path": "scripts/episode_1.json"},
                "videos": {"current_ids": [], "stale_ids": [], "missing_ids": ["E1U1"]},
                "audio": {"current_ids": [], "stale_ids": [], "missing_ids": ["E1U1"]},
            },
            "next_action": WorkflowNextAction(
                type=WorkflowActionType.GENERATE_VIDEOS,
                requested_ids=["E1U1"],
                reason="video clips are missing",
            ),
        }
    )


@pytest.mark.parametrize(
    ("content_mode", "generation_mode"),
    [("drama", "storyboard"), ("drama", "reference_video"), ("course", "reference_video")],
)
def test_drama_and_course_video_plans_omit_narration_delivery(
    content_mode: str,
    generation_mode: str,
) -> None:
    plan = build_workflow_plan(_video_status(content_mode, generation_mode))

    assert all(step.id != "narration_delivery" for step in plan.steps)
    assert plan.narration_delivery is None
    assert plan.next_action.type is WorkflowActionType.GENERATE_VIDEOS


def test_ad_video_plan_retains_explicit_narration_delivery_choice() -> None:
    plan = build_workflow_plan(_video_status("ad", "storyboard"))

    delivery_step = next(step for step in plan.steps if step.id == "narration_delivery")
    assert delivery_step.required is True
    assert delivery_step.state is WorkflowStepState.READY
    assert plan.narration_delivery is not None
    assert plan.next_action.type is WorkflowActionType.CHOOSE_NARRATION_DELIVERY


@pytest.mark.parametrize("content_mode", ["drama", "course"])
def test_video_request_payload_omits_delivery_for_decoupled_modes(content_mode: str) -> None:
    assert video_workflow_uses_narration_delivery(content_mode) is False
    assert narration_delivery_for_video_workflow(content_mode, POST_PRODUCTION) is None
    assert NarrationDeliveryRequestOptions(narration_delivery=None).to_payload() == {}


@pytest.mark.parametrize("content_mode", ["drama", "course"])
def test_agent_video_contract_omits_and_rejects_retired_delivery_parameter(content_mode: str) -> None:
    ctx = SimpleNamespace(
        project_name="demo",
        pm=SimpleNamespace(load_project=lambda _name: {"content_mode": content_mode}),
    )
    schema = {
        "type": "object",
        "properties": {"script": {"type": "string"}, "narration_delivery": {"type": "string"}},
        "required": ["script", "narration_delivery"],
    }

    projected = _tool_schema_for_context(ctx, schema)
    assert "narration_delivery" not in projected["properties"]
    assert "narration_delivery" not in projected["required"]
    assert _reference_request_options({}, content_mode=content_mode).narration_delivery is None
    with pytest.raises(ValueError, match="已移除 narration_delivery 参数"):
        _reference_request_options({"narration_delivery": POST_PRODUCTION}, content_mode=content_mode)


def test_ad_agent_video_contract_still_requires_delivery() -> None:
    with pytest.raises(ValueError, match="narration_delivery 必填"):
        _reference_request_options({}, content_mode="ad")
    assert (
        _reference_request_options({"narration_delivery": POST_PRODUCTION}, content_mode="ad").narration_delivery
        == POST_PRODUCTION
    )
