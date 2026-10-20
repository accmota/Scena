"""``run_task``: an async sequence started from anywhere (Actors Design — Tasks).

A task is a ``Handle(kind="task")`` that drives a coroutine. ``run_task(fn)``
infers its owner like ``after`` (a bound method or a closure over ``self`` →
that actor; inside a mode body → that mode; else the act, or the game before
the top level ends); ``e.run_task(fn)`` is owned by ``e``. The first step runs
at the call; later steps in the process tick. Work the task starts belongs to
it: cancelling or replacing the task cancels that work; a task that finishes
leaves it running. An awaited handle cancelled under a task ends it with a
warning naming the reason (the task's own cancel is quiet).

    python tests/run_tiers.py focused test_tasks
"""
from __future__ import annotations

import asyncio
import gc
import os
import sys
import types
import unittest
import warnings
import weakref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import (  # noqa: E402
    Cancelled, Circle, Entity, Handle, after, clock, every, on_mode, parallel, race,
    run_task, until, wait,
)
import scena.process as process  # noqa: E402
from scena.process import get_scheduler, reset_process_scheduler, tick_processes  # noqa: E402


def _frame(dt=0.1):
    clock.advance(dt)
    tick_processes()


class TaskCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._frame = 0
        self._owned = []
        self._top = process._top_level_ended
        process._set_top_level_ended(True)        # after the seal: ownerless work is act work

    def tearDown(self):
        for obj in self._owned:
            if getattr(obj, "is_alive", False):
                obj.destroy()
        reset_process_scheduler()
        process._set_top_level_ended(self._top)

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def caught(self, body):
        with warnings.catch_warnings(record=True) as got:
            warnings.simplefilter("always")
            body()
        return [str(w.message) for w in got]


async def _seq_log(log, tag="a", n=2):
    for i in range(n):
        log.append((tag, i))
        await wait(0.1)
    log.append((tag, "end"))
    return tag


class TestRefusals(TaskCase):
    def assertRefused(self, fn, *needles):
        msgs = self.caught(lambda: self.assertRaises(TypeError, run_task, fn))
        with self.assertRaises(TypeError) as cm:
            run_task(fn)
        for needle in needles:
            self.assertIn(needle, str(cm.exception))
        self.assertFalse([m for m in msgs if "never awaited" in m], msgs)
        self.assertEqual(get_scheduler()._tasks, {})

    def test_none_and_non_callable(self):
        self.assertRefused(None, "expected a function")
        self.assertRefused(3, "expected a function")

    def test_a_coroutine_is_closed_and_refused(self):
        async def show():
            await wait(1)

        self.assertRefused(show(), "run_task(show)", "lambda")

    def test_a_plain_def_is_refused(self):
        def plain():
            pass

        self.assertRefused(plain, "async def")

    def test_a_mode_is_refused(self):
        @on_mode
        async def diving(e):
            await wait(1)

        self.assertRefused(diving, "mode", "self.mode")

    def test_a_lambda_must_return_a_call_of_an_async_function(self):
        with self.assertRaises(TypeError) as cm:
            run_task(lambda: 3)
        self.assertIn("async", str(cm.exception))
        self.assertEqual(get_scheduler()._tasks, {})


