"""An author's classes (and the module they live in) die when the program drops them.

Bug AC1 (found by the game system tests, 2026-10-09): the engine cached
per-class data in module-level dicts keyed by the class (``entity._DEAD_ROUTES``,
``entity._SCENA_KIND_CACHE``, ``entity._PROPERTY_LINK_BY_CLASS``,
``collision._extra_slots_for_cls``). A key is a strong reference: once one
instance of ``class Tiro(Sprite)`` was destroyed, the class lived for the
whole process, and through its methods' ``__globals__`` so did the program's
namespace and every object in it (a destroyed hitbox part was still counted
by the census after the program closed). Harmless in a one-program process,
a leak in any process that runs many programs (the test tiers, an editor
that reloads a script).

The class guard does not list the caches: it exercises an author subclass of
each family through the engine paths that cache per class (construction,
``x["angle"]``, collision enroll, kind dispatch, destroy), then scans the
globals of every loaded ``scena`` module for anything still holding the
class, and requires the class to be collected.

    python -m unittest tests.test_author_class_lifetime -v
"""
from __future__ import annotations

import gc
import os
import sys
import types
import unittest
import weakref

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media_support import media  # noqa: E402
from system_support import SystemWorld, full_collect, referrer_chain  # noqa: E402

PROGRAM = '''
from scena import *

class Bola(Circle, radius=12, color="gold", group="bola"):
    def setup(self):
        self.hp = 3

class Caixa(Rect, width=30, height=20, group="caixa"):
    pass

class Nave(Sprite, source=NAVE_PNG, height=24, group="nave"):
    def on_update(self, dt):
        self.move_by(10 * dt, 0)

class Diretor(Entity):
    @on_mode
    def andando(self):
        after(5.0, lambda: None)

@collide("bola", "caixa")
def bateu(a, b):
    pass

made = [Bola(center=(100, 100)), Caixa(center=(110, 100)), Nave(center=(300, 300)),
        Diretor()]
made[3].mode = made[3].andando
for m in made[:3]:
    m.angle = 15
    _ = m["angle"]
'''


def _holders_in_scena_modules(cls) -> list:
    """Global containers of loaded scena modules that still hold ``cls``."""
    out = []
    for name, mod in list(sys.modules.items()):
        if not (name == "scena" or name.startswith("scena.")) or mod is None:
            continue
        for gname, value in list(vars(mod).items()):
            try:
                if isinstance(value, dict) and (cls in value or any(v is cls for v in value.values())):
                    out.append(f"{name}.{gname}")
                elif isinstance(value, (list, set, frozenset, tuple)) and any(v is cls for v in value):
                    out.append(f"{name}.{gname}")
            except TypeError:
                continue
    return out


class TestAuthorClassesAreFreed(unittest.TestCase):
    """AC1: a program's classes do not outlive the program."""

    def run_program(self, *, destroy: bool):
        ns = {"__name__": "author_prog_ac1", "NAVE_PNG": media("space", "playerShip1_red.png")}
        world = SystemWorld(draw=False)
        try:
            exec(compile(PROGRAM, "author_prog_ac1.py", "exec"), ns)
            world.step(3)
            classes = [ns[n] for n in ("Bola", "Caixa", "Nave", "Diretor")]
            refs = [weakref.ref(c) for c in classes]
            for obj in ns["made"]:
                world.track(obj)
            if destroy:
                for obj in ns["made"]:
                    obj.destroy()
                world.step(1)
            holders = {}
            for cls in classes:
                holders[cls.__name__] = _holders_in_scena_modules(cls)
            del classes, cls
        finally:
            world.teardown(strict=False)
        ns.clear()
        return refs, holders

    def assert_freed(self, refs, holders):
        # Collect here, with run_program's frame gone (no local still names a class).
        full_collect()
        held = {k: v for k, v in holders.items() if v}
        self.assertFalse(held, f"scena module globals hold author classes: {held}")
        alive = [r() for r in refs if r() is not None]
        chains = "\n".join(f"{c.__name__}:\n{referrer_chain(c, depth=4)}" for c in alive[:2])
        self.assertFalse(alive, f"author classes outlived the program:\n{chains}")

    def test_classes_freed_after_destroy(self):
        self.assert_freed(*self.run_program(destroy=True))

    def test_classes_freed_after_teardown(self):
        self.assert_freed(*self.run_program(destroy=False))


if __name__ == "__main__":
    unittest.main()
