"""Laws campaign, quick tier: the recorder itself (S0).

The laws recorder (``tests/laws/trace.py``) watches a run from outside the
engine through ``sys.monitoring``. Before any law can trust its trace:

* it leaves nothing behind (no tool id, no event set) — so a laws test
  cannot slow the modules that run after it in the same process;
* it sees every door an author function comes through (update, timers,
  contact handlers, on_destroy) and every frame;
* it is neutral (E0): the run with it is the run without it.

The canaries plant a recorder bug and require these checks to fail.
Strategy: design/Testing Design.md, "Laws and equations".

    python -m unittest tests.test_laws_quick -v
"""
from __future__ import annotations

import gc
import os
import sys
import unittest
import weakref
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import require_canaries  # noqa: E402
from laws import neutrality, trace  # noqa: E402
from laws.attach import attach  # noqa: E402
from program_support import ProgramRun  # noqa: E402

S0 = "tests/laws/fixtures/s0_basic"
PROBES = {"hits": lambda v: v.st.hits, "gone": lambda v: v.st.gone,
          "ticks": lambda v: v.st.ticks}


def _s0_run(frames: int = 90, **kw):
    run = ProgramRun(S0, kw.pop("params", {}), probes=PROBES, **kw)
    attach(run)
    run.start()
    try:
        run.step(frames)
        state = (run.ns["st"].hits, run.ns["st"].gone, run.ns["st"].ticks)
    finally:
        run.close()
    return run, state


def _s0_neutrality(frames: int = 90):
    """E0 on the fixture: samples, world, leftovers, recorder self-check."""
    import program_oracles as po
    from program_support import Scenario
    ns = {"SCENARIOS": {"s0": Scenario(steps=[("wait", frames)])}, "PROBES": PROBES}
    return neutrality.program(S0, ns, "s0")


class TestRecorderLeavesNothing(unittest.TestCase):

    def test_uninstall_frees_the_tool_and_every_event(self):
        rec = trace.install()
        tool = trace._tool
        codes = list(trace._hooks)
        self.assertEqual(sys.monitoring.get_tool(tool), trace.TOOL_NAME)
        trace.uninstall()
        self.assertEqual(trace.assert_clean(), [])
        self.assertIsNone(sys.monitoring.get_tool(tool))
        self.assertTrue(codes)
        self.assertIs(rec.errors, rec.errors)

    def test_a_second_install_is_refused(self):
        with trace.recording():
            with self.assertRaises(RuntimeError):
                trace.install()
        self.assertEqual(trace.assert_clean(), [])

    def test_the_engine_watchdog_id_and_the_sentinel_id_are_never_taken(self):
        self.assertNotIn(3, trace.TOOL_IDS)
        self.assertNotIn(4, trace.TOOL_IDS)


class TestRecorderSeesEveryDoor(unittest.TestCase):
    """The fixture: a ball breaks one brick, timers tick, the ball naps."""

    @classmethod
    def setUpClass(cls):
        cls.run_, cls.state = _s0_run()
        cls.rec = cls.run_.laws
        cls.ev = cls.rec.events

    def test_no_recorder_error_and_every_frame_seen(self):
        self.assertEqual(self.rec.errors, [])
        self.assertEqual(self.rec.counts["frames"], 90)
        self.assertEqual(sum(1 for e in self.ev if e[0] == "F"), 90)
        self.assertEqual(sum(1 for e in self.ev if e[0] == "f"), 90)

    def test_the_game_did_what_it_does(self):
        self.assertEqual(self.state[:2], (1, 1))     # one hit, one brick gone
        self.assertGreater(self.state[2], 3)

    def test_doors(self):
        doors = {e[1] for e in self.ev if e[0] == "X"}
        self.assertLessEqual({"update", "every", "after", "enter", "on_destroy"}, doors)

    def test_a_contact_handler_names_its_pair(self):
        hits = [e for e in self.ev if e[0] == "X" and e[1] == "enter"]
        self.assertEqual(len(hits), 1)
        _x, _door, phase, fn, args, _resume, method = hits[0]
        self.assertFalse(method)                     # a module rule, not a method
        self.assertEqual(phase, "collision")
        self.assertTrue(fn.endswith(":hit"))
        self.assertTrue(args[0].startswith("Circle@s0_basic.py:"))
        self.assertTrue(args[1].startswith("Brick@s0_basic.py:"))

    def test_creation_destroy_park_resume(self):
        bricks = [e for e in self.ev if e[0] == "N" and e[2] == "Brick"]
        self.assertEqual(len(bricks), 3)
        hit = next(e for e in self.ev if e[0] == "X" and e[1] == "enter")[4][1]
        kinds = [e[0] for e in self.ev if e[0] in "QDd" and e[1] == hit]
        self.assertEqual(kinds, ["Q", "D", "d"])
        ball = next(e[1] for e in self.ev if e[0] == "N" and e[2] == "Circle")
        self.assertEqual([e[0] for e in self.ev if e[0] in "KR" and e[1] == ball], ["K", "R"])

    def test_every_phase_opens_and_closes_in_frame_order(self):
        order = []
        for e in self.ev:
            if e[0] == "F":
                order = []
            elif e[0] == "P":
                order.append(e[1])
            elif e[0] == "f":
                break
        self.assertEqual(order, ["update", "tick", "collision", "leave", "hover", "flush",
                                 "predraw", "expire"])


