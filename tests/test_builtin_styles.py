from __future__ import annotations

from pathlib import Path

import pytest

from lib.builtin_styles import BUILTIN_STYLE_SOURCE, BUILTIN_STYLES, sync_builtin_styles
from lib.db.repositories.asset_repo import AssetRepository


@pytest.mark.unit
async def test_sync_creates_bundled_styles_and_is_idempotent(async_session, tmp_path: Path) -> None:
    first = await sync_builtin_styles(async_session, tmp_path)

    assert first == {"added": 2, "promoted": 0, "updated": 0, "unchanged": 0}
    for definition in BUILTIN_STYLES:
        style = await AssetRepository(async_session).get_by_external_identity(
            BUILTIN_STYLE_SOURCE,
            definition.external_id,
        )
        assert style is not None
        assert style.name == definition.name
        assert style.description == definition.description
        assert style.image_path == definition.image_path
        assert (tmp_path / definition.image_path).is_file()

    second = await sync_builtin_styles(async_session, tmp_path)

    assert second == {"added": 0, "promoted": 0, "updated": 0, "unchanged": 2}


@pytest.mark.unit
async def test_sync_promotes_legacy_style_without_changing_its_id(async_session, tmp_path: Path) -> None:
    legacy = await AssetRepository(async_session).create(
        asset_id="legacy-style-id",
        type="style",
        name="鳄鱼爸爸的景泰蓝 · 风格",
        description="legacy",
        image_path="_global_assets/style/legacy.jpg",
        source_project="legacy-project",
    )
    animation = await AssetRepository(async_session).create(
        asset_id="animation-style-id",
        type="style",
        name="3D动画风格",
        description="legacy animation",
        image_path="_global_assets/style/legacy-animation.png",
        source_project="legacy-project",
    )
    await async_session.commit()

    result = await sync_builtin_styles(async_session, tmp_path)

    assert result == {"added": 0, "promoted": 2, "updated": 0, "unchanged": 0}
    promoted = await AssetRepository(async_session).get_by_external_identity(
        BUILTIN_STYLE_SOURCE,
        "ziqi-pastoral",
    )
    assert promoted is not None
    assert promoted.id == legacy.id
    assert promoted.name == "子柒田园风"
    assert promoted.source_project is None

    promoted_animation = await AssetRepository(async_session).get_by_external_identity(
        BUILTIN_STYLE_SOURCE,
        "3d-animation",
    )
    assert promoted_animation is not None
    assert promoted_animation.id == animation.id
    assert promoted_animation.name == "3D动画风格"
    assert promoted_animation.source_project is None
