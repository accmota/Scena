"""Differential tests: draw fast paths vs the full draw path (CPU raster).

Pairs covered (fast/slow inventory, Testing Design — Strategy):

* **Sticky ``_plain_blit`` flag** (#3) — after any sequence of look / stamp /
  filter / transient changes, the stored flag equals a fresh evaluation of
  the predicate (``_refresh_plain_blit``). A stale True would blit a shape
  without its look; a stale False only costs speed — both are bugs.
* **Plain blit vs full draw** (#3) — the same plain shapes rendered with the
  flag as computed, and with it forced False (``Graphic.draw``): identical
  pixels.
* **Cull on vs off** (#4) — ``canvas.cull_offscreen`` must be conservative:
  for any scene (partly off-screen shapes, looks and stamps that pad the
  bounds, a moved camera) the frame is pixel-identical with culling on.
* **Shared-filter batching** (#10) — ``batch_shared_filters`` on vs off, on
  layouts whose filtered footprints do not overlap (the only case where the
  batched z-order trade-off promises identical pixels). Quality stays at
  ``high``: ``fx_quality="max"`` also changes detail, so it is not a switch.

The tombstone readers (#18) are guarded structurally in
``test_registry_layers.TestLiveCountsIgnoreTombstones`` (D1).

    python -m unittest tests.test_diff_draw -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import skia  # noqa: E402

from hypothesis_support import quiet  # noqa: E402
from system_support import system_world  # noqa: E402
from hypothesis import given, note, settings, strategies as hst  # noqa: E402

from scena import (  # noqa: E402
    Blur, Circle, Ellipse, Line, Neon, Polygon, Rect, RegularPolygon, canvas,
)

W, H = 160, 120


def _engine():
    from scena.orchestration import ScenaFramework
    return ScenaFramework.get_instance()._scena_draw


def render(objs, *, plain=None, batch=None) -> np.ndarray:
    """Draw ``objs`` as one layer on a fresh CPU surface; RGBA array."""
    eng = _engine()
    surf = skia.Surface(W, H)
    saved = eng.skia_canvas, eng.batch_shared_filters
    forced = []
    try:
        eng.skia_canvas = surf.getCanvas()
        eng.skia_canvas.clear(skia.Color4f(0, 0, 0, 1))
        if batch is not None:
            eng.batch_shared_filters = batch
        if plain is False:
            for o in objs:
                forced.append((o, o._plain_blit))
                object.__setattr__(o, "_plain_blit", False)
        eng._draw_layer_batched(list(objs))
    finally:
        for o, v in forced:
            object.__setattr__(o, "_plain_blit", v)
        eng.skia_canvas, eng.batch_shared_filters = saved
    return np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)).copy()


def assert_pixels_equal(tc, a: np.ndarray, b: np.ndarray, what: str, tol: int = 0) -> None:
    diff = np.abs(a.astype(int) - b.astype(int)).max(axis=-1)
    bad = diff > tol
    if bad.any():
        ys, xs = np.nonzero(bad)
        tc.fail(f"{what}: {int(bad.sum())} pixels differ (max delta {int(diff.max())}), "
                f"bbox x {xs.min()}..{xs.max()} y {ys.min()}..{ys.max()}")


COLORS = ["tomato", "gold", "cyan", "white", "#3060ff", "orchid"]
x = hst.integers(10, W - 10).map(float)
y = hst.integers(10, H - 10).map(float)
r = hst.integers(3, 18).map(float)

SHAPES = hst.one_of(
    hst.builds(lambda cx, cy, rr, col, lw: ("circle", cx, cy, rr, col, lw), x, y, r,
               hst.sampled_from(COLORS), hst.sampled_from([1.0, 1.5, 3.0])),
    hst.builds(lambda cx, cy, rr, col, lw: ("rect", cx, cy, rr, col, lw), x, y, r,
               hst.sampled_from(COLORS), hst.sampled_from([1.0, 1.5, 3.0])),
    hst.builds(lambda cx, cy, rr, col, lw: ("line", cx, cy, rr, col, lw), x, y, r,
               hst.sampled_from(COLORS), hst.sampled_from([1.0, 1.5, 3.0])),
    hst.builds(lambda cx, cy, rr, col, lw: ("poly", cx, cy, rr, col, lw), x, y, r,
               hst.sampled_from(COLORS), hst.sampled_from([1.0, 1.5, 3.0])),
    hst.builds(lambda cx, cy, rr, col, lw: ("ellipse", cx, cy, rr, col, lw), x, y, r,
               hst.sampled_from(COLORS), hst.sampled_from([1.0, 1.5, 3.0])),
)


def build(spec):
    kind, cx, cy, rr, col, lw = spec
    with quiet():
        if kind == "circle":
            o = Circle(center=(cx, cy), radius=rr, color=col)
        elif kind == "rect":
            o = Rect(center=(cx, cy), width=rr * 1.6, height=rr, angle=20, color=col)
        elif kind == "line":
            o = Line(p1=(cx - rr, cy), p2=(cx + rr, cy + rr / 2), color=col)
        elif kind == "poly":
            o = RegularPolygon(center=(cx, cy), radius=rr, n=5, color=col)
        else:
            o = Ellipse(center=(cx, cy), width=rr * 2, height=rr, color=col)
        o.line_width = lw
    return o


def expected_plain(obj) -> bool:
    """Reference predicate, independent of the engine's: the documented contract
    (Shapes Design — Plain draw): no costume, no stamp, no filter, no live
    transient."""
    for name in ("_visual", "_glow", "_shadow", "_hue", "_tail", "_fill_filter", "_line_filter"):
        if getattr(obj, name, None) is not None:
            return False
    st = getattr(obj, "_tx_state", None)
    return not (st is not None and st.any_active())


class TestPlainBlit(unittest.TestCase):
    @given(specs=hst.lists(SHAPES, min_size=1, max_size=6))
    def test_plain_blit_matches_full_draw(self, specs):
        objs = [build(s) for s in specs]
        try:
            self.assertTrue(all(o._plain_blit for o in objs), "fixtures must be plain")
            assert_pixels_equal(self, render(objs), render(objs, plain=False),
                                "plain blit vs full draw")
        finally:
            for o in objs:
                o.destroy()

    LOOK_OPS = hst.lists(hst.one_of(
        hst.tuples(hst.just("visual"), hst.sampled_from(["neon", None])),
        hst.tuples(hst.just("glow"), hst.sampled_from([True, "red", None])),
        hst.tuples(hst.just("shadow"), hst.sampled_from([True, None])),
        hst.tuples(hst.just("tail"), hst.sampled_from([True, None])),
        hst.tuples(hst.just("fill_filter"), hst.sampled_from(["blur", None])),
        hst.tuples(hst.just("line_filter"), hst.sampled_from(["blur", None])),
        hst.tuples(hst.just("flash"), hst.sampled_from([0.1, 0.3])),
        hst.tuples(hst.just("color"), hst.sampled_from(COLORS)),
        hst.tuples(hst.just("tick"), hst.sampled_from([0.05, 0.2, 0.5])),
    ), min_size=1, max_size=12)

    @given(spec=SHAPES, ops=LOOK_OPS)
    def test_sticky_flag_equals_fresh_predicate(self, spec, ops):
        import scena.transients as tr
        now = [0.0]
        tr.set_now_fn(lambda: now[0])
        obj = build(spec)
        try:
            for i, op in enumerate(ops):
                note(f"step {i}: {op}")
                kind, val = op
                with quiet():
                    if kind == "visual":
                        obj.visual = Neon() if val == "neon" else None
                    elif kind in ("fill_filter", "line_filter"):
                        setattr(obj, kind, Blur(2) if val == "blur" else None)
                    elif kind == "flash":
                        obj.flash(duration=val)
                    elif kind == "tick":
                        now[0] += val
                        tr.tick_all_transients(now[0])
                    else:
                        setattr(obj, kind, val)
                self.assertEqual(obj._plain_blit, expected_plain(obj),
                                 f"sticky _plain_blit is {obj._plain_blit} but the "
                                 f"contract says {expected_plain(obj)} after step {i} {op}")
        finally:
            tr.set_now_fn(None)
            obj.destroy()


def _screen(world) -> np.ndarray:
    """The part of the SystemWorld surface that is the screen.

    Headless ``_draw_frame`` runs at scale 1 (y-up) into the top-left
    ``canvas.width × canvas.height`` of a framebuffer-sized surface, and
    ``glViewport`` is mocked, so geometry past the view spills into the rest of
    the surface. Only the design rectangle is visible (Testing Design —
    Harness pitfalls)."""
    a = np.asarray(world.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
    return a[: int(canvas.height), : int(canvas.width)].copy()


class TestCullIsConservative(unittest.TestCase):
    OFF = hst.integers(-60, W + 60).map(float)

    # Full frames are costly; a quarter of the profile's examples.
    @settings(max_examples=max(10, settings().max_examples // 4))
    @given(specs=hst.lists(hst.tuples(SHAPES, OFF, hst.integers(-60, H + 60).map(float),
                                      hst.sampled_from([None, "glow", "shadow", "neon"])),
                           min_size=1, max_size=8),
           pan=hst.tuples(hst.integers(-40, 40), hst.integers(-40, 40)),
           zoom=hst.sampled_from([1.0, 1.5, 0.75]),
           layer=hst.sampled_from([None, "fixed", "half", "scroll"]),
           turn=hst.sampled_from([0.0, 0.0, 25.0]))
    def test_frame_identical_with_cull(self, specs, pan, zoom, layer, turn):
        # ``layer``: the shapes on a parallax / scroll layer, culled against
        # that layer's own view window since showcase A8 (never culled before).
        with system_world(draw=True) as w:
            if layer is not None and layer not in canvas.layers:
                resp = {"fixed": dict(pan_response=0.0), "half": dict(pan_response=0.5),
                        "scroll": dict(scroll=(-40, 25))}[layer]
                canvas.layers.create(layer, **resp)
            objs = []
            for spec, ox, oy, look in specs:
                o = w.track(build(spec))
                if layer is not None:
                    o.layer = layer
                o.move_to(ox, oy)
                with quiet():
                    if look == "glow":
                        o.glow = True
                    elif look == "shadow":
                        o.shadow = True
                    elif look == "neon":
                        o.visual = Neon()
                objs.append(o)
            canvas.pan_to((canvas.width / 2 + pan[0], canvas.height / 2 + pan[1]))
            canvas.zoom_to(zoom)
            canvas.rotate_to(turn)
            if layer == "scroll":
                w.step(20)                  # the scroll accum moves the layer
            frames = []
            eng = w.fw._scena_draw
            saved = canvas.cull_offscreen, eng.batch_shared_filters
            # Test this frame: the backoff could skip the test, which only
            # draws more and would hide an aggressive cull.
            backoff = mock.patch.object(sys.modules["scena.canvas"], "_CULL_BACKOFF", False)
            backoff.start()
            self.addCleanup(backoff.stop)
            # Vary ONLY the cull switch. With shared-filter batching on, culling
            # an off-screen member changes a batched blur layer's bounds, which
            # moves edge pixels of the OTHER members by a level or two — that is
            # the batching trade-off (TestSharedFilterBatching), not culling.
            eng.batch_shared_filters = False
            try:
                for cull in (False, True):
                    canvas.cull_offscreen = cull
                    w.step(1, dt=0.0)
                    frames.append(_screen(w))
            finally:
                canvas.cull_offscreen, eng.batch_shared_filters = saved
            assert_pixels_equal(self, frames[0], frames[1], "cull off vs cull on")


class TestSharedFilterBatching(unittest.TestCase):
    @given(cells=hst.lists(hst.tuples(hst.integers(0, 3), hst.integers(0, 2)), min_size=2,
                           max_size=8, unique=True),
           kinds=hst.lists(hst.sampled_from(["circle", "rect", "poly"]), min_size=8, max_size=8),
           which=hst.sampled_from(["fill_filter", "line_filter"]))
    def test_batched_equals_per_shape_when_apart(self, cells, kinds, which):
        blur = Blur(2)  # one shared filter object → one batch key
        objs = []
        try:
            for (cx, cy), kind in zip(cells, kinds):
                o = build((kind, 20.0 + cx * 38, 20.0 + cy * 38, 8.0, "gold", 2.0))
                setattr(o, which, blur)
                objs.append(o)
            assert_pixels_equal(self, render(objs, batch=True), render(objs, batch=False),
                                "batch_shared_filters on vs off (apart)", tol=1)
        finally:
            for o in objs:
                o.destroy()


class TestDrawCanaries(unittest.TestCase):
    def test_cull_suite_catches_an_aggressive_cull(self):
        from diff_support import assert_catches
        eng_cls = type(_engine())
        assert_catches(self, "test_diff_draw.TestCullIsConservative.test_frame_identical_with_cull",
                       # Both doors: the one-object check and the draw loop's
                       # per-object step (review 2026-10-09 S9-10 hoisted it).
                       [(eng_cls, "_passes_cull", lambda self, obj, layer=None: False),
                        ("scena.canvas", "_cull_keeps", lambda obj, vb: False),
                        # The draw loop reads the (cached) box itself.
                        ("scena.canvas", "_cull_box", lambda obj: (1e18, 1e18, 1e18 + 1, 1e18 + 1))],
                       "a cull that drops visible shapes")

    def test_flag_suite_catches_a_stale_flag(self):
        from diff_support import assert_catches
        from scena.entity import Graphic
        orig = Graphic._refresh_plain_blit

        def lazy(self):
            # never clears the flag once set: the old sticky-True bug shape
            if getattr(self, "_plain_blit", False):
                return
            orig(self)

        # The setters reach the patched method; the test's reference is its own
        # predicate (expected_plain), so the canary can fail it.
        assert_catches(self, "test_diff_draw.TestPlainBlit.test_sticky_flag_equals_fresh_predicate",
                       [(Graphic, "_refresh_plain_blit", lazy)], "a flag that never clears")


if __name__ == "__main__":
    unittest.main()
