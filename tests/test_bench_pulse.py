"""Bench pulse auto-diff: framebuffer guard (scripts/bench/pulse.py, run_balanced.py, run_games.py).

Regression for 2026-09-28: a ``balanced-2`` run whose window opened on another
display rendered the GPU cells at FB 1200×800 (1×) instead of 2400×1600
(Retina 2×). Auto-diff compared them to the 2× row anyway and reported
"gpu −25% … candidate real move" — a different workload, not a code change
(heroes looked like +31% for the same reason). The log's ``§`` = 1× marker was
a hand convention the runner neither wrote nor read.

Now the runner stamps the scale on GPU summary cells and compares each GPU
cell with the newest row measured at the same scale (or says it could not).

    python -m unittest tests.test_bench_pulse -v
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "scripts", "bench")
if BENCH not in sys.path:
    sys.path.insert(0, BENCH)

import pulse  # noqa: E402
import run_balanced as rb  # noqa: E402

HOST = {"cpu": "Apple M4", "os": "Darwin 26.6.2", "python": "3.12.13"}
HEADER = (
    "## Summary\n\n"
    "| Date | Protocol | Host | cpu | gpu | heroes | live | soak | Notes |\n"
    "|---|---|---|---:|---:|---:|---:|---:|---|\n"
)


def _row(date, cpu, gpu, heroes, *, gpu_tag="2×", heroes_tag=None, live=8.0, rss=170.0):
    heroes_tag = gpu_tag if heroes_tag is None else heroes_tag
    return (
        f"| {date} | balanced-2 | Apple M4 · Darwin 26.6.2 · Py 3.12.13 | "
        f"{cpu:.3f} (200.0) `t1.2 c1.6 d0.9` | "
        f"{gpu:.3f} (120.0){pulse.fb_cell_suffix(gpu_tag)} | "
        f"{heroes:.3f} (160.0){pulse.fb_cell_suffix(heroes_tag)} | "
        f"{live:.3f} (125.0) `t2.4 c3.1 d1.0` | {rss:.1f} MiB / 0.7 ms / Δobj 0 |  |\n"
    )


def _log(*rows):
    """Newest-first summary table, like the real log."""
    return HEADER + "".join(rows) + "\n## Runs\n"


def _probe(work, fb=None, design=1200):
    p = {"work_ms": work, "fps": 1000.0 / work, "tick_ms": 1.0, "coll_ms": 1.0, "draw_ms": 1.0}
    if fb is not None:
        p.update(fb_width=fb, fb_height=fb * 2 // 3, design_w=design, design_h=800)
    return p


def _bundle(cpu, gpu, heroes, fb):
    return {
        "date": "2026-09-29", "protocol": "balanced-2", "host": HOST, "notes": "",
        "scena_fingerprint": "new",
        "probes": {
            "cpu_mix": _probe(cpu), "gpu_mix": _probe(gpu, fb), "gpu_heroes": _probe(heroes, fb),
            "live_mix": _probe(8.0),
            "soak": {"last_rss_mb": 170.0, "last_idle_work_ms": 0.7, "delta_objects": 0},
        },
    }


class TestFbTags(unittest.TestCase):
    def test_scale_tag(self):
        self.assertEqual(pulse.fb_scale_tag(2400, 1200), "2×")
        self.assertEqual(pulse.fb_scale_tag(1200, 1200), "1×")
        self.assertEqual(pulse.fb_scale_tag(1800, 1200), "1.5×")
        for fb, design in ((0, 1200), (None, 1200), (2400, None), ("x", 1200)):
            with self.subTest(fb=fb, design=design):
                self.assertIsNone(pulse.fb_scale_tag(fb, design))

    def test_cell_round_trip(self):
        for tag in ("2×", "1×", "1.5×", "3×"):
            with self.subTest(tag=tag):
                cell = "6.628 (150.9)" + pulse.fb_cell_suffix(tag)
                self.assertEqual(pulse.cell_fb_tag(cell), tag)

    def test_default_and_unknown_leave_cell_unmarked(self):
        self.assertEqual(pulse.fb_cell_suffix("2×"), "")
        self.assertEqual(pulse.fb_cell_suffix(None), "")
        self.assertEqual(pulse.cell_fb_tag("8.846 (113.0)"), "2×")

    def test_hand_marked_rows_still_read(self):
        # Older rows were marked by hand as "6.224 (160.7) §".
        self.assertEqual(pulse.cell_fb_tag("6.224 (160.7) §"), "1×")


class TestSummaryRowStampsScale(unittest.TestCase):
    def test_one_x_cells_marked_and_parse_back(self):
        for fb, want in ((1200, "1×"), (2400, "2×")):
            with self.subTest(fb=fb):
                line = rb._summary_row_line(_bundle(4.5, 6.6, 7.6, fb))
                cells = pulse.parse_summary_table(_log(line))[0]
                self.assertEqual(pulse.cell_fb_tag(cells[4]), want)
                self.assertEqual(pulse.cell_fb_tag(cells[5]), want)
                self.assertAlmostEqual(pulse.parse_leading_float(cells[4]), 6.6)
                # cpu / live cells are never stamped.
                self.assertNotIn("§", cells[3] + cells[6])

    def test_run_section_reuses_the_summary_row(self):
        # One row builder: the run section embeds the same (stamped) line.
        b = _bundle(4.5, 6.6, 7.6, 1200)
        b.update(scripts={}, when="now", pro_forma="comparable", git="none",
                 repeats=3, fingerprint="scripts")
        md = rb.render_markdown(b)
        self.assertIn(rb._summary_row_line(b), md)
        self.assertIn("FB 1200×800", md.split("heroes_mass", 1)[1])


class TestPrevRowAtSameScale(unittest.TestCase):
    LOG = _log(
        _row("2026-09-28", 4.48, 6.63, 7.64, gpu_tag="1×"),   # newest: other display
        _row("2026-09-27", 5.53, 8.85, 7.15, gpu_tag="2×"),
        _row("2026-08-28", 3.79, 6.22, 8.02, gpu_tag="1×"),
    )

    def test_two_x_run_skips_the_one_x_row(self):
        prev, labels, notes = rb._prev_balanced_metrics(
            self.LOG, {"gpu_work_ms": "2×", "heroes_work_ms": "2×"})
        self.assertEqual(prev["cpu_work_ms"], 4.48)          # cpu: newest row
        self.assertEqual(prev["gpu_work_ms"], 8.85)          # gpu: last 2× row
        self.assertEqual(prev["heroes_work_ms"], 7.15)
        self.assertIn("2026-09-27", labels["gpu_work_ms"])
        self.assertTrue(any("compared with the 2026-09-27 row" in n for n in notes))

    def test_same_scale_as_newest_uses_newest_silently(self):
        prev, labels, notes = rb._prev_balanced_metrics(
            self.LOG, {"gpu_work_ms": "1×", "heroes_work_ms": "1×"})
        self.assertEqual(prev["gpu_work_ms"], 6.63)
        self.assertEqual((labels, notes), ({}, []))

    def test_no_row_at_that_scale_is_not_compared(self):
        prev, labels, notes = rb._prev_balanced_metrics(
            self.LOG, {"gpu_work_ms": "1.5×", "heroes_work_ms": "1.5×"})
        self.assertNotIn("gpu_work_ms", prev)
        self.assertNotIn("heroes_work_ms", prev)
        self.assertEqual(prev["cpu_work_ms"], 4.48)
        self.assertEqual(sum("not compared" in n for n in notes), 2)

    def test_unknown_scale_falls_back_to_newest(self):
        prev, labels, notes = rb._prev_balanced_metrics(self.LOG, {})
        self.assertEqual(prev["gpu_work_ms"], 6.63)
        self.assertEqual((labels, notes), ({}, []))

    def test_other_protocols_ignored(self):
        log = self.LOG.replace("| 2026-09-28 | balanced-2 |", "| 2026-09-28 | balanced-1 |")
        prev, _l, _n = rb._prev_balanced_metrics(log, {"gpu_work_ms": "2×"})
        self.assertEqual(prev["cpu_work_ms"], 5.53)


class TestScaleSurvivesAggregation(unittest.TestCase):
    """The runner's real path: raw repeat JSON → ``summarize_probe`` → tag.

    First version of the guard dropped ``design_w`` here (only ``fb_width``
    was kept), so every live run tagged "unknown" and fell back to the newest
    row — the unit tests above built bundles by hand and missed it.
    """

    @staticmethod
    def _raw(fb, work=6.2):
        # Shape of gpu_mix.py's RESULT JSON (the fields the runner reads).
        return {"work_ms": work, "fps": 1000 / work, "draw_ms": 2.4, "fb_width": fb,
                "fb_height": fb * 2 // 3, "design_w": 1200, "design_h": 800}

    def test_uniform_repeats(self):
        for fb, want in ((2400, "2×"), (1200, "1×")):
            with self.subTest(fb=fb):
                probe = rb.summarize_probe([self._raw(fb) for _ in range(3)])
                self.assertEqual(rb._probe_fb_tag(probe), want)

    def test_repeats_on_different_displays_are_mixed(self):
        probe = rb.summarize_probe([self._raw(2400), self._raw(1200), self._raw(2400)])
        self.assertEqual(rb._probe_fb_tag(probe), "mixed")
        cell = "6.2 (161.3)" + pulse.fb_cell_suffix("mixed")
        self.assertEqual(pulse.cell_fb_tag(cell), "mixed")
        prev, _labels, notes = rb._prev_balanced_metrics(
            _log(_row("2026-09-28", 4.5, 6.6, 7.6)), {"gpu_work_ms": "mixed"})
        self.assertNotIn("gpu_work_ms", prev)
        self.assertTrue(any("not compared" in n for n in notes))


class TestDashboardHeadline(unittest.TestCase):
    def test_gpu_headline_says_when_the_newest_row_is_not_2x(self):
        import dashboard
        for tag, noted in (("1×", True), ("2×", False)):
            with self.subTest(tag=tag):
                log = _log(_row("2026-09-28", 4.5, 6.63, 7.6, gpu_tag=tag))
                head = dashboard.BalancedPulse().parse(log)["headline"]
                self.assertIn("gpu 6.63 ms", head)
                self.assertEqual("FB 1×" in head, noted)


class TestAutodiffEndToEnd(unittest.TestCase):
    """The 2026-09-28 case through ``_autodiff_balanced`` (reads LOG_PATH, prints)."""

    def _run(self, log_text, bundle):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "balanced.md"
            path.write_text(log_text, encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(rb, "LOG_PATH", path), \
                    mock.patch.object(rb, "latest_scena_fingerprint", lambda _t: "old"), \
                    contextlib.redirect_stdout(out):
                rb._autodiff_balanced(bundle)
            return out.getvalue()

    def test_fb_change_is_not_reported_as_a_move(self):
        log = _log(_row("2026-09-28", 5.53, 8.85, 7.15, gpu_tag="2×"))
        out = self._run(log, _bundle(5.5, 6.63, 5.0, fb=1200))  # −25% / −30% at 1×
        self.assertNotIn("gpu_work_ms: 8.850", out)
        self.assertNotIn("heroes_work_ms: 7.150", out)
        self.assertIn("not compared", out)

    def test_same_fb_move_is_still_reported(self):
        log = _log(_row("2026-09-28", 5.53, 8.85, 7.15, gpu_tag="2×"))
        out = self._run(log, _bundle(5.5, 6.63, 7.1, fb=2400))
        self.assertIn("gpu_work_ms: 8.850 → 6.630", out)
        self.assertIn("candidate real move", out)

    def test_older_same_fb_row_does_not_claim_same_fingerprint(self):
        log = _log(
            _row("2026-09-28", 5.5, 6.6, 7.6, gpu_tag="1×"),
            _row("2026-09-27", 5.5, 8.85, 7.15, gpu_tag="2×"),
        )
        with mock.patch.object(rb, "latest_scena_fingerprint", lambda _t: "new"):
            out = io.StringIO()
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "balanced.md"
                path.write_text(log, encoding="utf-8")
                with mock.patch.object(rb, "LOG_PATH", path), contextlib.redirect_stdout(out):
                    rb._autodiff_balanced(_bundle(5.5, 6.63, 7.1, fb=2400))
        text = out.getvalue()
        line = next(l for l in text.splitlines() if "gpu_work_ms:" in l and "→" in l)
        self.assertIn("2026-09-27", line)
        self.assertNotIn("environment noise", line)


import run_games as rg  # noqa: E402


def _game_rep(work, *, fb_w=2006, win_w=1003, mx=None, rss_end=270.0, load=2.0):
    """Shape of game_bench.py's RESULT_JSON (the fields run_games reads)."""
    return {
        "fb": [fb_w, fb_w * 3 // 4, win_w, win_w * 3 // 4],
        "rss_mb": [250.0, rss_end],
        "load": [load, load, load],
        "sides": {"all": {
            "work_ms": work, "work_p95": work * 1.2, "work_p99": work * 1.3,
            "work_max": work * 2 if mx is None else mx, "x4_ms": 4 * work, "fps": 1000 / work,
            "phases": {"simulate": work * 0.6, "draw_frame": work * 0.3},
        }},
    }


def _games(scale=2, festa=45.0, ninja=2.5, rss=275.0):
    fb_w = 1003 * scale
    out = {}
    for gid, _script, _params in rg.GAMES:
        work = {"ninja": ninja, "festa": festa}.get(gid, 10.0)
        reps = [_game_rep(work * f, fb_w=fb_w, mx=24.0 if gid == "corrida" else None,
                          rss_end=rss) for f in (0.9, 1.0, 1.2)]
        out[gid] = rg.summarize_game(reps)
    return out


def _games_log(*rows):
    return (
        "## Summary\n\n"
        "| Date | Protocol | Host | Load | FB | " + " | ".join(k for k, _g, _f in rg.CELLS)
        + " | Notes |\n|" + "---|" * (6 + len(rg.CELLS)) + "\n" + "".join(r + "\n" for r in rows)
        + "\nRetired:\n\n| Date | Protocol | Host | Load | ninja | Notes |\n|---|---|---|---|---|---|\n"
        "| 2026-10-12 | `games-1` | h | 4.1 | 2.83 |  |\n\n## Runs\n"
    )


def _games_row(date, games):
    meta = {"date": date, "host": HOST}
    return rg.summary_row(games, meta, "")


class TestGamesPulse(unittest.TestCase):
    """``games-2`` (run_games.py): median of interleaved repeats, a framebuffer
    stamp per row, festa compared only at the same scale.

    Regression for 2026-10-13: ``games-1`` logged festa at 36.2 ms (FB 1×);
    the next run opened at FB 2× (4K display) and read ~45 ms, submit 19.6 →
    26.3 ms. The row did not say the scale, so the auto-diff would have
    reported a +25 % festa move for a display change.
    """

    def test_median_of_repeats_and_framebuffer(self):
        g = rg.summarize_game([_game_rep(w) for w in (12.0, 10.0, 30.0)])
        self.assertEqual(g["work_ms"], 12.0)            # median, not mean (17.3)
        self.assertEqual(g["works"], [12.0, 10.0, 30.0])
        self.assertEqual(g["fb_tag"], "2006x1504")

    def test_tag_is_the_framebuffer_not_fb_over_design(self):
        # First games-2 run, one 4K display: the window is fitted to the
        # display, so fb / design width read 2.006, 2.236 and 2.506 for games
        # that all ran at the same backing scale. The pixel count is the workload.
        a = _game_rep(5.0, fb_w=2006, win_w=1000)
        b = _game_rep(5.0, fb_w=2506, win_w=1000)
        self.assertEqual(rg.run_fb_tag(a), "2006x1504")
        self.assertNotEqual(rg.run_fb_tag(a), rg.run_fb_tag(b))

    def test_repeats_on_different_displays_are_mixed(self):
        g = rg.summarize_game([_game_rep(5.0), _game_rep(5.0, fb_w=1003)])
        self.assertEqual(g["fb_tag"], "mixed")
        games = _games()
        games["festa"] = g
        self.assertEqual(rg.row_fb_tag(games), "mixed")

    def test_fb_column_follows_festa_only(self):
        games = _games(scale=2)
        games["ninja"] = rg.summarize_game([_game_rep(2.5, fb_w=2506, win_w=1000)])
        self.assertEqual(rg.row_fb_tag(games), "2006x1504")

    def test_row_round_trips_every_cell(self):
        games = _games()
        prev, labels, notes = rg.prev_metrics(_games_log(_games_row("2026-10-13", games)), "2006x1504")
        want = rg.metrics(games)
        self.assertEqual(set(prev), set(want))
        for k, v in want.items():
            self.assertAlmostEqual(prev[k], v, delta=0.51 if k.endswith("_mb") else 0.006, msg=k)
        self.assertEqual(prev["corrida_max_ms"], 24.0)
        self.assertEqual((labels, notes), ({}, []))

    def test_festa_skips_a_row_at_another_scale(self):
        log = _games_log(_games_row("2026-10-14", _games(scale=1, festa=36.0)),
                         _games_row("2026-10-13", _games(scale=2, festa=45.0, ninja=2.6)))
        prev, labels, notes = rg.prev_metrics(log, "2006x1504")
        self.assertAlmostEqual(prev["ninja_work_ms"], 2.5)     # CPU cells: newest row
        self.assertAlmostEqual(prev["festa_work_ms"], 45.0)    # festa: last 2× row
        self.assertIn("2026-10-13", labels["festa_work_ms"])
        self.assertTrue(any("compared with the 2026-10-13 row" in n for n in notes))

    def test_no_row_at_that_scale_is_not_compared(self):
        log = _games_log(_games_row("2026-10-13", _games(scale=1)))
        for tag in ("2006x1504", "mixed"):
            with self.subTest(tag=tag):
                prev, _labels, notes = rg.prev_metrics(log, tag)
                self.assertNotIn("festa_work_ms", prev)
                self.assertNotIn("festa_rss_mb", prev)
                self.assertIn("ninja_work_ms", prev)
                self.assertEqual(sum("not compared" in n for n in notes), 2)

    def test_retired_protocol_rows_are_not_read(self):
        self.assertEqual(rg.prev_metrics(_games_log(), "2006x1504"), (None, {}, []))

    def _autodiff(self, log, games):
        out = io.StringIO()
        with mock.patch.object(rg, "latest_scena_fingerprint", lambda _t: "old"), \
                contextlib.redirect_stdout(out):
            rg.report_autodiff(games, log, "new")
        return out.getvalue()

    def test_fb_change_is_not_reported_as_a_move(self):
        log = _games_log(_games_row("2026-10-12", _games(scale=1, festa=36.2)))
        out = self._autodiff(log, _games(scale=2, festa=45.0))
        self.assertNotIn("festa_work_ms: 36", out)
        self.assertIn("not compared", out)

    def test_same_fb_move_is_still_reported(self):
        log = _games_log(_games_row("2026-10-12", _games(scale=2, festa=36.2, rss=270.0)))
        out = self._autodiff(log, _games(scale=2, festa=45.0, ninja=3.5, rss=700.0))
        self.assertIn("festa_work_ms: 36.200 → 45.000", out)
        self.assertIn("ninja_work_ms: 2.500 → 3.500", out)
        self.assertIn("festa_rss_mb", out)

    def test_dashboard_reads_the_new_row(self):
        import dashboard
        log = _games_log(_games_row("2026-10-13", _games(scale=1)))
        got = dashboard.GamesPulse().parse(log)
        self.assertEqual(got["protocol"], "games-2")
        self.assertIn("ninja 2.5", got["headline"])
        self.assertIn("corrida max 24.0", got["headline"])
        self.assertIn("festa FB 1003x752", got["headline"])
        self.assertEqual(got["last5"], [2.5])


class TestFingerprintRowLabel(unittest.TestCase):
    """Run logs written before 0.6.0 label the fingerprint row "Stage" (the
    framework's old name); new ones say "Scena". Both read back."""

    def _log(self, label):
        return ("# x\n\n## Runs\n\n### 2026-10-06 run\n\n| Key | Value |\n| --- | --- |\n"
                f"| {label} | `0123456789ab` |\n")

    def test_new_and_old_labels(self):
        for label in ("Scena", "Stage"):
            self.assertEqual(rb.latest_scena_fingerprint(self._log(label)), "0123456789ab", label)


if __name__ == "__main__":
    unittest.main()