class TestRunning(TaskCase):
    def test_first_step_runs_at_the_call_later_steps_in_the_tick(self):
        log = []
        h = run_task(lambda: _seq_log(log))
        self.assertIsInstance(h, Handle)
        self.assertEqual(h.kind, "task")
        self.assertEqual(log, [("a", 0)])
        _frame(0.1)
        self.assertEqual(log, [("a", 0), ("a", 1)])
        _frame(0.1)
        self.assertEqual(log[-1], ("a", "end"))
        self.assertTrue(h.done)
        self.assertFalse(h.cancelled)

    def test_owner_is_passed_like_after(self):
        box = self.track(Circle())
        seen = []

        async def show(b):
            seen.append(b)

        box.run_task(show)
        self.assertEqual(seen, [box])

    def test_await_a_task_returns_its_value(self):
        out = []

        async def child():
            await wait(0.1)
            return 42

        async def parent():
            out.append(await run_task(child))

        run_task(parent)
        _frame(0.1)
        _frame(0.1)
        self.assertEqual(out, [42])

    def test_parallel_and_race_take_tasks(self):
        log = []

        async def both():
            await parallel(run_task(lambda: _seq_log(log, "x", 1)),
                           run_task(lambda: _seq_log(log, "y", 3)))
            log.append("both")
            first = await race(run_task(lambda: _seq_log(log, "p", 1)),
                               run_task(lambda: _seq_log(log, "q", 5)))
            log.append(("race", first))

        run_task(both)
        for _ in range(8):
            _frame(0.1)
        self.assertIn("both", log)
        self.assertIn(("race", 0), log)
        self.assertLess(log.index(("y", "end")), log.index("both"))

    def test_elapsed_follows_world_time_and_park(self):
        box = self.track(Circle())

        async def long(b):
            await wait(10)

        h = box.run_task(long)
        _frame(0.2)
        self.assertAlmostEqual(h.elapsed, 0.2)
        box.time_scale = 0.5
        _frame(0.2)
        self.assertAlmostEqual(h.elapsed, 0.3)
        box.active = False
        _frame(0.2)
        self.assertAlmostEqual(h.elapsed, 0.3)
        self.assertEqual(h.remaining, 0.0)

    def test_pause_is_refused(self):
        h = run_task(lambda: _seq_log([]))
        with self.assertRaises(TypeError):
            h.pause()

    def test_a_task_cannot_await_itself(self):
        hold = {}

        async def selfish():
            await wait(0.1)
            await hold["h"]

        hold["h"] = run_task(selfish)
        with self.assertRaises(TypeError):
            _frame(0.1)

    def test_errors_raise_at_the_call_and_from_the_tick(self):
        async def bad_now():
            raise ValueError("first step")

        async def bad_later():
            await wait(0.1)
            raise ValueError("later")

        with self.assertRaises(ValueError):
            run_task(bad_now)
        run_task(bad_later)
        with self.assertRaises(ValueError):
            _frame(0.1)


class TestOwnership(TaskCase):
    def test_free_function_after_the_seal_is_act_work(self):
        h = run_task(lambda: _seq_log([]))
        self.assertIsNone(h.owner)
        self.assertEqual(h.scope, "act")

    def test_top_level_is_game_work_and_its_children_stay_game(self):
        process._set_top_level_ended(False)
        kids = []

        async def intro():
            kids.append(wait(5))
            await kids[-1]

        h = run_task(intro)
        self.assertEqual(h.scope, "game")
        process._set_top_level_ended(True)
        _frame(0.1)
        self.assertEqual(kids[0].scope, "game")
        get_scheduler().cancel_ownerless("act")          # an act change
        self.assertFalse(h.cancelled)
        self.assertFalse(kids[0].cancelled)

    def test_bound_method_and_closure_over_self_belong_to_the_actor(self):
        class Ship(Circle):
            async def flash(self):
                await wait(5)

            def start(self):
                return run_task(self.flash), run_task(lambda: self.flash())

        s = self.track(Ship())
        a, b = s.start()
        for h in (a, b):
            self.assertIs(h.owner, s)
            self.assertEqual(h.scope, "entity")
        s.destroy()
        self.assertTrue(a.cancelled and b.cancelled)

    def test_inside_a_mode_body_it_is_mode_work(self):
        c = self.track(Circle())
        got = {}

        async def side():
            await wait(5)

        async def formation(e):
            got["bare"] = run_task(side)
            got["own"] = e.run_task(side)
            await wait(5)

        c.mode = formation
        self.assertEqual(got["bare"].scope, "mode")
        self.assertEqual(got["own"].scope, "entity")
        c.mode = None
        self.assertTrue(got["bare"].cancelled)
        self.assertFalse(got["own"].cancelled)

    def test_dead_owner_never_starts(self):
        box = Circle()
        box.destroy()
        called = []

        async def show(b):
            called.append(b)

        h = box.run_task(show)
        self.assertTrue(h.cancelled)
        self.assertEqual(called, [])
        self.assertEqual(get_scheduler()._tasks, {})


