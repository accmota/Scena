"""Differential tests: collision fast paths vs reference paths / brute force.

``test_sys_hyp_collision`` already checks the broad phase, proxy AABBs and
contact bookkeeping against oracles over real frames. This suite covers what
it states it does not:

* **Snapshot caches** (#1) — ``snapshot_shape`` with a cache owner (exact hit,
  or translate-in-place reuse) and the collider-level ``_world_prims`` vs
  ``_snapshot_shape_uncached``, after random pose / size sequences. D2 lived
  here (a translate shifted Prims a polygon cache still filed under the old
  key). Tolerance ``1e-6`` absolute: repeated translation adds float drift.
  Prims compare as a multiset by nearest match, never a raw-float sort (D10).
* **Proxy ⊇ exact** (#16) — the cheap proxy AABB (closed form, and the
  collider's translate-only update) always contains the exact prim bounds.
* **Narrow phase** (#11) — layer-1 closed forms (circle / AABB pairs) vs
  ``_sat_prims``: same hit / no-hit away from exact touching, same depth;
  normals compared only where they are not a tie (concentric circles, a
  circle center inside a box, equal AABB overlaps).
* **Sweeps / TOI** (#12) — ``_toi_prim_sets`` (closed-form fast TOI, or
  conservative advancement → bisection) vs a **brute-force sweep**: sample the
  motion at 1/400 steps and run the exact static test at each sample. The
  sweep may not miss a sampled hit, may not report a hit the samples never
  see (beyond grazing), and its time must fall within one sample of the first
  sampled hit (bisection brackets to 1/96 of the motion, hence its own bound).
* **Incremental ``@collide`` enroll** (#15) — the tag index kept up to date
  per spawn / tag / untag / collidable / destroy equals a full
  ``_refresh_pair_enrollments`` rebuild, and every collider's
  ``_pair_targets`` equals the set the registered pairs imply.

    python -m unittest tests.test_diff_collision -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_same, assert_same_prims  # noqa: E402
from hypothesis_support import quiet  # noqa: E402
from hypothesis import assume, example, given, note, strategies as hst  # noqa: E402

import scena  # noqa: E402,F401
from scena import Circle, Ellipse, Polygon, Rect, RegularPolygon, Square, collide  # noqa: E402
from test_diff_pose import MODELS, OPS, apply, _outcome  # noqa: E402

col = sys.modules["scena.collision"]  # the module (``scena.collision`` is a facade)
Prim, PrimKind = col.Prim, col.PrimKind


def _prims_key(prims):
    return sorted(
        (p.kind.name, tuple(p.aabb), tuple(p.params), tuple(tuple(v) for v in (p.verts or ())))
        for p in prims
    )


def _assert_prims(tc, got, want, what):
    """Same prims as a multiset, within the translate-drift tolerance.

    Not ``sorted(_prims_key(...))``: an ulp of drift reorders tied prims (D10).
    """
    assert_same_prims(tc, got, want, what, rel=1e-9, abs_=1e-6)


def _contains(outer, inner, eps=1e-6):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


# Collision-relevant kinds (Text is not collidable geometry here).
COLLISION_MODELS = sorted(m for m in MODELS if not m.startswith("Text"))

SIZE_OPS = hst.one_of(
    hst.tuples(hst.just("size"), hst.sampled_from(["radius", "width", "height", "length", "side",
                                                   "major_axis"]),
               hst.integers(1, 40).map(float)),
    # A → B → A: caches keyed by a past state are wrong only when the state
    # comes BACK (D2). Random walks almost never revisit exact vertices, so
    # generate the round trip on purpose.
    # Write one Defining Point part directly (p1 / p2 / fp1 / perimeter_point
    # / top_left / vertex …): keys must cover every Defining input (R7).
    hst.tuples(hst.just("defining_point"), hst.integers(0, 3),
               hst.integers(-20, 20).map(float), hst.integers(-20, 20).map(float)),
    hst.tuples(hst.just("excursion"), hst.integers(-60, 60).map(float),
               hst.integers(-60, 60).map(float), hst.sampled_from([0.0, 10.0, 90.0])),
)


class TestSnapshotCaches(unittest.TestCase):
    @given(model=hst.sampled_from(COLLISION_MODELS),
           ops=hst.lists(hst.one_of(OPS.filter(lambda o: not o[0].startswith("tween") and o[0] != "tick"),
                                    SIZE_OPS), min_size=1, max_size=14))
    # D10: translate drift of 1 ulp flipped a raw-float sort of the two arc
    # wedges, so the oracle compared wedge A with wedge B (harness bug).
    @example(model="Circle arc", ops=[("move_face", -27.0, 3.0), ("move_to", 0.0, 0.0)])
    # R7 on purpose: a Defining write that leaves center / heading / scale alone.
    # The flip path used to reach it; since flips turn the pose heading (G14)
    # it no longer does, and the canary went blind.
    @example(model="Ellipse focal_points", ops=[("size", "major_axis", 30.0)])
    @example(model="Circle two_points", ops=[("defining_point", 1, 6.0, 2.0)])
    @example(model="Circle center_perimeter", ops=[("defining_point", 1, -5.0, 9.0)])
    def test_cached_equals_uncached(self, model, ops):
        with quiet():
            obj = MODELS[model]()
        system = col.get_collision_system()
        owner = col.Collider([obj], _identity_shape=obj)
        try:
            for i, op in enumerate(ops):
                note(f"step {i}: {op}")
                with quiet():
                    if op[0] == "excursion":
                        _, dx, dy, wiggle = op
                        obj.move_by(dx, dy)
                        col.snapshot_shape(obj, cache_owner=owner)      # translate reuse
                        system._update_proxy(owner, commit_motion=False)
                        system._world_prims(owner)                      # translate reuse
                        obj.move_by(-dx, -dy)
                        if wiggle:
                            obj.rotate_by(wiggle)
                            obj.rotate_by(-wiggle)                      # forces a rebuild
                    elif op[0] == "defining_point":
                        from scena import Point
                        names = [n for n in (getattr(obj, "_defining_part_names", ()) or ())
                                 if isinstance(getattr(obj, n, None), Point)]
                        if not names:
                            continue
                        pt = getattr(obj, names[op[1] % len(names)])
                        _outcome(pt._takein, (float(pt.x) + op[2], float(pt.y) + op[3]))
                    elif op[0] == "size":
                        if op[1] not in getattr(type(obj), "_setattr_route", {}):
                            continue
                        _outcome(setattr, obj, op[1], op[2])
                    else:
                        _outcome(apply, obj, op)
                truth = col._snapshot_shape_uncached(obj, cache_owner=None)
                what = f"{model} step {i} {op}"
                _assert_prims(self, col.snapshot_shape(obj, cache_owner=owner), truth,
                              what + " (snapshot_shape cache)")
                # Engine order: the proxy refresh runs before _world_prims
                # (_world_prims stamps _proxy_key; calling it first would make
                # the next _update_proxy skip a real change).
                system._update_proxy(owner, commit_motion=False)
                _assert_prims(self, system._world_prims(owner), truth, what + " (_world_prims)")
                exact = col._prims_bounds_aabb(truth) if truth else None
                if exact is not None:
                    proxy = col._proxy_aabb_for_shape(obj)
                    if proxy is not None:
                        self.assertTrue(_contains(proxy, exact),
                                        f"{what}: proxy {proxy} does not contain exact {exact}")
                    if owner._proxy_valid:
                        self.assertTrue(_contains(tuple(owner._proxy), exact),
                                        f"{what}: collider proxy {owner._proxy} does not contain {exact}")
        finally:
            obj.destroy()


class TestPrimsOracle(unittest.TestCase):
    """D10: the prims oracle must not pair prims by sorting raw floats.

    The translate fast path drifts by an ulp. When two prims tie on the first
    sort fields, that ulp reorders them and a sorted compare pairs different
    prims — a false "cache diverges" on correct output.
    """

    @staticmethod
    def _poly(verts):
        xs = [x for x, _ in verts]
        ys = [y for _, y in verts]
        return Prim(PrimKind.POLY, (min(xs), min(ys), max(xs), max(ys)), (), list(verts))

    def _wedges(self, nudge=0.0):
        # The two halves of a 180° arc (Circle arc after move_face → move_to):
        # equal aabb min-x, so a sort falls through to the next field.
        a = self._poly([(0.0, 0.0), (-8.94495361206257, 0.99388), (-0.99388, -8.94495361206257)])
        b = self._poly([(0.0, 0.0), (0.99388, 8.94495361206257), (-8.94495361206257 + nudge, 0.99388)])
        return a, b

    def test_ulp_drift_that_reorders_a_sort_still_matches(self):
        a, b = self._wedges()
        a2, b2 = self._wedges(nudge=-4e-15)   # b's min-x now sorts before a's
        self.assertNotEqual([k[1] for k in _prims_key([a, b])],
                            [k[1] for k in _prims_key([a2, b2])])   # the trap is armed
        _assert_prims(self, [a, b], [a2, b2], "ulp drift")
        _assert_prims(self, [b, a], [a2, b2], "ulp drift, other order")

    @given(model=hst.sampled_from(COLLISION_MODELS), seed=hst.integers(0, 2**32 - 1),
           ulps=hst.integers(1, 64), dy=hst.integers(1, 50).map(float))
    def test_class_guard_drift_and_order_never_matter(self, model, seed, ulps, dy):
        """Every model's real prims, shuffled and nudged by a few ulps, match;
        the same prims displaced by 1e-3 do not.

        Each prim gets a twin shifted along y: equal ``aabb`` min-x, the tie
        that let an ulp reorder a sorted compare (D10). Without it no model's
        prims tie and a sort-based oracle passes this guard too.
        """
        import random
        rng = random.Random(seed)
        with quiet():
            obj = MODELS[model]()
        try:
            truth = col._snapshot_shape_uncached(obj, cache_owner=None)
        finally:
            obj.destroy()
        assume(truth)
        truth = truth + [col._copy_translate([p], 0.0, dy)[0] for p in truth]

        def nudge(v, n):
            for _ in range(n):
                v = math.nextafter(v, rng.choice((-math.inf, math.inf)))
            return v

        def moved(p, f):
            return Prim(p.kind, tuple(f(v) for v in p.aabb),
                        tuple(f(v) if isinstance(v, float) else v for v in p.params),
                        None if p.verts is None else [(f(x), f(y)) for x, y in p.verts])

        drifted = [moved(p, lambda v: nudge(v, ulps)) for p in truth]
        rng.shuffle(drifted)
        _assert_prims(self, drifted, truth, f"{model} drift")
        far = [moved(p, lambda v: v + 1e-3) for p in truth]
        with self.assertRaises(AssertionError):
            _assert_prims(self, far, truth, f"{model} displaced")

    def test_real_difference_still_fails(self):
        a, b = self._wedges()
        _, b_far = self._wedges(nudge=-1e-3)
        with self.assertRaises(AssertionError):
            _assert_prims(self, [a, b], [a, b_far], "displaced")
        with self.assertRaises(AssertionError):
            _assert_prims(self, [a, b], [a], "missing prim")
        with self.assertRaises(AssertionError):
            _assert_prims(self, [a, a], [a, b], "duplicate instead of b")


# ---------------------------------------------------------------------------
# Narrow phase: layer-1 closed forms vs SAT
# ---------------------------------------------------------------------------

def _circle(x, y, r):
    return Prim(PrimKind.CIRCLE, (x - r, y - r, x + r, y + r), (x, y, r))


def _aabb(x0, y0, w, h):
    box = (x0, y0, x0 + w, y0 + h)
    return Prim(PrimKind.AABB, box, box)


small = hst.integers(-40, 40).map(float)
size = hst.integers(1, 30).map(float)
circles = hst.builds(_circle, small, small, size)
aabbs = hst.builds(_aabb, small, small, size, size)
fast_prims = hst.one_of(circles, aabbs)


def _separation(pa, pb):
    """Signed gap between two layer-1 prims (negative = overlap depth)."""
    if pa.kind == PrimKind.CIRCLE and pb.kind == PrimKind.CIRCLE:
        (ax, ay, ar), (bx, by, br) = pa.params, pb.params
        return math.hypot(bx - ax, by - ay) - ar - br
    if pa.kind == PrimKind.AABB and pb.kind == PrimKind.AABB:
        a, b = pa.params, pb.params
        return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])
    c, box = (pa, pb) if pa.kind == PrimKind.CIRCLE else (pb, pa)
    x, y, r = c.params
    b = box.params
    qx, qy = min(max(x, b[0]), b[2]), min(max(y, b[1]), b[3])
    if (qx, qy) == (x, y):  # center inside
        return -r - min(x - b[0], b[2] - x, y - b[1], b[3] - y)
    return math.hypot(x - qx, y - qy) - r


def _normal_is_unique(pa, pb):
    if pa.kind == PrimKind.CIRCLE and pb.kind == PrimKind.CIRCLE:
        (ax, ay, _), (bx, by, _) = pa.params, pb.params
        return math.hypot(bx - ax, by - ay) > 1e-6
    if pa.kind == PrimKind.AABB and pb.kind == PrimKind.AABB:
        a, b = pa.params, pb.params
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        return abs(ox - oy) > 1e-6
    c, box = (pa, pb) if pa.kind == PrimKind.CIRCLE else (pb, pa)
    x, y, _ = c.params
    b = box.params
    return not (b[0] <= x <= b[2] and b[1] <= y <= b[3])


class TestNarrowPhaseLayers(unittest.TestCase):
    @given(pa=fast_prims, pb=fast_prims)
    def test_closed_form_matches_sat(self, pa, pb):
        gap = _separation(pa, pb)
        # _sat_prims has no circle-circle branch (the engine never routes a
        # circle pair there); the closed form is checked against the gap below.
        sat_applies = not (pa.kind == PrimKind.CIRCLE and pb.kind == PrimKind.CIRCLE)
        assume(abs(gap) > 1e-6)  # exactly touching is a tie either way
        fast = col.narrow_phase(pa, pb)
        self.assertEqual(fast is None, gap > 0, f"closed form vs true gap {gap}")
        if fast is not None:
            self.assertAlmostEqual(fast.depth, -gap, places=6)
        if not sat_applies:
            return
        ref = col._sat_prims(pa, pb)
        self.assertEqual(fast is None, ref is None, f"hit disagrees with SAT (gap {gap})")
        if fast is None:
            return
        self.assertAlmostEqual(fast.depth, ref.depth, places=6)
        if _normal_is_unique(pa, pb):
            # SAT rounds its axis to 5 decimals (axis dedupe).
            assert_same(self, tuple(fast.normal), tuple(ref.normal), "normal", abs_=1e-5)


# ---------------------------------------------------------------------------
# Sweeps: every TOI path vs a brute-force sampled sweep
# ---------------------------------------------------------------------------

def _obb(x, y, hw, hh, deg):
    ang = math.radians(deg)
    return Prim(PrimKind.OBB, col._aabb_from_obb(x, y, hw, hh, ang), (x, y, hw, hh, ang))


obbs = hst.builds(_obb, small, small, size, size, hst.integers(0, 179).map(float))
any_prims = hst.one_of(circles, aabbs, obbs)
SAMPLES = 400


def _sampled_first_hit(pas, pbs, dx, dy):
    """(first sampled t with overlap depth > 1e-4, max depth seen) — the oracle."""
    first, deepest = None, 0.0
    for k in range(SAMPLES + 1):
        t = k / SAMPLES
        moved = col._copy_translate(pas, dx * t, dy * t)
        c = col._narrow_any(moved, pbs)
        if c is not None:
            deepest = max(deepest, c.depth)
            if first is None and c.depth > 1e-4:
                first = t
    return first, deepest


class TestSweepsAgainstSampling(unittest.TestCase):
    @given(pa=any_prims, pb=any_prims, dx=hst.integers(-120, 120).map(float),
           dy=hst.integers(-120, 120).map(float))
    def test_toi_matches_sampled_sweep(self, pa, pb, dx, dy):
        assume(math.hypot(dx, dy) > 1.0)
        assume(col._narrow_any([pa], [pb]) is None)  # start apart: a real sweep
        hit = col._toi_prim_sets([pa], [pb], dx, dy)
        first, deepest = _sampled_first_hit([pa], [pb], dx, dy)
        fast = col._is_fast_narrow(pa, pb)
        step = 1.0 / SAMPLES
        slack = step if fast else max(step, 1.0 / col._TOI_BISECT_CAP)
        note(f"fast={fast} hit={hit and hit[0]} first_sample={first} deepest={deepest}")
        if first is not None:
            self.assertIsNotNone(hit, f"sweep missed a hit the samples see at t={first}")
            self.assertLessEqual(hit[0], first + 1e-9, "sweep time is after the first sampled hit")
            self.assertGreaterEqual(hit[0], first - step - slack,
                                    "sweep time is more than one sample before the first hit")
        elif hit is not None:
            # Grazing contacts the samples cannot resolve are allowed.
            self.assertLess(deepest, 0.05, f"sweep hit at t={hit[0]} the samples never see")


# ---------------------------------------------------------------------------
# Incremental @collide enroll vs full rebuild
# ---------------------------------------------------------------------------

TAGS = ("dc_a", "dc_b", "dc_c")
ENROLL_OPS = hst.lists(hst.one_of(
    hst.tuples(hst.just("spawn"), hst.sampled_from(TAGS)),
    hst.tuples(hst.just("tag"), hst.integers(0, 20), hst.sampled_from(TAGS)),
    hst.tuples(hst.just("untag"), hst.integers(0, 20), hst.sampled_from(TAGS)),
    hst.tuples(hst.just("collidable"), hst.integers(0, 20), hst.booleans()),
    hst.tuples(hst.just("park"), hst.integers(0, 20), hst.booleans()),
    hst.tuples(hst.just("destroy"), hst.integers(0, 20)),
    hst.tuples(hst.just("step")),
), min_size=1, max_size=25)


def _index_snapshot(system):
    """Tag → collider set, and tag → indexed collider ids (order-free)."""
    tags = {t: frozenset(id(c) for c in lst) for t, lst in system._tag_colliders.items() if lst}
    index = {t: frozenset(v.keys()) for t, v in system._tag_index.items() if v}
    return tags, index


def _index_positions_ok(system):
    """``_tag_index[tag][id(c)]`` is ``c``'s position in ``_tag_colliders[tag]``."""
    bad = []
    for t, lst in system._tag_colliders.items():
        idx = system._tag_index.get(t, {})
        for pos, c in enumerate(lst):
            if idx.get(id(c)) != pos:
                bad.append((t, pos, idx.get(id(c))))
    return bad


