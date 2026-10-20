"""``st.key`` reads the cell's value; ``st["key"]`` is the cell (0.8.0).

Before 0.8.0 the dot read returned the cell (an ``Attribute``), so a value
that Python compares by identity or by type silently misbehaved:
``st.mic is None`` was always False, ``best = st.score`` followed the score,
``type(st.n)`` was ``Attribute``, ``match st.mic: case None`` never matched.
An Entity field (``ship.hp``) already read the value, so the two disagreed.

Bug class guarded here: **a State read that hands out something other than
the value**, and **a binding site that silently accepts the value where it
needs the cell**. Each binding API takes ``st["key"]`` and refuses the value
with the bracket spelling in the message; the completeness check fails when a
new widget with a ``cell`` parameter is not in the matrix.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scena  # noqa: E402
from scena import (  # noqa: E402
    Button, CheckBox, Circle, DropDown, Entity, Menu, Slider, State, Text,
    TextInput, Vec2, init, on_change, tween, until, when,
)
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.state import Attribute, FieldRef, get_scena_system  # noqa: E402
from scena.uiwidget import _NO_CELL  # noqa: E402

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()


class _Marker:
    """An author object stored in a cell (compared by identity)."""


def _payloads():
    """(label, value) pairs that cover every way Python compares a value."""
    return [
        ("None", None), ("True", True), ("False", False), ("int", 3),
        ("float", 1.5), ("str", "abc"), ("tuple", (1, 2)), ("list", [1, 2]),
        ("dict", {"a": 1}), ("Vec2", Vec2(1, 2)), ("object", _Marker()),
    ]


class EngineCase(unittest.TestCase):
    def setUp(self):
        init(width=800, height=600)
        self.wm = ScenaFramework.get_instance().widget_manager
        self._owned = []

    def tearDown(self):
        if self.wm.focused_widget in self._owned:
            self.wm.set_focus(None)
        for obj in reversed(self._owned):
            try:
                obj.destroy()
            except Exception:
                pass
        self._owned.clear()

    def track(self, obj):
        self._owned.append(obj)
        return obj


class TestDotReadIsTheValue(EngineCase):
    """``st.key`` is the stored object itself, in every bag, like an ink field."""

    def test_every_payload_kind_reads_back_as_itself(self):
        for bag in (scena.st, State(name="hud")):
            for label, value in _payloads():
                with self.subTest(bag=bag.name, payload=label):
                    setattr(bag, "rv_" + label, value)
                    got = getattr(bag, "rv_" + label)
                    self.assertIs(type(got), type(value))
                    self.assertNotIsInstance(got, (Attribute, FieldRef))
                    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
                        self.assertIs(got, value)
                    else:
                        self.assertEqual(got, value)

    def test_identity_checks_work(self):
        st = State(name="st")
        st.mic = None
        self.assertTrue(st.mic is None)
        target = self.track(Circle())
        st.alvo = target
        self.assertTrue(st.alvo is target)
        st.alvo = None
        self.assertFalse(st.alvo is target)

    def test_match_case_sees_the_value(self):
        st = State(name="st")
        for value, want in ((None, "none"), (True, "true"), ("menu", "menu")):
            st.estado = value
            match st.estado:
                case None:
                    got = "none"
                case True:
                    got = "true"
                case "menu":
                    got = "menu"
                case _:
                    got = "other"
            self.assertEqual(got, want)

    def test_a_read_kept_in_a_variable_is_a_copy(self):
        st = State(name="st")
        st.score = 3
        recorde = st.score
        historico = [st.score]
        st.score = 10
        historico.append(st.score)
        self.assertEqual(recorde, 3)
        self.assertEqual(historico, [3, 10])

    def test_a_linked_cell_reads_its_value(self):
        st = State(name="st")
        c = self.track(Circle(radius=4))
        st["metade"] @= lambda: c.radius / 2
        self.assertIs(type(st.metade), float)
        self.assertEqual(st.metade, 2.0)
        c.radius = 10
        self.assertEqual(st.metade, 5.0)

    def test_a_value_can_be_a_dict_key(self):
        st = State(name="st")
        st.modo = "fácil"
        self.assertEqual({"fácil": 1}[st.modo], 1)

    def test_matches_an_entity_field(self):
        st = State(name="st")
        e = self.track(Entity())
        for label, value in _payloads():
            with self.subTest(payload=label):
                setattr(st, "pf_" + label, value)
                setattr(e, "pf_" + label, value)
                self.assertIs(type(getattr(st, "pf_" + label)), type(getattr(e, "pf_" + label)))
                self.assertEqual(getattr(st, "pf_" + label) is value,
                                 getattr(e, "pf_" + label) is value)

    def test_missing_cell_still_raises_with_the_fix(self):
        st = State(name="st")
        st.score = 0
        with self.assertRaises(AttributeError) as cm:
            st.scroe
        self.assertIn("st has no cell 'scroe'", str(cm.exception))
        self.assertIn("score", str(cm.exception))

    def test_bracket_is_the_cell(self):
        st = State(name="st")
        st.score = 7
        ref = st["score"]
        self.assertIsInstance(ref, FieldRef)
        self.assertEqual(ref.value, 7)
        self.assertIsInstance(st._resolve_cell("score"), Attribute)


class TestFormulasStillFindTheCell(EngineCase):
    """``lambda: st.a`` reads the value, but the link depends on the cell."""

    def test_formula_over_st_updates(self):
        st = State(name="st")
        st.a = 2
        c = self.track(Circle())
        c["radius"] @= lambda: st.a * 3
        self.assertEqual(c.radius, 6)
        st.a = 5
        self.assertEqual(c.radius, 15)

    def test_chain_into_the_payload_depends_on_the_cell(self):
        st = State(name="st")
        st.pos = Vec2(1, 2)
        c = self.track(Circle())
        c["radius"] @= lambda: st.pos.x + 1
        self.assertEqual(c.radius, 2)
        st.pos = Vec2(9, 0)                 # a new payload: the link follows the cell
        self.assertEqual(c.radius, 10)

    def test_formula_reading_a_missing_cell_names_it(self):
        st = State(name="st")
        st.vidas = 3
        c = self.track(Circle())
        with self.assertRaises(AttributeError) as cm:
            c["radius"] @= lambda: st.vidsa * 2
        self.assertIn("has no cell 'vidsa'", str(cm.exception))


class TestInPlaceChanges(EngineCase):
    """``st.pos`` is the held Vec2 / list: in-place changes and the links."""

    def test_augmented_vec2_write_reaches_links(self):
        st = State(name="st")
        st.pos = Vec2(1, 2)
        c = self.track(Circle())
        c["center"] @= lambda: st.pos
        st.pos += Vec2(10, 0)
        self.assertEqual((c.center.x, c.center.y), (11.0, 2.0))
        st.pos -= (1, 1)
        self.assertEqual((c.center.x, c.center.y), (10.0, 1.0))

    def test_augmented_list_write_reaches_watchers_and_links(self):
        st = State(name="st")
        st.itens = [1]
        c = self.track(Circle())
        c["radius"] @= lambda: len(st.itens) * 10
        seen = []
        on_change(st["itens"])(lambda value: seen.append(list(value)))
        st.itens += [2]
        self.assertEqual(c.radius, 20)
        get_scena_system().flush()
        self.assertEqual(seen[-1], [1, 2])

    def test_writing_into_the_held_vec2_reaches_links(self):
        st = State(name="st")
        st.pos = Vec2(1, 2)
        c = self.track(Circle())
        c["center"] @= lambda: st.pos
        st.pos.x = 5
        self.assertEqual((c.center.x, c.center.y), (5.0, 2.0))
        st.pos.y = 6
        self.assertEqual((c.center.x, c.center.y), (5.0, 6.0))

    def test_a_replaced_payload_is_a_free_vec2_again(self):
        st = State(name="st")
        old = Vec2(1, 2)
        st.pos = old
        st.pos = Vec2(3, 4)
        c = self.track(Circle())
        c["center"] @= lambda: st.pos
        old.x = 7                            # no longer held: a plain Vec2
        self.assertEqual(old.x, 7)
        self.assertEqual((st.pos.x, c.center.x), (3.0, 3.0))
        for hook in ("_write_field", "_refuse_author_write", "update", "_held_payload"):
            self.assertNotIn(hook, vars(old))
        self.assertFalse(old._needs_pull_invalidate)
        st.pos.x = 0
        self.assertEqual(c.center.x, 0.0)

    def test_other_vec2s_are_untouched(self):
        free = Vec2(1, 2)
        free.x = 5
        self.assertEqual(free.x, 5)
        for hook in ("_write_field", "_refuse_author_write", "update", "_held_payload"):
            self.assertNotIn(hook, vars(free))

    def test_reassigning_an_object_payload_is_harmless(self):
        st = State(name="st")
        c = self.track(Circle())
        st.alvo = c
        st.alvo = c                          # same object again: no error
        st.alvo.radius = 12                  # an object is edited in place
        self.assertEqual(c.radius, 12)


# --- binding sites --------------------------------------------------------------

def _widget_cases():
    """name → (factory(cell) for a bound widget, starting value)."""
    return {
        "Slider": (lambda cell: Slider(cell), 30.0),
        "CheckBox": (lambda cell: CheckBox(cell), True),
        "DropDown": (lambda cell: DropDown(cell, options=["a", "b"]), "b"),
        "TextInput": (lambda cell: TextInput(cell), "Ana"),
        "Button": (lambda cell: Button(cell, label="Fire"), 0.0),
        "Menu": (lambda cell: Menu(cell, options=["a", "b"]), "a"),
    }


class TestBindingSitesTakeTheCell(EngineCase):

    def test_every_cell_widget_is_covered(self):
        """A public class whose first parameter is a data ``cell`` is in the matrix.

        ``Pixelate(cell=5.0)`` is a pixel size, not a data cell: its
        annotation is a number."""
        found = set()
        for name in scena.__all__:
            obj = getattr(scena, name)
            if not isinstance(obj, type):
                continue
            try:
                params = list(inspect.signature(obj.__init__).parameters.values())
            except (TypeError, ValueError):
                continue
            if len(params) > 1 and params[1].name == "cell":
                hint = str(params[1].annotation)
                if params[1].default is _NO_CELL or "Attribute" in hint:
                    found.add(name)
        self.assertEqual(found, set(_widget_cases()))

    def test_bracket_cell_binds_both_ways(self):
        for name, (make, start) in _widget_cases().items():
            with self.subTest(widget=name):
                st = State(name="st")
                st.v = start
                w = self.track(make(st["v"]))
                self.assertIs(w.data, st._resolve_cell("v"))
                self.assertEqual(w.value, start)
                w.destroy()                  # one modal Menu at a time

    def test_the_value_raises_with_the_bracket_spelling(self):
        for name, (make, start) in _widget_cases().items():
            with self.subTest(widget=name):
                st = State(name="st")
                st.v = start
                with self.assertRaises(TypeError) as cm:
                    make(st.v)
                self.assertIn(f'{name}(st["', str(cm.exception))

    def test_a_caption_given_as_the_cell_names_label(self):
        """``Button("Contar")``: the text is the button's caption, not a cell
        (persona probes round 2, R2-4: the message only said "pass the cell
        with brackets")."""
        for make, kind in ((lambda v: Button(v), "Button"), (lambda v: CheckBox(v), "CheckBox"),
                           (lambda v: Slider(v), "Slider")):
            with self.subTest(widget=kind), self.assertRaises(TypeError) as cm:
                make("Contar")
            self.assertIn(f"{kind}(label='Contar')", str(cm.exception))

    def test_explicit_none_raises_and_omitted_cell_is_fine(self):
        # ``Menu(st.nave)`` while ``st.nave`` is still None would otherwise
        # leave the widget silently unbound.
        for name, (make, _start) in _widget_cases().items():
            with self.subTest(widget=name):
                with self.assertRaises(TypeError) as cm:
                    make(None)
                self.assertIn("leave the argument out", str(cm.exception))
        self.track(Slider())
        self.track(TextInput())

    def test_a_field_of_an_object_does_not_bind(self):
        c = self.track(Circle())
        with self.assertRaises(TypeError) as cm:
            Slider(c["radius"])
        self.assertIn("only a State cell binds here", str(cm.exception))

    def test_text_shows_a_cell_live_and_refuses_a_number(self):
        st = State(name="st")
        st.score = 3
        t = self.track(Text(st["score"]))
        st.score = 9
        self.assertEqual(t.value, 9)
        with self.assertRaises(TypeError) as cm:
            Text(st.score)
        self.assertIn('Text(st["score"])', str(cm.exception))
        self.track(Text(str(st.score)))      # a string snapshot is fine

    def test_watchers_take_the_cell(self):
        st = State(name="st")
        st.wave = 1
        st.alive = False
        st.pos = Vec2(0, 0)
        on_change(st["wave"])(lambda: None)
        when(st["alive"])(lambda: None)
        on_change(st["pos"])(lambda: None)
        for label, deco, value, want in (
            ("on_change(int)", on_change, st.wave, '@on_change(st["wave"])'),
            ("when(bool)", when, st.alive, '@when(st["alive"])'),
            ("on_change(Vec2)", on_change, st.pos, '@on_change(st["pos"])'),
        ):
            with self.subTest(case=label):
                with self.assertRaises(TypeError) as cm:
                    deco(value)(lambda: None)
                self.assertIn(want, str(cm.exception))

    def test_tween_until_and_links_name_the_bracket(self):
        st = State(name="st")
        st.t = 0.0
        c = self.track(Circle())
        with self.assertRaises(TypeError) as cm:
            tween(st.t, 1.0, time=1)
        self.assertIn('st["t"]', str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            until(st.t)
        self.assertIn('until(st["done"])', str(cm.exception))
        with self.assertRaises(TypeError) as cm:
            c["radius"] @= st.t
        self.assertIn("st['score']", str(cm.exception))
        c["radius"] @= st["t"]               # the cell links
        st.t = 4.0
        self.assertEqual(c.radius, 4.0)


class TestHeldVec2IsNotTheCell(EngineCase):
    """A Vec2 is a Container, so every door that takes a Container accepted
    ``st.pos`` (the held Vec2) where it needs the cell: it worked until the
    next ``st.pos = …`` replaced the payload, then went silently stale (the
    link stayed on the old Vec2, the tween moved it behind the cell's back).
    Each door refuses it with the bracket spelling; the cell still works."""

    def setUp(self):
        super().setUp()
        self.st = State(name="st")
        self.st.pos = Vec2(1, 2)
        self.st.x = 3.0

    def assert_refused(self, call, bracket):
        with self.assertRaises(TypeError) as cm:
            call()
        msg = str(cm.exception)
        self.assertIn(bracket, msg)
        self.assertIn("holds now, not the cell", msg)

    def test_every_door_refuses_the_held_vec2(self):
        st = self.st
        c = self.track(Circle())

        def link_target():
            st.pos @= (lambda: Vec2(st.x, 0))

        def link_source():
            c["center"] @= st.pos

        doors = {
            "@= target": (link_target, 'st["pos"] @= …'),
            "@= source": (link_source, '… @= st["pos"]'),
            "tween": (lambda: tween(st.pos, Vec2(10, 0), time=1), 'tween(st["pos"], …)'),
            "until": (lambda: until(st.pos), 'until(st["pos"])'),
        }
        for name, (call, bracket) in doors.items():
            with self.subTest(door=name):
                self.assert_refused(call, bracket)
        self.assertIsNone(vars(st.pos).get('_link'))   # nothing was linked
        self.assertEqual((st.pos.x, st.pos.y), (1.0, 2.0))

    def test_a_named_bag_spells_its_own_bracket(self):
        hud = State(name="hud")
        hud.alvo = Vec2(0, 0)
        self.assert_refused(lambda: tween(hud.alvo, Vec2(1, 1), time=1), 'tween(hud["alvo"], …)')

    def test_the_cell_links_and_follows_a_replaced_payload(self):
        st = self.st
        c = self.track(Circle())
        c["center"] @= st["pos"]
        st.pos = Vec2(50, 60)
        self.assertEqual((c.center.x, c.center.y), (50.0, 60.0))

    def test_a_vec2_that_left_the_cell_is_free(self):
        old = self.st.pos
        self.st.pos = Vec2(5, 5)
        c = self.track(Circle())
        c["center"] @= old                   # no longer held: an ordinary Vec2 source
        old.x = 9
        self.assertEqual(c.center.x, 9.0)


class TestCellCopiesAnObjectsVec2(EngineCase):
    """``st.v0 = ball.vel`` stored the ball's own Vec2, and the held-payload
    guard then sat on the ball's field: ``ball.vel = …`` (whose setter writes
    into that Vec2) raised an error naming ``st.v0`` (RA3). A cell holds a Vec2
    by value: an owned Vec2 is copied, like ``recorde = st.score``, and the
    cell's hooks sit on the copy."""

    def test_storing_a_field_vec2_snapshots_it(self):
        st = State(name="st")
        ball = self.track(Circle())
        ball.vel = Vec2(50, 0)
        st.v0 = ball.vel
        self.assertIsNot(st.v0, ball.vel)
        ball.vel = Vec2(3, 3)                # the ball's field stays writable
        self.assertEqual((ball.vel.x, ball.vel.y), (3.0, 3.0))
        self.assertEqual((st.v0.x, st.v0.y), (50.0, 0.0))
        st.v0.x = 1                          # the copy is the held payload
        self.assertEqual((st.v0.x, ball.vel.x), (1, 3.0))
        self.assertIsNone(ball.vel.__dict__.get("_held_payload"))

    def test_replacing_with_a_field_vec2_snapshots_it_too(self):
        st = State(name="st")
        st.v0 = Vec2(0, 0)
        ball = self.track(Circle())
        ball.vel = Vec2(7, 8)
        st.v0 = ball.vel
        ball.vel = Vec2(1, 1)
        self.assertEqual((st.v0.x, st.v0.y), (7.0, 8.0))

    def test_a_free_vec2_is_held_as_is(self):
        st = State(name="st")
        v = Vec2(1, 2)
        st.v = v
        self.assertIs(st.v, v)               # no copy where no one else owns it
        c = self.track(Circle())
        c["center"] @= lambda: st.v
        v.x = 3                              # another name for st.v
        self.assertEqual((st.v.x, c.center.x), (3, 3.0))


if __name__ == "__main__":
    unittest.main()
