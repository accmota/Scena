"""The link preview image (og:image) of every page: docs/assets/og/scena.png.

1200 × 630, the size link previews use. The name and the tagline on the left;
on the right two frames of the README's clips (the race and the space duel).
Run it again when those clips change:

    python tools/site/make_og_image.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent.parent
README = REPO / "docs" / "assets" / "readme"
FONTS = REPO / "examples" / "media" / "fonts"
OUT = REPO / "docs" / "assets" / "og" / "scena.png"

W, H = 1200, 630
BG = (22, 24, 29)        # the site's --bg
TEXT = (208, 212, 220)   # --text
MUTED = (154, 163, 176)  # --muted
ACCENT = (142, 184, 204)  # --accent
# (clip, frame): a race lap and a duel with the black hole between the ships.
FRAMES = [("race.webp", 250), ("more_examples.webp", 200)]
SHOT_W = 520


def frame(name: str, index: int) -> Image.Image:
    im = Image.open(README / name)
    im.seek(index)
    im = im.convert("RGB")
    return im.resize((SHOT_W, round(im.height * SHOT_W / im.width)), Image.LANCZOS)


def rounded(im: Image.Image, radius: int = 14) -> tuple[Image.Image, Image.Image]:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *im.size), radius, fill=255)
    return im, mask


def main() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    bold = FONTS / "JetBrainsMonoNLNerdFontMono-Bold.ttf"
    regular = FONTS / "JetBrainsMonoNLNerdFontMono-Regular.ttf"

    shots = [frame(n, i) for n, i in FRAMES]
    gap = 18
    y = (H - sum(s.height for s in shots) - gap) // 2
    x = W - SHOT_W - 48
    for s in shots:
        im, mask = rounded(s)
        img.paste(im, (x, y), mask)
        y += s.height + gap

    left = 64
    draw.text((left, 150), "Scena", font=ImageFont.truetype(str(bold), 112), fill=TEXT)
    tag = ImageFont.truetype(str(regular), 36)
    draw.text((left, 300), "2D games and", font=tag, fill=TEXT)
    draw.text((left, 348), "creative graphics", font=tag, fill=TEXT)
    draw.text((left, 396), "in Python", font=tag, fill=TEXT)
    draw.text((left, 490), "pip install scena", font=ImageFont.truetype(str(regular), 28), fill=ACCENT)
    draw.text((left, 534), "built for learning", font=ImageFont.truetype(str(regular), 24), fill=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"{OUT.relative_to(REPO)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
