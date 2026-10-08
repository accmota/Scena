"""Bench pulse auto-diff: framebuffer guard (scripts/bench/pulse.py, run_balanced.py).

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
