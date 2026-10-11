"""Measured boxes are lazy: ``Box._snapshot`` answers like an eager Box.

Rule under test (Box Design.md, "Measured boxes are lazy"): ``graphic.box``,
``Box(graphic)``, layout children and grid cells keep the center as floats
and build the center Point only when ``center`` is read or written. Every
public read and verb must answer exactly as ``Box(center=, width=, height=,
angle=)`` with the same names would.

Bug class guarded: a fast path that drifts from the slow one (a derived
corner read from a Point that was never filled, a write lost because the
pending floats won), and a measurement that quietly builds Shapes again.

    python -m unittest tests.test_box_snapshot -v
"""
import itertools
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import Box, Circle, Rect, Sprite, Text, canvas, group, init
from scena.shapes import Point, get_xy
from scena.state import get_scena_system
from tests.graph_support import full_collect, gc_paused  # noqa: E402

FRAMES = [
    (10.0, 20.0, 30.0, 40.0, 0.0),
    (-5.0, 7.5, 12.0, 3.0, 30.0),
    (100.0, -50.0, 0.0, 8.0, -135.0),
    (0.0, 0.0, 44.0, 0.0, 90.0),
]
SIGNS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
POINTS = (
    "center", "top_left", "top_right", "bottom_left", "bottom_right",
    "top_center", "bottom_center", "left_center", "right_center",
)


def twins(frame, signs):
    cx, cy, w, h, ang = frame
    eager = Box(center=(cx, cy), width=w, height=h, angle=ang)
    eager.__dict__["_name_signs"] = signs
    lazy = Box._snapshot(cx, cy, w, h, ang, name_signs=signs)
    return eager, lazy


def xy(p):
    return tuple(round(v, 9) for v in get_xy(p, bare=True))


def frame_of(box):
    return tuple(round(v, 9) for v in box._oriented_frame())


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        init(width=1000, height=800)
        canvas.reset_view()


class TestSameAnswers(SnapshotCase):
    def cases(self):
        for frame, signs in itertools.product(FRAMES, SIGNS):
            with self.subTest(frame=frame, signs=signs):
                yield twins(frame, signs)

    def test_scalar_reads(self):
        for eager, lazy in self.cases():
            for name in ("width", "height", "angle", "left", "right", "top", "bottom",
                         "is_collapsed"):
                self.assertAlmostEqual(float(getattr(lazy, name)), float(getattr(eager, name)),
                                       places=9, msg=name)
            self.assertEqual(repr(lazy), repr(eager))

    def test_point_reads(self):
        for eager, lazy in self.cases():
            for name in POINTS:
                self.assertEqual(xy(getattr(lazy, name)), xy(getattr(eager, name)), name)

    def test_layout_verbs(self):
        for eager, lazy in self.cases():
            self.assertEqual(frame_of(lazy.inset(2)), frame_of(eager.inset(2)))
            self.assertEqual(frame_of(lazy.outset(3)), frame_of(eager.outset(3)))
            for side in ("top", "bottom", "left", "right"):
                self.assertEqual(frame_of(lazy.strip(side, 5)), frame_of(eager.strip(side, 5)), side)
                self.assertEqual(frame_of(lazy.beside(side, gap=1)),
                                 frame_of(eager.beside(side, gap=1)), side)
                self.assertEqual(xy(lazy.strip(side, 5).top_left),
                                 xy(eager.strip(side, 5).top_left), side)
            lc = [frame_of(c) for c in lazy.grid(3, 2, gap=1)]
            ec = [frame_of(c) for c in eager.grid(3, 2, gap=1)]
            self.assertEqual(lc, ec)
            for pt in ((10, 20), (0, 0), (-5, 9)):
                self.assertEqual(lazy.contains_point(pt), eager.contains_point(pt))

    def test_rotation_verbs(self):
        for eager, lazy in self.cases():
            for box in (eager, lazy):
                box.rotate_by(15)
                box.rotate_by(20, about=(3, 4))
                box.rotate_to(-10)
            self.assertEqual(frame_of(lazy), frame_of(eager))
            self.assertEqual(xy(lazy.top_right), xy(eager.top_right))

    def test_writes_land_on_the_real_model(self):
        for eager, lazy in self.cases():
            for box in (eager, lazy):
                box.width = 50
                box.center = (1, 2)
                box.height = 6
            self.assertEqual(frame_of(lazy), frame_of(eager))
            self.assertEqual(xy(lazy.bottom_left), xy(eager.bottom_left))

    def test_a_corner_read_first_then_the_center(self):
        """Derived corners come from the floats; the center filled later agrees."""
        for eager, lazy in self.cases():
            self.assertEqual(xy(lazy.top_left), xy(eager.top_left))
            self.assertEqual(xy(lazy.center), xy(eager.center))
            lazy.center = (9, 9)
            eager.center = (9, 9)
            self.assertEqual(xy(lazy.top_left), xy(eager.top_left))

    def test_center_link(self):
        src = Point(5, 6)
        lazy = Box._snapshot(0, 0, 10, 10, 0)
        lazy["center"] @= src
        src.x = 20
        self.assertEqual(xy(lazy.center), (20.0, 6.0))
        self.assertAlmostEqual(lazy.left, 15.0)


