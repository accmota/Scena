"""Unit tests for atlas auto-hitbox fitting (Slice 5)."""
from __future__ import annotations

import unittest

import numpy as np

import math
import skia

from tests.media_support import media

from scena.atlas import (
    AtlasFrame,
    _UNION_CACHE,
    _choose_auto_collider,
    _frame_set_signature,
    _mask_to_source_ellipse,
    _quality_score,
    auto_collider_for_frames,
    ellipse_to_local,
    fill_holes,
    fit_bbox,
    fit_circle,
    fit_ellipse,
    fit_hull,
    greedy_rects,
    reset_atlas_caches,
    union_mask_for_frames,
)


class TestFillHoles(unittest.TestCase):
    def setUp(self):
        reset_atlas_caches()

    def test_enclosed_hole_is_filled(self):
        sq = np.zeros((32, 32), dtype=bool)
        sq[4:28, 4:28] = True
        sq[12:20, 12:20] = False
        filled = fill_holes(sq)
        self.assertTrue(filled[16, 16])
        self.assertEqual(int(filled.sum()), int(sq.sum()) + 64)

    def test_open_l_notch_stays_empty(self):
        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        filled = fill_holes(L)
        self.assertFalse(filled[10, 10])
        self.assertEqual(int(filled.sum()), int(L.sum()))


class TestFitCircle(unittest.TestCase):
    def test_accepts_disk(self):
        disk = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        disk[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 14 ** 2] = True
        hit = fit_circle(disk)
        self.assertIsNotNone(hit)
        self.assertGreater(hit[2], 10.0)
        self.assertGreaterEqual(hit[3], 0.90)  # precision

    def test_rejects_l_when_precision_capped(self):
        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        self.assertIsNone(fit_circle(L))

    def test_rejects_thin_tall_bar_that_overshoots_frame(self):
        """A fully-opaque 5x32 bar can't be covered by a circle without the
        circle bulging far past its own 5px-wide frame (radius must reach
        ~16 to cover the height). Precision must be scored against the
        circle's true area, not just the in-frame grid cells, or this
        wrongly reports ~100% precision (see regression: a laser-bolt
        sprite got a circle roughly 3x wider than its own art)."""
        bar = np.zeros((32, 5), dtype=bool)
        bar[:, :] = True
        self.assertIsNone(fit_circle(bar))


class TestShapeMetricsUseTrueArea(unittest.TestCase):
    def test_circle_precision_penalizes_overshoot_past_mask_bounds(self):
        from scena.atlas import _shape_metrics

        mask = np.ones((10, 10), dtype=bool)
        # A circle much bigger than the mask: every in-bounds cell is
        # opaque, so grid-based precision would read as 1.0, but the
        # circle's real area is far larger than the mask.
        yy, xx = np.ogrid[:10, :10]
        inside = (xx - 4.5) ** 2 + (yy - 4.5) ** 2 <= 50 ** 2
        prec, rec = _shape_metrics(mask, inside, area=math.pi * 50 * 50)
        self.assertAlmostEqual(rec, 1.0)
        self.assertLess(prec, 0.05)

    def test_precision_never_exceeds_one(self):
        """Discrete centers inside a small disk can outnumber πr²; clamp."""
        from scena.atlas import _shape_metrics

        mask = np.ones((5, 5), dtype=bool)
        inside = mask.copy()
        # Analytic area tiny vs 25 opaque cells.
        prec, _rec = _shape_metrics(mask, inside, area=math.pi * 1.0 * 1.0)
        self.assertLessEqual(prec, 1.0)


class TestFitEllipse(unittest.TestCase):
    def test_elongated_horizontal_bar(self):
        m = np.zeros((24, 48), dtype=bool)
        m[10:14, 4:44] = True
        hit = fit_ellipse(m)
        self.assertIsNotNone(hit)
        _, _, rx, ry, _, prec, rec = hit
        self.assertGreaterEqual(prec, 0.85)
        self.assertGreater(rx, ry)

    def test_local_angle_matches_true_orientation_after_y_flip(self):
        """``ellipse_to_local`` mirrors y (image y-down -> engine y-up), which
        reverses the sense of rotation. Regression: without negating the
        angle, a tilted ellipse ended up mirrored across the horizontal and
        pointed away from the shape it was meant to cover."""
        size = 60
        cx0 = cy0 = 30.0
        theta = math.radians(30.0)
        c0, s0 = math.cos(theta), math.sin(theta)
        half_len, half_wid = 25.0, 6.0
        m = np.zeros((size, size), dtype=bool)
        yy, xx = np.mgrid[0:size, 0:size]
        dx, dy = xx - cx0, yy - cy0
        u = dx * c0 + dy * s0
        v = -dx * s0 + dy * c0
        m[(np.abs(u) <= half_len) & (np.abs(v) <= half_wid)] = True

        hit = fit_ellipse(m)
        self.assertIsNotNone(hit)
        cx, cy, rx, ry, ang, _prec, _rec = hit

        frame = AtlasFrame(
            name="bar", x=0, y=0, w=size, h=size,
            src_x=0, src_y=0, src_w=size, src_h=size,
            pivot_x=0.5, pivot_y=0.5,
        )
        src_ell = _mask_to_source_ellipse(cx, cy, rx, ry, ang, frame, 1.0, 1.0)
        _nx, _ny, _nrx, _nry, local_ang = ellipse_to_local(*src_ell, frame)

        # Ground truth: transform the bar's own long-axis endpoints through
        # the same (working, pre-existing) y-up position pipeline and read
        # off the true local-space tilt.
        def to_local_xy(px: float, py: float) -> tuple:
            nx = (px - 0.5 * size) / size
            ny = (0.5 * size - py) / size
            return nx, ny

        p1 = to_local_xy(cx0 + half_len * c0, cy0 + half_len * s0)
        p2 = to_local_xy(cx0 - half_len * c0, cy0 - half_len * s0)
        true_ang = math.atan2(p1[1] - p2[1], p1[0] - p2[0])

        diff = (math.degrees(local_ang) - math.degrees(true_ang)) % 180.0
        diff = min(diff, 180.0 - diff)
        self.assertLess(diff, 2.0)