def _expected_targets(system):
    want = {}
    for a, b, *_rest in list(system._pair_handlers) + list(system._resolve_pairs):
        for left in system._handler_colliders(a):
            want.setdefault(id(left), set()).add(b)
        for right in system._handler_colliders(b):
            want.setdefault(id(right), set()).add(a)
    return want


class TestIncrementalEnroll(unittest.TestCase):
    def test_collidable_while_parked_reenrolls_on_resume(self):
        """``collidable = True`` while parked must not skip enroll on resume.

        The flag is already true, so restoring the stashed value is a no-op.
        A full pair refresh still enrolls; resume has to match it.
        """
        col.reset_collision_system()
        system = col.get_collision_system()
        collide("dc_a", "dc_b")(lambda a, b: None)
        body = Circle(center=(0, 0), radius=5, group="dc_a")
        try:
            body.active = False
            body.collidable = True
            body.active = True
            incremental = _index_snapshot(system)
            self.assertIn("dc_a", incremental[0])
            system._refresh_pair_enrollments()
            self.assertEqual(incremental, _index_snapshot(system))
        finally:
            if body.is_alive:
                body.destroy()
            col.reset_collision_system()

    def setUp(self):
        col.reset_collision_system()

    def tearDown(self):
        col.reset_collision_system()

    @given(ops=ENROLL_OPS)
    def test_index_equals_rebuild(self, ops):
        col.reset_collision_system()
        system = col.get_collision_system()
        collide("dc_a", "dc_b")(lambda a, b: None)
        collide("dc_b", "dc_c")(lambda a, b: None)
        bodies = []
        try:
            for i, op in enumerate(ops):
                with quiet():
                    kind = op[0]
                    if kind == "spawn":
                        bodies.append(Circle(center=(len(bodies) * 3, 0), radius=5, group=op[1]))
                    elif kind == "step":
                        system.step()
                    else:
                        if not bodies:
                            continue
                        b = bodies[op[1] % len(bodies)]
                        if not b.is_alive:
                            continue
                        if kind == "tag":
                            b.tag(op[2])
                        elif kind == "untag":
                            b.untag(op[2])
                        elif kind == "collidable":
                            b.collidable = op[2]
                        elif kind == "park":
                            b.active = op[2]
                        else:
                            b.destroy()
                what = f"step {i} {op}"
                self.assertEqual(_index_positions_ok(system), [],
                                 f"tag index positions out of sync after {what}")
                incremental = _index_snapshot(system)
                targets = {id(c): set(c._pair_targets) for c in system._colliders}
                system._refresh_pair_enrollments()
                self.assertEqual(incremental, _index_snapshot(system),
                                 f"tag index differs from a full rebuild after {what}")
                want = _expected_targets(system)
                for c in system._colliders:
                    self.assertEqual(targets[id(c)], want.get(id(c), set()),
                                     f"_pair_targets of {c._identity!r} after {what}")
        finally:
            for b in bodies:
                if b.is_alive:
                    b.destroy()


