"""Phase-1 probes of the geometry campaign: one deterministic probe per suspect.

Every drift candidate that reading the code turned up, and every finding a
campaign harness reported, has a probe here written from the **contract**
(the owning design doc), not from what the code does. A probe that fails on
HEAD is listed in ``geom_campaign_known.PROBES`` with its finding and the phase
that fixes it; a listed probe must still fail, and one that passes fails the
suite ("fixed: remove it from PROBES"), so the list only shrinks. After its
fix a probe stays as the finding's regression test.

Suspects cleared by a probe stay too (the probe is the evidence):

* ``_ensure_scalar_anchor`` swapping an anchor type on a cross-model copy does
  not freeze an outside formula that reads ``angle``
  (``test_cross_model_copy_keeps_angle_readers``);
* a reversed Track view's own ``_rotation`` is a dead store: its collision key
  follows the host (``test_reversed_view_collision_follows_the_host``).

    python tests/run_tiers.py focused test_geom_probes
"""
from __future__ import annotations

import functools
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world  # noqa: E402

import geom_axes as A  # noqa: E402
import geom_campaign_known as KNOWN  # noqa: E402
import geometry_support as G  # noqa: E402
from scena import (  # noqa: E402
    Circle, Ellipse, Line, Point, Rect, RegularPolygon, State, Text, Track, canvas,
)
from scena.state import CallableAssignError, LinkedAttributeError  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def probe(pid):
    """Run the probe; if ``pid`` is listed as known-broken, it must still fail."""
    def deco(fn):
        @functools.wraps(fn)
        def run(self):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if pid not in KNOWN.PROBES:
                    return fn(self)
                try:
                    fn(self)
                except AssertionError:
                    return
                self.fail(f"probe {pid} passes now: remove it from geom_campaign_known.PROBES "
                          f"({KNOWN.PROBES[pid]})")
        return run
    return deco


class _World(unittest.TestCase):
    def setUp(self):
        self._w = fresh_world()
        self.w = self._w.__enter__()
        G.reset_clock()

    def tearDown(self):
        self._w.__exit__(None, None, None)

    def t(self, obj):
        return self.w.track(obj)


def _xy(p):
    return (float(p.x), float(p.y))


