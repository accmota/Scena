"""A key from ``on_key_*`` written into a field (IN2 in Testing Design).

``on_key_down(key)`` receives a ``KeyName``: a ``str`` whose ``==`` raises on a
string the handler can never deliver (``key == "ESCAPE"``). A field write's
change check (``old != new``) compared the old value with the key the same
way, so ``st.nome = key`` over ``"x"`` and ``t.text = key`` over ``"Aperte"``
raised. A field now stores the key as a plain ``str``; a key nested in a
tuple / list / dict (not unwrapped) reads as "changed" in the change check.

    python tests/run_tiers.py focused test_key_name_fields
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glfw  # noqa: E402

from scena import (  # noqa: E402
    Button, Circle, CheckBox, Rect, Slider, Sprite, Text, TextInput, st,
)
from scena import input as scena_input  # noqa: E402
from scena import state as scena_state  # noqa: E402
from scena.input import KeyName  # noqa: E402
from scena.state import KeyNameMismatch  # noqa: E402
from tests.input_driver import input_driver  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402
from tests.system_support import system_world  # noqa: E402

setUpModule, tearDownModule = module_sweep()

FRAME = 1 / 60
# Old values a field may hold before the key arrives: a case variant of a key
# ("x" → "on_key receives 'X'"), a word that is no key ("unknown key"), "".
OLD_STRINGS = ("x", "Aperte", "")


def _key(name="X"):
    return KeyName(name)


def _st_cell(old):
    st.nome = old
    return (lambda v: setattr(st, "nome", v)), (lambda: st.nome)


def _st_cell_bound_to_text_input(old):
    st.nome = old
    TextInput(st["nome"])
    return (lambda v: setattr(st, "nome", v)), (lambda: st.nome)


def _text(old):
    t = Text(old or " ", center=(100, 100))
    t.text = old
    return (lambda v: setattr(t, "text", v)), (lambda: t["text"].value)


def _text_linked(old):
    st.fonte = old
    t = Text(" ", center=(100, 100))
    t["text"] @= lambda: st.fonte
    return (lambda v: setattr(st, "fonte", v)), (lambda: t["text"].value)


def _ink(old):
    r = Rect(center=(100, 100), width=20, height=20)
    r.rotulo = old
    return (lambda v: setattr(r, "rotulo", v)), (lambda: r.rotulo)


def _ink_first_write(old):
    r = Rect(center=(100, 100), width=20, height=20)
    return (lambda v: setattr(r, "rotulo", v)), (lambda: r.rotulo)


def _button_label(old):
    st.b = False
    b = Button(st["b"], label=old or " ")
    b.label = old
    return (lambda v: setattr(b, "label", v)), (lambda: b.label)


def _text_input_text(old):
    st.campo = old
    box = TextInput(st["campo"])
    return (lambda v: setattr(box, "text", v)), (lambda: box.text)


def _text_input_placeholder(old):
    st.campo2 = ""
    box = TextInput(st["campo2"], placeholder=old)
    return (lambda v: setattr(box, "placeholder", v)), (lambda: box.placeholder)


# Every kind of field that does a change check (or stores author text).
WRITERS = {
    "st cell": _st_cell,
    "st cell bound to a TextInput": _st_cell_bound_to_text_input,
    "Text.text": _text,
    "Text.text linked to an st cell": _text_linked,
    "ink field": _ink,
    "ink field, first write": _ink_first_write,
    "Button.label": _button_label,
    "TextInput.text": _text_input_text,
    "TextInput.placeholder": _text_input_placeholder,
}


class TestAKeyEntersEveryField(unittest.TestCase):

    def test_a_key_written_over_any_string_is_stored_as_a_plain_str(self):
        with system_world(draw=False) as w:
            for label, make in WRITERS.items():
                for old in OLD_STRINGS:
                    with self.subTest(field=label, old=old):
                        write, read = make(old)
                        write(_key("X"))
                        got = read()
                        self.assertIs(type(got), str)
                        self.assertEqual(got, "X")
                        # Data now: an author compare with any string is a str compare.
                        self.assertFalse(got == "nenhuma")
                        self.assertTrue(got != "ESCAPE")
                        write(_key("X"))            # same key again
                        write(_key("SPACE"))        # another key
                        write(old)                  # back to the plain string
                        self.assertEqual(read(), old)
                        w.step(1, dt=FRAME)

    def test_a_key_nested_in_a_value_is_a_change(self):
        # Not unwrapped (no deep scan); the change check reads the mismatch
        # as "changed" — it only raises when the strings differ.
        with system_world(draw=False):
            r = Rect(center=(100, 100), width=20, height=20)
            for old, new in (
                (("", "x"), ("", _key("X"))),
                (["x"], [_key("X")]),
                ({"a": "Aperte"}, {"a": _key("X")}),
            ):
                with self.subTest(old=old):
                    st.combo = old
                    st.combo = new
                    self.assertEqual(st.combo, new)
                    st.combo = old
                    self.assertEqual(st.combo, old)
                    if isinstance(old, tuple):
                        r.combo = old
                        r.combo = new
                        self.assertEqual(r.combo, new)
                        r.combo = old
                        self.assertEqual(r.combo, old)

    def test_a_cell_created_from_a_key_holds_a_plain_str(self):
        with system_world(draw=False):
            st.nova_tecla = _key("SPACE")
            self.assertIs(type(st.nova_tecla), str)
            st.nova_tecla = "nenhuma"
            t = Text(_key("A"), center=(100, 100))
            self.assertIs(type(t["text"].value), str)
            t.text = "Aperte"


class TestEveryStrFieldTakesAKey(unittest.TestCase):
    """Class guard: any public field that holds a ``str`` takes a key.

    A new widget or shape field that stores author text joins the sweep by
    itself. The write may refuse "X" as a value (a layer, a blend name), but
    never with the key's own mismatch, and what it stores is a plain ``str``.
    """

    def _instances(self):
        st.sw_b = False
        st.sw_t = "x"
        st.sw_n = 0.5
        return {
            "Text": Text("Aperte", center=(100, 100)),
            "Rect": Rect(center=(100, 100), width=20, height=20),
            "Circle": Circle(center=(100, 100), radius=10),
            "Sprite": Sprite(center=(100, 100)),
            "Button": Button(st["sw_b"], label="Ok"),
            "CheckBox": CheckBox(st["sw_b"], label="Ok"),
            "TextInput": TextInput(st["sw_t"], placeholder="nome", label="Nome"),
            "Slider": Slider(st["sw_n"], label="Vol"),
        }

    def test_sweep(self):
        swept = 0
        with system_world(draw=False) as w:
            for cname, obj in self._instances().items():
                for name in dir(obj):
                    if name.startswith("_"):
                        continue
                    try:
                        before = getattr(obj, name)
                    except Exception:
                        continue
                    if isinstance(before, scena_state.Attribute):
                        before = before.value
                    if not isinstance(before, str):
                        continue
                    for key in ("X", "SPACE"):
                        with self.subTest(obj=cname, field=name, key=key):
                            try:
                                setattr(obj, name, _key(key))
                            except KeyNameMismatch as exc:
                                self.fail(f"{cname}.{name} = key compared loudly: {exc}")
                            except (TypeError, ValueError, AttributeError):
                                continue            # the field refuses "X" itself
                            got = getattr(obj, name)
                            if isinstance(got, scena_state.Attribute):
                                got = got.value
                            self.assertNotIsInstance(got, KeyName)
                            swept += 1
                            setattr(obj, name, before)
                w.step(1, dt=FRAME)
        self.assertGreaterEqual(swept, 8, "the sweep found no str field to write")


class TestTheHandlerKeepsItsTypoCheck(unittest.TestCase):

    def test_comparing_the_key_with_a_misspelled_name_still_raises(self):
        key = _key("A")
        for bad, fix in (("ESCAPE", "ESC"), ("a", "'A'"), ("Aperte", "unknown key")):
            with self.subTest(bad=bad):
                with self.assertRaises(KeyNameMismatch) as ctx:
                    key == bad  # noqa: B015
                self.assertIn(fix, str(ctx.exception))
        self.assertTrue(issubclass(KeyNameMismatch, ValueError))


class TestThroughARealKeyPress(unittest.TestCase):
    """The two repros of IN2, through the framework's own GLFW handler."""

    def test_on_key_down_writes_the_key_into_fields(self):
        with system_world(draw=True) as w, input_driver(w) as d:
            st.nome = "x"
            t = Text("Aperte", center=(200, 150))
            r = Rect(center=(100, 100), width=20, height=20)
            r.ultima = "nenhuma"
            seen = []
            cm = w.fw.canvas_manager
            saved = cm.on_key_down

            def on_key_down(key):
                self.assertIsInstance(key, KeyName)
                st.nome = key
                t.text = key
                r.ultima = key
                seen.append(key == "X")

            try:
                cm.on_key_down = on_key_down
                d.press(glfw.KEY_X)
                d.release(glfw.KEY_X)
                w.step(2, dt=FRAME)
            finally:
                cm.on_key_down = saved
            self.assertEqual(seen, [True])
            self.assertEqual((st.nome, t["text"].value, r.ultima), ("X", "X", "X"))
            self.assertTrue(r.ultima != "nenhuma")


class TestCanaries(unittest.TestCase):
    """Each guard fails when its half of the fix is taken out."""

    def test_without_the_unwrap_the_field_keeps_the_loud_key(self):
        # The write survives (the change check reads the mismatch), but the
        # field holds the KeyName and the author's later compare raises.
        with system_world(draw=False), mock.patch.object(scena_state, "_KEY_NAME", None):
            st.nome = "x"
            st.nome = _key("X")
            self.assertIsInstance(st.nome, KeyName)
            with self.assertRaises(KeyNameMismatch):
                st.nome != "nenhuma"  # noqa: B015

    def test_without_the_mismatch_class_the_nested_key_raises(self):
        with system_world(draw=False), \
                mock.patch.object(scena_input, "KeyNameMismatch", ValueError):
            st.combo = ("", "x")
            with self.assertRaises(ValueError):
                st.combo = ("", _key("X"))


if __name__ == "__main__":
    unittest.main()
