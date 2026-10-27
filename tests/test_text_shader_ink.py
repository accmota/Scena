"""
Shader ink on Text (a Gradient / Texture ``fill`` or ``line``) draws from the
glyph atlas, in the material frame a Shape of the same box has.

Shader text used to be drawn as glyph outlines: a ``skia.Path`` filled and
stroked every frame, and a multi-line text rebuilt that path every frame
(~1 ms for Ring Guardian's 7-line story). The story screen with a gradient
and an outline ran at 125 fps against 274 plain (2026-10-27). It now draws
like solid text, with the material re-anchored on the paint
(``uiwidget._paint_for_upright_string``). That helper composed its local
matrix in the wrong order and shifted the material by twice the baseline
height; nothing passed it a shader until then.

Guarded here, in pixels: inside the letters, a shader Text paints what a
Rect of its box with the same material paints there (Gradient, radial
Gradient, Texture, a Texture outline, one line and several, turned 180°,
90° with a scale, -30°); a text typed letter by letter draws as a fresh
Text at every step; and drawing shader text builds no glyph path.

Bug class guarded: a material frame that slips under the y-up flip, a turn
or a scale; a stale layout while the content changes; a regression to
per-frame glyph paths.

Run:

    python tests/run_tiers.py focused test_text_shader_ink
"""
from __future__ import annotations

import contextlib
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

import scena.text as text_mod  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena import Gradient, Rect, Text, Texture  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

boot()
setUpModule, tearDownModule = module_sweep()

FONT = os.path.join(ROOT, "examples", "media", "fonts", "Play-Regular.ttf")
STORY = "You are Captain Arcos, leader\nof the forces of Arr. gjpqy\nShoot everything that moves."


@contextlib.contextmanager
def world():
    """A drawn world on a 1000 x 700 framebuffer, not the headless 2000 x 1200:
    the cost of a frame follows its pixels (WP27, WP50). Design units are
    pixels here, y up from the design height (300): every pose stays inside."""
    fw = ScenaFramework.get_instance()
    with mock.patch.object(fw, "fb_width", 1000), mock.patch.object(fw, "fb_height", 700):
        with system_world(draw=True) as w:
            yield w


def frame(w):
    w.step(1, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3].astype(int)


def ramp_image():
    """Red across, green up: any slip of the frame changes the colour."""
    n = 64
    x = np.linspace(0, 255, n, dtype=np.uint8)
    rgba = np.zeros((n, n, 4), np.uint8)
    rgba[:, :, 0] = x[None, :]
    rgba[:, :, 1] = x[:, None]
    rgba[:, :, 2] = 90
    rgba[:, :, 3] = 255
    return skia.Image.fromarray(rgba, colorType=skia.kRGBA_8888_ColorType)


RAMP = ramp_image()
WHITE = Gradient("white", "white")


def materials():
    return {
        "gradient": lambda: Gradient("red", "blue", angle=-90),
        "gradient across": lambda: Gradient("lime", "magenta"),
        "radial": lambda: Gradient("white", "blue", type="radial"),
        "texture": lambda: Texture(image=RAMP),
    }


# (name, text, font size, angle, scale, center); letters thick enough to
# keep inner pixels once the edge is dropped
POSES = [
    ("one line", "RING GUARDIAN gjq", 60, 0, 1.0, (300, 200)),
    ("one line turned 180", "UPSIDE gjq", 50, 180, 1.0, (300, 200)),
    ("one line turned 90, scaled", "SIDEWAYS", 40, 90, 1.4, (300, 0)),
    ("lines", STORY, 44, 0, 1.0, (450, 100)),
    ("lines turned -30", STORY, 44, -30, 1.0, (450, 0)),
]


def make_text(content, size, angle, scale, center, **paint):
    t = Text(content, center=center, font=FONT, font_size=size)
    for k, v in paint.items():
        setattr(t, k, v)
    if angle:
        t.angle = angle
    if scale != 1.0:
        t.scale = scale
    return t


def box_rect(t, material, angle, scale, center):
    """A Rect of the Text's box with the same material: the frame to match.

    Read after a draw: a one-line shader Text's box becomes its tight ink
    when it is laid out."""
    w = (t._x2 - t._x1) * scale
    h = (t._y2 - t._y1) * scale
    r = Rect(center=center, width=w, height=h)
    r.fill = material
    r.line = None     # ink reaches the box edge, where an outline would paint
    if angle:
        r.angle = angle
    return r


