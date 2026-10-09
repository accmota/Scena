"""Verb sequences against the affine shadow (geometry campaign, H1).

The geometry contract (``test_geometry_contract``) applies one verb to a fresh
subject. Here a subject starts in any base state (flipped, turned past a full
turn, scaled to ``MIN_SCALE``, degenerate, names crossed, copied across
models, cloned, mid-tween, parked, collidable, drawn), may carry a link (a
field, a point part, the whole object, a chain, or be the source of another
shape's link), and runs a **sequence** of pose verbs. After every step the
composed map of the steps must hold on every point part, the drawn set, the
heading (full turns kept; Q1 flips; Q2 timed ``rotate_to``), the scale, the
flip flags, the hit test, the collision prims, ``.box`` and the cull AABB
(``geom_shadow``). A refused step changes nothing.

Layers (Testing Design — Geometry campaign):

* ``TestShadowArray.test_quick_array`` — a 2-wise covering array over
  family × base × link × verb × verb × read order × execution twin × warmth
  (the model of each family taken in turn): every key it finds must be in
  ``geom_campaign_known.SHADOW``.
* ``TestShadowArray.test_full_arrays`` (gate / deep profiles) — a 2-wise
  array over every kind × model, plus a 3-wise array over the family-level
  axes. Every found key is known, and every known pattern is found (a fixed
  bug cannot stay listed). Reach: every axis value ran.
* ``TestShadowMachine`` — Hypothesis: a pool of subjects, up to the profile's
  step count, with clones and unlinks as rules.
* ``TestShadowCanaries`` — planted bugs the array must catch.

    python tests/run_tiers.py focused test_geom_sequences
"""
from __future__ import annotations

import fnmatch
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis import settings, strategies as hst  # noqa: E402
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule  # noqa: E402
from hypothesis_support import WorldTracker, fresh_world  # noqa: E402

import covering  # noqa: E402
import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402

FAMILIES = sorted({A.family(k) for k in A.K})
MODELS = {f: sorted(k for k in A.K if A.family(k) == f) for f in FAMILIES}
BASES = list(A.B)
LINKS = list(A.L)
XS = ("normal", "forced_slow", "caches_dropped", "in_batch")
WARMS = list(A.W)
DEEP = hypothesis_support.PROFILE in ("ci", "deep")


def _axes(kinds):
    return [("K", kinds), ("V1", S.STEP_NAMES), ("V2", S.STEP_NAMES), ("B", BASES),
            ("L", LINKS), ("W", WARMS), ("R", list(A.R)), ("X", list(XS))]


# Minimal repros of every listed finding (geom_campaign_known.SHADOW): a
# covering array reaches a three-way cell only by chance, so the full run
# always includes these, and each stays as a regression cell after its fix.
PINNED = [
    ("Rect spine cap", "rotated", "none", ["flip_x", "flip_y"]),             # Q1
    ("Rect center_wh", "rotated", "none", ["rotate_to timed", "move_by"]),   # Q2
    ("Ellipse center_wh noangle", "degenerate", "none", ["flip_x", "flip_y"]),  # GX1
    ("Line point_point", "degenerate", "none", ["flip_x", "move_by"]),       # GX2
    ("Line tangent_angle", "degenerate", "none", ["flip_y", "move_by"]),     # GX3
    ("Line tangent_point", "mid_tween", "none", ["move_by timed", "rotate_by"]),  # GX4
    ("Line center_length", "fresh", "part", ["scale_by timed", "move_by"]),  # GX4 (linked center)
    ("Svg", "min_scale", "none", ["scale_to", "scale_by about"]),           # GX5
]


def _run_pinned(reach: A.Reach):
    found = {}
    with fresh_world() as w:
        for kind, base, link, steps in PINNED:
            found.update(S.run_cell(w, kind, base, link, steps, reach=reach) or {})
    return found


def _run(rows, family_level: bool, reach: A.Reach):
    found = {}
    with fresh_world() as w:
        for n, row in enumerate(rows):
            kind = row["K"]
            if family_level:
                models = MODELS[kind]
                kind = models[n % len(models)]
            out = S.run_cell(w, kind, row["B"], row["L"], [row["V1"], row["V2"]],
                             read=row["R"], x=row["X"], warm=row["W"], reach=reach)
            if out:
                found.update(out)
    return found


def _unknown(found, known):
    return sorted(k for k in found if not any(fnmatch.fnmatch(k, p) for p in known))


def _stale(found, known):
    return sorted(p for p in known if not any(fnmatch.fnmatch(k, p) for k in found))


def _fmt(keys, found):
    return "\n  ".join(f"{k}  {found.get(k, '')}"[:300] for k in keys[:40])


class TestShadowArray(unittest.TestCase):
    def _reach_ok(self, reach, kind_axis, kinds):
        axes = {kind_axis: kinds, "B": BASES, "L": LINKS, "R": list(A.R), "X": list(XS),
                "W": WARMS}
        missing = reach.missing(axes)
        self.assertFalse(missing, f"axis values no cell ran (vacuous): {missing}")
        ran = [v for v in S.STEP_NAMES if reach.hits[("V", v)]]
        self.assertEqual(sorted(ran), sorted(S.STEP_NAMES), "verbs that never ran unrefused")

    def test_quick_array(self):
        rows = covering.covering_array(_axes(FAMILIES), 2)
        reach = A.Reach()
        found = _run(rows, True, reach)
        found.update(_run_pinned(reach))
        new = _unknown(found, KNOWN.SHADOW)
        self.assertFalse(new, f"new shadow violations (triage, then fix or list):\n  {_fmt(new, found)}")
        self._reach_ok(reach, "F", FAMILIES)

    def test_full_arrays(self):
        if not DEEP:
            self.skipTest("full arrays run in the gate and deep tiers")
        reach = A.Reach()
        found = _run(covering.covering_array(_axes(sorted(A.K)), 2), False, reach)
        found.update(_run(covering.covering_array(_axes(FAMILIES), 3), True, reach))
        found.update(_run_pinned(reach))
        new = _unknown(found, KNOWN.SHADOW)
        stale = _stale(found, KNOWN.SHADOW)
        self.assertFalse(new, f"new shadow violations:\n  {_fmt(new, found)}")
        self.assertFalse(stale, f"known patterns nothing matches (fixed: remove them): {stale}")
        self._reach_ok(reach, "K", sorted(A.K))


