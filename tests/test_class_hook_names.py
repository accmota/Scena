"""A class-body method the engine would never call is refused at the class line.

Review 2026-10-14 (PA3 / PC5). Hook names in a class body are found by name;
a wrong name was dead code, silently:

* ``class Fase(Act): def update(self, dt)`` / ``def on_key_down(self, key)``
  (the top-of-file spellings) never ran;
* ``class Ship(Circle): def update(self, dt)`` overrode ``Container.update``
  (the reactive graph's recalculation): the construction crashed deep in
  ``state._batch_update`` with "missing 1 required positional argument: 'dt'";
* ``def on_colide(self, other)``, ``def on_updat(self, dt)`` and a plain
  method named ``collide_with`` (the decorator's name) were accepted.

Class guard: every exported Entity family is subclassed in an author module
and asked the same questions; every name the engine discovers in a class body
is in the near-miss pool (a new hook joins it or this fails); the author
helper names the repo uses (``on_hit``, ``on_frame``, ...) and every engine
``on_*`` name a family defines stay legal.

    python tests/run_tiers.py focused test_class_hook_names
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402
from scena import collide_with, on_change  # noqa: E402
from scena.act import Act  # noqa: E402
from scena.entity import (  # noqa: E402
    Entity, _ACTOR_HOOK_NAMES, _CLASS_HOOK_NAMES, _FOREIGN_HOOK_NAMES,
    _HOOK_LOOKUP_NAMES, _TOP_LEVEL_INPUT_HOOKS,
)
from scena._pkg import is_framework_module  # noqa: E402
from system_support import SystemTestCase  # noqa: E402

AUTHOR_MODULE = "author_game"

# Helper names author code in the repo gives its own methods (examples,
# tutorials, tests, the Guia): never one edit from a hook.
AUTHOR_HELPERS = (
    "on_hit", "on_death", "on_hp", "on_go", "on_stay", "on_leave", "on_any",
    "on_hot", "on_stat", "on_band", "on_finish", "on_fail", "on_frame",
    "on_exit", "on_done_rules", "on_destroy_once", "on_hit_bolt",
)


def families():
    out = []
    for name in scena.__all__:
        obj = getattr(scena, name, None)
        if inspect.isclass(obj) and issubclass(obj, Entity) and obj is not Act:
            out.append(obj)
    return out


def author_class(base, name, fn=None):
    body = {"__module__": AUTHOR_MODULE}
    body[name] = fn if fn is not None else (lambda self, *a: None)
    return type("Meu" + base.__name__, (base,), body)


def engine_on_names(kind):
    names = set()
    for k in kind.__mro__:
        if is_framework_module(k.__module__):
            names.update(n for n in k.__dict__ if n.startswith("on_"))
    return names


class TestActRefusesTheTopLevelSpellings(unittest.TestCase):

    def test_update_names_on_update(self):
        with self.assertRaises(TypeError) as cm:
            class Fase(Act):
                def update(self, dt):
                    pass
        msg = str(cm.exception)
        self.assertIn("Fase.update(self, dt): update is reserved", msg)
        self.assertIn("on_update(self, dt)", msg)

    def test_update_of_any_signature_is_refused_and_quoted(self):
        # An act is a Container too: a helper ``def update(self)`` shadows the
        # engine's recalculation of linked fields. The message quotes the
        # method as written (release audit C15).
        for body, quoted in (("def update(self):\n    pass", "Fase.update(self)"),
                             ("def update(self, a, b):\n    pass", "Fase.update(self, a, b)")):
            with self.subTest(quoted=quoted), self.assertRaises(TypeError) as cm:
                ns = {}
                exec(body, ns)
                type("Fase", (Act,), {"update": ns["update"], "__module__": __name__})
            self.assertIn(quoted, str(cm.exception))
            self.assertIn("another name", str(cm.exception))

    def test_every_top_level_input_callback_names_the_act_way(self):
        for name in _TOP_LEVEL_INPUT_HOOKS:
            with self.subTest(name=name):
                with self.assertRaises(TypeError) as cm:
                    author_class(Act, name)
                msg = str(cm.exception)
                self.assertIn(f".{name} would never be called", msg)
                self.assertIn("do not run on an act", msg)
                fix = "keyp.once" if name in ("on_key_down", "on_key_up", "on_key", "on_char") \
                    else "mouse.press()"
                self.assertIn(fix, msg)

    def test_the_act_hooks_stay_legal(self):
        class Fase(Act):
            def setup(self):
                pass

            def on_update(self, dt):
                pass

            def on_destroy(self):
                pass

            def on_hit(self):           # an author helper
                pass

    def test_a_near_miss_on_an_act(self):
        with self.assertRaises(TypeError) as cm:
            author_class(Act, "on_updat")
        self.assertIn("Did you mean on_update?", str(cm.exception))


class TestEveryFamily(SystemTestCase, unittest.TestCase):
    world_draw = False

    def test_update_is_refused_naming_on_update(self):
        for kind in families():
            with self.subTest(kind=kind.__name__):
                with self.assertRaises(TypeError) as cm:
                    author_class(kind, "update", lambda self, dt: None)
                msg = str(cm.exception)
                self.assertIn("on_update(self, dt)", msg)
                self.assertIn("update is reserved", msg)

    def test_a_ship_with_update_raises_at_the_class_not_at_construction(self):
        # Before: accepted, then Ship(...) raised "missing 1 required
        # positional argument: 'dt'" from state._batch_update.
        with self.assertRaises(TypeError) as cm:
            class Ship(scena.Circle):
                def update(self, dt):
                    pass
        self.assertIn("Ship.update(self, dt)", str(cm.exception))

    def test_top_level_input_callbacks_are_refused(self):
        for kind in families():
            for name in _TOP_LEVEL_INPUT_HOOKS:
                with self.subTest(kind=kind.__name__, name=name):
                    with self.assertRaises(TypeError) as cm:
                        author_class(kind, name)
                    msg = str(cm.exception)
                    self.assertIn("top-of-file function name", msg)
                    if name == "on_mouse_click":
                        self.assertIn("on_click(self)", msg)

    def test_one_edit_from_a_hook_is_refused(self):
        for kind in families():
            pool = set(_CLASS_HOOK_NAMES) | engine_on_names(kind)
            for hook in sorted(pool):
                tail = hook[3:]
                typos = {
                    "on_" + tail[:-1],                              # dropped last letter
                    "on_" + tail[1] + tail[0] + tail[2:],           # swapped first two
                }
                for typo in sorted(typos - pool):
                    with self.subTest(kind=kind.__name__, typo=typo):
                        with self.assertRaises(TypeError) as cm:
                            author_class(kind, typo)
                        msg = str(cm.exception)
                        self.assertIn(f".{typo} is not a hook name", msg)
                        self.assertIn("Did you mean on_", msg)

    def test_the_review_typos(self):
        for typo, fix in (("on_colide", "on_collide"), ("on_updat", "on_update"),
                          ("on_destory", "on_destroy"), ("on_clik", "on_click"),
                          ("on_collision", "on_collide"),
                          ("on_collision_exit", "on_collide_exit")):
            with self.subTest(typo=typo):
                with self.assertRaises(TypeError) as cm:
                    author_class(scena.Circle, typo)
                self.assertIn(f"Did you mean {fix}?", str(cm.exception))

    def test_a_plain_collide_with_method_is_refused(self):
        with self.assertRaises(TypeError) as cm:
            class Rock(scena.Circle):
                def collide_with(self, other):
                    pass
        msg = str(cm.exception)
        self.assertIn("Rock.collide_with is the name of a decorator", msg)
        self.assertIn("on_collide(self, other)", msg)

    def test_hooks_engine_names_and_helpers_stay_legal(self):
        for kind in families():
            names = (set(_CLASS_HOOK_NAMES) | engine_on_names(kind) | set(AUTHOR_HELPERS))
            for name in sorted(names):
                with self.subTest(kind=kind.__name__, name=name):
                    author_class(kind, name)

    def test_a_decorated_method_keeps_its_name(self):
        # ``@on_change`` / ``@collide_with`` methods are tagged, not hooks.
        class Heroi(scena.Circle):
            @on_change(lambda self: self.hp)
            def on_clik(self):          # a near miss, but a rule, not a hook
                pass

            @collide_with("rock")
            def on_colide(self, other):
                pass

    def test_a_subclass_may_reuse_its_author_base_names(self):
        class Base(scena.Circle):
            def on_hit(self):
                pass

        class Filho(Base):
            def on_hit(self):
                pass


class TestThePoolFollowsTheEngine(unittest.TestCase):
    """A hook the engine discovers by name joins the near-miss pool."""

    def test_every_discovered_hook_is_in_the_pool(self):
        missing = set(_ACTOR_HOOK_NAMES) - set(_CLASS_HOOK_NAMES)
        self.assertFalse(missing, f"add {sorted(missing)} to entity._CLASS_HOOK_NAMES")
        self.assertEqual(set(_HOOK_LOOKUP_NAMES) - set(_CLASS_HOOK_NAMES), {"setup"})

    def test_foreign_names_point_at_real_hooks(self):
        for wrong, fix in _FOREIGN_HOOK_NAMES.items():
            self.assertIn(fix, _CLASS_HOOK_NAMES, wrong)

    def test_the_top_level_list_is_the_frameworks(self):
        import scena.orchestration as orch
        src = inspect.getsource(orch.ScenaFramework.set_auto_callbacks)
        for name in _TOP_LEVEL_INPUT_HOOKS:
            self.assertIn(f"'{name}'", src)


if __name__ == "__main__":
    unittest.main()
