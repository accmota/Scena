"""Family parity: Sprite, Text, Track and Hitbox parts (geometry campaign, H6).

The shape sweeps reach these families through ``geom_axes.K`` (sheet-anchored
sprites included); this module holds what only a family has:

* ``TestSpriteArtInsideItsBox`` — a pixel oracle: the art a sprite draws
  (rendered, any sheet anchor, after turns, scales and flips) lies inside its
  ``.box``, and its collision prims lie inside the same frame.
* ``TestHitboxPartsFollowTheHost`` — a ``px_rect`` / ``px_circle`` part moves
  with every pose verb and flip of its host: its prims are the host's
  composed map (``geom_shadow``) applied to where they started.
* ``TestTextKeepsItsAnchor`` — after any verb, a new string keeps an anchored
  caption's anchor (and a centred caption's center), and a link that read the
  caption first follows (D25 / D26 generalized).
* ``TestReversedTrackAgrees`` — a ``reversed()`` view reads the host's path
  backwards after every verb on either of them (``view.at(u) == host.at(1 - u)``).

    python tests/run_tiers.py focused test_geom_families
"""
from __future__ import annotations

import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from hypothesis_support import fresh_world, quiet  # noqa: E402

import geom_axes as A  # noqa: E402
import geom_shadow as S  # noqa: E402
import geometry_support as G  # noqa: E402
from media_support import media  # noqa: E402
from scena import Point, Sheet, Sprite, State, Text, Track  # noqa: E402

SPRITES = ("Sprite", "Sprite sheet bottom", "Sprite sheet left", "Sprite sheet pair")
SEQUENCES = (
    (),
    ("rotate_by",),
    ("scale_by",),
    ("flip_x",),
    ("flip_y",),
    ("rotate_by", "flip_x"),
    ("scale_to", "rotate_by about", "flip_y"),
    ("flip_x", "flip_y", "angle ="),
)


def _apply(obj, kind, steps):
    sh = S.Shadow(obj, kind)
    for st in steps:
        if S.STEP_BY_NAME[st][1](obj):
            m, pose = S.STEP_BY_NAME[st][2](obj, sh)
            sh.push(m)
            S._update_pose(sh, pose)
    return sh


def _box_frame_contains(obj, pts, slack):
    from test_geometry_contract import _box_contains
    return _box_contains(obj, pts, slack)


class TestSpriteArtInsideItsBox(unittest.TestCase):
    """What a sprite draws stays inside ``.box`` (Sprite Design: the box is the drawn cell)."""

    def _art_pixels(self, obj):
        from test_diff_draw import render
        px = render([obj])
        lit = px[..., :3].max(axis=-1) > 30
        ys, xs = np.nonzero(lit)
        return list(zip(xs.astype(float) + 0.5, ys.astype(float) + 0.5))

    def test_every_anchor_after_every_sequence(self):
        wrong = []
        with fresh_world() as w:
            for kind in SPRITES:
                for steps in SEQUENCES:
                    p = dict(G.P0, x=80.0, y=60.0, s=1.6, r=0.0)
                    obj = w.track(A.build(kind, p))
                    with quiet():
                        _apply(obj, kind, steps)
                    pts = self._art_pixels(obj)
                    if len(pts) < 50:
                        wrong.append(f"{kind} {steps}: drew {len(pts)} pixels")
                        continue
                    if not _box_frame_contains(obj, pts, 1.5):
                        wrong.append(f"{kind} {steps}: art outside .box")
                    from test_geometry_contract import _prim_points
                    prims, conics = _prim_points(obj)
                    prims += [(c[1][0], c[1][1]) for c in conics]
                    if prims and not _box_frame_contains(obj, prims, 1e-4 * 100):
                        wrong.append(f"{kind} {steps}: collision prims outside .box")
                    gap = (float(obj.box.angle) - float(obj.angle)) % 360.0
                    if min(gap, 360.0 - gap) > 1e-6:
                        wrong.append(f"{kind} {steps}: box.angle {obj.box.angle} vs angle {obj.angle}")
        self.assertEqual(wrong, [])

    def test_the_oracle_can_fail(self):
        """A box that misses the art is caught (no vacuous pass)."""
        with fresh_world() as w:
            obj = w.track(A.build("Sprite sheet bottom", dict(G.P0, x=80.0, y=60.0, s=1.6, r=0.0)))
            pts = self._art_pixels(obj)
            moved = [(x + 30.0, y) for x, y in pts]
            self.assertFalse(_box_frame_contains(obj, moved, 1.5))


