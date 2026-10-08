"""Per-frame paths stay on their fast path, and the fast path equals the slow one.

Graphics review batch 10 (2026-10-08), the performance table:

* E15: ``_main_hitbox_off`` / ``_touching_sides`` / ``_blit_plain`` had no
  class default, so each probe of a moving actor raised inside
  ``Entity.__getattr__`` (about 0.5 µs each, twice per actor per frame).
* E16: ``destroy()`` spent a third of its time in ``traceback.extract_stack``.
* SA14: an instant ``move_to`` computed a pivot it never used.
* SC10: a free Polygon ``move_by`` went through the batch (14 µs, Rect 2 µs).
* SB11: a Line turned about its center went through the batch (8 µs).
* HP14: ``Hitbox.__setattr__`` checked retired names on every private write.
* PA-note: a second Sheet over the same files re-packed and re-fitted its
  auto hitboxes (about 10 ms).

Each fast path is pinned two ways: it is taken on a free shape (a spy on the
slow path), and it lands where the slow path lands (the same shape driven
through the slow path by a Derivate read, which sets the sticky pull flag).

    python tests/run_tiers.py focused test_hot_paths
"""
from __future__ import annotations

import collections
import os
import sys
import unittest
import warnings
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world, quiet  # noqa: E402

import scena  # noqa: E402
import scena.entity as E  # noqa: E402
import scena.shapes as SH  # noqa: E402


def _xy(p):
    return (round(float(p.x), 9), round(float(p.y), 9))


class TestHotProbesHaveClassDefaults(unittest.TestCase):
    def test_a_frame_of_moving_actors_never_falls_into_getattr(self):
        """E15: every attribute the frame probes exists on the class."""
        from system_support import SystemWorld
        from tests.media_support import media
        w = SystemWorld(draw=True)
        try:
            with quiet():
                sprites = [scena.Sprite(media("space", "enemyGreen1.png"), center=(20 + i * 5, 50),
                                        height=20, group="hp_e") for i in range(6)]
                circles = [scena.Circle(center=(20 + i * 5, 52), radius=4, group="hp_b") for i in range(6)]
                texts = [scena.Text("hi", center=(10, 10 + i)) for i in range(3)]
            for c in circles:
                c.collidable = True

            @scena.collide("hp_e", "hp_b")
            def _hit(a, b, info=None):
                pass

            def mover():
                for c in circles:
                    c.move_by(0.1, 0)
                for s in sprites:
                    s.rotate_by(1)
            scena.every(0.001, mover)
            w.step(2)
            misses = collections.Counter()
            real = E.Entity.__getattr__

            def spy(self, name):
                misses[name] += 1
                return real(self, name)
            with mock.patch.object(E.Entity, "__getattr__", spy):
                w.step(5)
            self.assertEqual(dict(misses), {})
            del texts
        finally:
            w.teardown()


class TestFastPathsAreTaken(unittest.TestCase):
    def test_free_polygon_move_by(self):
        with fresh_world():
            p = scena.Polygon(points=[(0, 0), (10, 0), (5, 8)])
            with mock.patch.object(SH.Polygon, "_move_by_batched", side_effect=AssertionError("slow")):
                p.move_by(1, 2)
            p.destroy()

    def test_free_line_turn_about_center(self):
        with fresh_world():
            for line in (scena.Line(p1=(0, 0), p2=(10, 4)),
                         scena.Line(center=(5, 5), length=10, angle=20),
                         scena.Line(p1=(0, 0), angle=30, length=12)):
                with mock.patch.object(SH.Line, "_rotate_by_batched", side_effect=AssertionError("slow")):
                    line.rotate_by(15)
                line.destroy()

    def test_instant_move_to_reads_no_pivot(self):
        with fresh_world():
            r = scena.Rect(center=(0, 0), width=4, height=3)
            with mock.patch.object(SH.Rect, "_pivot_xy", side_effect=AssertionError("pivot read")):
                r.move_to((5, 6))
            self.assertEqual(_xy(r.center), (5.0, 6.0))
            r.destroy()


