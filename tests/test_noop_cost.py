"""Guard: a no-op builds nothing.

Class guard for PM7 (a verb on an empty group built a hidden Shape per call,
~0.3 ms every frame). Cost is a contract too, and garbage collection hides it
from every leak test (Testing Design, "What the program-model campaign taught" 5).

* Every public method an exported Entity class offers, called through an empty
  group (``group["nobody"].move_by(…)``), registers no object and returns None
  (Guia "Agir em massa": the method does nothing).
* Every world setting that is a plain attribute (``act.WORLD_SETTINGS``),
  written back with its own value, registers no object.

The spy is ``Registry.add_live``: every Entity, part and point that joins the
live roster passes through it.

    python -m unittest tests.test_noop_cost -v
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import quiet, system_world  # noqa: E402

import scena  # noqa: E402
from scena import group  # noqa: E402
from scena.registry import GroupOperator, Registry  # noqa: E402


def _spy():
    made = []
    real = Registry.add_live

    def add_live(self, obj):
        made.append(type(obj).__name__)
        return real(self, obj)
    return made, mock.patch.object(Registry, "add_live", add_live)


def _entity_methods():
    """Public methods of exported Entity classes, minus the group's own ones."""
    from scena.entity import Entity
    names = set()
    for n in scena.__all__:
        cls = getattr(scena, n, None)
        if inspect.isclass(cls) and issubclass(cls, Entity):
            for attr, val in inspect.getmembers(cls):
                if attr.startswith("_") or not inspect.isfunction(val):
                    continue
                names.add(attr)
    own = {a for a in dir(GroupOperator) if not a.startswith("_")}
    return sorted(names - own)


class TestEmptyGroupVerbsBuildNothing(unittest.TestCase):
    def test_every_method(self):
        names = _entity_methods()
        self.assertGreater(len(names), 50, "inventory looks empty")
        with system_world(draw=False):
            g = group["noop_nobody"]
            made, patch = _spy()
            with patch, quiet():
                for name in names:
                    with self.subTest(method=name):
                        before = len(made)
                        result = getattr(g, name)()
                        self.assertIsNone(result)
                        self.assertEqual(made[before:], [], f"group[…].{name}() on an empty group")


def _entity_fields():
    """Public non-method names of exported Entity classes (properties, slots),
    minus the group's own: what ``group["x"].<name>`` reads from a member."""
    from scena.entity import Entity
    names = set()
    for n in scena.__all__:
        cls = getattr(scena, n, None)
        if inspect.isclass(cls) and issubclass(cls, Entity):
            for attr in dir(cls):
                if attr.startswith("_"):
                    continue
                static = inspect.getattr_static(cls, attr, None)
                if static is None or inspect.isfunction(static) or isinstance(static, (staticmethod, classmethod, type)):
                    continue
                names.add(attr)
    own = {a for a in dir(GroupOperator) if not a.startswith("_")}
    return sorted(names - own - set(_entity_methods()))


class TestEmptyGroupFieldReadsRaise(unittest.TestCase):
    """A field read on an empty group raises with the fix (Guia: "ler um campo
    dá erro"). ``group["boss"].center`` answered an invented (0, 0) from a
    Blank built and registered per read, and ``.hp`` raised naming ``Blank``
    (graphics review SC12). Whole-group reads (``centroid``, ``box``,
    ``empty``, ``count``) are the group's own and answer."""

    def test_every_field_raises_with_the_group_and_builds_nothing(self):
        names = _entity_fields()
        self.assertGreater(len(names), 50, "inventory looks empty")
        with system_world(draw=False):
            g = group["noop_nobody"]
            made, patch = _spy()
            with patch, quiet():
                for name in names + ["hp"]:
                    with self.subTest(field=name):
                        before = len(made)
                        with self.assertRaises(AttributeError) as cm:
                            getattr(g, name)
                        msg = str(cm.exception)
                        self.assertIn("group['noop_nobody'] is empty", msg)
                        self.assertNotIn("Blank", msg)
                        self.assertEqual(made[before:], [], f"group[…].{name} on an empty group")
            self.assertIsNone(g.centroid)
            self.assertIsNone(g.box)
            self.assertTrue(g.empty)


def _settings():
    """``(label, owner, attribute)`` for every world setting that is a plain attribute."""
    from scena.act import WORLD_SETTINGS
    from scena.orchestration import ScenaFramework
    roots = {
        "canvas": scena.canvas, "clock": scena.clock, "collision": scena.collision,
        "effects": scena.canvas.effects, "playfield": scena.canvas.playfield,
        "layers": scena.canvas.layers,
        "background": ScenaFramework.get_instance().background_stack,
    }
    out = []
    for w in WORLD_SETTINGS:
        for cover in w.covers:
            if "." not in cover:
                continue
            root, attr = cover.split(".", 1)
            owner = roots.get(root)
            if owner is None or "." in attr:
                continue
            static = inspect.getattr_static(owner, attr, None)
            if static is None or callable(static) and not isinstance(static, property):
                continue                    # a verb (pan_to, add, reset_base …)
            out.append((cover, owner, attr))
    return out


class TestSettingAWorldValueToItselfBuildsNothing(unittest.TestCase):
    def test_every_attribute_setting(self):
        settings = _settings()
        written = []
        with system_world(draw=False):
            made, patch = _spy()
            with patch, quiet():
                for cover, owner, attr in settings:
                    with self.subTest(setting=cover):
                        value = getattr(owner, attr)
                        before = len(made)
                        try:
                            setattr(owner, attr, value)
                        except AttributeError as e:
                            if "read-only" in str(e):
                                continue        # a view written through verbs (zoom_to …)
                            raise
                        written.append(cover)
                        self.assertEqual(made[before:], [], f"{cover} = {cover}")
        self.assertGreaterEqual(len(written), 8, written)   # not vacuous


class TestNoopCanary(unittest.TestCase):
    def test_a_verb_that_builds_on_an_empty_group_is_caught(self):
        from diff_support import assert_catches
        from scena.shapes import Blank
        import scena.registry as R
        assert_catches(self, "test_noop_cost.TestEmptyGroupVerbsBuildNothing.test_every_method",
                       [(R, "_empty_group_attr", lambda name: getattr(Blank(), name))],
                       "an empty-group verb that builds a Shape (PM7)")


if __name__ == "__main__":
    unittest.main()