class TestHitboxPartsFollowTheHost(unittest.TestCase):
    def _part_points(self, part):
        """Prim corner points, and the radii of circle prims (compared apart)."""
        from scena.collision import _snapshot_shape_uncached
        pts, radii = [], []
        for prim in _snapshot_shape_uncached(part, cache_owner=None):
            kind = prim.kind.name
            if kind == "CIRCLE":
                cx, cy, r = prim.params[:3]
                pts.append((cx, cy))
                radii.append(r)
            elif kind == "OBB":
                cx, cy, hw, hh, ang = prim.params[:5]
                pts += G.frame_corners(cx, cy, 2 * hw, 2 * hh, math.degrees(ang))
            elif kind == "AABB":
                x1, y1, x2, y2 = prim.params[:4]
                pts += [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            else:
                pts += [tuple(v) for v in (prim.verts or ())]
        return pts, radii

    def test_parts_follow_every_verb_and_flip(self):
        wrong, moved = [], 0
        with fresh_world() as w:
            for kind in SPRITES:
                for knob in (dict(px_rect=(8, 6, 14, 10)), dict(px_circle=(20, 18, 6))):
                    for steps in SEQUENCES[1:]:
                        obj = w.track(A.build(kind, dict(G.P0, x=80.0, y=60.0, s=1.6, r=0.0)))
                        with quiet():
                            part = obj.add_hitbox(group="campaign_parts", **knob)
                        before, r0 = self._part_points(part)
                        with quiet():
                            sh = _apply(obj, kind, steps)
                        want = [S.apply(sh.m, q) for q in before]
                        k = math.sqrt(abs(sh.m[0] * sh.m[3] - sh.m[1] * sh.m[2]))
                        got, r1 = self._part_points(part)
                        if not G.same_set(G.as_set(got, 4), G.as_set(before, 4), 1e-3):
                            moved += 1
                        if not G.same_set(G.as_set(got, 4), G.as_set(want, 4), 1e-3):
                            wrong.append(f"{kind} {sorted(knob)} {steps}")
                        elif any(abs(a * k - b) > 1e-3 for a, b in zip(r0, r1)):
                            wrong.append(f"{kind} {sorted(knob)} {steps}: radius")
        self.assertEqual(wrong, [], "a hitbox part left its host's pose")
        self.assertGreater(moved, 40, "vacuous: the parts never moved")


class TestTextKeepsItsAnchor(unittest.TestCase):
    PLACES = ("center", "top_left", "top_right")
    VERBS = {
        "none": lambda t: None,
        "rotate_by": lambda t: t.rotate_by(33),
        "move_by": lambda t: t.move_by(7, -3),
        "scale_by": lambda t: t.scale_by(1.4),
        "angle =": lambda t: setattr(t, "angle", 20),
    }

    def test_a_new_string_keeps_the_anchor_and_links_follow(self):
        wrong = []
        with fresh_world() as w:
            for place in self.PLACES:
                for vname, verb in self.VERBS.items():
                    for read_first in (False, True):
                        t = w.track(Text("geo", **{place: (40.0, 30.0)}))
                        verb(t)
                        pin = w.track(Point(0, 0))
                        pin @= (lambda t=t, place=place: getattr(t, place))
                        if read_first:
                            float(pin.x)
                        anchor = G.xy(getattr(t, place))
                        st = State(name="captions")
                        st.s = "geometry campaign"
                        t["text"] @= lambda: st.s
                        got = G.xy(getattr(t, place))
                        if not A.close_xy(got, anchor, 1e-6):
                            wrong.append(f"{place} after {vname}: the anchor moved {anchor} -> {got}")
                        if not A.close_xy(G.xy(pin), got, 1e-6):
                            wrong.append(f"{place} after {vname} (read first {read_first}): a link lags")
                        d = G.drawn(t)
                        from test_geometry_contract import _box_contains
                        if not _box_contains(t, d, 1e-6):
                            wrong.append(f"{place} after {vname}: box misses the new layout")
        self.assertEqual(wrong, [])


class TestReversedTrackAgrees(unittest.TestCase):
    HOSTS = {
        "points": lambda: Track(points=[(0, 0), (40, 5), (60, 30), (20, 40)]),
        "circle": lambda: Track.circle(radius=20, center=(10, 5)),
        "eight": lambda: Track.eight(width=60, height=30, center=(0, 0)),
        "line": lambda: Track.line(p1=(0, 0), p2=(40, 10)),
    }
    STEPS = {
        "host move": lambda h, v: h.move_by(7, -3),
        "view move": lambda h, v: v.move_by(7, -3),
        "host turn": lambda h, v: h.rotate_by(33),
        "view turn": lambda h, v: v.rotate_by(33, about=(5, 5)),
        "host scale": lambda h, v: h.scale_by(1.3),
        "view scale": lambda h, v: v.scale_by(0.8),
        "host flip": lambda h, v: setattr(h, "flip_x", not h.flip_x),
    }

    def test_view_reads_the_host_backwards(self):
        wrong = []
        with fresh_world() as w:
            for hname, make in self.HOSTS.items():
                for sname, step in self.STEPS.items():
                    host = w.track(make())
                    view = host.reversed()
                    with quiet():
                        step(host, view)
                    for u in (0.0, 0.2, 0.5, 0.77, 1.0):
                        a, b = view.at(u), host.at(1.0 - u)
                        if not A.close_xy(tuple(map(float, a)), tuple(map(float, b)), 1e-6):
                            wrong.append(f"{hname} after {sname}: view.at({u}) {a} vs host.at({1 - u}) {b}")
                            break
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
