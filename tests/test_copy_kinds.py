"""Whole copies across kinds: every kind × every source kind × every copy door.

Shapes Design C7 "Copies": a copy reproduces its source, so a kind takes only
what it can be (a Rect takes a Square / Concave / Box frame, a Triangle a
regular triangle, a Polygon any polygon of its arity) and an Ellipse also fills
a Box, as ``Ellipse(box=)`` does (Box Design, "Fit"). Every other pair refuses
with a TypeError that names the fix, before any write.

The bug (CK1 in Testing Design): ``Circle(...) << box`` raised AttributeError,
``Ellipse(...) << box`` "Unknown ellipse model: RectModel.CENTER_WH" and
``Triangle(...) << box`` "'Box' object has no attribute '_n'" — through
``<<``, ``absorb`` and a whole ``@=`` alike — and most cross-kind pairs left
the target with the source's model. The matrix is derived from the kind
registry (``geometry_support.KINDS``), which must cover every exported kind.

    python tests/run_tiers.py focused test_copy_kinds
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import AUTHOR_ERRORS, fresh_world, quiet  # noqa: E402

import geometry_support as G  # noqa: E402
import scena  # noqa: E402
from scena import Box, Ellipse, LinkedAttributeError, Rect, Shape  # noqa: E402
from scena.box import region_frame  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made

P = {"x": 30.0, "y": -12.0, "s": 1.0, "r": 25.0}
DOORS = ("<<", "absorb", "@=")
BOX_KINDS = sorted(k for k in G.KINDS if k.split()[0] == "Box")
# What a Box fills (Box Design, "Fit"): the frame kinds whose box= placement
# is a fill. A Point takes the position only (C7: the Point exception).
FILLS_A_BOX = {"Rect", "Concave", "Ellipse", "Box"}
TAKES_POSITION = {"Point", "Anchor"}
# One source per kind: the first model the registry lists for it.
SOURCES = sorted({k.split()[0]: k for k in reversed(list(G.KINDS))}.values())
# Errors a copy raised from inside: never an author answer.
LEAKS = ("has no attribute", "Unknown ")


def _kind(name):
    return name.split()[0]


def _track(w, obj):
    if not isinstance(obj, Box):       # a Box is a value, not an actor
        w.track(obj)
    return obj


def _has_door(dst, door):
    if door == "absorb":
        return callable(getattr(dst, "absorb", None))
    return True


def _copy(dst, src, door):
    if door == "<<":
        dst << src
    elif door == "absorb":
        dst.absorb(src)
    else:
        dst @= (lambda: src)


def _read(fn):
    out = G.safe(fn)
    return repr(out) if isinstance(out, G.ReadError) else out


def _state(obj):
    """What a refused copy must leave alone: model, inputs, drawing, pose."""
    return tuple(_read(f) for f in (
        lambda: getattr(obj, "model", None),
        lambda: sorted(obj.__dict__.get("_defining_part_names") or ()),
        lambda: [tuple(round(c, 6) for c in q) for q in G.drawn(obj)],
        lambda: G.center_of(obj),
        lambda: (float(obj.angle), obj.flip_x, obj.flip_y),
    ))


def _cell(w, dst_kind, src_kind, door):
    """None when the cell keeps the contract, else what went wrong."""
    with quiet():
        dst = _track(w, G.KINDS[dst_kind](dict(P, x=P["x"] + 37.0)))
        src = _track(w, G.KINDS[src_kind](dict(P)))
    if not _has_door(dst, door):
        return None
    before = _state(dst)
    try:
        with quiet():
            _copy(dst, src, door)
    except AUTHOR_ERRORS as exc:          # a linked target refuses any write
        msg = str(exc)
        if any(s in msg for s in LEAKS):
            return f"leaks {type(exc).__name__}: {msg[:80]}"
        if _state(dst) != before:
            return "refused after a write"
        if isinstance(exc, LinkedAttributeError):
            return "linked"             # the link guard, before the kind rule
        if callable(getattr(dst, "move_by", None)):
            try:
                dst.move_by(1.0, 0.0)
            except Exception as exc2:   # noqa: BLE001
                # A relational target may refuse a move (it is linked); a
                # target left with the source's model breaks instead.
                if not isinstance(exc2, AUTHOR_ERRORS) or any(t in str(exc2) for t in LEAKS):
                    return f"broken after the refusal: {type(exc2).__name__}"
        return "refused"
    except Exception as exc:   # noqa: BLE001
        return f"leaks {type(exc).__name__}: {str(exc)[:80]}"
    return "copied"


class TestEveryKindRegistered(unittest.TestCase):
    def test_the_registry_covers_every_exported_kind(self):
        # The matrix below is only as wide as the registry.
        exported = {
            name for name in scena.__all__
            if isinstance(getattr(scena, name), type)
            and issubclass(getattr(scena, name), (Shape, Box))
            and getattr(scena, name) is not Shape
        }
        registered = {_kind(k) for k in G.KINDS}
        self.assertEqual(exported - registered, set())


class TestBoxIntoEveryKind(unittest.TestCase):
    """Every kind (every model) × every Box model × every copy door."""

    def test_a_box_fills_the_fill_kinds_and_every_other_kind_refuses(self):
        bad = {}
        with fresh_world() as w:
            for dst_kind in sorted(G.KINDS):
                for box_kind in BOX_KINDS:
                    for door in DOORS:
                        out = _cell(w, dst_kind, box_kind, door)
                        if out is None:
                            continue
                        kind = _kind(dst_kind)
                        takes = kind in FILLS_A_BOX or kind in TAKES_POSITION
                        if door == "absorb":
                            takes = False      # absorb destroys a Shape: a Box is none
                        want = "copied" if takes else "refused"
                        if out not in (want, "linked"):
                            bad[f"{dst_kind} {door} {box_kind}"] = out
        self.assertEqual(bad, {})

    def test_the_copy_is_the_box_frame(self):
        bad = []
        with fresh_world() as w, quiet():
            for dst_kind in sorted(k for k in G.KINDS if _kind(k) in FILLS_A_BOX
                                   and not G.is_relational(G.build(k))):
                for box_kind in BOX_KINDS:
                    for door in ("<<", "@="):
                        dst = _track(w, G.KINDS[dst_kind](dict(P, x=80.0)))
                        box = G.KINDS[box_kind](dict(P))
                        _copy(dst, box, door)
                        want = G.frame_corners(*region_frame(box))
                        got = G.frame_corners(*region_frame(dst))
                        if not G.same_set(got, want, 1e-6):
                            bad.append(f"{dst_kind} {door} {box_kind}")
        self.assertEqual(bad, [])


class TestEveryKindIntoEveryKind(unittest.TestCase):
    """Every kind (every model) × one source per kind × every copy door: the
    copy reproduces its source, or refuses cleanly with the target unchanged."""

    def test_no_copy_leaks_or_half_writes(self):
        bad = {}
        with fresh_world() as w:
            for dst_kind in sorted(G.KINDS):
                for src_kind in SOURCES:
                    for door in DOORS:
                        out = _cell(w, dst_kind, src_kind, door)
                        if out not in (None, "copied", "refused", "linked"):
                            bad[f"{dst_kind} {door} {src_kind}"] = out
        self.assertEqual(bad, {})


class TestEllipseFillsABox(unittest.TestCase):
    def test_like_box_placement_then_acts_alike(self):
        hero = Rect(center=(100, 100), width=40, height=20, angle=30)
        for model in sorted(k for k in G.KINDS if _kind(k) == "Ellipse"
                            and not G.is_relational(G.build(k))):     # linked: refuses <<
            for flipped in (False, True):
                with self.subTest(model=model, flipped=flipped), quiet():
                    e = G.KINDS[model](dict(P))
                    if flipped:
                        e.flip_x = True
                    e << hero.box
                    placed = Ellipse(box=hero.box)
                    for o in (e, placed):
                        o.rotate_by(33)
                        o.move_by(5, -2)
                    self.assertTrue(G.same_set([G.xy(e.fp1), G.xy(e.fp2)],
                                               [G.xy(placed.fp1), G.xy(placed.fp2)], 1e-6))
                    self.assertAlmostEqual(float(e.major_axis), float(placed.major_axis))
                    e.destroy()
                    placed.destroy()
        hero.destroy()

    def test_a_whole_link_follows_the_box(self):
        hero = Rect(center=(100, 100), width=40, height=20)
        e = Ellipse(center=(0, 0), width=4, height=2)
        e @= (lambda: hero.box)
        hero.move_by(10, 0)
        hero.width = 50
        self.assertEqual((float(e.center.x), float(e.width)), (110.0, 50.0))
        e.destroy()
        hero.destroy()


class TestRefusalsNameTheFix(unittest.TestCase):
    def test_inscribing_kinds_point_at_box_placement(self):
        from scena import Circle, RegularPolygon, Triangle
        b = Box(center=(100, 100), width=40, height=20)
        for make in (lambda: Circle(center=(0, 0), radius=3),
                     lambda: Triangle(center=(0, 0), radius=30),
                     lambda: RegularPolygon(center=(0, 0), radius=3, n=5)):
            dst = make()
            kind = type(dst).__name__
            with self.subTest(kind=kind):
                with self.assertRaises(TypeError) as cm:
                    dst << b
                self.assertIn(f"{kind}(box=box)", str(cm.exception))
                with self.assertRaises(TypeError) as cm:
                    dst << Rect(center=(0, 0), width=4, height=2)
                self.assertIn(f"{kind}(box=rect.box)", str(cm.exception))
            dst.destroy()

    def test_frame_kinds_point_at_the_frame(self):
        from scena import Circle
        r, c = Rect(center=(0, 0), width=4, height=2), Circle(center=(0, 0), radius=3)
        e = Ellipse(center=(0, 0), width=4, height=2)
        with self.assertRaises(TypeError) as cm:
            r << c
        self.assertIn("rect << circle.box", str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            e << r
        self.assertIn("ellipse << rect.box", str(cm.exception))
        for o in (r, c, e):
            o.destroy()

    def test_a_regular_polygon_refuses_a_triangle(self):
        # A Triangle's base_ratio can make it isosceles (the Square / Rect rule);
        # a Triangle takes a regular triangle.
        from scena import RegularPolygon, Triangle
        rp = RegularPolygon(center=(0, 0), radius=3, n=3)
        with self.assertRaises(TypeError):
            rp << Triangle(center=(5, 5), radius=4, base_ratio=0.5)
        t = Triangle(center=(0, 0), radius=30)
        t << RegularPolygon(center=(5, 5), radius=3, n=3)
        self.assertEqual((float(t.center.x), float(t.radius)), (5.0, 3.0))
        for o in (rp, t):
            o.destroy()


if __name__ == "__main__":
    unittest.main()
