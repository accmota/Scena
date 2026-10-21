"""An unknown read names the fix (persona probes PP, 0.9.0).

Bug class: a read of a name the object does not have (``chave.hide()``,
``bola.transform``, ``clock.tick(60)``) raised Python's bare "object has no
attribute", or a suggestion of a private engine name (``Did you mean:
'_tick'?``). Writes already named the fix (``bola.velocity = …`` → "Scena
spells it 'vel'"); reads now do too: the names other engines and Scratch use,
a field another kind owns, a close public name. A miss that nobody prints
(``hasattr``, ``getattr(x, name, None)``) builds no message.

    python tests/run_tiers.py focused test_read_hints
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scena import Circle, Entity, Rect, Sprite, Text, clock, init  # noqa: E402


def _read_error(obj, name) -> str:
    try:
        getattr(obj, name)
    except AttributeError as e:
        return str(e)
    raise AssertionError(f"{name} read without error")


class TestEntityReads(unittest.TestCase):

    def setUp(self):
        init(width=400, height=300)
        self.c = Circle(center=(50, 50), radius=10)
        self.addCleanup(self.c.destroy)

    def test_names_from_other_engines_and_scratch(self):
        for name, fix in (("hide", "visible = False"), ("show", "visible = True"),
                          ("kill", "destroy()"), ("remove", "destroy()"),
                          ("transform", ".center"), ("position", ".center"),
                          ("goto", "move_to("), ("glide", "time="),
                          ("point_towards", "heading("), ("look_at", "heading(")):
            msg = _read_error(self.c, name)
            self.assertIn(fix, msg, name)
            self.assertIn("Circle", msg, name)

    def test_a_field_another_kind_owns(self):
        self.assertIn("set_alpha", _read_error(self.c, "alpha"))
        self.assertIn("(a Text field)", _read_error(self.c, "font_size"))

    def test_a_close_public_name(self):
        self.assertIn("'radius'", _read_error(self.c, "raidus"))
        self.c.vidas = 3
        self.assertIn("'vidas'", _read_error(self.c, "vida"))

    def test_scenas_own_spelling(self):
        self.assertIn("'vel'", _read_error(self.c, "velocity"))

    def test_never_a_private_name(self):
        for name in ("tick", "rgistry", "constructed"):
            msg = _read_error(self.c, name)
            self.assertNotIn("'_", msg, name)

    def test_a_plain_miss_keeps_the_python_words(self):
        self.assertIn("'Circle' object has no attribute 'zzqx'", _read_error(self.c, "zzqx"))

    def test_a_traceback_names_attribute_error(self):
        import traceback
        try:
            self.c.hide()
        except AttributeError as e:
            text = "".join(traceback.format_exception_only(type(e), e))
        self.assertTrue(text.startswith("AttributeError: "), text)
        self.assertNotIn("_UnknownRead", text)

    def test_an_own_field_never_set_gets_no_far_fetched_hint(self):
        self.assertNotIn("'vel'", _read_error(self.c, "nivel"))

    def test_hasattr_and_getattr_default_still_work(self):
        self.assertFalse(hasattr(self.c, "hide"))
        self.assertIsNone(getattr(self.c, "hide", None))
        e = Entity()
        self.addCleanup(e.destroy)
        self.assertFalse(hasattr(e, "transform"))


class TestClockReads(unittest.TestCase):

    def test_tick_names_the_frame_loop_not_a_private_method(self):
        msg = _read_error(clock, "tick")
        self.assertNotIn("_tick", msg)
        self.assertIn("update(dt)", msg)
        self.assertIn("framerate", msg)

    def test_a_close_public_name(self):
        self.assertIn("'time'", _read_error(clock, "tme"))
        self.assertNotIn("'_", _read_error(clock, "tme"))

    def test_private_misses_stay_plain(self):
        self.assertFalse(hasattr(clock, "_no_such_thing"))


class TestPositionalTime(unittest.TestCase):
    """``move_to(1, 200, 100)`` (Scratch's "glide 1 s to x, y") got Python's
    "takes from 1 to 3 positional arguments but 4 were given": the count
    holds ``self``, and nothing says ``time=`` (persona probes PP). Every pose
    verb names the keyword, with the call written back."""

    def setUp(self):
        init(width=400, height=300)
        self.c = Circle(center=(50, 50), radius=10)
        self.addCleanup(self.c.destroy)

    def message(self, fn, *args):
        with self.assertRaises(TypeError) as cm:
            fn(*args)
        return str(cm.exception)

    def test_scratch_order_glide(self):
        msg = self.message(self.c.move_to, 1, 200, 100)
        self.assertIn("move_to(200, 100, time=1)", msg)
        self.assertNotIn("positional arguments", msg)

    def test_seconds_last(self):
        self.assertIn("move_to(200, 100, time=2)", self.message(self.c.move_to, 200, 100, 2))
        self.assertIn("move_by(10, 0, time=0.5)", self.message(self.c.move_by, 10, 0, 0.5))

    def test_turns_and_scales(self):
        self.assertIn("rotate_to(90, time=1)", self.message(self.c.rotate_to, 90, 1))
        self.assertIn("rotate_by(45, time=2)", self.message(self.c.rotate_by, 45, 2))
        self.assertIn("scale_to(2, time=1)", self.message(self.c.scale_to, 2, 1))
        self.assertIn("scale_by(0.5, time=1)", self.message(self.c.scale_by, 0.5, 1))

    def test_a_subclass_override_says_the_same(self):
        from scena import Line, Text
        ln = Line(p1=(0, 0), p2=(10, 0))
        t = Text("oi", center=(100, 100))
        self.addCleanup(ln.destroy)
        self.addCleanup(t.destroy)
        self.assertIn("rotate_to(90, time=1)", self.message(ln.rotate_to, 90, 1))
        self.assertIn("rotate_by(30, time=1)", self.message(t.rotate_by, 30, 1))
        self.assertIn("move_to(5, 5, time=1)", self.message(t.move_to, 1, 5, 5))

    def test_the_right_calls_still_work(self):
        self.c.move_to(200, 100)
        h = self.c.move_to(100, 100, time=1)
        h.cancel()
        self.c.rotate_by(10)
        self.c.scale_to(1.5)



class TestIntersectionsOfACurve(unittest.TestCase):
    """``intersections(line, track)`` listed the shapes it takes and stopped
    there; a teacher plotting y = x² as a Track could not go on (persona
    probes round 2, R2-5). The message names the route, and the route works."""

    def test_the_message_names_lines_between_spaced_points(self):
        from scena import Line, Track, intersections
        init(width=1000, height=700)
        curve = Track(points=[(100, 580), (500, 100), (900, 580)])
        level = Line(p1=(0, 280), p2=(1000, 280))
        self.addCleanup(curve.destroy)
        self.addCleanup(level.destroy)
        with self.assertRaises(TypeError) as cm:
            intersections(level, curve)
        self.assertIn("spaced_points", str(cm.exception))
        pts = curve.spaced_points(64)
        hits = []
        for a, b in zip(pts, pts[1:]):
            seg = Line(p1=a, p2=b)
            hits += intersections(level, seg)
            seg.destroy()
        self.assertEqual(len(hits), 2)


class TestForeignPoseWrites(unittest.TestCase):
    """``paddle.position = Vec2(40, 300)`` (Godot, Unity) became an own field
    nothing reads, while the read named ``.center`` (persona probes round 2,
    R2-7). The write names it too; a bare Entity keeps the name as its own."""

    def setUp(self):
        init(width=400, height=300)

    def test_a_shape_refuses_and_names_center_and_angle(self):
        from scena import Vec2
        r = Rect(center=(50, 50), width=20, height=100)
        self.addCleanup(r.destroy)
        for name, fix, value in (("position", "center", Vec2(40, 300)),
                                 ("global_position", "center", (40, 300)),
                                 ("rotation", "angle", 30), ("rotation_degrees", "angle", 30)):
            with self.subTest(name=name), self.assertRaises(AttributeError) as cm:
                setattr(r, name, value)
            self.assertIn(f"'{fix}'", str(cm.exception))

    def test_a_bare_entity_keeps_it(self):
        e = Entity()
        self.addCleanup(e.destroy)
        e.position = 3
        self.assertEqual(e.position, 3)


class TestTimerGivenACall(unittest.TestCase):
    """``every(0.6, spawn())`` ran ``spawn`` once and returned the decorator,
    silently: no wave ever came (persona probes round 2, R2-8). An explicit
    ``None`` where the function goes now raises; the decorator form (the
    function omitted) and ``on_done=`` stay."""

    def test_a_call_result_raises_naming_the_function_form(self):
        from scena import after, every, Entity
        init(width=200, height=200)
        e = Entity()
        self.addCleanup(e.destroy)
        for fn in (lambda: every(0.6, None), lambda: after(1, None),
                   lambda: e.every(0.6, None), lambda: e.after(1, None)):
            with self.assertRaises(TypeError) as cm:
                fn()
            self.assertIn("without parentheses", str(cm.exception))

    def test_the_decorator_and_keyword_forms_still_work(self):
        from scena import after, every
        init(width=200, height=200)

        @every(0.5)
        def tique():
            pass

        h = after(1, on_done=lambda: None)
        tique.handle.cancel()
        h.cancel()


class TestModeBodyCalledByHand(unittest.TestCase):
    """``self.mode = self.phase2()`` ran the body as a helper (its ``every``
    outlived the mode) and set the mode to ``None``, silently (persona probes
    round 2, R2-9). A sync mode body is entered only by the engine."""

    def test_a_direct_call_raises_and_the_mode_setter_still_enters(self):
        from scena import Rect, on_mode
        init(width=400, height=300)
        ran = []

        class Boss(Rect):
            def setup(self):
                self.mode = self.phase1

            @on_mode
            def phase1(self):
                ran.append("phase1")

            @on_mode
            def phase2(self):
                ran.append("phase2")

        b = Boss(center=(200, 150), width=40, height=20)
        self.addCleanup(b.destroy)
        self.assertEqual(ran, ["phase1"])
        with self.assertRaises(TypeError) as cm:
            b.mode = b.phase2()
        self.assertIn("self.mode = self.phase2", str(cm.exception))
        self.assertEqual(ran, ["phase1"])
        b.mode = b.phase2
        self.assertEqual(ran, ["phase1", "phase2"])
        self.assertEqual(b.mode, b.phase2)

    def test_a_plain_function_mode_still_gets_its_owner(self):
        from scena import Entity, on_mode
        init(width=400, height=300)
        got = []

        @on_mode
        def calm(e):
            got.append(e)

        @on_mode
        def idle():
            got.append("idle")

        e = Entity()
        self.addCleanup(e.destroy)
        e.mode = calm
        e.mode = idle
        self.assertEqual(got, [e, "idle"])


class TestMissingCellAfterARename(unittest.TestCase):
    """``st.pontos`` renamed to ``st.placar`` in one place only: "Create it
    first" made a second cell the screen never showed (persona probes round 3,
    R3-5). With no close name, the message lists the cells that exist."""

    def test_the_existing_cells_are_listed(self):
        from scena.state import State
        bag = State(name="st")
        bag.placar = 0
        bag.energia = 3
        with self.assertRaises(AttributeError) as cm:
            bag.pontos
        msg = str(cm.exception)
        self.assertIn("st has: energia, placar", msg)
        self.assertIn("renamed", msg)

    def test_a_close_name_is_still_the_hint(self):
        from scena.state import State
        bag = State(name="st")
        bag.pontos = 0
        with self.assertRaises(AttributeError) as cm:
            bag.ponto
        self.assertIn("Did you mean 'pontos'", str(cm.exception))


class TestAClassKeywordGroupIsKnown(unittest.TestCase):
    """``class Inimigo(Rect, group="inimigos")``, its first enemy spawned a
    second later, and ``@when(lambda: group["inimigos"].empty)`` warned "No
    group 'inimigos'. Did you mean 'tiros_inimigos'?" in a correct game
    (persona probes round 3, R3-6)."""

    def test_no_near_miss_warning(self):
        import warnings
        from scena import Rect, group
        init(width=200, height=200)

        class Inimigo(Rect, width=20, height=20, group="pp_inimigos"):
            pass

        class TiroInimigo(Rect, width=4, height=10, group="pp_tiros_inimigos"):
            pass

        t = TiroInimigo(center=(50, 50))
        self.addCleanup(t.destroy)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            self.assertTrue(group["pp_inimigos"].empty)


class TestVelGivenANumber(unittest.TestCase):
    """``self.vel = 150`` (a speed of one's own): the message said "vel = None
    stops physics motion" (nothing moves by vel) and left out the Guia's own
    fix, another name (persona probes round 3, R3-7)."""

    def test_the_message_names_another_name_and_no_physics_motion(self):
        init(width=200, height=200)
        c = Circle(center=(10, 10), radius=3)
        self.addCleanup(c.destroy)
        with self.assertRaises(TypeError) as cm:
            c.vel = 150
        msg = str(cm.exception)
        self.assertIn("self.rapidez = 150", msg)
        self.assertIn("never moves an object by it", msg)
        self.assertNotIn("physics motion", msg)


class TestBoxGivenNone(unittest.TestCase):
    """``Rect(box=grade.cell_at(0, 0))`` (a column/row given to cell_at, which
    takes a point) said "box= requires a Box": the author passed what they
    took for a cell (persona probes round 3, R3-8)."""

    def test_the_message_says_none_and_names_cell(self):
        from scena import Box
        init(width=800, height=800)
        grade = Box(center=(400, 400), width=480, height=480).grid(3, 3)
        with self.assertRaises(TypeError) as cm:
            Rect(box=grade.cell_at(-1000, -1000))
        msg = str(cm.exception)
        self.assertIn("got None", msg)
        self.assertIn("grid.cell(col, row)", msg)


class TestRoundThreeMessages(unittest.TestCase):
    """Persona probes round 3: the browser's and physics engines' words get
    Scena's (R3-12, R3-13, R3-14); a formula with no Scena value names the
    form the author wrote (R3-15); a hand-made map is pointed at json.load
    (R3-10)."""

    def setUp(self):
        init(width=200, height=200)

    def test_foreign_method_reads(self):
        r = Rect(center=(10, 10), width=5, height=5)
        self.addCleanup(r.destroy)
        for name, fix in (("addEventListener", "on_click"), ("apply_impulse", "vel"),
                          ("apply_force", "vel"), ("setPosition", "center")):
            self.assertIn(fix, _read_error(r, name), name)

    def test_physics_keywords_on_a_constructor(self):
        with self.assertRaises(TypeError) as cm:
            Circle(center=(1, 1), radius=3, mass=10, bounce=0.2)
        msg = str(cm.exception)
        self.assertIn("ball.mass = 10", msg)
        self.assertIn("resolve(", msg)

    def test_resolve_friction(self):
        from scena import resolve
        with self.assertRaises(TypeError) as cm:
            resolve("pp_a", "pp_b", friction=0.4)
        msg = str(cm.exception)
        self.assertIn("no friction", msg)
        self.assertIn("bounce=", msg)

    def test_a_text_lambda_over_plain_variables(self):
        pontos = 3
        with self.assertRaises(TypeError) as cm:
            Text(lambda: f"Pontos {pontos}", center=(50, 50))
        msg = str(cm.exception)
        self.assertIn("no reactive sources", msg)
        self.assertIn("Text(lambda", msg)
        self.assertIn("st.pontos", msg)

    def test_a_hand_made_map_is_pointed_at_json_load(self):
        from scena.level_format import LevelFormatError, parse
        for data in ({"mapa": ["#####"]}, {"format": "scena-level", "mapa": ["#####"]}):
            with self.assertRaises(LevelFormatError) as cm:
                parse(data, source="mine.json")
            self.assertIn("json.load", str(cm.exception))


class TestRoundFourMessages(unittest.TestCase):
    """Persona probes round 4: "create hidden, show later" written as a
    constructor keyword (R4-2), and a ``move_by`` game with ``bounce=`` told
    to give its STATIC wall a ``.vel`` (R4-4)."""

    def setUp(self):
        init(width=200, height=200)

    def test_visible_on_a_constructor_names_the_next_line(self):
        for make in (lambda: Rect(center=(1, 1), width=4, height=4, visible=False),
                     lambda: Circle(center=(1, 1), radius=2, visible=False),
                     lambda: Text("oi", visible=False),
                     lambda: Sprite("k-rolling-ball/ball_red_large.png", visible=False)):
            with self.assertRaises(TypeError) as cm:
                make()
            msg = str(cm.exception)
            self.assertIn(".visible = False", msg)
            self.assertIn("Point, Track", msg)

    def _walk_into_the_wall(self, bounce):
        import warnings
        from scena import resolve, STATIC
        from scena.collision import _vel_missing_warned, get_collision_system
        _vel_missing_warned.clear()
        wall = Rect(center=(120, 100), width=20, height=200, group="r44_parede")
        wall.mass = STATIC
        hero = Rect(center=(100, 100), width=20, height=20, group="r44_heroi")
        self.addCleanup(wall.destroy)
        self.addCleanup(hero.destroy)
        resolve("r44_heroi", "r44_parede", bounce=bounce)
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            for _ in range(5):
                hero.move_by(3, 0)
                get_collision_system().step()
        return hero, wall, [str(w.message) for w in ws if ".vel" in str(w.message)]

    def test_a_move_by_body_on_a_bounce_pair_is_told_and_the_wall_is_not(self):
        hero, wall, msgs = self._walk_into_the_wall(0.5)
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("Drop bounce=", msgs[0])
        self.assertNotIn(repr(wall), msgs[0])

    def test_a_move_by_game_with_bounce_zero_is_quiet(self):
        hero, _wall, msgs = self._walk_into_the_wall(0)
        self.assertEqual(msgs, [])
        self.assertLessEqual(hero.center.x, 100.5)      # it still stops at the wall


class TestOnCollideWithNoPartner(unittest.TestCase):
    """R5-7 (persona probes, round 5): an Alien's ``on_collide`` and a plain
    ``Rect`` bullet never met, silently: ``on_collide`` tests enrolled bodies
    only. A second into play, when every enrolled body is one its own hook
    enrolled and no contact came, one warning names how the other side joins."""

    def setUp(self):
        from scena.collision import reset_collision_system
        init(width=600, height=800)
        reset_collision_system()
        self.addCleanup(reset_collision_system)
        clock._time = 0.0

    def _play(self, bullet_joins=False):
        import warnings
        from scena.collision import get_collision_system

        class Alien(Rect):
            def on_collide(self, other):
                pass

        aliens = [Alien(center=(100 + 60 * i, 500), width=30, height=24) for i in range(3)]
        bullet = Rect(center=(300, 84), width=4, height=16, group="bullet")
        if bullet_joins:
            bullet.collidable = True
        for o in aliens + [bullet]:
            self.addCleanup(o.destroy)
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            for _ in range(70):
                clock._time += 1 / 60
                get_collision_system().step()
        return [str(w.message) for w in ws if "on_collide runs only" in str(w.message)]

    def test_a_lonely_on_collide_is_told_once(self):
        msgs = self._play()
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("Alien.on_collide", msgs[0])
        self.assertIn("collidable = True", msgs[0])

    def test_an_enrolled_partner_is_quiet(self):
        self.assertEqual(self._play(bullet_joins=True), [])


class TestRoundFiveMessages(unittest.TestCase):
    """Persona probes round 5: a limit names the value it got (R5-5: a
    computed ``60 // 120`` is 0); ``sides=`` is pointed at ``n=``, not at
    ``side=``, another quantity (R5-6)."""

    def setUp(self):
        init(width=400, height=300)

    def test_limits_name_the_value(self):
        from scena import after, every, Slider, st
        with self.assertRaises(ValueError) as cm:
            every(60 // 120, lambda: None)
        self.assertIn("got 0", str(cm.exception))
        self.assertIn("60 / 120", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            after(-1, lambda: None)
        self.assertIn("got -1", str(cm.exception))
        st.r55_level = 0
        with self.assertRaises(ValueError) as cm:
            Slider(st["r55_level"], min_value=0, max_value=1 - 1)
        self.assertIn("both 0", str(cm.exception))

    def test_sides_points_at_n(self):
        from scena import RegularPolygon
        with self.assertRaises(TypeError) as cm:
            RegularPolygon(sides=5, center=(200, 200), radius=40)
        msg = str(cm.exception)
        self.assertIn("n= is the number of sides", msg)
        self.assertNotIn("Did you mean 'side'", msg)

if __name__ == "__main__":
    unittest.main()
