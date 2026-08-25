"""HyperFrames picture-edit evidence classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.services.hyperframes_editing import analyze_hyperframes_editing

pytestmark = pytest.mark.unit


def _workspace(tmp_path: Path, composition: str) -> Path:
    workspace = tmp_path / "episode_01"
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        json.dumps(
            {
                "units": [
                    {"unit_id": "E1U01", "video": {"duration_microseconds": 2_000_000}},
                    {"unit_id": "E1U02", "video": {"duration_microseconds": 3_000_000}},
                ]
            }
        ),
        encoding="utf-8",
    )
    (workspace / "index.html").write_text(composition, encoding="utf-8")
    return workspace


def test_full_length_sequential_composition_is_only_an_assembly_draft(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        """<div data-composition-id="main" data-duration="5">
        <video data-unit-id="E1U01" data-start="0" data-duration="2" data-track-index="0"></video>
        <audio data-start="0" data-duration="2"></audio>
        <video data-unit-id="E1U02" data-start="2" data-duration="3" data-track-index="0"></video>
        <audio data-start="2" data-duration="3"></audio>
        </div>""",
    )

    analysis = analyze_hyperframes_editing(workspace)

    assert analysis.state == "assembly_draft"
    assert analysis.picture_edit_count == 0
    assert analysis.video_clip_count == 2


def test_source_trim_and_retimed_timeline_are_classified_as_picture_edit(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        """<div data-composition-id="main" data-duration="4.6">
        <video data-unit-id="E1U01" data-start="0" data-duration="1.8" data-media-start="0.2" data-track-index="0"></video>
        <audio data-start="0" data-duration="1.8" data-media-start="0.2"></audio>
        <video data-unit-id="E1U02" data-start="1.8" data-duration="2.8" data-track-index="0"></video>
        <audio data-start="1.8" data-duration="2.8"></audio>
        </div>""",
    )

    analysis = analyze_hyperframes_editing(workspace)

    assert analysis.state == "edited"
    assert analysis.timing_changes == 2
    assert analysis.picture_edit_count >= 2


def test_audio_only_change_does_not_mislabel_assembly_as_picture_edit(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        """<div data-composition-id="main" data-duration="5">
        <video data-unit-id="E1U01" data-start="0" data-duration="2" data-track-index="0"></video>
        <audio data-start="0" data-duration="2" data-automation='{"version":1}'></audio>
        <video data-unit-id="E1U02" data-start="2" data-duration="3" data-track-index="0"></video>
        </div>""",
    )

    analysis = analyze_hyperframes_editing(workspace)

    assert analysis.state == "assembly_draft"
    assert analysis.audio_automations == 1


def test_seek_safe_visual_timeline_is_picture_edit_evidence(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        """<div data-composition-id="main" data-duration="5">
        <video data-unit-id="E1U01" data-start="0" data-duration="2" data-track-index="0"></video>
        <video data-unit-id="E1U02" data-start="2" data-duration="3" data-track-index="0"></video>
        </div><script>const tl = gsap.timeline({paused:true}); window.__timelines.main = tl;</script>""",
    )

    analysis = analyze_hyperframes_editing(workspace)

    assert analysis.state == "edited"
    assert analysis.visual_treatments >= 1


def test_unparseable_composition_is_not_mislabeled_as_an_edit(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "user edit")

    analysis = analyze_hyperframes_editing(workspace)

    assert analysis.state == "unknown"
    assert analysis.video_clip_count == 0