class TestFitTwoEllipses(unittest.TestCase):
    def test_kenney_plus_gets_two_ellipses(self):
        """Real plus/T art: H+V arm split should clear the recall floor."""
        import os
        from scena.atlas import (
            fit_two_ellipses, _downsample_alpha, fill_holes, auto_collider_for_frame,
        )
        from scena.sprite import Sheet

        sh = Sheet(media("shooter", "sheet.xml"))   # Kenney atlas frame
        fr = sh._frame_at(sh.names.index("laserRed09.png"))
        mask = fill_holes(_downsample_alpha(sh.image, fr.x, fr.y, fr.w, fr.h))
        hit = fit_two_ellipses(mask)
        self.assertIsNotNone(hit)
        pair, prec, rec = hit
        self.assertEqual(len(pair), 2)
        self.assertGreaterEqual(prec, 0.90)
        self.assertGreaterEqual(rec, 0.75)

        col = auto_collider_for_frame(
            sh.image, fr,
        )
        self.assertEqual(col.kind, "ellipses")
        self.assertEqual(len(col.ellipses), 2)

    def test_x_shape_gets_diagonal_ellipses(self):
        """Diagonal X art: two ±45° ellipses, not two overlapping central blobs."""
        import os
        import math
        from scena.atlas import (
            fit_two_ellipses, _downsample_alpha, fill_holes, auto_collider_for_frame,
        )
        from scena.sprite import Sheet

        sh = Sheet(media("shooter", "sheet.xml"))   # Kenney atlas frame
        fr = sh._frame_at(sh.names.index("laserBlue11.png"))
        mask = fill_holes(_downsample_alpha(sh.image, fr.x, fr.y, fr.w, fr.h))
        hit = fit_two_ellipses(mask, strict=True)
        self.assertIsNotNone(hit)
        pair, prec, rec = hit
        self.assertGreaterEqual(prec, 0.90)
        self.assertGreaterEqual(rec, 0.75)
        # Arms should be elongated and roughly orthogonal (≈90° apart mod 180).
        a0 = math.degrees(pair[0][4])
        a1 = math.degrees(pair[1][4])
        diff = abs(a0 - a1) % 180.0
        diff = min(diff, 180.0 - diff)
        self.assertGreater(diff, 50.0)
        for e in pair:
            aspect = max(e[2], e[3]) / max(min(e[2], e[3]), 1e-6)
            self.assertGreater(aspect, 1.5)

        col = auto_collider_for_frame(
            sh.image, fr,
        )
        self.assertEqual(col.kind, "ellipses")
        self.assertGreaterEqual(col.recall, 0.75)

    def test_l_shape_rejects_weak_two_ellipse_split(self):
        """H+V density split can invent a plus on an L; absolute recall floor rejects it."""
        from scena.atlas import fit_two_ellipses

        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        self.assertIsNone(fit_two_ellipses(L))
        col = _choose_auto_collider(L)
        self.assertNotEqual(col.kind, "ellipses")
        self.assertGreaterEqual(col.recall, 0.90)

    def test_force_ellipses_never_returns_empty_metrics(self):
        """Lab force_kind=ellipses must not bake none (r=p=0 → full-rect overlay)."""
        from scena.atlas import _choose_auto_collider

        # Convex disk: two-ellipse fit fails; must fall back to one ellipse/circle.
        disk = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        disk[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 12 ** 2] = True
        col = _choose_auto_collider(disk, force_kind="ellipses")
        self.assertNotEqual(col.kind, "none")
        self.assertGreater(col.recall, 0.0)
        self.assertGreater(col.precision, 0.0)

        # Plus: forced path should return two ellipses even if below auto floors.
        cross = np.zeros((32, 32), dtype=bool)
        cross[2:30, 12:20] = True
        cross[12:20, 2:30] = True
        col2 = _choose_auto_collider(cross, force_kind="ellipses")
        self.assertIn(col2.kind, ("ellipses", "ellipse", "circle"))
        self.assertGreater(col2.recall, 0.0)

    def test_force_circle_never_returns_empty_on_bar(self):
        """Lab force_kind=circle must keep a circle on thin bars (not full rect)."""
        from scena.atlas import _choose_auto_collider

        bar = np.zeros((8, 32), dtype=bool)
        bar[2:6, :] = True
        # Strict precision floor rejects a disk on a thin bar.
        self.assertIsNone(fit_circle(bar))
        col = _choose_auto_collider(bar, force_kind="circle")
        self.assertEqual(col.kind, "circle")
        self.assertIsNotNone(col.circle)
        self.assertGreater(col.recall, 0.0)
        self.assertGreater(col.precision, 0.0)

    def test_force_ellipse_never_returns_empty_on_needle(self):
        """Lab force_kind=ellipse keeps a prim on needles that miss p≥0.90."""
        from scena.atlas import _choose_auto_collider

        needle = np.zeros((4, 32), dtype=bool)
        needle[1:3, :] = True
        self.assertIsNone(fit_ellipse(needle))
        col = _choose_auto_collider(needle, force_kind="ellipse")
        self.assertIn(col.kind, ("ellipse", "circle"))
        self.assertGreater(col.recall, 0.0)
        self.assertGreater(col.precision, 0.0)

    def test_best_effort_circle_prefers_quality_not_max_radius(self):
        """best_effort must not always pick the covering (max-r) disk."""
        bar = np.zeros((8, 32), dtype=bool)
        bar[2:6, :] = True
        hit = fit_circle(bar, best_effort=True)
        self.assertIsNotNone(hit)
        _cx, _cy, r, prec, rec = hit
        # Covering radius is ~half-diagonal (~16); a quality pick stays tighter.
        self.assertLess(r, 14.0)
        covering = fit_circle(bar, min_precision=0.0)
        self.assertIsNotNone(covering)
        self.assertLess(r, covering[2])
        self.assertGreaterEqual(
            _quality_score(prec, rec),
            _quality_score(covering[3], covering[4]),
        )


