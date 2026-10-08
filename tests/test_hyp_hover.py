"""Hover resolver state machine (tiered ``step_hover``).

Random author sessions (create targets, hide / show, flag flips, hover-only
handlers, z-order, destroy, pointer moves, moving the hovered shape) against
three invariants, checked after every step and one frame:

(a) exit guarantee — the hover target, if any, is alive, drawn, a target and
    contains the pointer;
(b) tiered == brute force — with no *other* shape moved under a still pointer
    (the one documented trade-off, not generated here), the tiered result is
    the topmost eligible target;
(c) edges alternate — per shape, enter / exit alternate starting with enter,
    and teardown balances them.

Guards the bug class "event-driven level state goes stale" (Testing Design).

    python -m unittest tests.test_hyp_hover -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402
from hypothesis import strategies as hst  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine, invariant, precondition, rule,
)

from scena import Circle  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.entity import _drawn  # noqa: E402
from scena.orchestration import ShapeInteractionManager  # noqa: E402

boot()

ORIGIN = 90_000.0
SPOTS = [(0.0, 0.0), (20.0, 0.0), (0.0, 20.0), (400.0, 400.0)]


def _eligible(shape) -> bool:
    return ShapeInteractionManager._hover_eligible(shape)


class HoverMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.registry = ScenaCanvas.get_current().registry
        self.sim = ShapeInteractionManager(self.registry)
        self.shapes = []
        self.log = []
        self.sim.note_pointer(world_xy=(ORIGIN, ORIGIN))

    # --- helpers ------------------------------------------------------------

    def _live(self):
        return [s for s in self.shapes if s.is_alive]

    def _record(self, kind):
        return lambda shape: self.log.append((kind, shape))

    def _brute(self):
        x, y = self.sim._ptr_world
        for shape in self.registry.iter_interactive_hit_order():
            if _drawn(shape) and _eligible(shape) and shape.contains_point(x, y):
                return shape
        return None

    # --- rules ----------------------------------------------------------------

    @rule(spot=hst.sampled_from(SPOTS), clickable=hst.booleans(),
          hover_handlers=hst.booleans())
    def create(self, spot, clickable, hover_handlers):
        if len(self._live()) >= 6:
            return
        c = Circle(center=(ORIGIN + spot[0], ORIGIN + spot[1]), radius=25)
        c.clickable = clickable
        if hover_handlers or not clickable:
            c.on_hover = self._record("enter")
            c.on_hover_exit = self._record("exit")
        self.shapes.append(c)

    @precondition(lambda self: self._live())
    @rule(i=hst.integers(0, 5))
    def toggle_visible(self, i):
        live = self._live()
        s = live[i % len(live)]
        s.visible = not s.visible

    @precondition(lambda self: self._live())
    @rule(i=hst.integers(0, 5))
    def toggle_clickable(self, i):
        live = self._live()
        s = live[i % len(live)]
        s.clickable = not s.clickable

    @precondition(lambda self: self._live())
    @rule(i=hst.integers(0, 5), front=hst.booleans())
    def restack(self, i, front):
        live = self._live()
        s = live[i % len(live)]
        s.move_to_front() if front else s.move_to_back()

    @precondition(lambda self: self._live())
    @rule(i=hst.integers(0, 5))
    def destroy(self, i):
        live = self._live()
        live[i % len(live)].destroy()

    @rule(spot=hst.sampled_from(SPOTS))
    def move_pointer(self, spot):
        self.sim.note_pointer(world_xy=(ORIGIN + spot[0] + 1, ORIGIN + spot[1]))

    @precondition(lambda self: self.sim._hover_target is not None)
    @rule(spot=hst.sampled_from(SPOTS))
    def move_hovered(self, spot):
        self.sim._hover_target.move_to(ORIGIN + spot[0], ORIGIN + spot[1])

    # --- one frame after every rule, then the invariants ------------------------

    @invariant()
    def frame_then_check(self):
        self.sim.step_hover()
        target = self.sim._hover_target
        x, y = self.sim._ptr_world
        if target is not None:  # (a)
            assert target.is_alive and _drawn(target) and _eligible(target)
            assert target.contains_point(x, y)
            assert target.pointer_hover
        assert target is self._brute()  # (b)
        for s in self.shapes:  # (c)
            kinds = [k for k, who in self.log if who is s]
            assert kinds == ["enter", "exit"] * (len(kinds) // 2) + (
                ["enter"] if len(kinds) % 2 else [])
            if len(kinds) % 2:
                assert s is target

    def teardown(self):
        for s in self.shapes:
            if s.is_alive:
                s.destroy()
        for s in self.shapes:
            kinds = [k for k, who in self.log if who is s]
            assert len(kinds) % 2 == 0, kinds


TestHoverResolver = HoverMachine.TestCase


if __name__ == "__main__":
    unittest.main()
