"""A linked ``scale`` is applied before anything reads the geometry it rewrites (SL1).

``shape["scale"] @= f`` drives ``scale_to`` through a property anchor, which
writes the sizes and the points only when it is pulled. A pull happened on a
read of ``scale`` itself, on ``box``, at the draw and in collision; a read of
``length`` / ``width`` / ``radius`` / ``p2`` / a corner made first after the
source moved returned the geometry of the last pull, and so did a formula that
read one of them (``probe["radius"] @= lambda: sq.width / 10``). The heading
had the same hole and its fix (D18) is the pattern: the shape pulls its linked
pose before a structural resolve, and the parts the verb rewrites carry
``_pull_owner``.

    python tests/run_tiers.py focused test_scale_link
"""
from __future__ import annotations

import os
import sys
import unittest
from collections.abc import Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from scena import Circle, Square, State  # noqa: E402
from scena.state import LinkedAttributeError  # noqa: E402

import geometry_support as G  # noqa: E402
import reactive_matrix_support as M  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

# Every kind with a pose scale (a Box is a value: no pose, no link). Kinds
# whose scale is refused while a part follows another shape (an Anchor, a
# ``parallel_dist`` / ``tangent_point`` Line, a ``from_rect`` Ellipse) are
# skipped where the link raises.
KINDS = [k for k in G.KINDS if not k.startswith("Box")]
# Reads past the slots: sizes, measures and points an author reads in update.
EXTRA = ("width", "height", "radius", "length", "box", "points", "corners")


def _names(obj):
    names = [n for n, _ in M.field_names(obj)]
    return names + [n for n in EXTRA if n not in names and hasattr(type(obj), n)]


def _flat(v):
    if isinstance(v, Sequence) and not isinstance(v, str):
        return tuple(_flat(x) for x in v)
    if hasattr(v, "width") and hasattr(v, "center") and not hasattr(v, "draw"):
        return (M._flat(v.center), round(float(v.width), 6), round(float(v.height), 6))
    return M._flat(v)


def _snapshot(obj, names):
    out = {}
    for n in names:
        try:
            out[n] = _flat(getattr(obj, n))
        except Exception as e:  # an error is a value: both sides must agree
            out[n] = "!" + type(e).__name__
    return out


# Each pose field and two values: the link's first value, then the source's.
POSE = {
    "scale": (1.5, 0.6),
    "angle": (20.0, 70.0),
    "flip_x": (False, True),
    "flip_y": (False, True),
}


def _formula(st, field):
    if isinstance(POSE[field][0], bool):
        return lambda: st.v is True
    return lambda: st.v + 0.0


class TestPoseLinkIsFresh(unittest.TestCase):
    """With ``shape[field] @= f`` on a pose field (``scale``, ``angle``, a flip)
    and the source moved, whichever name is read FIRST reads what
    ``shape.field = value`` gives."""

    def check(self, field):
        v0, v1 = POSE[field]
        linked = 0
        for kind in KINDS:
            names = _names(G.build(kind))
            for first in names:
                with self.subTest(kind=kind, first=first):
                    st = State(name=f"sl{next(M._COUNTER)}")
                    st.v = v0
                    subject, twin = G.build(kind), G.build(kind)
                    try:
                        subject[field] @= _formula(st, field)
                    except (LinkedAttributeError, AttributeError, TypeError):
                        continue        # not linkable here, or refused at the @=
                    try:
                        setattr(twin, field, v0)
                    except LinkedAttributeError:
                        continue        # the heading follows a reference shape
                    linked += 1
                    _snapshot(subject, [field] + names)
                    _snapshot(twin, [field] + names)
                    st.v = v1
                    setattr(twin, field, v1)
                    order = [first] + [n for n in names if n != first]
                    bad = M.diff(_snapshot(subject, order), _snapshot(twin, order))
                    self.assertEqual(bad, {}, f"{kind}: {first} read first")
        return linked

    def test_scale(self):
        self.assertGreater(self.check("scale"), 300, "vacuous: few links installed")

    def test_angle(self):
        self.assertGreater(self.check("angle"), 300, "vacuous: few links installed")

    def test_flip_x(self):
        self.assertGreater(self.check("flip_x"), 100, "vacuous: few links installed")

    def test_flip_y(self):
        self.assertGreater(self.check("flip_y"), 100, "vacuous: few links installed")


class TestCanaries(unittest.TestCase):
    """The plants the guard above must catch (skipped when SCENA_CANARIES=0)."""

    def test_a_pose_link_that_is_not_pulled_is_caught(self):
        from diff_support import assert_catches
        from scena.entity import Graphic
        assert_catches(
            self, "test_scale_link.TestPoseLinkIsFresh.test_scale",
            [(Graphic, "_pull_pose_links", lambda self: None)],
            "a size read before the linked scale was applied (SL1)")

    def test_a_read_that_skips_the_owner_is_caught(self):
        from diff_support import assert_catches
        from scena.state import Container
        assert_catches(
            self, "test_scale_link.TestPoseLinkIsFresh.test_scale",
            [(Container, "_pull_owner_first", lambda self: None)],
            "a Defining read that does not route through its owner (SL1)")


class TestFormulaOverAScaledShape(unittest.TestCase):
    """A formula that reads a size of a scale-linked shape follows the source,
    read before the shape's own ``scale``."""

    def test_formula_follows(self):
        st = State(name=f"sl{next(M._COUNTER)}")
        st.k = 0.5
        sq = Square(center=(0, 0), length=100)
        sq["scale"] @= lambda: st.k
        probe = Circle(center=(0, 0), radius=3)
        probe["radius"] @= lambda: sq.width / 10
        self.assertAlmostEqual(probe.radius, 5.0)
        st.k = 2
        self.assertAlmostEqual(probe.radius, 20.0)
        self.assertAlmostEqual(sq.length, 200.0)
        st.k = 1
        self.assertAlmostEqual(sq.top_left.x, -50.0)
        self.assertAlmostEqual(probe.radius, 10.0)


if __name__ == "__main__":
    unittest.main()
