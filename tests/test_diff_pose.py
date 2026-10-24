"""Differential tests: pose fast path vs the batched reference path.

Pairs covered (fast/slow inventory, Testing Design — Strategy):

* **A1 / A4 pose writes** (``_pose_fast_ok``: bare ``__dict__`` float writes)
  vs the batched ``takein`` / ``mark_dirty`` path (``_move_by_batched``,
  ``_rotate_by_batched``, …). Twin B is forced slow with
  ``_flag_pull_consumers``; both twins get the same random verb sequence
  (instant and timed) and must end in the same pose + collision geometry
  after every step.
* **Defining readers vs Derivate reads**: at the end, every public geometry
  read (``center``, ``radius``, ``width``, ``p1`` …) agrees between the twins —
  the fast twin's Defining-only state must mean the same shape.
* **Engine readers stay cold** (``TestEngineReadersStayCold``): a fresh shape
  must stay on the fast path after each per-frame engine reader (draw, cull
  AABB, collision pose key / proxy / snapshot, ``_center_xy``). Reading a
  cold Derivate materializes it and sets ``_needs_pull_invalidate`` for good
  (Reactive Design — Engine readers stay cold).

Oracle: tolerance ``REL 1e-9 / ABS 1e-7`` (the paths add and rotate in a
different order). Every comparison first asserts twin A is still fast, so a
test cannot pass by comparing slow against slow.

    python -m unittest tests.test_diff_pose -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import (  # noqa: E402
    assert_fast, assert_same, fingerprint, is_fast, make_twins,
)
from hypothesis_support import quiet  # noqa: E402
from hypothesis import given, note, strategies as hst  # noqa: E402

from scena import (  # noqa: E402
    Circle, Ellipse, Triangle, Line, Polygon, Rect, RegularPolygon,
    Sprite, Square, Text, Vec2, clock,
)
from scena.process import reset_process_scheduler, tick_processes  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

# START_SLOW's shapes link to a reference shape (a Rect, a Line, a Circle) that
# the test does not hold: it outlived the module, and later modules counted it
# (the deep serial pass, 2026-10-24: string_theory saw its Lines; WP42).
setUpModule, tearDownModule = module_sweep()

# Every constructor model with a Defining-only pose. The key is the label in
# failure messages; each factory builds one fresh shape.
MODELS = {
    "Circle center_radius": lambda: Circle(center=(10, 20), radius=7),
    "Circle arc": lambda: Circle(center=(1, 2), radius=9, angle=110, spread=180),
    "Circle center_perimeter": lambda: Circle(center=(0, 0), perimeter_point=(5, 0)),
    "Circle two_points": lambda: Circle(p1=(0, 0), p2=(10, 4)),
    "Rect center_wh": lambda: Rect(center=(0, 0), width=10, height=6, angle=15),
    "Rect corner_corner": lambda: Rect(p1=(0, 0), p2=(10, 6)),
    "Rect top_left_wh": lambda: Rect(top_left=(0, 10), width=8, height=4),
    "Rect point_vec": lambda: Rect(p1=(0, 0), vec=Vec2(10, 4)),
    "Rect spine": lambda: Rect(p1=(0, 0), p2=(10, 4), height=3, anchor="cap"),
    "Square center_length": lambda: Square(center=(3, 3), length=5),
    "Square top_left_length": lambda: Square(top_left=(0, 5), length=5),
    "Ellipse center_wh": lambda: Ellipse(center=(0, 0), width=12, height=5),
    "Ellipse focal_points": lambda: Ellipse(fp1=(-3, 0), fp2=(3, 0), major_axis=10),
    "Line point_point": lambda: Line(p1=(0, 0), p2=(10, 5)),
    "Line center_length_angle": lambda: Line(center=(0, 0), length=10, angle=30),
    "Line point_vec": lambda: Line(p1=(0, 0), vec=Vec2(3, 4)),
    "Polygon": lambda: Polygon(points=[(0, 0), (10, 0), (12, 8), (0, 6)]),
    "RegularPolygon center_radius": lambda: RegularPolygon(center=(0, 0), radius=6, n=5),
    "RegularPolygon center_side": lambda: RegularPolygon(center=(0, 0), side=6, n=5),
    "RegularPolygon vertex_side": lambda: RegularPolygon(vertex=(0, 0), side=6, n=5),
    "Triangle": lambda: Triangle(center=(0, 0), side=6),
    "Sprite": lambda: Sprite("diff_missing.png", center=(5, 5)),
    "Text": lambda: Text("hi", center=(0, 0)),
}

# Engine readers that run every frame for a drawn / collidable actor.
def _readers():
    import skia
    col = sys.modules["scena.collision"]
    cvm = sys.modules["scena.canvas"]
    from scena.orchestration import ScenaFramework
    eng = ScenaFramework.get_instance()._scena_draw
    surface = skia.Surface(64, 64)
    return {
        "_center_xy": lambda o: o._center_xy(),
        "collision pose key": lambda o: col._collision_pose_key(o),
        "collision proxy aabb": lambda o: col._proxy_aabb_for_shape(o),
        "collision snapshot": lambda o: col._snapshot_shape_uncached(o, cache_owner=None),
        "cull aabb": lambda o: cvm._approx_draw_aabb(o),
        "cull test": lambda o: eng._passes_cull(o),
        "draw": lambda o: o.draw(surface.getCanvas()),
        # Pointer hover / click (graphics review R6: one hover warmed a
        # RegularPolygon for good, 2.8 -> 58 us per move + rotate).
        "hit test": lambda o: o.contains_point(*o._center_xy()),
        "is_collapsed": lambda o: o.is_collapsed,
    }


def _reader_models():
    """MODELS plus every Graphic kind of ``geometry_support.KINDS`` that starts fast.

    A sweep is only as wide as its list (graphics review): the reader matrix
    covers the contract registry, not a hand-picked subset."""
    import geometry_support as G
    out = dict(MODELS)
    for kind in sorted(G.KINDS):
        if kind.startswith("Box") or kind in START_SLOW or kind in out:
            continue
        out[kind] = (lambda k=kind: G.build(k))
    return out


# KINDS entries that start on the slow path, with the reason.
START_SLOW = {
    "Ellipse from_rect": "linked to its Rect at construction",
    "Line parallel_dist": "linked to its reference Line at construction",
    "Line parallel_point": "linked to its reference Line at construction",
    "Line perpendicular_point": "linked to its reference Line at construction",
    "Line tangent_angle": "linked to its Circle at construction",
    "Line tangent_point": "linked to its Circle at construction",
    "Track line point_point": "by design (G11): a control-point Track keeps its centroid live",
}


# Known violations (D3 in Testing Design). This set may only SHRINK: a new
# warm cell fails the guard, and a fixed cell still listed here fails too
# (so the list cannot go stale).
KNOWN_WARM = frozenset()

# Author pose verbs that warm a cold Derivate (D3). Same shrink-only rule.
KNOWN_WARM_VERBS = frozenset()

# One instance of each instant verb, for the verb matrix.
VERB_SAMPLES = (
    ("move_to", 5.0, 6.0), ("move_by", 3.0, 4.0), ("move_polar", 30.0, 5.0),
    ("move_face", 3.0, 4.0), ("rotate_by", 20.0), ("rotate_about", 20.0, (50.0, 50.0)),
    ("rotate_to", 40.0), ("set_rotation", 40.0), ("scale_by", 1.25),
    ("scale_about", 1.25, (50.0, 50.0)), ("scale_to", 2.0), ("flip_x",), ("flip_y",),
)

# Models whose fingerprint itself warms the fast twin (derived from KNOWN_WARM
# for the fingerprint readers); the differential cannot run on them until D3
# is fixed for those cells.
_FINGERPRINT_READERS = {"_center_xy", "collision snapshot"}


def _pose_models():
    skip = {m for m, r in KNOWN_WARM if r in _FINGERPRINT_READERS}
    return sorted(m for m in MODELS if m not in skip)


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------

coord = hst.integers(-200, 200).map(float)
delta = hst.integers(-60, 60).map(float)
angle = hst.integers(-400, 400).map(float)
factor = hst.sampled_from([0.5, 0.8, 1.0, 1.25, 2.0])
pivot = hst.tuples(coord, coord)

OPS = hst.one_of(
    hst.tuples(hst.just("move_to"), coord, coord),
    hst.tuples(hst.just("move_by"), delta, delta),
    hst.tuples(hst.just("move_polar"), angle, delta),
    hst.tuples(hst.just("move_face"), delta, delta),
    hst.tuples(hst.just("rotate_by"), angle),
    hst.tuples(hst.just("rotate_about"), angle, pivot),
    hst.tuples(hst.just("rotate_to"), angle),
    hst.tuples(hst.just("set_rotation"), angle),
    hst.tuples(hst.just("scale_by"), factor),
    hst.tuples(hst.just("scale_about"), factor, pivot),
    hst.tuples(hst.just("scale_to"), factor),
    hst.tuples(hst.just("flip_x")),
    hst.tuples(hst.just("flip_y")),
    hst.tuples(hst.just("tween_move"), delta, delta),
    hst.tuples(hst.just("tween_rotate"), angle),
    hst.tuples(hst.just("tween_scale"), factor),
    hst.tuples(hst.just("tick"), hst.sampled_from([0.05, 0.1, 0.25])),
)


def apply(obj, op) -> None:
    kind = op[0]
    if kind == "move_to":
        obj.move_to(op[1], op[2])
    elif kind == "move_by":
        obj.move_by(op[1], op[2])
    elif kind == "move_polar":
        obj.move_by(angle=op[1], distance=op[2])
    elif kind == "move_face":
        obj.move_by(op[1], op[2], face=True)
    elif kind == "rotate_by":
        obj.rotate_by(op[1])
    elif kind == "rotate_about":
        obj.rotate_by(op[1], about=op[2])
    elif kind == "rotate_to":
        obj.rotate_to(op[1])
    elif kind == "set_rotation":
        obj.angle = op[1]
    elif kind == "scale_by":
        obj.scale_by(op[1])
    elif kind == "scale_about":
        obj.scale_by(op[1], about=op[2])
    elif kind == "scale_to":
        obj.scale_to(op[1])
    elif kind == "flip_x":
        obj.flip_x = not obj.flip_x
    elif kind == "flip_y":
        obj.flip_y = not obj.flip_y
    elif kind == "tween_move":
        obj.move_by(op[1], op[2], time=0.2, force=True)
    elif kind == "tween_rotate":
        obj.rotate_by(op[1], time=0.2, force=True)
    elif kind == "tween_scale":
        obj.scale_to(op[1], time=0.2, force=True)
    else:
        raise AssertionError(kind)


def _outcome(fn, *args):
    """``None`` on success, else the exception type name (compared across twins)."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__
    return None


