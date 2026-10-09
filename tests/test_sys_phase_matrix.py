"""Phase × mutation × observer: a change made in one frame phase is seen by
every later phase of that frame, and by every phase of the next.

Interaction campaign, class 1 (design/Testing Design.md, "Interaction
campaign"). ``test_sys_frame_order`` checks four handoffs by hand; here the
documented frame order (Scena Design, "Frame order") is the oracle for the
whole product:

* **phase** where the mutation runs — ``update``, ``process`` (an actor's
  ``on_update``), ``collision`` (a pair handler), ``leave`` (a leave handler),
  ``hover`` (a hover handler), ``flush`` (a ``@when``), ``pre_draw`` (a
  transient ``on_done``); every arming is checked to have run in frame N and
  in that phase (a phase clock patched onto the frame body);
* **mutation** of the subject X — destroy, park, resume, hide, show,
  collidable off / on, untag / tag, move onto / off / far from its partner,
  an ink write;
* **observer** reading X from its own phase — the X–Y contact (collision
  handlers, phase 2), the leave edge (3), the hover level (4), a ``@when``
  on X's ink (5), X's own ``on_update`` tick (1), the drawn flag at draw (7).

Rule: the observer sees the new state in frame N when its phase comes after
the mutation's, in N or N+1 when it is the same phase (two handlers of one
step run in no promised order), else in N+1 — and never the old state after
that. ``EFFECT`` names what each mutation changes; every other observer must
not move. A cell the rule does not cover is a SPEC-GAP for the owning doc
first; ``KNOWN`` is shrink-only.

    python -m unittest tests.test_sys_phase_matrix -v
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_catches  # noqa: E402
from system_support import quiet, system_world  # noqa: E402

import scena.orchestration as orch  # noqa: E402
from scena import (Circle, Entity, clock, collide, collide_exit, collide_stay, hover,  # noqa: E402
                   hover_exit, leave_playfield, when)
from scena.bounds import get_bounds_system  # noqa: E402
from scena.collision import get_collision_system  # noqa: E402
from scena.entity import _drawn  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

N = 8                      # the frame of the mutation
FRAMES = N + 4             # frames run per cell
ORDER = {"update": 0, "process": 1, "collision": 2, "leave": 3, "hover": 4,
         "flush": 5, "pre_draw": 6, "draw": 7}
PHASES = ["update", "process", "collision", "leave", "hover", "flush", "pre_draw"]
# observer -> the phase it reads in, and its kind (a state per frame, or an edge)
OBSERVERS: Dict[str, Tuple[str, str]] = {
    "ticks": ("process", "state"),
    "contact": ("collision", "state"),
    "leave": ("leave", "edge"),
    "hover": ("hover", "state"),
    "when": ("flush", "edge"),
    "drawn": ("draw", "state"),
}

# mutation -> (how X starts, the mutation, what it changes)
#   start: a dict of X's initial deviations from the default cell (alive, over
#   Y, under the pointer, visible, collidable, tagged "x")
#   effect: observer -> new state (state observers) or True (an edge fires)
MUTATIONS: Dict[str, Dict[str, Any]] = {
    "destroy":        dict(start={}, effect={"contact": False, "hover": False,
                                             "drawn": False, "ticks": False}),
    "park":           dict(start={}, effect={"contact": False, "hover": False,
                                             "drawn": False, "ticks": False}),
    "resume":         dict(start={"parked": True}, effect={"contact": True, "hover": True,
                                                           "drawn": True, "ticks": True}),
    "hide":           dict(start={}, effect={"drawn": False, "hover": False}),
    "show":           dict(start={"hidden": True}, effect={"drawn": True, "hover": True}),
    "collidable_off": dict(start={}, effect={"contact": False}),
    "collidable_on":  dict(start={"opted_out": True}, effect={"contact": True}),
    "untag":          dict(start={}, effect={"contact": False}),
    "tag":            dict(start={"untagged": True}, effect={"contact": True}),
    "move_in":        dict(start={"away": True}, effect={"contact": True, "hover": True}),
    "move_out":       dict(start={}, effect={"contact": False, "hover": False}),
    "move_far":       dict(start={}, effect={"contact": False, "hover": False, "leave": True}),
    "ink_write":      dict(start={}, effect={"when": True}),
}

# (phase, mutation, observer) cells the matrix cannot read, with the reason.
NOT_OBSERVED: Dict[Tuple[str, str, str], str] = {
    ("hover", "*", "hover"): "the hover phase is armed by moving the pointer to a helper "
                             "card, so X is not under the pointer in that cell",
    ("*", "move_in", "hover"): "documented trade-off: a shape sliding under a still pointer "
                               "waits for pointer motion (test_pointer_hover.TestTradeOff)",
}

# Mutations whose effects may show in frame N from any phase: teardown is
# synchronous (Actors Design, Protections: a partner's exit fires from the
# destroy; a dead actor reads as gone at once).
SYNCHRONOUS = {"destroy"}

# Shrink-only: "phase | mutation | observer" -> reason (a finding or a settled
# contract difference). A listed cell must still fail; never list to pass.
KNOWN: Dict[str, str] = {
}

AWAY = (300.0, 0.0)          # inside the test world's playfield, off Y
FAR = (99999.0, 0.0)
# Phase helpers sit inside the playfield (400 x 300, pad 0.25), away from X and Y.
HELPERS = {"pair": (150.0, 100.0), "leaver": (200.0, 100.0), "card": (250.0, 100.0),
           "flasher": (300.0, 100.0)}


def _not_observed(phase: str, mutation: str, observer: str) -> Optional[str]:
    for (p, m, o), why in NOT_OBSERVED.items():
        if p in (phase, "*") and m in (mutation, "*") and o in (observer, "*"):
            return why
    return None


class PhaseClock:
    """``now`` names the phase the frame body is in (patched entry points)."""

    def __init__(self, w, cleanup: Callable[[Callable], Any],
                 log: Optional[List[Tuple[int, str]]] = None) -> None:
        self.now = "between"
        self.log = log
        self.on_draw: List[Callable[[], None]] = []
        fw = w.fw

        def enter(name, real):
            def run(*a, **k):
                self.mark(name)
                return real(*a, **k)
            return run

        def draw_hook(*a, **k):
            self.mark("draw")
            for fn in self.on_draw:
                fn()
            return real_draw(*a, **k)

        real_draw = fw._draw_frame
        col = get_collision_system()
        targets = [
            (orch, "tick_processes", enter("process", orch.tick_processes)),
            (col, "step", enter("collision", col.step)),
            (get_bounds_system(), "step", enter("leave", get_bounds_system().step)),
            (fw, "_step_hover", enter("hover", fw._step_hover)),
            (get_scena_system(), "flush", enter("flush", get_scena_system().flush)),
            (fw, "_tick_pre_draw", enter("pre_draw", fw._tick_pre_draw)),
            (fw, "_draw_frame", draw_hook),
        ]
        for target, attr, fn in targets:
            p = mock.patch.object(target, attr, new=fn)
            p.start()
            cleanup(p.stop)

    def mark(self, name: str) -> None:
        self.now = name
        if self.log is not None:
            self.log.append((clock.frame, name))


class Cell:
    """One (phase, mutation) world: X over Y under the pointer, every observer
    wired, the mutation armed in ``phase`` of frame N."""

    def __init__(self, tc: unittest.TestCase, w, phase: str, mutation: str) -> None:
        self.tc, self.w, self.phase, self.mutation = tc, w, phase, mutation
        self.clockp = PhaseClock(w, tc.addCleanup)
        self.armed_at: List[Tuple[int, str]] = []
        self.state: Dict[str, Dict[int, bool]] = {o: {} for o in OBSERVERS}
        self.edges: Dict[str, List[int]] = {"leave": [], "when": [], "hover_enter": [],
                                            "hover_exit": [], "contact_exit": []}
        self.update_hooks: List[Callable[[], None]] = []
        start = MUTATIONS[mutation]["start"]
        sm = w.fw.shape_manager
        spec = MUTATIONS[mutation]

        # -- the subject and its partner -------------------------------------
        x0 = AWAY if start.get("away") else (0.0, 0.0)
        with quiet():
            tags = {} if start.get("untagged") else {"group": "x"}
            self.x = x = w.track(Circle(center=x0, radius=8, **tags))
            self.y = w.track(Circle(center=(0.0, 0.0), radius=8, group="y"))
        x.hp = 5
        x.clickable = True

        frame = lambda: clock.frame  # noqa: E731

        @collide("x", "y")
        def _enter(a, b, info=None):
            self.state["contact"][frame()] = True

        @collide_stay("x", "y")
        def _stay(a, b, info=None):
            self.state["contact"][frame()] = True

        @collide_exit("x", "y")
        def _exit(a, b, info=None):
            self.edges["contact_exit"].append(frame())

        @leave_playfield("x")
        def _left(item):
            self.edges["leave"].append(frame())

        @hover(x)
        def _lit(card):
            self.edges["hover_enter"].append(frame())

        @hover_exit(x)
        def _unlit(card):
            self.edges["hover_exit"].append(frame())

        @when(lambda: x.hp <= 0)
        def _low():
            self.edges["when"].append(frame())

        x.on_update = lambda e, dt: self.state["ticks"].__setitem__(frame(), True)

        def at_draw():
            self.state["drawn"][frame()] = bool(x.is_alive and _drawn(x))
        self.clockp.on_draw.append(at_draw)

        sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(0.0, 0.0))
        if start.get("opted_out"):
            x.collidable = False
        if start.get("hidden"):
            x.visible = False
        if start.get("parked"):
            x.active = False

        # -- phase helpers, far from X --------------------------------------
        with quiet():
            self.ha = w.track(Circle(center=HELPERS["pair"], radius=8, group="ha"))
            self.hb = w.track(Circle(center=HELPERS["pair"], radius=8, group="hb"))
            self.hl = w.track(Circle(center=HELPERS["leaver"], radius=8, group="hl"))
            self.hc = w.track(Circle(center=HELPERS["card"], radius=8))
            self.hf = w.track(Circle(center=HELPERS["flasher"], radius=8))
        self.hc.clickable = True
        self.hk = w.track(Entity())
        self.hk.flag = False
        self.hp = w.track(Entity())
        self.hp.n = 0

        def fire():
            self.armed_at.append((frame(), self.clockp.now))
            self.apply()

        if phase == "update":
            self.update_hooks.append(lambda: fire() if frame() == N else None)
        elif phase == "process":
            self.hp.on_update = lambda e, dt: fire() if frame() == N else None
        elif phase == "collision":
            @collide_stay("ha", "hb")
            def _armed(a, b, info=None):
                if frame() == N:
                    fire()
        elif phase == "leave":
            @leave_playfield("hl")
            def _armed_leave(item):
                fire()
            self.update_hooks.append(
                lambda: self.hl.move_to(*FAR) if frame() == N else None)
        elif phase == "hover":
            @hover(self.hc)
            def _armed_hover(card):
                fire()
            self.update_hooks.append(
                lambda: sm.note_pointer(world_xy=HELPERS["card"]) if frame() == N else None)
        elif phase == "flush":
            @when(lambda: self.hk.flag)
            def _armed_when():
                fire()
            self.update_hooks.append(
                lambda: setattr(self.hk, "flag", True) if frame() == N else None)
        elif phase == "pre_draw":
            # 0.06 s (flash floor 0.05 s) started at N-4 ends inside frame N's
            # pre-draw tick: world time is pinned to 1/60 steps.
            self.update_hooks.append(
                lambda: self.hf.flash(0.06, on_done=fire) if frame() == N - 4 else None)
        else:
            raise ValueError(phase)

        def update(dt):
            self.clockp.mark("update")
            for fn in self.update_hooks:
                fn()
        w.on_update(update)

    # -- the mutation ------------------------------------------------------
    def apply(self) -> None:
        x, m = self.x, self.mutation
        if m == "destroy":
            x.destroy()
        elif m == "park":
            x.active = False
        elif m == "resume":
            x.active = True
        elif m == "hide":
            x.visible = False
        elif m == "show":
            x.visible = True
        elif m == "collidable_off":
            x.collidable = False
        elif m == "collidable_on":
            x.collidable = True
        elif m == "untag":
            x.untag("x")
        elif m == "tag":
            x.tag("x")
        elif m == "move_in":
            x.move_to(0.0, 0.0)
        elif m == "move_out":
            x.move_to(*AWAY)
        elif m == "move_far":
            x.move_to(*FAR)
        elif m == "ink_write":
            x.hp = 0
        else:
            raise ValueError(m)

    # -- the verdict ---------------------------------------------------------
    def run(self) -> List[str]:
        self.w.step(FRAMES)
        out = []
        if self.armed_at != [(N, self.phase)]:
            return [f"arming: the mutation ran at {self.armed_at}, want [({N}, {self.phase!r})]"]
        effect = MUTATIONS[self.mutation]["effect"]
        # The hover level as the hover step itself reports it: its enter /
        # exit handlers (phase 4), applied frame by frame.
        hovered = False
        for f in range(1, FRAMES + 1):
            for kind_, flag in (("hover_enter", True), ("hover_exit", False)):
                if f in self.edges[kind_]:
                    hovered = flag
            self.state["hover"][f] = hovered
        for obs, (obs_phase, kind) in OBSERVERS.items():
            if _not_observed(self.phase, self.mutation, obs):
                continue
            allowed = self._allowed(obs_phase)
            if kind == "edge":
                fired = self.edges[obs]
                if effect.get(obs):
                    if len(fired) != 1 or fired[0] not in allowed:
                        out.append(f"{obs}: fired at frames {fired}, want once in {sorted(allowed)}")
                elif fired:
                    out.append(f"{obs}: fired at frames {fired}, want never")
                continue
            series = [bool(self.state[obs].get(f, False)) for f in range(1, FRAMES + 1)]
            before = series[N - 3]            # frame N-2: settled, before the mutation
            if obs in effect:
                after = effect[obs]
                if before == after:
                    out.append(f"{obs}: already {after} before the mutation (cell builds no change)")
                    continue
                flips = [f for f in range(N - 1, FRAMES + 1) if series[f - 1] == after]
                first = flips[0] if flips else None
                tail_ok = first is not None and all(series[f - 1] == after
                                                    for f in range(first, FRAMES + 1))
                head_ok = all(series[f - 1] == before for f in range(N - 2, (first or FRAMES + 1)))
                if first not in allowed or not tail_ok or not head_ok:
                    out.append(f"{obs}: {self._show(series)}; want {before}→{after} at a frame in "
                               f"{sorted(allowed)}")
            else:
                moved = [f for f in range(N - 2, FRAMES + 1) if series[f - 1] != before]
                if moved:
                    out.append(f"{obs}: {self._show(series)}; must stay {before} "
                               f"(moved at {moved})")
        return out

    def _allowed(self, obs_phase: str) -> set:
        if ORDER[obs_phase] > ORDER[self.phase]:
            return {N}
        if ORDER[obs_phase] == ORDER[self.phase] or self.mutation in SYNCHRONOUS:
            return {N, N + 1}
        return {N + 1}

    @staticmethod
    def _show(series: List[bool]) -> str:
        return "".join("T" if s else "." for s in series) + f" (frames 1..{len(series)}, N={N})"


class TestPhaseMatrix(unittest.TestCase):
    """Every mutation in every phase; one subTest per phase."""
    maxDiff = None

    def _cell(self, phase: str, mutation: str) -> None:
        with system_world() as w:
            cell = Cell(self, w, phase, mutation)
            msgs = cell.run()
        key = f"{phase} | {mutation}"
        hits = [k for k in KNOWN if k.split(" | ")[0] in (phase, "*")
                and k.split(" | ")[1] in (mutation, "*")
                and any(m.startswith(k.split(" | ")[2]) for m in msgs)]
        if msgs and not hits:
            self.fail(f"{key}:\n  " + "\n  ".join(msgs))
        if hits and not msgs:
            self.fail(f"KNOWN entries no longer fail; remove them: {hits}")

    def _matrix(self, mutation: str) -> None:
        for phase in PHASES:
            with self.subTest(phase=phase):
                self._cell(phase, mutation)


for _m in MUTATIONS:
    setattr(TestPhaseMatrix, f"test_{_m}", (lambda m: lambda self: self._matrix(m))(_m))


class TestAxes(unittest.TestCase):
    """The tables cover each other; a new phase or observer needs a row."""

    def test_every_phase_is_in_the_order(self):
        for p in PHASES:
            self.assertIn(p, ORDER)
        for o, (p, kind) in OBSERVERS.items():
            self.assertIn(p, ORDER, o)
            self.assertIn(kind, ("state", "edge"), o)

    def test_every_effect_names_an_observer(self):
        for m, spec in MUTATIONS.items():
            for o in spec["effect"]:
                self.assertIn(o, OBSERVERS, f"{m}: {o}")

    def test_every_edge_observer_is_an_effect_of_some_mutation(self):
        edges = {o for o, (_p, k) in OBSERVERS.items() if k == "edge"}
        for o in edges:
            self.assertTrue(any(o in s["effect"] for s in MUTATIONS.values()), o)

    def test_frame_body_runs_every_phase_once_per_frame(self):
        """The phase clock sees each phase, in the documented order, every frame."""
        with system_world() as w:
            seen: List[Tuple[int, str]] = []
            pc = PhaseClock(w, self.addCleanup, log=seen)
            w.on_update(lambda dt: pc.mark("update"))
            w.step(4)
        for f in (3, 4):
            got = [p for fr, p in seen if fr == f]
            self.assertEqual(got, ["update", "process", "collision", "leave", "hover",
                                   "flush", "pre_draw", "draw"], f"frame {f}")

    def test_known_keys_name_real_cells(self):
        for key in KNOWN:
            p, m, o = key.split(" | ")
            self.assertTrue(p == "*" or p in PHASES, key)
            self.assertTrue(m == "*" or m in MUTATIONS, key)
            self.assertTrue(o in OBSERVERS, key)


class TestCanaries(unittest.TestCase):
    """Prove the matrix can fail (Testing Design: canaries)."""

    def test_catches_a_hover_step_that_never_runs(self):
        assert_catches(self, "test_sys_phase_matrix.TestPhaseMatrix.test_destroy",
                       [(orch.ScenaFramework, "_step_hover", lambda self: None)],
                       "a hover level that never updates")

    def test_catches_a_collision_step_that_keeps_stale_contacts(self):
        from scena.collision import CollisionSystem
        assert_catches(self, "test_sys_phase_matrix.TestPhaseMatrix.test_collidable_off",
                       [(CollisionSystem, "step", lambda self: None)],
                       "a collision step that never runs")


if __name__ == "__main__":
    unittest.main()
