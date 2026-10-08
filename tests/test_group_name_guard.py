"""``group["name"]`` warns on a near-miss typo, never on a real empty group.

Bug class: **the typo guard fired on correct names.** The guard warned when a
name was not in ``group_map`` and resembled one that was. ``group_map`` holds
only live members, so two correct reads warned:

* not filled yet: ``group["tiros_inimigos"]`` before the first enemy shot
  ("Did you mean 'inimigos'?"), although ``@collide`` / ``@leave_playfield``
  name the group (``examples/naves.py``);
* emptied: the registry drops a bucket with its last member, so clearing the
  fleet made ``group["inimigos"]`` warn "Did you mean 'tiros_inimigos'?" (the
  ``until_empty`` member of the class: ``test_process``).

Rule (Actors Design, Group names): a name is known when it is live, ever had a
member, is a formula group, or a rule declared it (``@collide`` family,
``collide_with``, ``resolve``, ``@leave_playfield``). Only an unknown near-miss
warns, at the call that typed it.

    python tests/run_tiers.py focused test_group_name_guard
"""
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Circle, group, init  # noqa: E402
from scena.bounds import leave_playfield, reset_bounds_system  # noqa: E402
from scena.collision import (  # noqa: E402
    collide,
    collide_exit,
    collide_stay,
    collide_with,
    reset_collision_system,
    resolve,
)


def _near_miss_warnings(read):
    """Run ``read()``; return the "No group" warnings it raised."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        read()
    return [str(w.message) for w in caught if "No group" in str(w.message)]


class _Case(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        reset_collision_system()
        reset_bounds_system()
        self._owned = []

    def tearDown(self):
        for s in self._owned:
            if not getattr(s, "_destroyed", False):
                s.destroy()
        reset_collision_system()
        reset_bounds_system()

    def own(self, s):
        self._owned.append(s)
        return s


class TestTypoStillWarns(_Case):
    def test_unknown_near_miss_warns_at_the_call(self):
        self.own(Circle(center=(0, 0), radius=5, group="gng_wasps"))
        got = _near_miss_warnings(lambda: group["gng_wsps"])
        self.assertEqual(len(got), 1)
        self.assertIn("Did you mean 'gng_wasps'", got[0])

    def test_a_rule_declared_name_is_suggested(self):
        @collide("gng_bolts", "gng_rocks")
        def _hit(a, b):
            pass

        got = _near_miss_warnings(lambda: group["gng_bolt"])
        self.assertEqual(len(got), 1)
        self.assertIn("gng_bolts", got[0])


class TestNotFilledYet(_Case):
    """The naves case: the group is named by a rule before its first member."""

    def setUp(self):
        super().setUp()
        self.own(Circle(center=(0, 0), radius=5, group="gnf_inimigos"))

    def test_collide_family_declares(self):
        for i, deco in enumerate((collide, collide_stay, collide_exit)):
            name = f"gnf_tiros{i}_inimigos"

            @deco(name, "gnf_inimigos")
            def _hit(a, b):
                pass

            self.assertEqual(_near_miss_warnings(lambda: group[name]), [], deco.__name__)

    def test_collide_list_side_declares(self):
        @collide(["gnf_a_inimigos", "gnf_b_inimigos"], "gnf_inimigos")
        def _hit(a, b):
            pass

        self.assertEqual(_near_miss_warnings(lambda: group["gnf_a_inimigos"]), [])
        self.assertEqual(_near_miss_warnings(lambda: group["gnf_b_inimigos"]), [])

    def test_resolve_declares(self):
        resolve("gnf_r_inimigos", "gnf_inimigos")
        self.assertEqual(_near_miss_warnings(lambda: group["gnf_r_inimigos"]), [])

    def test_leave_playfield_declares(self):
        @leave_playfield("gnf_l_inimigos")
        def _gone(s):
            pass

        self.assertEqual(_near_miss_warnings(lambda: group["gnf_l_inimigos"]), [])

    def test_collide_with_declares(self):
        class Nave(Circle):
            @collide_with("gnf_w_inimigos")
            def bateu(self, other):
                pass

        self.assertEqual(_near_miss_warnings(lambda: group["gnf_w_inimigos"]), [])


class TestEmptied(_Case):
    def test_a_group_that_emptied_reads_quietly(self):
        enemy = self.own(Circle(center=(0, 0), radius=5, group="gne_inimigos"))
        self.own(Circle(center=(0, 0), radius=5, group="gne_tiros_inimigos"))
        enemy.destroy()
        got = _near_miss_warnings(lambda: group["gne_inimigos"])
        self.assertEqual(got, [])
        self.assertEqual(group["gne_inimigos"].count, 0)

    def test_untagged_last_member_reads_quietly(self):
        enemy = self.own(Circle(center=(0, 0), radius=5, group="gnu_inimigos"))
        self.own(Circle(center=(0, 0), radius=5, group="gnu_tiros_inimigos"))
        enemy.untag("gnu_inimigos")
        self.assertEqual(_near_miss_warnings(lambda: group["gnu_inimigos"]), [])


if __name__ == "__main__":
    unittest.main()
