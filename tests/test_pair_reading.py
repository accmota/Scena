"""One reading of a point-like ``(x, y)`` at every author entry (Track C item 3).

About twenty private helpers turned a value into ``(x, y)``, each with its own
rules: lists accepted here and refused there, sequences longer than two read
as their first two items in some places, booleans taken as coordinates,
state cells unwrapped in some places only. They now delegate to
``shapes._xy_of`` (policies: ``graphic_center`` / ``duck`` for deltas,
``points=False`` where a Point is a place, not a displacement).

Rules: exactly two numbers; a list is a pair; a bool is not a coordinate; a
cell is read fresh. Vec2 refuses a Point operand where it would mean a
displacement (``Vec2 << point``) and says why.

    python tests/run_tiers.py focused test_pair_reading
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from scena import Circle, Point, Track, Vec2, st  # noqa: E402

ENTRIES = {
    "Point <<": lambda v: Point(0, 0) << v,
    "shape.move_to": lambda v: Circle(center=(0, 0), radius=1).move_to(v),
    "Track.line(p1=)": lambda v: Track.line(p1=v, p2=(10, 0)),
    "Point + delta": lambda v: Point(0, 0) + v,
    "Vec2 <<": lambda v: Vec2(0, 0) << v,
    "Vec2 +": lambda v: Vec2(0, 0) + v,
    "Vec2 -": lambda v: Vec2(0, 0) - v,
    "Track(vectors=)": lambda v: Track(vectors=[v, (3, 0)]),
}


def _cell():
    st.pair_reading_cell = (1.0, 2.0)
    return st.pair_reading_cell


ACCEPTED = {"tuple": lambda: (1, 2), "list": lambda: [1, 2], "cell": _cell}
REFUSED = {"three items": lambda: (1, 2, 3), "a bool": lambda: (True, 0),
           "one item": lambda: (1,), "text": lambda: ("1", "2")}


class TestEveryEntryReadsAPairTheSameWay(unittest.TestCase):
    def test_accepted_everywhere(self):
        for entry, call in ENTRIES.items():
            for kind, make in ACCEPTED.items():
                with self.subTest(entry=entry, value=kind):
                    call(make())

    def test_refused_everywhere_with_a_type_error(self):
        for entry, call in ENTRIES.items():
            for kind, make in REFUSED.items():
                with self.subTest(entry=entry, value=kind):
                    with self.assertRaises(TypeError):
                        call(make())

    def test_a_list_reads_like_the_tuple(self):
        a, b = Point(0, 0), Point(0, 0)
        a << (3, 4)
        b << [3, 4]
        self.assertEqual((a.x, a.y), (b.x, b.y))


class TestAPointIsAPlace(unittest.TestCase):
    def test_vec2_refuses_a_point_and_says_why(self):
        with self.assertRaises(TypeError) as cm:
            Vec2(0, 0) << Point(1, 1)
        self.assertIn("a Point is a place", str(cm.exception))

    def test_the_operand_message_no_longer_offers_a_point(self):
        with self.assertRaises(TypeError) as cm:
            Vec2(1, 1) + "a"
        self.assertNotIn("a Point", str(cm.exception))
        self.assertIn("Vec2 or an (x, y) pair", str(cm.exception))

    def test_a_delta_refuses_a_graphic(self):
        # A direction is not a Graphic (Track vectors, like move_by).
        with self.assertRaises(TypeError):
            Track(vectors=[Circle(center=(1, 1), radius=1), (3, 0)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