class TestContractDecisions(_World):
    """Q1-Q5 and GR17 through a link (Testing Design — Geometry campaign)."""

    @probe("Q1")
    def test_q1_flip_applies_to_the_unwrapped_heading(self):
        for anchor in ("cap", "square", "side_left", "side_right"):
            r = self.t(Rect(p1=(0, 0), p2=(40, 0), height=12, anchor=anchor))
            r.rotate_by(400)
            r.flip_x = True
            self.assertAlmostEqual(float(r.angle), -220.0, msg=anchor)
            r.flip_x = False
            self.assertAlmostEqual(float(r.angle), 400.0, msg=anchor)
            fresh = self.t(Rect(p1=(0, 0), p2=(40, 0), height=12, anchor=anchor))
            fresh.flip_x = True
            self.assertAlmostEqual(float(fresh.angle), 180.0, msg=anchor)

    @probe("Q2")
    def test_q2_timed_rotate_to_ends_on_the_target(self):
        r = self.t(Rect(center=(0, 0), width=10, height=4))
        r.rotate_by(400)
        r.rotate_to(30, time=0.2)
        G.settle(1.0)
        self.assertAlmostEqual(float(r.angle), 30.0)

    @probe("Q2-camera")
    def test_q2_camera_timed_rotate_to_ends_on_the_target(self):
        try:
            canvas.rotate_to(400)
            canvas.rotate_to(30, time=0.2)
            G.settle(1.0)
            self.assertAlmostEqual(float(canvas.rotation), 30.0)
        finally:
            canvas.rotate_to(0)

    def test_q4_a_flip_does_not_mirror_a_running_turn(self):
        r = self.t(Rect(center=(0, 0), width=10, height=4))
        r.rotate_by(90, time=1.0)
        G.settle(0.5)
        mid = float(r.angle)
        r.flip_x = True
        G.settle(1.0)
        self.assertAlmostEqual(float(r.angle), 180.0 - mid + (90.0 - mid), places=6)

    def _relational(self):
        return [k for k in G.KINDS if k.split()[0] in ("Line", "Ellipse")
                and G.is_relational(A.build(k))]

    def _rigid_after(self, obj, kind):
        """move / rotate / scale are the rigid maps (Q3b: plain geometry)."""
        c0 = G.center_of(obj)
        p = {n: f() for n, f in G.point_parts(obj).items()}
        obj.move_by(7, -3)
        obj.rotate_by(33)
        obj.scale_by(1.5)
        c1 = (c0[0] + 7, c0[1] - 3)
        for n, f in G.point_parts(obj).items():
            if n.startswith("box.") or n not in p:
                continue
            want = G.scaled(G.turned((p[n][0] + 7, p[n][1] - 3), c1, 33), c1, 1.5)
            self.assertTrue(A.close_xy(f(), want, 1e-6), f"{kind}: {n} {f()} want {want}")

    @probe("Q3b-unlink_all")
    def test_q3b_unlink_all_makes_a_relational_shape_free(self):
        for kind in self._relational():
            obj = self.t(A.build(kind))
            obj.unlink_all()
            self.assertFalse(G.is_relational(obj), f"{kind} keeps {obj.model}")
            self._rigid_after(obj, kind)

    @probe("Q3b-destroy")
    def test_q3b_a_destroyed_reference_makes_it_free(self):
        for kind in self._relational():
            obj = self.t(A.build(kind))
            obj._ref.destroy()
            self.assertFalse(G.is_relational(obj), f"{kind} keeps {obj.model}")
            self._rigid_after(obj, kind)

    @probe("Q3b-force")
    def test_q3b_force_leaves_no_hybrid(self):
        e = self.t(A.build("Ellipse from_rect"))
        e.rotate_by(20, force=True)
        self.assertFalse(G.is_relational(e))
        linked = [n for n in ("center", "width", "height", "angle")
                  if getattr(e[n], "_link", None) is not None
                  or getattr(getattr(e, n, None), "_link", None) is not None]
        self.assertEqual(linked, [], "a forced verb left parts following the Rect")

    @probe("Q5")
    def test_q5_state_refuses_functions(self):
        st = State(name="q5")

        def named():
            return 1
        for fn in (named, self.setUp, print, len):
            with self.assertRaises(CallableAssignError, msg=repr(fn)):
                setattr(st, "f", fn)
        st.k = int          # a class is a value (a kind to build later)
        st.v = 3
        self.assertEqual(st.v, 3)

    @probe("GR17-link")
    def test_gr17_a_linked_angle_publishes_the_pose_store(self):
        st = State(name="gr17")
        st.a = 0.0
        for kind in ("RegularPolygon center_radius", "Rect center_wh", "Ellipse center_wh",
                     "Square center_length", "Line center_length"):
            obj = self.t(A.build(kind))
            obj["angle"] @= lambda: st.a
            for v in (70.0, 120.0):
                st.a = v
                self.assertAlmostEqual(float(obj.angle), v)
                self.assertAlmostEqual(float(obj._rotation), v, msg=f"{kind}: store lags")


