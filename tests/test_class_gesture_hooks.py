"""A pointer gesture written as a class method works like the instance form.

Bug (CH1, 2026-10-14, found writing the "Ganchos na classe" interlude): in a
class, ``def on_click(self)`` made the shape clickable, but ``on_drag_to`` /
``on_drag_over`` / ``on_drop_by`` methods did not make it draggable /
droppable (the engine only installed the names in ``_ACTOR_HOOK_NAMES``), and
with ``draggable = True`` set by hand the engine called ``on_drag_to(self,
alvo, pos)`` with ``(self, alvo)``: the payload slid by one.

The class form takes the *other* side and ``pos`` (``self`` is already one
side), as ``on_collide(self, other, info)`` does: ``on_drag_to(self, alvo,
pos)``, ``on_drag_over(self, alvo, pos)``, ``on_drop_by(self, peca, pos)``.

Class guard: every pointer handler property a Graphic has is a discovered
class hook, and a method of that name turns on the same flag as assigning a
function to the instance does, on every Graphic family (Shape, Sprite, Text).

    python tests/run_tiers.py focused test_class_gesture_hooks
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun, drag, wait  # noqa: E402

# The pointer handler properties of a Graphic and the flag each one turns on
# (``None``: a hover target, no flag).
GESTURES = {
    "on_click": "clickable",
    "on_drag_to": "draggable",
    "on_drag_over": "draggable",
    "on_drop_by": "droppable",
    "on_hover": None,
    "on_hover_exit": None,
}
ARGS = {"on_click": "", "on_hover": "", "on_hover_exit": "",
        "on_drag_to": ", alvo, pos", "on_drag_over": ", alvo, pos", "on_drop_by": ", peca, pos"}


class TestEveryGestureIsAClassHook(unittest.TestCase):
    def test_the_engine_discovers_every_pointer_property(self):
        from scena.entity import _ACTOR_HOOK_NAMES
        from scena.process import _ACTOR_HOOK_METHOD_NAMES
        from scena.shapes import Shape
        props = {n for n in dir(Shape) if n.startswith("on_")
                 and isinstance(getattr(Shape, n, None), property)}
        self.assertTrue(set(GESTURES) <= props, "a gesture property was renamed")
        for name in props & set(GESTURES):
            with self.subTest(name=name):
                self.assertIn(name, _ACTOR_HOOK_NAMES)
                self.assertIn(name, _ACTOR_HOOK_METHOD_NAMES)


SOURCE = '''
from scena import *
init(width=600, height=400)
st.log = []
'''


CLASS_LINE = {"Circle": "Circle, radius=20",
              "Sprite": 'Sprite, source="space/star_gold.png", width=40',
              "Text": "Text"}
MAKE = {"Circle": "Coisa(center=(300, 200))",
        "Sprite": "Coisa(center=(300, 200))",
        "Text": 'Coisa("x", center=(300, 200))'}
PLAIN = {"Circle": "Circle(radius=20)",
         "Sprite": 'Sprite("space/star_gold.png", width=40)',
         "Text": 'Text("y")'}


class TestAMethodTurnsOnItsFlag(unittest.TestCase):
    def test_each_gesture_on_each_family(self):
        for family in CLASS_LINE:
            for name, flag in GESTURES.items():
                if flag is None:
                    continue
                with self.subTest(family=family, gesture=name):
                    src = SOURCE + (
                        f"class Coisa({CLASS_LINE[family]}):\n"
                        f"    def {name}(self{ARGS[name]}):\n"
                        f"        pass\n\n"
                        f"coisa = {MAKE[family]}\n"
                        f"solta = {PLAIN[family]}\n"
                        f"solta.{name} = lambda *a: None\n"
                        f"run()\n")
                    with ProgramRun("examples/_gesture.py", source=src) as run:
                        run.step(1)
                        self.assertTrue(getattr(run.ns["coisa"], flag))
                        self.assertEqual(getattr(run.ns["coisa"], flag),
                                         getattr(run.ns["solta"], flag))


class TestTheMethodGetsTheOtherSide(unittest.TestCase):
    SRC = SOURCE + '''
class Pote(Rect, width=160, height=100, color="gray"):
    def on_drop_by(self, peca, pos):
        st.log.append(("drop", peca is bola, self is pote, round(pos[0])))


class Bola(Circle, radius=14, color="khaki"):
    def on_drag_over(self, alvo, pos):
        st.log.append(("over", self is bola, alvo is pote or alvo is None))

    def on_drag_to(self, alvo, pos):
        st.log.append(("to", self is bola, alvo is pote, round(pos[0])))


pote = Pote(center=(400, 80))
bola = Bola(center=(150, 300))
run()
'''

    def test_drag_payload(self):
        with ProgramRun("examples/_gesture.py", source=self.SRC) as run:
            run.step(2)
            run.play([drag(150, 300, 400, 80, frames=6), wait(2)])
            log = run.ns["st"].log
        overs = [e for e in log if e[0] == "over"]
        self.assertTrue(overs and all(e[1] and e[2] for e in overs))
        self.assertIn(("to", True, True, 400), log)
        self.assertIn(("drop", True, True, 400), log)
        self.assertLess(log.index(("to", True, True, 400)), log.index(("drop", True, True, 400)))

    def test_the_top_level_signature_raises_at_construction(self):
        src = SOURCE + '''
class Bola(Circle, radius=14):
    def on_drag_to(self, peca, alvo, pos):
        pass

Bola()
run()
'''
        with self.assertRaises(TypeError) as ctx:
            with ProgramRun("examples/_gesture.py", source=src) as run:
                run.step(1)
        self.assertIn("on_drag_to", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