class TestBuildsNoPointUntilAsked(SnapshotCase):
    def test_reads_and_layout_build_no_point(self):
        r = Rect(center=(10, 20), width=30, height=40, angle=30)
        s = Sprite("missing_for_snapshot_test.png", center=(0, 0))
        try:
            built = []
            real_init = Point.__init__

            def counting_init(self, *args, **kwargs):
                built.append(1)
                return real_init(self, *args, **kwargs)

            with mock.patch.object(Point, "__init__", counting_init):
                for g in (r, s):
                    b = g.box
                    b.width, b.height, b.left, b.right, b.top, b.bottom
                    b.contains_point((0, 0))
                    b.inset(1).width
                    b.strip("top", 2).height
                    [c.width for c in b.grid(2, 2)]
                    Box(g).width
                self.assertEqual(len(built), 0, "a measurement built a Point")
                b = r.box
                b.center
                self.assertEqual(len(built), 1, "reading center builds exactly one Point")
        finally:
            r.destroy()
            s.destroy()


class TestMeasuredPointsStayOffGraph(SnapshotCase):
    """D11 (Testing Design): a measured Box's point read entered the graph.

    ``graphic.box.top_left`` built a Point part that registered a node (and
    the Box one) with a structural edge. A Box and its parts are a reference
    cycle, so those nodes left the graph only at a full cyclic GC: reading a
    box point every frame climbed the node count until the leak detector
    warned "reactive graph rising". A measured Box's tree now stays off the
    graph until something links into it. Counted with the cyclic GC off, so
    refcounting alone must keep the graph flat.
    """

    READS = 40

    def setUp(self):
        super().setUp()
        self.enterContext(gc_paused())
        full_collect()

    def assert_flat(self, read, what):
        read()  # first touch may warm class-level caches
        graph = get_scena_system().dependency_graph
        before = len(graph.nodes)
        for _ in range(self.READS):
            read()
        self.assertEqual(len(graph.nodes), before, f"{what} grew the reactive graph")

    def test_every_point_of_every_measured_graphic(self):
        graphics = [
            Rect(center=(10, 20), width=30, height=40, angle=30),
            Circle(center=(0, 0), radius=12),
            Sprite("missing_for_snapshot_test.png", center=(5, 5)),
            Text("hi", center=(0, 0)),
        ]
        try:
            for g in graphics:
                for name in POINTS:
                    with self.subTest(graphic=type(g).__name__, point=name):
                        self.assert_flat(lambda: getattr(g.box, name).x,
                                         f"{type(g).__name__}.box.{name}")
        finally:
            for g in graphics:
                g.destroy()

    def test_layout_children_views_and_group_box(self):
        r = Rect(center=(0, 0), width=100, height=60, group="measured_d11")
        try:
            reads = {
                "box.inset(4).top_left": lambda: r.box.inset(4).top_left,
                "box.strip('top', 5).center": lambda: r.box.strip("top", 5).center,
                "box.grid(2, 2).cell(1, 1).top_right": lambda: r.box.grid(2, 2).cell(1, 1).top_right,
                "Box(graphic).bottom_left": lambda: Box(r).bottom_left,
                "canvas.game_view.top_left": lambda: canvas.game_view.top_left,
                "canvas.ui_view.center": lambda: canvas.ui_view.center,
                "group[...].box.top_right": lambda: group["measured_d11"].box.top_right,
                "canvas.playfield.inset(2).top_left": lambda: canvas.playfield.inset(2).top_left,
            }
            for what, read in reads.items():
                with self.subTest(what):
                    self.assert_flat(read, what)
        finally:
            r.destroy()

    def test_views_answer_like_the_corner_boxes(self):
        """game_view / ui_view / group box: same names as Box(p1=, p2=)."""
        vb = (canvas.game_view.left, canvas.game_view.bottom,
              canvas.game_view.right, canvas.game_view.top)
        eager = Box(p1=vb[:2], p2=vb[2:])
        lazy = canvas.game_view
        for name in POINTS + ("p1", "p2"):
            self.assertEqual(xy(getattr(lazy, name)), xy(getattr(eager, name)), name)
        self.assertEqual(repr(lazy), repr(eager))


