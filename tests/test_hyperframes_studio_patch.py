"""Version pin and committed shell customization for embedded HyperFrames Studio."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent


def test_frontend_pins_the_customized_hyperframes_version() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    workspace = (ROOT / "frontend" / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    assert package["dependencies"]["hyperframes"] == "0.8.14"
    assert "hyperframes@0.8.14: patches/hyperframes@0.8.14.patch" in workspace


def test_studio_patch_localizes_the_shell_and_removes_the_upstream_logo() -> None:
    patch = (ROOT / "frontend" / "patches" / "hyperframes@0.8.14.patch").read_text(encoding="utf-8")

    assert '<html lang="zh-CN">' in patch
    assert "ArcReel 剪辑器" in patch
    assert 'svg[aria-label="Hyperframes"]' in patch
    assert '"Storyboard": "分镜"' in patch
    assert '"Preview": "预览"' in patch
    assert '"Export": "导出"' in patch
