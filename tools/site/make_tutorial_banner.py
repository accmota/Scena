"""The picture at the top of the tutorial index: docs/assets/tutorial/banner.webp.

Six games the tutorials build, one frame each from the README's clips, in a
3 × 2 grid with the tutorial's number in the corner. No words, so both indexes
(pt and en) share it. Run it again when those clips change:

    python tools/site/make_tutorial_banner.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = Path(__file__).resolve().parent.parent.parent
README = REPO / "docs" / "assets" / "readme"
FONTS = REPO / "examples" / "media" / "fonts"
OUT = REPO / "docs" / "assets" / "tutorial" / "banner.webp"

BG = (25, 28, 36)          # tutorial.css --bg
BADGE = (18, 21, 27)       # --bg-code
ACCENT = (126, 182, 196)   # --accent
# (tutorial, clip, frame, where the crop sits from top 0 to bottom 1, zoom).
# Zoom scales the frame past "just covers the tile": above 1 it trims a HUD
# or the clip's file label at the edge; below 1 it keeps the whole height
# (the ship and the fleet) over a blurred copy of the frame that covers the tile.
TILES = [
    ("08", "ships_shield.webp", 200, 0.5, 0.78),
    ("17", "plane_landscape.webp", 140, 1.0, 1.08),
    ("21", "connect_four.webp", 152, 0.5, 1.0),
    ("27", "ninja_hazards.webp", 108, 0.75, 1.0),
    ("31", "more_examples.webp", 200, 0.4, 1.12),
    ("32", "race.webp", 250, 0.5, 1.0),
]
COLS, TILE_W, TILE_H, GAP = 3, 416, 260, 16
W = COLS * TILE_W + (COLS - 1) * GAP
H = 2 * TILE_H + GAP


def tile(name: str, index: int, anchor: float, zoom: float) -> Image.Image:
    """The frame scaled to cover the tile (times ``zoom``), cropped around ``anchor``."""
    im = Image.open(README / name)
    im.seek(index)
    im = im.convert("RGB")
    cover = max(TILE_W / im.width, TILE_H / im.height)
    scale = cover * zoom
    small = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    if small.width < TILE_W or small.height < TILE_H:
        back = im.resize((round(im.width * cover), round(im.height * cover)), Image.LANCZOS)
        back = back.filter(ImageFilter.GaussianBlur(24))
        back.paste(small, ((back.width - small.width) // 2, (back.height - small.height) // 2))
        small = back
    im = small
    x = (im.width - TILE_W) // 2
    y = round((im.height - TILE_H) * anchor)
    return im.crop((x, y, x + TILE_W, y + TILE_H))


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    font = ImageFont.truetype(str(FONTS / "JetBrainsMonoNLNerdFontMono-Bold.ttf"), 28)
    for k, (num, name, index, anchor, zoom) in enumerate(TILES):
        x = (k % COLS) * (TILE_W + GAP)
        y = (k // COLS) * (TILE_H + GAP)
        mask = Image.new("L", (TILE_W, TILE_H), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, TILE_W - 1, TILE_H - 1), 14, fill=255)
        img.paste(tile(name, index, anchor, zoom), (x, y), mask)
        draw = ImageDraw.Draw(img)
        left, top, right, bottom = draw.textbbox((0, 0), num, font=font)
        bx, by = x + 12, y + TILE_H - 12 - (bottom - top) - 12
        draw.rounded_rectangle((bx, by, bx + right - left + 20, by + bottom - top + 12), 8, fill=BADGE)
        draw.text((bx + 10 - left, by + 6 - top), num, font=font, fill=ACCENT)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, quality=82, method=6)
    print(f"{OUT.relative_to(REPO)} {W}×{H} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
