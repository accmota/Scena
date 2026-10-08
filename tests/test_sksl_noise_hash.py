"""SkSL value-noise lattice hash must be exact (Windows/Intel seam bug class).

Bug: every value-noise shader hashed corners with
``fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453)``. The weights are not
representable, so ``dot(i + (1,0), k)`` (this cell's right corner) and
``dot(i', k)`` (the neighbour's left corner) round differently once the driver
contracts / reassociates (Intel Iris Xe GL on Windows). ``* 43758`` amplifies one
ulp into an unrelated hash -> hard rectangular seams at every octave. Intel's
``sin`` also collapses to ~2 distinct values for ``|x| >= 2^17``.

Rule (Effect System Design §9): lattice hashes must take *exact* inputs and a
small ``sin`` argument -> ``n = dot(i, (127, 311) / 1024)``; corners ``n + c``.
Per-cell hashes (Stars, Embers, ...) use the same weights; shaders that loop over
neighbour cells salt in the exact ``n`` domain (``hash1(cn + 3.0)``), never
``hash(gid + float2(2.3, 0.7))``.
"""
from __future__ import annotations

import re
import unittest

import numpy as np

from scena import (
    _sksl_ambient,
    _sksl_ambient_kit,
    _sksl_backdrop,
    _sksl_effects,
    _sksl_shape,
)

MODULES = (_sksl_ambient, _sksl_ambient_kit, _sksl_backdrop, _sksl_effects, _sksl_shape)

W = (0.1240234375, 0.3037109375)          # (127, 311) / 1024
CORNERS = (0.0, 0.1240234375, 0.3037109375, 0.427734375)
SIN_SAFE = 2.0 ** 17                      # Intel GPU sin() collapses at |x| >= this


def _shader_sources():
    for mod in MODULES:
        for name, val in vars(mod).items():
            if isinstance(val, str) and "half4 main(" in val:
                yield f"{mod.__name__}.{name}", val
        for name, val in getattr(mod, "_SRCS", {}).items():
            yield f"{mod.__name__}._SRCS[{name!r}]", val


# A lattice hash evaluated at a shifted corner: H(i + float2(...)) — the seam pattern.
_CORNER_CALL = re.compile(r"\b\w*hash\w*\(\s*i\s*\+\s*float2\(")
_HASH1_OFFSET = re.compile(r"\bhash1\(\s*\w+\s*\+\s*([0-9.]+)\s*\)")
_NEIGHBOUR_LOOP = re.compile(r"for \(int \w+ = -1; \w+ <= 1;")
_FLOAT2_HASH_CALL = re.compile(r"\bhash(?!1\()\w*\(")


# fbm-like sums: a function named fbm* that samples noise() more than once.
_FBM = re.compile(r"float\s+(fbm\w*)\s*\(float2 p[^)]*\)\s*\{(.*?)\n\}", re.S)
_ROTATED = "0.8 * p.x - 0.6 * p.y"


class TestFbmOctavesRotate(unittest.TestCase):
    """Bug class: octaves on the same lattice axes add up value noise's axis
    ridges; a contrast curve then cuts straight edges and square holes (Clouds,
    2026-10). Every multi-octave fbm turns its domain between octaves
    (``(0.8, 0.6)`` rotation; ``floor()`` of the turned point is still an
    integer cell, so the exact hash above holds)."""

    def test_every_fbm_rotates_between_octaves(self):
        bad = []
        found = 0
        for name, src in _shader_sources():
            for m in _FBM.finditer(src):
                body = m.group(2)
                if body.count("noise(") > 1 or "for (" in body:
                    found += 1
                    if _ROTATED not in body:
                        bad.append(f"{name}:{m.group(1)}")
        self.assertGreaterEqual(found, 12)          # the scan still sees the shaders
        self.assertEqual(bad, [], "turn each octave: p = float2(0.8*p.x - 0.6*p.y, 0.6*p.x + 0.8*p.y)")