class TestHarnessFindings(_World):
    """GX findings: the minimal repro of each (Testing Design, catalogue GX)."""

    @probe("GX1")
    def test_gx1_a_tall_ellipse_flip_mirrors_each_focus(self):
        e = self.t(Ellipse(center=(3, -2), width=10, height=30, angle=17))
        f1, f2 = _xy(e.fp1), _xy(e.fp2)
        e.flip_x = True
        self.assertTrue(A.close_xy(_xy(e.fp1), G.mirrored(f1, (3, -2), "x")))
        self.assertTrue(A.close_xy(_xy(e.fp2), G.mirrored(f2, (3, -2), "x")))

    @probe("GX2")
    def test_gx2_a_zero_length_line_flips_its_heading(self):
        ln = self.t(Line(p1=(0, 0), p2=(10, 0)))
        ln.rotate_by(17)
        ln.p2 = _xy(ln.p1)
        h = float(ln.angle)
        ln.flip_x = True
        self.assertAlmostEqual(float(ln.angle), 180.0 - h)

    @probe("GX3")
    def test_gx3_a_zero_length_tangent_line_refuses_a_flip(self):
        c = self.t(Circle(center=(0, 0), radius=9))
        ln = self.t(Line(circle=c, at_angle=30, length=20))
        ln.length = 0
        with self.assertRaises(LinkedAttributeError):
            ln.flip_y = True

    @probe("GX4")
    def test_gx4_a_timed_verb_refuses_where_the_instant_one_does(self):
        st = State(name="gx4")
        st.x, st.k = 0.0, 1.0
        cases = []
        c = self.t(Circle(center=(0, 0), radius=9))
        cases.append(("tangent_point", self.t(Line(circle=c, from_point=(30, 0), side="left"))))
        q = self.t(Rect(center=(0, 0), width=5, height=3))
        q["scale"] @= lambda: st.k
        cases.append(("linked scale", q))
        sp = self.t(Rect(p1=(0, 0), p2=(10, 0), height=3, anchor="cap"))
        sp["p1"] @= lambda: (st.x, 0)
        cases.append(("spine linked p1", sp))
        lc = self.t(Line(center=(0, 0), length=20, angle=10))
        lc["center"] @= lambda: (st.x, 0)
        cases.append(("line linked center", lc))
        verbs = {
            "move_by": (lambda o: o.move_by(7, -3), lambda o: o.move_by(7, -3, time=0.2)),
            "move_to": (lambda o: o.move_to(5, 5), lambda o: o.move_to(5, 5, time=0.2)),
            "rotate_by": (lambda o: o.rotate_by(33), lambda o: o.rotate_by(33, time=0.2)),
            "scale_by": (lambda o: o.scale_by(1.5), lambda o: o.scale_by(1.5, time=0.2)),
            "scale_to": (lambda o: o.scale_to(2), lambda o: o.scale_to(2, time=0.2)),
        }
        wrong = []
        for name, obj in cases:
            for verb, (instant, timed) in verbs.items():
                try:
                    instant(obj)
                    refused = False
                except LinkedAttributeError:
                    refused = True
                if not refused:
                    continue        # the instant verb ran: nothing to compare
                try:
                    timed(obj)
                    wrong.append(f"{name}: {verb}(time=) accepted (instant refuses)")
                except LinkedAttributeError:
                    pass
                try:
                    G.settle(1.0)
                except LinkedAttributeError:
                    wrong.append(f"{name}: {verb}(time=) raised from a tick")
                G.reset_clock()
        self.assertEqual(wrong, [])

    @probe("GX5")
    def test_gx5_a_pose_zoom_kind_below_min_scale_stays_similar(self):
        from scena.validate import MIN_SCALE
        s = self.t(A.build("Svg"))
        s.scale_to(MIN_SCALE * 0.8)
        c0 = G.center_of(s)
        s.scale_by(1.5, about=(50.0, -20.0))
        want = G.scaled(c0, (50.0, -20.0), 1.5)
        self.assertTrue(A.close_xy(G.center_of(s), want, 1e-6), f"{G.center_of(s)} want {want}")

    @probe("GX6")
    def test_gx6_a_link_during_a_running_motion_is_refused_at_install(self):
        r = self.t(Rect(center=(0, 0), width=10, height=4))
        src = self.t(r.clone())
        r.rotate_by(90, time=1.0)
        G.settle(0.3)
        with self.assertRaises(LinkedAttributeError):
            r @= lambda: src
        G.settle(1.0)           # nothing raises from a tick

    @probe("GX7")
    def test_gx7_a_write_to_a_point_a_linked_heading_turns_keeps_pulling(self):
        st = State(name="gx7")
        st.a = 0.0
        ln = self.t(Line(p1=(0, 0), p2=(10, 0)))
        ln["angle"] @= lambda: st.a
        ln.p1.x = 1.0                       # before any read
        st.a = 90.0
        twin = self.t(Line(p1=(1, 0), p2=(10, 0)))
        twin.rotate_to(90)
        self.assertTrue(A.close_xy((float(ln.p1.x), float(ln.p1.y)), _xy(twin.p1)),
                        f"{_xy(ln.p1)} vs {_xy(twin.p1)}")


class TestFamilyFindings(_World):
    """Findings of the family subjects (H6)."""

    @probe("GX13")
    def test_gx13_an_anchored_caption_takes_one_placement_link(self):
        st = State(name="gx13")
        st.a, st.c = (-17.0, -1.0), (-16.0, 1.0)
        t = self.t(Text("geo", top_left=(0, 0)))
        t["top_left"] @= lambda: st.a
        with self.assertRaises((LinkedAttributeError, TypeError, AttributeError)):
            t["center"] @= lambda: st.c


class TestDriftCandidates(_World):
    """Suspects from reading the code; each probe states the contract."""

    def test_about_the_center_is_the_default_pivot(self):
        """Every "about centre?" test (15 sites, 3 through ``_about_is_pose_center``):
        a pivot exactly on the center, or within 1e-13 of it, gives the default result."""
        bad = []
        for kind in sorted(A.K):
            for verb in ("rotate_by", "scale_by"):
                for off in (0.0, 1e-13):
                    a, b = A.build(kind), A.build(kind)
                    if G.is_box(a) and verb == "scale_by":
                        continue
                    c = G.center_of(a)
                    try:
                        getattr(a, verb)(33 if verb == "rotate_by" else 1.5)
                        getattr(b, verb)(33 if verb == "rotate_by" else 1.5, about=(c[0] + off, c[1]))
                    except LinkedAttributeError:
                        continue
                    if not G.same_set(G.drawn(a), G.drawn(b), 1e-6):
                        bad.append((kind, verb, off))
                    for o in (a, b):
                        A._destroy(o)
        self.assertEqual(bad, [])

    def test_fast_turns_keep_angle_formulas_fresh(self):
        """Circle and RegularPolygon store a fast turn raw; Ellipse and Rect through the slot."""
        for kind in ("Circle center_radius", "RegularPolygon center_radius", "Ellipse center_wh",
                     "Rect center_wh", "Line point_point", "Square center_length"):
            obj = self.t(A.build(kind))
            pin = self.t(Point(0, 0))
            pin["angle"] @= lambda: obj.angle
            pin.angle
            obj.rotate_by(33)
            self.assertAlmostEqual(float(pin.angle), float(obj.angle), msg=kind)
            obj.angle = float(obj.angle) + 10
            self.assertAlmostEqual(float(pin.angle), float(obj.angle), msg=kind)

    def test_box_copy_takes_values_not_links(self):
        """``Box._takein_impl`` copies through ``_init_scalar``: a linked source copies its value."""
        from scena import Box
        st = State(name="boxcopy")
        st.w = 30.0
        src = Box(center=(0, 0), width=20, height=10)
        src["width"] @= lambda: st.w
        dst = Box(center=(5, 5), width=4, height=4)
        dst << src
        st.w = 50.0
        self.assertAlmostEqual(float(dst.width), 30.0)

    def test_cross_model_copy_keeps_angle_readers(self):
        r = self.t(Rect(p1=(0, 0), p2=(10, 5), angle=10))
        spine = self.t(Rect(p1=(0, 0), p2=(10, 10), height=3, anchor="cap"))
        pin = self.t(Point(0, 0))
        pin["angle"] @= lambda: r.angle
        pin.angle
        r << spine
        r.rotate_by(20)
        self.assertAlmostEqual(float(pin.angle), float(r.angle))

    def test_reversed_view_collision_follows_the_host(self):
        from scena.collision import _collision_pose_key
        t = self.t(Track.eight(width=60, height=30, center=(0, 0)))
        v = t.reversed()
        k0 = _collision_pose_key(v)
        t.rotate_by(40)
        self.assertNotEqual(_collision_pose_key(v), k0)


if __name__ == "__main__":
    unittest.main()
