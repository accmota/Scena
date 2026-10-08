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


def _heading_link(shape, st):
    """``shape["angle"] @= …`` as a value for ``__setitem__`` (the ``@=`` result)."""
    ref = shape["angle"]
    ref @= (lambda: st.v + 10.0)
    return ref


def _is_linked(shape, name):
    if isinstance(shape._field_slots()[name], ContainerSlot):
        return any(n._link is not None for n in getattr(shape, name)._iter_subtree())
    return shape[name].is_linked


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

    def test_every_input_the_heading_is_measured_from_is_exclusive(self):
        # Found by writing each input and watching ``angle``, not from the
        # engine's lists. A part the heading is read from but its turn does not
        # rewrite (a rim Circle's center) made the result depend on which
        # frames read it: the radius followed the center's path as far as
        # reads had seen it (45.8 unread vs 28.0 read, same final cell).
        for kind in DERIVED_HEADING:
            for name in _linkable_names(G.build(kind)):
                probe = G.build(kind)
                before = float(probe.angle)
                slot = probe._field_slots()[name]
                if isinstance(slot, ContainerSlot):
                    x, y = G.xy(getattr(probe, name))
                    setattr(probe, name, (x + 3.0, y + 5.0))
                else:
                    v = float(getattr(probe, name))
                    try:
                        setattr(probe, name, v + 3.0)
                    except ValueError:              # a bounded field (spread <= 360)
                        setattr(probe, name, v - 3.0)
                moves_heading = abs(float(probe.angle) - before) > 1e-9
                # A part the turn rewrites is exclusive whether or not it moves
                # the heading (pinned to the verb above).
                exclusive = moves_heading or name in _driven(probe)
                for heading_first in (True, False):
                    with self.subTest(kind=kind, part=name, heading_first=heading_first):
                        fresh = G.build(kind)
                        install = [lambda: fresh.__setitem__("angle", _heading_link(fresh, self.st)),
                                   lambda: _link(fresh, name, self.st)]
                        if not heading_first:
                            install.reverse()
                        install[0]()
                        if exclusive:
                            with self.assertRaises(LinkedAttributeError):
                                install[1]()
                            linked = (fresh["angle"].is_linked, _is_linked(fresh, name))
                            self.assertEqual(sum(linked), 1)            # installed nothing
                        else:
                            install[1]()
                            self.assertTrue(fresh["angle"].is_linked)
                            self.assertTrue(_is_linked(fresh, name))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
