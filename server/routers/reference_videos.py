"""参考生视频 CRUD + 生成路由。

Mount prefix: /api/v1/projects/{project_name}/reference-videos
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from lib.api_errors import ApiError, BadRequestError, NotFoundError
from lib.artifact_activation import resolve_artifact_episode
from lib.batch_admission import BatchAdmission, BatchAdmissionDecision, refused_ticket
from lib.course_video import derive_course_dependencies
from lib.db import async_session_factory
from lib.generation_queue import get_generation_queue
from lib.generation_queue_client import (
    BatchTaskResult,
    TaskSpec,
    TaskSpecValidationError,
    batch_enqueue_only,
)
from lib.generation_result import (
    GenerationAction,
    GenerationProblemCode,
    GenerationSelectionMode,
    enqueue_problem,
    normalize_requested_ids,
)
from lib.i18n import Translator
from lib.narration_delivery import (
    POST_PRODUCTION,
    USE_TTS,
    NarrationDelivery,
    narration_delivery_for_video_workflow,
    video_request_cost_unavailable_problem,
    video_request_requires_exact_quote,
    video_request_reuses_current_visual,
    video_workflow_uses_narration_delivery,
)
from lib.path_safety import PathTraversalError, safe_join
from lib.project_change_hints import project_change_source
from lib.project_manager import get_project_manager, is_reference_video_project
from lib.reference_video import derive_references_from_text
from lib.reference_video.keyframes import (
    DEFAULT_ENTRY_KEYFRAME_DESCRIPTION,
    MAX_KEYFRAMES_PER_UNIT,
    find_keyframe,
    keyframe_id,
    keyframe_mention,
    without_keyframe_mentions,
)
from lib.reference_video.prompt_render import resolve_reference_audio_paths
from lib.reference_video.request_projection import (
    ReferenceRequestOptions,
    ReferenceUnitRequestProjection,
    project_reference_unit_request,
)
from lib.reference_video.script_preview import build_script_preview
from lib.reference_video.units import reference_video_bucket
from lib.reference_video.voice_settings import VoiceRenderSettings
from lib.resource_paths import resource_relative_path
from lib.script_editor import ScriptEditError
from lib.speech_composition import admit_script_unit, refresh_video_unit_replan_state
from lib.version_manager import VersionManager
from lib.video_dependency import dependency_source_unit_id, derive_drama_video_dependencies
from server.auth import CurrentUser
from server.error_handlers import script_edit_detail
from server.routers._reorder import full_permutation_error
from server.routers._script_edits import execute_current_episode_edit, require_script_edit_result
from server.services.cost_estimation import quote_video_request
from server.services.effective_global_assets import resolve_linked_global_reference_audio_paths
from server.services.generation_tasks import emit_generation_success_batch
from server.services.h3_prompt_optimization import H3PromptOptimizationError, H3PromptOptimizationService
from server.services.h3_refine_tasks import (
    H3RefineUnavailable,
    enqueue_h3_refine_task,
    h3_refine_status,
)
from server.services.image_model_selection import ImageModelSelection
from server.services.narration_delivery_tasks import (
    prepare_current_reference_video_request_options,
    tts_task_in_progress,
)
from server.services.reference_keyframe_tasks import reference_keyframe_task_specs
from server.services.reference_storyboard_sheet_tasks import (
    StoryboardSheetGateError,
    reference_storyboard_sheet_task_specs,
)
from server.services.reference_storyboard_sheet_tasks import (
    confirm_storyboard_sheet as confirm_storyboard_sheet_service,
)
from server.services.reference_video_review import (
    ReferenceVideoReviewUnavailable,
    confirm_reference_video,
)
from server.services.reference_video_tasks import (
    apply_unit_video_assets,
    default_unit_duration,
    resolve_project_duration_context,
)
from server.services.upload_finalize import (
    UploadValidationError,
    commit_manual_video_upload,
    stage_uploaded_video_stream,
    validate_upload,
)
from server.services.video_batch_admission import (
    admit_reference_video_batch,
    artifact_state_tickets,
    reference_unit_task_spec,
    request_options_for_unit,
    resolve_reference_batch_targets,
    screen_script_entries,
)
from server.services.video_caps import project_video_caps

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_name}/reference-videos",
    tags=["reference-videos"],
)

# ============ 请求模型 ============


class ScriptPreviewRequest(BaseModel):
    prompt: str = ""
    unit_id: str | None = None


class StoryboardSheetGenerationRequest(ImageModelSelection):
    instructions: str | None = Field(default=None, max_length=4000)


class AddUnitRequest(BaseModel):
    # extra="forbid"：正文是单元的唯一真相，参考图执行期才派生。旧客户端仍带着
    # ``references`` 调用时要拿到 422 而不是被静默丢弃——被丢弃的话它会以为自己
    # 指定的参考图生效了。
    model_config = ConfigDict(extra="forbid")

    prompt: str
    duration_seconds: int | None = Field(default=None, ge=1)
    transition_to_next: str = Field(default="cut", pattern=r"^(cut|fade|dissolve)$")
    note: str | None = None
    unit_type: str = Field(default="story", pattern=r"^(opening|story|explanation|closing)$")
    scenes: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    presenters: list[str] = Field(default_factory=list)


class GenerateUnitRequest(BaseModel):
    # 单目标入口保留后期配音默认（docs/adr/0061）：请求由用户在这条 unit 的界面上直接触发，
    # 界面已呈现该 unit 的旁白状态与费用，代价也止于这一条视频。必填只加在替整批选定准入判据
    # 与时长基准的入口（``GenerateUnitsBatchRequest``）与由模型推断参数的 Agent 视频工具上。
    narration_delivery: NarrationDelivery = POST_PRODUCTION
    confirmed_request_duration_seconds: int | None = Field(default=None, gt=0)

    def projection_options(self, content_mode: object = None) -> ReferenceRequestOptions:
        return ReferenceRequestOptions(
            narration_delivery=narration_delivery_for_video_workflow(content_mode, self.narration_delivery),
            confirmed_request_duration_seconds=self.confirmed_request_duration_seconds,
        )


class GenerateUnitsBatchRequest(BaseModel):
    """批量视频生成请求。

    ``unit_ids`` 省略时只补齐缺失项；指定 id 则重新生成对应单元。
    ``confirmed_request_durations`` 为用户在聚合确认中接受的时长档位。
    """

    unit_ids: list[str] | None = None
    # drama/course 视频生成不再携带旁白交付契约；ad 仍在路由层要求显式选择。
    narration_delivery: NarrationDelivery | None = None
    confirmed_request_durations: dict[str, PositiveInt] = Field(default_factory=dict)

    def projection_options(self, content_mode: object = None) -> ReferenceRequestOptions:
        return ReferenceRequestOptions(
            narration_delivery=narration_delivery_for_video_workflow(content_mode, self.narration_delivery)
        )


class H3PromptOperationRequest(BaseModel):
    """Final request facts shared by prompt status, optimization and review."""

    model_config = ConfigDict(extra="forbid")

    unit_ids: list[str] | None = None
    narration_delivery: NarrationDelivery = POST_PRODUCTION
    confirmed_request_durations: dict[str, PositiveInt] = Field(default_factory=dict)


class UpdateH3PromptRequest(BaseModel):
    """One manually edited H3 prompt and the request facts needed to validate it."""

    model_config = ConfigDict(extra="forbid")

    rendered_prompt: str = Field(min_length=1)
    narration_delivery: NarrationDelivery = POST_PRODUCTION
    confirmed_request_duration_seconds: PositiveInt | None = None


class AddKeyframeRequest(BaseModel):
    unit_id: str
    description: str = Field(min_length=1)


class PatchKeyframeRequest(BaseModel):
    description: str = Field(min_length=1)


class GenerateKeyframesRequest(ImageModelSelection):
    keyframe_ids: list[str] | None = None


def _raise_storyboard_gate(exc: StoryboardSheetGateError) -> NoReturn:
    raise BadRequestError(exc.code, **exc.params) from exc


# ============ 辅助 ============


def _load_episode_script(project_name: str, episode: int, _t: Translator) -> tuple[dict, dict, str]:
    """加载 project.json + 指定集的剧本。返回 (project, script, script_file)。"""
    try:
        project = get_project_manager().load_project(project_name)
    except FileNotFoundError as exc:
        raise NotFoundError("project_not_found", name=project_name) from exc
    episodes = project.get("episodes") or []
    meta = next((e for e in episodes if e.get("episode") == episode), None)
    if meta is None or not meta.get("script_file"):
        raise HTTPException(status_code=404, detail=_t("ref_episode_not_found", episode=episode))
    script_file = meta["script_file"]
    try:
        script = get_project_manager().load_script(project_name, script_file)
    except FileNotFoundError as exc:
        raise NotFoundError("script_not_found", name=script_file) from exc
    if not is_reference_video_project(project):
        raise HTTPException(status_code=409, detail=_t("ref_not_reference_video_mode"))
    return project, script, script_file


def _problem_payload(projection: ReferenceUnitRequestProjection, _t: Translator) -> list[dict[str, Any]]:
    payloads = projection.problem_payloads()
    for payload, problem in zip(payloads, projection.problems, strict=True):
        payload["message"] = _t(problem.code, **problem.parameters())
    return payloads


def _raise_projection_blocker(
    projection: ReferenceUnitRequestProjection,
    _t: Translator,
    *,
    allow_duration_confirmation: bool,
    request_cost: dict[str, object] | None = None,
) -> None:
    blockers = [
        problem
        for problem in projection.blocking_problems
        if not (allow_duration_confirmation and problem.code == "reference_duration_confirmation_required")
    ]
    if not blockers:
        return
    detail = projection.to_advisory_payload()
    detail["allowed"] = False
    detail["problems"] = _problem_payload(projection, _t)
    if request_cost is not None:
        detail["request_cost"] = request_cost
    raise HTTPException(
        status_code=400,
        detail=detail,
    )


async def _quote_reference_request(
    *,
    projection: ReferenceUnitRequestProjection,
    options: ReferenceRequestOptions,
    _t: Translator,
) -> dict[str, object] | None:
    """Quote one TTS-aware request or fail closed when a paid tier change has no exact price."""

    cost = projection.cost
    if cost is None or options.narration_delivery != USE_TTS:
        return None
    quote = await quote_video_request(cost, async_session_factory)
    if quote is not None:
        if video_request_reuses_current_visual(
            request_duration_seconds=cost.duration_seconds,
            current_reusable_visual_duration_seconds=options.current_reusable_visual_duration_seconds,
        ):
            quote = quote.without_new_video_charge()
        return quote.to_payload()
    if not video_request_requires_exact_quote(
        request_duration_seconds=cost.duration_seconds,
        planned_duration_seconds=projection.planned_duration,
        current_visual_duration_seconds=options.current_visual_duration_seconds,
        current_reusable_visual_duration_seconds=options.current_reusable_visual_duration_seconds,
    ):
        return None

    cost_problem = video_request_cost_unavailable_problem(cost)
    cost_payload = cost_problem.to_payload(unit_id=projection.unit_id)
    cost_payload["message"] = _t(cost_problem.code, **cost_problem.parameters())
    raise HTTPException(
        status_code=400,
        detail={
            **projection.to_advisory_payload(),
            "allowed": False,
            "problems": [*_problem_payload(projection, _t), cost_payload],
        },
    )


def _next_unit_id(script: dict, episode: int) -> str:
    existing = {str(u.get("unit_id", "")) for u in (script.get("video_units") or [])}
    idx = 1
    while f"E{episode}U{idx}" in existing:
        idx += 1
    return f"E{episode}U{idx}"


def _build_unit_dict(
    *,
    unit_id: str,
    prompt: str,
    duration_seconds: int,
    transition: str,
    note: str | None,
    unit_type: str = "story",
    scenes: list[str] | None = None,
    characters: list[str] | None = None,
    props: list[str] | None = None,
    presenters: list[str] | None = None,
) -> dict:
    has_body = bool(prompt.strip())
    first_keyframe_id = keyframe_id(unit_id, 1) if has_body else None
    unit = {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "text": f"{keyframe_mention(first_keyframe_id)} {prompt}".strip() if first_keyframe_id else prompt,
        "storyboard_description": prompt.strip() or None,
        "duration_seconds": duration_seconds,
        "transition_to_next": transition,
        "note": note,
        "scenes": list(scenes or []),
        "characters": list(characters or []),
        "props": list(props or []),
        "presenters": list(presenters or []),
        "video_dependency": None,
        "video_review_status": "pending_review",
        "confirmed_video_version": None,
        "keyframes": (
            [
                {
                    "keyframe_id": first_keyframe_id,
                    "description": DEFAULT_ENTRY_KEYFRAME_DESCRIPTION,
                    "image_path": None,
                }
            ]
            if first_keyframe_id
            else []
        ),
        "generated_assets": {
            "storyboard_image": None,
            "storyboard_last_image": None,
            "grid_id": None,
            "grid_cell_index": None,
            "video_clip": None,
            "video_uri": None,
            "status": "pending",
        },
    }
    refresh_video_unit_replan_state(unit)
    return unit


def _require_unit_ready(
    unit: dict,
    *,
    content_mode: str | None = None,
    ignore_marker: bool = False,
    allow_blank_draft: bool = False,
) -> None:
    if allow_blank_draft and not str(unit.get("text") or "").strip():
        return
    admission = admit_script_unit(
        "video_units",
        unit,
        ignore_marker=ignore_marker,
        content_mode=content_mode,
    )
    if not admission.allowed:
        raise HTTPException(status_code=409, detail=admission.to_dict())


# ============ 端点：列出 + 新建 ============


@router.get("/episodes/{episode}/units")
async def list_units(project_name: str, episode: int, _t: Translator) -> dict[str, Any]:
    _project, script, _sf = _load_episode_script(project_name, episode, _t)
    return {"units": script.get("video_units") or []}


@router.post("/episodes/{episode}/units", status_code=status.HTTP_201_CREATED)
async def add_unit(
    project_name: str,
    episode: int,
    req: AddUnitRequest,
    _t: Translator,
) -> dict[str, Any]:
    project, current, script_file = _load_episode_script(project_name, episode, _t)
    # 取档要看这条 unit 执行时到底会不会带参考图，故按正文里已登记的 `@[名称]` 判定——
    # 与执行期的解析同一个出口，未登记的提及不产生参考图、也就不施加带图档位约束。
    refs, _missing = derive_references_from_text(req.prompt, project)

    # 时长是 unit 级单一真相：请求未给出时按项目能力解析默认档位（异步 IO 不进项目锁临界区）
    duration_seconds = req.duration_seconds
    if duration_seconds is None:
        duration_seconds = default_unit_duration(
            await resolve_project_duration_context(
                project, capability=reference_video_bucket(with_references=bool(refs))
            ),
            project,
            with_references=bool(refs),
        )

    units = current.get("video_units") if isinstance(current.get("video_units"), list) else []
    unit = _build_unit_dict(
        unit_id=_next_unit_id(current, episode),
        prompt=req.prompt,
        duration_seconds=int(duration_seconds),
        transition=req.transition_to_next,
        note=req.note,
        unit_type=req.unit_type,
        scenes=req.scenes,
        characters=req.characters,
        props=req.props,
        presenters=req.presenters,
    )
    dependency_updates: list[dict[str, Any]] = []
    insert_after_id = units[-1].get("unit_id") if units else None
    if project.get("content_mode") == "course":
        # opening/closing are fixed bookends; newly authored body units belong
        # immediately before closing so the script remains valid after one edit.
        body = units[:-1] if units and units[-1].get("unit_type") == "closing" else units
        closing = units[-1:] if len(body) != len(units) else []
        projected = derive_course_dependencies([*body, unit, *closing])
        unit = next(item for item in projected if item["unit_id"] == unit["unit_id"])
        insert_after_id = body[-1].get("unit_id") if body else None
        dependency_updates = [
            {"op": "update", "id": item["unit_id"], "fields": {"video_dependency": item.get("video_dependency")}}
            for item in projected
            if item["unit_id"] != unit["unit_id"]
        ]
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [
            {"op": "insert_after", "after_id": insert_after_id, "item": unit},
            *dependency_updates,
        ],
    )
    require_script_edit_result(result)
    saved = get_project_manager().load_script(project_name, result.script)
    inserted = _find_unit(saved, unit["unit_id"], _t)
    return {"unit": inserted, "edit_result": result.model_dump(mode="json")}


# ============ 端点：PATCH + DELETE ============


class PatchUnitRequest(BaseModel):
    # extra="forbid" 同 ``AddUnitRequest``。
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = None
    storyboard_description: str | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    transition_to_next: str | None = Field(default=None, pattern=r"^(cut|fade|dissolve)$")
    note: str | None = None
    unit_type: str | None = Field(default=None, pattern=r"^(opening|story|explanation|closing)$")
    scenes: list[str] | None = None
    characters: list[str] | None = None
    props: list[str] | None = None
    presenters: list[str] | None = None


class PatchCourseBookendsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenes: list[str]
    characters: list[str]
    presenters: list[str]


def _find_unit(script: dict, unit_id: str, _t: Translator) -> dict:
    for u in script.get("video_units") or []:
        if u.get("unit_id") == unit_id:
            return u
    raise HTTPException(status_code=404, detail=_t("ref_unit_not_found", unit_id=unit_id))


def _find_unit_for_project(_project: dict, script: dict, unit_id: str, _t: Translator) -> dict:
    return _find_unit(script, unit_id, _t)


def _course_base_units_confirmed(project: dict, script: dict) -> bool:
    if project.get("content_mode") != "course":
        return True
    base_units = [
        unit
        for unit in script.get("video_units") or []
        if isinstance(unit, dict) and unit.get("unit_type") in {"opening", "story", "closing"}
    ]
    return bool(base_units) and all(
        unit.get("video_review_status") == "confirmed"
        and isinstance(unit.get("generated_assets"), dict)
        and bool(unit["generated_assets"].get("video_clip"))
        for unit in base_units
    )


def _require_course_generation_phase(project: dict, script: dict, unit: dict) -> None:
    if project.get("content_mode") != "course" or unit.get("unit_type") != "explanation":
        return
    if not _course_base_units_confirmed(project, script):
        raise HTTPException(status_code=409, detail="请先生成并确认全部引子、故事演绎和总结视频")
    predecessor_id = dependency_source_unit_id(unit)
    predecessor = next(
        (
            candidate
            for candidate in script.get("video_units") or []
            if isinstance(candidate, dict) and candidate.get("unit_id") == predecessor_id
        ),
        None,
    )
    assets = predecessor.get("generated_assets") if isinstance(predecessor, dict) else None
    if not isinstance(assets, dict) or not assets.get("video_clip"):
        raise HTTPException(status_code=409, detail=f"前置单元 {predecessor_id} 的视频尚未完成")


def _next_keyframe_id(unit: dict[str, Any]) -> str:
    used = {
        str(item.get("keyframe_id"))
        for item in unit.get("keyframes") or []
        if isinstance(item, dict) and item.get("keyframe_id")
    }
    for index in range(1, MAX_KEYFRAMES_PER_UNIT + 1):
        candidate = keyframe_id(str(unit.get("unit_id") or ""), index)
        if candidate not in used:
            return candidate
    raise BadRequestError("reference_keyframe_limit", max_count=MAX_KEYFRAMES_PER_UNIT)


def _remove_keyframe_tag(text: str, keyframe_id_value: str) -> str:
    return text.replace(keyframe_mention(keyframe_id_value), "").replace("\n\n\n", "\n\n").strip()


@router.post("/episodes/{episode}/keyframes", status_code=status.HTTP_201_CREATED)
async def add_keyframe(
    project_name: str,
    episode: int,
    req: AddKeyframeRequest,
    _t: Translator,
) -> dict[str, Any]:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    unit = _find_unit(current, req.unit_id, _t)
    keyframes = [item for item in unit.get("keyframes") or [] if isinstance(item, dict)]
    if len(keyframes) >= MAX_KEYFRAMES_PER_UNIT:
        raise BadRequestError("reference_keyframe_limit", max_count=MAX_KEYFRAMES_PER_UNIT)
    value = _next_keyframe_id(unit)
    item = {"keyframe_id": value, "description": req.description.strip(), "image_path": None}
    next_text = f"{str(unit.get('text') or '').rstrip()}\n\n{keyframe_mention(value)}".strip()
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [{"op": "update", "id": req.unit_id, "fields": {"text": next_text, "keyframes": [*keyframes, item]}}],
    )
    require_script_edit_result(result)
    return {"keyframe": item, "edit_result": result.model_dump(mode="json")}


@router.patch("/episodes/{episode}/keyframes/{keyframe_id_value}")
async def patch_keyframe(
    project_name: str,
    episode: int,
    keyframe_id_value: str,
    req: PatchKeyframeRequest,
    _t: Translator,
) -> dict[str, Any]:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    found = find_keyframe(current, keyframe_id_value)
    if found is None:
        raise NotFoundError("reference_keyframe_not_found", id=keyframe_id_value)
    unit, _existing = found
    keyframes = [dict(item) for item in unit.get("keyframes") or [] if isinstance(item, dict)]
    updated = next(item for item in keyframes if item.get("keyframe_id") == keyframe_id_value)
    updated["description"] = req.description.strip()
    if updated.get("image_path"):
        updated["generation_input_changed"] = True
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [{"op": "update", "id": unit["unit_id"], "fields": {"keyframes": keyframes}}],
    )
    require_script_edit_result(result)
    return {"keyframe": updated, "edit_result": result.model_dump(mode="json")}


@router.delete("/episodes/{episode}/keyframes/{keyframe_id_value}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyframe(
    project_name: str,
    episode: int,
    keyframe_id_value: str,
    _t: Translator,
) -> Response:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    found = find_keyframe(current, keyframe_id_value)
    if found is None:
        raise NotFoundError("reference_keyframe_not_found", id=keyframe_id_value)
    unit, _existing = found
    keyframes = [
        dict(item)
        for item in unit.get("keyframes") or []
        if isinstance(item, dict) and item.get("keyframe_id") != keyframe_id_value
    ]
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [
            {
                "op": "update",
                "id": unit["unit_id"],
                "fields": {
                    "text": _remove_keyframe_tag(str(unit.get("text") or ""), keyframe_id_value),
                    "keyframes": keyframes,
                },
            }
        ],
    )
    require_script_edit_result(result)
    current_path = get_project_manager().get_project_path(project_name) / resource_relative_path(
        "keyframes", keyframe_id_value
    )
    await asyncio.to_thread(current_path.unlink, missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _enqueue_keyframe_specs(
    *,
    project_name: str,
    specs: list[TaskSpec],
    user_id: str,
) -> tuple[list[str], bool]:
    queue = get_generation_queue()
    task_ids: list[str] = []
    deduped: list[bool] = []
    for spec in specs:
        result = await queue.enqueue_task(
            project_name=project_name,
            task_type=spec.task_type,
            media_type=spec.media_type,
            resource_id=spec.resource_id,
            script_file=spec.script_file,
            payload=spec.payload,
            source="webui",
            user_id=user_id,
        )
        task_ids.append(result["task_id"])
        deduped.append(bool(result.get("deduped")))
    return task_ids, bool(task_ids) and all(deduped)


@router.post("/episodes/{episode}/keyframes/generate-batch")
async def generate_keyframes_batch(
    project_name: str,
    episode: int,
    req: GenerateKeyframesRequest,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    _project, script, script_file = _load_episode_script(project_name, episode, _t)
    requested = set(req.keyframe_ids) if req.keyframe_ids is not None else None
    try:
        specs = reference_keyframe_task_specs(
            script,
            script_file,
            keyframe_ids=requested,
            missing_only=requested is None,
            image_override=req.image_override_payload(),
        )
    except StoryboardSheetGateError as exc:
        _raise_storyboard_gate(exc)
    if requested is not None:
        found = {spec.resource_id for spec in specs}
        missing = sorted(requested - found)
        if missing:
            raise NotFoundError("reference_keyframe_not_found", id=", ".join(missing))
    task_ids, deduped = await _enqueue_keyframe_specs(project_name=project_name, specs=specs, user_id=user.id)
    return {
        "success": True,
        "task_ids": task_ids,
        "deduped": deduped,
        "message": _t("reference_keyframes_task_submitted", count=len(task_ids)),
    }


@router.post("/episodes/{episode}/keyframes/{keyframe_id_value}/generate")
async def generate_keyframe(
    project_name: str,
    episode: int,
    keyframe_id_value: str,
    req: ImageModelSelection,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    _project, script, script_file = _load_episode_script(project_name, episode, _t)
    try:
        specs = reference_keyframe_task_specs(
            script,
            script_file,
            keyframe_ids={keyframe_id_value},
            image_override=req.image_override_payload(),
        )
    except StoryboardSheetGateError as exc:
        _raise_storyboard_gate(exc)
    if not specs:
        raise NotFoundError("reference_keyframe_not_found", id=keyframe_id_value)
    task_ids, deduped = await _enqueue_keyframe_specs(project_name=project_name, specs=specs, user_id=user.id)
    return {
        "success": True,
        "task_id": task_ids[0],
        "deduped": deduped,
        "message": _t("reference_keyframe_task_submitted", id=keyframe_id_value),
    }


@router.post("/episodes/{episode}/units/{unit_id}/storyboard-sheet/generate")
async def generate_storyboard_sheet(
    project_name: str,
    episode: int,
    unit_id: str,
    req: StoryboardSheetGenerationRequest,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    _project, script, script_file = _load_episode_script(project_name, episode, _t)
    specs = reference_storyboard_sheet_task_specs(
        script,
        script_file,
        unit_ids={unit_id},
        image_override=req.image_override_payload(),
        instructions=req.instructions,
    )
    if not specs:
        raise NotFoundError("ref_unit_not_found", unit_id=unit_id)
    task_ids, deduped = await _enqueue_keyframe_specs(project_name=project_name, specs=specs, user_id=user.id)
    return {
        "success": True,
        "task_id": task_ids[0],
        "deduped": deduped,
        "message": _t("reference_storyboard_sheet_task_submitted", unit_id=unit_id),
    }


@router.post("/episodes/{episode}/units/{unit_id}/storyboard-sheet/confirm")
async def confirm_storyboard_sheet(
    project_name: str,
    episode: int,
    unit_id: str,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    _project, _script, script_file = _load_episode_script(project_name, episode, _t)
    try:
        sheet = await confirm_storyboard_sheet_service(project_name, script_file, unit_id, user_id=user.id)
    except StoryboardSheetGateError as exc:
        _raise_storyboard_gate(exc)
    return {
        "success": True,
        "storyboard_sheet": sheet,
        "message": _t("reference_storyboard_sheet_confirmed", unit_id=unit_id),
    }


@router.patch("/episodes/{episode}/units/{unit_id}")
async def patch_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    req: PatchUnitRequest,
    _t: Translator,
) -> dict[str, Any]:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    _find_unit(current, unit_id, _t)
    fields: dict[str, Any] = {}
    if req.prompt is not None:
        fields["text"] = req.prompt
    if req.storyboard_description is not None:
        fields["storyboard_description"] = without_keyframe_mentions(req.storyboard_description)
    if req.duration_seconds is not None:
        fields["duration_seconds"] = req.duration_seconds
    if req.transition_to_next is not None:
        fields["transition_to_next"] = req.transition_to_next
    if req.note is not None:
        fields["note"] = req.note
    for field_name in ("unit_type", "scenes", "characters", "props", "presenters"):
        value = getattr(req, field_name)
        if value is not None:
            fields[field_name] = value
    if not fields:
        return {"unit": _find_unit(current, unit_id, _t)}
    operations: list[dict[str, Any]] = [{"op": "update", "id": unit_id, "fields": fields}]
    if _project.get("content_mode") == "course":
        projected: list[dict[str, Any]] = []
        for existing in current.get("video_units") or []:
            candidate = dict(existing)
            if candidate.get("unit_id") == unit_id:
                candidate.update(fields)
            projected.append(candidate)
        projected = derive_course_dependencies(projected)
        dependency_by_id = {item["unit_id"]: item.get("video_dependency") for item in projected}
        operations = [
            {
                "op": "update",
                "id": existing["unit_id"],
                "fields": {
                    **(fields if existing.get("unit_id") == unit_id else {}),
                    "video_dependency": dependency_by_id[existing["unit_id"]],
                },
            }
            for existing in current.get("video_units") or []
            if isinstance(existing, dict) and existing.get("unit_id") in dependency_by_id
        ]
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        operations,
    )
    require_script_edit_result(result, operation_not_found=True)
    saved = get_project_manager().load_script(project_name, result.script)
    unit = _find_unit(saved, unit_id, _t)
    return {"unit": unit, "edit_result": result.model_dump(mode="json")}


@router.patch("/episodes/{episode}/course-bookends")
async def patch_course_bookends(
    project_name: str,
    episode: int,
    req: PatchCourseBookendsRequest,
    _t: Translator,
) -> dict[str, Any]:
    project, current, script_file = _load_episode_script(project_name, episode, _t)
    if project.get("content_mode") != "course":
        raise HTTPException(status_code=409, detail="仅课程视频项目支持首尾场景联动编辑")
    units = [unit for unit in current.get("video_units") or [] if isinstance(unit, dict)]
    opening = next((unit for unit in units if unit.get("unit_type") == "opening"), None)
    closing = next((unit for unit in units if unit.get("unit_type") == "closing"), None)
    if opening is None or closing is None:
        raise HTTPException(status_code=409, detail="课程视频缺少 opening 或 closing 单元")
    fields = {
        "scenes": req.scenes,
        "characters": req.characters,
        "presenters": req.presenters,
    }
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [
            {"op": "update", "id": opening["unit_id"], "fields": fields},
            {"op": "update", "id": closing["unit_id"], "fields": fields},
        ],
    )
    require_script_edit_result(result)
    saved = get_project_manager().load_script(project_name, result.script)
    return {
        "units": [unit for unit in saved.get("video_units") or [] if unit.get("unit_type") in {"opening", "closing"}],
        "edit_result": result.model_dump(mode="json"),
    }


@router.delete("/episodes/{episode}/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    _t: Translator,
) -> Response:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    _find_unit(current, unit_id, _t)
    result = execute_current_episode_edit(
        get_project_manager(),
        project_name,
        episode,
        script_file,
        current,
        [{"op": "remove", "id": unit_id}],
    )
    require_script_edit_result(result, operation_not_found=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ReorderRequest(BaseModel):
    unit_ids: list[str]


@router.post("/episodes/{episode}/units/reorder")
async def reorder_units(
    project_name: str,
    episode: int,
    req: ReorderRequest,
    _t: Translator,
) -> dict[str, Any]:
    _project, current, script_file = _load_episode_script(project_name, episode, _t)
    units = current.get("video_units") or []
    existing_ids = [unit.get("unit_id") for unit in units]
    error_kind = full_permutation_error(existing_ids, req.unit_ids)
    if error_kind is not None:
        detail_key = {
            "length": "ref_unit_ids_length_mismatch",
            "duplicate": "ref_duplicate_unit_ids",
            "mismatch": "ref_unit_ids_mismatch",
        }[error_kind]
        raise HTTPException(status_code=400, detail=_t(detail_key))
    if existing_ids == req.unit_ids:
        return {"units": units}
    operations = [
        {"op": "move_after", "id": unit_id, "after_id": req.unit_ids[index - 1] if index else None}
        for index, unit_id in enumerate(req.unit_ids)
    ]
    if _project.get("content_mode") == "course":
        by_id = {unit.get("unit_id"): unit for unit in units if isinstance(unit, dict)}
        projected = derive_course_dependencies([by_id[unit_id] for unit_id in req.unit_ids])
        operations.extend(
            {
                "op": "update",
                "id": unit["unit_id"],
                "fields": {"video_dependency": unit.get("video_dependency")},
            }
            for unit in projected
        )
    elif _project.get("content_mode") == "drama":
        by_id = {unit.get("unit_id"): unit for unit in units if isinstance(unit, dict)}
        projected = derive_drama_video_dependencies(
            [
                {
                    **by_id[unit_id],
                    "continues_previous": dependency_source_unit_id(by_id[unit_id]) is not None,
                }
                for unit_id in req.unit_ids
            ]
        )
        operations.extend(
            {
                "op": "update",
                "id": unit["unit_id"],
                "fields": {"video_dependency": unit.get("video_dependency")},
            }
            for unit in projected
        )
    result = execute_current_episode_edit(
        get_project_manager(), project_name, episode, script_file, current, operations
    )
    require_script_edit_result(result)
    reordered = get_project_manager().load_script(project_name, result.script)["video_units"]
    return {"units": reordered, "edit_result": result.model_dump(mode="json")}


@router.post("/episodes/{episode}/units/{unit_id}/confirm-video")
async def confirm_unit_video(
    project_name: str,
    episode: int,
    unit_id: str,
    _t: Translator,
) -> dict[str, Any]:
    try:
        return await confirm_reference_video(
            get_project_manager(),
            project_name,
            episode,
            unit_id,
        )
    except ReferenceVideoReviewUnavailable as exc:
        missing = {"project_not_found", "ref_episode_not_found", "script_not_found", "ref_unit_not_found"}
        raise HTTPException(
            status_code=404 if exc.code in missing else 409,
            detail=_t(exc.code, **exc.params),
        ) from exc


@router.get("/episodes/{episode}/units/{unit_id}/hd")
async def get_unit_hd_status(
    project_name: str,
    episode: int,
    unit_id: str,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    result = await h3_refine_status(
        get_project_manager(),
        project_name,
        episode,
        unit_id,
        user_id=user.id,
    )
    code = result.get("code")
    if isinstance(code, str):
        params = result.get("params")
        result["message"] = _t(code, **(params if isinstance(params, dict) else {}))
    return result


@router.post("/episodes/{episode}/units/{unit_id}/hd", status_code=status.HTTP_202_ACCEPTED)
async def make_unit_hd(
    project_name: str,
    episode: int,
    unit_id: str,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    try:
        return await enqueue_h3_refine_task(
            get_project_manager(),
            project_name,
            episode,
            unit_id,
            source="webui",
            user_id=user.id,
        )
    except H3RefineUnavailable as exc:
        raise HTTPException(status_code=409, detail=_t(exc.code, **exc.params)) from exc


@router.get("/episodes/{episode}/units/{unit_id}/duration-precheck")
async def precheck_unit_duration(
    project_name: str,
    episode: int,
    unit_id: str,
    _t: Translator,
    narration_delivery: NarrationDelivery = POST_PRODUCTION,
) -> dict[str, Any]:
    """入队前的时长取档预检：申请秒数与请求时长基准不一致时前端需先向用户确认。

    ``needs_confirmation`` 为 false 时仅表示请求时长基准本身是当前档位成员。能力或档位元数据
    无法解析时返回结构化 blocker，不制造无约束申请。
    """
    project, script, script_file = _load_episode_script(project_name, episode, _t)
    content_mode = project.get("content_mode") or script.get("content_mode")
    narration_delivery = narration_delivery_for_video_workflow(content_mode, narration_delivery)
    unit = _find_unit(script, unit_id, _t)
    _require_unit_ready(unit, content_mode=script.get("content_mode") or project.get("content_mode"))
    tts_in_progress = (
        await tts_task_in_progress(
            project_name=project_name,
            resource_id=unit_id,
            script_file=script_file,
        )
        if narration_delivery == USE_TTS
        else False
    )

    project_path = get_project_manager().get_project_path(project_name)
    current_options = await prepare_current_reference_video_request_options(
        project=project,
        script=script,
        script_file=script_file,
        unit=unit,
        project_path=project_path,
        options=ReferenceRequestOptions(narration_delivery=narration_delivery),
        project_name=project_name,
        tts_in_progress=tts_in_progress,
    )
    projection = await project_reference_unit_request(
        project=project,
        script=script,
        unit=unit,
        project_path=project_path,
        options=current_options,
        tts_in_progress=tts_in_progress,
        current_options_materialized=True,
    )
    request_cost = await _quote_reference_request(projection=projection, options=current_options, _t=_t)
    _raise_projection_blocker(
        projection,
        _t,
        allow_duration_confirmation=True,
        request_cost=request_cost,
    )
    slot = projection.request_duration
    if slot is None:
        raise BadRequestError("reference_supported_durations_missing")
    response: dict[str, Any] = {
        **projection.to_advisory_payload(),
        "needs_confirmation": any(
            problem.blocking and problem.code == "reference_duration_confirmation_required"
            for problem in projection.problems
        ),
        "script_duration": projection.planned_duration,
        "current_visual_duration": projection.current_visual_duration,
        "duration_input": projection.duration_input,
        "request_duration": slot.seconds,
        "adjustment": slot.adjustment,
        "declared_capability": projection.declared_capability,
        "hydrated_capability": projection.hydrated_capability,
        "provider_id": projection.provider_id,
        "model_id": projection.model_id,
        "problems": _problem_payload(projection, _t),
    }
    if request_cost is not None:
        response["request_cost"] = request_cost
    return response


@router.post("/episodes/{episode}/script-preview")
async def preview_script(
    project_name: str,
    episode: int,
    req: ScriptPreviewRequest,
    user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    """视频单元正文的读时派生预览：utterances + 降级可见性 warning。

    只读、不落盘——正文是唯一真相，utterances 与参考图都是机械派生物。声音相关的
    warning 依赖该集视频后端的能力（``voice_consistency`` 与参考音频段数上限）与本集的无声
    开关，与执行层同一份解析出口；能力解析失败时按 ``soft`` 降级，只是少发这几条提示。
    """
    project, script, _sf = _load_episode_script(project_name, episode, _t)
    caps = await project_video_caps(project, degraded_to="解析预览不发声音相关提示", user_id=user.id)
    unit = _find_unit(script, req.unit_id, _t) if req.unit_id else None
    voice_settings = VoiceRenderSettings.from_caps(caps)
    if voice_settings.voice_consistency == "native" and not voice_settings.is_silent:
        project_path = get_project_manager().get_project_path(project_name)
        audio_ready = await asyncio.to_thread(resolve_reference_audio_paths, project, project_path)
        audio_ready.update(
            await resolve_linked_global_reference_audio_paths(
                project,
                project_path.parent,
                session_factory=async_session_factory,
            )
        )
        voice_settings = VoiceRenderSettings.from_caps(caps, audio_ready=audio_ready)
    preview = build_script_preview(
        req.prompt,
        project,
        voice_settings,
        max_reference_images=caps.get("max_reference_images"),
        unit=unit,
    )
    return {
        "utterances": [
            {"index": index, "kind": u.kind, "speaker": u.speaker, "text": u.text}
            for index, u in enumerate(preview.utterances, start=1)
        ],
        "warnings": [{"key": w["key"], "message": _t(w["key"], **w["params"])} for w in preview.warnings],
    }


async def _run_h3_prompt_operation(
    operation: str,
    project_name: str,
    episode: int,
    req: H3PromptOperationRequest,
) -> list[dict[str, Any]]:
    service = H3PromptOptimizationService()
    method = getattr(service, operation)
    try:
        results = await method(
            project_name,
            episode,
            unit_ids=req.unit_ids,
            narration_delivery=req.narration_delivery,
            confirmed_request_durations=req.confirmed_request_durations,
        )
    except H3PromptOptimizationError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "h3_prompt_output_invalid", "message": str(exc)},
        ) from exc
    payloads = [result.model_dump(mode="json") for result in results]
    for payload in payloads:
        artifact = payload.get("artifact") if isinstance(payload, dict) else None
        if isinstance(artifact, dict) and artifact.get("narration_delivery") is None:
            artifact.pop("narration_delivery", None)
        if isinstance(payload, dict) and payload.get("narration_delivery") is None:
            payload.pop("narration_delivery", None)
    return payloads


@router.post("/episodes/{episode}/h3-prompts/status")
async def h3_prompt_status(
    project_name: str,
    episode: int,
    req: H3PromptOperationRequest,
) -> dict[str, Any]:
    return {"states": await _run_h3_prompt_operation("states", project_name, episode, req)}


@router.post("/episodes/{episode}/h3-prompts/optimize")
async def optimize_h3_prompts(
    project_name: str,
    episode: int,
    req: H3PromptOperationRequest,
) -> dict[str, Any]:
    return {"artifacts": await _run_h3_prompt_operation("optimize", project_name, episode, req)}


@router.post("/episodes/{episode}/h3-prompts/confirm")
async def confirm_h3_prompts(
    project_name: str,
    episode: int,
    req: H3PromptOperationRequest,
) -> dict[str, Any]:
    return {"artifacts": await _run_h3_prompt_operation("confirm", project_name, episode, req)}


@router.patch("/episodes/{episode}/h3-prompts/{unit_id}")
async def update_h3_prompt(
    project_name: str,
    episode: int,
    unit_id: str,
    req: UpdateH3PromptRequest,
) -> dict[str, Any]:
    try:
        artifact = await H3PromptOptimizationService().update_prompt(
            project_name,
            episode,
            unit_id=unit_id,
            rendered_prompt=req.rendered_prompt,
            narration_delivery=req.narration_delivery,
            confirmed_request_duration_seconds=req.confirmed_request_duration_seconds,
        )
    except H3PromptOptimizationError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "h3_prompt_output_invalid", "message": str(exc)},
        ) from exc
    payload = artifact.model_dump(mode="json")
    if payload.get("narration_delivery") is None:
        payload.pop("narration_delivery", None)
    return {"artifact": payload}


@router.post(
    "/episodes/{episode}/units/{unit_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    user: CurrentUser,
    _t: Translator,
    req: GenerateUnitRequest | None = None,
) -> dict[str, Any]:
    project, script, script_file = _load_episode_script(project_name, episode, _t)
    unit = _find_unit(script, unit_id, _t)  # raises 404 if missing
    _require_course_generation_phase(project, script, unit)
    _require_unit_ready(unit, content_mode=script.get("content_mode") or project.get("content_mode"))
    guard_prompt = str(unit.get("text") or "")
    content_mode = project.get("content_mode") or script.get("content_mode")
    request_options = (req or GenerateUnitRequest()).projection_options(content_mode)
    tts_in_progress = (
        await tts_task_in_progress(
            project_name=project_name,
            resource_id=unit_id,
            script_file=script_file,
        )
        if request_options.narration_delivery == USE_TTS
        else False
    )
    project_path = get_project_manager().get_project_path(project_name)
    current_options = await prepare_current_reference_video_request_options(
        project=project,
        script=script,
        script_file=script_file,
        unit=unit,
        project_path=project_path,
        options=request_options,
        project_name=project_name,
        tts_in_progress=tts_in_progress,
    )
    projection = await project_reference_unit_request(
        project=project,
        script=script,
        unit=unit,
        project_path=project_path,
        options=current_options,
        tts_in_progress=tts_in_progress,
        current_options_materialized=True,
    )
    request_cost = await _quote_reference_request(projection=projection, options=current_options, _t=_t)
    _raise_projection_blocker(
        projection,
        _t,
        allow_duration_confirmation=False,
        request_cost=request_cost,
    )
    # 经统一守卫点构造：空提示词的结构校验在此当场拒绝（400），与 SDK 入队路径一致，
    # 不再漏到执行层失败（见 ADR-0001）。
    try:
        spec = TaskSpec.from_request(
            task_type="reference_video",
            media_type="video",
            resource_id=unit_id,
            prompt=guard_prompt,
            script_file=script_file,
            extra_payload={"reference_request_options": request_options.to_payload()},
        )
    except TaskSpecValidationError as exc:
        raise HTTPException(status_code=400, detail=_t(exc.code, **exc.params)) from exc

    queue = get_generation_queue()
    result = await queue.enqueue_task(
        project_name=project_name,
        task_type=spec.task_type,
        media_type=spec.media_type,
        resource_id=spec.resource_id,
        payload=spec.payload,
        script_file=spec.script_file,
        source="webui",
        user_id=user.id,
    )
    projection_payload = {**projection.to_advisory_payload(), "problems": _problem_payload(projection, _t)}
    if request_cost is not None:
        projection_payload["request_cost"] = request_cost
    return {
        "task_id": result["task_id"],
        "deduped": result.get("deduped", False),
        "projection": projection_payload,
    }


def _admission_payload(admission: BatchAdmission, _t: Translator) -> dict[str, Any]:
    """Localize the shared admission envelope for the browser.

    Only the message strings are added: codes, actions, tiers and costs stay
    exactly as the shared seam produced them, so Web and Agent never disagree
    about what happened — only about what language it is read in.
    """

    payload = admission.to_payload()
    units = payload.get("units")
    if isinstance(units, list):
        for unit in units:
            problems = unit.get("problems") if isinstance(unit, dict) else None
            if not isinstance(problems, list):
                continue
            for problem in problems:
                if isinstance(problem, dict):
                    params = problem.get("params")
                    problem["message"] = _t(str(problem.get("code")), **(params if isinstance(params, dict) else {}))
    return payload


def _enqueue_failure_payload(failure: BatchTaskResult, _t: Translator) -> dict[str, Any]:
    """一个没能入队的目标，按共享契约的问题形状转述给浏览器。

    问题码与下一步动作与 Agent 侧同源，只多一句本地化说明。原始异常文本（`detail`）来自数据库与
    队列层，可能带出连接串或内部拓扑，因此只落服务端日志，不进浏览器响应体——与 `_admission_payload`
    只转述受控问题码的姿态一致。
    """

    problem = enqueue_problem(failure.error, interrupted=failure.enqueue_interrupted)
    logger.warning("reference batch enqueue failed for unit %s: %s", failure.resource_id, problem.detail)
    return {
        "unit_id": failure.resource_id,
        "problem": {**problem.model_dump(mode="json", exclude={"detail"}), "message": _t(problem.code)},
    }


@router.post("/episodes/{episode}/units/generate-batch")
async def generate_units_batch(
    project_name: str,
    episode: int,
    user: CurrentUser,
    _t: Translator,
    req: GenerateUnitsBatchRequest,
) -> dict[str, Any]:
    """Admit a whole batch of reference units, then create their tasks.

    The verdict is returned with HTTP 200 in all three outcomes: an evaluation
    that refuses the request is a successful evaluation, and collapsing it into a
    generic 4xx would hide every gap after the first one. Callers branch on
    ``decision``. An admitted batch whose enqueue is interrupted is likewise a
    200: the tasks already created run on, and ``enqueue_failures`` names the
    targets that never reached the queue.
    """

    project, script, script_file = _load_episode_script(project_name, episode, _t)
    body = req
    content_mode = project.get("content_mode") or script.get("content_mode")
    if video_workflow_uses_narration_delivery(content_mode) and body.narration_delivery is None:
        raise HTTPException(status_code=422, detail="narration_delivery is required for this content mode")
    try:
        requested_ids = normalize_requested_ids(body.unit_ids, field="unit_ids")
    except ValueError as exc:
        raise BadRequestError("ref_batch_empty_selection") from exc

    # 容器原样交给筛查：`or []` 会把假值（false / 0 / ""）变成合法的空数组，那次请求就会
    # 报成「通过且零任务」，而不是如实说剧本的 video_units 坏了。成不了目标的条目（非对象、
    # 缺 unit_id、id 不是标量、id 重复，来自外部编辑或 Agent 裸写）在「缺失即生成」的目标
    # 集合里属于这次请求：悄悄略过就等于让同批健康的 unit 独自入队计费。
    units, malformed = screen_script_entries(script.get("video_units", []), requested_ids=requested_ids)

    if project.get("content_mode") in {"course", "drama"}:
        selected_units = units
        explanation_selected = any(unit.get("unit_type") == "explanation" for unit in selected_units)
        base_selected = any(unit.get("unit_type") != "explanation" for unit in selected_units)
        if requested_ids is not None and explanation_selected and base_selected:
            raise HTTPException(status_code=409, detail="课程基础视频与知识解说视频需分两批生成")
        if requested_ids is None:
            base_units = [unit for unit in units if unit.get("unit_type") != "explanation"]
            base_missing = [
                unit
                for unit in base_units
                if not isinstance(unit.get("generated_assets"), dict) or not unit["generated_assets"].get("video_clip")
            ]
            if base_missing:
                units = base_units
            elif not _course_base_units_confirmed(project, script):
                raise HTTPException(status_code=409, detail="请先确认全部基础视频，再生成知识解说")
            else:
                units = [unit for unit in units if unit.get("unit_type") == "explanation"]
        elif explanation_selected and not _course_base_units_confirmed(project, script):
            raise HTTPException(status_code=409, detail="请先确认全部基础视频，再生成知识解说")

    project_path = get_project_manager().get_project_path(project_name)
    artifact_episode = resolve_artifact_episode(project=project, script=script, script_filename=script_file) or episode
    targets, selection, _states = resolve_reference_batch_targets(
        units=units,
        requested_ids=requested_ids,
        project=project,
        project_path=project_path,
        episode=artifact_episode,
    )
    unmatched = [
        refused_ticket(
            unit_id,
            code=GenerationProblemCode.UNIT_NOT_FOUND,
            detail=f"unit {unit_id} 不在 video_units 中",
            action=GenerationAction.FIX_INPUT,
        )
        for unit_id in selection.unmatched_ids
    ]
    admission = await admit_reference_video_batch(
        project_name=project_name,
        project=project,
        project_path=project_path,
        script=script,
        script_file=script_file,
        episode=artifact_episode,
        units=targets,
        request_options=body.projection_options(content_mode),
        operation="generate_reference_videos_batch",
        selection=(
            GenerationSelectionMode.EXPLICIT if requested_ids is not None else GenerationSelectionMode.MISSING_ONLY
        ),
        confirmed_request_durations=body.confirmed_request_durations,
        spec_check=lambda unit: reference_unit_task_spec(
            unit,
            script_file,
            content_mode=script.get("content_mode") or project.get("content_mode"),
        ),
        # 产物状态不可读的 unit 被选目标环节排除在外，但它属于这次请求：不带进准入，
        # 同批健康的 unit 会照常入队，剩下这一个被无声略过。
        extra_tickets=[*unmatched, *malformed, *artifact_state_tickets(selection.unavailable)],
    )
    payload = _admission_payload(admission, _t)
    payload["skipped_unit_ids"] = sorted(state.unit_id for state in selection.skipped)
    if admission.decision is not BatchAdmissionDecision.ADMITTED:
        payload["task_ids"] = []
        payload["task_ids_by_unit"] = {}
        payload["enqueue_failures"] = []
        payload["deduped"] = False
        return payload

    specs = [
        reference_unit_task_spec(
            unit,
            script_file,
            content_mode=script.get("content_mode") or project.get("content_mode"),
        )
        for unit in targets
    ]
    for spec in specs:
        spec.source = "webui"
        # 确认过的档位按 unit 记进请求事实：它是本次请求的一部分，而不是全批共用的一个值。
        # 复用准入用的那份推导，两处各算一遍才是口径分叉的来源。
        options = request_options_for_unit(
            body.projection_options(content_mode),
            spec.resource_id,
            body.confirmed_request_durations,
        )
        spec.payload = {
            **(spec.payload or {}),
            "reference_request_options": options.to_payload(),
        }
    if project.get("content_mode") in {"course", "drama"}:
        target_ids = {spec.resource_id for spec in specs}
        unit_by_id = {unit.get("unit_id"): unit for unit in targets}
        for index, spec in enumerate(specs):
            unit = unit_by_id.get(spec.resource_id)
            predecessor = dependency_source_unit_id(unit) if isinstance(unit, dict) else None
            if isinstance(predecessor, str) and predecessor in target_ids:
                spec.dependency_resource_id = predecessor
                spec.dependency_group = f"video-dependency-episode-{episode}"
                spec.dependency_index = index
    enqueued, enqueue_failures = await batch_enqueue_only(project_name=project_name, specs=specs, user_id=user.id)
    # 入队中断不撤销已创建的任务：它们是准入通过的完整付费单元，照常执行。没轮到的目标
    # 逐 ID 报出来，界面据此释放乐观占用标记，下次「缺失即生成」只补这些。
    payload["enqueue_failures"] = [_enqueue_failure_payload(failure, _t) for failure in enqueue_failures]
    payload["task_ids"] = [item.task_id for item in enqueued]
    # 逐 unit 给出它自己的任务行：调用方的乐观占用标记要各等各的，拿整批清单会让每个 unit
    # 都等到全批落库为止。
    payload["task_ids_by_unit"] = {item.resource_id: item.task_id for item in enqueued}
    payload["deduped"] = bool(enqueued) and all(item.deduped for item in enqueued)
    return payload


@router.post("/episodes/{episode}/units/{unit_id}/upload-video")
async def upload_unit_video(
    project_name: str,
    episode: int,
    unit_id: str,
    _t: Translator,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """上传单元成片视频，替换该 unit 的 AI 生成视频。

    复用生成链路的 finalize（抽缩略图、清旧 video_uri、status=completed），
    并纳入版本管理。参考图上传走既有的项目资产上传通路，不在此处。
    """
    try:
        max_bytes = validate_upload(file.filename, file.size, kind="video")

        relative_path = resource_relative_path("reference_videos", unit_id)

        def _validate_unit() -> tuple[Path, VersionManager, str]:
            project, script, script_file = _load_episode_script(project_name, episode, _t)
            _find_unit_for_project(project, script, unit_id, _t)  # raises 404 if missing
            project_path = get_project_manager().get_project_path(project_name)
            # 路径遍历防护：unit_id 拼出的绝对路径不得逃出项目目录（与 versions.py 对齐）
            try:
                safe_join(project_path, relative_path)
            except PathTraversalError:
                raise HTTPException(status_code=400, detail=_t("invalid_resource_id", resource_id=unit_id))
            return project_path, VersionManager(project_path), script_file

        project_path, versions, script_file = await asyncio.to_thread(_validate_unit)
        target = project_path / relative_path

        with project_change_source("webui"):
            staged_video = await stage_uploaded_video_stream(file.file, target, max_bytes=max_bytes)

            # 上传流可达数百 MB、耗时数秒，期间 episode→script 绑定可能被并发重绑
            # （PATCH / agent 同步剧本）。staging 后重解析绑定，确保元数据写进当前生效的剧本。
            def _recheck_binding() -> str:
                project2, script2, script_file2 = _load_episode_script(project_name, episode, _t)
                _find_unit_for_project(project2, script2, unit_id, _t)
                return script_file2

            try:
                script_file = await asyncio.to_thread(_recheck_binding)

                def _commit_metadata(thumb_rel: str | None, on_commit: Callable[[Path], None]) -> None:
                    pm = get_project_manager()
                    with pm.locked_script(
                        project_name,
                        script_file,
                        validate=False,
                        on_commit=on_commit,
                    ) as script:
                        apply_unit_video_assets(script, unit_id, video_uri=None, thumb_rel=thumb_rel)

                version = await commit_manual_video_upload(
                    project_path=project_path,
                    versions=versions,
                    resource_type="reference_videos",
                    resource_id=unit_id,
                    script_file=script_file,
                    staged_video=staged_video,
                    current_video=target,
                    thumbnail_file=project_path / "reference_videos" / "thumbnails" / f"{unit_id}.jpg",
                    thumbnail_rel=f"reference_videos/thumbnails/{unit_id}.jpg",
                    original_filename=file.filename,
                    commit_metadata=_commit_metadata,
                )
            finally:
                await asyncio.to_thread(staged_video.unlink, missing_ok=True)
            # emit 内部会读剧本解析 episode 并计算指纹，放线程池避免阻塞事件循环；
            # 返回的指纹直接复用进响应体，免二次计算
            fingerprints = await asyncio.to_thread(
                emit_generation_success_batch,
                task_type="reference_video",
                project_name=project_name,
                resource_id=unit_id,
                payload={"script_file": script_file},
            )

        return {
            "success": True,
            "path": relative_path,
            "version": version,
            "asset_fingerprints": fingerprints,
        }
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=_t(exc.key, **exc.params)) from exc
    except FileNotFoundError as exc:
        # 不回传 str(exc)：load_script 的异常信息含服务器绝对路径
        raise NotFoundError("ref_script_missing") from exc
    except KeyError as exc:
        # finalize 写回时 unit 已被并发删除（落盘后绑定重查到锁内写回之间的窄竞态）
        raise HTTPException(status_code=404, detail=_t("ref_unit_not_found", unit_id=unit_id)) from exc
    except ScriptEditError as exc:
        raise HTTPException(status_code=400, detail=script_edit_detail(exc, _t)) from exc
    except (HTTPException, ApiError):
        # ApiError 与 HTTPException 并列：_load_episode_script 抛出的 NotFoundError
        # 不是 HTTPException 子类，不并入这里会被下面的 except Exception 吞成 500
        raise
    except Exception as exc:
        # 不回传 str(exc)：未预期异常的消息可能含服务器路径等内部细节，堆栈进日志即可
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc
