"""
Tier 1 reactive optimization — characterization / golden regression suite.

Written and green against *today's* code before any Tier 1 production change.
Pins geometry probes bit-exactly and engagement ceilings (mark_dirty calls /
cone visits) so each T1.1–T1.6 step can prove: same values, same-or-fewer
invalidation costs, no A2 / outbound-link / effect regressions.

Run::

    python -m pytest tests/test_reactive_tier1_characterization.py -q
"""

from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.shapes import Point, Rect, Circle, Line
from scena.state import (
    Attribute,
    State,
    get_scena_system,
    flush,
)
from scena.events import when, on_change, cleanup_global_event_system


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark_dirty_count(fn) -> int:
    um = get_scena_system().update_manager
    orig = um.mark_dirty
    n = 0

    def wrapped(node):
        nonlocal n
        n += 1
        return orig(node)

    um.mark_dirty = wrapped  # type: ignore[method-assign]
    try:
        fn()
    finally:
        um.mark_dirty = orig  # type: ignore[method-assign]
    return n


def _cone_stats(fn) -> tuple[int, int]:
    """Return (mark_dirty_calls, cone_node_visits) during ``fn``."""
    ss = get_scena_system()
    um = ss.update_manager
    g = ss.dependency_graph
    orig = um.mark_dirty
    calls = 0
    visits = 0

    def wrapped(node):
        nonlocal calls, visits
        calls += 1
        seed = node
        if seed is None:
            return orig(node)
        if isinstance(seed, int):
            seed = g.nodes.get(seed)
            if seed is None:
                return
        seen: set[int] = set()
        stack = [seed]
        while stack:
            cur = stack.pop()
            nid = getattr(cur, "_node_id", None)
            if nid is not None:
                if nid in seen:
                    continue
                seen.add(nid)
            visits += 1
            if nid is None:
                continue
            for dep_id in g.dependents.get(nid, ()):
                dep = g.nodes.get(dep_id)
                if dep is not None:
                    stack.append(dep)
        return orig(node)

    um.mark_dirty = wrapped  # type: ignore[method-assign]
    try:
        fn()
    finally:
        um.mark_dirty = orig  # type: ignore[method-assign]
    return calls, visits


def _probe_bar(bar: Rect) -> tuple[float, float, float]:
    return (float(bar.center.x), float(bar.center.y), float(bar.angle))