class TestNameSlot(TaskCase):
    def test_name_restarts_and_cancels_the_old_runs_work(self):
        log = []

        async def power():
            log.append("start")
            after(0.15, lambda: log.append("stale step"))
            await wait(1)
            log.append("end")

        first = run_task(power, name="power")
        _frame(0.1)
        second = run_task(power, name="power")
        self.assertTrue(first.cancelled)
        _frame(0.1)
        self.assertNotIn("stale step", log)
        self.assertFalse(second.done)

    def test_a_nested_task_restarting_itself_stays_under_its_parent(self):
        made = {}

        async def loop():
            made.setdefault("runs", []).append(1)
            await wait(0.1)
            if len(made["runs"]) < 3:
                made["last"] = run_task(loop, name="inner")

        async def outer():
            made["first"] = run_task(loop, name="inner")
            await wait(5)

        h = run_task(outer)
        _frame(0.1)
        _frame(0.1)
        last = made["last"]
        self.assertIs(last._task_parent, h)
        h.cancel()
        self.assertTrue(last.cancelled)

    def test_a_task_restarting_itself(self):
        runs = []

        async def loop():
            runs.append(len(runs))
            await wait(0.1)
            if len(runs) < 3:
                run_task(loop, name="loop")

        run_task(loop, name="loop")
        for _ in range(4):
            _frame(0.1)
        self.assertEqual(runs, [0, 1, 2])


class TestWatchdog(TaskCase):
    def test_a_spinning_task_is_named(self):
        old, every_ = process.WATCHDOG_RESUME_S, process.WATCHDOG_CHECK_EVERY
        process.WATCHDOG_RESUME_S, process.WATCHDOG_CHECK_EVERY = 0.05, 64
        self.addCleanup(setattr, process, "WATCHDOG_RESUME_S", old)
        self.addCleanup(setattr, process, "WATCHDOG_CHECK_EVERY", every_)
        process.set_watchdog(True)

        async def spinner():
            await wait(0.1)
            while True:
                pass

        h = run_task(spinner)
        msgs = self.caught(lambda: _frame(0.1))
        hits = [m for m in msgs if "SCENA ERROR" in m]
        self.assertEqual(len(hits), 1, msgs)
        self.assertIn("task spinner()", hits[0])
        self.assertIn("the task was CANCELLED", hits[0])
        self.assertTrue(h.cancelled)


class _YieldsNone:
    def __await__(self):
        yield


class _YieldsText:
    def __await__(self):
        yield "nope"


@types.coroutine
def _bare_yield():
    yield


async def _helper_with_asyncio_sleep():
    await asyncio.sleep(0)


