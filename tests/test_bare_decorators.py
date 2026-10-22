"""A Scena decorator written without its arguments, or with nothing to act on,
or above a method it cannot wire, raises with the fix.

Bug class (BD1, 2026-10-22, an author's question: "can a class use
``@click`` instead of ``def on_click(self)``?"). A decorator that takes
arguments, written bare (``@every`` above ``def spawn``), gets the function
itself as its argument and returns its inner decorator, which nothing calls:
the name is rebound to that closure and the function never runs. No error,
no warning. Members found: the six pointer verbs, ``@every``, ``@after``,
``@when``, ``@on_change``, the three ``@collide_with*`` and ``@exit_mode``
(``@collide*`` already raised: they take two required sides). Two more doors
of the six pointer verbs were silent too: ``@click()`` wired nothing, and
``@click(group["x"])`` above a method made a rule of the whole tag at the
class line, with the target as ``self`` (in an act, the button, not the act),
while ``@collide`` in a class body already refused.

Where the argument can never be a function (a target, an interval, a side)
the call raises (``validate.refuse_bare_decorator``). ``@when`` /
``@on_change`` / ``@exit_mode`` take a function, so the returned decorator
records it (``validate.mark_bare_candidate``); a class body (class line) or
the script namespace (``run()``) that binds the function's own name to it is
the bare form (``validate.bare_decorator_message``).

Class guard: every public decorator factory (a public function whose source
builds an inner decorator) is in ``BARE`` below, refused bare or a form whose
bare spelling is its own (``@on_mode``, a class ``@leave_playfield``).

    python tests/run_tiers.py focused test_bare_decorators
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from program_support import ProgramRun  # noqa: E402

POINTER = ("click", "hover", "hover_exit", "drag_to", "drag_over", "drop_by")
# Bare spelling refused: verb -> (handler parameters at the top of the file,
# in a class body, or None where the verb has no form there).
BARE = {
    **{v: ("t", "self") for v in POINTER},
    "collide": ("a, b", None), "collide_stay": ("a, b", None),
    "collide_exit": ("a, b", None),
    "collide_with": (None, "self, other"), "collide_with_stay": (None, "self, other"),
    "collide_with_exit": (None, "self, other"),
    "every": ("", "self"), "after": ("", "self"),
    "when": ("", "self"), "on_change": ("v", "self, v"),
    "exit_mode": ("", "self"),
}
# Bare is the form itself.
BARE_FORM = {"on_mode", "leave_playfield"}

HEAD = '''
from scena import *
init(width=600, height=400)
st.log = []
'''


def _program(body: str) -> str:
    return HEAD + body + "\nrun()\n"


def _run(test, body: str, steps: int = 1):
    """The program's log after ``steps`` frames (read before the world resets),
    and the namespace."""
    with ProgramRun("examples/_bare.py", source=_program(body)) as run:
        run.step(steps)
        return list(run.ns["st"].log), run.ns


def _refused(test, body: str) -> str:
    with test.assertRaises(TypeError) as ctx:
        _run(test, body)
    return str(ctx.exception)


class TestEveryDecoratorIsListed(unittest.TestCase):
    def test_every_public_decorator_factory_is_classified(self):
        import scena
        found = set()
        for name in scena.__all__:
            obj = getattr(scena, name, None)
            if not inspect.isfunction(obj):
                continue
            try:
                src = inspect.getsource(obj)
            except (OSError, TypeError):
                continue
            if "decorator" in src or "def deco(" in src:
                found.add(name)
        self.assertEqual(found, set(BARE) | BARE_FORM,
                         "a new decorator: add it to BARE (and refuse its bare "
                         "form) or to BARE_FORM")


class TestTheBareFormRaises(unittest.TestCase):
    def test_at_the_top_of_the_file(self):
        for verb, (top, _cls) in BARE.items():
            if top is None:
                continue
            with self.subTest(verb=verb):
                msg = _refused(self, f"@{verb}\ndef reage({top}):\n    st.log.append(1)\n")
                if not verb.startswith("collide"):
                    self.assertIn("reage", msg)
                    self.assertIn(f"@{verb}(", msg)

    def test_in_a_class_body(self):
        for verb, (_top, cls) in BARE.items():
            if cls is None:
                continue
            with self.subTest(verb=verb):
                msg = _refused(self, (
                    f"class Bola(Circle, radius=10):\n"
                    f"    @{verb}\n"
                    f"    def reage({cls}):\n"
                    f"        st.log.append(1)\n"
                    f"Bola()\n"))
                self.assertIn("reage", msg)
                self.assertIn(f"@{verb}(", msg)

    def test_in_an_act_class_body(self):
        for verb in ("every", "after", "when", "on_change"):
            with self.subTest(verb=verb):
                msg = _refused(self, (
                    f"class Fase(Act):\n"
                    f"    @{verb}\n"
                    f"    def reage({BARE[verb][1]}):\n"
                    f"        pass\n"))
                self.assertIn("reage", msg)

    def test_the_entity_timer_forms(self):
        for verb in ("every", "after"):
            with self.subTest(verb=verb):
                msg = _refused(self, (
                    f"class Bola(Circle, radius=10):\n"
                    f"    def setup(self):\n"
                    f"        @self.{verb}\n"
                    f"        def pisca():\n"
                    f"            pass\n"
                    f"Bola()\n"))
                self.assertIn(f"@self.{verb}(", msg)

    def test_a_call_missing_its_interval(self):
        msg = _refused(self, "def spawn():\n    pass\nevery(spawn)\n")
        self.assertIn("spawn", msg)

    def test_the_bare_forms_that_are_the_form_still_work(self):
        log, _ns = _run(self, '''
class Tiro(Circle, radius=4):
    @leave_playfield
    def sumiu(self):
        st.log.append("saiu")

    @on_mode
    def voando(self):
        self.move_by(0, 0)

Tiro().mode = Tiro.voando
''')
        self.assertEqual(log, [])


class TestTheArgumentsThatAreFunctionsStillWork(unittest.TestCase):
    """The bare check never fires on a real argument that is a function."""

    def test_named_condition_kept_decorator_and_named_mode(self):
        log, _ns = _run(self, '''
def acabou():
    return st.fim

st.fim = False

@when(acabou)
def fim():
    st.log.append("fim")

guarda = on_change(lambda: st.fim)    # made now, placed later

@guarda
def mudou(v):
    st.log.append(("mudou", v))

class Heroi(Circle, radius=10):
    @on_mode
    def andando(self):
        pass

    @exit_mode(andando)
    def parou(self):
        st.log.append("parou")

st.fim = True
''', steps=2)
        self.assertIn("fim", log)
        self.assertIn(("mudou", True), log)

    def test_timers_with_their_arguments(self):
        log, _ns = _run(self, '''
@every(0.01)
def tique():
    st.log.append("every")

def spawn():
    st.log.append("call")

every(0.01, spawn)

class Bola(Circle, radius=10):
    @every(0.01)
    def pisca(self):
        st.log.append("method")

Bola()
''', steps=3)
        for kind in ("every", "call", "method"):
            self.assertIn(kind, log)


class TestPointerWithoutTargets(unittest.TestCase):
    def test_empty_parentheses_raise(self):
        for verb in POINTER:
            with self.subTest(verb=verb):
                msg = _refused(self, f"@{verb}()\ndef reage(t):\n    pass\n")
                self.assertIn(f"@{verb}(bola)", msg)


class TestPointerInAClassBody(unittest.TestCase):
    def test_on_a_shape_names_the_class_hook(self):
        from scena.interaction import _CLASS_HOOK
        for verb in POINTER:
            with self.subTest(verb=verb):
                msg = _refused(self, (
                    f"bolas = group['bolas']\n"
                    f"class Bola(Circle, radius=10, group='bolas'):\n"
                    f"    @{verb}(bolas)\n"
                    f"    def reage(self):\n"
                    f"        pass\n"
                    f"Bola()\n"))
                self.assertIn(_CLASS_HOOK[verb], msg)

    def test_in_an_act_points_at_setup(self):
        msg = _refused(self, '''
botao = Button(label="Jogar")
class Menu(Act):
    @click(botao)
    def jogar(self):
        pass
''')
        self.assertIn("inside setup()", msg)

    def test_the_fixes_the_message_names_work(self):
        log, _ns = _run(self, '''
class Bola(Circle, radius=10):
    def setup(self):
        self.on_click = self.tocou

    def tocou(self):
        st.log.append("tocou")

class Menu(Act):
    def setup(self):
        self.botao = Button(label="Jogar")

        @click(self.botao)
        def jogar():
            st.log.append("jogar")

bola = Bola()
st.log.append((bola.clickable, bola.on_click.__name__))
''')
        self.assertIn((True, "tocou"), log)


if __name__ == "__main__":
    unittest.main()