class TestFitHull(unittest.TestCase):
    def test_contains_all_opaque_and_caps_verts(self):
        m = np.zeros((24, 24), dtype=bool)
        m[4:20, 4:20] = True
        hit = fit_hull(m, max_verts=6)
        self.assertIsNotNone(hit)
        verts, prec, rec = hit
        self.assertLessEqual(len(verts), 6)
        self.assertAlmostEqual(rec, 1.0)
        self.assertGreaterEqual(prec, 0.9)


class TestAdaptiveRects(unittest.TestCase):
    def test_stops_at_target_coverage(self):
        m = np.zeros((16, 16), dtype=bool)
        m[2:14, 2:14] = True
        rects = greedy_rects(m, max_rects=8, target=0.95)
        self.assertGreaterEqual(len(rects), 1)
        covered = sum(w * h for _, _, w, h in rects)
        self.assertGreaterEqual(covered / int(m.sum()), 0.95)

    def test_diminishing_gain_stops_early(self):
        m = np.zeros((32, 32), dtype=bool)
        m[0:28, 0:28] = True
        m[30, 30] = True
        rects = greedy_rects(m, max_rects=8)
        self.assertLess(len(rects), 8)


class TestQualityScore(unittest.TestCase):
    def test_perfect_fit_scores_one(self):
        self.assertAlmostEqual(_quality_score(1.0, 1.0), 1.0)

    def test_low_precision_is_never_rescued_by_recall(self):
        """Full coverage (recall=1.0) can't hide a bad (overshooting) fit;
        precision is raised to 1.5 so overshoot is worse than linear."""
        from scena.atlas import _AUTO_PRECISION_EXP

        self.assertLess(_quality_score(0.5, 1.0), 0.51)
        self.assertAlmostEqual(_quality_score(0.5, 1.0), 0.5 ** _AUTO_PRECISION_EXP)

    def test_recall_above_bar_gives_no_extra_credit(self):
        from scena.atlas import _AUTO_QUALITY_BAR

        at_bar = _quality_score(0.9, _AUTO_QUALITY_BAR)
        above_bar = _quality_score(0.9, 1.0)
        self.assertAlmostEqual(at_bar, above_bar)

    def test_recall_below_bar_is_scaled_down(self):
        from scena.atlas import _AUTO_QUALITY_BAR

        below = _quality_score(1.0, _AUTO_QUALITY_BAR / 2)
        self.assertLess(below, 0.6)


class TestGreedyCircles(unittest.TestCase):
    def test_two_disks_get_two_circles(self):
        from scena.atlas import greedy_circles

        m = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        m[(xx - 8) ** 2 + (yy - 8) ** 2 <= 6 ** 2] = True
        m[(xx - 23) ** 2 + (yy - 23) ** 2 <= 6 ** 2] = True
        circs = greedy_circles(m, max_circles=8)
        self.assertGreaterEqual(len(circs), 2)

    def test_stops_at_cap(self):
        from scena.atlas import greedy_circles

        m = np.ones((24, 24), dtype=bool)
        circs = greedy_circles(m, max_circles=3, target=1.0, diminish_floor=1.0)
        self.assertLessEqual(len(circs), 3)