class TestOnlyAHandleIsAwaited(TaskCase):
    """The tick resumes a task only when the Handle it awaits ends. Anything
    else a step yields — a bare yield (``asyncio.sleep(0)``) included — is
    refused at the ``await`` with the fix: before 2026-10-20 a None yield
    left the task waiting forever, with no error (``waiting_on`` None reads
    "still waiting" in the walk)."""

    # name, makes the awaitable, what the message names
    CASES = (
        ("asyncio.sleep(0)", lambda: asyncio.sleep(0), "asyncio.sleep()"),
        ("types.coroutine bare yield", _bare_yield, "_bare_yield()"),
        ("__await__ yields None", _YieldsNone, "_YieldsNone"),
        ("__await__ yields a str", _YieldsText, "_YieldsText"),
        ("asyncio.Future", lambda: asyncio.Future(loop=_asyncio_loop()), "asyncio.Future"),
        ("helper awaiting asyncio.sleep(0)", _helper_with_asyncio_sleep, "asyncio.sleep()"),
    )

    def assert_live_tasks_wait_on_a_handle(self):
        for handle in list(get_scheduler()._tasks):
            if not handle._done:
                self.assertIsInstance(handle._task.waiting_on, Handle)

    def assert_refused(self, start, name, line, *, later):
        """``start()`` runs the body; ``later``: its first step awaits wait(0.1)."""
        ran = []
        if later:
            h = start(ran)
            self.assert_live_tasks_wait_on_a_handle()
            with self.assertRaises(TypeError) as cm:
                _frame(0.1)
        else:
            with self.assertRaises(TypeError) as cm:
                start(ran)
            h = None
        msg = str(cm.exception)
        self.assertIn(f"awaited {name}", msg)
        self.assertIn("await a Handle", msg)
        self.assertIn("wait(seconds)", msg)
        self.assertIn(f"test_tasks.py, line {line}", msg)
        self.assertEqual(ran, [], "nothing after the await ran")
        if h is not None:
            self.assertTrue(h.cancelled)
            self.assertTrue(h.done)
        for _ in range(3):
            _frame(0.1)                              # nothing left to resume, no error
        self.assertEqual(ran, [])
        self.assert_live_tasks_wait_on_a_handle()
        self.assertFalse([t for t in get_scheduler()._tasks if not t._done])

    def test_run_task_refuses_each_kind_at_the_first_step(self):
        for label, make, name in self.CASES:
            with self.subTest(label):
                reset_process_scheduler()

                async def body(ran):
                    await make()
                    ran.append("after")

                line = body.__code__.co_firstlineno + 1
                self.assert_refused(lambda ran: run_task(lambda: body(ran)), name,
                                    line if "helper" not in label else _HELPER_LINE,
                                    later=False)

    def test_run_task_refuses_each_kind_at_a_later_step(self):
        for label, make, name in self.CASES:
            with self.subTest(label):
                reset_process_scheduler()

                async def body(ran):
                    await wait(0.1)
                    await make()
                    ran.append("after")

                line = body.__code__.co_firstlineno + 2
                self.assert_refused(lambda ran: run_task(lambda: body(ran)), name,
                                    line if "helper" not in label else _HELPER_LINE,
                                    later=True)

    def test_an_async_mode_refuses_each_kind(self):
        for label, make, name in self.CASES:
            for later in (False, True):
                with self.subTest(label, later=later):
                    reset_process_scheduler()
                    c = self.track(Circle())

                    async def diving(e):
                        if later:
                            await wait(0.1)
                        await make()
                        e.ran.append("after")

                    def start(ran):
                        c.ran = ran
                        c.mode = diving
                        return c._mode_task

                    line = diving.__code__.co_firstlineno + 3
                    self.assert_refused(start, name,
                                        line if "helper" not in label else _HELPER_LINE,
                                        later=later)
                    self.assertIsNone(c._mode_task)

    def test_the_message_names_the_mode(self):
        c = self.track(Circle())

        async def diving(e):
            await asyncio.sleep(0)

        with self.assertRaises(TypeError) as cm:
            c.mode = diving
        self.assertIn("async mode 'diving'", str(cm.exception))
        self.assertIn("asyncio event loop", str(cm.exception))

    def test_a_bare_yield_says_it_would_never_resume(self):
        async def body():
            await asyncio.sleep(0)

        with self.assertRaises(TypeError) as cm:
            run_task(body)
        self.assertIn("task body()", str(cm.exception))
        self.assertIn("never resume", str(cm.exception))

    def test_an_awaiter_of_the_refused_task_is_not_left_waiting(self):
        seen = []

        async def bad():
            await wait(0.1)
            await asyncio.sleep(0)

        async def outer():
            try:
                await run_task(bad)
            except Cancelled:
                seen.append("cancelled")

        h = run_task(outer)
        with self.assertRaises(TypeError):
            _frame(0.1)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _frame(0.1)
        self.assertEqual(seen, ["cancelled"])
        self.assertTrue(h.done)

    def test_wait_zero_is_the_fix_it_names(self):
        frames = []

        async def body():
            for _ in range(3):
                await wait(0)
                frames.append(clock._frame)

        run_task(body)
        for _ in range(4):
            _frame(1 / 60)
        self.assertEqual(frames, [1, 2, 3])          # one step a frame, no spin


_HELPER_LINE = _helper_with_asyncio_sleep.__code__.co_firstlineno + 1
_LOOP = []


def _asyncio_loop():
    """A loop only to build a Future (never run: Scena's tick drives tasks)."""
    if not _LOOP:
        _LOOP.append(asyncio.new_event_loop())
    return _LOOP[0]


def tearDownModule():
    while _LOOP:
        _LOOP.pop().close()


