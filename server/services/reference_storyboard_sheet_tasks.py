"""Video Unit Storyboard generation as a sibling of Keyframe production."""

from __future__ import annotations

import asyncio
import math
import os
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from math import gcd
from pathlib import Path
from typing import Any

from lib.db.base import DEFAULT_USER_ID
from lib.generation_queue_client import TaskSpec
from lib.image_reference_snapshot import freeze_image_references
from lib.path_safety import PathTraversalError, safe_join
from lib.reference_video.keyframes import without_keyframe_mentions
from lib.reference_video.request_projection import resolve_reference_assets
from lib.resource_paths import resource_relative_path
from lib.video_visual_provenance import resolve_video_aspect_ratio
from server.services.generation_context import ImageLaneRequest, resolve_generation_context
from server.services.generation_tasks import get_project_manager
from server.services.reference_image_binding import (
    bind_resolved_assets,
    prompt_roster,
    provider_inputs,
    visual_references,
)
from server.services.video_caps import project_video_caps


class StoryboardSheetGateError(ValueError):
    """A stable code-backed error raised by the mandatory review gate."""

    def __init__(self, code: str, **params: object) -> None:
        self.code = code
        self.params = params
        super().__init__(code)


def _storyboard_description(unit: dict[str, Any]) -> str:
    """Use the editable image description, falling back to the formal manuscript."""

    return without_keyframe_mentions(str(unit.get("storyboard_description") or unit.get("text") or ""))


def reference_storyboard_sheet_task_specs(
    script: dict[str, Any],
    script_file: str,
    *,
    unit_ids: set[str] | None = None,
    missing_only: bool = False,
    image_override: dict[str, str] | None = None,
    instructions: str | None = None,
    instructions_by_unit: dict[str, str] | None = None,
) -> list[TaskSpec]:
    base_payload = dict(image_override or {})
    normalized_instructions = str(instructions or "").strip()
    normalized_by_unit = {
        str(key).strip(): str(value).strip()
        for key, value in (instructions_by_unit or {}).items()
        if str(key).strip() and str(value).strip()
    }
    specs: list[TaskSpec] = []
    for unit in script.get("video_units") or []:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        description = _storyboard_description(unit)
        if not unit_id or not description or (unit_ids is not None and unit_id not in unit_ids):
            continue
        sheet = unit.get("storyboard_sheet")
        if missing_only and isinstance(sheet, dict) and sheet.get("image_path"):
            continue
        extra_payload = dict(base_payload)
        unit_instructions = normalized_by_unit.get(unit_id, "")
        if normalized_instructions and unit_instructions:
            extra_payload["storyboard_instructions"] = (
                f"整批共同审核意见：\n{normalized_instructions}\n\n仅适用于 {unit_id} 的审核意见：\n{unit_instructions}"
            )
        elif unit_instructions:
            extra_payload["storyboard_instructions"] = unit_instructions
        elif normalized_instructions:
            extra_payload["storyboard_instructions"] = normalized_instructions
        specs.append(
            TaskSpec.from_request(
                task_type="reference_storyboard_sheet",
                media_type="image",
                resource_id=unit_id,
                prompt=description,
                script_file=script_file,
                extra_payload=extra_payload,
            )
        )
    return specs


