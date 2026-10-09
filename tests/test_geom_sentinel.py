"""The sentinel checks itself (geometry campaign, H2).

* ``TestSentinelCanaries`` — each invariant fires on a planted bug of its class
  and stays quiet on the same scenario without it:
  D13 (a dirty bit cleared without recomputing: I-clean), R7 (a stale hull
  under an unchanged cache key: I-epoch), a fast-path leak (a link that does
  not flag its tree: I-fast), and GX7 (a bare-read flag on a pull-owned
  point: I-bare).
* ``TestSentinelOverTheShadowArray`` — the H1 quick array runs under the
  sentinel; every violation it logs must be known
  (``geom_campaign_known.SENTINEL``).
* ``TestSentinelIsInvisible`` — wrapping keeps names, docstrings and
  results; uninstall restores every entry point.

The whole suite runs under it with ``python tests/run_tiers.py gate --sentinel``
(Testing Design — Geometry campaign).

    python tests/run_tiers.py focused test_geom_sentinel
"""
from __future__ import annotations

import fnmatch
import os
import sys
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world  # noqa: E402

import geom_campaign_known as KNOWN  # noqa: E402
import geom_sentinel as GS  # noqa: E402
from scena import Circle, Line, Point, Rect, State  # noqa: E402


def _keys(violations, inv):
    return [v["key"] for v in violations if v["key"].startswith(inv)]


class TestSentinelCanaries(unittest.TestCase):
    def _run(self, scenario, patches=()):
        # The world's teardown runs inside ``active`` too: a planted bug left
        # in the scenario's objects must not reach the tier's shared log.
        with GS.active(raise_=False) as found, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fresh_world() as w:
                stack = [mock.patch.object(*p) for p in patches]
                for p in stack:
                    p.start()
                try:
                    scenario(w)
                finally:
                    for p in reversed(stack):
                        p.stop()
                return list(found)

    def test_i_clean_catches_a_dirty_bit_cleared_without_recompute(self):
        def scenario(w, plant=False):
            r = w.track(Rect(center=(0, 0), width=20, height=10))
            pin = w.track(Point(0, 0))
            pin @= lambda: r.top_left        # top_left becomes a live Derivate
            pin.x
            if plant:
                # D13: the read resolves the tree (clean) but never recomputes.
                with mock.patch.object(Rect, "_update_impl", lambda self: None):
                    r.width = 50
                    pin.x                       # the link's pull resolves the tree
            else:
                r.width = 50
                pin.x
            r.unlink_all()                      # any entry point: the sentinel checks after it
        planted = self._run(lambda w: scenario(w, True))
        self.assertTrue(_keys(planted, "I-clean"), planted)
        self.assertFalse(_keys(self._run(scenario), "I-clean"))

    def test_i_epoch_catches_a_stale_hull(self):
        def scenario(w):
            from scena.collision import snapshot_shape
            import importlib
            C = sys.modules[importlib.import_module("scena.collision").__name__]
            c = w.track(Circle(center=(0, 0), radius=5))
            c.collidable = True
            C.snapshot_shape(c, cache_owner=c._collider)
            c.move_by(30, 0)
            C.snapshot_shape(c, cache_owner=c._collider)
            del snapshot_shape
        C = sys.modules["scena.collision"]
        planted = self._run(scenario, [(C, "_collision_pose_key", lambda shape: (0,))])
        self.assertTrue(_keys(planted, "I-epoch"), planted)
        self.assertFalse(_keys(self._run(scenario), "I-epoch"))

    def test_i_fast_catches_a_link_that_does_not_flag_its_tree(self):
        def scenario(w):
            st = State(name="sentfast")
            st.x = 0.0
            c = w.track(Circle(center=(0, 0), radius=5))
            c["center"] @= lambda: (st.x, 0)
            c.radius = 6
        from scena.state import Container
        planted = self._run(scenario, [(Container, "_flag_pull_consumers", lambda self: None)])
        self.assertTrue(_keys(planted, "I-fast"), planted)
        self.assertFalse(_keys(self._run(scenario), "I-fast"))

    def test_i_bare_catches_gx7(self):
        def scenario(w):
            st = State(name="sentbare")
            st.a = 0.0
            ln = w.track(Line(p1=(0, 0), p2=(10, 0)))
            ln["angle"] @= lambda: st.a
            ln.p1.x = 1.0
        found = self._run(scenario)
        self.assertTrue(_keys(found, "I-bare | Line"), found)


class TestSentinelOverTheShadowArray(unittest.TestCase):
    def test_quick_array_is_clean_or_known(self):
        import covering
        import geom_shadow as S
        import test_geom_sequences as T
        rows = covering.covering_array(T._axes(T.FAMILIES), 2)
        with GS.active(raise_=False) as found:
            T._run(rows, True, S.A.Reach())
            found = list(found)
        self.assertGreater(len(rows), 100)
        new = sorted({v["key"] for v in found
                      if not any(fnmatch.fnmatch(v["key"], p) for p in KNOWN.SENTINEL)})
        self.assertEqual(new, [], "sentinel violations under the shadow array")


class TestSentinelIsInvisible(unittest.TestCase):
    """The sentinel adds no frame and replaces no function (sys.monitoring)."""

    def test_entry_points_are_untouched(self):
        from scena.shapes import Shape
        raw = Shape.__dict__["move_by"]
        with GS.active(raise_=False):
            self.assertIs(Shape.__dict__["move_by"], raw)
            self.assertTrue(sys.monitoring.get_local_events(GS.TOOL, raw.__code__))
            with fresh_world() as w:
                c = w.track(Circle(center=(0, 0), radius=5))
                self.assertIs(c.move_by(1, 2), c)

    def test_author_sites_name_the_author(self):
        with GS.active(raise_=False):
            with fresh_world() as w:
                c = w.track(Circle(center=(0, 0), radius=5))
                c.move_by(1, 1)
                c.destroy()
                self.assertIn("test_geom_sentinel.py:", c._destroyed_by)

    def test_uninstall_clears_the_hooks(self):
        from scena.shapes import Shape
        if os.environ.get("SCENA_SENTINEL"):
            self.skipTest("installed for the whole process")
        with GS.active(raise_=False):
            pass
        self.assertFalse(sys.monitoring.get_local_events(GS.TOOL, Shape.__dict__["move_by"].__code__))


if __name__ == "__main__":
    unittest.main()