class TestDeferredTreeStaysCorrect(SnapshotCase):
    """Off-graph, a measured Box must still answer like an eager one.

    Writes recompute eagerly (``Container.update``); the first link wires the
    whole tree (``Container._join_dependency_graph``). Bug class: a write or
    link that no longer reaches a derived corner because the edge that used
    to carry it is missing.
    """

    def test_writes_after_corner_reads(self):
        for frame, signs in itertools.product(FRAMES, SIGNS):
            with self.subTest(frame=frame, signs=signs):
                eager, lazy = twins(frame, signs)
                corners = ("top_left", "bottom_right", "right_center", "p1", "p2")
                for name in corners:
                    getattr(eager, name), getattr(lazy, name)
                steps = (
                    lambda b: setattr(b, "width", 50),
                    lambda b: setattr(b.center, "x", 7),
                    lambda b: setattr(b, "center", (1, 2)),
                    lambda b: b.center.move_by(3, -4),
                    lambda b: b.rotate_by(25, about=(2, 3)),
                    lambda b: setattr(b, "height", 6),
                )
                for step in steps:
                    step(eager)
                    step(lazy)
                    for name in corners:
                        self.assertEqual(xy(getattr(lazy, name)), xy(getattr(eager, name)), name)
                self.assertTrue(lazy._in_deferred_graph_tree(), "a write wired the tree")

    def test_link_from_a_measured_point_follows_the_box(self):
        b = Rect(center=(0, 0), width=20, height=10).box
        corner = b.top_right
        dot = Point(0, 0)
        dot @= corner
        self.assertFalse(b._in_deferred_graph_tree())
        self.assertIn(b._node_id, get_scena_system().dependency_graph.nodes)
        self.assertEqual(xy(dot), xy(corner))
        b.width = 40
        self.assertEqual(xy(dot), (20.0, 5.0))
        b.center = (100, 100)
        self.assertEqual(xy(dot), (120.0, 105.0))

    def test_link_into_a_measured_box_scalar(self):
        src = Point(30, 0)
        b = Rect(center=(0, 0), width=20, height=10).box
        corner = b.top_right  # materialized off-graph, before the link
        b["width"] @= lambda: src.x
        self.assertFalse(b._in_deferred_graph_tree())
        self.assertEqual(xy(b.top_right), (15.0, 5.0))
        src.x = 60
        self.assertEqual(xy(corner), (30.0, 5.0))

    def test_link_a_measured_center(self):
        src = Point(5, 6)
        b = Rect(center=(0, 0), width=10, height=10).box
        tl = b.top_left
        b["center"] @= src
        src.x = 20
        self.assertEqual(xy(tl), (15.0, 11.0))


if __name__ == "__main__":
    unittest.main()