class TestShaderInkFrame(unittest.TestCase):
    """Inside the letters a shader Text paints what its box's Rect paints."""

    def check(self, role, key, make, pose):
        name, content, size, angle, scale, center = pose
        with world() as w:
            if role == "fill":
                mask_paint = dict(fill=WHITE)
                ink_paint = dict(fill=make())
            else:
                mask_paint = dict(fill=None, line=WHITE, line_width=8)
                ink_paint = dict(fill=None, line=make(), line_width=8)
            mask_t = make_text(content, size, angle, scale, center, **mask_paint)
            mask = frame(w).min(axis=2) >= 250
            mask_t.destroy()
            t = make_text(content, size, angle, scale, center, **ink_paint)
            ink = frame(w)
            # A stroke reaches past the box, and an atlas glyph may sit a
            # pixel past its tight ink: compare where the Rect covers too.
            cover = box_rect(t, WHITE, angle, scale, center)
            mask &= frame(w).min(axis=2) >= 250
            cover.destroy()
            # Skia sets glyph edge coverage by the paint's luminance, so white
            # covers an edge pixel more than red does: keep the inner pixels.
            mask[1:] &= mask[:-1].copy()
            mask[:-1] &= mask[1:].copy()
            mask[:, 1:] &= mask[:, :-1].copy()
            mask[:, :-1] &= mask[:, 1:].copy()
            r = box_rect(t, make(), angle, scale, center)
            t.destroy()
            ref = frame(w)
            r.destroy()
        what = f"{role} {key}, {name}"
        ys, xs = np.nonzero(ink.sum(axis=2))
        self.assertTrue(ys.min() > 0 and xs.min() > 0 and ys.max() < ink.shape[0] - 1
                        and xs.max() < ink.shape[1] - 1, f"{what}: the pose leaves the frame")
        self.assertGreater(mask.sum(), 100, f"{what}: no inked pixels")
        diff = np.abs(ink - ref).max(axis=2)[mask]
        self.assertLessEqual(int(np.percentile(diff, 99)), 6, f"{what}: p99 {np.percentile(diff, 99)}")
        self.assertLessEqual(float(diff.mean()), 1.5, f"{what}: mean {diff.mean():.2f}")

    def test_fill_materials_in_every_pose(self):
        for key, make in materials().items():
            for pose in POSES:
                with self.subTest(material=key, pose=pose[0]):
                    self.check("fill", key, make, pose)

    def test_texture_and_gradient_outlines(self):
        mats = materials()
        for key in ("texture", "gradient"):
            for pose in (POSES[0], POSES[1], POSES[3]):
                with self.subTest(material=key, pose=pose[0]):
                    self.check("line", key, mats[key], pose)


class TestTypedShaderText(unittest.TestCase):
    """A text typed letter by letter draws as a fresh Text at every step."""

    def typed_matches_fresh(self, full, place, step):
        def paint(t):
            t.fill = Gradient("gold", "orange red", angle=-90)
            t.line = "black"
            return t
        bad = []
        with world() as w:
            typed = paint(Text("", font=FONT, font_size=26, **place))
            for n in range(0, len(full) + 1, step):
                typed.text = full[:n]
                a = frame(w)
                typed.visible = False
                fresh = paint(Text(full[:n], font=FONT, font_size=26, **place))
                b = frame(w)
                fresh.destroy()
                typed.visible = True
                if np.abs(a - b).max():
                    bad.append(n)
        self.assertEqual(bad, [], "typed steps that differ from a fresh Text")

    def test_lines(self):
        self.typed_matches_fresh(STORY, dict(top_left=(80, 250)), 3)

    def test_one_line(self):
        # One line: the box is the tight ink, so it changes with every letter.
        self.typed_matches_fresh("Shoot everything gjq", dict(center=(300, 200)), 1)


class TestShaderInkDrawsFromTheAtlas(unittest.TestCase):
    """No glyph path is built to draw; one line measures its ink once."""

    def test_no_glyph_paths_while_drawing(self):
        with world() as w:
            lines = make_text(STORY, 26, 0, 1.0, (300, 100), fill=Texture(image=RAMP), line="black")
            one = make_text("RING GUARDIAN", 60, 20, 1.0, (300, 300),
                            fill=Gradient("red", "blue"), line=Gradient("white", "black"))
            frame(w)
            real_build = text_mod.build_upright_text_path
            real_draw = text_mod.draw_string_upright
            with mock.patch.object(text_mod, "build_upright_text_path", side_effect=real_build) as build, \
                    mock.patch.object(text_mod, "draw_string_upright", side_effect=real_draw) as draw:
                for _ in range(3):
                    frame(w)
                self.assertEqual(build.call_count, 0, "glyph paths built for unchanged text")
                self.assertGreater(draw.call_count, 0, "shader text did not draw from the atlas")
                one.text = "RING GUARDIAN 2"
                frame(w)
                frame(w)
                self.assertEqual(build.call_count, 1, "one line measures its new ink once")
            lines.destroy()
            one.destroy()


if __name__ == "__main__":
    unittest.main()