class TestChooseAutoCollider(unittest.TestCase):
    def test_disk_picks_circle(self):
        disk = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        disk[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 14 ** 2] = True
        col = _choose_auto_collider(disk)
        self.assertEqual(col.kind, "circle")
        self.assertIsNotNone(col.circle)

    def test_filled_square_force_box(self):
        """Lab force_kind=box still returns a single covering rect."""
        sq = np.ones((24, 24), dtype=bool)
        col = _choose_auto_collider(sq, force_kind="box")
        self.assertEqual(col.kind, "boxes")
        self.assertEqual(len(col.boxes), 1)

    def test_l_picks_boxes_not_circle(self):
        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        col = _choose_auto_collider(L)
        self.assertNotEqual(col.kind, "circle")
        self.assertTrue(col.kind in ("boxes", "poly", "circles", "ellipse", "ellipses"))

    def test_cross_prefers_precise_rects_over_lossy_hull(self):
        """A plus/cross is concave at all four inner corners: any single
        convex hull has to cut across those notches, so its precision is
        far worse than two rects (one per arm). Regression: the old
        cheapest-candidate-above-a-hard-recall-bar policy picked the hull
        anyway because it was "cheaper", covering large empty triangles at
        the four corners.
        """
        cross = np.zeros((32, 32), dtype=bool)
        cross[2:30, 12:20] = True
        cross[12:20, 2:30] = True
        col = _choose_auto_collider(cross, force_kind="boxes")
        self.assertEqual(col.kind, "boxes")
        self.assertGreaterEqual(col.precision, 0.95)

    def test_concave_notch_prefers_rects_near_recall_bar_over_worse_hull(self):
        """Two blobs joined by a thin bridge: the hull has to bridge the
        concave notches on both sides of the bridge (poor precision), while
        rects (one per blob, skipping the thin bridge) land just under the
        recall bar but at perfect precision. Regression: rects lost purely
        for falling a hair short of a hard recall cutoff, even though they
        were unambiguously the tighter fit."""
        dumbbell = np.zeros((32, 32), dtype=bool)
        dumbbell[2:14, 2:14] = True
        dumbbell[18:30, 18:30] = True
        dumbbell[13:19, 13:19] = True
        col = _choose_auto_collider(dumbbell, force_kind="boxes")
        self.assertEqual(col.kind, "boxes")

    def test_two_disks_prefer_circles_when_rotating(self):
        m = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        m[(xx - 8) ** 2 + (yy - 8) ** 2 <= 6 ** 2] = True
        m[(xx - 23) ** 2 + (yy - 23) ** 2 <= 6 ** 2] = True
        col = _choose_auto_collider(m)
        self.assertIn(col.kind, ("circles", "circle"))
        n = len(col.circles) if col.circles else (1 if col.circle else 0)
        self.assertGreaterEqual(n, 2)

    def test_near_round_fitted_ellipse_demotes_to_circle(self):
        from scena.atlas import ellipse_as_circle, fit_ellipse

        disk = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        disk[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 12 ** 2] = True
        ell = fit_ellipse(disk)
        self.assertIsNotNone(ell)
        cx, cy, rx, ry, ang, prec, rec = ell
        self.assertIsNotNone(ellipse_as_circle(rx, ry))
        col = _choose_auto_collider(disk)
        self.assertEqual(col.kind, "circle")

        bar = np.zeros((32, 32), dtype=bool)
        bar[12:20, 2:30] = True
        ell2 = fit_ellipse(bar)
        self.assertIsNotNone(ell2)
        _, _, rx2, ry2, _, _, _ = ell2
        self.assertIsNone(ellipse_as_circle(rx2, ry2))

    def test_auto_never_picks_multi_rect(self):
        """Concave plus: auto never emits multi-rect (rotation-safe policy)."""
        cross = np.zeros((32, 32), dtype=bool)
        cross[2:30, 12:20] = True
        cross[12:20, 2:30] = True
        forced = _choose_auto_collider(cross, force_kind="boxes")
        self.assertEqual(forced.kind, "boxes")
        self.assertGreaterEqual(len(forced.boxes), 2)

        auto = _choose_auto_collider(cross)
        if auto.kind == "boxes":
            self.assertEqual(len(auto.boxes), 1)
            self.assertGreaterEqual(auto.recall, 0.90)
        else:
            self.assertIn(
                auto.kind,
                ("poly", "circles", "circle", "ellipse", "ellipses"),
            )

    def test_auto_skips_undershooting_single_rect(self):
        """L-shape: 1-rect covers only one arm (~57% recall). Must not win."""
        L = np.zeros((32, 32), dtype=bool)
        L[:, :8] = True
        L[24:, :] = True
        col = _choose_auto_collider(L)
        self.assertNotEqual(col.kind, "boxes")
        self.assertGreaterEqual(col.recall, 0.75)

    def test_plus_picks_two_ellipses(self):
        import os
        from scena.atlas import auto_collider_for_frame
        from scena.sprite import Sheet

        sh = Sheet(media("shooter", "sheet.xml"))   # Kenney atlas frame
        fr = sh._frame_at(sh.names.index("laserRed09.png"))
        col = auto_collider_for_frame(sh.image, fr)
        self.assertEqual(col.kind, "ellipses")

    def test_greedy_caps_at_five(self):
        from scena.atlas import greedy_rects, greedy_circles, _AUTO_RECT_CAP, _AUTO_CIRCLE_CAP

        self.assertEqual(_AUTO_RECT_CAP, 5)
        self.assertEqual(_AUTO_CIRCLE_CAP, 5)
        # Checkerboard-ish leftovers force many small covers if uncapped.
        m = np.zeros((32, 32), dtype=bool)
        for i in range(0, 32, 4):
            for j in range(0, 32, 4):
                m[i:i + 2, j:j + 2] = True
        self.assertLessEqual(
            len(greedy_rects(m, target=1.0, diminish_floor=1.0)), 5,
        )
        self.assertLessEqual(
            len(greedy_circles(m, target=1.0, diminish_floor=1.0)), 5,
        )

    def test_hull_concavity_loses_to_rects_on_plus(self):
        from scena.atlas import fit_hull, _hull_quality, _quality_score

        cross = np.zeros((32, 32), dtype=bool)
        cross[2:30, 12:20] = True
        cross[12:20, 2:30] = True
        hull = fit_hull(cross)
        self.assertIsNotNone(hull)
        _, prec, rec = hull
        self.assertLess(_hull_quality(prec, rec), _quality_score(1.0, 0.9))