class TestSuspendableFrames(unittest.TestCase):
    """A task or generator frame lives on after the recorder reads its locals.

    CPython 3.12 caches the read on the frame (the recorder drops it); from
    3.13 ``f_locals`` is a proxy with no cache and no ``clear`` (PEP 667).
    The 0.11.0 gate on 3.14 failed every laws run with a task method:
    ``'FrameLocalsProxy' object has no attribute 'clear'``.
    """

    def test_a_task_method_is_recorded_without_error(self):
        run = ProgramRun("tests/laws/fixtures/s4_timers")
        attach(run)
        run.start()
        try:
            run.step(30)
        finally:
            run.close()
        self.assertEqual(run.laws.errors, [])
        first = [e for e in run.laws.events
                 if e[0] == "X" and e[3].endswith(":Sleeper.count") and not e[5]]
        self.assertTrue(first, "the Sleeper's task never started under the recorder")

    def test_the_frame_keeps_its_variables(self):
        def body():
            x = 41
            yield
            yield x + 1

        g = body()
        next(g)
        trace._drop_locals_cache(g.gi_frame.f_locals)
        self.assertEqual(next(g), 42)

    def test_what_the_frame_let_go_is_freed(self):
        class Thing:
            pass

        def body():
            x = Thing()
            yield weakref.ref(x)
            x = None
            yield

        g = body()
        ref = next(g)
        trace._drop_locals_cache(g.gi_frame.f_locals)
        next(g)
        gc.collect()
        self.assertIsNone(ref(), "the f_locals snapshot still holds what the frame dropped")


class TestLabelsFollowTheObject(unittest.TestCase):
    """A label is the object's, not its address's: once an object is freed,
    an unlabelled object of the same type at the same ``id()`` has no label
    (S7: a history door's Point read as a freed Point)."""

    def test_a_reused_id_does_not_inherit_a_label(self):
        class Thing:
            pass
        rec = trace.Recorder()
        first = Thing()
        rec._new_label(first, "Thing", "g.py:1")
        old = id(first)
        del first
        for _ in range(10000):
            other = Thing()
            if id(other) == old:
                break
            del other
        else:
            self.skipTest("the allocator never reused the id")
        self.assertIsNone(rec.label_of(other))

    def test_a_reused_handle_id_does_not_inherit_a_label(self):
        # WP35: Handle had no weak reference, so the check above passed it by;
        # a timer on a destroyed actor (cancelled inside Scheduler.add, before
        # the probe labels it) read as a freed handle's cancel when it landed
        # at its address: an idle-rewrite diff in some processes only.
        from scena.process import Handle
        rec = trace.Recorder()
        first = object.__new__(Handle)
        rec._new_label(first, "Handle:after", "g.py:1")
        old = id(first)
        del first
        for _ in range(10000):
            other = object.__new__(Handle)
            if id(other) == old:
                break
            del other
        else:
            self.skipTest("the allocator never reused the id")
        self.assertIsNone(rec.label_of(other))
        self.assertEqual(rec.errors, [])

    def test_a_label_on_a_type_without_a_weak_reference_is_an_error(self):
        class Slotted:
            __slots__ = ("x",)
        rec = trace.Recorder()
        rec._new_label(Slotted(), "Slotted", "g.py:1")
        rec._new_label(Slotted(), "Slotted", "g.py:2")
        self.assertEqual(len(rec.errors), 1)
        self.assertIn("Slotted", rec.errors[0])

    def test_a_live_object_keeps_its_label(self):
        class Thing:
            pass
        rec = trace.Recorder()
        obj = Thing()
        label = rec._new_label(obj, "Thing", "g.py:1")
        self.assertEqual(rec.label_of(obj), label)