def _panel_count(unit: dict[str, Any]) -> int:
    """Plan enough panels for both runtime and narrative density.

    Duration alone under-plans short but action-dense units (for example, a chase,
    fall, reaction, and recovery compressed into five seconds).  Keep the result
    bounded for image-model legibility while allowing transitions, dialogue beats,
    and unusually dense copy to add coverage.
    """

    duration = int(unit.get("duration_seconds") or 8)
    text = str(unit.get("text") or "")
    transition_markers = (
        "镜头切",
        "镜头转",
        "随后",
        "突然",
        "然后",
        "接着",
        "最后",
        "同时",
        "背景中",
        "回到",
    )
    transition_count = sum(text.count(marker) for marker in transition_markers)
    dialogue_count = text.count("]{")
    duration_count = math.ceil(duration / 2)
    transition_count = 4 + math.ceil((transition_count + max(0, dialogue_count - 1)) / 2)
    information_count = 4 + min(2, len(text) // 220)
    return max(4, min(8, max(duration_count, transition_count, information_count)))


def _sheet_grid(panel_count: int) -> tuple[int, int]:
    """Return a compact chronological grid for the requested panel count."""

    columns = 3 if panel_count > 4 else 2
    return columns, math.ceil(panel_count / columns)


def _sheet_aspect_ratio(panel_ratio: str, panel_count: int) -> str:
    """Auto-layout the outer canvas while preserving each cell's project ratio."""

    try:
        width_text, height_text = panel_ratio.split(":", 1)
        panel_width, panel_height = int(width_text), int(height_text)
        if panel_width <= 0 or panel_height <= 0:
            raise ValueError
    except (TypeError, ValueError):
        panel_width, panel_height = 9, 16
    columns, rows = _sheet_grid(panel_count)
    width = columns * panel_width
    height = rows * panel_height
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def normalize_storyboard_sheet_monochrome(image_path: Path) -> None:
    """Atomically turn the generated working sheet into a true grayscale PNG.

    Image models repeatedly leak subject colors from visual references even when
    the prompt forbids them.  Storyboard Sheets are production documents, so a
    deterministic post-process is the final invariant shared by Web UI and Agent
    calls.  Technical annotations may remain grayscale; color is optional there.
    """

    from PIL import Image, ImageOps

    fd, staged_name = tempfile.mkstemp(prefix=f".{image_path.stem}.gray.", suffix=".png", dir=image_path.parent)
    os.close(fd)
    staged_path = Path(staged_name)
    try:
        with Image.open(image_path) as source:
            grayscale = ImageOps.grayscale(source).convert("RGB")
            grayscale.save(staged_path, format="PNG", optimize=True)
        staged_path.replace(image_path)
    finally:
        staged_path.unlink(missing_ok=True)


def build_storyboard_sheet_prompt(
    project: dict[str, Any],
    unit: dict[str, Any],
    *,
    panel_ratio: str,
    panel_count: int,
    reference_roster: str,
    instructions: str | None = None,
) -> str:
    columns, rows = _sheet_grid(panel_count)
    sheet_ratio = _sheet_aspect_ratio(panel_ratio, panel_count)
    normalized_instructions = str(instructions or "").strip()
    review_block = (
        f"""

本次重新生成审核意见（用户明确授权，必须逐项落实；只改变分镜表达方式，不得新增、删除或改写脚本事实）：
{normalized_instructions}
"""
        if normalized_instructions
        else ""
    )
    return f"""生成一张用于拍摄与动画制作指导的 Video Unit Storyboard Sheet。它是生产工作文档，不是成片画面、概念设计图或彩色精修插画。

固定视觉规范：
- 主体必须是多画格黑白分镜：高对比黑色墨线、铅笔/炭笔灰阶和富有表现力的手绘线条；所有人物、场景、道具和光影只使用黑、白、灰。
- 彩色参考图只能用于身份、造型和空间绑定，必须转译成纯灰阶线稿；严禁保留参考图中梅瓶、服装、皮肤、花朵或背景的蓝、金、红等原有色相。
- 只允许技术批注使用少量鲜明的手绘红、蓝、绿、黄：方向箭头、运动路径、镜号、景别/焦段意图、简短动作、表情、对白/声音和时间提示。
- 彩色批注只是覆盖在黑白画格周围或留白处的技术信息，不能给人物、背景、道具或光影上色。
- 画面要像导演和动画师可直接使用的分镜工作表，优先表达动态、构图、动作连续性和信息覆盖；禁止最终渲染质感、电影级调色、彩色氛围光、精细材质和海报式装饰。

Video Unit：{unit.get("unit_id")}
项目成片风格（仅用于保持角色、时代、场景与设计身份一致，不得据此给分镜画格上色或精修）：{str(project.get("style") or "").strip()}
成片风格定义（同上，仅作身份与环境约束）：{str(project.get("style_description") or "").strip()}
正式 Video Unit 文稿（Storyboard 与 Keyframes 的共同上游）：
{str(unit.get("text") or "").strip()}

分镜版图片描述（支持与正式文稿一致的 `@[资产]` 引用语法，本次必须按此描述组织画格）：
{_storyboard_description(unit)}

真实参考图绑定（必须严格按 Picture 编号使用，不得把 @ 文本画进图里）：
{reference_roster}

版式要求：
- 输出一张外层比例约为 {sheet_ratio} 的 Storyboard Sheet；当前 {panel_count} 格可用 {columns} 列 × {rows} 行作为容量参考，但这不是固定矩阵模板，不得照搬其他项目的固定画布尺寸。
- 恰好包含 {panel_count} 个清晰分隔的 panel，按叙事发生顺序从左到右、从上到下排列。
- 每个单独 panel 的内容框都必须原生采用项目目标比例 {panel_ratio} 且边框清楚；不得把外层 Sheet 比例误当成 panel 比例，不得先画横屏再裁切、补边或拉伸。
- panel 的相对大小按动作阶段、信息密度、镜头变化和叙事重要性自适应：建立镜头、决定性动作或关键结果可以放大，过渡与反应镜头可以缩小；放大或缩小时仍保持单格 {panel_ratio}，不要默认生成等宽等高的固定 2×2。
- 如推荐容量未填满，保留整洁留白或把关键 panel 按同一 {panel_ratio} 成比例放大；不得新增重复画格凑数，也不得改变已有 panel 的 {panel_ratio} 比例。
- panel 共同覆盖正文中的知识目的、关键动作、可见证据、对白/旁白/画面文字、场景切换和镜头关系，不得新增、删减或改写脚本事实。
- 每格必须明确景别、角度、主体位置、动作阶段和结束状态；关键人物、动作、持物与证据完整可见，避免严重裁切、遮挡和竖屏安全区错误。
- 关键动作按“起始—推进—结束”分配到连续画格，动作方向、受力、角色反应、运镜路径与转场节奏清楚可读。
- 相邻 panel 以及前后 Video Unit 的角色外形、身体比例、服装、持物、朝向、空间轴线、家具/道具位置、光向和起止状态必须连续。
- 每个动作 beat 的入口 panel 描绘动作刚开始的稳定可见状态，不把同一 beat 的完成结果当作入口帧。
- 例如“妹妹追弟弟，弟弟绊倒摔进桂花堆”：入口 panel 是妹妹开始追、弟弟开始逃；摔入花堆只能作为后续发展或结果 panel。
- 使用清楚、简洁、可执行的分镜语言；技术标注必须短且不遮挡主体。不要生成大段正文、品牌、水印、页眉装饰或无关元素。
{review_block}
"""


def _load_unit(project_name: str, script_file: str, unit_id: str) -> tuple[dict, dict, dict]:
    pm = get_project_manager()
    project = pm.load_project(project_name)
    script = pm.load_script(project_name, script_file)
    unit = next(
        (
            candidate
            for candidate in script.get("video_units") or []
            if isinstance(candidate, dict) and candidate.get("unit_id") == unit_id
        ),
        None,
    )
    if unit is None:
        raise StoryboardSheetGateError("ref_unit_not_found", unit_id=unit_id)
    return project, script, unit


def _unit_storyboard_basis(unit: dict[str, Any]) -> tuple[object, object, object]:
    """Storyboard provenance is the formal manuscript, never sibling Keyframes."""

    return unit.get("text"), unit.get("duration_seconds"), _storyboard_description(unit)


def _assert_unit_unchanged(
    project_name: str, script_file: str, unit_id: str, expected_basis: tuple[object, object, object]
) -> None:
    _project, _script, unit = _load_unit(project_name, script_file, unit_id)
    if _unit_storyboard_basis(unit) != expected_basis:
        raise StoryboardSheetGateError("reference_storyboard_sheet_input_changed", unit_id=unit_id)


def _commit_sheet_pointer(
    project_name: str,
    script_file: str,
    unit_id: str,
    expected_basis: tuple[object, object, object],
    image_path: str,
) -> None:
    pm = get_project_manager()
    with pm.locked_script(project_name, script_file, validate=False) as script:
        unit = next(
            (
                candidate
                for candidate in script.get("video_units") or []
                if isinstance(candidate, dict) and candidate.get("unit_id") == unit_id
            ),
            None,
        )
        if unit is None:
            raise StoryboardSheetGateError("ref_unit_not_found", unit_id=unit_id)
        if _unit_storyboard_basis(unit) != expected_basis:
            raise StoryboardSheetGateError("reference_storyboard_sheet_input_changed", unit_id=unit_id)
        unit["storyboard_sheet"] = {
            "image_path": image_path,
            "status": "pending_review",
            "confirmed_at": None,
            "generation_input_changed": False,
        }


async def execute_reference_storyboard_sheet_task(
    project_name: str,
    resource_id: str,
    payload: dict[str, Any],
    *,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    del task_id
    script_file = str(payload.get("script_file") or "").strip()
    if not script_file:
        raise ValueError("script_file is required for reference_storyboard_sheet task")
    project, _script, unit = await asyncio.to_thread(_load_unit, project_name, script_file, resource_id)
    expected_basis = deepcopy(_unit_storyboard_basis(unit))
    project_path = get_project_manager().get_project_path(project_name)
    visual_reference_text = f"{str(unit.get('text') or '').strip()}\n{_storyboard_description(unit)}"
    resolved = await asyncio.to_thread(
        resolve_reference_assets,
        project,
        project_path,
        {"text": visual_reference_text, "keyframes": []},
    )
    assets = tuple(asset for asset in resolved if asset.reference.type not in {"keyframe", "storyboard_sheet"})
    bindings = bind_resolved_assets(assets)
    frozen = freeze_image_references(provider_inputs(bindings), visual_references(bindings, role="storyboard_subject"))
    try:
        ctx = await resolve_generation_context(
            project_name,
            payload,
            project=project,
            user_id=user_id,
            image=ImageLaneRequest(
                capability="i2i" if bindings else "t2i",
                stage="storyboard",
            ),
        )
        panel_ratio = resolve_video_aspect_ratio(project)
        count = _panel_count(unit)

        async def _before_submit() -> None:
            await asyncio.to_thread(_assert_unit_unchanged, project_name, script_file, resource_id, expected_basis)

        image_path = resource_relative_path("storyboard_sheets", resource_id)
        _output, version = await ctx.generator.generate_image_async(
            prompt=build_storyboard_sheet_prompt(
                project,
                unit,
                panel_ratio=panel_ratio,
                panel_count=count,
                reference_roster=prompt_roster(bindings),
                instructions=str(payload.get("storyboard_instructions") or "").strip() or None,
            ),
            resource_type="storyboard_sheets",
            resource_id=resource_id,
            reference_images=frozen.reference_images,
            aspect_ratio=_sheet_aspect_ratio(panel_ratio, count),
            image_size=None,
            before_submit=_before_submit,
            source="reference_storyboard_sheet",
            script_file=script_file,
            panel_aspect_ratio=panel_ratio,
            panel_count=count,
            postprocess_output=normalize_storyboard_sheet_monochrome,
            monochrome_postprocessed=True,
        )
    finally:
        await asyncio.to_thread(frozen.cleanup)
    await asyncio.to_thread(
        _commit_sheet_pointer,
        project_name,
        script_file,
        resource_id,
        expected_basis,
        image_path,
    )
    return {
        "version": version,
        "file_path": image_path,
        "resource_type": "storyboard_sheets",
        "resource_id": resource_id,
    }


def require_storyboard_sheet(unit: dict[str, Any]) -> dict[str, Any]:
    """Require the sibling Storyboard image; no confirmation gate exists."""

    sheet = unit.get("storyboard_sheet")
    if not isinstance(sheet, dict) or not str(sheet.get("image_path") or "").strip():
        raise StoryboardSheetGateError("reference_storyboard_sheet_required", unit_id=str(unit.get("unit_id") or ""))
    return sheet


def require_formal_keyframes(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """Require the keyframes derived from the formal Video Unit manuscript."""

    keyframes = [
        item
        for item in unit.get("keyframes") or []
        if isinstance(item, dict)
        and isinstance(item.get("keyframe_id"), str)
        and str(item.get("keyframe_id")).strip()
        and str(item.get("description") or "").strip()
    ]
    if not keyframes:
        raise StoryboardSheetGateError("reference_keyframes_required", unit_id=str(unit.get("unit_id") or ""))
    return keyframes


def require_generated_keyframes(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """Require every planned keyframe to have an activated image pointer."""

    keyframes = require_formal_keyframes(unit)
    missing_ids = [
        str(item.get("keyframe_id") or "")
        for item in keyframes
        if not str(item.get("image_path") or "").strip()
    ]
    if missing_ids:
        raise StoryboardSheetGateError(
            "reference_keyframe_images_required",
            unit_id=str(unit.get("unit_id") or ""),
            keyframe_ids=", ".join(missing_ids),
        )
    return keyframes


async def confirm_storyboard_sheet(
    project_name: str,
    script_file: str,
    unit_id: str,
    *,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """Confirm the current Sheet without coupling it to sibling Keyframe generation."""

    del user_id
    project, _script, unit = await asyncio.to_thread(_load_unit, project_name, script_file, unit_id)
    formal_keyframes = require_formal_keyframes(unit)
    sheet = unit.get("storyboard_sheet")
    if not isinstance(sheet, dict) or not str(sheet.get("image_path") or "").strip():
        raise StoryboardSheetGateError("reference_storyboard_sheet_required", unit_id=unit_id)
    project_path = get_project_manager().get_project_path(project_name)
    try:
        sheet_path = safe_join(project_path, str(sheet["image_path"]), require_file=True)
    except (FileNotFoundError, PathTraversalError):
        raise StoryboardSheetGateError("reference_storyboard_sheet_required", unit_id=unit_id) from None
    if not sheet_path.is_file():
        raise StoryboardSheetGateError("reference_storyboard_sheet_required", unit_id=unit_id)

    candidate = deepcopy(unit)
    candidate["storyboard_sheet"]["status"] = "confirmed"
    available = [asset for asset in resolve_reference_assets(project, project_path, candidate) if asset.path.is_file()]
    non_keyframe_count = sum(asset.reference.type != "keyframe" for asset in available)
    projected_reference_count = non_keyframe_count + len(formal_keyframes)
    caps = await project_video_caps(project, degraded_to="分镜版只校验可解析的参考图上限")
    max_references = caps.get("max_reference_images")
    if isinstance(max_references, int) and projected_reference_count > max_references:
        raise StoryboardSheetGateError(
            "reference_storyboard_sheet_reference_limit",
            unit_id=unit_id,
            count=projected_reference_count,
            max_count=max_references,
        )

    confirmed_at = datetime.now(UTC).isoformat()
    pm = get_project_manager()
    with pm.locked_script(project_name, script_file, validate=False) as current:
        current_unit = next(
            (
                item
                for item in current.get("video_units") or []
                if isinstance(item, dict) and item.get("unit_id") == unit_id
            ),
            None,
        )
        if current_unit is None or current_unit.get("storyboard_sheet") != sheet:
            raise StoryboardSheetGateError("reference_storyboard_sheet_changed", unit_id=unit_id)
        current_unit["storyboard_sheet"]["status"] = "confirmed"
        current_unit["storyboard_sheet"]["confirmed_at"] = confirmed_at
        confirmed_unit = deepcopy(current_unit)
    return confirmed_unit["storyboard_sheet"]


__all__ = [
    "StoryboardSheetGateError",
    "build_storyboard_sheet_prompt",
    "confirm_storyboard_sheet",
    "execute_reference_storyboard_sheet_task",
    "reference_storyboard_sheet_task_specs",
    "require_storyboard_sheet",
    "require_generated_keyframes",
    "require_formal_keyframes",
]