class TestFastPathEqualsSlowPath(unittest.TestCase):
    """The same verb on a free shape (fast) and on a twin whose Derivate was
    read (sticky pull flag: the batch) lands on the same geometry."""

    def test_polygon_move_by(self):
        with fresh_world():
            pts = [(0, 0), (10, 0), (6, 9), (1, 5)]
            fast, slow = scena.Polygon(points=pts), scena.Polygon(points=pts)
            slow.centroid                                  # pull flag: the batch
            for p in (fast, slow):
                p.move_by(3.5, -1.25)
                p.move_by(None, 2.0)
            self.assertEqual([_xy(v) for v in fast.points], [_xy(v) for v in slow.points])
            self.assertEqual(_xy(fast.centroid), _xy(slow.centroid))
            self.assertAlmostEqual(fast.signed_area, slow.signed_area)

    def test_line_turn_about_center(self):
        with fresh_world():
            for build in (lambda: scena.Line(p1=(0, 0), p2=(10, 4)),
                          lambda: scena.Line(center=(5, 5), length=10, angle=20),
                          lambda: scena.Line(p1=(1, 2), angle=30, length=12)):
                fast, slow = build(), build()
                slow.p2                                    # pull flag: the batch
                for line in (fast, slow):
                    line.rotate_by(37)
                    line.rotate_by(-12, about=line._center_xy())
                for name in ("p1", "p2", "center"):
                    self.assertEqual(_xy(getattr(fast, name)), _xy(getattr(slow, name)), name)
                self.assertAlmostEqual(fast.angle, slow.angle)


class TestDestroySiteAndHitboxWrites(unittest.TestCase):
    def test_destroy_names_the_author_line(self):
        """E16: the site comes from a ``sys._getframe`` walk."""
        with fresh_world():
            c = scena.Circle(center=(0, 0), radius=2)
            c.destroy()
            self.assertIn("test_hot_paths.py:", c._destroyed_by)
            self.assertIn("test_destroy_names_the_author_line", c._destroyed_by)

    def test_hitbox_has_no_setattr_and_still_refuses_retired_names(self):
        """HP14: the retired names are class descriptors, not a per-write check."""
        from scena.hitbox import Hitbox, _RETIRED_KNOBS
        self.assertNotIn("__setattr__", Hitbox.__dict__)
        from test_value_validation import _grid_sprite
        with fresh_world():
            s = _grid_sprite()
            hb = s.add_hitbox(group="hp14")
            for name in _RETIRED_KNOBS:
                with self.assertRaisesRegex(AttributeError, r"hb\."):
                    getattr(hb, name)
                with self.assertRaisesRegex(AttributeError, r"hb\."):
                    setattr(hb, name, 1)
            s.destroy()


class TestFileListSheetsShareTheirBakes(unittest.TestCase):
    def test_a_second_sheet_over_the_same_files_fits_nothing(self):
        """PA-note: the packed strip is shared, so the auto-hitbox fits are."""
        import scena.atlas as A
        from tests.media_support import MEDIA
        pattern = os.path.join(MEDIA, "ninja", "Run__*.png")
        with fresh_world(), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            first = scena.Sheet(pattern, fps=12)
            a = scena.Sprite(first, center=(0, 0), height=60)
            a.hitbox.box
            fits = []
            real = A._choose_auto_collider
            with mock.patch.object(A, "_choose_auto_collider",
                                   lambda *x, **k: fits.append(1) or real(*x, **k)):
                second = scena.Sheet(pattern, fps=12)
                b = scena.Sprite(second, center=(0, 0), height=60)
                b.hitbox.box
            self.assertIs(second.image, first.image)
            self.assertEqual(fits, [])
            second.clip("mine", [0, 1], fps=4)               # still the author's own
            self.assertNotIn("mine", first._cycles)
            a.destroy()
            b.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
