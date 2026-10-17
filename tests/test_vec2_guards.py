"""Static guards of the Vec2 battery: the tables it drives, pinned to their source.

Testing Design, "Vec2 battery" and "Planning a new test" (7: pin derived
tables to their source in both directions; 16: derive lists from the class).

* Every raw store of x / y in ``Vec2`` sits in a function this file names
  (the batched store ``_store_xy``, the copy ``_takein_impl``, the arithmetic
  fast path ``temp``): a new raw writer must say which guards it runs.
* ``vec2_support.DOOR_METHODS`` is every in-place spelling ``Vec2`` has, and
  every name in it exists.
* ``vec2_support.PART_KINDS`` is every Vec2 part an engine class declares
  (``ContainerSlot(Vec2)``), and every entry is still declared.
* The Guia's Vec2 table names only methods ``Vec2`` has; a public method it
  does not name is listed in ``UNDOCUMENTED`` (shrink-only).

    python -m unittest tests.test_vec2_guards -v
"""
from __future__ import annotations

import ast
import inspect
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vec2_support as V  # noqa: E402
from scena import Vec2  # noqa: E402
from scena.state import Container, ContainerSlot  # noqa: E402

# Function -> what it guarantees before its raw store of x / y.
RAW_XY_WRITERS = {
    "temp": "finite floats only (anything else takes the checking constructor)",
    "_store_xy": "derived refusal, finite check, then a batched slot write",
    "_takein_impl": "type, overflow; finite when owned (GX15: a free vector may hold NaN, VB4)",
    "__new__": "constructor arguments, not the vector's fields",
}

# Public Vec2 methods the Guia's table does not name (shrink-only: document
# one, then drop it here).
UNDOCUMENTED = {"abs_angle_to", "angle_to", "clamp_length_to", "do_rotation",
                "project", "reject", "reject_from", "temp", "to_array"}


def _vec2_class_node():
    path = os.path.join(ROOT, "scena", "scenamath.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Vec2")


class TestRawStores(unittest.TestCase):
    def test_every_raw_xy_store_is_named(self):
        found = set()
        for fn in (n for n in _vec2_class_node().body if isinstance(n, ast.FunctionDef)):
            for node in ast.walk(fn):
                if not isinstance(node, (ast.Assign, ast.AugAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    attr = (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                            and t.value.id == "self" and t.attr in ("x", "y"))
                    key = (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                           and t.slice.value in ("x", "y"))
                    if attr or key:
                        found.add(fn.name)
        self.assertEqual(found - set(RAW_XY_WRITERS), set(),
                         "a new raw x / y store: name it in RAW_XY_WRITERS with the "
                         "guards it runs, and add its door to vec2_support.DOORS")
        self.assertEqual(set(RAW_XY_WRITERS) - found, set(), "stale RAW_XY_WRITERS entries")


class TestTablesPinned(unittest.TestCase):
    def test_door_methods(self):
        in_place = {n for n in dir(Vec2)
                    if (n.startswith("__i") and n.endswith("__") and n not in
                        ("__init__", "__init_subclass__", "__iter__"))
                    or n == "__lshift__" or n.startswith("do_")}
        self.assertEqual(in_place, set(V.DOOR_METHODS),
                         "in-place spellings and vec2_support.DOOR_METHODS differ")
        for door in V.DOOR_METHODS.values():
            self.assertIn(door, V.DOORS)

    def test_part_kinds(self):
        seen, stack, declared = set(), [Container], set()
        while stack:
            cls = stack.pop()
            for sub in type.__subclasses__(cls):
                if sub not in seen:
                    seen.add(sub)
                    stack.append(sub)
        for cls in seen:
            if cls.__module__.startswith("scena."):
                for name, slot in vars(cls).items():
                    if isinstance(slot, ContainerSlot) and issubclass(slot.container_class, Vec2):
                        declared.add((cls.__name__, name))
        self.assertEqual(declared, set(V.PART_KINDS),
                         "Vec2 parts and vec2_support.PART_KINDS differ: give a new "
                         "part a kind in KINDS")
        for kind in V.PART_KINDS.values():
            self.assertIn(kind, V.KINDS)

    def test_contexts_operands_reads_are_driven(self):
        # Every axis value the matrix names is one the support can run.
        self.assertTrue(set(V.GOOD_OPERANDS) <= set(V.OPERANDS))
        self.assertTrue(set(V.NEVER_REFUSED) <= set(V.GOOD_OPERANDS))
        for kind, door in V.DESIGNED_REFUSALS:
            self.assertIn(kind, V.KINDS)
            self.assertIn(door, V.DOORS)


class TestGuiaTable(unittest.TestCase):
    def _guia_methods(self):
        path = os.path.join(ROOT, "docs", "pt", "guide", "index.html")
        with open(path, encoding="utf-8") as f:
            html = f.read()
        start = html.index("Neste Vec2")
        end = html.index("Interseções", start)
        # The first cell of each row: the name column (one or more <code>).
        firsts = re.findall(r"<tr><td>(.*?)</td>", html[start:end])
        names = set()
        for cell in firsts:
            for code in re.findall(r"<code>([^<]*)</code>", cell):
                names.update(re.findall(r"\.([a-z_]+)\(", code))
        return names

    def test_the_guia_names_real_methods(self):
        names = self._guia_methods()
        self.assertTrue(names, "the Guia's Vec2 table was not found (vacuous)")
        missing = sorted(n for n in names if not hasattr(Vec2, n))
        self.assertFalse(missing, f"the Guia names Vec2 methods that do not exist: {missing}")

    def test_undocumented_is_shrink_only(self):
        names = self._guia_methods()
        public = {n for n, f in inspect.getmembers(Vec2, callable)
                  if not n.startswith("_") and n in vars(Vec2)}
        self.assertEqual(public - names, UNDOCUMENTED,
                         "public Vec2 methods the Guia does not name changed: document "
                         "the new one, or drop a documented one from UNDOCUMENTED")


if __name__ == "__main__":
    unittest.main()
