"""Process overlay (Ctrl+Shift+6 / ``show_processes``): the panel's rows.

One row per task (an async mode's body, ``run_task``) with what it awaits,
for how long (``Script.waiting_since``) and the author line; one row per
mode; alike rows fold; a long wait on an ``until`` is SLOW; the second step
adds the loose timers. Off, the draw reads nothing (Actors Design — Process
overlay).

    python tests/run_tiers.py focused test_process_overlay
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import (  # noqa: E402
    Circle, Entity, clock, every, on_mode, parallel, race, run_task, show_processes,
    until, until_empty, wait,
)
import scena.process as process  # noqa: E402
import scena.process_overlay as po  # noqa: E402
from scena.process import get_scheduler, reset_process_scheduler, tick_processes  # noqa: E402

HERE = os.path.basename(__file__)


def _frame(dt=0.1):
    clock.advance(dt)
    tick_processes()


def _frames(seconds, dt=0.1):
    for _ in range(int(round(seconds / dt))):
        _frame(dt)


def _line_of(marker: str) -> str:
    with open(__file__, encoding="utf-8") as f:
        for i, text in enumerate(f, 1):
            if marker in text and "_line_of" not in text:
                return f"{HERE}:{i}"
    raise AssertionError(marker)


class OverlayCase(unittest.TestCase):
    def setUp(self):
        reset_process_scheduler()
        clock.scale = 1.0
        clock.paused = False
        clock._dt = 0.0
        clock._time = 0.0
        clock._frame = 0
        self._owned = []
        self._top = process._top_level_ended
        process._set_top_level_ended(True)
        po._level = 0
        po._invalidate()

    def tearDown(self):
        for obj in self._owned:
            if getattr(obj, "is_alive", False):
                obj.destroy()
        reset_process_scheduler()
        process._set_top_level_ended(self._top)
        po._level = 0
        po._invalidate()

    def track(self, obj):
        self._owned.append(obj)
        return obj

    def task_rows(self):
        return [r for r in po.build_rows() if r.group == "task"]


class TestWaitingSince(OverlayCase):
    def test_age_restarts_at_each_await(self):
        flag = [False]

        async def seq():
            await wait(1.0)
            await until(lambda: flag[0])

        h = run_task(seq)
        _frames(0.5)
        self.assertAlmostEqual(h._elapsed - h._task.waiting_since, 0.5, places=6)
        _frames(1.5)                      # wait ends at 1.0, until since then
        script = h._task
        self.assertAlmostEqual(h._elapsed - script.waiting_since, 1.0, places=6)

    def test_age_frozen_while_parked(self):
        box = self.track(Circle())

        async def seq(c):
            await until(lambda: False)

        h = box.run_task(seq)
        _frames(1.0)
        box.active = False
        _frames(3.0)
        self.assertAlmostEqual(h._elapsed - h._task.waiting_since, 1.0, places=6)
        row = self.task_rows()[0]
        self.assertEqual(row.owner, "Circle (parked)")
        self.assertFalse(row.slow)


class TestAwaitDescriptions(OverlayCase):
    def test_wait(self):
        async def seq():
            await wait(2.0)  # @line-wait

        run_task(seq)
        _frames(0.5)
        (row,) = self.task_rows()
        self.assertEqual(row.awaiting, "wait 1.5s left")
        self.assertEqual(row.func, "seq")
        self.assertEqual(row.kind, "task")
        self.assertEqual(row.owner, "act")
        self.assertEqual(row.line, _line_of("@line-wait"))
        self.assertFalse(row.slow)

    def test_until_and_slow_at_threshold(self):
        async def seq():
            await until(lambda: False)  # @line-until

        run_task(seq)
        _frames(4.9)
        (row,) = self.task_rows()
        self.assertTrue(row.awaiting.startswith("until 4.9s"), row.awaiting)
        self.assertFalse(row.slow)
        _frames(0.1)
        (row,) = self.task_rows()
        self.assertTrue(row.slow)
        self.assertEqual(row.line, _line_of("@line-until"))
        self.assertEqual(po.task_counts(), (1, 1))

    def test_long_wait_is_not_slow(self):
        async def seq():
            await wait(30.0)

        run_task(seq)
        _frames(10.0, dt=0.5)
        (row,) = self.task_rows()
        self.assertFalse(row.slow)
        self.assertEqual(po.task_counts(), (1, 0))

    def test_until_empty(self):
        async def seq():
            await until_empty("nobody_is_this")

        box = self.track(Circle())
        box.group = "nobody_is_this"
        run_task(seq)
        (row,) = self.task_rows()
        self.assertTrue(row.awaiting.startswith("until_empty"), row.awaiting)

    def test_move_to_names_the_verb(self):
        box = self.track(Circle())

        async def seq(c):
            await c.move_to(100, 0, time=2)

        box.run_task(seq)
        _frames(0.5)
        (row,) = self.task_rows()
        self.assertEqual(row.awaiting, "move_to 1.5s left")
        self.assertEqual(row.owner, "Circle")

    def test_parallel_and_race(self):
        async def par():
            await parallel(wait(1.0), wait(3.0))

        async def rac():
            await race(until(lambda: False), until(lambda: False))

        run_task(par)
        run_task(rac)
        _frames(1.5)
        a, b = self.task_rows()
        self.assertEqual(a.awaiting, "parallel 1/2 done")
        self.assertEqual(b.awaiting, "race of 2")
        _frames(4.0)
        a, b = self.task_rows()[0], self.task_rows()[-1]
        self.assertEqual(b.func, "rac")
        self.assertTrue(b.slow)          # no clock member

    def test_awaited_task(self):
        async def inner():
            await wait(5.0)

        async def outer():
            await run_task(inner)

        run_task(outer)
        rows = self.task_rows()
        self.assertEqual(rows[0].func, "outer")
        self.assertTrue(rows[0].awaiting.startswith("task inner()"), rows[0].awaiting)

    def test_helper_line_is_the_helpers_await(self):
        async def helper():
            await until(lambda: False)  # @line-helper

        async def seq():
            await helper()

        run_task(seq)
        (row,) = self.task_rows()
        self.assertEqual(row.func, "seq")
        self.assertEqual(row.line, _line_of("@line-helper"))

    def test_named_task(self):
        async def seq():
            await wait(1)

        run_task(seq, name="power")
        (row,) = self.task_rows()
        self.assertEqual(row.kind, 'task "power"')


class TestRowsShape(OverlayCase):
    def test_alike_tasks_fold(self):
        async def seq(c):
            await wait(1.0)

        boxes = [self.track(Circle()) for _ in range(3)]
        for b in boxes:
            b.run_task(seq)
        rows = self.task_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].count, 3)
        self.assertEqual(rows[0].cells()[0], "Circle x3")

    def test_nested_task_is_indented(self):
        async def child():
            await wait(5.0)

        async def parent():
            run_task(child)
            await wait(9.0)

        run_task(parent)
        rows = self.task_rows()
        self.assertEqual([(r.func, r.depth) for r in rows], [("parent", 0), ("child", 1)])
        self.assertTrue(rows[1].cells()[0].startswith("|_ "))

    def test_owned_work_counted(self):
        async def seq():
            every(1.0, lambda: None)
            every(2.0, lambda: None)
            await wait(9.0)

        run_task(seq)
        (row,) = self.task_rows()
        self.assertEqual(row.work, 2)
        self.assertEqual(row.cells()[-1], "+2 work")

    def test_game_owner(self):
        process._set_top_level_ended(False)

        async def seq():
            await wait(1)

        run_task(seq)
        (row,) = self.task_rows()
        self.assertEqual(row.owner, "game")

    def test_time_zero_owner(self):
        box = self.track(Circle())

        async def seq(c):
            await wait(1)

        box.run_task(seq)
        box.time_scale = 0.0
        (row,) = self.task_rows()
        self.assertEqual(row.owner, "Circle (time 0)")

    def test_dead_owner_leaves(self):
        box = self.track(Circle())

        async def seq(c):
            await until(lambda: False)

        box.run_task(seq)
        self.assertEqual(len(self.task_rows()), 1)
        box.destroy()
        _frame()
        self.assertEqual(self.task_rows(), [])


class Wasp(Entity):
    def setup(self):
        self.mode = self.formation

    @on_mode
    def formation(self):
        every(1.0, self.shoot)

    def shoot(self):
        pass

    @on_mode
    async def diving(self):
        await wait(3.0)

    @on_mode
    async def quick(self):
        every(1.0, self.shoot)


class TestModeRows(OverlayCase):
    def test_sync_mode_rows_fold(self):
        for _ in range(4):
            self.track(Wasp())
        _frames(0.5)
        modes = [r for r in po.build_rows() if r.group == "mode"]
        self.assertEqual(len(modes), 1)
        row = modes[0]
        self.assertEqual((row.owner, row.func, row.kind, row.count), ("Wasp", "formation", "sync", 4))
        self.assertEqual(row.cells()[-1], "4 timers")
        self.assertAlmostEqual(row.age, 0.5, places=6)

    def test_async_mode_is_a_task_row_only(self):
        w = self.track(Wasp())
        w.mode = w.diving
        rows = po.build_rows()
        self.assertEqual([(r.group, r.func, r.kind) for r in rows], [("task", "diving", "mode")])

    def test_async_mode_whose_body_ended(self):
        w = self.track(Wasp())
        w.mode = w.quick
        rows = po.build_rows()
        self.assertEqual([(r.group, r.func, r.kind, r.awaiting) for r in rows],
                         [("mode", "quick", "mode", "body ended")])


class TestTimerRows(OverlayCase):
    def test_loose_timers_only_at_the_second_step(self):
        box = self.track(Circle())

        def blink():
            pass

        box.every(0.5, blink)

        async def seq():
            every(1.0, blink)            # the task's: counted on its row
            await wait(9)

        run_task(seq)
        self.assertEqual([r for r in po.build_rows() if r.group == "timer"], [])
        timers = [r for r in po.build_rows(timers=True) if r.group == "timer"]
        self.assertEqual(len(timers), 1)
        self.assertEqual((timers[0].owner, timers[0].func, timers[0].kind),
                         ("Circle", "blink", "every"))


class TestSwitch(OverlayCase):
    def test_show_processes_and_cycle(self):
        show_processes()
        self.assertEqual(po.processes_overlay_level(), 1)
        show_processes(False)
        self.assertEqual(po.processes_overlay_level(), 0)
        self.assertEqual([po.cycle_processes_overlay() for _ in range(3)], [1, 2, 0])

    def test_refuses_a_non_bool(self):
        with self.assertRaises(TypeError):
            show_processes("yes")

    def test_off_reads_nothing(self):
        with mock.patch.object(po, "panel_lines", side_effect=AssertionError("read")):
            po.draw_process_overlay(None, 800, 600)

    def test_draws_on_a_raster(self):
        import skia

        async def seq():
            await until(lambda: False)

        run_task(seq)
        _frames(6.0, dt=0.5)
        show_processes()
        surface = skia.Surface.MakeRasterN32Premul(800, 600)
        po.draw_process_overlay(surface.getCanvas(), 800, 600)
        header, lines = po.panel_lines()
        self.assertIn("1 task (1 slow)", header)
        self.assertEqual(lines[0][5], "SLOW")

    def test_empty_panel_and_row_cap(self):
        header, lines = po.panel_lines()
        self.assertEqual(lines[0][0], "nothing running")

        async def seq(n):
            await wait(1.0 + n)

        for n in range(po.MAX_ROWS + 3):
            run_task(lambda n=n: seq(n), name=f"t{n}")
        header, lines = po.panel_lines()
        self.assertEqual(len(lines), po.MAX_ROWS + 1)
        self.assertEqual(lines[-1][0], "+3 more")


class TestFramework(OverlayCase):
    def setUp(self):
        super().setUp()
        from scena import init
        from scena.orchestration import ScenaFramework
        init(width=800, height=600)
        self.fw = ScenaFramework.get_instance()

    def test_chord_cycles(self):
        import glfw
        mods = glfw.MOD_CONTROL | glfw.MOD_SHIFT
        seen = []
        for _ in range(3):
            self.assertTrue(self.fw._handle_framework_shortcut(glfw.KEY_6, glfw.PRESS, mods))
            seen.append((po.processes_overlay_level(), self.fw._feedback_text))
        self.assertEqual(seen, [(1, "Processes: on"), (2, "Processes: + timers"),
                                (0, "Processes: off")])

    def test_hud_counts_tasks(self):
        self.assertNotIn("tasks:", self.fw._system_info_text())

        async def seq():
            await until(lambda: False)

        run_task(seq)
        self.assertIn("tasks: 1  ", self.fw._system_info_text())
        _frames(5.0)
        self.assertIn("tasks: 1 (1 slow)", self.fw._system_info_text())


if __name__ == "__main__":
    unittest.main()
