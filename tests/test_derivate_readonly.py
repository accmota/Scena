"""
Derivate attributes must be read-only: setting or linking one directly should
raise, while internal derivation (construction, transforms) and outbound
links reading a Derivate attribute as a source keep working.

Run headless:

    python -m unittest tests.test_derivate_readonly -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math

from scena.shapes import Line, Point, Rect
from scena.state import DerivedAttributeError


class TestDerivateAttributesAreReadOnly(unittest.TestCase):
    def test_set_or_link_derivate_raises_across_models(self):
        """Writing/linking a Derivate part with '=' or '@=' raises, in either Rect model."""
        source = Point(1, 1)

        top_left_wh = Rect(top_left=(0, 0), width=100, height=50)
        with self.assertRaises(DerivedAttributeError):
            top_left_wh.p2 = (5, 5)                # Point-typed Derivate, top-level '='
        with self.assertRaises(DerivedAttributeError):
            top_left_wh.center @= source           # Point-typed Derivate, '@='
        with self.assertRaises(DerivedAttributeError):
            top_left_wh.top_right.x = 42            # nested leaf under a Derivate Point, '='
        with self.assertRaises(DerivedAttributeError):
            top_left_wh.top_right["x"] @= lambda: source.x     # nested leaf under a Derivate Point, '@='

        corner_corner = Rect(p1=(0, 0), p2=(10, 10))
        with self.assertRaises(DerivedAttributeError):
            corner_corner.width = 500               # Attribute-typed Derivate flips per model

        # The very same attribute names are perfectly settable/linkable when Defining.
        top_left_wh.width = 999
        corner_corner.p1 = (1, 1)
        corner_corner.p2 @= source
        self.assertEqual(corner_corner.p2.x, 1)

    def test_internal_derivation_and_transforms_unaffected(self):
        """The shape's own machinery must still be able to write its Derivate parts."""
        rect = Rect(top_left=(0, 0), width=100, height=50)
        line = Line(p1=lambda: rect.top_left, p2=lambda: rect.center)  # linking TO a Derivate source: fine

        # Construction already derived center/corners; transforms recompute them again.
        rect.move_by(10, 20)
        rect.rotate_by(math.degrees(0.3))
        rect.scale_by(1.5)

        self.assertEqual(line.p2.x, rect.center.x)
        self.assertEqual(line.p2.y, rect.center.y)



def _vec2_computed_fields():
    """Every Derivate scalar field of Vec2 (``length``, ``angle``, and any new one)."""
    from scena.scenamath import Vec2
    from scena.state import FieldType, ScalarSlot
    return sorted(
        name for name, value in vars(Vec2).items()
        if isinstance(value, ScalarSlot) and value.field_type is FieldType.Derivate
    )


