"""Entity subclass hooks and construction integrity.

Regression for 2026-09-25: a second ``__init_subclass__`` added to the
``Entity`` class body (for constructor rollback) silently replaced the first,
so subclasses lost their setattr route, the actor finish (``setup()``,
method watches) and deferred ``@every`` / ``@after`` claims. Symptom:
``Rect.angle = …`` recursed forever through ``Shape.angle``.

    python -m unittest tests.test_entity_hooks -v
"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.source_support import iter_files  # noqa: E402

from scena import (  # noqa: E402
    Circle, Ellipse, Entity, Rect, Square, Text, init,
)
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.state import ScalarSlot  # noqa: E402


def _duplicate_defs(path):
    """``(line, owner, name)`` for each def that rebinds an earlier one in the same body."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef)):
            continue
        seen = {}
        for stmt in node.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decos = [ast.unparse(d) for d in stmt.decorator_list]
            # property setters / deleters and @overload legitimately repeat a name
            if any(d.endswith((".setter", ".deleter")) or d.endswith("overload") for d in decos):
                continue
            if stmt.name in seen:
                out.append((stmt.lineno, getattr(node, "name", "<module>"), stmt.name))
            else:
                seen[stmt.name] = stmt.lineno
    return out


class TestNoSilentRedefinition(unittest.TestCase):
    """Bug class: a later ``def`` with the same name silently wins in Python."""

    def test_no_class_or_module_defines_a_function_twice(self):
        found = []
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            for line, owner, name in _duplicate_defs(path):
                found.append(f"{os.path.basename(path)}:{line} {owner}.{name}")
        self.assertEqual(found, [], "duplicate definitions (the later one wins):\n" + "\n".join(found))


# Attributes that hold an Entity (or None). A destroyed Entity is falsy
# (Entity.__bool__), so ``x.host or fallback`` swaps a dead host for the
# fallback instead of testing for None.
_ENTITY_REFS = frozenset({
    "_alias_of", "host", "_host", "owner", "_owner", "parent", "_parent",
    "source", "_source", "target", "_target", "rider", "actor", "entity",
    "shape", "sprite",
})


class TestNoTruthinessFallbackOnEntities(unittest.TestCase):
    """R9 (Testing Design): ``self._alias_of or self`` fell back to a reversed
    view's own empty tables once its host was destroyed (the rider jumped to
    the origin). Use ``is not None`` for an Entity-or-None slot."""

    def test_entity_refs_are_not_or_fallbacks(self):
        bad = []
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                    continue
                for val in node.values[:-1]:
                    name = (val.attr if isinstance(val, ast.Attribute)
                            else val.id if isinstance(val, ast.Name) else None)
                    if name in _ENTITY_REFS:
                        bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} "
                                   f"({name} or ...)")
        self.assertEqual(bad, [], "Entity-or-None used as an `or` fallback; "
                                  "a destroyed Entity is falsy — use `is not None`")


class TestHooksDoNotCallTheirDispatcher(unittest.TestCase):
    """A7 (Testing Design): ``Square._takein_impl`` called ``super()._takein``
    — the dispatcher, which calls ``self._takein_impl`` again — and recursed
    forever. A ``_x_impl`` hook chains with ``super()._x_impl``, never ``_x``."""

    def test_impl_hooks_chain_to_impl(self):
        bad = []
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for fn in ast.walk(tree):
                if not (isinstance(fn, ast.FunctionDef) and fn.name.endswith("_impl")):
                    continue
                base = fn.name[: -len("_impl")]
                for node in ast.walk(fn):
                    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == base):
                        continue
                    recv = node.func.value
                    is_super = (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name)
                                and recv.func.id == "super")
                    if is_super or (isinstance(recv, ast.Name) and recv.id == "self"):
                        bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} "
                                   f"{fn.name} calls {base}()")
        self.assertEqual(bad, [])


class TestSubclassHooks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_every_entity_subclass_has_its_own_setattr_route(self):
        seen, stack = set(), [Entity]
        while stack:
            cls = stack.pop()
            for sub in cls.__subclasses__():
                if sub in seen:
                    continue
                seen.add(sub)
                stack.append(sub)
                with self.subTest(cls=sub.__name__):
                    self.assertIn("_setattr_route", vars(sub))

    def test_geometry_rotation_routes_to_its_scalar_slot(self):
        for cls in (Rect, Ellipse, Square):
            with self.subTest(cls=cls.__name__):
                self.assertIsInstance(cls._setattr_route["angle"], ScalarSlot)

    def test_rotation_write_and_flip_do_not_recurse(self):
        for obj in (Rect(center=(0, 0), width=10, height=6),
                    Ellipse(center=(0, 0), width=10, height=6)):
            with self.subTest(kind=type(obj).__name__):
                obj.angle = 30
                obj.rotate_by(10)
                obj.flip_x = True
                self.assertAlmostEqual(float(obj.angle) % 360, 140.0)
                obj.destroy()

    def test_subclass_setup_runs_once(self):
        calls = []

        class Director(Entity):
            def setup(self):
                calls.append(self)

        class Ball(Circle):
            def setup(self):
                calls.append(self)

        d, b = Director(), Ball(center=(0, 0), radius=3)
        self.assertEqual(calls, [d, b])
        d.destroy()
        b.destroy()


class TestConstructionIsAtomic(unittest.TestCase):
    """A rejected constructor claims no roster entry, group, draw entry, or new layer."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        self.registry = ScenaCanvas.get_current().registry

    def test_bare_entity_with_missing_layer_leaves_no_roster_or_group(self):
        mark = self.registry._next_key
        with self.assertRaises(ValueError):
            Entity(layer="hooks_missing", group="hooks_g")
        self.assertEqual([k for k in self.registry.live.keys() if k > mark], [])
        self.assertEqual(self.registry.group_live_count("hooks_g"), 0)

    def test_subclass_init_error_after_register_rolls_back(self):
        class Fussy(Circle):
            def __init__(self, **kw):
                super().__init__(**kw)
                raise RuntimeError("author bug in __init__")

        before = len(self.registry.objects_on_layer("default"))
        with self.assertRaises(RuntimeError):
            Fussy(group="hooks_g3")
        self.assertEqual(len(self.registry.objects_on_layer("default")), before)
        self.assertFalse(any(isinstance(o, Fussy) for o in self.registry.live_objects()))
        self.assertEqual(self.registry.group_live_count("hooks_g3"), 0)


class TestTextClonePlacement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_layer_is_placement_not_a_copy(self):
        hud = Text("hud")
        world = Text("world", center=(0, 0), layer="top")
        made = [hud.clone(), world.clone(), world.clone(layer="top")]
        self.assertEqual([m.layer for m in made], ["ui", "default", "top"])
        for t in (hud, world, *made):
            t.destroy()


if __name__ == "__main__":
    unittest.main()