def _lazy_part_lines():
    """``{line: Points registered there}`` for a shuttle and a follower that
    links to its ``center`` (which fills the shuttle's ``fp1`` / ``fp2``)."""
    import inspect
    from scena import Ellipse
    from system_support import system_world
    rec = trace.Recorder()
    with system_world(draw=False):
        trace.install(rec)
        try:
            here = inspect.currentframe().f_lineno
            shuttle = Ellipse(center=(100, 100), width=58, height=12)
            follower = Ellipse(center=lambda: shuttle.center, width=24, height=5)
        finally:
            trace.uninstall()
        follower.destroy()
        shuttle.destroy()
    lines = {}
    for e in rec.events:
        if e[0] == "N" and e[2] == "Point" and e[3].startswith("test_laws_quick.py:"):
            line = int(e[3].rsplit(":", 1)[1]) - here
            lines[line] = lines.get(line, 0) + 1
    return lines


class TestLazyPartsAreTheirShapes(unittest.TestCase):
    """A part filled on first access (an Ellipse's foci, when another shape
    first links to its ``center``) is labelled at its shape's line, not at the
    line that read it: E3 swapped two readers of loom.py's shuttle and the
    shuttle's foci changed lines."""

    def test_the_foci_are_labelled_at_the_shuttle(self):
        # the shuttle's center and foci at its line; the follower's center at its own
        self.assertEqual(_lazy_part_lines(), {1: 3, 2: 1})


class TestNeutrality(unittest.TestCase):
    """E0: the run with the recorder is the run without it."""

    def test_fixture(self):
        self.assertEqual(_s0_neutrality(), [])

    def test_program(self):
        from program_support import load_spec
        ns = load_spec("bouncing_balls", "a")
        self.assertEqual(neutrality.program("bouncing_balls", ns, next(iter(ns["SCENARIOS"]))), [])


class TestCanaries(unittest.TestCase):
    """Prove the S0 checks can fail: plant a recorder bug, watch them bite."""

    def setUp(self):
        require_canaries(self)

    def test_a_disabled_frame_hook_is_caught(self):
        real = trace._on_start

        def planted(code, offset):
            if code is trace._frame_code:
                return sys.monitoring.DISABLE     # the plant: a hooked code disabled
            return real(code, offset)

        with mock.patch.object(trace, "_on_start", planted):
            msgs = _s0_neutrality(30)
        self.assertTrue(any("frames of 30" in m for m in msgs), msgs)

    def test_a_recorder_that_keeps_its_objects_is_caught(self):
        real = trace.Recorder._new_label
        kept = []

        def planted(self, obj, kind, site):
            kept.append(obj)                      # the plant: a strong reference
            return real(self, obj, kind, site)

        try:
            with mock.patch.object(trace.Recorder, "_new_label", planted):
                msgs = _s0_neutrality(30)
        finally:
            kept.clear()
        self.assertTrue(any("survivors" in m for m in msgs), msgs)

    def test_foci_labelled_at_their_reader_are_caught(self):
        # the plant: the part's own _site, the line that read it first
        with mock.patch.object(trace, "_materializing_site", lambda frame: None):
            self.assertEqual(_lazy_part_lines(), {1: 1, 2: 3})


if __name__ == "__main__":
    unittest.main()
