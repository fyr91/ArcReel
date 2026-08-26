from __future__ import annotations

import pytest

from server.services.reference_storyboard_sheet_tasks import (
    StoryboardSheetGateError,
    _panel_count,
    _sheet_aspect_ratio,
    build_storyboard_sheet_prompt,
    reference_storyboard_sheet_task_specs,
    require_formal_keyframes,
)

pytestmark = pytest.mark.unit


def test_sheet_outer_canvas_is_auto_laid_out_from_panel_ratio() -> None:
    assert _sheet_aspect_ratio("9:16", 6) == "27:32"
    assert _sheet_aspect_ratio("16:9", 6) == "8:3"


def test_panel_count_accounts_for_action_density_not_only_duration() -> None:
    assert _panel_count({"duration_seconds": 5, "text": "爸爸研磨釉料。", "keyframes": []}) == 4
    assert (
        _panel_count(
            {
                "duration_seconds": 5,
                "text": "弟弟奔跑，突然摔倒。镜头切到妹妹，然后回到爸爸；弟弟{哎呀}，妹妹{小心}。",
                "keyframes": [{"description": "弟弟开始奔跑"}],
            }
        )
        == 6
    )


def test_sheet_prompt_preserves_panel_ratio_and_action_progression() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "田园动画", "style_description": "暖色自然光"},
        {
            "unit_id": "E1U01",
            "text": "妹妹追弟弟，弟弟绊倒摔进桂花堆。",
            "keyframes": [{"description": "妹妹开始追弟弟"}],
        },
        panel_ratio="9:16",
        panel_count=6,
        reference_roster="- Picture 1 = @[鳄鱼妹妹]",
    )

    assert "每个单独 panel 的内容框都必须原生采用项目目标比例 9:16" in prompt
    assert "panel 的相对大小按动作阶段、信息密度、镜头变化和叙事重要性自适应" in prompt
    assert "不要默认生成等宽等高的固定 2×2" in prompt
    assert "入口 panel 是妹妹开始追、弟弟开始逃" in prompt
    assert "Picture 1 = @[鳄鱼妹妹]" in prompt


def test_sheet_prompt_uses_only_formal_manuscript_not_keyframe_descriptions() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "景泰蓝科普动画"},
        {
            "unit_id": "E1U14",
            "text": "器物静置在石台上冷却，表面光泽逐渐显现。",
            "duration_seconds": 8,
            "keyframes": [{"keyframe_id": "E1U14K1", "description": "错误旧内容：蒸汽持续升腾"}],
        },
        panel_ratio="9:16",
        panel_count=4,
        reference_roster="无",
    )

    assert "静置在石台上冷却" in prompt
    assert "光泽逐渐显现" in prompt
    assert "蒸汽" not in prompt


def test_sheet_prompt_uses_monochrome_working_drawing_with_adaptive_layout() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "田园暖色动画", "style_description": "暖色自然光、精细材质"},
        {
            "unit_id": "E1U18",
            "text": "妹妹踮脚插花，爸爸揉头。",
            "duration_seconds": 5,
            "keyframes": [{"description": "妹妹踮脚把野花插进瓶口"}],
        },
        panel_ratio="9:16",
        panel_count=5,
        reference_roster="- Picture 1 = @[鳄鱼妹妹]",
    )

    assert "人物、场景、道具和光影只使用黑、白、灰" in prompt
    assert "彩色参考图只能用于身份、造型和空间绑定，必须转译成纯灰阶线稿" in prompt
    assert "只允许技术批注使用少量鲜明的手绘红、蓝、绿、黄" in prompt
    assert "不能给人物、背景、道具或光影上色" in prompt
    assert "3 列 × 2 行" in prompt
    assert "外层比例约为 27:32" in prompt
    assert "每个单独 panel 的内容框都必须原生采用项目目标比例 9:16" in prompt
    assert "不得照搬其他项目的固定画布尺寸" in prompt
    assert "成片风格（仅用于保持角色、时代、场景与设计身份一致" in prompt


def test_sheet_prompt_requires_semantic_nonuniform_time_mapping() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "田园动画"},
        {
            "unit_id": "E1U20",
            "text": "妹妹先观察花瓶，随后小心插花，最后退后确认构图。",
            "duration_seconds": 8,
        },
        panel_ratio="16:9",
        panel_count=4,
        reference_roster="- Picture 1 = @[鳄鱼妹妹]",
    )

    assert "完整播放范围固定为 00:00.000 至 00:08.000" in prompt
    assert "不得按总时长机械等分" in prompt
    assert "所有时间范围必须精确、有序、互不重叠且首尾相接" in prompt
    assert "统一使用 `MM:SS.mmm–MM:SS.mmm`" in prompt
    assert "最后一格必须保留稳定的视觉尾巴" in prompt


def test_sheet_prompt_tracks_physical_state_across_panels() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "田园动画"},
        {
            "unit_id": "E1U21",
            "text": "妹妹伸手拿起花瓶，再把花瓶放回桌面。",
            "duration_seconds": 5,
        },
        panel_ratio="16:9",
        panel_count=4,
        reference_roster="- Picture 1 = @[鳄鱼妹妹]",
    )

    assert "画面位置、前后景深、身体朝向、视线、姿态和运动路径" in prompt
    assert "数量、外观、方向、归属、持有者和支撑方式" in prompt
    assert "手与物体之间必须保留清楚可见的空气间隙" in prompt
    assert "不得跨轴或镜像翻转场景关系" in prompt
    assert "禁止角色、手、身体部位、持物和环境物件在 panel 之间瞬移" in prompt


def test_sheet_prompt_appends_user_authorized_regeneration_instructions() -> None:
    prompt = build_storyboard_sheet_prompt(
        {"style": "田园动画"},
        {"unit_id": "E1U18", "text": "妹妹插花，爸爸揉头。", "keyframes": []},
        panel_ratio="9:16",
        panel_count=4,
        reference_roster="无",
        instructions="第 3 格爸爸不得触碰花；第 4 格画揉头方向箭头。",
    )

    assert "本次重新生成审核意见" in prompt
    assert "第 3 格爸爸不得触碰花；第 4 格画揉头方向箭头。" in prompt
    assert "不得新增、删除或改写脚本事实" in prompt


def test_sheet_specs_keep_request_scoped_model_override() -> None:
    specs = reference_storyboard_sheet_task_specs(
        {"video_units": [{"unit_id": "E1U01", "text": "庭院开场"}]},
        "episode_1.json",
        image_override={"image_provider": "runware", "image_model": "openai:gpt-image@2"},
    )

    assert specs[0].task_type == "reference_storyboard_sheet"
    assert specs[0].payload["image_provider"] == "runware"
    assert specs[0].payload["image_model"] == "openai:gpt-image@2"


def test_keyframe_generation_gate_rejects_missing_formal_keyframes() -> None:
    with pytest.raises(StoryboardSheetGateError) as exc_info:
        require_formal_keyframes({"unit_id": "E1U01", "keyframes": []})

    assert exc_info.value.code == "reference_keyframes_required"