def _tick(dt: float) -> None:
    clock.advance(dt)
    tick_processes()


# Public reads compared once at the end (they may warm Derivates; that is fine
# after the last differential step).
_PUBLIC = ("center", "radius", "width", "height", "length", "side", "angle",
           "spread", "p1", "p2", "fp1", "fp2", "major_axis",
           "top_left", "vertex", "points", "angle", "scale")


def _public_reads(obj) -> dict:
    out = {}
    for name in _PUBLIC:
        if not hasattr(type(obj), name) and name not in getattr(type(obj), "_setattr_route", {}):
            continue
        try:
            v = getattr(obj, name)
        except Exception as exc:  # a read that raises must raise on both twins
            out[name] = f"raises {type(exc).__name__}"
            continue
        out[name] = _plain(v)
    return out


def _plain(v):
    from scena.shapes import _bare_num
    if hasattr(v, "x") and hasattr(v, "y"):
        return (_bare_num(v.x), _bare_num(v.y))
    from collections.abc import Sequence
    if isinstance(v, Sequence) and not isinstance(v, str):
        return tuple(_plain(x) for x in v)
    try:
        return _bare_num(v)
    except Exception:
        return repr(v)


class TestPoseFastVsBatched(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        self._owned = []

    def tearDown(self):
        reset_process_scheduler()
        for o in self._owned:
            try:
                o.destroy()
            except Exception:
                pass

    @given(model=hst.sampled_from(_pose_models()), ops=hst.lists(OPS, min_size=1, max_size=12))
    def test_same_pose_after_every_step(self, model, ops):
        reset_process_scheduler()
        a, b = make_twins(MODELS[model])
        self._owned += [a, b]
        assert_fast(self, a, "construction")
        assert_same(self, fingerprint(a), fingerprint(b), f"{model} construction")
        for i, op in enumerate(ops):
            note(f"step {i}: {op}")
            what = f"{model} step {i} {op}"
            with quiet():
                if op[0] == "tick":
                    _tick(op[1])
                else:
                    ea = _outcome(apply, a, op)
                    eb = _outcome(apply, b, op)
                    self.assertEqual(ea, eb, f"{what}: the paths raise differently")
            if op[0].startswith("tween"):
                # timed verbs write through the process tick (force=True claims
                # the fields) — that path is shared; compare after ticks.
                continue
            assert_same(self, fingerprint(a), fingerprint(b), what)
            if op[0] != "tick" and not is_fast(a):
                if (model, op[0]) in KNOWN_WARM_VERBS:
                    note(f"stop: {what} is a known D3 cell")
                    break
                assert_fast(self, a, what)
        _tick(1.0)  # finish every tween
        assert_same(self, fingerprint(a), fingerprint(b), f"{model} end")
        assert_same(self, _public_reads(a), _public_reads(b), f"{model} public reads")
        for o in (a, b):
            o.destroy()
        self._owned.clear()


class TestEngineReadersStayCold(unittest.TestCase):
    """D3 guard: per-frame engine readers keep a fresh shape on the fast path."""

    def test_matrix(self):
        readers = _readers()
        warm = set()
        fresh_slow = []
        for model, make in _reader_models().items():
            for reader, read in readers.items():
                with quiet():
                    obj = make()
                if not is_fast(obj):
                    fresh_slow.append(model)
                    obj.destroy()
                    break
                with quiet():
                    read(obj)
                if not is_fast(obj):
                    warm.add((model, reader))
                obj.destroy()
        self.assertEqual(fresh_slow, [], "a fresh shape must start on the fast path")
        new = sorted(warm - KNOWN_WARM)
        fixed = sorted(KNOWN_WARM - warm)
        self.assertEqual(new, [], "engine readers warmed a cold Derivate "
                         "(read Defining geometry instead; Reactive Design — Engine readers stay cold)")
        self.assertEqual(fixed, [], "fixed — remove these cells from KNOWN_WARM")

    def test_start_slow_is_not_stale(self):
        import geometry_support as G
        for kind in START_SLOW:
            with quiet():
                obj = G.build(kind)
            self.assertFalse(is_fast(obj), f"{kind} now starts fast: remove it from START_SLOW")
            obj.destroy()

    def test_verb_matrix(self):
        warm = set()
        for model, make in MODELS.items():
            for op in VERB_SAMPLES:
                with quiet():
                    obj = make()
                    _outcome(apply, obj, op)
                if not is_fast(obj):
                    warm.add((model, op[0]))
                obj.destroy()
        new = sorted(warm - KNOWN_WARM_VERBS)
        fixed = sorted(KNOWN_WARM_VERBS - warm)
        self.assertEqual(new, [], "a pose verb warmed a cold Derivate")
        self.assertEqual(fixed, [], "fixed — remove these cells from KNOWN_WARM_VERBS")


class TestPoseCanaries(unittest.TestCase):
    """The differential must fail when only the fast path is wrong."""

    def test_catches_a_translate_error_on_the_fast_path(self):
        from diff_support import assert_catches
        orig = sys.modules["scena.shapes"]._translate_point_float

        def skewed(p, dx=None, dy=None):
            return orig(p, None if dx is None else dx * 1.001, dy)

        assert_catches(self, "test_diff_pose.TestPoseFastVsBatched.test_same_pose_after_every_step",
                       [("scena.shapes", "_translate_point_float", skewed)],
                       "a 0.1 % translate error on the A1 path")

    def test_catches_an_absolute_write_error_on_the_fast_path(self):
        # ``_takein_xy_float`` is A1-only (move_to on the fast branch); a helper
        # both paths share would move both twins alike and prove nothing.
        from diff_support import assert_catches
        orig = sys.modules["scena.shapes"]._takein_xy_float

        def skewed(point, x=None, y=None):
            return orig(point, x=None if x is None else x + 0.01, y=y)

        assert_catches(self, "test_diff_pose.TestPoseFastVsBatched.test_same_pose_after_every_step",
                       [("scena.shapes", "_takein_xy_float", skewed)],
                       "an absolute-write error on the A1 path")


if __name__ == "__main__":
    unittest.main()
