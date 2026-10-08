"""The heading is ``angle`` (Shapes Design — Geometry contract).

``angle`` is a field on every Graphic. Setting it — ``=``, ``["angle"] @=``,
the constructor keyword or a ``tween``, all the same — keeps the model's other
inputs, so the point the shape was placed by stays. If the heading is derived
from the placement points (Rect spine, Ellipse foci, a p1/p2 Line, a Circle
placed by its rim, a free Polygon), setting it is ``rotate_to`` about the
center, and a link drives ``rotate_to``. The verbs ``rotate_to`` /
``rotate_by`` always turn the whole shape about the center (or ``about=``).
``rotation`` is retired on Graphics: every spelling raises with a hint and
nothing becomes ink.

    python -m unittest tests.test_angle_field -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geometry_support as G  # noqa: E402
from scena import (  # noqa: E402
    Circle, Ellipse, Line, Point, Polygon, Rect, RegularPolygon, Sprite, Square, State,
    Svg, Text, Track,
)

INPUT_MODELS = {
    # name: (builder(**extra), the part that stays fixed)
    "Rect center_wh": (lambda **k: Rect(center=(3, -2), width=40, height=16, **k), "center"),
    "Rect top_left_wh": (lambda **k: Rect(top_left=(3, -2), width=40, height=16, **k), "top_left"),
    "Rect point_vec": (lambda **k: Rect(p1=(3, -2), vec=(40, 16), **k), "p1"),
    "Square top_left": (lambda **k: Square(top_left=(3, -2), length=20, **k), "top_left"),
    "Ellipse center_wh": (lambda **k: Ellipse(center=(3, -2), width=30, height=12, **k), "center"),
    "RegularPolygon center": (lambda **k: RegularPolygon(center=(3, -2), radius=6, n=5, **k), "center"),
    "RegularPolygon vertex": (lambda **k: RegularPolygon(vertex=(3, -2), side=6, n=5, **k), "vertex"),
    "Line center_length": (lambda **k: Line(center=(3, -2), length=30, **{"angle": 0, **k}), "center"),
    "Line point_angle_length": (lambda **k: Line(p1=(3, -2), length=30, **{"angle": 0, **k}), "p1"),
    "Text top_left": (lambda **k: Text("geo", top_left=(3, -2), layer="default", **k), "top_left"),
    "Text top_right": (lambda **k: Text("geo", top_right=(3, -2), layer="default", **k), "top_right"),
}

DERIVED_MODELS = {
    "Rect spine": lambda: Rect(p1=(3, -2), p2=(43, 4), height=12, anchor="cap"),
    "Ellipse foci": lambda: Ellipse(fp1=(-5, -2), fp2=(11, 1), major_axis=24),
    "Line p1 p2": lambda: Line(p1=(3, -2), p2=(43, 4)),
    "Circle by rim": lambda: Circle(p1=(3, -2), p2=(23, -2)),
}


class TestAngleIsAnInput(unittest.TestCase):
    def test_setting_keeps_the_placement_point(self):
        for name, (build, fixed) in INPUT_MODELS.items():
            with self.subTest(model=name):
                shape = build()
                before = G.xy(getattr(shape, fixed))
                shape.angle = 50
                self.assertTrue(G.close(G.xy(getattr(shape, fixed)), before, 1e-9))
                self.assertAlmostEqual(float(shape.angle), 50.0)

    def test_equals_link_and_constructor_agree(self):
        st = State()
        st.r = 50.0
        for name, (build, _fixed) in INPUT_MODELS.items():
            with self.subTest(model=name):
                a, b, c = build(), build(), build(angle=50)
                a.angle = 50
                b["angle"] @= lambda: st.r
                self.assertTrue(G.same_set(G.drawn(a), G.drawn(b)))
                self.assertTrue(G.same_set(G.drawn(a), G.drawn(c)))

    def test_the_verbs_still_turn_about_the_center(self):
        for name, (build, _fixed) in INPUT_MODELS.items():
            with self.subTest(model=name):
                shape = build()
                c = G.center_of(shape)
                shape.rotate_to(float(shape.angle) + 50)
                self.assertTrue(G.close(G.center_of(shape), c, 1e-9))


class TestDerivedAngleTurnsTheShape(unittest.TestCase):
    """Rect spine / Ellipse foci used to raise DerivedAttributeError on set and link."""

    def test_setting_is_rotate_to_about_the_center(self):
        for name, build in DERIVED_MODELS.items():
            with self.subTest(model=name):
                a, b = build(), build()
                a.angle = 70
                b.rotate_to(70)
                self.assertAlmostEqual(float(a.angle), 70.0)
                self.assertTrue(G.same_set(G.drawn(a), G.drawn(b)))
                self.assertTrue(G.close(G.center_of(a), G.center_of(build()), 1e-9))

    def test_a_link_drives_rotate_to_and_unlinks_cleanly(self):
        st = State()
        for name, build in DERIVED_MODELS.items():
            with self.subTest(model=name):
                st.a = 10.0
                shape = build()
                c = G.center_of(shape)
                shape["angle"] @= lambda: st.a
                self.assertTrue(shape["angle"].is_linked)
                self.assertAlmostEqual(float(shape.angle), 10.0)
                st.a = 45.0
                self.assertAlmostEqual(float(shape.angle), 45.0)
                self.assertAlmostEqual(shape._rotation_value() % 360.0, 45.0)
                self.assertTrue(G.close(G.center_of(shape), c, 1e-9))
                # Used as a formula source, the link survives.
                probe = Line(p1=(0, 0), p2=(1, 1))
                probe["p2"] @= lambda: (float(shape.angle), 0.0)
                self.assertAlmostEqual(float(probe.p2.x), 45.0)
                self.assertTrue(shape["angle"].is_linked)
                shape["angle"].unlink()
                self.assertFalse(shape["angle"].is_linked)
                self.assertAlmostEqual(float(shape.angle), 45.0)
                probe.destroy()
                shape.destroy()



class TestAngleIsTheHeading(unittest.TestCase):
    """``angle`` reads the heading on every kind (G14)."""

    def test_line_angle_is_its_direction(self):
        import math
        line = Line(p1=(0, 0), p2=(30, 12))
        self.assertAlmostEqual(float(line.angle), math.degrees(math.atan2(12, 30)))
        line.rotate_to(50)
        self.assertAlmostEqual(float(line.angle), 50.0)       # read 33 before
        line.flip_x = True
        self.assertAlmostEqual(float(line.angle) % 360.0, 130.0)

    def test_line_full_turns_still_accumulate(self):
        line = Line(p1=(0, 0), p2=(30, 12))
        r0 = float(line.angle)
        line.rotate_by(720)
        self.assertAlmostEqual(float(line.angle), r0 + 720.0, places=6)

    def test_derived_heading_does_not_depend_on_what_was_read(self):
        # The same point writes read the same heading whichever reads came
        # between them. Rect spine wrote its heading back into the turn
        # reference on every update it ran, so a warm rect counted a turn a
        # cold one did not (204.78 vs -155.22; the reactive matrix found it).
        import itertools
        ends = {"Ellipse foci": ("fp1", "fp2")}
        # p2 goes round p1, then p1 jumps across: the direction crosses ±180.
        writes = [("b", (-14.0, 5.0)), ("a", (25.0, 23.0)), ("b", (-30.0, -9.0)),
                  ("a", (40.0, -20.0)), ("b", (-6.0, 30.0))]
        for name, build in DERIVED_MODELS.items():
            a_name, b_name = ends.get(name, ("p1", "p2"))
            seen = {}
            for reads in itertools.product((False, True), repeat=len(writes) + 1):
                shape = build()
                for (end, xy), read in zip(writes, reads):
                    if read:
                        shape.angle                 # warms the Derivate heading
                    getattr(shape, a_name if end == "a" else b_name)._takein(xy)
                if reads[-1]:
                    shape.center
                seen[reads] = round(float(shape.angle), 6)
                shape.destroy()
            with self.subTest(model=name):
                self.assertEqual(len(set(seen.values())), 1, seen)

    def test_point_writes_keep_the_turns_the_verbs_counted(self):
        # Only verbs move the turn reference: after rotate_by(720) a point
        # write reads the new direction near +720, warm or cold.
        for name, build in DERIVED_MODELS.items():
            for warm in (False, True):
                with self.subTest(model=name, warm=warm):
                    shape = build()
                    if warm:
                        shape.angle
                    r0 = float(shape.angle)
                    shape.rotate_by(720)
                    self.assertAlmostEqual(float(shape.angle), r0 + 720.0, places=6)
                    shape.rotate_by(5)                  # a turn, then a nudge back
                    shape.rotate_by(-5)
                    self.assertAlmostEqual(float(shape.angle), r0 + 720.0, places=6)
                    shape.destroy()

    def test_flips_keep_the_turns_on_every_kind(self):
        # flip_x reads 180 − θ and flip_y −θ with the full turns kept, and the
        # flip back restores θ. A Rect spine unwrapped the mirrored heading to
        # the old turn reference: -690 flipped to -570, not 870.
        builds = dict(DERIVED_MODELS)
        builds.update({name: build for name, (build, _fixed) in INPUT_MODELS.items()
                       if not name.startswith("Text")})
        for name, build in builds.items():
            for axis in ("x", "y"):
                for warm in (False, True):
                    with self.subTest(model=name, axis=axis, warm=warm):
                        shape = build()
                        if warm:
                            shape.angle
                        shape.rotate_by(-720)
                        shape.rotate_by(30)
                        r = float(shape.angle)
                        setattr(shape, "flip_" + axis, True)
                        want = (180.0 - r) if axis == "x" else -r
                        self.assertAlmostEqual(float(shape.angle), want, places=6)
                        setattr(shape, "flip_" + axis, False)
                        self.assertAlmostEqual(float(shape.angle), r, places=6)
                        shape.destroy()

    def test_flips_mirror_a_pose_heading(self):
        from scena import Point, Polygon
        for obj in (Point(1, 2), Polygon(points=[(0, 0), (4, 0), (4, 3)])):
            with self.subTest(kind=type(obj).__name__):
                obj.rotate_by(30)
                r = float(obj.angle)
                obj.flip_x = True
                self.assertAlmostEqual(float(obj.angle), 180.0 - r)
                obj.flip_x = False
                self.assertAlmostEqual(float(obj.angle), r)
                obj.flip_y = True
                self.assertAlmostEqual(float(obj.angle), -r)



class TestAngleFormulasStayFresh(unittest.TestCase):
    """A formula that names ``shape.angle`` re-runs on every change of the heading.

    G18: a heading arrow ``p2=lambda: …shape.angle…`` stayed put when a
    ``center=, radius=`` Circle flipped (or took ``angle =`` / an ``angle``
    link), and when a Line's endpoint was written: ``angle`` is read from
    the geometry there, and only the pose verbs marked its property anchor
    dirty. The probe is read bare (what draw reads), not pulled — a pulled
    read re-evaluates and hides a formula that was never told to.
    """

    def _probe_after(self, obj, act):
        from scena.state import LinkedAttributeError, get_scena_system
        probe = Line(p1=(0, 0), p2=lambda: (obj.angle, 0.0))
        get_scena_system().flush()
        try:
            act()
        except LinkedAttributeError:
            probe.destroy()
            if G.is_relational(obj):
                return None             # a linked input refuses: nothing to follow
            raise
        get_scena_system().flush()
        got = probe._segment_xy()[2]
        probe.destroy()
        return got, float(obj.angle)

    def _actions(self, obj):
        acts = [("rotate_by", lambda: obj.rotate_by(25)), ("angle =", lambda: setattr(obj, "angle", 40))]
        if G.can_flip(obj):
            acts += [("flip_x", lambda: setattr(obj, "flip_x", not obj.flip_x)),
                     ("flip_y", lambda: setattr(obj, "flip_y", not obj.flip_y))]
        return acts

    def test_every_kind_every_heading_change(self):
        from hypothesis_support import fresh_world
        pose = {"x": 3.0, "y": -2.0, "s": 1.0, "r": 20.0}
        with fresh_world() as w:
            for kind, build in sorted(G.KINDS.items()):
                obj = build(dict(pose))
                if not hasattr(type(obj), "angle") or kind.startswith("Box"):
                    continue
                w.track(obj)
                for name, act in self._actions(obj):
                    with self.subTest(kind=kind, change=name):
                        res = self._probe_after(obj, act)
                        if res is not None:
                            self.assertAlmostEqual(res[0], res[1], places=9)

    def test_geometry_writes_and_links_reach_the_heading(self):
        st = State()
        st.a = 5.0
        cases = [
            ("Circle angle =", Circle(center=(0, 0), radius=5, angle=10), lambda o: setattr(o, "angle", 77)),
            ("Circle angle link", Circle(center=(0, 0), radius=5, angle=lambda: st.a), lambda o: setattr(st, "a", 50.0)),
            ("Circle p1 write", Circle(p1=(0, 0), p2=(10, 0)), lambda o: setattr(o, "p1", (5, 5))),
            ("Line p2 write", Line(p1=(0, 0), p2=(10, 0)), lambda o: setattr(o, "p2", (0, 10))),
            ("Line p1 write", Line(p1=(0, 0), p2=(10, 0)), lambda o: setattr(o, "p1", (10, 10))),
            ("Rect spine p2 write", Rect(p1=(0, 0), p2=(10, 0), height=4, anchor="cap"), lambda o: setattr(o, "p2", (0, 10))),
            ("Ellipse fp2 write", Ellipse(fp1=(0, 0), fp2=(10, 0), major_axis=20), lambda o: setattr(o, "fp2", (0, 10))),
        ]
        for name, obj, act in cases:
            with self.subTest(case=name):
                got, want = self._probe_after(obj, lambda o=obj, a=act: a(o))
                self.assertAlmostEqual(got, want, places=9)
                obj.destroy()


def _graphic_kinds():
    """Every Graphic kind in the contract registry (Box is not a Graphic)."""
    return {k: b for k, b in sorted(G.KINDS.items()) if not k.startswith("Box")}


_POSE = {"x": 3.0, "y": -2.0, "s": 1.0, "r": 20.0}


class TestRotationIsRetired(unittest.TestCase):
    """``rotation`` raises on every Graphic — read, write, link, constructor.

    The bug class: a removed or reserved pose name that is accepted and quietly
    becomes ink (before the rename, ``rect.angle = 30`` did exactly that on a
    Rect: a custom field, and the rect did not turn).
    """

    def test_every_spelling_raises_on_every_kind(self):
        from hypothesis_support import fresh_world
        with fresh_world() as w:
            for kind, build in _graphic_kinds().items():
                obj = w.track(build(dict(_POSE)))
                with self.subTest(kind=kind):
                    for act in (lambda: obj.rotation,
                                lambda: setattr(obj, "rotation", 10),
                                lambda: obj["rotation"]):
                        with self.assertRaises(AttributeError) as ctx:
                            act()
                        self.assertIn("angle", str(ctx.exception))
                    self.assertFalse(hasattr(obj, "rotation"))
                    self.assertNotIn("rotation", obj.__dict__.get("_ink") or {})

    def test_the_hint_names_no_private_field(self):
        import traceback
        try:
            Rect(center=(0, 0), width=4, height=2).rotation
        except AttributeError as exc:
            shown = "".join(traceback.format_exception_only(exc))
        self.assertNotIn("_rotation", shown)

    def test_constructors_name_the_fix(self):
        builds = {
            "Rect": lambda: Rect(center=(0, 0), width=4, height=2, rotation=5),
            "Line": lambda: Line(center=(0, 0), length=4, rotation=5),
            "Circle": lambda: Circle(center=(0, 0), radius=4, rotation=5),
            "Polygon": lambda: Polygon(points=[(0, 0), (4, 0), (2, 3)], rotation=5),
            "Sprite": lambda: Sprite(rotation=5),
            "Svg": lambda: Svg(rotation=5),
            "Text": lambda: Text("a", center=(0, 0), rotation=5),
            "Track": lambda: Track(points=[(0, 0), (4, 0)], rotation=5),
        }
        for kind, build in builds.items():
            with self.subTest(kind=kind):
                with self.assertRaises(TypeError) as ctx:
                    build()
                self.assertIn("angle", str(ctx.exception))

    def test_near_misses_of_rotation_and_angle_raise(self):
        r = Rect(center=(0, 0), width=4, height=2)
        for typo in ("rotaton", "rotations", "angel"):
            with self.subTest(typo=typo):
                with self.assertRaises(AttributeError) as ctx:
                    setattr(r, typo, 30)
                self.assertIn("angle", str(ctx.exception))

    def test_no_reserved_name_becomes_ink(self):
        """Every reserved pose / paint name and every retired name, on every kind:
        a write is either applied or refused — never stored as ink."""
        from hypothesis_support import fresh_world
        from scena.entity import _INK_RESERVED
        names = sorted(set(_INK_RESERVED) | {"rotation"})
        with fresh_world() as w:
            for kind, build in _graphic_kinds().items():
                obj = w.track(build(dict(_POSE)))
                for name in names:
                    try:
                        setattr(obj, name, 1.0)
                    except Exception:  # noqa: BLE001 — a refusal is fine
                        pass
                    if not obj:
                        obj = w.track(build(dict(_POSE)))   # a write destroyed or parked it
                        continue
                    with self.subTest(kind=kind, name=name):
                        self.assertNotIn(name, obj.__dict__.get("_ink") or {})


class TestRefusedWritesChangeNothing(unittest.TestCase):
    """A reserved-name write that raises must leave the object as it was.

    The bug: ``circle.owner = 1.0`` stored the float, then failed in
    ``_add_parts``. The circle now read as a part, so ``destroy()`` refused it
    and it outlived its test — the deep tier's serial pass then crashed six
    unrelated draw tests on it. Whole class: every kind, every reserved name.
    """

    def test_owner_junk_is_refused_before_it_is_stored(self):
        c = Circle(center=(0, 0), radius=4)
        try:
            for junk in (1.0, "rect", (1, 2), object()):
                with self.subTest(junk=type(junk).__name__):
                    with self.assertRaises(TypeError) as ctx:
                        c.owner = junk
                    self.assertIn("owner", str(ctx.exception))
                    self.assertIsNone(c.owner)
        finally:
            c.destroy()
        self.assertFalse(c.is_alive)

    def test_parts_cannot_be_rebound(self):
        c = Circle(center=(0, 0), radius=4)
        try:
            before = c.parts
            with self.assertRaises(TypeError) as ctx:
                c.parts = 1.0
            self.assertIn("read-only", str(ctx.exception))
            self.assertIs(c.parts, before)
        finally:
            c.destroy()
        self.assertFalse(c.is_alive)

    def test_every_kind_stays_destroyable_after_any_write(self):
        """Applied or refused, a junk write never strands the object."""
        from hypothesis_support import quiet
        from scena.entity import _INK_RESERVED
        names = sorted(set(_INK_RESERVED) | {"rotation"})
        for kind, build in _graphic_kinds().items():
            for name in names:
                with quiet():
                    obj = build(dict(_POSE))
                    try:
                        setattr(obj, name, 1.0)
                    except Exception:  # noqa: BLE001 — refusals are fine
                        pass
                    if not obj:          # the write destroyed or parked it
                        continue
                    with self.subTest(kind=kind, name=name):
                        try:
                            obj.destroy()
                        except Exception as exc:  # noqa: BLE001
                            self.fail(f"{name} = 1.0 left {kind} "
                                      f"undestroyable: {exc!r}")
                        self.assertFalse(obj.is_alive)


# Kinds whose heading verbs are known wrong (shrink-only: a fixed entry fails).
KNOWN_HEADING = {}


class TestAngleWorksOnEveryKind(unittest.TestCase):
    def _reads(self, kind, got, want):
        if kind in KNOWN_HEADING:
            self.assertNotAlmostEqual(got, want, places=6, msg=f"fixed: remove {kind} from KNOWN_HEADING")
        else:
            self.assertAlmostEqual(got, want, places=6)

    def test_setting_angle_reads_back(self):
        """``x.angle = v`` turns every kind (the old ``rect.angle`` was a silent no-op)."""
        from hypothesis_support import fresh_world
        with fresh_world() as w:
            for kind, build in _graphic_kinds().items():
                obj = w.track(build(dict(_POSE)))
                with self.subTest(kind=kind):
                    want = float(obj.angle) + 30.0
                    try:
                        obj.angle = want
                    except Exception as exc:  # noqa: BLE001
                        # Only a linked input may refuse (parallel / tangent / FROM_RECT).
                        self.assertIn("link", str(exc).lower(), kind)
                        continue
                    self._reads(kind, float(obj.angle), want)

    def test_full_turns_accumulate(self):
        from hypothesis_support import fresh_world
        with fresh_world() as w:
            for kind, build in _graphic_kinds().items():
                obj = w.track(build(dict(_POSE)))
                with self.subTest(kind=kind):
                    a0 = float(obj.angle)
                    try:
                        obj.rotate_by(400)
                    except Exception as exc:  # noqa: BLE001
                        self.assertIn("link", str(exc).lower(), kind)
                        continue
                    self._reads(kind, float(obj.angle), a0 + 400.0)

    def test_p1_p2_line_keeps_full_turns(self):
        line = Line(p1=(0, 0), p2=(10, 0))
        line.rotate_by(400)
        self.assertAlmostEqual(float(line.angle), 400.0)     # read 40 before

    def test_line_clone_keeps_the_turn_count(self):
        for line in (Line(center=(0, 0), length=40, angle=290),
                     Line(p1=(0, 0), length=40, angle=290)):
            with self.subTest(model=line.model.name):
                self.assertAlmostEqual(float(line.clone().angle), 290.0)


class TestLineTangent(unittest.TestCase):
    def test_heading_is_at_angle_plus_90(self):
        c = Circle(center=(0, 0), radius=10)
        line = Line(circle=c, at_angle=0, length=20)
        self.assertAlmostEqual(float(line.angle), 90.0)
        self.assertTrue(G.close(G.xy(line.p1), (10.0, 0.0), 1e-9))

    def test_setting_angle_reads_back(self):
        """It read 240 after ``rotation = 150``: rotate_to measured from the position."""
        c = Circle(center=(0, 0), radius=10)
        line = Line(circle=c, at_angle=0, length=20)
        line.angle = 150
        self.assertAlmostEqual(float(line.angle), 150.0)
        self.assertAlmostEqual(float(line.at_angle), 60.0)
        line.rotate_to(30)
        self.assertAlmostEqual(float(line.angle), 30.0)

    def test_turning_keeps_it_tangent(self):
        import math
        c = Circle(center=(0, 0), radius=10)
        line = Line(circle=c, at_angle=0, length=20)
        line.rotate_by(70)
        x1, y1 = G.xy(line.p1)
        self.assertAlmostEqual(math.hypot(x1, y1), 10.0)
        x2, y2 = G.xy(line.p2)
        self.assertAlmostEqual((x2 - x1) * x1 + (y2 - y1) * y1, 0.0, places=6)

    def test_angle_keyword_names_at_angle(self):
        c = Circle(center=(0, 0), radius=10)
        with self.assertRaises(TypeError) as ctx:
            Line(circle=c, angle=0, length=20)
        self.assertIn("at_angle", str(ctx.exception))
        line = c.tangent_line_from_angle(at_angle=0, size=20)
        self.assertAlmostEqual(float(line.angle), 90.0)


class TestConstructorAngle(unittest.TestCase):
    def test_sprite_and_svg(self):
        self.assertAlmostEqual(float(Sprite(angle=45).angle), 45.0)
        self.assertAlmostEqual(float(Svg(angle=45).angle), 45.0)
        nave = Sprite(art_angle=90)
        self.assertAlmostEqual(float(nave.angle), float(nave.rest_heading))
        self.assertAlmostEqual(float(nave.clone().angle), 90.0)
        st = State()
        st.a = 10.0
        s = Sprite(angle=lambda: st.a)
        st.a = 70.0
        self.assertAlmostEqual(float(s.angle), 70.0)

    def test_text_keeps_its_anchor(self):
        t = Text("geo", top_left=(3, -2), layer="default", angle=30)
        self.assertAlmostEqual(float(t.angle), 30.0)
        self.assertTrue(G.close(G.xy(t.top_left), (3.0, -2.0), 1e-9))
        c = Text("geo", center=(3, -2), angle=30)
        self.assertTrue(G.close(G.xy(c.center), (3.0, -2.0), 1e-9))

    def test_track_line_angle_is_its_heading(self):
        import math
        t = Track.line(length=40, angle=30, p1=(0, 0))
        self.assertAlmostEqual(float(t.angle), 30.0)
        self.assertAlmostEqual(t.angle_at(0.5), 30.0)
        self.assertTrue(G.close(t.at(0), (0.0, 0.0), 1e-9))
        end = (40 * math.cos(math.radians(30)), 40 * math.sin(math.radians(30)))
        self.assertTrue(G.close(t.at(1), end, 1e-9))
        self.assertAlmostEqual(float(Track.shuttle(length=40, angle=30).angle), 30.0)


if __name__ == "__main__":
    unittest.main()