class TestSilhouettePathV2(unittest.TestCase):
    def setUp(self):
        reset_atlas_caches()

    def test_vw_reduces_square_contour(self):
        from scena.atlas import (
            _FX_PATH_V2_MAX, _marching_squares_outer, _simplify_contour_vw,
        )
        sq = np.zeros((48, 48), dtype=bool)
        sq[6:42, 6:42] = True
        padded = np.zeros((50, 50), dtype=bool)
        padded[1:-1, 1:-1] = sq
        verts = _marching_squares_outer(padded)
        self.assertGreater(len(verts), 40)
        simple = _simplify_contour_vw(verts)
        self.assertLessEqual(len(simple), _FX_PATH_V2_MAX)
        self.assertLess(len(simple), len(verts))
        self.assertGreaterEqual(len(simple), 4)

    def test_fx_alpha_matches_hitbox_threshold(self):
        from scena.atlas import _FX_ALPHA
        # 0–255. Same floor as hitbox auto-bake (~6%).
        self.assertEqual(_FX_ALPHA, 16)

    def test_v1_cap_still_strides(self):
        from scena.atlas import _cap_contour
        verts = [(float(i), 0.0) for i in range(400)]
        capped = _cap_contour(verts)
        self.assertLessEqual(len(capped), 200)

    def test_bake_stores_both_paths(self):
        import skia
        from scena.atlas import AtlasFrame, _bake_frame_fx, _FX_PATH_V2_MAX
        info = skia.ImageInfo.Make(48, 48, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
        surf = skia.Surface.MakeRaster(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)
        paint = skia.Paint()
        paint.setColor(skia.ColorWHITE)
        canvas.drawRect(skia.Rect.MakeXYWH(8, 8, 32, 32), paint)
        img = surf.makeImageSnapshot()
        fx = _bake_frame_fx(img, AtlasFrame("sq", 0, 0, 48, 48))
        self.assertFalse(fx.empty)
        self.assertIsNotNone(fx.path)
        self.assertIsNotNone(fx.path_v2)
        self.assertLessEqual(fx.n_path_v2, _FX_PATH_V2_MAX)
        self.assertLessEqual(fx.n_path_v2, fx.n_path)
        # Quadratic smoothing: not a polyline of n_path_v2 line segments.
        self.assertFalse(fx.path_v2.isEmpty())

    def test_smooth_path_rounds_corners(self):
        from scena.atlas import _verts_to_smooth_path_norm
        verts = [(1.0, 1.0), (11.0, 1.0), (11.0, 11.0), (1.0, 11.0)]
        path = _verts_to_smooth_path_norm(verts, 12, 12)
        self.assertIsNotNone(path)
        self.assertFalse(path.isEmpty())
        # Four quads, not four lineTo corners.
        verbs = path.countVerbs() if hasattr(path, "countVerbs") else 0
        if verbs:
            self.assertGreaterEqual(verbs, 5)

    def test_sprite_sil_v2_sksl_compiles(self):
        from scena._sksl_shape import procedural_builder
        procedural_builder("sprite_sil_v2")


class TestMaskCache(unittest.TestCase):
    def setUp(self):
        reset_atlas_caches()

    def test_second_force_kind_does_not_downsample(self):
        import os
        from unittest.mock import patch
        from scena.atlas import auto_collider_for_frame, _downsample_alpha
        from scena.sprite import Sheet, reset_sprite_caches

        path = media("space", "star_gold.png")
        reset_sprite_caches()
        reset_atlas_caches()
        sh = Sheet(path)
        fr = sh._frame_at(0)
        with patch("scena.atlas._downsample_alpha", wraps=_downsample_alpha) as spy:
            auto_collider_for_frame(sh.image, fr, force_kind="circle")
            n_first = spy.call_count
            self.assertGreaterEqual(n_first, 1)
            auto_collider_for_frame(sh.image, fr, force_kind="poly")
            self.assertEqual(spy.call_count, n_first)

    def test_reset_atlas_caches_clears_mask_cache(self):
        import os
        from unittest.mock import patch
        from scena.atlas import auto_collider_for_frame, _downsample_alpha, _MASK_CACHE
        from scena.sprite import Sheet, reset_sprite_caches

        path = media("space", "star_gold.png")
        reset_sprite_caches()
        reset_atlas_caches()
        sh = Sheet(path)
        fr = sh._frame_at(0)
        auto_collider_for_frame(sh.image, fr)
        self.assertGreater(len(_MASK_CACHE), 0)
        reset_atlas_caches()
        self.assertEqual(len(_MASK_CACHE), 0)
        with patch("scena.atlas._downsample_alpha", wraps=_downsample_alpha) as spy:
            auto_collider_for_frame(sh.image, fr)
            self.assertGreaterEqual(spy.call_count, 1)


class TestFitBbox(unittest.TestCase):
    def test_occupied_extent(self):
        from scena.atlas import fit_bbox

        m = np.zeros((16, 16), dtype=bool)
        m[4:10, 2:8] = True
        self.assertEqual(fit_bbox(m), (2, 4, 6, 6))

    def test_one_pixel(self):
        from scena.atlas import fit_bbox

        m = np.zeros((8, 8), dtype=bool)
        m[3, 5] = True
        self.assertEqual(fit_bbox(m), (5, 3, 1, 1))

    def test_empty(self):
        from scena.atlas import fit_bbox

        m = np.zeros((8, 8), dtype=bool)
        self.assertIsNone(fit_bbox(m))


def _solid_rect_image(w: int, h: int, rects):
    """RGBA image: opaque white rects on transparent."""
    info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kUnpremul_AlphaType)
    surf = skia.Surface.MakeRaster(info)
    c = surf.getCanvas()
    c.clear(skia.ColorTRANSPARENT)
    paint = skia.Paint(Color=skia.ColorWHITE, AntiAlias=False)
    for x, y, bw, bh in rects:
        c.drawRect(skia.Rect.MakeXYWH(x, y, bw, bh), paint)
    return surf.makeImageSnapshot()


