"""Collision state survives every lifecycle transition (graphics review R3).

The 2026-10-08 review found collision state stored on a throwaway object, or
checked on one path only:

* E1: ``on_collide`` / ``_stay`` / ``_exit`` lived on the Collider, which
  ``collidable = False`` and park drop. After ``active = False -> True`` the
  callbacks were gone, so pool / respawn games silently stopped reporting
  hits. A method callback still read as bound but never fired.
* E2: ``on_collide =`` / ``resolve_now`` on a parked actor built a Collider;
  resume then recorded a sticky opt-out, and the actor never collided with
  groups again.
* E3: ``collidable = False`` before any ``@collide`` returned early without
  recording the opt-out, so the actor collided anyway. The result depended
  on statement order.
* E11: a stash accepted while parked (``layer = "ui"`` + ``collidable =
  True``) raised on resume and left the actor half resumed.

The guard runs every sequence of up to three lifecycle statements on a
subject, then builds a twin directly in the sequence's final state (callback,
``collidable``, ``active``, in one canonical order) and checks that both
report the same hits over the next frames. The contract is the one the docs
write (Actors Design, "active (park)"; Collision Design, enrollment table):

* ``on_collide = f`` sets the callback and opts in;
* ``on_collide = None`` clears it;
* ``collidable = v`` is the author's switch (False is sticky);
* ``active = v`` parks and resumes without forgetting.

Known violations are shrink-only (``graphics_known.LIFECYCLE``).

    python tests/run_tiers.py focused test_collision_lifecycle
"""
from __future__ import annotations

import itertools
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase  # noqa: E402

import scena  # noqa: E402

OPS = ("park", "unpark", "col_off", "col_on", "cb_set", "cb_clear", "decl")
FRAMES = 3


class _Hits:
    def __init__(self):
        self.cb = set()       # ids that the object callback fired for
        self.pair = set()     # ids the @collide("lc_a", "lc_b") handler saw


def _model(ops):
    """The final state the docs promise for a statement sequence."""
    s = {"active": True, "col": None, "cb": False, "decl": False}
    for op in ops:
        if op == "park":
            s["active"] = False
        elif op == "unpark":
            s["active"] = True
        elif op == "col_off":
            s["col"] = False
        elif op == "col_on":
            s["col"] = True
        elif op == "cb_set":
            s["cb"] = True
            s["col"] = True          # on_collide opts the body in
        elif op == "cb_clear":
            s["cb"] = False
        elif op == "decl":
            s["decl"] = True
    return s


class TestCollisionLifecycle(SystemTestCase, unittest.TestCase):
    world_draw = False

    def _pair(self, x, hits):
        a = self.track(scena.Circle(center=(x, 0), radius=10, group="lc_a"))
        b = self.track(scena.Circle(center=(x + 5, 0), radius=10, group="lc_b"))
        b.collidable = True
        return a, b

    def _callback(self, hits):
        def on_hit(me, other, info=None):
            hits.cb.add(id(me))
        return on_hit

    def _declare(self, hits):
        @scena.collide("lc_a", "lc_b")
        def lc_pair(a, b, info=None):
            hits.pair.add(id(a))
        return lc_pair

    def _run(self, a, ops, hits, declared):
        for op in ops:
            try:
                if op == "park":
                    a.active = False
                elif op == "unpark":
                    a.active = True
                elif op == "col_off":
                    a.collidable = False
                elif op == "col_on":
                    a.collidable = True
                elif op == "cb_set":
                    a.on_collide = self._callback(hits)
                elif op == "cb_clear":
                    a.on_collide = None
                elif op == "decl" and not declared[0]:
                    self._declare(hits)
                    declared[0] = True
            except Exception as e:  # noqa: BLE001
                return f"{op} raised {type(e).__name__}"
        return None

    def _twin(self, x, state, hits):
        a, _b = self._pair(x, hits)
        if state["cb"]:
            a.on_collide = self._callback(hits)
        if state["col"] is not None:
            a.collidable = state["col"]
        if not state["active"]:
            a.active = False
        return a

    def violations(self) -> dict:
        out = {}
        seqs = [s for n in (1, 2, 3) for s in itertools.product(OPS, repeat=n)]
        for i, ops in enumerate(seqs):
            self.w.teardown()
            self.setUp()
            hits = _Hits()
            declared = [False]
            a, _b = self._pair(0.0, hits)
            err = self._run(a, ops, hits, declared)
            state = _model(ops)
            if state["decl"] and not declared[0]:
                self._declare(hits)
            twin = self._twin(500.0, state, hits)
            self.w.step(FRAMES)
            key = " > ".join(ops)
            if err:
                out[key] = err
                continue
            got = (id(a) in hits.cb, id(a) in hits.pair)
            want = (id(twin) in hits.cb, id(twin) in hits.pair)
            if got != want:
                out[key] = f"callback / pair fired {got}, twin {want}"
        return out

    def test_every_sequence_matches_its_final_state(self):
        from graphics_known import shrink_only
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            shrink_only(self, self.violations(), "LIFECYCLE")

    def test_a_method_callback_survives_park(self):
        """E1: a class-body ``on_collide`` method keeps firing after resume."""
        hits = []

        class Probe(scena.Circle):
            def on_collide(self, other, info=None):
                hits.append(1)

        a = self.track(Probe(center=(0, 0), radius=10))
        b = self.track(scena.Circle(center=(5, 0), radius=10))
        b.collidable = True
        a.active = False
        a.active = True
        self.w.step(FRAMES)
        self.assertTrue(hits, "the method on_collide stopped firing after park / resume")

    def test_ui_layer_is_refused_while_collision_is_stashed(self):
        """E11: validated where the stash is written, not on resume."""
        a = self.track(scena.Circle(center=(0, 0), radius=10))
        a.active = False
        a.collidable = True
        with self.assertRaises(scena.UiLayerError if hasattr(scena, "UiLayerError") else Exception):
            a.layer = "ui"
        a.active = True                     # resumes cleanly
        self.assertTrue(a.active and a.collidable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
