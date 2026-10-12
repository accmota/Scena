"""Reading an author field (ink) the fast way answers what the slow way does.

Rule under test (Actors Design.md, "Ink"; Scena Design "Values vs links"): an
author field (``self.hp = 3``) lives in the entity's ink and every read misses
normal lookup, so ``Entity.__getattr__`` runs. Its fast path returns the ink
value directly when, and only when, the slow path would: the name is in ink, the
entity is not destroyed, the name is not the refused ``x`` / ``y`` pose alias,
and the class's retired names do not list it (a linked ink field is pulled
first). Every other read takes the unchanged slow path.

The oracle is the slow path itself (``_INK_READ_FAST = False``): for many
names × states — ink present / absent, linked ink, ``x`` / ``y`` on a Graphic
and on a bare Entity, retired names, destroyed entities, subclasses — the value
or the exception (type and message) is the same.

Bug class guarded: a fast read that skips a refusal (a destroyed actor still
answering, ``ship.x`` returning a stored number) or a pull (a stale link).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena.entity import Entity
from scena.shapes import Circle, Rect
from scena import st

E = sys.modules["scena.entity"]

NAMES = ("hp", "vel_alvo", "rumo", "x", "y", "missing", "rotation", "hitbox_scale", "speed_old")


def outcome(obj, name):
    try:
        v = getattr(obj, name)
        return ("value", v if not hasattr(v, "__dict__") else id(v))
    except Exception as e:      # noqa: BLE001 - compared as data
        return ("raise", type(e).__name__, str(e))


class Hero(Rect):
    pass


class TestSameAnswers(unittest.TestCase):
    def setUp(self):
        self.owned = []

    def tearDown(self):
        for o in self.owned:
            try:
                o.destroy()
            except Exception:
                pass

    def make(self):
        objs = []
        for cls in (Rect, Circle, Hero):
            if cls is Circle:
                o = cls(center=(0, 0), radius=5)
            else:
                o = cls(center=(0, 0), width=5, height=5)
            o.hp = 3
            o.rumo = 45.0
            objs.append(o)
        e = Entity()
        e.hp = 7
        e.x = 1.5            # a bare Entity keeps x as ink
        objs.append(e)
        linked = Rect(center=(0, 0), width=5, height=5)
        st.alvo = 2.0
        linked.vel_alvo = 0.0
        linked["vel_alvo"] @= lambda: st.alvo * 10
        objs.append(linked)
        self.owned += objs
        return objs

    def compare_all(self, objs, ctx):
        for o in objs:
            for name in NAMES:
                with mock.patch.object(E, "_INK_READ_FAST", False, create=True):
                    slow = outcome(o, name)
                fast = outcome(o, name)
                self.assertEqual(fast, slow, f"{ctx}: {type(o).__name__}.{name}")

    def test_live_linked_and_destroyed(self):
        objs = self.make()
        self.compare_all(objs, "live")
        st.alvo = 5.0                          # the link must be pulled
        self.compare_all(objs, "after a source write")
        self.assertEqual(objs[-1].vel_alvo, 50.0)
        for o in objs:
            o.destroy()
        self.compare_all(objs, "destroyed")

    def test_linked_ink_is_pulled_inside_a_frame(self):
        """In a running frame writes only mark dirty; the read must pull."""
        from scena.state import get_scena_system
        linked = Rect(center=(0, 0), width=5, height=5)
        self.owned.append(linked)
        st.fonte = 1.0
        linked.alvo2 = 0.0
        linked["alvo2"] @= lambda: st.fonte * 10
        ss = get_scena_system()
        for fast in (False, True):
            ss.begin_frame_batch()
            try:
                st.fonte = 7.0 if fast else 3.0
                with mock.patch.object(E, "_INK_READ_FAST", fast, create=True):
                    self.assertEqual(linked.alvo2, 70.0 if fast else 30.0, f"fast={fast}")
            finally:
                ss.end_frame_batch()

    def test_fast_path_is_taken(self):
        objs = self.make()
        with mock.patch.object(Entity, "_ink_read_slow", side_effect=AssertionError("slow"),
                               create=True):
            self.assertEqual(objs[0].hp, 3)
            self.assertEqual(objs[0].rumo, 45.0)


if __name__ == "__main__":
    unittest.main()
