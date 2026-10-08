"""
FxQuality preset tests.

    python -m unittest tests.test_fx_quality -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init, FxQuality
from scena.fx_quality import (
    next_quality,
    QUALITY_ORDER,
    preset_for,
    DEFAULT_FX_QUALITY,
    fidelity_tier,
    fidelity_is_lite,
    fidelity_is_survival,
    fidelity_is_max,
    particle_scale,
    hero_fx_lod,
    RENDER_PROFILES,
    QUALITY_CYCLE,
    profile_index_for_quality,
    TIER_LOW,
    TIER_MED,
    TIER_HIGH,
    activate_quality,
)


class TestFxQuality(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)

    def test_default_is_high(self):
        canvas.fx_quality = "high"
        self.assertEqual(DEFAULT_FX_QUALITY, FxQuality.HIGH)
        self.assertEqual(canvas.fx_quality, FxQuality.HIGH)
        self.assertAlmostEqual(canvas.post_fx_scale, 0.5)
        self.assertAlmostEqual(canvas.shape_fx_scale, 1.0)
        self.assertTrue(canvas.batch_shared_filters)
        self.assertEqual(fidelity_tier(), TIER_HIGH)

    def test_presets(self):
        expected = {
            FxQuality.MAX: (1.0, 1.0, False),
            FxQuality.HIGH: (0.5, 1.0, True),
            FxQuality.MEDIUM: (0.5, 1.0, True),
            FxQuality.LOW: (0.25, 1.0, True),
        }
        for q, (post, shape, batch) in expected.items():
            p = preset_for(q)
            self.assertAlmostEqual(p["post_scale"], post)
            self.assertAlmostEqual(p["shape_scale"], shape)
            self.assertEqual(p["batch_shared_filters"], batch)
            self.assertNotIn("draw_cache_mode", p)
            self.assertNotIn("post_mode", p)

    def test_from_value_and_aliases(self):
        self.assertEqual(FxQuality._from_value("high"), FxQuality.HIGH)
        self.assertEqual(FxQuality._from_value("medium"), FxQuality.MEDIUM)
        self.assertEqual(FxQuality._from_value("med"), FxQuality.MEDIUM)
        self.assertEqual(FxQuality._from_value("max"), FxQuality.MAX)
        self.assertEqual(FxQuality._from_value(0), FxQuality.LOW)
        with self.assertRaises(ValueError):
            FxQuality._from_value("nope")

    def test_next_quality_cycles(self):
        q = FxQuality.LOW
        seen = []
        for _ in range(len(QUALITY_CYCLE) + 1):
            seen.append(q)
            q = next_quality(q)
        self.assertEqual(seen[0], seen[-1])
        self.assertEqual(len(set(seen[:-1])), len(QUALITY_CYCLE))
        self.assertEqual(
            list(QUALITY_CYCLE),
            [FxQuality.LOW, FxQuality.MEDIUM, FxQuality.HIGH],
        )
        # max is API-only; next step enters product cycle at low.
        self.assertEqual(next_quality(FxQuality.MAX), FxQuality.LOW)
        self.assertEqual(
            list(QUALITY_ORDER),
            [FxQuality.LOW, FxQuality.MEDIUM, FxQuality.HIGH, FxQuality.MAX],
        )

    def test_set_fx_quality_applies_scales_and_batch(self):
        canvas.fx_quality = "max"
        self.assertAlmostEqual(canvas.post_fx_scale, 1.0)
        self.assertAlmostEqual(canvas.shape_fx_scale, 1.0)
        self.assertFalse(canvas.batch_shared_filters)
        self.assertTrue(fidelity_is_max())
        self.assertEqual(fidelity_tier(), TIER_HIGH)

        canvas.fx_quality = "medium"
        self.assertAlmostEqual(canvas.post_fx_scale, 0.5)
        self.assertAlmostEqual(canvas.shape_fx_scale, 1.0)
        self.assertTrue(canvas.batch_shared_filters)
        self.assertTrue(fidelity_is_lite())
        self.assertFalse(fidelity_is_survival())
        self.assertEqual(fidelity_tier(), TIER_MED)
        self.assertAlmostEqual(particle_scale(), 0.75)

        canvas.fx_quality = "low"
        self.assertAlmostEqual(canvas.post_fx_scale, 0.25)
        self.assertAlmostEqual(canvas.shape_fx_scale, 1.0)
        self.assertTrue(canvas.batch_shared_filters)
        self.assertTrue(fidelity_is_survival())
        self.assertTrue(fidelity_is_lite())
        self.assertEqual(fidelity_tier(), TIER_LOW)
        self.assertAlmostEqual(particle_scale(), 0.5)

        canvas.fx_quality = "high"
        self.assertTrue(canvas.batch_shared_filters)
        self.assertAlmostEqual(canvas.shape_fx_scale, 1.0)
        self.assertFalse(fidelity_is_lite())
        self.assertEqual(fidelity_tier(), TIER_HIGH)
        self.assertAlmostEqual(particle_scale(), 1.0)

    def test_render_profiles(self):
        self.assertEqual(len(RENDER_PROFILES), 3)
        self.assertEqual(RENDER_PROFILES[0].quality, FxQuality.LOW)
        self.assertEqual(RENDER_PROFILES[1].quality, FxQuality.MEDIUM)
        self.assertEqual(RENDER_PROFILES[2].quality, FxQuality.HIGH)
        self.assertTrue(RENDER_PROFILES[2].batch_shared_filters)
        self.assertEqual(profile_index_for_quality("high"), 2)
        self.assertEqual(profile_index_for_quality("medium"), 1)
        # max maps onto the high product rung (not a cycle step).
        self.assertEqual(profile_index_for_quality("max"), 2)

    def test_hero_fx_lod(self):
        lod_low = hero_fx_lod("low")
        self.assertEqual(lod_low.passes, 1)
        self.assertFalse(lod_low.mask)
        lod_med = hero_fx_lod("medium")
        self.assertEqual(lod_med.passes, 2)
        self.assertFalse(lod_med.mask)
        lod_high = hero_fx_lod("high")
        self.assertEqual(lod_high.passes, 3)
        self.assertTrue(lod_high.mask)

    def test_activate_quality_is_hot_path_slots(self):
        activate_quality("low")
        self.assertIs(hero_fx_lod(), hero_fx_lod())  # same object
        self.assertEqual(fidelity_tier(), TIER_LOW)
        activate_quality("high")
        self.assertEqual(fidelity_tier(), TIER_HIGH)

    def test_outer_glow_pipeline_gate(self):
        from scena.filters import GlowFilter
        g = GlowFilter()
        canvas.fx_quality = "high"
        self.assertTrue(g._uses_filter_pipeline())
        canvas.fx_quality = "medium"
        self.assertTrue(g._uses_filter_pipeline())
        canvas.fx_quality = "low"
        self.assertTrue(g._uses_filter_pipeline())
        self.assertTrue(callable(getattr(g, "_draw_survival", None)))


if __name__ == "__main__":
    unittest.main()
