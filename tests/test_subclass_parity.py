"""Family parity: what an author subclass may do, every exported family answers alike.

Class of bugs (Testing Design, "What the game system tests taught"): a family
implements a shared subclass feature its own way, or not at all, and each
family's tests only ask about that family's own way.

* AC2: ``class Energia(Orb, radius=16)`` raised Python's "takes no keyword
  arguments" while Shape and Sprite take class keywords; the probe this
  module started from found nine more families with the same raw error
  (Text, the widgets, Entity, Endless).
* AC6: ``on_collide`` written as a method got ``other`` = itself.
* AC11: an object whose own field reads the object warned on destroy.
* AC1: an author class outlived the program (``test_author_class_lifetime``
  checks the caching paths; here every family's subclass is collected).

Every exported ``Entity`` class (``scena.__all__``) is subclassed in an
author module and asked the same questions. A family that cannot answer one
is listed with its reason; a stale entry fails.

    python tests/run_tiers.py focused test_subclass_parity
"""
from __future__ import annotations

import gc
import inspect
import os
import sys
import unittest
import warnings
import weakref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402
from scena import Rect  # noqa: E402
from scena.entity import Entity  # noqa: E402
from hypothesis_support import leak_message  # noqa: E402
from system_support import SystemTestCase, full_collect  # noqa: E402

AUTHOR_MODULE = "author_game"

# Families that are not instantiated as author subclasses here, with the reason.
NOT_SUBCLASSED = {
    "Act": "not an actor: test_act (class keywords refused with its own message)",
    "Shape": "abstract: every concrete shape kind is checked",
}

# Kinds whose instances never collide, so the collide-method question has no answer.
NO_CONTACT = {
    "Button": "a ui widget: collidable is refused (TypeError)",
    "TextInput": "a ui widget: collidable is refused (TypeError)",
    "DropDown": "a ui widget: collidable is refused (TypeError)",
    "Slider": "a ui widget: collidable is refused (TypeError)",
    "CheckBox": "a ui widget: collidable is refused (TypeError)",
    "Menu": "a ui widget: collidable is refused (TypeError)",
    "SpriteButton": "on the ui layer: collidable is refused (UiLayerError)",
    "Text": "a bare Text is on the ui layer: collidable is refused (UiLayerError)",
    "Entity": "no geometry: nothing to touch",
    "Endless": "a layer feeder, not a body",
    "SpatialFx": "the bare base has no domain: a kind defines _domain_aabb / _collision_specs",
}

# Open findings this guard pins (shrink-only: an entry that passes fails).
KNOWN_SELF_READ = {
    "Polygon": "AC14 (a documented limit): an own field cannot read the polygon's center, a "
               "computed point of the whole polygon, the new field included; the refusal says so",
}

# Kinds whose custom fields cannot be linked with ``obj["field"] @=``.
NO_INK_LINK = {
    "Point": "custom fields on a Point are plain attributes; its bracket fields are its own (x, y)",
    "Anchor": "no inbound links by design (Guia: Anchor, 'Sem ligação de entrada')",
}


def kinds():
    out = []
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) and issubclass(obj, Entity) and name not in NOT_SUBCLASSED:
            out.append(obj)
    return out


def author_subclass(kind, body=None, **class_kw):
    ns = {"__module__": AUTHOR_MODULE}
    ns.update(body or {})
    return type("Meu" + kind.__name__, (kind,), ns, **class_kw)


def make(cls):
    """One instance of ``cls`` (an author subclass of an exported kind)."""
    if issubclass(cls, scena.Menu):
        return cls(options=["a", "b"])
    if issubclass(cls, scena.Endless):
        if "parity_pista" not in scena.canvas.layers:
            scena.canvas.layers.create("parity_pista", below="default")
        return cls("parity_pista", lambda slot: [], step=100)
    return cls()


def destroy(obj):
    if obj is not None and getattr(obj, "is_alive", False):
        obj.destroy()