class TestChildren(TaskCase):
    def test_cancel_cascades_to_its_work(self):
        made = {}

        async def show():
            made["after"] = after(5, lambda: None)
            made["inner"] = run_task(lambda: _seq_log([], "i", 9))
            await wait(5)

        h = run_task(show)
        h.cancel()
        self.assertTrue(made["after"].cancelled)
        self.assertTrue(made["inner"].cancelled)

    def test_its_work_is_gone_before_its_finally_runs(self):
        seen = {}

        async def show():
            timer = after(5, lambda: None)
            try:
                await wait(5)
            finally:
                seen["timer_cancelled"] = timer.cancelled

        run_task(show).cancel()
        self.assertEqual(seen, {"timer_cancelled": True})

    def test_a_finished_task_leaves_its_work_running(self):
        log = []

        async def show():
            after(0.3, lambda: log.append("later"))
            await wait(0.1)

        h = run_task(show)
        _frame(0.1)
        self.assertTrue(h.done)
        for _ in range(3):
            _frame(0.1)
        self.assertEqual(log, ["later"])

    def test_work_of_a_finished_nested_task_passes_to_the_outer(self):
        made = {}

        async def inner():
            made["after"] = after(5, lambda: None)

        async def outer():
            await run_task(inner)
            await wait(5)

        h = run_task(outer)
        _frame(0.1)
        h.cancel()
        self.assertTrue(made["after"].cancelled)

    def test_another_actors_bound_method_is_not_its_work(self):
        bomb = self.track(Circle())
        made = {}

        async def show():
            made["boom"] = after(5, bomb.destroy)
            await wait(5)

        run_task(show).cancel()
        self.assertFalse(made["boom"].cancelled)

    def test_work_made_after_its_own_mode_switch_dies_with_the_old_mode(self):
        c = self.track(Circle())
        made = {}

        def calm(e):
            pass

        async def angry(e):
            e.mode = calm
            made["late"] = after(1, lambda: None)   # still in angry's step
            await wait(1)

        c.mode = angry
        self.assertTrue(made["late"].cancelled)
        self.assertTrue(c.mode == calm)

    def test_back_pointers_are_cleared_when_work_ends(self):
        made = {}

        async def show():
            made["short"] = after(0.05, lambda: None)
            made["long"] = after(5, lambda: None)
            await wait(0.1)
            await wait(5)

        h = run_task(show)
        coro = weakref.ref(h._task.coro)
        _frame(0.1)
        self.assertIsNone(made["short"]._task_parent, "a finished child unlinks")
        self.assertIn(made["long"], h._children)
        self.assertNotIn(made["short"], h._children)
        h.cancel()
        self.assertIsNone(h._children)
        self.assertIsNone(h._task)
        self.assertIsNone(made["long"]._task_parent)
        gc.collect()
        self.assertIsNone(coro(), "the cancelled body is freed")


class TestCancelledUnderIt(TaskCase):
    def test_target_destroyed_warns_with_the_reason(self):
        box = self.track(Circle())

        async def show():
            await box.move_to(100, 0, time=1)

        run_task(show)
        msgs = self.caught(lambda: (box.destroy(), _frame(0.1)))
        hits = [m for m in msgs if "silently cancelled" in m]
        self.assertEqual(len(hits), 1, msgs)
        self.assertIn("show()", hits[0])
        self.assertIn("destroyed", hits[0])
        self.assertIn("test_tasks.py", hits[0])

    def test_own_cancel_is_quiet(self):
        h = run_task(lambda: _seq_log([], "q", 5))
        self.assertEqual(self.caught(h.cancel), [])

    def test_catching_cancelled_goes_on(self):
        box = self.track(Circle())
        log = []

        async def show():
            try:
                await box.move_to(100, 0, time=1)
            except Cancelled:
                log.append("caught")
            await wait(0.1)
            log.append("after")

        run_task(show)
        msgs = self.caught(lambda: (box.destroy(), _frame(0.1), _frame(0.1)))
        self.assertEqual(log, ["caught", "after"])
        self.assertFalse([m for m in msgs if "silently cancelled" in m])


class TestPhases(TaskCase):
    def test_started_from_a_when_callback_steps_in_the_tick(self):
        # first step where it is started, the next ones in the process tick
        log = []

        async def show():
            log.append(("first", process.get_scheduler()._iterating))
            await wait(0.1)
            log.append(("later", process.get_scheduler()._iterating))

        run_task(show)
        _frame(0.1)
        self.assertEqual(log, [("first", False), ("later", True)])


if __name__ == "__main__":
    unittest.main()
