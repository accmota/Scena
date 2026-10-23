"""
A look drawn for a group paints each body as it does for one shape.

Looks that draw their peers together (``_emit_look_passes``) must keep each
host's body kind: a stroke type (a Track, a Line) keeps a stroked body and an
area shape (a Circle, a Rect) keeps its fill. Neon bucketed every host that is
not a Line or a Circle as ``"path"`` and filled it, so two closed Tracks with
Neon painted two solid disks while one alone drew its ring (showcase A12,
2026-10-23).

Bug class guarded: a grouped look pass that decides the body from the draw
kind (line / circle / path) instead of from the host's stroke type.

Run:

    python tests/run_tiers.py focused test_look_group_body
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from program_support import FRAME  # noqa: E402
from system_support import boot, system_world  # noqa: E402

from scena import Circle, Neon, Track  # noqa: E402

boot()


def pixels(w, n=2):
    w.step(n, dt=FRAME)
    img = w.surface.makeImageSnapshot()
    info = skia.ImageInfo.Make(img.width(), img.height(),
                               skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    buf = bytearray(img.width() * img.height() * 4)
    assert img.readPixels(info, buf, img.width() * 4, 0, 0)
    return np.frombuffer(bytes(buf), np.uint8).reshape(img.height(), img.width(), 4)[:, :, :3]


def lit(px) -> bool:
    return int(px.astype(int).sum()) > 60


class TestNeonGroupBody(unittest.TestCase):
    def ring_centres(self, makers):
        with system_world(draw=True) as w:
            shapes = [make(cx) for cx, make in zip((90, 200, 310), makers)]
            a = pixels(w)
            return [a[150, cx] for cx in (90, 200, 310)[:len(shapes)]]

    def test_closed_tracks_keep_a_hollow_ring(self):
        for n in (1, 2, 3):
            with self.subTest(tracks=n):
                makers = [lambda cx: Track.circle(center=(cx, 150), radius=40,
                                                   line_width=3, visual=Neon("cyan"))] * n
                for px in self.ring_centres(makers):
                    self.assertFalse(lit(px), f"{n} Neon tracks: centre painted {px}")

    def test_star_tracks_keep_a_hollow_body(self):
        makers = [lambda cx: Track.star(center=(cx, 150), radius=45,
                                        line_width=3, visual=Neon("cyan"))] * 2
        for px in self.ring_centres(makers):
            self.assertFalse(lit(px), f"Neon star tracks: centre painted {px}")

    def test_area_shapes_keep_their_fill(self):
        # The other side of the key: Circles grouped with a Track stay filled.
        makers = [
            lambda cx: Circle(center=(cx, 150), radius=40, visual=Neon("cyan")),
            lambda cx: Track.circle(center=(cx, 150), radius=40,
                                    line_width=3, visual=Neon("cyan")),
            lambda cx: Circle(center=(cx, 150), radius=40, visual=Neon("cyan")),
        ]
        c1, ring, c2 = self.ring_centres(makers)
        self.assertTrue(lit(c1), f"Neon circle lost its fill: {c1}")
        self.assertTrue(lit(c2), f"Neon circle lost its fill: {c2}")
        self.assertFalse(lit(ring), f"Neon track grouped with circles filled: {ring}")


if __name__ == "__main__":
    unittest.main()
