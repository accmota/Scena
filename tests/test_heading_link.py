"""A linked heading and a linked part it rewrites are exclusive, refused at install (D17).

Where ``angle`` is derived (a Line from ``p1 → p2``, ``p1`` + ``vec``, ``p1`` +
``dx`` / ``dy``) a link on it drives ``rotate_to``, which refuses to write a
part that has its own formula. Installing the second link used to succeed and
every later read of ``angle`` raised ``LinkedAttributeError``. Now the second
link raises at the ``@=``, and installs nothing.

````_heading_driven_parts```` is pinned to what ``rotate_by`` refuses, in both
directions, so the list cannot drift from the verb.

    python tests/run_tiers.py focused test_heading_link
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

from scena import Line, State  # noqa: E402
from scena.state import ContainerSlot, FieldRef, LinkedAttributeError, ScalarSlot  # noqa: E402

import geometry_support as G  # noqa: E402
import reactive_matrix_support as M  # noqa: E402

DERIVED_HEADING = (
    "Line point_point", "Line point_vec", "Line point_dx_dy",
    "Circle two_points", "Circle center_perimeter",
    "Ellipse focal_points",
    "Rect spine cap", "Rect spine square", "Rect spine side_left", "Rect spine side_right",
)


def _name(part):
    return str(part.name) if isinstance(part, FieldRef) else part._attr_name


def _driven(line):
    return [_name(p) for p in line._heading_driven_parts()]


def _linkable_names(line):
    """Defining fields a link may drive, except the heading itself."""
    out = []
    for name, slot in line._field_slots().items():
        if name == "angle" or line._field_is_derivate(name, slot):
            continue
        if isinstance(slot, (ScalarSlot, ContainerSlot)):
            out.append(name)
    return out


def _link(line, name, st):
    slot = line._field_slots()[name]
    if isinstance(slot, ContainerSlot):
        line[name] @= (lambda: (st.v, st.v))
    else:
        line[name] @= (lambda: st.v + 0.0)


class TestHeadingLinkIsExclusive(unittest.TestCase):
    def setUp(self):
        self.st = State(name=f"hl{id(self)}")
        self.st.v = 1.0

    def test_a_part_link_then_the_heading_is_refused(self):
        for kind in DERIVED_HEADING:
            line = G.build(kind)
            for name in _driven(line):
                with self.subTest(kind=kind, part=name):
                    fresh = G.build(kind)
                    _link(fresh, name, self.st)
                    with self.assertRaises(LinkedAttributeError) as cm:
                        fresh["angle"] @= (lambda: self.st.v + 10.0)
                    self.assertIn(f"its {name} has an @= formula", str(cm.exception))
                    self.assertFalse(fresh["angle"].is_linked)      # installed nothing

    def test_the_heading_link_then_a_part_is_refused(self):
        for kind in DERIVED_HEADING:
            line = G.build(kind)
            for name in _driven(line):
                with self.subTest(kind=kind, part=name):
                    fresh = G.build(kind)
                    fresh["angle"] @= (lambda: self.st.v + 10.0)
                    with self.assertRaises(LinkedAttributeError) as cm:
                        _link(fresh, name, self.st)
                    self.assertIn("angle has an @= formula", str(cm.exception))
                    self.assertFalse(fresh[name].is_linked if not isinstance(
                        fresh._field_slots()[name], ContainerSlot) else
                        any(n._link is not None for n in getattr(fresh, name)._iter_subtree()))
                    self.assertEqual(float(fresh.angle), 11.0)       # the heading link survives

    def test_a_derived_kind_with_no_listed_parts_is_a_mistake(self):
        for kind in DERIVED_HEADING:
            self.assertTrue(_driven(G.build(kind)), kind)

    def test_the_part_the_heading_does_not_rewrite_still_links(self):
        # A linked ink field, or the heading as a model INPUT, is not a conflict.
        line = G.build("Line point_point")
        line["angle"] @= (lambda: self.st.v + 10.0)
        line.hp = 0.0
        line["hp"] @= (lambda: self.st.v + 0.0)
        centered = G.build("Line center_length")
        centered["center"] @= (lambda: (self.st.v, self.st.v))
        centered["angle"] @= (lambda: self.st.v + 10.0)


class TestDerivedHeadingLinkIsFresh(unittest.TestCase):
    """D18: with ``shape["angle"] @= f`` and the source moved, whichever name is
    read FIRST reads what ``shape.angle = value`` gives. The heading is applied
    when the anchor is pulled; a read of a point it rewrites (or of a Derivate
    built from them) used to see the points from before."""

    def test_every_name_read_first(self):
        for kind in DERIVED_HEADING:
            probe = G.build(kind)
            names = [n for n, _ in M.field_names(probe)]
            for first in names:
                with self.subTest(kind=kind, first=first):
                    st = State(name=f"fr{next(M._COUNTER)}")
                    st.v = 20.0
                    subject, twin = G.build(kind), G.build(kind)
                    subject["angle"] @= (lambda: st.v + 0.0)
                    twin.angle = 20.0
                    M.snapshot_names(subject, ["angle"])
                    M.snapshot_names(twin, ["angle"])
                    st.v = 70.0
                    twin.angle = 70.0
                    order = [first] + [n for n in names if n != first]
                    bad = M.diff(M.snapshot_names(subject, order),
                                 M.snapshot_names(twin, order))
                    self.assertEqual(bad, {}, f"{kind}: {first} read first")


class TestPartsListMatchesTheVerb(unittest.TestCase):
    """Linking X makes ``rotate_by`` refuse  <=>  X is in ``_heading_driven_parts``."""

    def test_list_equals_what_rotate_by_refuses(self):
        st = State(name=f"hv{id(self)}")
        st.v = 1.0
        for kind in DERIVED_HEADING:
            listed = set(_driven(G.build(kind)))
            refused = set()
            for name in _linkable_names(G.build(kind)):
                line = G.build(kind)
                try:
                    _link(line, name, st)
                except Exception:
                    continue
                try:
                    line.rotate_by(5.0)
                except LinkedAttributeError:
                    refused.add(name)
            with self.subTest(kind=kind):
                self.assertEqual(listed, refused,
                                 "``_heading_driven_parts`` drifted from Line.rotate_by")


# Pose verbs, each applied twice in every order: a store that one verb leaves
# behind shows only when the next verb builds on it.
POSE_OPS = {
    "angle = 50": lambda o: setattr(o, "angle", 50),
    "rotate_by 17": lambda o: o.rotate_by(17),
    "rotate_by 17 about": lambda o: o.rotate_by(17, about=(3.0, -4.0)),
    "rotate_to -40": lambda o: o.rotate_to(-40),
    "flip_x": lambda o: setattr(o, "flip_x", not o.flip_x),
    "flip_y": lambda o: setattr(o, "flip_y", not o.flip_y),
    "reset_rotation": lambda o: o.reset_rotation(),
    "scale_by 2": lambda o: o.scale_by(2),
    "move_by": lambda o: o.move_by(3, 1),
}


def pose_store_lags():
    """``"kind | op > op"`` where the pose store (``_rotation``, on the pose
    host for a Track view) differs from the ``angle`` the shape reads."""
    import itertools
    import math
    import warnings
    out, checked = {}, 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for kind in G.KINDS:
            for a, b in itertools.product(POSE_OPS, repeat=2):
                try:
                    obj = G.build(kind)
                except Exception:  # noqa: BLE001  (Box: a value, no pose)
                    continue
                if not hasattr(obj, "_rotation"):
                    continue
                try:
                    POSE_OPS[a](obj)
                    POSE_OPS[b](obj)
                    heading = float(obj.angle)
                except Exception:  # noqa: BLE001  (a refusal: other guards judge it)
                    continue
                host = obj._pose_host() if hasattr(obj, "_pose_host") else obj
                checked += 1
                if not math.isclose(heading, float(host._rotation), abs_tol=1e-6):
                    out[f"{kind} | {a} > {b}"] = (heading, float(host._rotation))
    return out, checked


class TestPoseStoreFollowsTheHeading(unittest.TestCase):
    """The pose store (``_rotation``) equals the heading a shape reads, after
    any two pose verbs. Where ``angle`` was a Defining slot (Rect, Square,
    Ellipse, Line by length, RegularPolygon) an ``angle =`` write left the
    store behind until the next verb: nothing drew wrong, because each verb
    rereads ``angle``, but a reader of the store in between saw the old
    heading (graphics review; 268 cases on HEAD). A Track view reads its host."""

    def test_every_kind_after_any_two_pose_verbs(self):
        lags, checked = pose_store_lags()
        self.assertGreater(checked, 2000, "vacuous sweep")
        self.assertEqual(lags, {})

    def test_canary_an_angle_write_that_does_not_publish(self):
        from diff_support import assert_catches
        from scena.shapes import Shape
        assert_catches(self, "test_heading_link.TestPoseStoreFollowsTheHeading.test_every_kind_after_any_two_pose_verbs",
                       # None turns off both the inline fast-path publish and the slow path.
                       [(Shape, "_publish_angle_input", None)],
                       "an angle write that leaves the pose store behind")


class TestLinkedDefiningAngleFollowsInStore(unittest.TestCase):
    """A link on a Defining ``angle`` pulls the value raw (Reactive Design,
    "Pull stores raw"); the pose store must follow it as it follows ``=``.
    It lagged a link pull on every such kind (GR17-link in Testing Design).
    Class guard: every kind whose model has a Defining ``angle``."""

    def test_every_kind_with_a_defining_angle(self):
        boot()
        st = State(name="gr17")
        st.a = 0.0
        checked = 0
        for kind in G.KINDS:
            obj = G.build(kind)
            if (G.is_box(obj) or G.is_relational(obj)      # no pose store / a relation drives it
                    or "angle" not in (getattr(obj, "_defining_part_names", ()) or ())):
                continue
            obj["angle"] @= lambda: st.a
            for v in (70.0, 430.0, -15.5):
                st.a = v
                self.assertAlmostEqual(float(obj.angle), v, msg=kind)
                self.assertAlmostEqual(float(obj._rotation), v, msg=f"{kind}: the store lags")
            checked += 1
        self.assertGreaterEqual(checked, 5, "vacuous sweep")


class TestWriteBeforeReadKeepsThePull(unittest.TestCase):
    """GX7: with a linked heading, a point the heading turns is pulled on read.
    A plain write to one coordinate before any read seeded the bare-read cache
    without that check, so the coordinate kept the written value after the
    heading's source moved while the other one turned."""

    def test_a_written_coordinate_still_turns_with_the_heading(self):
        boot()
        st = State(name="gx7")
        st.a = 0.0
        ln = Line(p1=(0, 0), p2=(10, 0))
        ln["angle"] @= lambda: st.a
        ln.p1.x = 1.0                       # before any read
        st.a = 90.0
        twin = Line(p1=(1, 0), p2=(10, 0))
        twin.rotate_to(90)
        self.assertAlmostEqual(float(ln.p1.x), float(twin.p1.x))
        self.assertAlmostEqual(float(ln.p1.y), float(twin.p1.y))


if __name__ == "__main__":
    unittest.main(verbosity=2)
