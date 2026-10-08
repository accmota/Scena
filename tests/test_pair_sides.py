"""Collision pair sides: ``@collide`` / ``@collide_stay`` / ``@collide_exit`` /
``resolve`` / ``unresolve`` accept the same atoms and refuse the same junk.

Bug class: **a pair nothing can match.** A side atom that names no body
(``5``, ``None``, a dict, a post effect, a function) used to be registered by
``resolve`` / ``unresolve`` without complaint: a silent no-op. One shared
check (``collision._check_pair_sides``) now runs for every pair call, before
anything is registered.

Rule (Collision Design.md, "Pair sides"): an atom is an actor (Entity), a
group tag string, ``group['tag']``, ``ANYTHING``, a Collider or a Hitbox part;
a side is one atom or a list / tuple of atoms.

    python tests/run_tiers.py focused test_pair_sides
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import ANYTHING, group  # noqa: E402
from scena.collision import (  # noqa: E402
    collide,
    collide_exit,
    collide_stay,
    get_collision_system,
    reset_collision_system,
    resolve,
    unresolve,
)
from scena.shapes import Circle, Rect  # noqa: E402
from scena.sprite import Sprite  # noqa: E402


class _Opaque:
    """Stands in for any non-body object (a post effect, a widget model)."""


def _fn():
    return None


# (value, type name the message must show, value text or None if hidden)
JUNK = (
    (5, "int", "5"),
    (2.5, "float", "2.5"),
    (None, "NoneType", "None"),
    (True, "bool", "True"),
    ({"heroi": 1}, "dict", None),
    ({"heroi"}, "set", None),
    (frozenset({"heroi"}), "frozenset", None),
    (_Opaque(), "_Opaque", None),
    (_fn, "function", None),
)


def _collide(left, right):
    @collide(left, right)
    def _h(a, b):
        pass


def _collide_stay(left, right):
    @collide_stay(left, right)
    def _h(a, b):
        pass


def _collide_exit(left, right):
    @collide_exit(left, right)
    def _h(a, b):
        pass


CALLS = (
    ("@collide", _collide, '@collide(player, "enemies")'),
    ("@collide_stay", _collide_stay, '@collide_stay(player, "enemies")'),
    ("@collide_exit", _collide_exit, '@collide_exit(player, "enemies")'),
    ("resolve()", resolve, 'resolve(player, "walls")'),
    ("unresolve()", unresolve, 'unresolve(player, "walls")'),
)


class PairSideTestCase(unittest.TestCase):
    def setUp(self):
        reset_collision_system()
        self._owned = []

    def tearDown(self):
        for s in self._owned:
            try:
                s.destroy()
            except Exception:
                pass
        reset_collision_system()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestJunkSidesRefused(PairSideTestCase):
    def test_every_call_refuses_every_junk_atom_on_either_side(self):
        for call, fn, example in CALLS:
            for value, type_name, shown in JUNK:
                for args in ((value, "walls"), ("heroi", value),
                             (["heroi", value], "walls"), ("heroi", ("walls", value))):
                    with self.subTest(call=call, value=type_name, args=len(args)):
                        with self.assertRaises(TypeError) as cm:
                            fn(*args)
                        msg = str(cm.exception)
                        self.assertIn(call, msg)
                        self.assertIn(type_name, msg)
                        self.assertIn(f"Write {example}.", msg)
                        self.assertIn("ANYTHING", msg)
                        if shown is not None:
                            self.assertIn(shown, msg)
                        else:
                            # No repr of an arbitrary object (addresses, huge dicts).
                            self.assertNotIn(" at 0x", msg)
                            self.assertNotIn("{", msg)

    def test_refused_resolve_registers_nothing(self):
        # All-or-nothing: a valid left side and a list with one junk atom.
        with self.assertRaises(TypeError):
            resolve("heroi", ["paredes", 5, "chao"])
        with self.assertRaises(TypeError):
            resolve(["heroi", None], "chao")
        self.assertEqual(get_collision_system()._resolve_pairs, [])

    def test_refused_unresolve_removes_nothing(self):
        resolve("heroi", "chao")
        with self.assertRaises(TypeError):
            unresolve("heroi", ["chao", 5])
        self.assertEqual(len(get_collision_system()._resolve_pairs), 1)

    def test_side_check_runs_before_only(self):
        # The side is the first mistake reported, not only=.
        with self.assertRaisesRegex(TypeError, "side must be"):
            resolve("heroi", 5, only="floor")

    def test_empty_sides_keep_their_own_message(self):
        for call, fn, _example in CALLS:
            with self.subTest(call=call):
                with self.assertRaisesRegex(TypeError, "must not be empty"):
                    fn([], "walls")


class TestValidAtomsAccepted(PairSideTestCase):
    def test_tags_anything_group_operator_and_lists(self):
        for call, fn, _example in CALLS:
            with self.subTest(call=call):
                fn("heroi", "chao")
                fn("heroi", ANYTHING)
                fn(group["heroi"], ["chao", group["paredes"]])
                fn(("heroi", "inimigos"), "chao")

    def test_actor_and_hitbox_part(self):
        hero = self.track(Rect(center=(0, 0), width=20, height=40, group="heroi"))
        ship = self.track(Sprite(center=(100, 0), size=64, hitbox_shape="rect", group="nave"))
        part = ship.add_hitbox(group="casco", shape="rect", scale=(0.5, 0.5))
        ball = self.track(Circle(center=(200, 0), radius=5))
        for call, fn, _example in CALLS:
            with self.subTest(call=call):
                fn(hero, "chao")
                fn(ball, ship)
                if call.startswith("@"):
                    fn(ball, [ship, part])

    def test_resolve_part_keeps_its_specific_refusal(self):
        # A hitbox part is a valid pair atom (it detects), so the generic side
        # check lets it through; resolve() then refuses it with its own reason.
        ship = self.track(Sprite(center=(100, 0), size=64, hitbox_shape="rect", group="nave"))
        part = ship.add_hitbox(group="casco", shape="rect", scale=(0.5, 0.5))
        with self.assertRaisesRegex(TypeError, "parts only detect"):
            resolve(part, "chao")


if __name__ == "__main__":
    unittest.main()
