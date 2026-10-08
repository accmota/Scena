"""Every public name an author can mistype into a write is classified (graphics review R8).

``Entity.__setattr__`` routes each public name per class. Three kinds of
name fell through it (2026-10-08):

* **E8, methods.** ``c.tag = "boss"`` or ``destroy = True`` silently replaced
  the method on the instance.
* **E12 / SA17, setter-less properties.** ``is_alive = …``, ``box = …`` and
  ``point.center = …`` raised Python's own "property … has no setter",
  with no hint.
* **E13, geometry names the class lacks.** ``circle.width = 20``,
  ``line.width = 5`` and ``text.size = 40`` became ink that nothing reads.

The guard enumerates, for every Entity kind, every public method, every
setter-less property, and every settable geometry name of another Graphic
kind that this kind lacks. A write to any of them must raise a Scena error
whose message is not one of Python's own, and must leave the instance
unchanged. Known violations are shrink-only (``graphics_known.ROUTE``).

    python tests/run_tiers.py focused test_route_table
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world, quiet  # noqa: E402

import geometry_support as G  # noqa: E402
import scena  # noqa: E402
from scena.entity import Graphic, _ACTOR_HOOK_NAMES  # noqa: E402
from scena.state import ScalarSlot  # noqa: E402
from test_hyp_surface import _AUTHOR_WORDS  # noqa: E402

# Python's own wording: an author reading it learns nothing about Scena.
_RAW = re.compile(r"has no setter|can't set attribute|object attribute '.*' is read-only"
                  r"|^'[A-Za-z_]+' object has no attribute")
# Callable slots by design: assigning a function is the API (``e.on_update = fn``).
_ASSIGNABLE = set(_ACTOR_HOOK_NAMES) | {"mode", "setup"}
_VALUE = 12.5


def _subjects():
    """(label, factory) for every Graphic kind in KINDS, plus a bare Entity."""
    out = [("Entity", scena.Entity)]
    for kind in sorted(G.KINDS):
        if kind.startswith("Box") or kind.endswith("reversed"):
            continue
        out.append((kind, (lambda k=kind: G.build(k))))
    return out


# Field names of some kind that are also ordinary words for a field of the
# author's own: not reserved on the kinds that lack them.
GENERIC = {
    "x": "a Point's own; on an actor the pose refusal names .center",
    "y": "same as x",
    "dx": "a delta an author may keep", "dy": "same as dx",
    "c": "a short name an author may keep", "u": "a Track cursor; a common author name",
    "text": "a label an author may keep on any actor", "cursor": "same as u",
    "begin": "a Track span; a common author name", "end": "same as begin",
    "spread": "a Circle arc; a common author name",
    "angle": "every Graphic has it", "center": "every Graphic has it",
}


def _settable_geometry_names():
    """Every field name of any kind in KINDS (the slots, not the engine's own
    word list: batch 9a enumerated ``_SIZE_WORDS``, the fix's list, and missed
    ``circle.top_left = …``), minus the generic words above."""
    names = set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for kind in G.KINDS:
            obj = G.build(kind)
            if hasattr(obj, "_field_slots"):
                names |= {n for n in obj._field_slots() if not n.startswith("_")}
    return names - set(GENERIC)


def _cases(obj, geometry):
    cls = type(obj)
    out = []
    for name in sorted(dir(cls)):
        if name.startswith("_") or name in _ASSIGNABLE:
            continue
        desc = inspect.getattr_static(cls, name, None)
        if isinstance(desc, property):
            if desc.fset is None:
                out.append(("read-only", name))
        elif callable(desc) and name in _AUTHOR_WORDS and not isinstance(desc, type):
            out.append(("method", name))
    if isinstance(obj, Graphic):
        for name in sorted(geometry):
            if inspect.getattr_static(cls, name, None) is None and name not in obj._field_slots():
                out.append(("missing geometry", name))
    return out


def route_violations() -> dict:
    """``"category | name"`` -> the kinds that let the write through.

    Keyed by name, not by kind: the route table is per class but the rule is
    one, so a fix closes a name on every kind at once."""
    geometry = _settable_geometry_names()
    found = {}
    with fresh_world():
        for label, make in _subjects():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                probe = make()
            cases = _cases(probe, geometry)
            probe.destroy()
            for what, name in cases:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    obj = make()
                key = f"{what} | {name}"
                verdict = None
                try:
                    with quiet():
                        setattr(obj, name, _VALUE)
                except Exception as e:  # noqa: BLE001
                    if _RAW.search(str(e)):
                        verdict = "raw message"
                else:
                    verdict = "accepted"
                if name in obj.__dict__ or name in (obj.__dict__.get("_ink") or {}):
                    verdict = verdict or "stored on the instance"
                if verdict:
                    found.setdefault(key, []).append(label.split()[0])
                with quiet():
                    type(obj).destroy(obj)        # the instance may have lost ``destroy`` (E8)
    return {k: ",".join(sorted(set(v))) for k, v in found.items()}


class TestEveryPublicNameIsClassified(unittest.TestCase):
    def test_a_write_to_a_method_read_only_or_foreign_name_raises_with_a_hint(self):
        from graphics_known import shrink_only
        shrink_only(self, route_violations(), "ROUTE")

    def test_canary_a_refusal_that_lets_the_write_through(self):
        from diff_support import assert_catches
        from scena.entity import _RouteRefusal
        assert_catches(self, "test_route_table.TestEveryPublicNameIsClassified."
                             "test_a_write_to_a_method_read_only_or_foreign_name_raises_with_a_hint",
                       [(_RouteRefusal, "__set__", lambda self, obj, value: object.__setattr__(obj, "_canary", value))],
                       "a refusal that silently accepts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
