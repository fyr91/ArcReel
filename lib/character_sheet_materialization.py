"""Project-local Character Sheet materialization from a linked Global Asset."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.path_safety import safe_join


@dataclass(frozen=True, slots=True)
class CharacterSheetMaterialization:
    """One planned Global Asset image copy into a project Character Sheet."""

    sheet_path: str
    source_path: Path
    target_path: Path


def plan_character_sheet_materialization(
    *,
    project_dir: Path,
    projects_root: Path,
    character_name: str,
    entry: dict,
    global_image_path: str | None,
    copies: list[tuple[Path, Path]],
) -> CharacterSheetMaterialization | None:
    """Fill an empty ``character_sheet`` by planning one project-local copy.

    The Global Asset remains immutable. Existing project sheets are authoritative
    and are never overwritten by a link operation.
    """

    current_sheet = entry.get("character_sheet")
    if isinstance(current_sheet, str) and current_sheet:
        return None
    if not isinstance(global_image_path, str) or not global_image_path:
        return None

    source_path = safe_join(projects_root, global_image_path, require_file=True)
    suffix = source_path.suffix.lower() or ".png"
    sheet_path = f"characters/{character_name}{suffix}"
    target_path = safe_join(project_dir, sheet_path)
    if source_path.resolve(strict=False) != target_path.resolve(strict=False):
        copies.append((source_path, target_path))
    entry["character_sheet"] = sheet_path
    return CharacterSheetMaterialization(
        sheet_path=sheet_path,
        source_path=source_path,
        target_path=target_path,
    )


__all__ = ["CharacterSheetMaterialization", "plan_character_sheet_materialization"]
