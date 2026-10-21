"""
A Contrail rebuilds its stroke from one span table, and draws exactly the path
it drew before.

Found profiling ``examples/constelacao.py`` (2026-10-21): three comets with a
40-point faded ``Contrail`` spent ~0.7 ms a frame in ``snapshot``. Each span
of the rebuild rebuilt the whole point list and the phantom ends
(``_append_span``: O(n²) a rebuild), and the fade bands computed every
Catmull-Rom span a second time. ``history._span_table`` now computes each span
once and both the stroke and the bands replay it: a 40-point faded rebuild
163 → 57 µs (History Design, "One span table a rebuild").

Bug class guarded: **a per-item helper that recomputes a per-collection
value** (here the point list and the phantom ends, per span). Pinned two ways:
the stroke, every band, the band alphas and the centre are byte-identical to
the pre-change rebuild (kept below as the reference) over random trails; and a
spy counts one ``catmull_rom_to_bezier`` per span and one ``_phantom_open``
per rebuild.

Run:

    python tests/run_tiers.py focused test_contrail_rebuild
"""
from __future__ import annotations

import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skia  # noqa: E402

import scena.history as H  # noqa: E402
from scena import Circle, Contrail, init  # noqa: E402
from scena.curves import _phantom_open, catmull_rom_to_bezier  # noqa: E402


# -- the rebuild before 2026-10-21, kept as the reference ----------------------

def _old_append_span(path, xs, ys, i, smooth):
    n = len(xs)
    if smooth <= 0.0:
        path.lineTo(xs[i + 1], ys[i + 1])
        return
    pts = list(zip(xs, ys))
    before, after = _phantom_open(pts)
    p0 = before if i == 0 else pts[i - 1]
    p3 = after if i + 2 >= n else pts[i + 2]
    _b0, b1, b2, b3 = catmull_rom_to_bezier(p0, pts[i], pts[i + 1], p3, smooth=smooth)
    path.cubicTo(b1[0], b1[1], b2[0], b2[1], b3[0], b3[1])


def old_rebuild(xs, ys, smooth, fade, ease):
    """(stroke, bands, alphas, centre) as ``_Stroke._rebuild_geometry`` made them."""
    path = skia.Path()
    n = len(xs)
    if n:
        path.moveTo(xs[0], ys[0])
        for i in range(n - 1):
            _old_append_span(path, xs, ys, i, smooth)
    bands, alphas = [], []
    centre = None
    if n >= 1:
        centre = (sum(xs) / n, sum(ys) / n)
    if fade and n >= 2:
        ease = ease or (lambda t: t)
        spans = n - 1
        n_bands = min(H._FADE_BANDS, spans)
        for b in range(n_bands):
            span0 = (b * spans) // n_bands
            span1 = ((b + 1) * spans) // n_bands
            if span1 <= span0:
                continue
            band = skia.Path()
            band.moveTo(xs[span0], ys[span0])
            for i in range(span0, span1):
                _old_append_span(band, xs, ys, i, smooth)
            bands.append(bytes(band.serialize()))
            alphas.append(max(0.0, min(1.0, float(ease(span1 / float(n - 1))))))
    return bytes(path.serialize()), bands, alphas, centre


def state_of(stroke):
    n = len(stroke._xs)
    centre = (stroke._center_pt.x, stroke._center_pt.y) if n else None
    return (bytes(stroke._path.serialize()), [bytes(b.serialize()) for b in stroke._band_paths],
            list(stroke._band_alphas), centre)


def trail(rng, n):
    pts = [(rng.uniform(-50, 900), rng.uniform(-50, 700)) for _ in range(n)]
    if n > 3 and rng.random() < 0.3:
        pts[2] = pts[1]                         # a repeated sample (comet standing still)
    if n > 5 and rng.random() < 0.2:
        pts[4] = (pts[3][0] + 1e-9, pts[3][1])  # nearly repeated
    return pts


class _World(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self.trail = Contrail(max_points=40, fade=True, line_width=5)

    def tearDown(self):
        self.trail.destroy()


class TestSamePathAsBefore(_World):
    def test_random_trails(self):
        rng = random.Random(7)
        stroke = self.trail._stroke
        squared = lambda t: t * t   # noqa: E731
        cases = 0
        for _ in range(250):
            n = rng.choice([0, 1, 2, 3, 4, 5, 8, 16, 17, 33, 40, 41])
            pts = trail(rng, n)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            for smooth in (1.0, 0.0, 0.5, 2.0):
                for fade in (True, False):
                    ease = rng.choice([None, squared])
                    stroke._xs[:] = xs
                    stroke._ys[:] = ys
                    stroke._smooth, stroke._fade, stroke._ease_fn = smooth, fade, ease
                    stroke._rebuild_geometry()
                    self.assertEqual(state_of(stroke), old_rebuild(xs, ys, smooth, fade, ease),
                                     (n, smooth, fade))
                    cases += 1
        self.assertGreater(cases, 1000)

    def test_through_snapshots(self):
        rng = random.Random(8)
        ball = Circle(center=(400, 300), radius=5)
        try:
            for step in range(120):
                ball.move_to(rng.uniform(0, 800), rng.uniform(0, 600))
                self.trail.snapshot(ball)
                pts = [(float(p.x), float(p.y)) for p in self.trail]
                want = old_rebuild([p[0] for p in pts], [p[1] for p in pts], 1.0, True, None)
                self.assertEqual(state_of(self.trail._stroke), want, step)
            self.assertEqual(len(self.trail), 40)
        finally:
            ball.destroy()


class TestOneSpanTablePerRebuild(_World):
    def test_each_span_once(self):
        for x in range(40):
            self.trail.snapshot(x * 10.0, (x % 7) * 13.0)
        with mock.patch.object(H, "catmull_rom_to_bezier", wraps=catmull_rom_to_bezier) as cr, \
                mock.patch.object(H, "_phantom_open", wraps=_phantom_open) as ph:
            self.trail.snapshot(400.0, 77.0)
        self.assertEqual(cr.call_count, 39)     # 40 samples, 39 spans: once each
        self.assertEqual(ph.call_count, 1)

    def test_polyline_computes_no_curve(self):
        self.trail.smooth = 0
        with mock.patch.object(H, "catmull_rom_to_bezier", wraps=catmull_rom_to_bezier) as cr:
            for x in range(10):
                self.trail.snapshot(x * 10.0, 0.0)
        self.assertEqual(cr.call_count, 0)


if __name__ == "__main__":
    unittest.main()
