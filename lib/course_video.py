"""Course-video structure, dependency and lecturer-overlay primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from lib.path_safety import safe_join

COURSE_UNIT_TYPES = frozenset({"opening", "story", "explanation", "closing"})
COURSE_CHARACTER_ROLES = frozenset({"actor", "main_lecturer", "guest_lecturer"})
LECTURER_PORTRAIT_FIELD = "lecturer_portrait"
COURSE_ROLE_FIELD = "course_role"


def derive_course_dependencies(units: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return units with explanation dependencies recomputed from canonical order.

    A story starts a new chain. The first explanation depends on that story and
    every consecutive explanation depends on the previous explanation.
    """

    result: list[dict[str, Any]] = []
    chain_tail: str | None = None
    story_seen = False
    for raw in units:
        unit = dict(raw)
        unit_type = unit.get("unit_type", "story")
        unit_id = str(unit.get("unit_id") or "")
        if unit_type == "story":
            story_seen = True
            chain_tail = unit_id
            unit["depends_on_unit_id"] = None
        elif unit_type == "explanation":
            if not story_seen or not chain_tail:
                raise ValueError(f"explanation unit {unit_id or '<missing>'} must follow a story unit")
            unit["depends_on_unit_id"] = chain_tail
            chain_tail = unit_id
        else:
            unit["depends_on_unit_id"] = None
        result.append(unit)
    return result


def validate_course_assets(project: Mapping[str, Any]) -> None:
    """Validate lecturer roles once asset inventory has been reviewed."""

    characters = project.get("characters")
    if not isinstance(characters, Mapping):
        raise ValueError("course project characters must be an object")
    mains = [
        name
        for name, entry in characters.items()
        if isinstance(entry, Mapping) and entry.get(COURSE_ROLE_FIELD) == "main_lecturer"
    ]
    if len(mains) != 1:
        raise ValueError(f"course project requires exactly one main lecturer, found {len(mains)}")
    for name, entry in characters.items():
        if not isinstance(entry, Mapping):
            continue
        role = entry.get(COURSE_ROLE_FIELD, "actor")
        if role not in COURSE_CHARACTER_ROLES:
            raise ValueError(f"character {name!r} has invalid course_role {role!r}")


def validate_opening_closing(units: Sequence[Mapping[str, Any]]) -> None:
    if not units:
        raise ValueError("course video units cannot be empty")
    opening, closing = units[0], units[-1]
    if opening.get("unit_type") != "opening" or closing.get("unit_type") != "closing":
        raise ValueError("course video must start with opening and end with closing")
    opening_scenes = list(opening.get("scenes") or [])
    closing_scenes = list(closing.get("scenes") or [])
    if len(opening_scenes) != 1 or opening_scenes != closing_scenes:
        raise ValueError("opening and closing must share exactly one background scene")
    opening_people = {*(opening.get("characters") or []), *(opening.get("presenters") or [])}
    closing_people = {*(closing.get("characters") or []), *(closing.get("presenters") or [])}
    if not opening_people or opening_people != closing_people:
        raise ValueError("opening and closing must share the same non-empty character set")


def lecturer_portrait_path(project_dir: Path, name: str, entry: Mapping[str, Any]) -> Path:
    derived = f"characters/lecturers/{name}.png"
    raw = entry.get(LECTURER_PORTRAIT_FIELD)
    if not raw:
        derived_path = safe_join(project_dir, derived)
        if derived_path.is_file():
            return derived_path
    raw = raw or entry.get("character_sheet") or entry.get("reference_image")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"lecturer {name!r} has no square portrait or character image")
    return safe_join(project_dir, raw, require_file=True)


def materialize_square_lecturer_portrait(
    project_dir: Path,
    name: str,
    entry: Mapping[str, Any],
    *,
    size: int = 1024,
) -> str:
    """Create the reusable 1:1 lecturer image from the selected character image."""

    source = lecturer_portrait_path(project_dir, name, {**entry, LECTURER_PORTRAIT_FIELD: None})
    relative = f"characters/lecturers/{name}.png"
    destination = safe_join(project_dir, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        square = ImageOps.fit(image.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
        square.save(destination, format="PNG")
    return relative


def compose_explanation_keyframe(
    *,
    project_dir: Path,
    tail_frame: Path,
    presenter_names: Sequence[str],
    characters: Mapping[str, Any],
    unit_id: str,
) -> str:
    """Overlay one square lecturer panel at bottom-right of a predecessor tail frame."""

    if not presenter_names:
        raise ValueError(f"explanation unit {unit_id} requires at least one presenter")
    with Image.open(tail_frame) as base_input:
        base = base_input.convert("RGBA")
    short_side = min(base.size)
    panel_size = max(160, round(short_side * 0.28))
    margin = max(16, round(short_side * 0.025))
    border = max(4, round(panel_size * 0.018))
    panel = Image.new("RGBA", (panel_size, panel_size), (16, 20, 24, 238))

    portraits: list[Image.Image] = []
    for name in presenter_names:
        entry = characters.get(name)
        if not isinstance(entry, Mapping):
            raise ValueError(f"presenter {name!r} is not a registered character")
        if not entry.get(LECTURER_PORTRAIT_FIELD):
            materialize_square_lecturer_portrait(project_dir, name, entry)
        path = lecturer_portrait_path(project_dir, name, entry)
        with Image.open(path) as image:
            portraits.append(image.convert("RGBA").copy())
    cell_width = panel_size // len(portraits)
    for index, portrait in enumerate(portraits):
        fitted = ImageOps.fit(
            portrait,
            (cell_width, panel_size),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.35),
        )
        panel.alpha_composite(fitted, (index * cell_width, 0))
    bordered = ImageOps.expand(panel, border=border, fill=(238, 187, 83, 255))
    x = base.width - bordered.width - margin
    y = base.height - bordered.height - margin
    base.alpha_composite(bordered, (x, y))

    relative = f"keyframes/course/{unit_id}_composite.png"
    destination = safe_join(project_dir, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(destination, format="PNG")
    return relative


__all__ = [
    "COURSE_CHARACTER_ROLES",
    "COURSE_ROLE_FIELD",
    "COURSE_UNIT_TYPES",
    "LECTURER_PORTRAIT_FIELD",
    "compose_explanation_keyframe",
    "derive_course_dependencies",
    "materialize_square_lecturer_portrait",
    "validate_course_assets",
    "validate_opening_closing",
]
