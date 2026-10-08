"""Guia thumbnails rendered for real (one child process per picture, CPU path).

Slow (~30 s on the Mac alone; minutes on a slower machine under gate load:
503 s on Windows, one render ~50 s): listed in ``SLOW`` in tests/run_tiers.py,
so the quick tier skips it and gate runs it. The fast checks live in
tests/test_guia_thumbs.py.

Animated loops need Pillow (in the ``test`` extra); without it those tests
skip with the install command instead of failing.

    python -m unittest tests.test_guia_thumbs_render -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "tools", "guide")   # tests/repo_layout.GUIDE_TOOLS
sys.path.insert(0, GUIDE)

import make_guia_thumbs as mt  # noqa: E402

# Skip before the child runs: each render is ~50 s on a loaded slow machine.
needs_pil = unittest.skipUnless(importlib.util.find_spec("PIL") is not None,
                                'animated thumbnails need Pillow: pip install -e ".[test]"')


def _render(code, scene="shape", kind="glow", anim=None):
    # CPU path: tests run without a display. (The script defaults to the GPU.)
    with tempfile.TemporaryDirectory() as tmp:
        rule = {"transient": "event", "impact": "peak"}.get(scene, "at")
        spec = {"id": "t", "code": code, "scene": scene, "kind": kind, "anim": anim,
                "poster": rule, "gpu": False, "out": os.path.join(tmp, "t.webp"),
                "anim_out": os.path.join(tmp, "t.anim.webp"),
                "card_out": os.path.join(tmp, "t.card.webp")}
        out = subprocess.run(
            [sys.executable, os.path.join(GUIDE, "make_guia_thumbs.py"), "--render-one", json.dumps(spec)],
            capture_output=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=300,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
        )
        res = json.loads(out.stdout.strip().splitlines()[-1])
        res["files"] = [f for f in ("t.anim.webp", "t.card.webp", "t.webp")
                        if os.path.exists(os.path.join(tmp, f))]
        if "t.webp" in res["files"]:
            import numpy as np
            import skia
            img = skia.Image.open(os.path.join(tmp, "t.webp"))
            res["poster"] = np.asarray(img.toarray(colorType=skia.kRGBA_8888_ColorType))
        return res


class TestRender(unittest.TestCase):
    """One child process per render (as the script does)."""

    def test_a_still_look_gets_a_poster_only(self):
        res = _render('c.visual = Neon("magenta")')
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["w"], res["h"], res["backend"]), (480, 300, "cpu"))
        self.assertFalse(res["anim"])
        self.assertEqual(res["files"], ["t.card.webp", "t.webp"])

    @needs_pil
    def test_a_moving_look_gets_a_loop_without_being_told(self):
        # Shells and orbs move too: the loop follows measured motion, not the kind.
        res = _render("c.visual = Tracer()", kind="shell")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["anim"])
        self.assertEqual(res["files"], ["t.anim.webp", "t.card.webp", "t.webp"])

    def test_anim_false_keeps_a_still(self):
        res = _render("c.visual = Tracer()", kind="shell", anim=False)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["files"], ["t.card.webp", "t.webp"])

    @needs_pil
    def test_a_bare_background_constructor_is_installed(self):
        res = _render("Clouds()", scene="field", kind="ambient")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["files"], ["t.anim.webp", "t.card.webp", "t.webp"])

    def test_spatial_fx_is_framed(self):
        # A small GlowSpot in the bottom-left corner of the design lands in the
        # middle of the picture: the camera frames the effect the snippet made.
        import numpy as np
        res = _render('GlowSpot(center=(20, 20), radius=16, color="white")',
                      scene="spatial", kind="point")
        self.assertTrue(res["ok"], res)
        lum = res["poster"][..., :3].astype(int).sum(axis=2)
        y, x = np.unravel_index(int(np.argmax(lum)), lum.shape)
        self.assertLess(abs(x - 240), 30, (x, y))
        self.assertLess(abs(y - 150), 30, (x, y))

    @needs_pil
    def test_a_transient_fires_mid_loop(self):
        res = _render("ship.pulse_outline(0.4)", scene="transient", kind="pulse")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["anim"])

    @needs_pil
    def test_an_impact_acts_on_the_photo(self):
        # Regression: the impact scene had no wallpaper; a shake of a flat
        # color changes nothing, so shake / glitch "rendered nothing".
        res = _render("canvas.shake(10)", scene="impact", kind="screen")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["anim"])

    def test_a_tall_effect_measures_tall(self):
        # Directed fire is width × length, not radius: the measuring pass must
        # zoom out on the engine's own domain, or the column is cut at the top.
        res = mt._child({"id": "t", "code": 'Fire(style="blaze")', "scene": "spatial",
                         "kind": "point", "anim": None, "gpu": False, "poster": "at",
                         "out": os.devnull, "anim_out": os.devnull, "card_out": os.devnull,
                         "measure": True})
        x0, y0, x1, y1 = res["box"]
        self.assertGreater(y1 - y0, mt.TALL_RATIO * (x1 - x0), res["box"])

    def test_blank_guard(self):
        res = _render("x = 1")
        self.assertFalse(res["ok"])
        self.assertIn("nothing visible", res["error"])

    def test_anim_true_must_move(self):
        res = _render("c.color = 'gold'", anim=True)
        self.assertFalse(res["ok"])
        self.assertIn("nothing moves", res["error"])


if __name__ == "__main__":
    unittest.main()
