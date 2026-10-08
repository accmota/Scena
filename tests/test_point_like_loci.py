"""Location APIs accept one point-like. Delta APIs still reject a Graphic."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import canvas, init
from scena.box import Box
from scena.collision import collision, get_collision_system, reset_collision_system
from scena.cover import get_cover, reset_cover
from scena.history import Contrail
from scena.input import Mouse
from scena.process import tween
from scena.shapes import Circle, Point, Rect
from scena.scenamath import Vec2
from scena.track import Track


def _mouse(x, y):
    mouse = Mouse()
    mouse._x = x
    mouse._y = y
    return mouse


def _spellings(x, y):
    return {
        "tuple": (x, y),
        "point": Point(x, y, layer=None),
        "vec": Vec2(x, y),
        "graphic": Circle(center=(x, y), radius=1, layer=None),
        "mouse": _mouse(x, y),
    }


def _round_xy(pair):
    return (round(float(pair[0]), 4), round(float(pair[1]), 4))


class TestPointLikeLoci(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        reset_collision_system()
        reset_cover()

    def tearDown(self):
        reset_collision_system()
        reset_cover()

    def test_spellings_agree(self):
        target = Circle(center=(0, 0), radius=8)
        target.collidable = True
        get_collision_system().step()
        box = Box(center=(0, 0), width=80, height=40)
        grid = box.grid(2, 2)
        probes = _spellings(0, 0)

        def move_to(p):
            body = Circle(center=(-50, -50), radius=2, layer=None)
            body.move_to(p)
            return _round_xy((body.center.x, body.center.y))

        def contains(p):
            return target.contains_point(p)

        def rotated(p):
            rect = Rect(center=(0, 0), width=30, height=10, layer=None)
            rect.rotate_to(90, about=p)
            return _round_xy((rect.center.x, rect.center.y))

        def box_about(p):
            region = Box(center=(0, 0), width=30, height=10)
            region.rotate_to(90, about=p)
            return _round_xy((region.center.x, region.center.y))

        def query_point(p):
            return tuple(id(hit) for hit in collision.query_point(p))

        def query_circle(p):
            return tuple(id(hit) for hit in collision.query_circle(p, radius=4))

        def ray(p):
            # p is the origin spelling; the far end is the same kind of value.
            kind = next(k for k, v in probes.items() if v is p)
            far = _spellings(40, 0)[kind]
            hit = collision.raycast(p, p2=far)
            self.assertIsNotNone(hit)
            return round(hit[1], 4)

        def line_p1(p):
            track = Track.line(p1=p, length=100, angle=0)
            return _round_xy((track.center.x, track.center.y))

        def wave_start(p):
            track = Track.wave(length=100, amplitude=10, start=p)
            return _round_xy((track.center.x, track.center.y))

        def tween_to(p):
            body = Circle(center=(-20, -20), radius=1, layer=None)
            handle = tween(body.center, p, time=0.2)
            handle._tween_write(1.0)
            handle.cancel()
            return _round_xy((body.center.x, body.center.y))

        def along(p):
            path = Track.line(length=80, angle=0, floating=True, layer=None)
            rider = Circle(center=(-100, -100), radius=1, layer=None)
            handle = rider.move_along(path, at=p, time=1)
            xy = _round_xy((rider.center.x, rider.center.y))
            handle.cancel()
            return xy

        def pan(p):
            canvas.pan_to(p)
            engine = canvas._engine
            return _round_xy((engine._look_x, engine._look_y))

        def iris(p):
            canvas.fade_out(0, style="iris", center=p)
            return _round_xy(get_cover().center)

        def cell(p):
            found = grid.cell_at(p)
            return None if found is None else id(found)

        def snap(p):
            trail = Contrail()
            point = trail.snapshot(p)
            return _round_xy((point.x, point.y))

        def burst(p):
            return canvas.burst_at(p, radius=10) is canvas

        actions = [
            move_to, contains, rotated, box_about, query_point, query_circle,
            ray, line_p1, wave_start, tween_to, along, pan, iris, cell, snap, burst,
        ]
        for action in actions:
            results = {name: action(value) for name, value in probes.items()}
            first = results["tuple"]
            for name, result in results.items():
                self.assertEqual(result, first, f"{action.__name__} via {name}")

        # The two-number form stays legal next to the point-like form.
        self.assertEqual(
            query_point((0, 0)),
            tuple(id(hit) for hit in collision.query_point(0, 0)),
        )
        self.assertEqual(
            query_circle((0, 0)),
            tuple(id(hit) for hit in collision.query_circle(0, 0, 4)),
        )

    def test_query_circle_positional_radius_raises(self):
        marker = Circle(center=(0, 0), radius=1, layer=None)
        with self.assertRaises(TypeError) as caught:
            collision.query_circle(marker, 80)
        self.assertIn("radius=", str(caught.exception))

    def test_deltas_reject_a_graphic(self):
        body = Circle(center=(0, 0), radius=2)
        marker = Circle(center=(5, 5), radius=1, layer=None)
        with self.assertRaises(TypeError):
            body.move_by(marker)
        with self.assertRaises(TypeError):
            canvas.pan_by(marker)
        with self.assertRaises(TypeError):
            Track.line(vec=marker)
        with self.assertRaises(TypeError):
            Track(vectors=[marker])

    def test_track_points_graphic_snapshots(self):
        """A Graphic in ``points=`` is a Container, so it takes the vertex path.

        That path still copies the center once (``takein`` / ``_xy_of``). It
        does not follow the Graphic. ``lambda: ship.center`` is the live form.
        """
        ship = Circle(center=(1, 2), radius=3)
        track = Track(points=[ship, (80, 2)])
        self.assertAlmostEqual(float(track._ctrl_points[0].x), 1.0)
        self.assertAlmostEqual(float(track._ctrl_points[0].y), 2.0)
        ship.move_to(9, 4)
        self.assertAlmostEqual(float(track._ctrl_points[0].x), 1.0)
        self.assertAlmostEqual(float(track._ctrl_points[0].y), 2.0)


if __name__ == "__main__":
    unittest.main()