class ShadowMachine(RuleBasedStateMachine):
    """Subjects in any base state run any verbs; clones and unlinks join the pool."""

    def __init__(self):
        super().__init__()
        self.world = WorldTracker()
        G.reset_clock()
        self.pool = []          # (kind, obj, shadow, link)
        self.found = {}

    @initialize(kind=hst.sampled_from(sorted(A.K)), base=hst.sampled_from(BASES),
                link=hst.sampled_from(LINKS))
    def first(self, kind, base, link):
        self.new_subject(kind, base, link)

    @rule(kind=hst.sampled_from(sorted(A.K)), base=hst.sampled_from(BASES),
          link=hst.sampled_from(LINKS))
    def new_subject(self, kind, base, link):
        if len(self.pool) >= 4:
            return
        if base == "mid_tween" and any(sh.pending_turn for _k, _o, sh, _l in self.pool):
            return              # its half-settle would advance another subject's motion
        made = S.make_subject(self.world, kind, base, link)
        if made is None or isinstance(made, dict):
            return              # base findings are the array's business
        obj, shadow, lk = made
        self.pool.append((kind, obj, shadow, lk))

    @rule(i=hst.integers(0, 3), step=hst.sampled_from(S.STEP_NAMES),
          read=hst.sampled_from(list(A.R)))
    def step(self, i, step, read):
        if not self.pool:
            return
        kind, obj, shadow, lk = self.pool[i % len(self.pool)]
        t0 = G.clock.time
        bad = S.run_step(obj, kind, shadow, lk, step, read)
        if G.clock.time != t0:
            # The settle ran every motion in the pool: each other shadow's
            # in-flight turn finished too. Only when the clock moved: a timed
            # step on a parked subject, or one refused up front, settles nothing.
            for _k, o2, sh2, _l in self.pool:
                if o2 is not obj:
                    sh2.settle()
        for k, v in bad.items():
            if not any(fnmatch.fnmatch(k, p) for p in KNOWN.SHADOW):
                raise AssertionError(f"{k}: {v}")
        if bad:
            self.pool.remove((kind, obj, shadow, lk))     # a known break ends that subject

    @rule(i=hst.integers(0, 3))
    def clone(self, i):
        if not self.pool or len(self.pool) >= 4:
            return
        kind, obj, shadow, lk = self.pool[i % len(self.pool)]
        if G.is_box(obj):
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            c = self.world.track(obj.clone())
        # The clone reads like its source now, and is free from here on.
        sp, cp = G.point_parts(obj), G.point_parts(c)
        for n, f in sp.items():
            if n in cp:
                a, b = G.safe(f), G.safe(cp[n])
                if not isinstance(a, G.ReadError) and not A.close_xy(a, b, 1e-5):
                    raise AssertionError(f"{kind} | clone | {n}: {b} vs {a}")
        self.pool.append((kind, c, S.Shadow(c, kind), A.LinkCtx("none")))

    @rule(i=hst.integers(0, 3))
    def unlink(self, i):
        if not self.pool:
            return
        kind, obj, shadow, lk = self.pool[i % len(self.pool)]
        if lk.name in ("none", "source"):
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            before = S.snapshot(obj)
            obj.unlink_all()
        diff = S.compare_snapshots(before, S.snapshot(obj))
        if diff:
            raise AssertionError(f"{kind} | unlink_all | moved {diff}")
        idx = self.pool.index((kind, obj, shadow, lk))
        self.pool[idx] = (kind, obj, shadow, A.LinkCtx("none"))

    def teardown(self):
        self.world.teardown(strict=False)


class TestShadowMachine(ShadowMachine.TestCase):
    settings = settings(max_examples=max(10, settings().max_examples // 4))


class TestShadowCanaries(unittest.TestCase):
    """Planted bugs the quick array must catch (SCENA_CANARIES)."""

    def _catch(self, patches, what):
        from diff_support import assert_catches
        assert_catches(self, "test_geom_sequences.TestShadowArray.test_quick_array", patches, what)

    def test_catches_a_rotation_only_flip(self):
        from scena import RegularPolygon
        from scena.shapes import Shape
        self._catch([(RegularPolygon, "_mirror_geometry", Shape._mirror_geometry)],
                    "RegularPolygon flip through the generic rotation mirror")

    def test_catches_a_scale_that_forgets_its_pivot(self):
        import scena.shapes as SH

        def no_pivot(x, y, cx, cy, factor):
            return x * factor, y * factor
        self._catch([("scena.shapes", "_scale_xy", no_pivot)], "scale about the origin")

    def test_catches_a_clone_that_drops_the_pose(self):
        from scena.entity import Graphic
        self._catch([(Graphic, "_clone_pose_from", lambda self, source: None)],
                    "clone leaves the pose at its defaults")


if __name__ == "__main__":
    unittest.main()
