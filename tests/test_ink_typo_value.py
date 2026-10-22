"""The value-aware typo guard on new author fields (Actors Design, "Ink").

Bug class: a one-edit typo of a short property (``bola.colr = "red"``,
``bola.angl = 45``) became an author field nothing reads, so nothing changed on
screen and the author got no clue. The one-edit rule needs a 6+ letter
property, because one edit from ``layer`` / ``owner`` / ``mode`` are real
fields (``laser``, ``owned``, ``modo``). A new name one edit from ``color`` /
``fill`` / ``line`` holding a colour, or from ``alpha`` / ``angle`` / ``scale``
/ ``width`` holding a number, now refuses; any other value makes the field.

    python tests/run_tiers.py focused test_ink_typo_value
"""
from __future__ import annotations

import os
import string
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scena.entity as entity_mod  # noqa: E402
from scena import (  # noqa: E402
    Circle, Color, Entity, Gradient, Line, Polygon, Rect, Text, group, init,
)
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

PAINT_VALUES = ("red", "dark navy", "Light Blue", "#ff0000", (1, 0, 0), (1.0, 0.0, 0.0, 0.5))
NUMBER_VALUES = (45, 2.5)


def _kinds():
    return (
        Circle(center=(10, 10), radius=5),
        Rect(center=(10, 10), width=8, height=6),
        Text("oi"),
        Line(p1=(0, 0), p2=(10, 0)),
        Polygon(points=[(0, 0), (10, 0), (5, 8)]),
    )


def _one_edit_variants(prop: str):
    """Every one-edit spelling of ``prop`` the rule covers: same first letter,
    not a plural, not ``prop`` + digits."""
    letters = string.ascii_lowercase
    out = set()
    for i in range(1, len(prop)):
        out.add(prop[:i] + prop[i + 1:])                       # deletion
        out.update(prop[:i] + c + prop[i + 1:] for c in letters)   # substitution
    for i in range(1, len(prop) + 1):
        out.update(prop[:i] + c + prop[i:] for c in letters)   # insertion
    for i in range(1, len(prop) - 1):
        out.add(prop[:i] + prop[i + 1] + prop[i] + prop[i + 2:])   # adjacent swap
    out.discard(prop)
    out.discard(prop + "s")
    return sorted(out)


def _ink(obj):
    return object.__getattribute__(obj, "_ink") or {}


class TestValueTypoRefuses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_the_reported_case(self):
        bola = Circle(center=(100, 100), radius=20)
        with self.assertRaises(AttributeError) as ctx:
            bola.colr = "red"
        msg = str(ctx.exception)
        self.assertIn("'colr'", msg)
        self.assertIn("Did you mean 'color'?", msg)
        self.assertNotIn("colr", _ink(bola))

    def test_every_one_edit_spelling_with_a_value_of_the_kind_refuses(self):
        for obj in _kinds():
            routes = type(obj)._setattr_route
            for prop, kind in entity_mod._TYPO_VALUE_KINDS.items():
                route = routes.get(prop)
                if not hasattr(type(route), "__set__") \
                        or isinstance(route, entity_mod._RouteRefusal):
                    continue        # the kind has no such property: nothing to mistype
                values = PAINT_VALUES if kind == "paint" else NUMBER_VALUES
                for typo in _one_edit_variants(prop):
                    if typo in routes:
                        continue    # a real name of the kind (its own route answers)
                    for value in values:
                        with self.subTest(kind=type(obj).__name__, typo=typo, value=value):
                            with self.assertRaises(AttributeError):
                                setattr(obj, typo, value)
                            self.assertNotIn(typo, _ink(obj))

    def test_colour_objects_count_as_colours(self):
        c = Circle(center=(10, 10), radius=5)
        for value in (Color("red"), Color(0.2, 0.4, 0.6), Gradient("plasma")):
            with self.subTest(value=value):
                with self.assertRaises(AttributeError) as ctx:
                    c.colr = value
                self.assertIn("'color'", str(ctx.exception))

    def test_inside_setup_and_through_a_group(self):
        class Bola(Circle):
            def setup(self):
                self.angl = 30

        with self.assertRaises(AttributeError) as ctx:
            Bola(center=(10, 10), radius=5)
        self.assertIn("'angle'", str(ctx.exception))
        Circle(center=(10, 10), radius=5, group="typo_bolas")
        with self.assertRaises(AttributeError):
            group["typo_bolas"].fil = "blue"


class TestRealFieldsStayFields(unittest.TestCase):
    """The neighbours that kept the one-edit rule at 6 letters: same names, other kinds of value."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_one_edit_names_with_another_kind_of_value(self):
        c = Circle(center=(10, 10), radius=5)
        laser = Rect(center=(0, 0), width=2, height=8)
        fields = {
            "laser": laser, "later": 3.0, "owned": True, "modal": True,   # 5-letter neighbours
            "lime": 3, "life": 2.0, "link": None, "sale": "promo",         # one edit from a table name
            "angl": "norte", "scal": [1, 2], "colr": 7,                    # typo spelling, wrong kind
            "alpa": True, "widt": False,                                   # bool is not a number here
            "fil": "not a colour name",                                    # strings that are no colour
        }
        for name, value in fields.items():
            with self.subTest(name=name):
                setattr(c, name, value)
                self.assertIs(getattr(c, name), value) if not isinstance(value, (int, float)) \
                    else self.assertEqual(getattr(c, name), value)

    def test_names_the_rule_never_considers(self):
        c = Circle(center=(10, 10), radius=5)
        for name, value in (("color2", "red"), ("fill0", "blue"), ("colors", "red"),
                            ("lines", "red"), ("nome", "Ana"), ("modo", "fuga"),
                            ("tempo", 0), ("ocolr", "red"), ("scales", 2)):
            with self.subTest(name=name):
                setattr(c, name, value)
                self.assertIn(name, _ink(c))

    def test_a_kind_without_the_property_keeps_the_field(self):
        # Entity() draws nothing: ``color`` / ``angle`` are reserved names it
        # stores plain, not properties, so there is nothing to mistype.
        e = Entity()
        self.addCleanup(e.destroy)
        e.colr = "red"
        e.angl = 45
        self.assertEqual(e.colr, "red")
        self.assertEqual(e.angl, 45)

    def test_a_field_made_with_another_kind_takes_any_value_later(self):
        c = Circle(center=(10, 10), radius=5)
        c.lime = 3
        c.lime = "green"            # a rewrite: the guard ran at creation only
        self.assertEqual(c.lime, "green")


class TestCheckRunsAtCreationOnly(unittest.TestCase):
    """No cost on the hot path: a rewrite of a field never enters the guard."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_rewrites_skip_the_guard(self):
        calls = []
        real = entity_mod._check_ink_near_miss

        def counting(*args):
            calls.append(args[1])
            return real(*args)

        entity_mod._check_ink_near_miss = counting
        self.addCleanup(setattr, entity_mod, "_check_ink_near_miss", real)
        c = Circle(center=(10, 10), radius=5)
        for i in range(50):
            c.life = float(i)
        self.assertEqual(calls, ["life"])

    def test_no_fuzzy_colour_lookup(self):
        # ``ColorNames.is_known`` runs the fuzzy matcher (40-240 us per string).
        from scena.color import ColorNames
        real = ColorNames.resolve
        seen = []

        def spy(name):
            seen.append(name)
            return real(name)

        ColorNames.resolve = spy
        self.addCleanup(setattr, ColorNames, "resolve", real)
        self.assertFalse(entity_mod._is_paint_value("not a colour name"))
        self.assertTrue(entity_mod._is_paint_value("dark navy"))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