class TestNoiseHashSources(unittest.TestCase):
    def test_no_shader_hashes_shifted_lattice_corners(self):
        """Bug class: any hash(i + float2(..)) corner call can seam on some driver."""
        bad = [name for name, src in _shader_sources() if _CORNER_CALL.search(src)]
        self.assertEqual(bad, [], "use n = dot(i, W); hash1(n + c) (exact corners)")

    def test_every_value_noise_uses_exact_lattice_hash(self):
        found = 0
        for name, src in _shader_sources():
            if "float2 u = f * f * (3.0 - 2.0 * f);" not in src:
                continue
            found += 1
            with self.subTest(shader=name):
                # optional "+ g_seed_n" (seeded kit shaders: exact k / 1024 shift)
                self.assertRegex(
                    src,
                    r"float n = dot\(i, float2\(0\.1240234375, 0\.3037109375\)\)( \+ g_seed_n)?;",
                )
                for c in ("0.1240234375", "0.3037109375", "0.427734375"):
                    self.assertIn(f"hash1(n + {c})", src)
        self.assertGreaterEqual(found, 16)

    def test_no_shader_uses_inexact_hash_weights(self):
        """Old (127.1, 311.7) weights: inexact and past Intel's sin() cliff."""
        bad = [name for name, src in _shader_sources() if "127.1" in src or "311.7" in src]
        self.assertEqual(bad, [], "use float2(0.1240234375, 0.3037109375) = (127, 311) / 1024")

    def test_hash1_offsets_are_exact(self):
        """Every ``hash1(n + k)`` corner / salt is on the 2^-10 grid -> sums stay exact."""
        found = 0
        for name, src in _shader_sources():
            for lit in _HASH1_OFFSET.findall(src):
                found += 1
                with self.subTest(shader=name, offset=lit):
                    self.assertEqual(float(lit) * 1024 % 1, 0.0)
                    self.assertEqual(float(np.float32(lit)), float(lit))
        self.assertGreater(found, 60)

    def test_neighbour_loop_shaders_hash_in_exact_n_domain(self):
        """Pixels in different cells hash the same gid in different loop iterations."""
        found = 0
        for name, src in _shader_sources():
            if not _NEIGHBOUR_LOOP.search(src):
                continue
            found += 1
            with self.subTest(shader=name):
                self.assertIsNone(_FLOAT2_HASH_CALL.search(src), "salt as hash1(cn + k)")
        self.assertGreaterEqual(found, 2)   # Embers, WindStreaks

    def test_weights_are_exact_binary_fractions(self):
        self.assertEqual(W[0] * 1024, 127.0)
        self.assertEqual(W[1] * 1024, 311.0)
        self.assertEqual(CORNERS[3], W[0] + W[1])
        for w in W:
            self.assertEqual(float(np.float32(w)), w)


def _corner_inputs_f32(i, order):
    """Corner hash inputs the way a driver might compute them (float32)."""
    ix, iy = np.float32(i[..., 0]), np.float32(i[..., 1])
    wx, wy = np.float32(W[0]), np.float32(W[1])
    if order == "shared":                 # this cell: n + c
        n = ix * wx + iy * wy
        return n + np.float32(CORNERS[1])
    # neighbour cell: its own floor(p) == i + (1, 0), dotted directly
    return (ix + np.float32(1.0)) * wx + iy * wy


class TestNoiseHashExactness(unittest.TestCase):
    def _lattice(self):
        rng = np.random.default_rng(7)
        # realistic fbm octave range (offsets accumulate to ~(175, 302)) and well beyond
        return rng.integers(-30000, 30000, size=(20000, 2)).astype(np.float32)

    def test_shared_corner_inputs_bit_identical(self):
        i = self._lattice()
        a = _corner_inputs_f32(i, "shared")
        b = _corner_inputs_f32(i, "neighbour")
        np.testing.assert_array_equal(a.view(np.uint32), b.view(np.uint32))

    def test_old_weights_are_not_exact(self):
        """Documents the bug: (127.1, 311.7) corner inputs disagree in float32."""
        i = self._lattice()
        k = np.float32(127.1), np.float32(311.7)
        a = (i[:, 0] * k[0] + i[:, 1] * k[1]) + k[0]
        b = (i[:, 0] + np.float32(1.0)) * k[0] + i[:, 1] * k[1]
        self.assertGreater(np.mean(a != b), 0.1)

    def test_sin_argument_stays_in_intel_safe_range(self):
        i = self._lattice()
        n = np.abs(i[:, 0].astype(np.float64) * W[0] + i[:, 1] * W[1]) + CORNERS[3]
        self.assertLess(float(n.max()), SIN_SAFE)


class TestPerCellHashLook(unittest.TestCase):
    """New per-cell hash keeps the old statistics (star counts, independence)."""

    def setUp(self):
        g = np.stack(np.meshgrid(np.arange(-300, 300), np.arange(-300, 300)), -1)
        g = g.reshape(-1, 2).astype(np.float32)
        self.cn = g[:, 0] * np.float32(W[0]) + g[:, 1] * np.float32(W[1])

    def _h(self, salt=0.0):
        v = np.sin(self.cn + np.float32(salt)).astype(np.float32) * np.float32(43758.5453)
        return v - np.floor(v)

    def test_threshold_rates_match_uniform(self):
        h = self._h()
        for thr in (0.86, 0.9, 0.95, 0.97):   # star / ember / debris cut-offs
            self.assertAlmostEqual(float(np.mean(h > thr)), 1.0 - thr, delta=0.006)

    def test_salts_are_independent(self):
        h = self._h()
        for salt in (3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0):
            self.assertLess(abs(np.corrcoef(h, self._h(salt))[0, 1]), 0.02)

    def test_salted_sums_are_order_independent(self):
        """(cn + dx) + k == cn + (dx + k): unrolled neighbour loops can't disagree."""
        dx = np.float32(W[0])
        for salt in (3.0, 21.0):
            k = np.float32(salt)
            a = (self.cn + dx) + k
            b = self.cn + (dx + k)
            np.testing.assert_array_equal(a.view(np.uint32), b.view(np.uint32))


if __name__ == "__main__":
    unittest.main()
