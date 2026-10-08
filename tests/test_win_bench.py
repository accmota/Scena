"""Windows jitter helpers (scripts/bench/win/): the platform-independent parts.

The Windows calls (DWM, D3DKMT, QPC) only run on the Windows machine
(procedure: scripts/bench/longrun.md). Here:

* vblank reconstruction from sparse (refresh counter, QPC) samples
* interval / residual / offset stats
* ``WinVsyncClock`` keeps ``frame_probe.VsyncClock``'s surface (the wrapper
  swaps one for the other; a contract drift would silently blank the report)
* the wrapper's patch targets still exist and are looked up the way it patches
* argv split and summary table

    python -m unittest tests.test_win_bench -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "scripts", "bench")
WIN = os.path.join(BENCH, "win")
for _p in (WIN, BENCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frame_probe  # noqa: E402
import win_jitter_probe  # noqa: E402
import win_summary  # noqa: E402
import win_vsync  # noqa: E402

FREQ = 10_000_000
PERIOD = FREQ / 59.94


def _timeline(n=600, c0=1000, q0=10**9):
    return [(c0 + i, int(q0 + i * PERIOD)) for i in range(n)]


class TestReconstruct(unittest.TestCase):
    def test_sparse_samples_recover_every_vblank(self):
        true = _timeline()
        sparse = [s for i, s in enumerate(true) if i % 3 == 0 or i == len(true) - 1]
        rec = win_vsync.reconstruct(sparse, PERIOD)
        self.assertEqual(len(rec["ticks"]), len(true))
        self.assertEqual(rec["bad_gaps"], 0)
        self.assertEqual(rec["max_gap"], 3)
        self.assertEqual(rec["exact"] + rec["interpolated"], len(true))
        worst = max(abs(a - q) for a, (_, q) in zip(rec["ticks"], true))
        self.assertLessEqual(worst, 1.0)

    def test_unsorted_and_duplicate_samples(self):
        true = _timeline(50)
        messy = list(reversed(true[::5])) + true[::5] + [true[-1]]
        rec = win_vsync.reconstruct(messy, PERIOD)
        self.assertEqual(len(rec["ticks"]), len(true))
        self.assertEqual(rec["ticks"], sorted(rec["ticks"]))

    def test_irregular_gap_is_not_interpolated(self):
        sparse = _timeline()[::3]
        c, q = sparse[10]
        sparse[10] = (c, q + int(5 * PERIOD))  # mode change / counter jump
        rec = win_vsync.reconstruct(sparse, PERIOD)
        self.assertEqual(rec["bad_gaps"], 2)
        self.assertLess(len(rec["ticks"]), 3 * (len(sparse) - 1) + 1)

    def test_empty_and_single(self):
        self.assertEqual(win_vsync.reconstruct([], PERIOD)["ticks"], [])
        self.assertEqual(win_vsync.reconstruct([(5, 100)], PERIOD)["ticks"], [100.0])


class TestStats(unittest.TestCase):
    def test_residuals_regular_vs_vrr(self):
        regular = _timeline()[::3]
        r = win_vsync.fit_residuals_ms(regular, FREQ)
        self.assertLess(r["p99"], 0.001)
        self.assertAlmostEqual(r["period_ms"], 1000 / 59.94, places=3)
        wobbly = [(c, q + (int(0.002 * FREQ) if i % 2 else 0)) for i, (c, q) in enumerate(regular)]
        self.assertGreater(win_vsync.fit_residuals_ms(wobbly, FREQ)["p99"], 0.5)
        self.assertIsNone(win_vsync.fit_residuals_ms(regular[:2], FREQ)["p99"])

    def test_interval_stats_counts_missed_and_short(self):
        ts = [i / 60.0 for i in range(120)]
        del ts[50]                      # one missed vblank
        ts.append(ts[10] + 0.001)       # one spurious wake: 1 ms + 15.7 ms, one short
        st = win_vsync.interval_stats(ts)
        self.assertAlmostEqual(st["hz"], 60.0, places=3)
        self.assertEqual(st["missed"], 1)
        self.assertEqual(st["short"], 1)
        self.assertIn("error", win_vsync.interval_stats([0.0, 0.1]))

    def test_nearest_offsets_are_signed(self):
        ref = [i / 60.0 for i in range(100)]
        late = win_vsync.nearest_offsets_ms([t + 0.0004 for t in ref[1:-1]], ref)
        early = win_vsync.nearest_offsets_ms([t - 0.0004 for t in ref[1:-1]], ref)
        self.assertAlmostEqual(late["median_ms"], 0.4, places=6)
        self.assertAlmostEqual(early["median_ms"], -0.4, places=6)
        self.assertEqual(win_vsync.nearest_offsets_ms([], ref)["n"], 0)


class _FakeSource:
    def __init__(self, times):
        self._t = times

    def stop(self):
        pass

    def times_s(self, offset):
        return [t + offset for t in self._t], {"fake": True}


class TestWinVsyncClockContract(unittest.TestCase):
    SURFACE = ("times", "period_s", "available", "error", "start", "stop")

    def test_same_surface_as_frame_probe_clock(self):
        mac, win = frame_probe.VsyncClock(), win_vsync.WinVsyncClock()
        for name in self.SURFACE:
            self.assertTrue(hasattr(mac, name), f"frame_probe.VsyncClock lost {name}")
            self.assertTrue(hasattr(win, name), f"WinVsyncClock lacks {name}")
        self.assertEqual(type(win.times), type(mac.times))

    @unittest.skipIf(sys.platform == "win32", "off-Windows behaviour")
    def test_start_off_windows_reports_why(self):
        c = win_vsync.WinVsyncClock()
        self.assertFalse(c.start())
        self.assertFalse(c.available)
        self.assertIn("Windows", c.error)
        c.stop()  # never started: no-op

    def test_stop_fills_sorted_times_and_period(self):
        c = win_vsync.WinVsyncClock()
        c.available, c._offset = True, 0.5
        c._src = _FakeSource([i / 60.0 for i in reversed(range(120))])
        c.stop()
        self.assertEqual(list(c.times), sorted(c.times))
        self.assertAlmostEqual(c.times[0], 0.5)
        self.assertAlmostEqual(c.period_s, 1 / 60.0, places=6)
        self.assertTrue(c.available)
        self.assertTrue(c.meta["fake"])
        n = len(c.times)
        c.stop()  # idempotent: frame_probe stops twice (run end + uninstall)
        self.assertEqual(len(c.times), n)

    def test_too_few_vsyncs_marks_unavailable(self):
        c = win_vsync.WinVsyncClock("d3dkmt")
        c.available, c._offset = True, 0.0
        c._src = _FakeSource([0.0, 0.016, 0.033])
        c.stop()
        self.assertFalse(c.available)
        self.assertIn("d3dkmt", c.error)


class TestWrapper(unittest.TestCase):
    def test_split_argv(self):
        w, p = win_jitter_probe.split_argv(
            ["--raw", "x.json", "--timer-res-1", "--display=fullscreen", "s.py", "--seconds", "5", "--", "--n", "3"])
        self.assertEqual(w, ["--raw", "x.json", "--timer-res-1", "--display=fullscreen"])
        self.assertEqual(p, ["s.py", "--seconds", "5", "--", "--n", "3"])
        # wrapper flags after the script belong to the probe / app
        self.assertEqual(win_jitter_probe.split_argv(["s.py", "--raw", "y"]), ([], ["s.py", "--raw", "y"]))

    def test_patch_targets_exist(self):
        for name in ("_on_run_start", "analyze"):
            self.assertTrue(callable(getattr(frame_probe.FrameProbe, name, None)), name)
        self.assertTrue(callable(frame_probe.current_rss_mb))
        for attr in ("t_start", "t_swap_end", "work", "swap", "gc_ms", "gc_gen", "meta"):
            self.assertTrue(hasattr(frame_probe.FrameProbe(), attr), attr)

    def test_frame_probe_builds_clock_from_module_global(self):
        sentinel = frame_probe.VsyncClock()
        with mock.patch.object(frame_probe, "VsyncClock", lambda: sentinel):
            self.assertIs(frame_probe.FrameProbe().vsync, sentinel)

    def test_main_installs_clock_and_writes_raw(self):
        import jitter_probe
        saved = (frame_probe.VsyncClock, frame_probe.current_rss_mb,
                 frame_probe.FrameProbe._on_run_start, frame_probe.FrameProbe.analyze)
        seen = {}

        def fake_main(argv):
            seen["argv"] = argv
            probe = frame_probe.FrameProbe()
            seen["clock"] = probe.vsync
            seen["rep"] = probe.analyze()  # < 3 frames: early error report
            return 0

        try:
            with tempfile.TemporaryDirectory() as td:
                raw = os.path.join(td, "sub", "r.raw.json")
                with mock.patch.object(jitter_probe, "main", fake_main):
                    rc = win_jitter_probe.main(
                        ["--vsync-source", "d3dkmt", "--raw", raw, "app.py", "--seconds", "3"])
                self.assertEqual(rc, 0)
                self.assertEqual(seen["argv"], ["app.py", "--seconds", "3"])
                self.assertIsInstance(seen["clock"], win_vsync.WinVsyncClock)
                self.assertEqual(seen["clock"].source_name, "d3dkmt")
                self.assertEqual(seen["rep"]["win"]["vsync_source"], "d3dkmt")
                with open(raw, encoding="utf-8") as f:
                    data = json.load(f)
                for key in ("t_start", "t_swap_end", "vsync", "vsync_period_s", "meta", "win"):
                    self.assertIn(key, data)
        finally:
            (frame_probe.VsyncClock, frame_probe.current_rss_mb,
             frame_probe.FrameProbe._on_run_start, frame_probe.FrameProbe.analyze) = saved


class TestSummary(unittest.TestCase):
    REP = {
        "meta": {"present_arg": "auto", "present_mode": "PRECISION", "present_hz": 60.0},
        "fps": 59.98, "display_hz": 60.0,
        "present": {"available": True, "frames_hz": 59.98, "refresh_hz": 59.94, "held_per_min": 12.5,
                    "episodes_per_min": 1.5, "episode_spacing_s": 25.0, "predicted_beat_s": 25.1},
        "hitches": {"steady_per_min": 0.4},
        "dur_steady": {"p99": 16.7, "p999": 17.1, "max": 30.2},
        "work_steady": {"p50": 7.9, "p99": 9.1},
        "phase_median_ms": {"swap": 0.3, "pace": 8.4},
        "pacing": {"late_p99_ms": 0.004},
        "gc": {"gen2": {"count": 19}, "gen2_max_ms": 9.8},
        "experiments": {"gc_freeze": True},
        "win": {"vsync_source": "dwm", "display": "fullscreen", "timer_res_1": False,
                "process_cpu_pct_of_one_core": 91.0,
                "clock": {"dwm_counter_delta": {"cFramesMissed": 3, "cFramesDropped": 0, "cFramesLate": 1}}},
    }

    def test_row_full_and_bare(self):
        row = win_summary.row("R3", self.REP)
        self.assertEqual(len(row), len(win_summary.COLS))
        self.assertIn("+gcfreeze", row[1])
        self.assertEqual(row[2], "fullscreen")
        self.assertEqual(row[6], "12.50 (1.50)")
        self.assertEqual(row[-1], "3/0/1")
        bare = win_summary.row("R0", {"fps": float("nan")})
        self.assertEqual(len(bare), len(win_summary.COLS))
        self.assertEqual(bare[6], "n/a")
        self.assertEqual(bare[4], "—")

    def test_main_reads_reports_not_raw(self):
        with tempfile.TemporaryDirectory() as td:
            for name, body in (("R1_auto.json", self.REP), ("R1_auto.raw.json", {"t_start": []}),
                               ("env.json", {})):
                with open(os.path.join(td, name), "w", encoding="utf-8") as f:
                    json.dump(body, f)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                win_summary.main([td])
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)  # header, rule, one run
        self.assertTrue(lines[2].startswith("| R1_auto |"))


class TestVerifySummary(unittest.TestCase):
    """``--prefix V``: the verification table for the pacing fix."""

    REP = {
        "meta": {"present_arg": "auto", "present_mode": "VSYNC", "present_hz": 60.0,
                 "gc_frozen": 103498, "cpu_pct_one_core": 31.4,
                 "pacer_end": {"strategy": "native", "interval": 1, "fallback": None,
                               "slips": 2, "overruns": 1, "presents": 5400}},
        "fps": 59.99,
        "vblank_steps": {"available": True, "hist": {1: 5399}, "off_per_min": 0.0,
                         "phase_p01": 0.12, "phase_p50": 0.15, "phase_p99": 0.26},
        "present": {"available": True, "held_per_min": 0.0, "episodes_per_min": 0.0},
        "hitches": {"steady_per_min": 0.0},
        "dur_steady": {"p99": 16.9, "max": 18.0},
        "work_steady": {"p50": 3.1, "p99": 5.0},
        "gc": {"gen2_times_s": [-0.0, 61.2], "gen2_max_ms": 40.0,
               "gen2_play_count": 1, "gen2_play_max_ms": 3.2},
        "win": {"vsync_source": "dwm", "display": None, "process_cpu_pct_of_one_core": 30.0},
        "events": [{"t": 0.0, "kind": "fx_auto", "detail": "high@60"},
                   {"t": 0.0, "kind": "fx_auto", "detail": "high@60"},
                   {"t": 14.2, "kind": "fx_auto", "detail": "medium@60"},
                   {"t": 61.0, "kind": "fx_auto", "detail": "high@60"}],
    }

    def test_vrow(self):
        row = win_summary.vrow("V1_first", self.REP)
        self.assertEqual(len(row), len(win_summary.VCOLS))
        col = dict(zip(win_summary.VCOLS, row))
        self.assertEqual(col["pacer (n) [fallback]"], "native (1) slips 2 (overruns 1)/5400")
        self.assertEqual(col["FX Auto (changes)"], "high@60 → medium@60 → high@60 (2)")
        self.assertEqual(col["vblank steps"], "{1: 5399}")
        # The setup collect (40 ms, before the freeze) is not play.
        self.assertEqual(col["gc2 in play n / max"], "1 / 3.2")
        self.assertEqual(col["CPU %1core"], "31")  # the probe's own figure wins
        bare = win_summary.vrow("V0", {})
        self.assertEqual(len(bare), len(win_summary.VCOLS))
        self.assertEqual(dict(zip(win_summary.VCOLS, bare))["vblank steps"], "n/a")
        self.assertEqual(dict(zip(win_summary.VCOLS, bare))["FX Auto (changes)"], "—")

    def test_fallback_shows(self):
        rep = json.loads(json.dumps(self.REP))
        rep["meta"]["pacer_end"] = {"strategy": "timer", "interval": 1,
                                    "fallback": "swap does not block (self-check)"}
        col = dict(zip(win_summary.VCOLS, win_summary.vrow("V1", rep)))
        self.assertIn("[swap does not block", col["pacer (n) [fallback]"])

    def test_main_prefix_v(self):
        with tempfile.TemporaryDirectory() as td:
            for name, body in (("V1_first.json", self.REP), ("V1_first.raw.json", {}),
                               ("R1_old.json", TestSummary.REP)):
                with open(os.path.join(td, name), "w", encoding="utf-8") as f:
                    json.dump(body, f)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                win_summary.main([td, "--prefix", "V"])
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("| run | present"))
        self.assertIn("vblank steps", lines[0])
        self.assertTrue(lines[2].startswith("| V1_first |"))


class TestLoadBurst(unittest.TestCase):
    """scripts/bench/load_burst.py (FX Auto stability runs)."""

    def test_args(self):
        import load_burst
        a = load_burst.parse_args(["--delay", "5", "--seconds", "3", "--workers", "all"])
        self.assertEqual((a.delay, a.seconds), (5.0, 3.0))
        self.assertEqual(a.workers, max(1, os.cpu_count() or 1))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            load_burst.parse_args(["--workers", "0"])

    def test_short_burst_runs_and_ends(self):
        import time
        import load_burst
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            load_burst.run(0.0, 0.2, 1)
        self.assertLess(time.time() - t0, 5.0)
        self.assertIn("load_burst: 1 busy worker(s)", buf.getvalue())
        self.assertIn("load_burst: done", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
