"""Lossless-layout contact sheets for provider reference-image limits.

The source images are never cropped.  Each tile is scaled with ``contain`` into
an aspect-preserving row slot, and the asset label is overlaid at bottom-right.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont, ImageOps

MAX_COLLAGE_EDGE: Final = 2048
COLLAGE_GAP: Final = 4

_FONT_CANDIDATES: Final = (
    # Optional deployment override comes first.
    "ARCREEL_CJK_FONT_PATH",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Common Linux images
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


@dataclass(frozen=True, slots=True)
class ReferenceCollageItem:
    path: Path
    label: str


def _font_path() -> str:
    for candidate in _FONT_CANDIDATES:
        value = os.environ.get(candidate) if candidate == "ARCREEL_CJK_FONT_PATH" else candidate
        if value and Path(value).is_file():
            return value
    # Pillow ships DejaVu Sans on normal installations.  It is the last-resort
    # fallback for Latin asset names; production packages should include one of
    # the CJK candidates above for Chinese labels.
    return "DejaVuSans.ttf"


def _balanced_rows(count: int) -> tuple[int, ...]:
    """Return compact landscape row sizes without leaving a one-item tail."""

    rows = max(1, round(math.sqrt(count / 1.9)))
    rows = min(rows, count)
    base, extra = divmod(count, rows)
    return tuple(base + (1 if index < extra else 0) for index in range(rows))


def _load_source(item: ReferenceCollageItem) -> Image.Image:
    with Image.open(item.path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    if image.width <= 0 or image.height <= 0:
        raise ValueError(f"reference image has invalid dimensions: {item.path}")
    return image


def _fit_font(draw: ImageDraw.ImageDraw, label: str, max_width: int, preferred_size: int) -> ImageFont.FreeTypeFont:
    font_path = _font_path()
    size = max(16, preferred_size)
    while size > 16:
        font = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), label, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, 16)


def _draw_bottom_right_label(canvas: Image.Image, box: tuple[int, int, int, int], label: str) -> None:
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(canvas, "RGBA")
    edge = max(6, min(12, min(x1 - x0, y1 - y0) // 30))
    padding_x = max(8, edge + 4)
    padding_y = max(6, edge - 2)
    available = max(16, (x1 - x0) - edge * 2 - padding_x * 2)
    preferred = max(24, min(48, round(min(x1 - x0, y1 - y0) * 0.075)))
    font = _fit_font(draw, label, available, preferred)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    text_width = right - left
    text_height = bottom - top
    tag_right = x1 - edge
    tag_bottom = y1 - edge
    tag_left = max(x0 + edge, tag_right - text_width - padding_x * 2)
    tag_top = max(y0 + edge, tag_bottom - text_height - padding_y * 2)
    draw.rounded_rectangle(
        (tag_left, tag_top, tag_right, tag_bottom),
        radius=max(5, edge - 2),
        fill=(12, 15, 18, 205),
        outline=(255, 255, 255, 145),
        width=2,
    )
    draw.text(
        (tag_left + padding_x, tag_top + padding_y - top),
        label,
        font=font,
        fill=(255, 255, 255, 255),
    )


def render_reference_collage(
    items: list[ReferenceCollageItem],
    output_path: Path,
    *,
    max_edge: int = MAX_COLLAGE_EDGE,
    gap: int = COLLAGE_GAP,
) -> Path:
    """Render a dense contact sheet while preserving every source image in full."""

    if not items:
        raise ValueError("reference collage requires at least one image")
    if max_edge < 64 or gap < 0:
        raise ValueError("invalid reference collage dimensions")

    sources = [_load_source(item) for item in items]
    try:
        row_counts = _balanced_rows(len(items))
        rows: list[list[tuple[ReferenceCollageItem, Image.Image, float]]] = []
        cursor = 0
        for count in row_counts:
            row: list[tuple[ReferenceCollageItem, Image.Image, float]] = []
            for item, image in zip(items[cursor : cursor + count], sources[cursor : cursor + count], strict=True):
                # Extreme panoramas/strips do not get to consume the whole row;
                # clamping only changes their slot and adds letterboxing, never cropping.
                aspect = min(3.0, max(0.4, image.width / image.height))
                row.append((item, image, aspect))
            rows.append(row)
            cursor += count

        row_heights = [
            max(1, round((max_edge - gap * (len(row) - 1)) / sum(entry[2] for entry in row))) for row in rows
        ]
        scale = min(1.0, (max_edge - gap * (len(rows) - 1)) / max(1, sum(row_heights)))
        canvas_width = max(64, round(max_edge * scale))

        # Recompute against the final width so rows end exactly at the right edge.
        row_heights = [
            max(1, round((canvas_width - gap * (len(row) - 1)) / sum(entry[2] for entry in row))) for row in rows
        ]
        canvas_height = sum(row_heights) + gap * (len(rows) - 1)
        if canvas_height > max_edge:
            ratio = max_edge / canvas_height
            canvas_width = max(64, round(canvas_width * ratio))
            row_heights = [
                max(1, round((canvas_width - gap * (len(row) - 1)) / sum(entry[2] for entry in row))) for row in rows
            ]
            canvas_height = sum(row_heights) + gap * (len(rows) - 1)

        canvas = Image.new("RGB", (canvas_width, canvas_height), (18, 18, 18))
        y = 0
        for row, row_height in zip(rows, row_heights, strict=True):
            available_width = canvas_width - gap * (len(row) - 1)
            raw_widths = [row_height * entry[2] for entry in row]
            raw_total = sum(raw_widths)
            widths = [max(1, round(available_width * width / raw_total)) for width in raw_widths]
            widths[-1] += available_width - sum(widths)
            x = 0
            for (item, source, _aspect), width in zip(row, widths, strict=True):
                tile = Image.new("RGB", (width, row_height), (242, 242, 242))
                contained = ImageOps.contain(source, (width, row_height), Image.Resampling.LANCZOS)
                paste_x = (width - contained.width) // 2
                paste_y = (row_height - contained.height) // 2
                tile.paste(contained, (paste_x, paste_y))
                canvas.paste(tile, (x, y))
                _draw_bottom_right_label(canvas, (x, y, x + width, y + row_height), item.label)
                x += width + gap
            y += row_height + gap

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path, format="PNG", optimize=True)
        return output_path
    finally:
        for image in sources:
            image.close()


__all__ = [
    "COLLAGE_GAP",
    "MAX_COLLAGE_EDGE",
    "ReferenceCollageItem",
    "render_reference_collage",
]
