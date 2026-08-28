"""Project Qwen Image 3 reference assets into at most three labeled collages."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lib.image_reference_collage import ReferenceCollageItem, render_reference_collage
from lib.image_reference_snapshot import FrozenImageReferences, freeze_image_references
from lib.visual_artifact_provenance import VisualReference
from server.services.reference_image_binding import (
    BoundImageReference,
    prompt_roster,
    provider_inputs,
    visual_references,
)

_QWEN_IMAGE_3_MODELS: Final = frozenset({"qwen-image-3.0", "qwen-image-3.0-pro"})
_CATEGORY_ORDER: Final = ("character", "prop", "scene")
_CATEGORY_LABEL: Final = {
    "character": "角色",
    "prop": "道具与商品",
    "scene": "场景",
}


@dataclass(frozen=True, slots=True)
class PreparedImageReferences:
    reference_images: list[object] | None
    reference_roster: str
    visual_references: tuple[VisualReference, ...]
    _frozen: FrozenImageReferences
    _collage_directory: Path | None = None

    def cleanup(self) -> None:
        if self._collage_directory is not None:
            shutil.rmtree(self._collage_directory, ignore_errors=True)
        self._frozen.cleanup()


def is_qwen_image_3(provider_id: str, model_id: str) -> bool:
    return provider_id == "dashscope" and model_id.lower() in _QWEN_IMAGE_3_MODELS


def _category(logical_type: str) -> str:
    if logical_type == "character":
        return "character"
    if logical_type == "scene":
        return "scene"
    # Products share the prop collage so the provider request remains bounded to
    # the three semantic sheets promised by this projection.
    return "prop"


def _labels_for_group(bindings: list[BoundImageReference]) -> list[str]:
    totals: dict[str, int] = {}
    for binding in bindings:
        totals[binding.logical_id] = totals.get(binding.logical_id, 0) + 1
    seen: dict[str, int] = {}
    labels: list[str] = []
    for binding in bindings:
        name = binding.logical_id
        seen[name] = seen.get(name, 0) + 1
        labels.append(name if totals[name] == 1 else f"{name} · {seen[name]}")
    return labels


def prepare_qwen_image_references(
    bindings: tuple[BoundImageReference, ...],
    *,
    provider_id: str,
    model_id: str,
    role: str,
) -> PreparedImageReferences:
    """Freeze inputs and collapse Qwen Image 3 requests over its three-image cap."""

    frozen = freeze_image_references(
        provider_inputs(bindings),
        visual_references(bindings, role=role),
    )
    if not is_qwen_image_3(provider_id, model_id) or len(bindings) <= 3:
        return PreparedImageReferences(
            reference_images=frozen.reference_images,
            reference_roster=prompt_roster(bindings),
            visual_references=frozen.visual_references,
            _frozen=frozen,
        )

    collage_directory = Path(tempfile.mkdtemp(prefix="arcreel-qwen-reference-collages-"))
    try:
        frozen_paths = [reference["image"] for reference in frozen.reference_images or []]
        grouped: dict[str, list[tuple[BoundImageReference, Path]]] = {key: [] for key in _CATEGORY_ORDER}
        for binding, raw_path in zip(bindings, frozen_paths, strict=True):
            grouped[_category(binding.logical_type)].append((binding, Path(raw_path)))

        projected_images: list[object] = []
        roster: list[str] = []
        picture_index = 1
        for category in _CATEGORY_ORDER:
            entries = grouped[category]
            if not entries:
                continue
            category_bindings = [entry[0] for entry in entries]
            labels = _labels_for_group(category_bindings)
            path = collage_directory / f"{picture_index:02d}-{category}.png"
            render_reference_collage(
                [
                    ReferenceCollageItem(path=entry[1], label=label)
                    for entry, label in zip(entries, labels, strict=True)
                ],
                path,
            )
            names = "、".join(f"@[{binding.logical_id}]" for binding in category_bindings)
            label = (
                f"Picture {picture_index} = {_CATEGORY_LABEL[category]}参考拼接图；"
                f"每个完整子图的右下角名称用于身份绑定：{names}"
            )
            projected_images.append({"image": path, "label": label})
            roster.append(f"- {label}")
            picture_index += 1

        if len(projected_images) > 3:
            raise RuntimeError("Qwen Image 3 reference collage projection exceeded three images")
        return PreparedImageReferences(
            reference_images=projected_images,
            reference_roster="\n".join(roster),
            visual_references=frozen.visual_references,
            _frozen=frozen,
            _collage_directory=collage_directory,
        )
    except BaseException:
        shutil.rmtree(collage_directory, ignore_errors=True)
        frozen.cleanup()
        raise


__all__ = [
    "PreparedImageReferences",
    "is_qwen_image_3",
    "prepare_qwen_image_references",
]
