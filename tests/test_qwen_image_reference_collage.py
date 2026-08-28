from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from lib.image_reference_collage import ReferenceCollageItem, render_reference_collage
from server.services.qwen_image_reference_collage import (
    is_qwen_image_3,
    prepare_qwen_image_references,
)
from server.services.reference_image_binding import BoundImageReference

pytestmark = pytest.mark.unit


def _image(path: Path, *, size: tuple[int, int] = (320, 180), color: str = "white") -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _binding(path: Path, name: str, logical_type: str) -> BoundImageReference:
    return BoundImageReference(
        path=path,
        label=f"@[{name}]",
        logical_type=logical_type,
        logical_id=name,
        kind="sheet",
    )


def test_collage_preserves_every_source_edge_without_cropping(tmp_path: Path) -> None:
    source = tmp_path / "wide.png"
    image = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 39, 39), fill="red")
    draw.rectangle((360, 0, 399, 39), fill="blue")
    draw.rectangle((0, 60, 39, 99), fill="green")
    draw.rectangle((360, 60, 399, 99), fill="yellow")
    image.save(source)

    output = render_reference_collage(
        [ReferenceCollageItem(source, "wide")],
        tmp_path / "collage.png",
        max_edge=512,
    )

    with Image.open(output) as rendered:
        colors = rendered.convert("RGB").getcolors(maxcolors=rendered.width * rendered.height)
        assert max(rendered.size) <= 512
        assert colors is not None
        palette = {color for _count, color in colors}
        # All four source corners remain visible. A crop-to-fill layout would
        # remove at least the left/right corner markers from this 4:1 source.
        assert any(r > 200 and g < 80 and b < 80 for r, g, b in palette)
        assert any(b > 150 and r < 100 for r, g, b in palette)
        assert any(g > 80 and r < 100 and b < 100 for r, g, b in palette)
        assert any(r > 180 and g > 150 and b < 100 for r, g, b in palette)


def test_collage_places_readable_label_overlay_at_bottom_right(tmp_path: Path) -> None:
    output = render_reference_collage(
        [ReferenceCollageItem(_image(tmp_path / "one.png"), "Character A")],
        tmp_path / "collage.png",
        max_edge=512,
    )

    with Image.open(output) as rendered:
        rgb = rendered.convert("RGB")
        assert rgb.getpixel((8, 8)) == (255, 255, 255)
        bottom_right = [
            rgb.getpixel((x, y))
            for x in range(max(0, rgb.width - 180), rgb.width - 4)
            for y in range(max(0, rgb.height - 90), rgb.height - 4)
        ]
        assert any(sum(pixel) < 300 for pixel in bottom_right)


def test_qwen_image_3_projection_groups_character_prop_product_and_scene(tmp_path: Path) -> None:
    bindings = (
        _binding(_image(tmp_path / "a.png", color="red"), "A", "character"),
        _binding(_image(tmp_path / "b.png", color="blue"), "B", "character"),
        _binding(_image(tmp_path / "p.png", color="green"), "P", "prop"),
        _binding(_image(tmp_path / "product.png", color="yellow"), "Product", "product"),
        _binding(_image(tmp_path / "scene.png", color="purple"), "Scene", "scene"),
    )

    prepared = prepare_qwen_image_references(
        bindings,
        provider_id="dashscope",
        model_id="qwen-image-3.0-pro",
        role="storyboard_subject",
    )
    projected_paths = [Path(reference["image"]) for reference in prepared.reference_images or []]
    frozen_paths = [reference.path for reference in prepared.visual_references]
    try:
        assert len(projected_paths) == 3
        assert all(path.is_file() for path in projected_paths)
        for path in projected_paths:
            with Image.open(path) as collage:
                assert max(collage.size) <= 2048
        assert "Picture 1 = 角色参考拼接图" in prepared.reference_roster
        assert "Picture 2 = 道具与商品参考拼接图" in prepared.reference_roster
        assert "@[P]" in prepared.reference_roster
        assert "@[Product]" in prepared.reference_roster
        assert "Picture 3 = 场景参考拼接图" in prepared.reference_roster
    finally:
        prepared.cleanup()

    assert all(not path.exists() for path in projected_paths)
    assert all(not path.exists() for path in frozen_paths)


@pytest.mark.parametrize(
    ("provider_id", "model_id", "expected"),
    [
        ("dashscope", "qwen-image-3.0", True),
        ("dashscope", "qwen-image-3.0-pro", True),
        ("dashscope", "qwen-image-2.0", False),
        ("custom-1", "qwen-image-3.0", False),
    ],
)
def test_qwen_image_3_model_gate(provider_id: str, model_id: str, expected: bool) -> None:
    assert is_qwen_image_3(provider_id, model_id) is expected


def test_projection_keeps_original_inputs_for_other_models(tmp_path: Path) -> None:
    bindings = tuple(_binding(_image(tmp_path / f"{index}.png"), f"Asset {index}", "character") for index in range(4))
    prepared = prepare_qwen_image_references(
        bindings,
        provider_id="runware",
        model_id="google:nano-banana@2-lite",
        role="keyframe_subject",
    )
    paths = [Path(reference["image"]) for reference in prepared.reference_images or []]
    try:
        assert len(paths) == 4
        assert prepared.reference_roster.endswith("- @[Asset 3]")
    finally:
        prepared.cleanup()
    assert all(not path.exists() for path in paths)


def test_qwen_image_3_does_not_collage_three_or_fewer_inputs(tmp_path: Path) -> None:
    bindings = tuple(_binding(_image(tmp_path / f"{index}.png"), f"Asset {index}", "character") for index in range(3))
    prepared = prepare_qwen_image_references(
        bindings,
        provider_id="dashscope",
        model_id="qwen-image-3.0",
        role="keyframe_subject",
    )
    try:
        assert len(prepared.reference_images or []) == 3
        assert "参考拼接图" not in prepared.reference_roster
    finally:
        prepared.cleanup()