class TestUnionMask(unittest.TestCase):
    def setUp(self):
        reset_atlas_caches()

    def test_union_covers_both_silhouettes(self):
        # Left blob in cell 0, right blob in cell 1 — opposite sides of each
        # cell's centre pivot, so the union is strictly wider than one blob.
        img = _solid_rect_image(64, 32, ((2, 12, 8, 8), (54, 12, 8, 8)))
        a = AtlasFrame("a", 0, 0, 32, 32, src_x=0, src_y=0, src_w=32, src_h=32)
        b = AtlasFrame("b", 32, 0, 32, 32, src_x=0, src_y=0, src_w=32, src_h=32)
        packed, synth, sx, sy = union_mask_for_frames(((img, a), (img, b)))
        box = fit_bbox(packed)
        self.assertIsNotNone(box)
        x, y, bw, bh = box
        self.assertGreater(bw * sx, 24.0)
        one, _, osx, _ = union_mask_for_frames(((img, a),))
        one_box = fit_bbox(one)
        self.assertIsNotNone(one_box)
        self.assertGreater(bw * sx, one_box[2] * osx)

    def test_union_aligns_by_pivot(self):
        """Same packed blob, different pivots → union is offset, not stacked."""
        img = _solid_rect_image(32, 32, ((12, 12, 8, 8),))
        centered = AtlasFrame(
            "c", 0, 0, 32, 32, src_x=0, src_y=0, src_w=32, src_h=32,
            pivot_x=0.5, pivot_y=0.5,
        )
        left = AtlasFrame(
            "l", 0, 0, 32, 32, src_x=0, src_y=0, src_w=32, src_h=32,
            pivot_x=0.0, pivot_y=0.5,
        )
        packed, synth, sx, sy = union_mask_for_frames(((img, centered), (img, left)))
        box = fit_bbox(packed)
        self.assertIsNotNone(box)
        _x, _y, bw, _bh = box
        self.assertGreater(bw * sx, 16.0)
        one, _, osx, _ = union_mask_for_frames(((img, centered),))
        one_box = fit_bbox(one)
        self.assertIsNotNone(one_box)
        self.assertGreater(bw * sx, one_box[2] * osx * 1.5)

    def test_union_stamp_covers_sample_footprint(self):
        """Finer union grid than the per-frame downsample must stay solid.

        128px cells downsample to 32 (4px samples). A ~90px silhouette makes
        union cells ~3px, so a corner stamp is a stripe field and ``auto``
        keeps a 1px circle. The footprint stamp fills the rect.
        """
        img = _solid_rect_image(256, 128, (
            (24, 20, 80, 90),
            (128 + 24, 20, 80, 90),
        ))
        a = AtlasFrame("a", 0, 0, 128, 128)
        b = AtlasFrame("b", 128, 0, 128, 128)
        packed, _synth, _sx, _sy = union_mask_for_frames(((img, a), (img, b)))
        box = fit_bbox(packed)
        self.assertIsNotNone(box)
        x, y, bw, bh = box
        interior = packed[y:y + bh, x:x + bw]
        self.assertGreater(float(interior.mean()), 0.85)
        chosen = _choose_auto_collider(fill_holes(packed))
        self.assertGreater(chosen.recall, 0.7)
        if chosen.circle is not None:
            self.assertGreater(chosen.circle[2], 4.0)

    def test_union_cache_key_distinguishes_frame_sets(self):
        img = _solid_rect_image(96, 32, (
            (4, 12, 8, 8), (36, 4, 16, 16), (76, 12, 8, 8),
        ))
        f0 = AtlasFrame("0", 0, 0, 32, 32)
        f1 = AtlasFrame("1", 32, 0, 32, 32)
        f2 = AtlasFrame("2", 64, 0, 32, 32)
        items_ab = ((img, f0), (img, f1))
        items_ac = ((img, f0), (img, f2))
        auto_collider_for_frames(items_ab)
        auto_collider_for_frames(items_ac)
        ones = ((1.0, 1.0), (1.0, 1.0))
        self.assertEqual(len(_UNION_CACHE), 2)
        self.assertIn((_frame_set_signature(items_ab), "", ones), _UNION_CACHE)
        self.assertIn((_frame_set_signature(items_ac), "", ones), _UNION_CACHE)
        self.assertNotEqual(
            _frame_set_signature(items_ab),
            _frame_set_signature(items_ac),
        )

    def test_unit_scales_match_default_union(self):
        img = _solid_rect_image(32, 32, ((4, 4, 10, 20),))
        a = AtlasFrame("a", 0, 0, 32, 32)
        b = AtlasFrame("b", 0, 0, 32, 32, pivot_x=0.25, pivot_y=0.5)
        items = ((img, a), (img, b))
        m0, s0, _x0, _y0 = union_mask_for_frames(items)
        m1, s1, _x1, _y1 = union_mask_for_frames(items, scales=((1, 1), (1, 1)))
        self.assertTrue(np.array_equal(m0, m1))
        self.assertEqual(
            (s0.src_x, s0.src_y, s0.src_w, s0.src_h),
            (s1.src_x, s1.src_y, s1.src_w, s1.src_h),
        )

    def test_scale_pulls_a_tall_frame_into_the_reference(self):
        """A full second cell scaled by 0.5 must not keep its raw pixel span."""
        img = _solid_rect_image(64, 32, ((12, 12, 8, 8), (32, 0, 32, 32)))
        a = AtlasFrame("a", 0, 0, 32, 32)
        b = AtlasFrame("b", 32, 0, 32, 32)
        items = ((img, a), (img, b))
        big, _, sx, _sy = union_mask_for_frames(items)
        small, _, sx2, _sy2 = union_mask_for_frames(
            items, scales=((1.0, 1.0), (0.5, 0.5)),
        )
        box_big = fit_bbox(big)
        box_small = fit_bbox(small)
        self.assertIsNotNone(box_big)
        self.assertIsNotNone(box_small)
        self.assertGreater(box_big[2] * sx, box_small[2] * sx2 + 4)


def _simplify_hull_full_recheck(hull, centers, *, max_verts):
    """Reference simplifier: every centre against the whole trial polygon.

    ``_simplify_hull`` must match this vertex choice. The reference is the
    cubic check that stalled the first ``Sprite("ball.png")`` bake; production
    code tests only the new chord against the centres' hull.
    """
    from scena.atlas import _point_in_convex, _triangle_area

    poly = list(hull)
    cap = max(3, int(max_verts))
    while len(poly) > cap:
        n = len(poly)
        best_i = None
        best_cost = 1e300
        for i in range(n):
            trial = poly[:i] + poly[i + 1:]
            if any(not _point_in_convex(cx, cy, trial) for cx, cy in centers):
                continue
            cost = _triangle_area(poly[(i - 1) % n], poly[i], poly[(i + 1) % n])
            if cost < best_cost:
                best_cost = cost
                best_i = i
        if best_i is None:
            break
        poly.pop(best_i)
    return poly


def _corner_hull_and_centers(mask):
    """Occupied-cell corner hull and centres, as ``fit_hull`` builds them."""
    from scena.atlas import _convex_hull, _occupied_centers

    ys, xs = np.nonzero(mask)
    pts = []
    for x, y in zip(xs.tolist(), ys.tolist()):
        xf, yf = float(x), float(y)
        pts.extend(((xf, yf), (xf + 1.0, yf), (xf + 1.0, yf + 1.0), (xf, yf + 1.0)))
    return _convex_hull(pts), _occupied_centers(mask)


