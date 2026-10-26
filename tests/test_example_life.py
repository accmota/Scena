"""
The claims of ``examples/life.py``, played headless.

The example says: the grid builds itself (every line flies from the corner
to its place) and then the game runs; the rules are Conway's (a live cell
with two or three live neighbours stays, a dead cell with exactly three is
born, every other cell dies) on a board that wraps round (a glider that
leaves on one side comes back on the other); a newborn starts at ``BORN``
of a grown cell and grows over ``GROW`` ticks to ``SIZE`` (not at once); a
cell dies shrinking away (it ends hidden); a click flips a cell and a drag
paints what the first cell became; when the board stops changing an
R-pentomino falls on it; and the board follows from ``COLS`` alone (square
cells, ``ROWS * CELL`` fits 672, centred up and down, 1120 wide).

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (tweens of a Line's ends, a shape's named tweens that
replace each other, ``on_done``, held-button reads and ``on_mouse_down``)
while it still builds and runs (``test_scripts_run`` only plays 30 frames);
a grid line that ends a fraction off its row (a tween that lands short); and
a board laid out for one ``COLS`` only (the file runs again with
``COLS = 40``).

Every tick the game plays here is held to an independent Conway step on a
torus, from the board the frame before.

Run:

    python tests/run_tiers.py focused test_example_life
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings
from collections import Counter
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
import scena.process  # noqa: E402
from scena import clock  # noqa: E402

PATH = "examples/life.py"
SECOND = 60
SCENA_DIR = os.path.normcase(os.path.join(ROOT, "scena")) + os.sep
OTHER_COLS = 40
EPS = 1e-9
GLIDER = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]     # moves +1 row, +1 column every 4 ticks
BLINKER = [(0, -1), (0, 0), (0, 1)]
R_PENTOMINO = [(0, 0), (0, 1), (1, -1), (1, 0), (2, 0)]


def engine_warnings(caught) -> list:
    """The warnings the engine raised (a SCENA message, or raised from scena/)."""
    return [f"{w.category.__name__}: {w.message}" for w in caught
            if "SCENA" in str(w.message)
            or os.path.normcase(os.path.abspath(w.filename)).startswith(SCENA_DIR)]


def source() -> str:
    with open(os.path.normpath(os.path.join(ROOT, *PATH.split("/"))), encoding="utf-8") as fh:
        return fh.read()


def board(ns) -> frozenset:
    return frozenset((r, c) for r, row in enumerate(ns["alive"]) for c, live in enumerate(row) if live)


def conway(live: frozenset, rows: int, cols: int) -> frozenset:
    """One Conway step on a rows x cols torus (independent of the example)."""
    near = Counter(((r + dr) % rows, (c + dc) % cols)
                   for r, c in live for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc)
    return frozenset(p for p, n in near.items() if n == 3 or (n == 2 and p in live))


def is_seed(want: frozenset, after: frozenset, rows: int, cols: int) -> bool:
    """``after`` is ``want`` with an R-pentomino (the example's seed) laid on it."""
    added = after - want
    if not want <= after or len(added) > 5:
        return False
    for r, c in added:              # some cell of the seed is its (0, 0)
        for dr, dc in R_PENTOMINO:
            shape = {((r - dr + er) % rows, (c - dc + ec) % cols) for er, ec in R_PENTOMINO}
            if added <= shape and shape <= after:
                return True
    return False


def ends(line) -> tuple:
    return ((line.p1.x, line.p1.y), (line.p2.x, line.p2.y))


def layout(ns) -> dict:
    """The board's numbers and every grid line's ends, once the grid is in place."""
    return {
        "COLS": ns["COLS"], "ROWS": ns["ROWS"], "CELL": ns["CELL"], "LEFT": ns["LEFT"],
        "BOTTOM": ns["BOTTOM"], "SIZE": ns["SIZE"],
        "rows": [ends(ln) for ln in ns["rows"]], "columns": [ends(ln) for ln in ns["columns"]],
        "cells": [len(ns["cells"])] + sorted({len(row) for row in ns["cells"]}),
        "centres": [(r, c, ns["cells"][r][c].center.x, ns["cells"][r][c].center.y)
                    for r in (0, ns["ROWS"] - 1) for c in (0, ns["COLS"] - 1)],
    }


class Game:
    """Steps the program and holds every tick to ``conway``."""

    def __init__(self, run, ticks: list):
        self.run = run
        self.ns = run.ns
        self.st = run.ns["st"]
        self.ticks = ticks        # (tick, before, after, quiet after)

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            before, count = board(self.ns), self.st.ticks
            self.run.step(1)
            if self.st.ticks != count:
                assert self.st.ticks == count + 1, "two ticks in one frame"
                self.ticks.append((self.st.ticks, before, board(self.ns), self.st.quiet))

    def until(self, pred, seconds: float) -> None:
        for _ in range(int(seconds * SECOND)):
            if pred():
                return
            self.step()
        raise AssertionError(f"not reached in {seconds} s")

    def clear(self) -> None:
        """Pause, empty the board and let the dying cells go."""
        self.st.running = False
        for r in range(self.ns["ROWS"]):
            for c in range(self.ns["COLS"]):
                self.ns["flip"](r, c, False)
        self.step(int(SECOND * 3 * self.st.period) + 2)

    def centre(self, r: int, c: int) -> tuple:
        return self.ns["place"](r, c)


class TestLife(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ticks = []
        with warnings.catch_warnings(record=True) as caught, \
                mock.patch.object(scena.process, "WATCHDOG_RESUME_S", 5.0):
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                cls.play(run)
                cls.author_error = scena.process.last_author_error()
            # the same file with another COLS: the board follows
            text = source()
            assert "COLS = 60 " in text
            with ProgramRun(PATH, seed=1, source=text.replace("COLS = 60 ", f"COLS = {OTHER_COLS} ", 1)) as run:
                game = Game(run, [])
                game.until(lambda: run.ns["st"].running, 15)
                cls.other = layout(run.ns)
                cls.other_ran = run.ns["st"].ticks
                game.step(SECOND)
                cls.other_ran = run.ns["st"].ticks - cls.other_ran
        cls.warned = engine_warnings(caught)

    @classmethod
    def play(cls, run) -> None:
        ns, st = run.ns, run.ns["st"]
        game = Game(run, cls.ticks)
        rows, cols = ns["ROWS"], ns["COLS"]
        cls.rows, cls.cols = rows, cols
        cls.size, cls.born, cls.grow, cls.period = ns["SIZE"], ns["BORN"], ns["GROW"], st.period
        cls.seed_shape = list(ns["R_PENTOMINO"])
        # -- the grid flies into place, then the soup, then the game runs
        game.until(lambda: st.ready, 12)
        cls.ready_at = clock.time
        game.until(lambda: st.running, 6)
        cls.running_at = clock.time
        cls.grid = layout(ns)
        cls.soup = len(board(ns))
        game.step(3 * SECOND)
        cls.soup_ticks = len(cls.ticks)
        # -- a dead cell ends hidden
        game.clear()
        cls.cleared = (len(board(ns)), sum(1 for row in ns["cells"] for cell in row if cell.visible))
        # -- a glider that wraps across both edges, and a blinker
        r0, c0 = rows - 4, cols - 4
        glider = frozenset(((r0 + dr) % rows, (c0 + dc) % cols) for dr, dc in GLIDER)
        blinker = frozenset((rows // 2 + dr, cols // 2 + dc) for dr, dc in BLINKER)
        for r, c in glider | blinker:
            ns["flip"](r, c, True)
        st.quiet = 0
        first = len(cls.ticks)
        st.running = True
        game.until(lambda: len(cls.ticks) - first >= 36, 10)
        st.running = False
        cls.glider = (glider, blinker, [after for _, _, after, _ in cls.ticks[first:first + 36]])
        # -- a click flips a cell; a newborn grows over GROW ticks
        game.clear()
        r, c = rows // 3, cols // 3
        cell = ns["cells"][r][c]
        run.press(*game.centre(r, c))
        game.step(1)
        run.release()
        born_at = clock.time
        cls.growth = []
        for _ in range(int((ns["GROW"] + 2) * st.period * SECOND)):
            cls.growth.append((clock.time - born_at, cell.length, cell.visible, ns["alive"][r][c]))
            game.step(1)
        run.press(*game.centre(r, c))
        game.step(1)
        run.release()
        died_at = clock.time
        cls.dying = []
        for _ in range(int(3 * st.period * SECOND)):
            cls.dying.append((clock.time - died_at, cell.length, cell.visible, ns["alive"][r][c]))
            game.step(1)
        # -- a drag paints what the first cell became
        r = rows // 2 + 5
        run.press(*game.centre(r, 10))
        game.step(2)
        for k in range(11, 16):
            run.move(*game.centre(r, k))
            game.step(2)
        run.release()
        game.step(2)
        cls.painted = sorted(c for rr, c in board(ns) if rr == r)
        run.press(*game.centre(r, 12))            # a live cell: the drag clears
        game.step(2)
        for k in list(range(13, 16)) + [16, 17]:  # on past the painted ones
            run.move(*game.centre(r, k))
            game.step(2)
        run.release()
        game.step(int(3 * st.period * SECOND))
        cls.erased = sorted(c for rr, c in board(ns) if rr == r)
        # -- a still board gets a seed
        game.clear()
        for dr, dc in ((0, 0), (0, 1), (1, 0), (1, 1)):       # a block: it never changes
            ns["flip"](5 + dr, 5 + dc, True)
        st.quiet = 0
        first = len(cls.ticks)
        st.running = True
        game.until(lambda: len(cls.ticks) - first >= 46, 12)
        cls.still = cls.ticks[first:]

    # -- the claims ---------------------------------------------------------
    def test_it_plays_without_a_warning(self):
        self.assertEqual(self.warned, [])
        self.assertIsNone(self.author_error)

    def test_the_grid_builds_itself_then_the_game_runs(self):
        self.assertGreater(self.ready_at, 4, "the grid is in place at once")
        self.assertGreater(self.running_at, self.ready_at)
        self.assertGreater(self.soup, 100, "vacuous: no soup")
        self.assertGreater(self.soup_ticks, 15, "the game does not run")

    def check_layout(self, lay: dict, cols: int) -> None:
        self.assertEqual(lay["COLS"], cols)
        cell, rows, left, bottom = lay["CELL"], lay["ROWS"], lay["LEFT"], lay["BOTTOM"]
        self.assertAlmostEqual(cols * cell, 1120, places=9)
        self.assertLessEqual(rows * cell, 672 + EPS)
        self.assertGreater((rows + 1) * cell, 672, "a row of the board is left empty")
        self.assertAlmostEqual(bottom - 64, (64 + 672) - (bottom + rows * cell), places=9,
                               msg="the board is not centred up and down")
        self.assertAlmostEqual(lay["SIZE"], 0.8 * cell, places=9)
        self.assertEqual(lay["cells"], [rows, cols])
        right, top = left + cols * cell, bottom + rows * cell
        self.assertEqual(len(lay["rows"]), rows + 1)
        self.assertEqual(len(lay["columns"]), cols + 1)
        for i, (p1, p2) in enumerate(lay["rows"]):
            y = bottom + i * cell
            for got, want in ((p1, (left, y)), (p2, (right, y))):
                self.assertLess(max(abs(got[0] - want[0]), abs(got[1] - want[1])), EPS,
                                f"row line {i} ends at {got}, not {want}")
        for i, (p1, p2) in enumerate(lay["columns"]):
            x = left + i * cell
            for got, want in ((p1, (x, bottom)), (p2, (x, top))):
                self.assertLess(max(abs(got[0] - want[0]), abs(got[1] - want[1])), EPS,
                                f"column line {i} ends at {got}, not {want}")
        for r, c, x, y in lay["centres"]:         # square cells, each in its square of the grid
            self.assertAlmostEqual(x, left + (c + 0.5) * cell, places=9)
            self.assertAlmostEqual(y, bottom + (r + 0.5) * cell, places=9)

    def test_the_grid_lines_end_exactly_on_the_grid(self):
        self.check_layout(self.grid, 60)

    def test_the_board_follows_cols_alone(self):
        self.check_layout(self.other, OTHER_COLS)
        self.assertNotEqual(self.other["ROWS"], self.grid["ROWS"])
        self.assertGreater(self.other_ran, 3, "the game does not run on the other board")

    def test_every_tick_is_conway_on_a_torus(self):
        self.assertGreater(len(self.ticks), 100)
        wrong, seeds = [], 0
        for n, before, after, quiet in self.ticks:
            want = conway(before, self.rows, self.cols)
            if after == want:
                continue
            if quiet == 0 and is_seed(want, after, self.rows, self.cols):
                seeds += 1          # a quiet board's seed, laid after the rules
                continue
            wrong.append(f"tick {n}: {len(after ^ want)} cells differ")
        self.assertEqual(wrong[:5], [])
        self.assertEqual(seeds, 1, "vacuous or loose: the seed check let more than the quiet seed through")

    def test_a_glider_comes_back_on_the_other_side(self):
        glider, blinker, boards = self.glider
        self.assertEqual(len(boards), 36)
        for m in range(1, 10):
            moved = frozenset(((r + m) % self.rows, (c + m) % self.cols) for r, c in glider)
            self.assertEqual(boards[4 * m - 1], moved | blinker, f"after {4 * m} ticks")
        wrapped = {p for b in boards for p in b if p[1] < 3} and {p for b in boards for p in b if p[0] < 3}
        self.assertTrue(wrapped, "vacuous: the glider never crossed an edge")
        self.assertNotEqual(boards[0], boards[1], "the blinker does not blink")

    def test_a_newborn_grows_over_grow_ticks(self):
        from math import isclose
        size, born, grow, period = self.size, self.born, self.grow, self.period
        self.assertEqual(size, self.grid["SIZE"])
        self.assertGreater(grow, 1)
        self.assertLess(born, 0.9)
        t0, length0, visible0, alive0 = self.growth[0]
        self.assertTrue(visible0 and alive0, "the click did not bring the cell to life")
        self.assertLess(abs(length0 - born * size), 0.05 * size, "the newborn does not start at BORN")
        lengths = [g[1] for g in self.growth]
        self.assertEqual(lengths, sorted(lengths), "the newborn shrinks while it grows")
        grown = next(t for t, length, *_ in self.growth if isclose(length, size, abs_tol=1e-9))
        self.assertGreater(grown, grow * period - 2 / SECOND, "the newborn is full size before GROW ticks")
        self.assertLess(grown, grow * period + 3 / SECOND)
        one_tick = [length for t, length, *_ in self.growth if t <= period]
        self.assertLess(max(one_tick), 0.9 * size, "the newborn is (nearly) full size at once")
        self.assertEqual(self.growth[-1][1], size)

    def test_a_dead_cell_shrinks_and_ends_hidden(self):
        self.assertEqual(self.cleared, (0, 0), "a cleared board keeps visible cells")
        self.assertFalse(self.dying[0][3], "a second click did not flip the cell back")
        self.assertTrue(self.dying[0][2], "the cell vanished at once instead of shrinking")
        lengths = [d[1] for d in self.dying if d[2]]
        self.assertEqual(lengths, sorted(lengths, reverse=True))
        t, length, visible, alive = self.dying[-1]
        self.assertFalse(visible)
        self.assertEqual(length, 0)

    def test_a_drag_paints_what_the_first_cell_became(self):
        self.assertEqual(self.painted, list(range(10, 16)))
        # pressed on a live cell (12): it and the live cells after it die, the
        # dead ones it crosses (16, 17) stay dead, the ones before it live on
        self.assertEqual(self.erased, [10, 11])

    def test_a_still_board_gets_a_seed(self):
        self.assertEqual(self.seed_shape, R_PENTOMINO)
        quiet = [q for _, _, _, q in self.still]
        self.assertIn(40, quiet, "vacuous: the board was never quiet for 40 ticks")
        i = quiet.index(40) + 1
        self.assertEqual(quiet[i], 0, "the quiet count went on past 40")
        n, before, after, _ = self.still[i]
        self.assertEqual(before, conway(before, self.rows, self.cols), "vacuous: the board was not still")
        self.assertEqual(len(after - before), 5, "no R-pentomino fell")
        self.assertTrue(is_seed(before, after, self.rows, self.cols), "what fell is not an R-pentomino")
        # nothing fell before: the block stood alone for 40 ticks
        self.assertEqual({len(b) for _, b, a, q in self.still[1:i]}, {4})


if __name__ == "__main__":
    unittest.main()
