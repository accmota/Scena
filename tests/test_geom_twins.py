"""N-version twins: one program, six executions, one shape (geometry campaign, H5).

The same random program of pose steps (``geom_shadow.STEPS``) runs on every
kind × model under six executions, and after every step each twin must read
what the normal twin reads (``diff_support.fingerprint``: pose and uncached
collision prims through cold engine readers, so reading never warms twin A):

* normal — twin A; ``assert_fast`` at the end where the kind starts fast;
* forced slow — ``_flag_pull_consumers`` (the batched path for good);
* caches dropped — every bare-read cache and memo cleared before each step;
* in a batch — each step inside a frame batch;
* in a frame — each step followed by one frame of world time;
* eager graph — eager registration and strong nodes (a fresh scena system).

At the end every point part, read publicly, must agree too. ``test_diff_pose``
does the forced-slow pair on its own model list; this runs every kind of
``geom_axes.K`` and the four other executions.

    python tests/run_tiers.py focused test_geom_twins
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hypothesis_support  # noqa: E402
from hypothesis import given, settings, strategies as hst  # noqa: E402
from hypothesis_support import fresh_world  # noqa: E402

import diff_support as D  # noqa: E402
import geom_axes as A  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402

KINDS = sorted(k for k in A.K if not k.startswith("Box"))
TWINS = ("forced_slow", "caches_dropped", "in_batch", "in_frame", "eager_graph")
# Kinds that start on the slow path by design (test_diff_pose.START_SLOW, GR5).
START_SLOW = ("Track line point_point",)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _run(kind, program, twin):
    """Fingerprints after every step of ``program`` on ``kind`` under ``twin``."""
    out = []
    with fresh_world() as w:
        G.reset_clock()
        obj = w.track(A.build(kind))
        if getattr(obj, "_ref", None) is not None:
            w.track(obj._ref)
        if twin == "forced_slow":
            D.force_slow(obj)
        for step in program:
            name, applies, run = S.STEP_BY_NAME[step]
            if not applies(obj):
                out.append(("n/a",))
                continue
            if twin == "caches_dropped":
                D.invalidate_all_caches(obj)
            sh = _ShadowStub(obj)

            def go():
                run(obj, sh)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if twin == "in_batch":
                        D.in_batch(go)
                    elif twin == "in_frame":
                        D.in_frame(go)
                    else:
                        go()
                out.append(("ok", D.fingerprint(obj)))
            except (Exception, RecursionError) as exc:  # noqa: BLE001
                out.append(("raises", type(exc).__name__))
                G.reset_clock()
        fast = D.is_fast(obj)            # before any public read warms a Derivate
        parts = {n: G.safe(f) for n, f in G.point_parts(obj).items()}
    return out, parts, fast


class _ShadowStub:
    """What a step reads from its shadow: the current heading and scale."""

    def __init__(self, obj):
        fp = D.fingerprint(obj)             # cold readers: twin A stays fast
        self.heading = float(fp.get("angle", 0.0))
        self.scale = float(fp.get("scale", 1.0))
        self.flip_x = bool(getattr(obj, "flip_x", False))
        self.flip_y = bool(getattr(obj, "flip_y", False))
        self.pending_turn = 0.0
        self.parts0 = {}

    def center(self):
        return (0.0, 0.0)

    def part(self, name):
        return (0.0, 0.0)


def _compare(tc, kind, program, twin):
    base, base_parts, fast = _run(kind, program, "normal")
    if twin == "eager_graph":
        with D.eager_graph():
            other, parts, _ = _run(kind, program, "normal")
    else:
        other, parts, _ = _run(kind, program, twin)
    for i, (a, b) in enumerate(zip(base, other)):
        what = f"{kind} under {twin}, after {program[:i + 1]}"
        tc.assertEqual(a[0], b[0], f"{what}: {a} vs {b}")
        if a[0] == "ok":
            D.assert_same(tc, b[1], a[1], what, rel=1e-7, abs_=1e-6)
    for n, v in base_parts.items():
        w = parts.get(n)
        if isinstance(v, G.ReadError) or isinstance(w, G.ReadError):
            continue
        tc.assertTrue(A.close_xy(v, w, 1e-6), f"{kind} under {twin}: {n} {w} vs {v}")
    return fast


INSTANT = [n for n in S.STEP_NAMES if n not in S.TIMED]


class TestTwinsAgree(unittest.TestCase):
    @settings(max_examples=max(10, settings().max_examples // 2))
    @given(kind=hst.sampled_from(KINDS), twin=hst.sampled_from(TWINS),
           program=hst.lists(hst.sampled_from(S.STEP_NAMES), min_size=1, max_size=6))
    def test_same_fingerprint_after_every_step(self, kind, twin, program):
        _compare(self, kind, program, twin)

    def test_every_kind_every_twin(self):
        """Deterministic sweep: a fixed program of instant steps (the fast path's own)."""
        program = ["move_by", "rotate_by", "scale_by", "flip_x", "angle =", "rotate_by about", "move_to"]
        for kind in KINDS:
            for twin in TWINS:
                _compare(self, kind, program, twin)

    def test_twin_a_stays_fast(self):
        """No vacuous pass: a free kind on instant moves and turns stays fast."""
        slow = []
        for kind in KINDS:
            if kind.startswith(START_SLOW) or G.is_relational(A.build(kind)):
                continue
            _out, _parts, fast = _run(kind, ["move_by", "rotate_by", "move_to"], "normal")
            if not fast:
                slow.append(kind)
        self.assertLess(len(slow), len(KINDS) // 2, f"twin A left the fast path: {slow}")


class TestTwinCanaries(unittest.TestCase):
    """The twins differ when only one execution path is wrong (SCENA_CANARIES)."""

    def test_catches_a_translate_error_on_the_fast_path(self):
        from diff_support import assert_catches
        orig = sys.modules["scena.shapes"]._translate_point_float

        def skewed(p, dx=None, dy=None):
            return orig(p, None if dx is None else dx * 1.001, dy)
        assert_catches(self, "test_geom_twins.TestTwinsAgree.test_every_kind_every_twin",
                       [("scena.shapes", "_translate_point_float", skewed)],
                       "a 0.1 % translate error on the fast path only")


if __name__ == "__main__":
    unittest.main()
