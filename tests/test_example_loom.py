"""
The claims of ``examples/loom.py``, played headless.

The example says: a Jacquard loom weaves its punched cards row by row, from
the card's bottom row up; where a row has a hole the thread is lifted and
the weft passes under it (the dark ground), where it has none the weft
floats over it (the bright picture), and the card repeats twice across the
cloth; each new row is beaten in right above the last one; when a card has
been woven twice the camera steps back to show the tapestry and the next
card goes in (Diamond, Chevron, Star, then Diamond again); clicking a hole
of the card punches or fills it and the cloth changes from the next row on;
UP / DOWN make it faster / slower (between 0.25x and 2x); N finishes the
card now; the cloth keeps ``KEEP`` rows (a ``History``) and the oldest one
winds onto the beam.

Bug class guarded: **an example that stops doing what its docstring says**
after an engine change (``History(max_points=, on_leave=)`` with a death
verb, scrolling layers, links on ``Track`` ``begin`` / ``end``, ``unlink``)
while it still builds and runs, **a cloth that leaks** (a row that winds
onto the beam must go with its floats: the live objects stay bounded over
two loops of the three cards), and **a card that warns**: every card is
woven twice over and must not raise a single Scena warning.

Not covered: drawing (a CPU raster frame costs seconds headless).

Run:

    python tests/run_tiers.py focused test_example_loom
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402
from hypothesis_support import registry  # noqa: E402

PATH = "examples/loom.py"
SECOND = 60
ROW_TIME = 0.4 + 0.85 + 0.18 + 0.2     # read, fly, beat, pause: one row at 1x


def tap(run, key):
    run.key_down(key)
    run.step(1)
    run.key_up(key)
    run.step(1)


def spy_rows(ns):
    """Record every row the loom weaves: (frame, card name, pick, row)."""
    rows = []
    weave_row = ns["weave_row"]

    def spy(y, chosen, pick):
        row = weave_row(y, chosen, pick)
        rows.append((chosen[0], pick, row))
        return row

    ns["weave_row"] = spy
    return rows


def floating(ns, row) -> list:
    """The warp threads (0 … WARPS-1) the weft floats over in this row."""
    left, gap = ns["LEFT"], ns["GAP"]
    over = []
    for i in range(ns["WARPS"]):
        x = left + i * gap
        if any(t.p1.x <= x <= t.p2.x for t in row.floats):
            over.append(i)
    return over


def expected_floats(ns, pattern: str) -> list:
    lifted = pattern * ns["REPEAT"]
    return [i for i, c in enumerate(lifted) if c != "X"]


class TestLoomWeaving(unittest.TestCase):
    def test_three_cards_are_woven_and_the_cloth_stays_bounded(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with ProgramRun(PATH, seed=1) as run:
                ns = run.ns
                st, cloth, keep = ns["st"], ns["cloth"], ns["KEEP"]
                rows = spy_rows(ns)
                cards = [st.card_name]
                live = []
                at_card = []        # 1 s into each card
                revealed = 0.0
                for _ in range(300 * SECOND):
                    run.step(1)
                    self.assertLessEqual(len(cloth), keep)
                    if st.card_name != cards[-1]:
                        cards.append(st.card_name)
                        run.step(SECOND)
                        at_card.append(len(registry().live))
                    if run.frames % SECOND == 0:
                        live.append(len(registry().live))
                    if ns["bloom"].enabled:
                        revealed = max(revealed, 1 - ns["canvas"].zoom)
                    if len(cards) == 7:
                        break
                self.assertEqual(cards, ["Diamond", "Chevron", "Star"] * 2 + ["Diamond"])
                # each card is woven twice, bottom row up
                for name in ("Diamond", "Chevron", "Star"):
                    picks = [p for n, p, _ in rows if n == name][:24]
                    self.assertEqual(picks, [11 - k % 12 for k in range(24)], name)
                # the camera stepped back to show the tapestry
                self.assertGreater(revealed, 0.1)
                # rows that wound onto the beam are gone, floats and all
                woven = [r for _, _, r in rows]
                gone = woven[:-keep - 2]
                self.assertTrue(gone, "vacuous: no row left the cloth")
                for row in gone:
                    self.assertFalse(row.is_alive, "a row that left the cloth stays")
                    self.assertTrue(all(not t.is_alive for t in row.floats))
                # the live objects plateau: what one card adds, the next one does not
                first, last = live[20:60], live[-40:]
                self.assertLess(max(last), max(first) * 1.15, (max(first), max(last)))
                # and the same point of the same card, one loop later: nothing
                # piled up (a death verb only hides a shape). Cards differ
                # (a card with more floats has more objects), loops must not.
                for a, b in zip(at_card[:3], at_card[3:]):
                    self.assertLessEqual(b, a, at_card)
        self.assertEqual([str(w.message) for w in caught], [], "a card raised a Scena warning")

    def test_floats_follow_the_card_and_rows_stack_up(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            rows = spy_rows(ns)
            run.step(int(6 * ROW_TIME * SECOND))
            done = [r for r in rows if r[2].is_alive][:-1]     # the last may still be flying
            self.assertGreaterEqual(len(done), 4)
            pattern = ns["CARDS"][0][4]
            for name, pick, row in done:
                self.assertEqual(floating(ns, row), expected_floats(ns, pattern[pick]), pick)
            # each row is beaten in right above the last one
            ys = [float(r.center.y) for _, _, r in done]
            for a, b in zip(ys, ys[1:]):
                self.assertAlmostEqual(b - a, ns["ROW"], delta=1e-6)
            self.assertAlmostEqual(float(done[-1][2].center.y), st.top - ns["ROW"] * (st.picks - len(done)),
                                   delta=1e-6)

    def test_the_weft_is_laid_behind_the_shuttle(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            rows = spy_rows(ns)
            progress = ns["progress"]
            seen = 0
            for _ in range(int(3 * ROW_TIME * SECOND)):
                run.step(1)
                if not rows:
                    continue
                row = rows[-1][2]
                p = progress()
                if 0.05 < p < 0.95:
                    if len(rows) % 2:        # odd rows fly right: the end follows
                        if abs(row.end - p) < 1e-9:
                            seen += 1
                    elif abs(row.begin - p) < 1e-9:
                        seen += 1
            self.assertGreater(seen, 40, "the weft does not follow the shuttle")


class TestLoomControls(unittest.TestCase):
    def test_a_click_on_the_card_changes_the_cloth_from_the_next_row_on(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            rows = spy_rows(ns)
            hole_place, holes = ns["hole_place"], ns["holes"]
            # the first row is in at ~2 s; row 10 is thrown at ~2.6 s: click
            # while the shuttle flies it
            run.step(175)
            self.assertEqual(st.pick, 10)
            self.assertEqual([p for _, p, _ in rows], [11, 10], "not mid-flight on row 10")
            card = ns["CARDS"][0][4]
            woven_before = {p: floating(ns, r) for _, p, r in rows}
            original_10, original_8 = card[10], card[8]
            # punch and fill on the row being woven (10) and on a row ahead (8)
            flips = [(10, 5), (8, 0), (8, 7)]
            new = {pick: card[pick] for pick, _ in flips}
            for pick, column in flips:
                old = card[pick][column]
                x, y = hole_place(pick, column)
                run.press(x, y)
                run.step(1)
                run.release()
                run.step(1)
                letter = "." if old == "X" else "X"
                self.assertEqual(card[pick][column], letter, (pick, column))
                self.assertEqual(holes[pick][column].visible, letter == "X")
                new[pick] = card[pick]
            # the row on the loom stays as it was read; the next ones follow the card
            run.step(int(5 * ROW_TIME * SECOND))
            woven = {p: r for _, p, r in rows}
            self.assertIn(8, woven, "vacuous: row 8 not woven yet")
            self.assertEqual(floating(ns, woven[8]), expected_floats(ns, new[8]))
            self.assertNotEqual(expected_floats(ns, new[8]), expected_floats(ns, original_8))
            self.assertEqual(floating(ns, woven[11]), woven_before[11], "a row already woven changed")
            self.assertEqual(floating(ns, woven[10]), expected_floats(ns, original_10),
                             "the row on the loom changed")
            self.assertEqual(floating(ns, woven[10]), woven_before[10])
            # a click off the card does nothing
            snapshot = list(card)
            run.press(200, 700)
            run.step(1)
            run.release()
            run.step(1)
            self.assertEqual(list(card), snapshot)

    def test_up_and_down_change_the_speed_within_its_range(self):
        with ProgramRun(PATH, seed=1) as run:
            st = run.ns["st"]
            speeds = []
            for key in ("UP", "UP", "DOWN", "DOWN", "DOWN", "DOWN", "DOWN"):
                tap(run, key)
                speeds.append(st.speed)
            self.assertEqual(speeds, [2, 2, 1, 0.5, 0.25, 0.25, 0.25])

    def test_faster_weaves_more_rows(self):
        counts = {}
        for key in (None, "UP", "DOWN"):
            with ProgramRun(PATH, seed=1) as run:
                st = run.ns["st"]
                if key:
                    tap(run, key)
                start = st.picks
                run.step(10 * SECOND)
                counts[key] = st.picks - start
        self.assertAlmostEqual(counts[None], 10 / ROW_TIME, delta=1.5)
        self.assertGreaterEqual(counts["UP"], 2 * counts[None] - 1)
        self.assertLessEqual(counts["DOWN"], counts[None] / 2 + 1)

    def test_n_finishes_the_card_now(self):
        with ProgramRun(PATH, seed=1) as run:
            ns = run.ns
            st = ns["st"]
            run.step(int(2.5 * ROW_TIME * SECOND))
            picks = st.picks
            tap(run, "N")
            self.assertTrue(st.finish)
            run.step(int(1.5 * ROW_TIME * SECOND))
            self.assertLessEqual(st.picks, picks + 1, "N did not stop the card")
            self.assertTrue(ns["bloom"].enabled, "the tapestry was not shown")
            run.step(10 * SECOND)
            self.assertEqual((st.card, st.card_name, st.finish), (1, "Chevron", False))
            self.assertLessEqual(st.picks, 2)
            pattern = ns["CARDS"][1][4]
            for pick in range(12):
                for column in range(12):
                    self.assertEqual(ns["holes"][pick][column].visible, pattern[pick][column] == "X")
            self.assertFalse(ns["bloom"].enabled)
            self.assertEqual(ns["canvas"].zoom, 1)


if __name__ == "__main__":
    unittest.main()