class TestSimplifyHull(unittest.TestCase):
    """Hull simplification stays pixel-exact and cheap on a round mask."""

    def _assert_matches_recheck(self, mask, max_verts):
        from scena.atlas import _point_in_convex, _simplify_hull

        hull, centers = _corner_hull_and_centers(mask)
        if len(hull) < 3 or not centers:
            return
        got = _simplify_hull(hull, centers, max_verts=max_verts)
        ref = _simplify_hull_full_recheck(hull, centers, max_verts=max_verts)
        self.assertEqual(got, ref)
        for cx, cy in centers:
            self.assertTrue(_point_in_convex(cx, cy, got))

    def test_disk_matches_full_recheck(self):
        mask = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        mask[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 15.0 ** 2] = True
        for max_verts in (3, 6, 8):
            self._assert_matches_recheck(mask, max_verts)

    def test_seeded_masks_match_full_recheck(self):
        rng = np.random.default_rng(1)
        for k in range(24):
            h, w = (int(v) for v in rng.integers(4, 13, 2))
            yy, xx = np.ogrid[:h, :w]
            kind = k % 3
            if kind == 0:
                cx = float(rng.uniform(0, w))
                cy = float(rng.uniform(0, h))
                rx = float(rng.uniform(1, w))
                ry = float(rng.uniform(1, h))
                mask = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1
            elif kind == 1:
                mask = rng.random((h, w)) < float(rng.uniform(0.05, 0.9))
            else:
                mask = np.zeros((h, w), dtype=bool)
                for _ in range(int(rng.integers(1, 4))):
                    cx = float(rng.uniform(0, w))
                    cy = float(rng.uniform(0, h))
                    r = float(rng.uniform(1, 8))
                    mask |= (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
            for max_verts in (3, 6, 8):
                self._assert_matches_recheck(mask, max_verts)

    def test_round_mask_simplify_is_not_the_cubic_recheck(self):
        """32×32 disk, the worst hull. The cubic re-check (the stall in the first
        ``Sprite("ball.png")`` bake) is ~200× slower than production on the Mac
        and on Windows. Under a loaded tier both slow down together, so the
        ratio holds on any machine; an absolute ms budget did not (WP3, WP7)."""
        import time
        from scena.atlas import _simplify_hull

        mask = np.zeros((32, 32), dtype=bool)
        yy, xx = np.ogrid[:32, :32]
        mask[(xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 15.0 ** 2] = True
        hull, centers = _corner_hull_and_centers(mask)

        def ms(fn):
            start = time.perf_counter()
            fn()
            return (time.perf_counter() - start) * 1000.0

        fast = min(ms(lambda: _simplify_hull(hull, centers, max_verts=8)) for _ in range(5))
        slow = ms(lambda: _simplify_hull_full_recheck(hull, centers, max_verts=8))
        self.assertLess(fast * 20.0, slow, f"production {fast:.2f} ms, cubic {slow:.1f} ms")


class TestReviewedAtlasFixes(unittest.TestCase):
    def setUp(self):
        reset_atlas_caches()

    def test_disk_hull_recall_is_rasterized(self):
        from scena.atlas import _point_in_convex

        mask = np.zeros((40, 40), dtype=bool)
        yy, xx = np.ogrid[:40, :40]
        mask[(xx - 19.5) ** 2 + (yy - 19.5) ** 2 <= 14.0 ** 2] = True
        fitted = fit_hull(mask)
        self.assertIsNotNone(fitted)
        verts, precision, recall = fitted
        self.assertAlmostEqual(recall, 1.0)
        self.assertLess(precision, 1.0)
        hull = [(x + 0.5, y + 0.5) for x, y in verts]
        ys, xs = np.nonzero(mask)
        for x, y in zip(xs.tolist(), ys.tolist()):
            self.assertTrue(_point_in_convex(x + 0.5, y + 0.5, hull))

    def test_largest_island_contour_and_half_cell_norm(self):
        from scena.atlas import _marching_squares_outer, _verts_to_path_norm

        mask = np.zeros((48, 24), dtype=bool)
        mask[1:5, 1:5] = True
        mask[16:40, 2:20] = True
        contour = _marching_squares_outer(mask)
        self.assertGreaterEqual(len(contour), 4)
        self.assertFalse(
            contour[-2] == contour[0] and contour[-1] == contour[1]
        )
        self.assertNotEqual(contour[0], contour[-1])
        cy = sum(p[1] for p in contour) / len(contour)
        self.assertGreater(cy, 12.0)
        mw, mh = mask.shape[1], mask.shape[0]
        path = _verts_to_path_norm(contour, mw, mh)
        self.assertIsNotNone(path)
        x, y = contour[0]
        # Cell-centre normalization sits half a cell from the old (x - 1) offset.
        self.assertAlmostEqual((x - 0.5) / mw - (x - 1.0) / mw, 0.5 / mw)

    def test_xml_unnamed_frames_json_bom_and_negative_trim(self):
        import os
        import tempfile

        from scena.atlas import parse_atlas_json, parse_atlas_xml

        xml = """<TextureAtlas imagePath="sheet.png">
          <SubTexture x="0" y="0" width="8" height="8"/>
          <SubTexture x="8" y="0" width="8" height="8" frameX="-4" frameY="2"/>
        </TextureAtlas>"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = os.path.join(tmp, "atlas.xml")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(xml)
            _image, frames = parse_atlas_xml(xml_path)
            self.assertEqual(len(frames), 2)
            self.assertEqual(frames[1].src_x, 4)
            self.assertEqual(frames[1].src_y, 2)
            payload = (
                '{"frames":{"a":{"frame":{"x":0,"y":0,"w":8,"h":8},'
                '"spriteSourceSize":{"x":-3,"y":4,"w":8,"h":8}}}}'
            )
            json_path = os.path.join(tmp, "atlas.json")
            with open(json_path, "wb") as f:
                f.write(b"\xef\xbb\xbf" + payload.encode("utf-8"))
            _image, jframes = parse_atlas_json(json_path)
            self.assertEqual(len(jframes), 1)
            self.assertEqual(jframes[0].src_x, 3.0)
            self.assertEqual(jframes[0].src_y, 4.0)

    def test_rotated_frame_mask_matches_blit_unrotate(self):
        from scena.atlas import _display_mask, _mask_for_region

        img = _solid_rect_image(8, 16, ((0, 0, 8, 4),))
        frame = AtlasFrame("r", 0, 0, 8, 16, rotated=True)
        packed = _mask_for_region(img, 0, 0, 8, 16)
        shown = _display_mask(img, frame)
        self.assertTrue(np.array_equal(shown, np.rot90(packed, 1)))
        self.assertGreater(int(shown.sum()), 0)

    def test_rotated_blit_alpha_matches_display_mask(self):
        """Asymmetric packed frame: blit unrotate and ``_display_mask`` agree."""
        from scena.atlas import _display_mask

        w, h = 8, 4
        info = skia.ImageInfo.MakeN32Premul(w, h)
        surf = skia.Surface(info)
        canvas = surf.getCanvas()
        canvas.clear(skia.ColorTRANSPARENT)
        paint = skia.Paint(Color=skia.ColorBLACK)
        canvas.drawRect(skia.Rect.MakeXYWH(0, 0, 2, 4), paint)
        img = surf.makeImageSnapshot().makeRasterImage()
        frame = AtlasFrame("r", 0, 0, w, h, rotated=True)
        mask = _display_mask(img, frame)
        # Same swap and -90° the sprite blit uses (y-down, counter-clockwise).
        dw, dh = float(h), float(w)
        out = skia.Surface(int(dw), int(dh))
        oc = out.getCanvas()
        oc.clear(skia.ColorTRANSPARENT)
        oc.save()
        oc.translate(dw * 0.5, dh * 0.5)
        oc.rotate(-90.0)
        src = skia.Rect.MakeWH(w, h)
        dst = skia.Rect.MakeXYWH(-dh * 0.5, -dw * 0.5, dh, dw)
        oc.drawImageRect(img, src, dst, skia.SamplingOptions())
        oc.restore()
        snap = out.makeImageSnapshot().makeRasterImage()
        pixels = snap.toarray(colorType=skia.kRGBA_8888_ColorType)
        alpha = pixels[:, :, 3] > 0
        self.assertEqual(alpha.shape, mask.shape)
        self.assertTrue(np.array_equal(alpha, mask))

    def test_sheet_token_cache_drops_and_lru_evicts(self):
        import gc

        from scena.atlas import (
            _ATLAS_CACHE_CAP,
            _AUTO_CACHE,
            _MASK_CACHE,
            _cache_put,
            alloc_sheet_token,
            auto_collider_for_frame,
            bind_sheet_images,
            image_cache_token,
            release_sheet_token,
        )

        img = _solid_rect_image(16, 16, ((2, 2, 12, 12),))
        frame = AtlasFrame("a", 0, 0, 16, 16)
        token = alloc_sheet_token()
        bind_sheet_images(token, (img,))
        first = auto_collider_for_frame(img, frame)
        self.assertEqual(image_cache_token(img), token)
        self.assertTrue(any(key[0] == token for key in _AUTO_CACHE))
        release_sheet_token(token)
        del img
        gc.collect()
        self.assertFalse(any(key[0] == token for key in _AUTO_CACHE))
        fresh = _solid_rect_image(16, 16, ((0, 0, 4, 4),))
        second = auto_collider_for_frame(fresh, frame)
        self.assertIsNot(second, first)

        reset_atlas_caches()
        for i in range(_ATLAS_CACHE_CAP + 3):
            _cache_put(_MASK_CACHE, ("slot", i), i)
        self.assertEqual(len(_MASK_CACHE), _ATLAS_CACHE_CAP)
        self.assertNotIn(("slot", 0), _MASK_CACHE)
        self.assertIn(("slot", _ATLAS_CACHE_CAP + 2), _MASK_CACHE)

    def test_sheets_sharing_one_image_share_bakes(self):
        """A second Sheet over the same decoded image hits the first one's bake.

        Regression: each ``Sheet(path)`` got its own token, so a spawner building
        ``Sheet(path)`` per spawn refit ``hitbox_shape="auto"`` every time (~27 ms).
        """
        from scena.atlas import (
            _AUTO_CACHE,
            _MASK_CACHE,
            alloc_sheet_token,
            auto_collider_for_frame,
            bind_sheet_images,
            image_cache_token,
            release_sheet_token,
        )

        reset_atlas_caches()
        img = _solid_rect_image(16, 16, ((2, 2, 12, 12),))
        frame = AtlasFrame("a", 0, 0, 16, 16)
        t1 = alloc_sheet_token()
        bind_sheet_images(t1, (img,))
        first = auto_collider_for_frame(img, frame)
        t2 = alloc_sheet_token()
        bind_sheet_images(t2, (img,))
        self.assertEqual(image_cache_token(img), t1)
        self.assertIs(auto_collider_for_frame(img, frame), first)
        self.assertEqual((len(_AUTO_CACHE), len(_MASK_CACHE)), (1, 1))
        # First holder dies: the survivor keeps the token and the bake.
        release_sheet_token(t1)
        self.assertEqual(image_cache_token(img), t1)
        self.assertIs(auto_collider_for_frame(img, frame), first)
        # Last holder dies: binding and bakes go (image-id reuse stays safe).
        release_sheet_token(t2)
        self.assertEqual(image_cache_token(img), id(img))
        self.assertFalse(any(key[0] == t1 for key in _AUTO_CACHE))
        self.assertFalse(any(key[0] == t1 for key in _MASK_CACHE))


if __name__ == "__main__":
    unittest.main()