class TestClassKeywords(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_every_family_takes_group_or_names_the_fix(self):
        took, refused = [], []
        for kind in kinds():
            with self.subTest(kind=kind.__name__):
                try:
                    cls = author_subclass(kind, group="parity")
                except TypeError as exc:
                    self.assertIsNone(leak_message(exc), f"{kind.__name__}: {exc}")
                    self.assertIn("Pass them when you make one", str(exc))
                    refused.append(kind.__name__)
                    continue
                obj = make(cls)
                try:
                    self.assertTrue(obj.tagged("parity"), f"{kind.__name__}: class group= not applied")
                finally:
                    destroy(obj)
                took.append(kind.__name__)
        # Shape, Sprite and SpatialFx families take class keywords.
        for name in ("Circle", "Rect", "Line", "Sprite", "Orb", "Fire", "Jet", "Text"):
            self.assertIn(name, took)
        # Decided 2026-10-10: the widgets, Entity and Endless keep the clear error.
        for name in ("Button", "Slider", "CheckBox", "DropDown", "TextInput", "Menu",
                     "Entity", "Endless"):
            self.assertIn(name, refused)

    def test_an_unknown_class_keyword_is_an_author_error(self):
        for kind in kinds():
            with self.subTest(kind=kind.__name__):
                with self.assertRaises(TypeError) as ctx:
                    author_subclass(kind, nonsense_knob=3)
                self.assertIsNone(leak_message(ctx.exception), str(ctx.exception))

    def test_an_author_mixin_still_gets_its_keywords(self):
        seen = {}

        class Mixin:
            def __init_subclass__(cls, flavor=None, **kw):
                seen[cls.__name__] = flavor
                super().__init_subclass__(**kw)

        type("Doce", (scena.Text, Mixin), {"__module__": AUTHOR_MODULE}, flavor="mel")
        self.assertEqual(seen, {"Doce": "mel"})


class TestCollideMethods(SystemTestCase, unittest.TestCase):
    """AC6 for every family: a method hook gets (other, info) like a callback."""

    world_draw = False

    def test_method_hooks_get_the_other_body(self):
        checked = []
        for kind in kinds():
            name = kind.__name__
            if name in NO_CONTACT:
                continue
            with self.subTest(kind=name):
                seen = []

                def on_collide(self, other, info, seen=seen):
                    seen.append((self, other, info))

                obj = make(author_subclass(kind, {"on_collide": on_collide}))
                wall = Rect(center=(200, 150), width=4000, height=4000)
                try:
                    wall.collidable = True
                    self.w.step(2)
                    self.assertTrue(seen, f"{name}: no contact with a wall over the whole world")
                    me, other, info = seen[0]
                    self.assertIs(me, obj)
                    self.assertIs(other, wall, f"{name}: other is {type(other).__name__}")
                    self.assertIs(info.a, obj)
                    self.assertIs(info.b, wall)
                finally:
                    destroy(obj)
                    destroy(wall)
                checked.append(name)
        self.assertGreaterEqual(len(checked), 20)

    def test_tables_are_current(self):
        names = {k.__name__ for k in kinds()}
        self.assertLessEqual(set(NO_CONTACT), names, "a stale NO_CONTACT entry")
        self.assertLessEqual(set(NO_INK_LINK), names, "a stale NO_INK_LINK entry")
        self.assertLessEqual(set(KNOWN_SELF_READ), names, "a stale KNOWN_SELF_READ entry")


class TestOwnFieldsDieQuietly(SystemTestCase, unittest.TestCase):
    """AC11 for every family: a field that reads its own object leaves with it."""

    world_draw = False

    def test_destroy_is_silent(self):
        for kind in kinds():
            if kind.__name__ in NO_INK_LINK:
                continue
            with self.subTest(kind=kind.__name__):
                obj = make(author_subclass(kind))
                obj.carga = 1.0
                if hasattr(obj, "center"):
                    # A part read too (AC11: the Guia's hero["grounded"] reads a part).
                    if kind.__name__ in KNOWN_SELF_READ:
                        from scena.state import CircularReferenceError
                        try:
                            obj["dobro"] @= lambda o=obj: o.carga + 1 + o.center.x * 0
                        except CircularReferenceError as exc:
                            self.assertIn("known limit", str(exc))
                            obj.destroy()
                            continue
                        self.fail(f"{kind.__name__} reads its own center now: drop it from KNOWN_SELF_READ")
                    obj["dobro"] @= lambda o=obj: o.carga + 1 + o.center.x * 0
                else:
                    obj["dobro"] @= lambda o=obj: o.carga + 1
                self.assertEqual(obj.dobro, 2.0)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    obj.destroy()
                    self.w.step(1)
                bad = [str(w.message) for w in caught if "was unlinked" in str(w.message)]
                self.assertEqual(bad, [])


class TestSubclassesAreFreed(unittest.TestCase):
    """AC1 for every family: the class dies once its last instance is gone."""

    def test_every_family(self):
        from system_support import SystemWorld
        world = SystemWorld(draw=False)
        refs = {}
        try:
            for kind in kinds():
                cls = author_subclass(kind)
                obj = make(cls)
                if kind.__name__ not in NO_INK_LINK:
                    obj.carga = 2.0
                    obj["dobro"] @= lambda o=obj: o.carga * 2
                    _ = obj.dobro
                world.step(1)
                obj.destroy()
                world.step(1)
                refs[kind.__name__] = weakref.ref(cls)
                del cls, obj
        finally:
            world.teardown(strict=False)
        full_collect()
        gc.collect()
        alive = sorted(n for n, r in refs.items() if r() is not None)
        self.assertEqual(alive, [], "author subclasses outlived their last instance")


if __name__ == "__main__":
    unittest.main()