class TestVec2ComputedFieldMessages(unittest.TestCase):
    """``v.length = 5`` said "the shape's current model … construct the shape
    with a different model": a Rect message, no help on a Vec2. Every Vec2
    computed field now names the in-place spelling."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def test_fields_are_found(self):
        self.assertEqual(_vec2_computed_fields(), ["angle", "length"])

    def test_set_names_vec_from_angle(self):
        from scena import Vec2
        for name in _vec2_computed_fields():
            with self.subTest(field=name):
                v = Vec2(3, 4)
                with self.assertRaises(DerivedAttributeError) as cm:
                    setattr(v, name, 7)
                msg = str(cm.exception)
                self.assertIn(f"Vec2.{name} is computed from x and y", msg)
                self.assertIn("v << vec_from_angle(", msg)
                self.assertNotIn("model", msg)
                self.assertEqual((v.x, v.y), (3, 4))

    def test_set_message_uses_the_value_written(self):
        from scena import Vec2
        v = Vec2(3, 4)
        with self.assertRaises(DerivedAttributeError) as cm:
            v.length = 5
        self.assertIn("v << vec_from_angle(v.angle, 5)", str(cm.exception))
        with self.assertRaises(DerivedAttributeError) as cm:
            v.angle = 30
        self.assertIn("v << vec_from_angle(30, v.length)", str(cm.exception))

    def test_link_names_the_whole_vector_link(self):
        from scena import Vec2
        for name in _vec2_computed_fields():
            with self.subTest(field=name):
                v = Vec2(3, 4)
                with self.assertRaises(DerivedAttributeError) as cm:
                    v[name] @= lambda: 5
                msg = str(cm.exception)
                self.assertIn(f"Vec2.{name} is computed from x and y, so it cannot be linked", msg)
                self.assertIn("v @= lambda: vec_from_angle(angle, length)", msg)

    def test_the_suggested_spellings_work(self):
        from scena import Vec2, vec_from_angle
        v = Vec2(3, 4)
        held = v
        v << vec_from_angle(v.angle, 5 * 2)
        self.assertIs(held, v)
        self.assertAlmostEqual(v.length, 10)
        self.assertAlmostEqual(v.x, 6)
        v << vec_from_angle(90, v.length)
        self.assertAlmostEqual(v.angle, 90)
        self.assertAlmostEqual(v.length, 10)

    def test_shapes_word_their_own_message(self):
        r = Rect(top_left=(0, 0), width=100, height=50)
        with self.assertRaises(DerivedAttributeError) as cm:
            r.center = (1, 1)
        self.assertIn("rect.move_to(1, 1, about=rect.center)", str(cm.exception))


class TestLinkedVec2ComputedFieldsFollow(unittest.TestCase):
    """A Vec2 linked whole (``v @= lambda: …``) stores x / y on read through
    ``_takein_impl`` (Reactive Design, "Pull stores raw"), which does not run
    ``_update_impl``: ``length`` / ``angle`` read 0.0 (never computed) or
    their value from before the link, and a link reading ``w.length`` saw the
    same stale value."""

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def _sources(self):
        from scena import Vec2, vec_from_angle, st
        st.cs_heading = 30
        return st, {
            "lambda -> Vec2": lambda: vec_from_angle(st.cs_heading, 10),
            "lambda -> tuple": lambda: (10 * math.cos(math.radians(st.cs_heading)),
                                        10 * math.sin(math.radians(st.cs_heading))),
        }

    def test_read_before_and_after_the_link(self):
        from scena import Vec2
        st, sources = self._sources()
        for label, formula in sources.items():
            for read_first in (False, True):
                for name in _vec2_computed_fields():
                    with self.subTest(source=label, read_first=read_first, field=name):
                        st.cs_heading = 30
                        v = Vec2(1, 0)
                        if read_first:
                            v.length, v.angle
                        v @= formula
                        expect = {"length": 10.0, "angle": 30.0}
                        self.assertAlmostEqual(getattr(v, name), expect[name])
                        st.cs_heading = 90
                        expect["angle"] = 90.0
                        self.assertAlmostEqual(getattr(v, name), expect[name])
                        v.unlink()

    def test_a_link_reading_length_follows(self):
        from scena import Vec2
        st, _ = self._sources()
        st.cs_side = 0
        w = Vec2(0, 0)
        w @= lambda: (st.cs_side, 4)
        z = Vec2(lambda: (w.length, w.angle))
        self.assertAlmostEqual(z.x, 4)
        st.cs_side = 3
        self.assertAlmostEqual(w.length, 5)
        self.assertAlmostEqual(z.x, 5)
        self.assertAlmostEqual(z.y, math.degrees(math.atan2(4, 3)))


class TestDerivedFieldMessages(unittest.TestCase):
    """Every computed field of every model, every write form, says what it is
    computed from and a fix that works. The old text ("the shape's current
    model … Construct the shape with a different model") fit no Text, Track
    or Box, and named no way to move a computed point; ``<<`` on a computed
    point did not even raise (it overwrote the point; the shape stayed)."""

    OLD = "shape's current model"

    @classmethod
    def setUpClass(cls):
        from hypothesis_support import boot
        boot()

    def _computed_fields(self):
        import geometry_support as G
        from scena.state import ContainerSlot, ScalarSlot
        for kind in G.KINDS:
            obj = G.build(kind)
            if not hasattr(obj, "_field_slots"):
                continue
            if kind.endswith("reversed"):
                continue        # a view forwards its writes to the host (Tracks Design)
            for name, slot in sorted(obj._field_slots().items()):
                if not obj._field_is_derivate(name, slot) or name == "angle":
                    continue    # a derived heading turns the actor (rotate_to), by design
                point = isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Point"
                if isinstance(slot, ContainerSlot) or isinstance(slot, ScalarSlot):
                    yield kind, name, isinstance(slot, ContainerSlot), point

    def _forms(self, part):
        if part:
            return {
                "=": lambda o, n: setattr(o, n, (1, 2)),
                ".x =": lambda o, n: setattr(getattr(o, n), "x", 1),
                "@=": lambda o, n: getattr(o, n).__imatmul__(lambda: (1, 2)),
                "<<": lambda o, n: getattr(o, n).__lshift__((1, 2)),
            }
        return {
            "=": lambda o, n: setattr(o, n, 5),
            "@=": lambda o, n: o[n].__imatmul__(lambda: 5),
        }

    def test_every_form_raises_with_the_new_wording(self):
        import geometry_support as G
        import inspect
        import re
        checked = 0
        for kind, name, part, point in self._computed_fields():
            for form, write in self._forms(part).items():
                with self.subTest(kind=kind, field=name, form=form):
                    obj = G.build(kind)
                    before = getattr(obj, name)
                    before = (before.x, before.y) if part else before
                    try:
                        write(obj, name)
                    except DerivedAttributeError as e:
                        msg = str(e)
                    except TypeError as e:          # @= of a constant: no source to link
                        self.assertIn("no reactive sources", str(e))
                        continue
                    else:
                        self.fail(f"{kind}.{name} {form} did not raise")
                    self.assertNotIn(self.OLD, msg)
                    self.assertIn(f".{name} is", msg)
                    after = getattr(obj, name)
                    self.assertEqual((after.x, after.y) if part else after, before)
                    for kw in re.findall(r"with (\w+)=:", msg):
                        self.assertIn(kw, inspect.signature(type(obj)).parameters)
                    checked += 1
        self.assertGreater(checked, 500)

    # Kinds whose suggested move is wrong (shrink-only: a fixed entry fails).
    KNOWN_BAD_HINT = {
        "Line parallel_dist": "GR1 (graphics review, batch 8): move projects onto the normal",
        "Line tangent_point": "SB1 (batch 8): the move re-solves the tangent",
        "Line tangent_angle": "GR2 (batch 9): the hint suggests move_to, which a linked p1 refuses",
        "Ellipse from_rect": "GR2 (batch 9): the hint suggests move_to, which a linked center refuses",
    }

    def test_the_suggested_move_lands_the_point(self):
        import geometry_support as G
        import re
        checked = 0
        for kind, name, part, point in self._computed_fields():
            if not point:
                continue
            if kind in self.KNOWN_BAD_HINT:
                continue                 # pinned by test_known_bad_hints_still_fail
            for form, value in (("=", (7, -3)), (".x =", 7)):
                with self.subTest(kind=kind, field=name, form=form):
                    obj = G.build(kind)
                    try:
                        if form == "=":
                            setattr(obj, name, value)
                        else:
                            setattr(getattr(obj, name), "x", value)
                    except DerivedAttributeError as e:
                        msg = str(e)
                    found = re.search(r"write (\w+)\.(move_to\(.*\))\.$", msg)
                    if found is None:
                        self.assertNotIn("move_to", msg)     # a value (Box) or the Track cursor
                        continue
                    eval(f"obj.{found.group(2)}", {"obj": obj, found.group(1): obj})
                    p = getattr(obj, name)
                    if form == "=":
                        self.assertAlmostEqual(p.x, 7, places=6)
                        self.assertAlmostEqual(p.y, -3, places=6)
                    else:
                        self.assertAlmostEqual(p.x, 7, places=6)
                    checked += 1
        self.assertGreater(checked, 150)

    def test_known_bad_hints_still_fail(self):
        import geometry_support as G
        import re
        for kind in self.KNOWN_BAD_HINT:
            with self.subTest(kind=kind):
                obj = G.build(kind)
                landed = True
                for name in ("center", "p2", "fp1"):
                    if name not in obj._field_slots() or not obj._field_is_derivate(name, obj._field_slots()[name]):
                        continue
                    try:
                        setattr(obj, name, (7, -3))
                    except DerivedAttributeError as e:
                        found = re.search(r"write (\w+)\.(move_to\(.*\))\.$", str(e))
                    if found is None:
                        continue
                    try:
                        eval(f"obj.{found.group(2)}", {"obj": obj, found.group(1): obj})
                        p = getattr(obj, name)
                        landed = landed and abs(p.x - 7) < 1e-6 and abs(p.y + 3) < 1e-6
                    except Exception:  # noqa: BLE001  (the hint's move is refused)
                        landed = False
                    break
                self.assertFalse(landed, f"fixed: remove {kind} from KNOWN_BAD_HINT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