def _assert_probes_exact(actual, expected, places_msg: str = ""):
    """Bit-identical float tuples — Tier 1 must not reorder arithmetic."""
    assert len(actual) == len(expected), (
        f"probe length {len(actual)} != {len(expected)} {places_msg}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"probe[{i}] {a!r} != {e!r} {places_msg}"


# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

def deep_binary_tree(levels: int = 4, driver_val: float = 0.0):
    """Binary tree of Rects linked via left/right_square_center (spinning-rects shape)."""
    st = State(name="drv")
    st.t = driver_val
    t = st.t
    root = Rect(center=(500.0, 350.0), width=200.0, height=200.0 / 15)
    root["angle"] @= (lambda t=t: (t * 26.0) % 360.0)
    bars = [root]

    def recurse(nivel: int, parent: Rect) -> None:
        if nivel > levels:
            return
        for side in ("left_square_center", "right_square_center"):
            child = Rect(
                center=(lambda b=parent, s=side: getattr(b, s)),
                width=200.0 / (2 ** nivel),
                height=(200.0 / (2 ** nivel)) / 15,
            )
            child["angle"] @= (
                lambda t=t, n=nivel: (t * 26.0 * ((-1.5) ** n)) % 360.0
            )
            bars.append(child)
            recurse(nivel + 1, child)

    recurse(1, root)
    return st, bars


def linear_chain(n: int = 20):
    st = State(name="chain")
    st.t = 0.0
    t = st.t
    prev = Rect(center=(0.0, 0.0), width=100.0, height=10.0)
    prev["angle"] @= (lambda t=t: (t * 20.0) % 360.0)
    chain = [prev]
    for i in range(n - 1):
        r = Rect(
            center=(lambda b=prev: b.right_square_center),
            width=100.0 * (0.97 ** i),
            height=10.0,
        )
        r["angle"] @= (lambda t=t: (t * 20.0) % 360.0)
        chain.append(r)
        prev = r
    return st, chain


def diamond(width: int = 8):
    st = State(name="dia")
    st.a = 1.0
    a = st.a
    branches = []
    for i in range(width):
        b = Attribute(0.0, attr_name=f"b{i}")
        b @= (lambda a=a: a + 1.0)
        branches.append(b)
    # Sum via pairwise Attribute chain so AST sources resolve from a file.
    # Sink depends on every branch Attribute (each is a Container source via default).
    sink = Attribute(0.0, attr_name="sink")

    def _sum_all(
        b0=branches[0],
        b1=branches[1],
        b2=branches[2],
        b3=branches[3],
        b4=branches[4],
        b5=branches[5],
        b6=branches[6],
        b7=branches[7],
    ):
        return (
            float(b0.value)
            + float(b1.value)
            + float(b2.value)
            + float(b3.value)
            + float(b4.value)
            + float(b5.value)
            + float(b6.value)
            + float(b7.value)
        )

    sink @= _sum_all
    return st, branches, sink


# ---------------------------------------------------------------------------
# Pinned goldens (generated against pre-Tier-1 codebase)
# ---------------------------------------------------------------------------

DEEP_PROBES_T0 = [
    (500.0, 350.0, 0.0),
    (406.6666666666667, 350.0, 0.0),
    (360.0, 350.0, 0.0),
    (336.6666666666667, 350.0, 0.0),
    (325.0, 350.0, 0.0),
    (348.33333333333337, 350.0, 0.0),
    (383.3333333333333, 350.0, 0.0),
    (371.66666666666663, 350.0, 0.0),
    (395.0, 350.0, 0.0),
    (453.33333333333337, 350.0, 0.0),
    (430.00000000000006, 350.0, 0.0),
    (418.33333333333337, 350.0, 0.0),
    (441.66666666666674, 350.0, 0.0),
    (476.6666666666667, 350.0, 0.0),
    (465.0, 350.0, 0.0),
    (488.33333333333337, 350.0, 0.0),
    (593.3333333333334, 350.0, 0.0),
    (546.6666666666667, 350.0, 0.0),
    (523.3333333333334, 350.0, 0.0),
    (511.6666666666667, 350.0, 0.0),
    (535.0, 350.0, 0.0),
    (570.0000000000001, 350.0, 0.0),
    (558.3333333333335, 350.0, 0.0),
    (581.6666666666667, 350.0, 0.0),
    (640.0, 350.0, 0.0),
    (616.6666666666666, 350.0, 0.0),
    (605.0, 350.0, 0.0),
    (628.3333333333333, 350.0, 0.0),
    (663.3333333333334, 350.0, 0.0),
    (651.6666666666667, 350.0, 0.0),
    (675.0, 350.0, 0.0),
]

DEEP_PROBES_T1 = [
    (500.0, 350.0, 26.0),
    (416.1125556787444, 309.08535963301944, 321.0),
    (379.84574414408576, 338.45364454867854, 58.5),
    (367.6541109673803, 318.55870738041637, 272.25),
    (367.1960797835245, 330.2163794698915, 131.625),
    (368.11214215123607, 306.90103529094125, 131.625),
    (392.0373773207912, 358.3485817169407, 272.25),
    (391.57934613693544, 370.0062538064158, 131.625),
    (392.495408504647, 346.6909096274656, 131.625),
    (452.37936721340304, 279.71707471736033, 58.5),
    (440.1877340366976, 259.82213754909816, 272.25),
    (439.7297028528418, 271.4798096385733, 131.625),
    (440.64576522055336, 248.16446545962305, 131.625),
    (464.5710003901085, 299.6120118856225, 272.25),
    (464.1129692062527, 311.2696839750976, 131.625),
    (465.0290315739643, 287.9543397961474, 131.625),
    (583.8874443212555, 390.91464036698056, 321.0),
    (547.620632786597, 420.28292528263967, 58.5),
    (535.4289996098914, 400.3879881143775, 272.25),
    (534.9709684260356, 412.0456602038526, 131.625),
    (535.8870307937473, 388.7303160249024, 131.625),
    (559.8122659633025, 440.17786245090184, 272.25),
    (559.3542347794466, 451.83553454037695, 131.625),
    (560.2702971471583, 428.5201903614267, 131.625),
    (620.1542558559141, 361.54635545132146, 58.5),
    (607.9626226792086, 341.6514182830593, 272.25),
    (607.5045914953528, 353.3090903725344, 131.625),
    (608.4206538630644, 329.9937461935842, 131.625),
    (632.3458890326197, 381.44129261958363, 272.25),
    (631.8878578487638, 393.09896470905875, 131.625),
    (632.8039202164755, 369.7836205301085, 131.625),
]

DEEP_PROBES_T25 = [
    (500.0, 350.0, 65.0),
    (460.5556289042014, 265.4112732099127, 262.5),
    (466.6468512078038, 311.6787000740238, 146.25),
    (486.04780882819654, 298.71539463689976, 140.625),
    (495.0662641174285, 291.3141396549906, 329.0625),
    (477.0293535389646, 306.11664961880894, 329.0625),
    (447.2458935874111, 324.6420055111479, 140.625),
    (456.26434887664306, 317.2407505292387, 329.0625),
    (438.22743829817915, 332.04326049305706, 329.0625),
    (454.464406600599, 219.14384634580153, 146.25),
    (473.8653642209917, 206.18054090867747, 140.625),
    (482.88381951022365, 198.77928592676827, 329.0625),
    (464.84690893175974, 213.58179589058668, 329.0625),
    (435.06344898020626, 232.1071517829256, 140.625),
    (444.0819042694382, 224.7058968010164, 329.0625),
    (426.0449936909743, 239.5084067648348, 329.0625),
    (539.4443710957986, 434.5887267900873, 262.5),
    (545.535593399401, 480.85615365419847, 146.25),
    (564.9365510197938, 467.8928482170744, 140.625),
    (573.9550063090257, 460.4915932351652, 329.0625),
    (555.9180957305618, 475.2941031989836, 329.0625),
    (526.1346357790082, 493.8194590913225, 140.625),
    (535.1530910682402, 486.41820410941335, 329.0625),
    (517.1161804897763, 501.2207140732317, 329.0625),
    (533.3531487921962, 388.3212999259762, 146.25),
    (552.754106412589, 375.3579944888521, 140.625),
    (561.7725617018209, 367.95673950694294, 329.0625),
    (543.735651123357, 382.7592494707613, 329.0625),
    (513.9521911718034, 401.28460536310024, 140.625),
    (522.9706464610354, 393.88335038119106, 329.0625),
    (504.93373588257145, 408.6858603450094, 329.0625),
]

# One deep-tree frame (write st.t, then read every bar): 1 source write +
# 45 ScalarAnchor rotation notifies = the pre-Tier-1 budget of 46.
# These were once raised to 107 / 1097 to fit a regression: after the
# takein -> _takein rename, _resolve_link called the dispatcher, so every
# *pull* of a linked Point re-walked its cone (2026-09-28, sierpinski 2x;
# tests/test_pull_no_invalidate.py). A pull stores raw; it never marks dirty.
# Do not raise these without a new pull-consumer path — and never to absorb
# per-read walks.
DEEP_MARK_DIRTY_CEILING = 46
DEEP_CONE_VISIT_CEILING = 477

CHAIN_PROBES_T0 = [
    (0.0, 0.0, 0.0),
    (45.0, 0.0, 0.0),
    (90.0, 0.0, 0.0),
    (133.5, 0.0, 0.0),
    (175.545, 0.0, 0.0),
    (216.17864999999998, 0.0, 0.0),
    (255.4432905, 0.0, 0.0),
    (293.379991785, 0.0, 0.0),
    (330.02859203145, 0.0, 0.0),
    (365.42773427050645, 0.0, 0.0),
    (399.6149022423912, 0.0, 0.0),
    (432.6264551751195, 0.0, 0.0),
    (464.49766151986586, 0.0, 0.0),
    (495.26273167426984, 0.0, 0.0),
    (524.9548497240418, 0.0, 0.0),
    (553.6062042323205, 0.0, 0.0),
    (581.2480181053509, 0.0, 0.0),
    (607.9105775621903, 0.0, 0.0),
    (633.6232602353246, 0.0, 0.0),
    (658.4145624282648, 0.0, 0.0),
]

CHAIN_PROBES_T15 = [
    (0.0, 0.0, 30.0),
    (38.97114317029974, 22.499999999999996, 30.0),
    (77.94228634059948, 44.99999999999999, 30.0),
    (115.61439140522256, 66.74999999999999, 30.0),
    (152.0264295073393, 87.77249999999998, 30.0),
    (187.21620265582484, 108.08932499999997, 30.0),
    (221.22037879928817, 127.72164524999997, 30.0),
    (254.07452584787993, 146.68999589249995, 30.0),
    (285.8131446744463, 165.01429601572494, 30.0),
    (316.46970112564793, 182.71386713525317, 30.0),
    (346.0766570727459, 199.80745112119556, 30.0),
    (374.66550053086326, 216.31322758755968, 30.0),
    (402.2667748746694, 232.24883075993287, 30.0),
    (428.9101071775937, 247.63136583713487, 30.0),
    (454.62423570086264, 262.4774248620208, 30.0),
    (479.43703655786584, 276.8031021161602, 30.0),
    (503.37554957859123, 290.6240090526754, 30.0),
    (526.4660033981272, 303.9552887810951, 30.0),
    (548.7338397925095, 316.8116301176622, 30.0),
    (570.2037372844926, 329.20728121413237, 30.0),
]


class Tier1Case(unittest.TestCase):
    def tearDown(self):
        cleanup_global_event_system()


class TestDeepBinaryTree(Tier1Case):
    def test_geometry_matches_golden_sequence(self):
        st, bars = deep_binary_tree(4, 0.0)
        try:
            _assert_probes_exact(
                [_probe_bar(b) for b in bars], DEEP_PROBES_T0, "t=0"
            )
            st.t = 1.0
            _assert_probes_exact(
                [_probe_bar(b) for b in bars], DEEP_PROBES_T1, "t=1"
            )
            st.t = 2.5
            _assert_probes_exact(
                [_probe_bar(b) for b in bars], DEEP_PROBES_T25, "t=2.5"
            )
        finally:
            for b in bars:
                b.destroy()

    def test_engagement_within_pre_tier1_ceiling(self):
        st, bars = deep_binary_tree(4, 2.5)
        try:
            # settle
            for b in bars:
                _ = b.center.x, b.angle

            def frame():
                st.t = float(st.t) + 0.1
                for b in bars:
                    _ = b.center.x, b.center.y, b.angle

            calls, visits = _cone_stats(frame)
            self.assertLessEqual(calls, DEEP_MARK_DIRTY_CEILING)
            self.assertLessEqual(visits, DEEP_CONE_VISIT_CEILING)
            # Must still do real work (not silently skipping the graph).
            self.assertGreater(calls, 0)
            self.assertGreater(visits, 0)
        finally:
            for b in bars:
                b.destroy()


class TestLinearChain(Tier1Case):
    def test_geometry_matches_golden(self):
        st, chain = linear_chain(20)
        try:
            st.t = 0.0
            _assert_probes_exact(
                [_probe_bar(r) for r in chain], CHAIN_PROBES_T0, "t=0"
            )
            st.t = 1.5
            _assert_probes_exact(
                [_probe_bar(r) for r in chain], CHAIN_PROBES_T15, "t=1.5"
            )
        finally:
            for r in chain:
                r.destroy()

    def test_tip_moves_when_driver_changes(self):
        st, chain = linear_chain(12)
        try:
            tip = chain[-1]
            before = (float(tip.center.x), float(tip.center.y))
            st.t = 2.0
            after = (float(tip.center.x), float(tip.center.y))
            self.assertNotEqual(before, after)
        finally:
            for r in chain:
                r.destroy()


class TestDiamond(Tier1Case):
    def test_sink_sums_all_branches_once(self):
        st, branches, sink = diamond(8)
        self.assertEqual(float(sink.value), 16.0)  # 8 * (1+1)
        resolve_count = {"n": 0}
        orig = sink._resolve_link

        def wrapped():
            resolve_count["n"] += 1
            return orig()

        sink._resolve_link = wrapped  # type: ignore[method-assign]
        try:
            st.a = 10.0
            self.assertEqual(float(sink.value), 88.0)  # 8 * 11
            self.assertEqual(resolve_count["n"], 1)
        finally:
            sink._resolve_link = orig  # type: ignore[method-assign]


class TestColdDerivateUnlinked(Tier1Case):
    def test_unlinked_motion_zero_mark_dirty(self):
        rects = [
            Rect(center=(i * 10.0, 0.0), width=20.0, height=8.0)
            for i in range(20)
        ]
        try:
            for r in rects:
                self.assertFalse(r._needs_pull_invalidate)

            def motion():
                for i, r in enumerate(rects):
                    r.move_to(i + 1.0, 0.0)
                    r.move_by(0.1, 0.0)

            self.assertEqual(_mark_dirty_count(motion), 0)
        finally:
            for r in rects:
                r.destroy()


class TestBatchedPoseOutbound(Tier1Case):
    def test_batch_move_keeps_point_and_leaf_fresh(self):
        host = Rect(center=(0.0, 0.0), width=40.0, height=20.0)
        sink_pt = Point(0, 0)
        sink_pt @= host.center
        leaf = Attribute(0.0)
        leaf @= (lambda h=host: h.center.x)
        try:
            self.assertTrue(host._needs_pull_invalidate)
            with host._batch_update():
                host.move_to(50.0, 60.0)
            self.assertEqual((float(sink_pt.x), float(sink_pt.y)), (50.0, 60.0))
            self.assertEqual(float(leaf.value), 50.0)
            host.move_by(3.0, -2.0)
            self.assertEqual((float(sink_pt.x), float(sink_pt.y)), (53.0, 58.0))
            self.assertEqual(float(leaf.value), 53.0)
        finally:
            host.destroy()
            sink_pt.destroy()

    def test_leaf_sink_under_nested_batch(self):
        """Outbound leaf @= must stay fresh after Point._takein under outer batch."""
        host = Rect(center=(10.0, 20.0), width=30.0, height=10.0)
        leaf = Attribute(0.0)
        leaf @= (lambda h=host: h.center.x)
        try:
            with host._batch_update():
                host.center._takein((99.0, 20.0))
            self.assertEqual(float(leaf.value), 99.0)
        finally:
            host.destroy()


class TestScalarAnchorRotationScale(Tier1Case):
    def test_circle_rotation_property_anchor_tracks(self):
        c = Circle(center=(0, 0), radius=10)
        sink = Attribute(0.0)
        sink @= (lambda c=c: c.angle)
        try:
            self.assertEqual(float(sink.value), 0.0)
            c.rotate_to(30.0)
            self.assertEqual(float(sink.value), 30.0)
            # Same value again — dependent must still read correctly.
            c.rotate_to(30.0)
            self.assertEqual(float(sink.value), 30.0)
            c.rotate_to(90.0)
            self.assertEqual(float(sink.value), 90.0)
        finally:
            c.destroy()

    def test_rect_scalar_rotation_link_tracks(self):
        r = Rect(center=(0, 0), width=40, height=20, angle=0.0)
        sink = Attribute(0.0)
        sink @= (lambda r=r: r.angle)
        try:
            self.assertEqual(float(sink.value), 0.0)
            r.rotate_to(45.0)
            self.assertEqual(float(sink.value), 45.0)
            r.rotate_to(45.0)
            self.assertEqual(float(sink.value), 45.0)
            r.rotate_to(-10.0)
            self.assertEqual(float(sink.value), -10.0)
        finally:
            r.destroy()

    def test_spine_derivate_rotation_notifies(self):
        spine = Rect(p1=(0.0, 0.0), p2=(10.0, 0.0), height=4.0, anchor="cap")
        sink = Attribute(0.0)
        sink @= (lambda s=spine: s.angle)
        try:
            self.assertEqual(float(sink.value), 0.0)
            spine.p2 = (0.0, 10.0)
            self.assertEqual(float(sink.value), 90.0)
        finally:
            spine.destroy()

    def test_scale_property_anchor_tracks(self):
        c = Circle(center=(0, 0), radius=5)
        sink = Attribute(0.0)
        sink @= (lambda c=c: c.scale)
        try:
            self.assertEqual(float(sink.value), 1.0)
            c.scale_to(2.0)
            self.assertEqual(float(sink.value), 2.0)
            c.scale_to(2.0)
            self.assertEqual(float(sink.value), 2.0)
            c.scale_to(0.5)
            self.assertEqual(float(sink.value), 0.5)
        finally:
            c.destroy()


class TestMixedInkStateEffects(Tier1Case):
    def tearDown(self):
        ss = get_scena_system()
        if ss.update_manager.deferring:
            ss.end_frame_batch()
        cleanup_global_event_system()
        super().tearDown()

    def test_when_and_on_change_fire_once_on_flush(self):
        ship = Circle(center=(0, 0), radius=5)
        ship.hp = 10
        st = State(name="hud")
        st.score = 0
        fired: list = []

        @when(lambda: ship.hp <= 0)
        def death():
            fired.append("death")

        @on_change(lambda: st.score)
        def on_score(v=None):
            fired.append(("score", float(st.score)))

        ss = get_scena_system()
        try:
            ss.begin_frame_batch()
            ship.hp = 0
            st.score = 5
            self.assertEqual(fired, [])
            flush()
            self.assertEqual(fired, ["death", ("score", 5.0)])
            flush()  # idempotent — no double fire
            self.assertEqual(fired, ["death", ("score", 5.0)])
            ss.end_frame_batch()
        finally:
            ship.destroy()

    def test_geometry_link_coexists_with_ink(self):
        ship = Circle(center=(0, 0), radius=8)
        ship.hp = 3
        marker = Point(0, 0)
        marker @= ship.center
        try:
            ship.move_to(40.0, 50.0)
            self.assertEqual((float(marker.x), float(marker.y)), (40.0, 50.0))
            ship.hp = 1
            self.assertEqual(ship.hp, 1)
            # Ink write must not break geometry link.
            ship.move_by(1.0, 0.0)
            self.assertEqual((float(marker.x), float(marker.y)), (41.0, 50.0))
        finally:
            ship.destroy()
            marker.destroy()


class TestDestroyMidgraph(Tier1Case):
    def test_destroy_child_freezes_observer(self):
        src = Rect(center=(0.0, 0.0), width=100.0, height=20.0)
        child = Rect(
            center=(lambda s=src: s.left_square_center),
            width=50.0,
            height=10.0,
        )
        obs = Point(0, 0)
        obs @= child.center
        try:
            frozen = (float(obs.x), float(obs.y))
            self.assertEqual(frozen, (-40.0, 0.0))
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                child.destroy()
                self.assertTrue(
                    any(issubclass(x.category, RuntimeWarning) for x in w)
                )
            self.assertIsNone(obs._link)
            self.assertEqual((float(obs.x), float(obs.y)), frozen)
            # Source still movable; observer frozen.
            src.move_to(100.0, 0.0)
            self.assertEqual((float(obs.x), float(obs.y)), frozen)
        finally:
            if getattr(src, "_node_id", None) is not None:
                src.destroy()
            if getattr(obs, "_node_id", None) is not None:
                obs.destroy()

    def test_destroy_source_unlinks_chain(self):
        src = Rect(center=(0.0, 0.0), width=80.0, height=16.0)
        child = Rect(
            center=(lambda s=src: s.right_square_center),
            width=40.0,
            height=8.0,
        )
        try:
            before = (float(child.center.x), float(child.center.y))
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                src.destroy()
                self.assertTrue(
                    any(issubclass(x.category, RuntimeWarning) for x in w)
                )
            self.assertIsNone(child.center._link)
            self.assertEqual(
                (float(child.center.x), float(child.center.y)), before
            )
        finally:
            if getattr(child, "_node_id", None) is not None:
                child.destroy()


class TestResolveOnceMemoization(Tier1Case):
    def test_structural_resolve_once_per_dirty_read(self):
        rect = Rect(center=(50, 50), width=40, height=20, angle=0.0)
        _ = rect.top_left
        line = Line(p1=(lambda: rect.right_center), p2=(200, 50))
        calls: list = []
        orig = rect._update_impl

        def counting():
            calls.append(1)
            return orig()

        ss = get_scena_system()
        try:
            ss.begin_frame_batch()
            rect._update_impl = counting  # type: ignore[method-assign]
            rect.angle = 30
            self.assertEqual(len(calls), 0)
            _ = rect.top_left.x
            self.assertEqual(len(calls), 1)
            _ = rect.right_center.x
            self.assertEqual(len(calls), 1)
            self.assertEqual(float(line.p1.x), float(rect.right_center.x))
        finally:
            rect._update_impl = orig  # type: ignore[method-assign]
            ss.end_frame_batch()
            rect.destroy()
            line.destroy()


class TestSubtreeIterationContract(Tier1Case):
    """Pre-cache contract: _iter_subtree yields self then descendants."""

    def test_iter_subtree_includes_parts_and_self(self):
        r = Rect(center=(0, 0), width=10, height=8)
        try:
            nodes = list(r._iter_subtree())
            self.assertIs(nodes[0], r)
            self.assertIn(r.center, nodes)
            # After materializing a Derivate, it appears in the walk.
            _ = r.left_square_center
            nodes2 = list(r._iter_subtree())
            self.assertIn(r.left_square_center, nodes2)
            self.assertGreater(len(nodes2), len(nodes))
        finally:
            r.destroy()

    def test_destroy_removes_all_subtree_ids(self):
        r = Rect(center=(1, 1), width=5, height=5)
        _ = r.top_left
        ids = [
            n._node_id
            for n in r._iter_subtree()
            if getattr(n, "_node_id", None) is not None
        ]
        g = get_scena_system().dependency_graph
        r.destroy()
        for nid in ids:
            self.assertNotIn(nid, g.nodes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