class TestCollisionCanaries(unittest.TestCase):
    def test_snapshot_suite_catches_poly_cache_aliasing(self):
        from diff_support import assert_catches
        assert_catches(self, "test_diff_collision.TestSnapshotCaches.test_cached_equals_uncached",
                       [("scena.collision", "_clone_prims", lambda prims: prims)],
                       "D2 (poly cache hands out its Prims)")

    def test_snapshot_suite_catches_a_stale_pose_key(self):
        # R7: without Defining-based extras, a focal Ellipse / two-point Circle
        # key misses flips and Defining writes (generic extra reads stale slots).
        from diff_support import assert_catches
        from scena.shapes import Circle as _Circle, Ellipse as _Ellipse
        assert_catches(self, "test_diff_collision.TestSnapshotCaches.test_cached_equals_uncached",
                       [(_Circle, "_collision_pose_extra", None),
                        (_Ellipse, "_collision_pose_extra", None)],
                       "R7 (pose key blind to Defining inputs)")

    def test_oracle_guard_catches_a_sorted_compare(self):
        # D10's class: pairing prims by sorting raw floats. The guard must
        # reject that oracle, or it would pass the bug straight back in.
        from diff_support import assert_catches

        def sorted_compare(tc, got, want, what="", rel=1e-9, abs_=1e-7):
            assert_same(tc, _prims_key(got), _prims_key(want), what, rel=rel, abs_=abs_)

        assert_catches(self, "test_diff_collision.TestPrimsOracle.test_class_guard_drift_and_order_never_matter",
                       [("diff_support", "assert_same_prims", sorted_compare)],
                       "D10 (prims paired by a raw-float sort)")

    def test_sweep_suite_catches_a_late_toi(self):
        from diff_support import assert_catches
        orig = col._toi_fast

        def late(pa, pb, dx, dy):
            hit = orig(pa, pb, dx, dy)
            return None if hit is None else (min(1.0, hit[0] + 0.05), hit[1])

        assert_catches(self, "test_diff_collision.TestSweepsAgainstSampling.test_toi_matches_sampled_sweep",
                       [("scena.collision", "_toi_fast", late)], "a fast TOI 5 % late")


if __name__ == "__main__":
    unittest.main()
