"""Bug-class guards from the API robustness audit.

Each test pins a whole class of silent failure or leaked internal error, not
a single call site: every public constructor family, every field kind, every
key-name query, every decorator arity.

    python -m unittest tests.test_api_robustness -v
"""
from __future__ import annotations

import inspect
import math
import os
import subprocess
import sys
import textwrap
import unittest
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.source_support import iter_files
from tests import repo_layout as layout  # noqa: E402

import scena
from scena import (
    init, canvas, st, keyp, mouse, audio, group, Mouse,
    Circle, Rect, Square, Ellipse, Line, Polygon, RegularPolygon,
    EquilateralTriangle, Point, Sprite, Text, Entity, Vec2, Sheet,
    Slider, DropDown, Button, CheckBox, TextInput, SkyGradient, Fire,
    when, on_change, collide, collide_with, on_mode, exit_mode,
    chance, ready, recently, play_sound, set_fx_auto, State,
)
from scena.background import BackgroundField
from scena.postfx import PostEffect
from scena.spatial_fx import SpatialFx
from scena.audio_effects import AudioEffect
from scena.state import CallableAssignError
from scena.events import cleanup_global_event_system
from scena import validate

from tests.leftovers import module_sweep  # noqa: E402
from tests.graph_support import gc_paused, settled_graph_size  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _public_classes(base):
    return sorted(
        (getattr(scena, n) for n in scena.__all__
         if isinstance(getattr(scena, n), type) and issubclass(getattr(scena, n), base)
         and getattr(scena, n) is not base),
        key=lambda c: c.__name__,
    )


def _numeric_knobs(cls):
    fn = cls.__init__
    out = []
    for p in inspect.signature(fn).parameters.values():
        d = p.default
        if p.name in ("self", "attr_name", "owner", "register"):
            continue
        if isinstance(d, bool) or not isinstance(d, (int, float)):
            continue
        out.append(p.name)
    return out


class TestPublicSurface(unittest.TestCase):
    REMOVED = (
        "set_leak_detector", "set_sync_watchdog", "sky_palette",
        "get_extrude_focus", "set_metal_light", "get_metal_light",
    )

    def test_engine_tooling_not_exported(self):
        for name in self.REMOVED:
            with self.subTest(name=name):
                self.assertNotIn(name, scena.__all__)

    def test_engine_tooling_still_importable_from_modules(self):
        from scena.orchestration import set_leak_detector
        from scena.process import set_sync_watchdog
        from scena.background_kinds import sky_palette
        from scena.recipes import get_extrude_focus, set_metal_light, get_metal_light
        for fn in (set_leak_detector, set_sync_watchdog, sky_palette,
                   get_extrude_focus, set_metal_light, get_metal_light):
            self.assertTrue(callable(fn))

    def test_set_extrude_focus_stays_public(self):
        self.assertIn("set_extrude_focus", scena.__all__)

    def test_all_has_no_duplicates(self):
        self.assertEqual(len(scena.__all__), len(set(scena.__all__)))

    def test_wrapped_constructors_show_real_signature(self):
        # Every exported class: help() is not (*args, **kwargs), and engine
        # knobs stay off the signature.
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not isinstance(cls, type):
                continue
            with self.subTest(cls=name):
                try:
                    params = list(inspect.signature(cls).parameters)
                except (TypeError, ValueError):
                    continue
                self.assertNotEqual(params, ["args", "kwargs"], name)
                for bad in params:
                    self.assertFalse(bad.startswith("_"), name)
                    self.assertNotIn(bad, ("attr_name", "owner", "register"), name)


class TestConstructorNumbers(unittest.TestCase):
    """Every FX / background / SpatialFx / audio constructor: type, NaN, sign, typo."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    FAMILIES = (PostEffect, BackgroundField, SpatialFx, AudioEffect)

    def _classes(self):
        for base in self.FAMILIES:
            yield from _public_classes(base)

    def test_string_for_number_is_type_error(self):
        for cls in self._classes():
            for knob in _numeric_knobs(cls):
                with self.subTest(cls=cls.__name__, knob=knob):
                    with self.assertRaises(TypeError) as ctx:
                        cls(**{knob: "lots"})
                    self.assertIn(knob, str(ctx.exception))

    def test_non_finite_is_value_error(self):
        for cls in self._classes():
            for knob in _numeric_knobs(cls):
                for bad in (math.nan, math.inf):
                    with self.subTest(cls=cls.__name__, knob=knob, bad=bad):
                        with self.assertRaises(ValueError):
                            cls(**{knob: bad})

    def test_negative_size_is_value_error(self):
        for cls in self._classes():
            for knob in _numeric_knobs(cls):
                if knob not in validate._NONNEG_PARAMS:
                    continue
                with self.subTest(cls=cls.__name__, knob=knob):
                    with self.assertRaises(ValueError):
                        cls(**{knob: -1})

    def test_unknown_keyword_is_type_error_with_valid_list(self):
        for cls in self._classes():
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(TypeError) as ctx:
                    cls(zz_not_a_knob=1)
                msg = str(ctx.exception)
                self.assertIn("zz_not_a_knob", msg)
                self.assertNotIn("attr_name", msg)

    def test_near_miss_keyword_suggests(self):
        with self.assertRaises(TypeError) as ctx:
            Circle(radius=3, colr="red")
        self.assertIn("Did you mean 'color'", str(ctx.exception))
        with self.assertRaises(TypeError) as ctx:
            Fire(center=(100, 100), width=40, style="plume", lenght=3)
        msg = str(ctx.exception)
        self.assertIn("Did you mean 'length'", msg)
        self.assertTrue(msg.startswith("Fire "), msg)  # public name, not _LookPlume


class TestShapesAreKeywordOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_positional_values_raise_with_example(self):
        for cls in (Circle, Rect, Square, Ellipse, Line, Polygon,
                    RegularPolygon, EquilateralTriangle):
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(TypeError) as ctx:
                    cls(10)
                msg = str(ctx.exception)
                self.assertIn("keyword arguments only", msg)
                self.assertIn(f"{cls.__name__}(", msg)

    def test_polygon_signature_hides_catchall(self):
        params = inspect.signature(Polygon).parameters
        self.assertNotIn("args", params)
        self.assertIn("points", params)


class TestCallableAssignEveryFieldKind(unittest.TestCase):
    """`obj.field = lambda` never links; it raises naming the bracket spelling."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_every_field_kind(self):
        c = Circle(center=(0, 0), radius=5)
        c.hp = 1
        st.robust_x = 0
        cases = [
            (c, "radius"),      # ScalarSlot
            (c, "center"),      # ContainerSlot
            (c, "angle"),    # property-link field
            (c, "hp"),          # existing ink
            (c, "brand_new"),   # new ink
            (c, "vel"),         # physics property
            (Rect(center=(0, 0), width=40, height=20), "corner_radius"),  # paint-only
        ]
        for obj, field in cases:
            with self.subTest(field=field):
                with self.assertRaises(CallableAssignError) as ctx:
                    setattr(obj, field, lambda: 3)
                self.assertIn("@=", str(ctx.exception))
        with self.assertRaises(CallableAssignError):
            st.robust_x = lambda: 3

    def test_state_refuses_every_plain_function(self):
        # Q5 (geometry campaign): State refused only a lambda; a named def, a
        # method or a builtin was stored silently.
        import functools

        def named():
            return 3
        for fn in (named, self.setUp, print, len, functools.partial(max, 1)):
            with self.subTest(fn=fn):
                with self.assertRaises(CallableAssignError) as ctx:
                    st.robust_fn = fn
                self.assertIn("@=", str(ctx.exception))
                with self.assertRaises(CallableAssignError):
                    st.create("robust_fn2", fn)
        st.robust_kind = int            # a class is a value
        st.robust_num = 3
        self.assertEqual(st.robust_num, 3)

    def test_error_is_catchable_as_legacy_types(self):
        self.assertTrue(issubclass(CallableAssignError, TypeError))
        self.assertTrue(issubclass(CallableAssignError, AttributeError))
        self.assertTrue(issubclass(CallableAssignError, ValueError))


class TestInkGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_near_miss_of_real_property_raises(self):
        c = Circle(center=(0, 0), radius=5)
        for typo, fix in (("angel", "angle"), ("visable", "visible"),
                          ("radious", "radius"), ("colour", "color"),
                          ("centre", "center")):
            with self.subTest(typo=typo):
                with self.assertRaises(AttributeError) as ctx:
                    setattr(c, typo, 1)
                self.assertIn(fix, str(ctx.exception))

    def test_enable_and_enabled_point_at_active(self):
        c = Circle(center=(0, 0), radius=5)
        e = Entity()
        self.addCleanup(e.destroy)
        for obj, name in ((c, "enabled"), (c, "enable"), (e, "enabled"), (e, "enable")):
            with self.subTest(kind=type(obj).__name__, name=name):
                with self.assertRaises(AttributeError) as ctx:
                    setattr(obj, name, False)
                msg = str(ctx.exception)
                self.assertIn(".active = True", msg)
                self.assertIn("park", msg)
                self.assertTrue(obj.active)
                ink = object.__getattribute__(obj, "_ink")
                self.assertFalse(ink and name in ink)
                with self.assertRaises(AttributeError):
                    getattr(obj, name)
        with self.assertRaises(AttributeError) as ctx:
            c["enabled"]
        self.assertIn(".active = True", str(ctx.exception))
        with self.assertRaises(AttributeError):
            c["enable"] @= (lambda: False)

    def test_ordinary_game_names_are_ink(self):
        c = Circle(center=(0, 0), radius=5)
        for name in ("hp", "speed", "player", "flame", "weight", "score", "heights"):
            with self.subTest(name=name):
                setattr(c, name, 1)
                self.assertEqual(getattr(c, name), 1)

    def test_look_property_of_other_kind_raises(self):
        c = Circle(center=(0, 0), radius=5)
        t = Text("hi")
        e = Entity()
        self.addCleanup(e.destroy)
        for obj, name in ((c, "alpha"), (t, "alpha"), (c, "font_size"), (e, "line_width")):
            with self.subTest(kind=type(obj).__name__, name=name):
                with self.assertRaises(AttributeError) as ctx:
                    setattr(obj, name, 1)
                self.assertIn(name, str(ctx.exception))

    def test_group_assignment_normalizes_and_syncs_registry(self):
        c = Circle(center=(0, 0), radius=5, group="robust_a")
        c.group = "robust_b"
        self.assertEqual(c.group, {"robust_b"})
        self.assertIn(c, group["robust_b"])
        self.assertNotIn(c, group["robust_a"])
        with self.assertRaises(TypeError):
            c.group = 5

    def test_id_keyword_is_refused(self):
        # Scena has no ids (the variable is the handle); any id= is a TypeError.
        for value in (5, "player", ""):
            with self.subTest(value=value):
                with self.assertRaises(TypeError) as ctx:
                    Circle(**{"id": value})
                self.assertIn("group=", str(ctx.exception))


class TestPoseSetters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_flags_are_strict_bools(self):
        c = Circle(center=(0, 0), radius=5)
        for field in ("visible", "flip_x", "flip_y"):
            for bad in ("no", 2, None):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(TypeError):
                        setattr(c, field, bad)
        c.visible = 0
        self.assertFalse(c.visible)
        c.visible = True

    def test_angles_are_finite_numbers(self):
        from scena import Box
        objs = [
            Circle(center=(0, 0), radius=5),
            Rect(center=(0, 0), width=10, height=5),
            Square(center=(0, 0), length=4),
            Ellipse(center=(0, 0), width=10, height=5),
            Line(p1=(0, 0), p2=(10, 0)),
            Polygon(points=[(0, 0), (10, 0), (0, 10)]),
            RegularPolygon(center=(0, 0), radius=5, n=5),
            EquilateralTriangle(center=(0, 0), side=5),
            Point(3, 4),
            Box(center=(0, 0), width=10, height=5),
            Text("hi"),
        ]
        for obj in objs:
            with self.subTest(kind=type(obj).__name__):
                for verb in (obj.rotate_by, obj.rotate_to):
                    with self.assertRaises(ValueError):
                        verb(math.inf)
                    with self.assertRaises(TypeError):
                        verb("north")
                if hasattr(type(obj), "angle"):
                    with self.assertRaises(TypeError):
                        obj.angle = "x"
        for verb in (canvas.rotate_by, canvas.rotate_to):
            with self.subTest(kind="canvas", verb=verb.__name__):
                with self.assertRaises(TypeError):
                    verb("north")

    def test_vel_shapes(self):
        c = Circle(center=(0, 0), radius=5)
        with self.assertRaises(TypeError):
            c.vel = 5
        with self.assertRaises(TypeError):
            c.vel = (1, 2, 3)
        with self.assertRaises(ValueError):
            c.vel = (math.nan, 0)
        c.vel = (3, 4)
        self.assertEqual((c.vel.x, c.vel.y), (3.0, 4.0))
        c.vel = None

    def test_layer_type_and_typo(self):
        with self.assertRaises(TypeError) as ctx:
            Circle(layer=3.5)
        self.assertIn("layer", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            Circle(layer="defualt")
        msg = str(ctx.exception)
        self.assertIn("Did you mean 'default'", msg)
        self.assertIn("Existing layers", msg)


class TestKeyAndButtonNames(unittest.TestCase):
    def test_unknown_key_names_raise_with_fix(self):
        for spec, fix in (("ESCAPE", "ESC"), ("RETURN", "ENTER"), ("SPCAE", "SPACE"),
                          ("CTRL+ESCAPE", "ESC")):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError) as ctx:
                    keyp(spec)
                self.assertIn(fix, str(ctx.exception))

    def test_every_query_path_checks(self):
        for fn in (keyp, keyp.once, keyp.only, keyp.held, keyp.held.once):
            with self.subTest(fn=fn):
                with self.assertRaises(ValueError):
                    fn("ESCAPE")
                with self.assertRaises(TypeError):
                    fn(5)
        with self.assertRaises(ValueError):
            "ESCAPE" in keyp  # noqa: B015

    def test_other_platform_modifier_words_raise_with_fix(self):
        # One spelling per key: CONTROL / OPTION / COMMAND used to be silent aliases.
        for spec, fix in (("CONTROL", "CTRL"), ("option", "ALT"), ("COMMAND", "CMD"),
                          ("SUPER", "CMD"), ("win", "CMD"), ("META", "CMD"),
                          ("control+s", "CTRL"), ("LEFT_OPTION", "LEFT_ALT"),
                          ("RIGHT_COMMAND", "RIGHT_CMD"), ("LALT", "LEFT_ALT"),
                          ("RCMD", "RIGHT_CMD"), ("PGDOWN", "PAGEDOWN"),
                          ("BKSP", "BACKSPACE")):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError) as ctx:
                    keyp(spec)
                self.assertIn(f"Scena calls it {fix!r}", str(ctx.exception))

    def test_every_spelling_hint_names_a_real_key(self):
        # Bug class: a hint table entry that points at a name keyp rejects,
        # or a spelling that is itself accepted (a silent second spelling).
        from scena.input import _KEY_SPELLINGS, check_key_spec

        for spelling, fix in _KEY_SPELLINGS.items():
            if not spelling.strip():
                continue
            with self.subTest(spelling=spelling):
                check_key_spec(fix)
                with self.assertRaises(ValueError) as ctx:
                    keyp(spelling)
                self.assertIn(f"Scena calls it {fix!r}", str(ctx.exception))

    def test_every_spelling_hint_on_key_names_a_delivered_key(self):
        # ``key == "LSHIFT"`` used to say on_key receives 'LEFT_SHIFT', which
        # on_key never delivers (sides arrive as the family).
        from scena.input import _KEY_SPELLINGS, KeyName, _is_delivered_name

        key = KeyName("A")
        for spelling in _KEY_SPELLINGS:
            if not spelling.strip():
                continue
            with self.subTest(spelling=spelling):
                with self.assertRaises(ValueError) as ctx:
                    key == spelling  # noqa: B015
                msg = str(ctx.exception)
                named = msg.split("on_key receives ", 1)[1].split(",", 1)[0].strip("'")
                self.assertTrue(_is_delivered_name(named), msg)
        with self.assertRaises(ValueError) as ctx:
            key == "LEFT_OPTION"  # noqa: B015
        self.assertIn("on_key receives 'ALT'", str(ctx.exception))
        self.assertIn("keyp('LEFT_ALT')", str(ctx.exception))

    def test_punctuation_is_numbered_by_position(self):
        # K1…K12 in reading order; the US cap only documents the position.
        import glfw
        from scena.input import get_glfw_key_name

        expected = {
            glfw.KEY_GRAVE_ACCENT: "K1", glfw.KEY_MINUS: "K2", glfw.KEY_EQUAL: "K3",
            glfw.KEY_LEFT_BRACKET: "K4", glfw.KEY_RIGHT_BRACKET: "K5",
            glfw.KEY_BACKSLASH: "K6", glfw.KEY_SEMICOLON: "K7",
            glfw.KEY_APOSTROPHE: "K8", glfw.KEY_WORLD_1: "K9", glfw.KEY_WORLD_2: "K9",
            glfw.KEY_COMMA: "K10", glfw.KEY_PERIOD: "K11", glfw.KEY_SLASH: "K12",
        }
        for code, name in expected.items():
            with self.subTest(name=name, code=code):
                self.assertEqual(get_glfw_key_name(code), name)
                self.assertIsInstance(keyp(name), bool)
                self.assertIsInstance(keyp(name.lower()), bool)
                self.assertIsInstance(keyp(f"CTRL+{name}"), bool)
        for bad in ("K0", "K13", "K01"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                keyp(bad)

    def test_punctuation_glyphs_and_words_raise_with_number(self):
        # The cap differs per layout (ABNT2's K7 is Ç), so a glyph is never a name.
        for spec, fix in ((".", "K11"), (",", "K10"), (";", "K7"), ("/", "K12"),
                          ("-", "K2"), ("=", "K3"), ("[", "K4"), ("]", "K5"),
                          ("\\", "K6"), ("'", "K8"), ("`", "K1"),
                          ("PERIOD", "K11"), ("comma", "K10"), ("SEMICOLON", "K7"),
                          ("ctrl+.", "K11"), ("SHIFT+/", "K12")):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError) as ctx:
                    keyp(spec)
                self.assertIn(f"Scena calls it {fix!r}", str(ctx.exception))
        from scena.input import KeyName

        key = KeyName("K11")
        self.assertTrue(key == "K11")
        with self.assertRaises(ValueError) as ctx:
            key == "."  # noqa: B015
        self.assertIn("on_key receives 'K11'", str(ctx.exception))

    def test_every_glfw_key_is_named_or_dropped(self):
        # Bug class: an unnamed key reached keyp / on_key as its raw code
        # ("46" for the period) — a name no query could spell.
        import glfw
        from scena.input import check_key_spec, get_glfw_key_name, known_glfw_keys

        codes = {getattr(glfw, n) for n in dir(glfw) if n.startswith("KEY_")}
        for code in sorted(codes):
            name = get_glfw_key_name(code)
            if name is None:
                continue
            with self.subTest(code=code, name=name):
                check_key_spec(name)
        self.assertIsNone(get_glfw_key_name(glfw.KEY_UNKNOWN))
        self.assertIsNone(get_glfw_key_name(glfw.KEY_KP_ADD))
        for code in known_glfw_keys():
            with self.subTest(seed=code):
                self.assertIsNotNone(get_glfw_key_name(code))

    def test_valid_names_pass(self):
        for spec in ("space", "A", "7", "ctrl+s", "SHIFT", "LEFT_SHIFT", "F12", "cmd+shift+z"):
            with self.subTest(spec=spec):
                self.assertIsInstance(keyp(spec), bool)

    def test_empty_and_plus_raise(self):
        for spec in ("", "CTRL+", "+"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    keyp(spec)

    def test_mouse_button_names(self):
        with self.assertRaises(TypeError) as ctx:
            mouse.press("left")
        self.assertIn("BTN_LEFT", str(ctx.exception))
        self.assertIsInstance(mouse.press(Mouse.BTN_LEFT), bool)
        self.assertIsInstance(mouse.press(), bool)

    def test_subscript_is_not_a_query(self):
        with self.assertRaises(TypeError) as ctx:
            keyp["A"]
        msg = str(ctx.exception)
        self.assertIn('keyp("A")', msg)
        self.assertIn('keyp.once("A")', msg)
        with self.assertRaises(ValueError) as ctx:
            keyp["SPAXE"]
        self.assertIn("SPACE", str(ctx.exception))
        with self.assertRaises(TypeError):
            keyp[5]
        with self.assertRaises(TypeError) as ctx:
            keyp.held["LEFT"]
        msg = str(ctx.exception)
        self.assertIn('keyp.held("LEFT")', msg)
        self.assertIn('keyp.held.once("LEFT")', msg)

    def test_key_name_compare(self):
        from scena.input import KeyName

        key = KeyName("A")
        self.assertIsInstance(key, str)
        self.assertEqual(key, "A")
        self.assertNotEqual(key, "B")
        self.assertFalse(key == "B")
        self.assertTrue(key != "B")
        self.assertIs(key == None, False)  # noqa: E711
        self.assertEqual(hash(key), hash("A"))
        self.assertEqual({"A": 1}[key], 1)
        self.assertIs({"SPAXE": 1}.get(key), None)
        self.assertIsInstance(key.lower(), str)
        self.assertNotIsInstance(key.lower(), KeyName)
        self.assertTrue(key in ("A", "SPAXE"))
        with self.assertRaises(ValueError) as ctx:
            "SPAXE" == key  # noqa: B015
        self.assertIn("SPACE", str(ctx.exception))
        for bad, fix in (
            ("space", "SPACE"),
            ("a", "A"),
            ("LEFT_SHIFT", "SHIFT"),
            ("ESCAPE", "ESC"),
            ("CTRL+S", "CTRL+S"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    key == bad  # noqa: B015
                self.assertIn(fix, str(ctx.exception))
        other = KeyName("B")
        with self.assertRaises(ValueError) as ctx:
            other in ("A", "SPAXE")
        self.assertIn("SPACE", str(ctx.exception))
        with self.assertRaises(ValueError):
            key != "SPAXE"


class TestDecoratorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def tearDown(self):
        cleanup_global_event_system()

    def test_when_non_bool_raises_at_decorator(self):
        st.robust_n = 1
        with self.assertRaises(TypeError):
            @when(lambda: st.robust_n)
            def _h():
                pass

    def test_bare_value_condition_raises(self):
        for bad in (5, "hp <= 0", True):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    @when(bad)
                    def _h():
                        pass

    def test_handler_arity_checked_at_decorator(self):
        st.robust_flag = False
        with self.assertRaises(TypeError) as ctx:
            @when(lambda: st.robust_flag)
            def needs_arg(value):
                pass
        self.assertIn("needs_arg", str(ctx.exception))
        with self.assertRaises(TypeError):
            @on_change(lambda: st.robust_flag)
            def needs_two(a, b):
                pass

        @on_change(lambda: st.robust_flag)
        def takes_value(value):
            pass

        @on_change(lambda: st.robust_flag)
        def takes_nothing():
            pass

    def test_method_handler_arity(self):
        with self.assertRaises(TypeError):
            class _Bad(Entity):
                @when(lambda self: True)
                def fire(self, extra):
                    pass

    def test_collide_sides_and_arity(self):
        with self.assertRaises(TypeError):
            collide(5, "b")
        with self.assertRaises(TypeError):
            collide(None, "b")
        with self.assertRaises(TypeError):
            @collide("robust_a", "robust_b")
            def four(me, other, info, extra):
                pass

        @collide("robust_a", "robust_b")
        def two(me, other):
            pass

        with self.assertRaises(TypeError):
            class _BadWith(Circle):
                @collide_with("robust_b")
                def hit(self, other, info, extra):
                    pass

    def test_mode_decorators_need_functions(self):
        with self.assertRaises(TypeError):
            on_mode(5)
        with self.assertRaises(TypeError):
            exit_mode(5)


class TestLeakedInternalErrors(unittest.TestCase):
    """Wrong input names the fix instead of surfacing an engine traceback."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_widgets(self):
        with self.assertRaises(TypeError) as ctx:
            Slider(0.5)
        self.assertIn("initial=0.5", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            Slider(min_value=5, max_value=1)
        self.assertIn("Swap", str(ctx.exception))
        with self.assertRaises(ValueError):
            DropDown(options=[])
        with self.assertRaises(TypeError):
            DropDown(options="abc")
        with self.assertRaises(TypeError):
            Button(on_click="x")
        # One parameter receives the button (same rule as shape.on_click);
        # two cannot be served.
        Button(on_click=lambda button: None).destroy()
        with self.assertRaises(TypeError):
            Button(on_click=lambda button, extra: None)
        for widget in (CheckBox, TextInput, DropDown, Button):
            with self.subTest(widget=widget.__name__):
                with self.assertRaises(TypeError):
                    widget(3)

    def test_set_color_needs_a_color(self):
        with self.assertRaises(TypeError) as ctx:
            Circle(center=(0, 0), radius=5).set_color()
        self.assertIn("set_color(", str(ctx.exception))

    def test_numbers_rule_on_calls(self):
        with self.assertRaises(ValueError):
            canvas.shake(-1)
        with self.assertRaises(TypeError):
            canvas.flash("red")
        with self.assertRaises(ValueError):
            audio.volume = -1
        with self.assertRaises(TypeError):
            audio.volume = "loud"
        with self.assertRaises(ValueError):
            play_sound("missing_robust.wav", volume=-1)
        with self.assertRaises(ValueError) as ctx:
            chance(30)
        self.assertIn("percent", str(ctx.exception))
        with self.assertRaises(TypeError):
            ready(5, 1)
        with self.assertRaises(TypeError):
            ready("robust_timer", "soon")
        with self.assertRaises(TypeError):
            recently(3, True)

    def test_every_duration_names_itself(self):
        from scena import after, every, wait, amp_db
        c = Circle(center=(0, 0), radius=5)
        calls = {
            "after": lambda v: after(v, lambda: None),
            "every": lambda v: every(v, lambda: None),
            "wait": lambda v: wait(v),
            "move_to": lambda v: c.move_to((1, 1), time=v),
            "rotate_to": lambda v: c.rotate_to(10, time=v),
            "pan_to": lambda v: canvas.pan_to((0, 0), time=v),
            "flash": lambda v: c.flash(duration=v),
        }
        for name, call in calls.items():
            with self.subTest(call=name):
                with self.assertRaises(TypeError) as ctx:
                    call("soon")
                self.assertNotIn("could not convert", str(ctx.exception))
                with self.assertRaises((TypeError, ValueError)):
                    call(math.nan)
        with self.assertRaises(TypeError):
            after(lambda: 1, lambda: None)
        with self.assertRaises(TypeError):
            amp_db("x")

    def test_look_name_string_points_to_class(self):
        c = Circle(center=(0, 0), radius=5)
        for text, cls in (("neon", "Neon"), ("Metal", "Metal"), ("electric_field", "ElectricField")):
            with self.subTest(text=text):
                with self.assertRaises(TypeError) as ctx:
                    c.visual = text
                self.assertIn(f"{cls}()", str(ctx.exception))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            c.visual = "ink"      # also a color name → Paint
            c.visual = "red"
            c.visual = "#ff0000"

    def test_camera_properties_point_to_verbs(self):
        with self.assertRaises(AttributeError) as ctx:
            canvas.zoom = 2
        self.assertIn("zoom_to", str(ctx.exception))
        with self.assertRaises(AttributeError) as ctx:
            canvas.pan_x = 2
        self.assertIn("pan_to", str(ctx.exception))

    def test_flags_and_vectors(self):
        with self.assertRaises(TypeError):
            set_fx_auto("yes")
        with self.assertRaises(TypeError) as ctx:
            Vec2(1)
        self.assertIn("Vec2(3, 4)", str(ctx.exception))

    def test_sky_palette_typo_raises(self):
        with self.assertRaises(ValueError) as ctx:
            SkyGradient("nope")
        self.assertIn("Sky presets", str(ctx.exception))
        SkyGradient("navy")      # a color is fine
        SkyGradient("#203050")   # hex too
        SkyGradient("sunset")

    def test_missing_sheet_keeps_requested_grid(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sheet = Sheet("robust_missing_hero.png", cols=4, rows=3)
        self.assertEqual(sheet._nframes, 12)
        sheet.clip("hit", [10, 11], fps=12)

    def test_state_messages(self):
        bag = State(name="robust_bag")
        with self.assertRaises(AttributeError) as ctx:
            bag.scroe
        self.assertIn("Create it first", str(ctx.exception))
        with self.assertRaises(Exception) as ctx:
            bag.name = "x"
        self.assertIn("reserved", str(ctx.exception))


class TestFormulaSourcesWithoutFile(unittest.TestCase):
    """`st` formulas from exec / REPL (no source file) still find their cells."""

    def test_exec_formula_links_st_cell(self):
        code = textwrap.dedent("""
            from scena import *
            st.robust_lives = 3
            ship = Circle(center=(0, 0), radius=5)
            ship["shield"] @= lambda: st.robust_lives * 10
            st.robust_lives = 4
            result = ship.shield
        """)
        ns: dict = {}
        exec(compile(code, "<robust-exec>", "exec"), ns)
        self.assertEqual(ns["result"], 40)

    def test_missing_st_cell_in_formula_names_the_cell(self):
        path = os.path.join(ROOT, "tests", "_robust_formula_probe.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent("""
                from scena import *
                ship = Circle(center=(0, 0), radius=5)
                try:
                    ship["shield"] @= lambda: st.robust_nope * 10
                except AttributeError as e:
                    print("ERR", e)
            """))
        self.addCleanup(os.remove, path)
        out = subprocess.run(
            [sys.executable, path], capture_output=True, cwd=ROOT,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": ROOT, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONIOENCODING": "utf-8"},
        )
        self.assertIn("has no cell 'robust_nope'", out.stdout)


class TestPhase3SilentPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_bracket_typo_raises(self):
        ship = Circle(radius=8)
        with self.assertRaises(AttributeError) as ctx:
            ship["rotaton"]
        self.assertIn("angle", str(ctx.exception))

    def test_font_is_family_or_file_not_skia(self):
        t = Text(text="hi", font="Arial")
        self.assertEqual(t.font, "Arial")
        self.assertIsInstance(t.font, str)
        t.font = None
        self.assertIsNone(t.font)

    def test_state_bracket_link_creates_cell(self):
        c = Circle(radius=6)
        st["robust_new"] @= lambda: c.radius
        self.assertEqual(st.robust_new, 6)
        with self.assertRaises(AttributeError):
            _ = st.robust_missing
        with self.assertRaises(AttributeError):
            st["keys"] @= lambda: c.radius

    def test_move_to_names_itself(self):
        c = Circle(radius=4)
        with self.assertRaises(TypeError) as ctx:
            c.move_to(0, 0, time="a")
        self.assertIn("move_to time=", str(ctx.exception))

    def test_chase_rate_sign(self):
        from scena import chase
        self.assertEqual(chase(0, 10, 0, dt=0.1), 0)
        with self.assertRaises(ValueError):
            chase(0, 10, -1, dt=0.1)
        with self.assertRaises(ValueError):
            chase(0, 10, 1, dt=-0.1)
        with self.assertRaises(TypeError):
            chase(0, 10, True, dt=0.1)

    def test_color_over_255_hints(self):
        from scena import Color
        with self.assertRaises(ValueError) as ctx:
            Color(300, 0, 0)
        self.assertIn("divide by 255", str(ctx.exception))

    def test_look_rejects_bad_amount(self):
        from scena import Neon
        with self.assertRaises(TypeError):
            Neon(amount="lots")


class TestGuiaMatchesCode(unittest.TestCase):
    """The Guia's catalog cards and examples track the real API."""

    @classmethod
    def setUpClass(cls):
        guide = layout.GUIDE_TOOLS
        sys.path.insert(0, guide)
        import validate_guia  # type: ignore
        cls.v = validate_guia
        cls.bags = validate_guia.load_catalogs()

    def test_catalog_shape(self):
        self.assertEqual(self.v.validate_catalogs(self.bags), [])

    def test_post_is_the_stack_and_impactos_the_one_shot_verbs(self):
        # Post = what lives in canvas.effects; Impactos = canvas verbs that fire
        # and decay (screen / point / cover). A card in the wrong bag misleads.
        from scena.postfx import PostEffect
        for it in self.bags["POST"]:
            with self.subTest(it["id"]):
                obj = self.v.resolve_catalog_symbol(it["name"])
                self.assertTrue(isinstance(obj, type) and issubclass(obj, PostEffect), it["name"])
        for it in self.bags["IMPACTS"]:
            with self.subTest(it["id"]):
                self.assertTrue(it["name"].startswith("canvas."), it["name"])
                self.assertTrue(callable(self.v.resolve_catalog_symbol(it["name"])), it["name"])
                self.assertIn(it["kind"], ("screen", "point", "cover"))
                self.assertEqual(it["kind"] == "point", it["name"].endswith("_at"))

    def test_catalog_js_is_valid(self):
        # A JS syntax error (one stray ")") emptied every catalog in the page
        # while the regex loader still "saw" every card.
        self.assertEqual(self.v.check_catalog_js(self.v.CATALOGS, self.bags), [])

    def test_catalog_js_checker_catches_bracket_errors(self):
        broken = {
            "extra paren in P list": 'x = [P("a", "b", "c"))];',
            "missing ]": 'const A = [{ id: "a" };',
            "} closes (": "f(a};",
            "unclosed {": "x = { a: 1",
            "stray closer": "x = 1);",
            "${ closed by )": "y = `a ${f(1)) b`;",
        }
        for label, src in broken.items():
            with self.subTest(label):
                self.assertNotEqual(self.v.js_brackets(src)[0], [])

    def test_catalog_js_checker_skips_strings_comments_regex(self):
        ok = [
            'x = ["a) b", "[x", \'}\', "(\\"q"];',
            "// ) [ {\n/* ( */ x = 1;",
            'y = `a ${f("}")} b`; z = /[)]/g.test(s); w = /\\(/;',
            "q = a / b / (c);",
        ]
        for src in ok:
            with self.subTest(src):
                self.assertEqual(self.v.js_brackets(src)[0], [])

    def test_catalog_js_card_count_matches_loader(self):
        # A card the regex loader cannot read (fields out of order) is unchecked.
        bags = {k: list(v) for k, v in self.bags.items()}
        bags["LOOKS"] = bags["LOOKS"][:-1]
        errors = self.v.check_catalog_js(self.v.CATALOGS, bags)
        self.assertTrue(any("LOOKS" in e for e in errors), errors)

    def test_catalog_js_engine_agrees(self):
        errors = self.v.check_catalog_js_engine(self.bags)
        if errors is None:
            self.skipTest("no node / jsc")
        self.assertEqual(errors, [])

    def test_catalog_params_match_signatures(self):
        errors, gaps = self.v.check_catalog_signatures(self.bags)
        self.assertEqual(errors, [])
        self.assertEqual(gaps, [])

    def test_parameter_tables_use_real_keywords(self):
        self.assertEqual(self.v.check_parameter_keywords(), [])

    def test_member_cards_name_author_methods(self):
        self.assertEqual(self.v.check_member_cards(), [])

    def test_examples_compile(self):
        self.assertEqual(self.v.check_examples_compile(self.v.collect_examples(self.bags)), [])

    def test_examples_run(self):
        # Fresh process: examples build real actors and register events.
        guide = layout.GUIDE_TOOLS
        script = (
            "import sys; sys.path.insert(0, {guide!r}); import validate_guia as v; "
            "b = v.load_catalogs(); s = {{}}; f = v.run_examples(v.collect_examples(b), s); "
            "total = s['ran'] + s['skipped']; "
            "bad = list(f); "
            "rate = (s['skipped'] / total) if total else 0; "
            "bad.append('skipped ' + str(s['skipped']) + '/' + str(total)) if rate >= 0.20 else None; "
            "print('\\n'.join(bad)); sys.exit(1 if bad else 0)"
        ).format(guide=guide)
        out = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, cwd=ROOT,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": ROOT, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONIOENCODING": "utf-8"},
            timeout=300,
        )
        self.assertEqual(out.returncode, 0, out.stdout[-4000:] + out.stderr[-2000:])


class TestGuiaAccessProbe(unittest.TestCase):
    """The "lê / escreve" audit writes a *different* value, then restores it.

    Regression: it used to write the current value back, so a setter that
    returns early on a same-value write and refuses every real one
    (the old ``Entity.id`` before K5) passed as writable.
    """

    @classmethod
    def setUpClass(cls):
        guide = layout.GUIDE_TOOLS
        sys.path.insert(0, guide)
        import validate_guia  # type: ignore
        cls.v = validate_guia

    def test_probe_value_differs_and_keeps_the_kind(self):
        from scena import Color, Vec2
        cases = [True, False, 0, 7, 0.0, 2.5, "", "hud", frozenset({"a"}), (1, 2), (0.5, 0.5, 0.5)]
        for value in cases:
            with self.subTest(value=value):
                probe = self.v.probe_value(value)
                self.assertIsNot(probe, self.v._NO_PROBE)
                self.assertNotEqual(probe, value)
                self.assertIs(type(probe) is bool, type(value) is bool)
        rgb = self.v.probe_value(Color("red"))
        self.assertTrue(all(0.0 <= c <= 1.0 for c in rgb), rgb)  # a valid colour
        self.assertNotEqual(rgb[:3], Color("red").rgb[:3])
        self.assertEqual(self.v.probe_value(Vec2(1, 2)), (2, 3))
        self.assertIs(self.v.probe_value(object()), self.v._NO_PROBE)

    def test_same_value_noop_setter_is_read_only(self):
        class SkipsSameValue:
            _k = "fixed"

            @property
            def k(self):
                return self._k

            @k.setter
            def k(self, value):
                if value == self._k:
                    return  # the old Entity.id shape
                raise AttributeError("read-only")

        self.assertIs(self.v.probe_writable(SkipsSameValue(), "k"), False)

    def test_value_errors_still_count_as_writable(self):
        class Picky:
            _n = 1.0

            @property
            def n(self):
                return self._n

            @n.setter
            def n(self, value):
                raise ValueError("out of range")

        self.assertIs(self.v.probe_writable(Picky(), "n"), True)

    def test_type_error_saying_read_only_is_read_only(self):
        # Handle.u refuses with TypeError("… read-only …"): read-only, not a
        # field that merely rejects this value.
        class SaysReadOnly:
            @property
            def u(self):
                return 0.25

            @u.setter
            def u(self, value):
                raise TypeError("Handle.u is read-only")

        self.assertIs(self.v.probe_writable(SaysReadOnly(), "u"), False)

    def _row(self, section_id, cell):
        return (f'<section id="{section_id}"><table><tr><td>{cell}</td>'
                '<td class="type"><span class="t">número</span></td>'
                '<td>lê / escreve</td><td>…</td></tr></table></section>')

    def test_canary_section_owner_decides_the_probe(self):
        # Bug class: ".length" in Track's table passed because Line.length
        # (another pool object) accepts writes. The section's object decides.
        errors = self.v.check_access_column(self._row("desenhar-track", "<code>.length</code>"))
        self.assertEqual(len(errors), 1, errors)
        ok = self.v.check_access_column(self._row("shape-line", "<code>.length</code>"))
        self.assertEqual(ok, [])

    def test_canary_shorthand_keeps_its_owner(self):
        # Bug class: in "mouse.x / .y", ".y" was probed on every object (Vec2.y
        # takes writes), so the read-only mouse row passed.
        errors = self.v.check_access_column(
            self._row("frame-mouse", "<code>mouse.x</code> / <code>.y</code>"))
        self.assertEqual(len(errors), 1, errors)

    def test_model_dependent_fields_are_not_flagged(self):
        # Line.center is derived in the p1= / p2= model, writable in center=.
        self.assertEqual(self.v.check_access_column(self._row("shape-line", "<code>.center</code>")), [])

    def test_probe_restores_what_it_wrote(self):
        c = Circle(center=(10, 20), radius=5, color="red")
        try:
            before = (c.center.x, c.center.y, c.visible, c.color.rgb, c.angle)
            for name in ("center", "visible", "color", "angle"):
                self.assertIs(self.v.probe_writable(c, name), True, name)
            after = (c.center.x, c.center.y, c.visible, c.color.rgb, c.angle)
            self.assertEqual(after, before)
        finally:
            c.destroy()

    def test_background_fields_get_a_real_probe(self):
        from scena import Color, Gradient, canvas
        stack = canvas.background
        original = stack.base  # other tests may leave any field kind here
        try:
            stack.base = "navy"
            base = stack.base
            for owner, name, value in ((canvas, "background", stack), (stack, "base", base)):
                with self.subTest(field=name):
                    probe = self.v.probe_value(value)
                    self.assertIsNot(probe, self.v._NO_PROBE)
                    self.assertNotEqual(tuple(probe[:3]), Color("navy").rgb[:3])
                    self.assertIs(self.v.probe_writable(owner, name), True)
                    self.assertIs(stack.base, base)  # original field restored
            # Non-colour bases (gradient, sky, image) still get a probe.
            for kind in (Gradient("sunset"), original):
                with self.subTest(base=type(kind).__name__):
                    stack.base = kind
                    field = stack.base
                    self.assertIsNot(self.v.probe_value(field), self.v._NO_PROBE)
                    self.assertIs(self.v.probe_writable(stack, "base"), True)
                    self.assertIs(stack.base, field)
        finally:
            stack.base = original

    def test_same_field_noop_base_setter_is_read_only(self):
        # The bug class on a composite: a setter that keeps the same field
        # and refuses any other value must not pass as writable.
        from scena import canvas
        from scena.background import BackgroundStack
        real = BackgroundStack.__dict__["base"]

        def skips_same_field(self, value):
            if value is self._base:
                return
            raise AttributeError("read-only")

        BackgroundStack.base = property(real.fget, skips_same_field)
        try:
            self.assertIs(self.v.probe_writable(canvas.background, "base"), False)
        finally:
            BackgroundStack.base = real

    def test_guide_access_column_matches_code(self):
        # Fresh process: the audit builds one object of every author type and
        # clears canvas layers. Also fails if any probed field has no
        # "different" value and falls back to writing itself back.
        guide = layout.GUIDE_TOOLS
        script = textwrap.dedent("""
            import sys
            sys.path.insert(0, {guide!r})
            import validate_guia as v
            fallbacks = []
            real = v.probe_writable
            def spy(obj, name):
                try:
                    value = getattr(obj, name)
                except Exception:
                    value = None
                if value is not None and not callable(value) and v.probe_value(value) is v._NO_PROBE:
                    fallbacks.append(name + ": " + type(value).__name__)
                return real(obj, name)
            v.probe_writable = spy
            e = v.check_access_column()
            e += ["same-value fallback: " + f for f in sorted(set(fallbacks))]
            print("\\n".join(e))
            sys.exit(1 if e else 0)
        """).format(guide=guide)
        out = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, cwd=ROOT,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": ROOT, "PYTHONDONTWRITEBYTECODE": "1",
                 "PYTHONIOENCODING": "utf-8"},
            timeout=300,
        )
        self.assertEqual(out.returncode, 0, out.stdout[-4000:] + out.stderr[-2000:])


class TestLifecycleContracts(unittest.TestCase):
    """Rejected calls and hard remove leave a consistent registry."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_failed_constructor_leaves_no_roster_or_draw(self):
        registry = scena.canvas._engine.registry
        mark = registry._next_key
        with self.assertRaises(Exception):
            Circle(color=False, group="zombie")
        self.assertEqual([k for k in registry.live.keys() if k > mark], [])
        self.assertEqual(len(scena.group["zombie"]), 0)

    def test_second_destroy_does_not_drop_a_newer_actor(self):
        registry = scena.canvas._engine.registry
        a = Circle(center=(0, 0), radius=4)
        a.destroy()
        b = Circle(center=(1, 0), radius=4)
        a.destroy()
        self.assertTrue(registry.is_live(b))
        b.destroy()

    def test_rejected_layer_keeps_the_old_one(self):
        c = Circle(center=(0, 0), radius=4)
        before = c.layer
        with self.assertRaises(ValueError):
            c.layer = "missing-layer"
        self.assertEqual(c.layer, before)
        c.destroy()

    def test_dead_actor_rejects_layer_and_tag(self):
        from scena.state import DestroyedError
        c = Circle(center=(0, 0), radius=4)
        c.destroy()
        with self.assertRaises(DestroyedError):
            c.layer = "top"
        with self.assertRaises(DestroyedError):
            c.tag("ghosts")

    def test_dead_instant_verbs_leave_pose_unchanged(self):
        """Dead Sprite used to raise NotImplementedError; dead Circle used to move."""
        from scena.state import DestroyedError

        def make_all():
            return [
                Circle(center=(10, 20), radius=4),
                Rect(center=(10, 20), width=8, height=6),
                Sprite(center=(10, 20), size=16),
                Text("hi", center=(10, 20)),
                Point(10, 20),
                Line(p1=(0, 0), p2=(10, 0)),
            ]

        def pose(obj):
            return (float(obj.center.x), float(obj.center.y))

        calls = {
            "move_by": lambda obj: obj.move_by(3, 4),
            "move_to": lambda obj: obj.move_to(1, 2),
            "rotate_by": lambda obj: obj.rotate_by(15),
            "scale_by": lambda obj: obj.scale_by(1.1),
            "confine": lambda obj: obj.confine(canvas.game_view),
        }
        for obj in make_all():
            before = pose(obj)
            obj.destroy()
            self.assertEqual(pose(obj), before)
            for name, call in calls.items():
                with self.subTest(kind=type(obj).__name__, verb=name):
                    with self.assertRaises(DestroyedError):
                        call(obj)
                    self.assertEqual(pose(obj), before)

    def test_dead_timed_move_is_a_cancelled_handle(self):
        c = Circle(center=(10, 20), radius=4)
        c.destroy()
        before = (float(c.center.x), float(c.center.y))
        handle = c.move_by(5, 0, time=0.1)
        self.assertTrue(handle.cancelled)
        self.assertEqual((float(c.center.x), float(c.center.y)), before)

    def test_dead_actor_stays_readable(self):
        from scena.state import DestroyedError
        c = Circle(center=(10, 20), radius=4)
        c.hp = 3
        c.destroy()
        self.assertEqual((float(c.center.x), float(c.center.y)), (10.0, 20.0))
        self.assertFalse(c.is_alive)
        # Ink reads already raise (History appends its breadcrumb to that error).
        with self.assertRaises(DestroyedError):
            _ = c.hp

    def test_bool_matches_is_alive(self):
        c = Circle(center=(0, 0), radius=4)
        self.assertTrue(c)
        self.assertTrue(c.is_alive)
        c.destroy()
        self.assertFalse(c)
        self.assertFalse(c.is_alive)

    def test_destroyed_message_names_the_call_and_the_destroy_site(self):
        from scena.state import DestroyedError
        ship = Circle(center=(0, 0), radius=4)
        ship.destroy()
        with self.assertRaises(DestroyedError) as ctx:
            ship.move_by(1, 0)
        text = str(ctx.exception)
        self.assertIn("move_by()", text)
        self.assertIn("test_api_robustness.py", text)
        self.assertIn("test_destroyed_message_names_the_call_and_the_destroy_site", text)
        self.assertIn("if ship:", text)

    def test_dead_slot_write_raises(self):
        from scena.state import DestroyedError
        c = Circle(center=(0, 0), radius=4)
        c.destroy()
        with self.assertRaises(DestroyedError):
            c.radius = 9
        self.assertEqual(c.radius, 4)
        p = Point(1, 2)
        p.destroy()
        with self.assertRaises(DestroyedError):
            p.x = 5
        self.assertEqual(p.x, 1)

    def test_dead_visible_collidable_color_and_play(self):
        from scena.state import DestroyedError
        c = Circle(center=(0, 0), radius=4, color="red")
        c.destroy()
        with self.assertRaises(DestroyedError):
            c.visible = False
        with self.assertRaises(DestroyedError):
            c.collidable = False
        with self.assertRaises(DestroyedError):
            c.set_color("blue")
        self.assertTrue(c.visible)
        sprite = Sprite(center=(0, 0), size=16)
        sprite.destroy()
        with self.assertRaises(DestroyedError):
            sprite.play("walk")

    def test_active_true_on_a_dead_actor_does_not_revive(self):
        c = Circle(center=(0, 0), radius=4)
        c.destroy()
        c.active = True
        self.assertFalse(c.active)
        self.assertFalse(c.is_alive)

    def test_bare_entity_can_park(self):
        e = Entity()
        e.active = False
        self.assertFalse(e.active)
        e.active = True
        self.assertTrue(e.active)
        e.destroy()

    def test_text_clone(self):
        t = Text("x", center=(0, 0))
        copy = t.clone()
        self.assertEqual(str(copy.text.value), "x")
        t.destroy()
        copy.destroy()

    def test_bad_hex_warns_and_is_magenta(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            c = Circle(center=(0, 0), radius=4, color="#")
        self.assertTrue(any("magenta" in str(w.message) for w in caught))
        self.assertEqual(c.color.rgb[:3], (1.0, 0.0, 1.0))
        c.destroy()

    def test_ease_typo_suggests(self):
        from scena.easing import resolve_ease
        with self.assertRaises(ValueError) as ctx:
            resolve_ease("ease_inn")
        self.assertIn("ease_in", str(ctx.exception))

    def test_param_skeleton_lists_real_keywords(self):
        guide = layout.GUIDE_TOOLS
        sys.path.insert(0, guide)
        import validate_guia as v
        rows = v.param_skeleton(Circle)
        names = [name for name, _, _ in rows]
        self.assertIn("radius", names)
        self.assertIn("center", names)


class TestGroupNameVerbs(unittest.TestCase):
    """Single-name group verbs reject a list with a Scena message, not a builtin."""

    def setUp(self):
        self.circle = Circle(center=(0, 0), radius=4, group="keep")

    def tearDown(self):
        if self.circle.is_alive:
            self.circle.destroy()

    def _unchanged(self, call):
        before = set(self.circle.group)
        with self.assertRaises(TypeError) as cm:
            call()
        self.assertNotIn("unhashable", str(cm.exception))
        self.assertEqual(set(self.circle.group), before)
        return str(cm.exception)

    def test_entity_verbs_reject_a_list_an_int_none_and_blank(self):
        for verb in (
            self.circle.add_to_group,
            self.circle.remove_from_group,
            self.circle.tagged,
        ):
            message = self._unchanged(lambda v=verb: v(["a", "b"]))
            self.assertIn("tag(", message)
            for bad in (3, None, ""):
                self._unchanged(lambda v=verb, b=bad: v(b))

    def test_hitbox_verbs_reject_a_list_an_int_none_and_blank(self):
        sprite = Sprite(center=(0, 0), size=16, hitbox_shape="rect")
        part = sprite.add_hitbox(group="hurt")
        self.addCleanup(sprite.destroy)
        before = set(part.group)
        for verb in (part.add_to_group, part.remove_from_group):
            with self.assertRaises(TypeError) as cm:
                verb(["a", "b"])
            self.assertIn("tag(", str(cm.exception))
            self.assertNotIn("unhashable", str(cm.exception))
            for bad in (3, None, ""):
                with self.assertRaises(TypeError) as cm:
                    verb(bad)
                self.assertNotIn("unhashable", str(cm.exception))
            self.assertEqual(set(part.group), before)


class TestConstructorKnobsNeverLeakFloat(unittest.TestCase):
    """A2 (Testing Design): three constructor knobs used raw ``float()``:
    Line's home ``length`` / ``angle``, ``Ellipse(padding=)`` and the Rect spine
    ``height``. Junk leaked Python's "could not convert" / "float() argument".
    Found by ``test_hyp_api.TestConstructorFuzz`` at the ci profile."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_bad_values_raise_scena_errors(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from hypothesis_support import leak_message
        calls = {
            "Line(length=, angle=)": lambda v: Line(length=v, angle=0),
            "Line(angle=, length=)": lambda v: Line(angle=v, length=5),
            "Ellipse(padding=)": lambda v: Ellipse(from_rect=Rect(), padding=v),
            "Rect spine height=": lambda v: Rect(p1=(0, 0), p2=(5, 0), height=v, anchor="cap"),
        }
        for label, call in calls.items():
            for bad in ("x", "", None, [1], math.nan, math.inf):
                with self.subTest(call=label, bad=bad):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        with self.assertRaises((TypeError, ValueError)) as ctx:
                            call(bad)
                    self.assertIsNone(leak_message(ctx.exception), str(ctx.exception))

    def test_negative_size_knobs_raise(self):
        for label, call in {
            "Line length": lambda: Line(length=-1, angle=0),
            "Rect spine height": lambda: Rect(p1=(0, 0), p2=(5, 0), height=-1, anchor="cap"),
        }.items():
            with self.subTest(call=label):
                with self.assertRaises(ValueError):
                    call()


class TestSurfaceFuzzFindings(unittest.TestCase):
    """A3–A5 (Testing Design): minimal repros found by ``test_hyp_surface``.

    A3 — numeric knobs leaked ``float()`` for None / bool / tuple / object (the
    guard let non-strings through, and interned looks built their key in
    ``__new__`` before the guard ran). A4 — structured knobs (radius pairs,
    offsets, directions, scroll, filter inputs, colormaps, counts) and a few
    functions leaked Python's messages. A5 — widget geometry leaked, and a
    rejected widget moved the HUD layout cursor."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    CASES = {
        # A3: class-wide numeric guard (sampled; the fuzzer covers every class)
        "Bloom(intensity=None)": lambda: scena.Bloom(intensity=None),
        "Stars(twinkle=True)": lambda: scena.Stars(twinkle=True),
        "Neon(amount='x')": lambda: scena.Neon(amount="x"),
        "Metal(speed=object())": lambda: scena.Metal(speed=object()),
        "SkyGradient(fade=(1, 2))": lambda: scena.SkyGradient(fade=(1, 2)),
        "Kaleidoscope(segments=fn)": lambda: scena.Kaleidoscope(segments=lambda: 3),
        # A4: structured knobs
        "Dilate(radius=object())": lambda: scena.Dilate(radius=object()),
        "Erode(radius='')": lambda: scena.Erode(radius=""),
        "Blur(input=object())": lambda: scena.Blur(input=object()),
        "DropShadow(offset='')": lambda: scena.DropShadow(offset=""),
        "Shadow(offset=None)": lambda: scena.Shadow(offset=None),
        "DistantLight(direction=None)": lambda: scena.DistantLight(direction=None),
        "Chromadust(scroll='')": lambda: scena.Chromadust(scroll=""),
        "Colormap(colors='00')": lambda: scena.Colormap(colors="00"),
        "Contrail(max_points=object())": lambda: scena.Contrail(max_points=object()),
        "Contrail(max_points=inf)": lambda: scena.Contrail(max_points=math.inf),
        "CheapGlow(alpha='')": lambda: scena.CheapGlow(alpha=""),
        "Svg(width=fn)": lambda: scena.Svg(width=lambda: 3),
        "Vec2(tuple='')": lambda: scena.Vec2(tuple=""),
        "remap(None)": lambda: scena.remap(None),
        "vec_from_angle(None)": lambda: scena.vec_from_angle(None),
        # A5: widgets
        "Button(top_left='')": lambda: scena.Button(top_left=""),
        "CheckBox(top_left={})": lambda: scena.CheckBox(top_left={}),
        "DropDown(top_left=object())": lambda: scena.DropDown(options=["a"], top_left=object()),
        "Slider(top_left=(nan, 0))": lambda: scena.Slider(top_left=(math.nan, 0)),
        "Button(top_left=fn)": lambda: scena.Button(top_left=lambda: (1, 2)),
        "Button(x1=3)": lambda: scena.Button(x1=3),
        "TextInput(width='w')": lambda: scena.TextInput(width="w"),
        "CheckBox(size='')": lambda: scena.CheckBox(size=""),
        "Gradient(size=fn)": lambda: scena.Gradient(size=lambda: 3),
        "Lattice(scroll=dict)": lambda: scena.Lattice(scroll={"": 0, "0": 0}),
        "Vec2(tuple=dict)": lambda: scena.Vec2(tuple={"": 0, "0": 0}),
        "DropShadow(dx=fn)": lambda: scena.DropShadow(dx=lambda: 1),
        "ColorSweep(axis=nan)": lambda: scena.ColorSweep(axis=math.nan),
        "Slider(min_value=fn)": lambda: scena.Slider(min_value=lambda: 1),
        "Track(angle='x')": lambda: scena.Track(points=[(0, 0), (10, 0)], angle="x"),
        "ready(n, fn)": lambda: scena.ready("m3_fn", lambda: 1),
        "recently(n, 1, hold=fn)": lambda: scena.recently("m3_fn", 1, hold=lambda: 1),
        "chase(dt=fn)": lambda: scena.chase(1, 2, 1, dt=lambda: 1),
        "amp_db(floor=fn)": lambda: scena.amp_db(0.5, floor=lambda: 1),
        "canvas.shake(fn)": lambda: scena.canvas.shake(lambda: 1),
        "canvas.glitch(fn)": lambda: scena.canvas.glitch(lambda: 1),
        "Rect(corner_radius=fn)": lambda: scena.Rect(center=(0, 0), width=2, height=2, corner_radius=lambda: 1),
        "canvas.flash(fn)": lambda: scena.canvas.flash(lambda: 1),
        "canvas.zoom_by(fn)": lambda: scena.canvas.zoom_by(lambda: 2),
        "chase(rate=fn)": lambda: scena.chase(1, 2, lambda: 1),
        "scale_to(fn, time=1)": lambda: scena.Circle(radius=2).scale_to(lambda: 2, time=1),
        "Ellipse(from_rect=False)": lambda: scena.Ellipse(from_rect=False),
        "Ellipse(from_rect=Circle)": lambda: scena.Ellipse(from_rect=scena.Circle(radius=2)),
        "Line(circle=Rect)": lambda: scena.Line(circle=scena.Rect(center=(0, 0), width=2, height=2),
                                                angle=0, length=3),
        "Line(parallel_to=None)": lambda: scena.Line(p1=(0, 0), parallel_to=None, length=3),
        "Text(width=fn)": lambda: scena.Text("a", width=lambda: 3),
        "ProceduralFill(seed=None)": lambda: scena.ProceduralFill(seed=None),
        "Text(top_left='')": lambda: scena.Text("a", layer="ui", top_left=""),
        "Text(top_right=object())": lambda: scena.Text("a", layer="ui", top_right=object()),
        "Text(top_center=(inf, 0))": lambda: scena.Text("a", top_center=(math.inf, 0)),
        "Text(x1=3)": lambda: scena.Text("a", x1=3),
        "Line(x1=0, …)": lambda: scena.Line(x1=0, y1=0, x2=1, y2=1),
    }

    def test_bad_values_raise_scena_errors(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from hypothesis_support import leak_message
        for label, call in self.CASES.items():
            with self.subTest(call=label):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with self.assertRaises((TypeError, ValueError)) as ctx:
                        call()
                self.assertIsNone(leak_message(ctx.exception), str(ctx.exception))

    def test_flags_take_a_real_bool(self):
        # A12: "no" is truthy in Python; it silently switched these ON.
        for label, call in {
            "Stars(enabled='no')": lambda: scena.Stars(enabled="no"),
            "Circle(use_center='no')": lambda: scena.Circle(radius=2, use_center="no"),
            "Contrail(fade='no')": lambda: scena.Contrail(fade="no"),
            "Slider(only_int=None)": lambda: scena.Slider(only_int=None),
            "set_watchdog('no')": lambda: scena.set_watchdog("no"),
            "show_tracks('no')": lambda: scena.show_tracks("no"),
        }.items():
            with self.subTest(call=label):
                with self.assertRaises(TypeError):
                    call()
        scena.set_watchdog(1)      # 0 / 1 still read as a flag
        scena.set_watchdog(True)

    def test_set_extrude_focus_rejects_junk(self):
        from scena.recipes import get_extrude_focus
        before = get_extrude_focus()
        with self.assertRaises(TypeError):
            scena.set_extrude_focus("x", 0)
        self.assertEqual(get_extrude_focus(), before)

    def test_color_sweep_axis_is_strict(self):
        # A13: an unknown name fell back to radial and numbers wrapped (7 -> 1).
        with self.assertRaises(ValueError) as ctx:
            scena.ColorSweep(axis="horizontl")
        self.assertIn("horizontal", str(ctx.exception))
        for bad in (7, 1.5, -1):
            with self.subTest(axis=bad):
                with self.assertRaises(ValueError):
                    scena.ColorSweep(axis=bad)
        with self.assertRaises(TypeError):
            scena.ColorSweep(axis=None)
        self.assertEqual(scena.ColorSweep(axis="h").axis, "horizontal")
        self.assertEqual(scena.ColorSweep(axis=2).axis, "vertical")
        sweep = scena.ColorSweep(axis="vertical")
        with self.assertRaises(ValueError):
            sweep.axis = "sideways"
        self.assertEqual(sweep.axis, "vertical")   # a rejected write changes nothing

    def test_ready_without_interval_on_a_new_name_is_a_type_error(self):
        # Was KeyError from the poll-slot dict (M1 open item, fixed in M3).
        c = scena.Circle(radius=2)
        try:
            for call in (lambda: scena.ready("m3_never_seen"),
                         lambda: c.ready("m3_never_seen")):
                with self.assertRaises(TypeError) as ctx:
                    call()
                self.assertIn("interval", str(ctx.exception))
        finally:
            c.destroy()

    def test_track_rotation_formula_links(self):
        c = scena.Circle(radius=3)
        t = scena.Track(points=[(0, 0), (10, 0), (10, 10)], angle=lambda: c.radius * 10)
        try:
            c.radius = 5
            self.assertAlmostEqual(float(t.angle), 50.0)
        finally:
            t.destroy()
            c.destroy()

    def test_vec2_rejects_unknown_keywords(self):
        with self.assertRaises(TypeError) as ctx:
            scena.Vec2(1, 2, zz_not_a_knob=1)
        self.assertIn("zz_not_a_knob", str(ctx.exception))

    def test_rejected_widget_does_not_move_the_layout_cursor(self):
        from scena.orchestration import ScenaFramework
        wm = ScenaFramework.get_instance().widget_manager
        before = (wm._stack_x, getattr(wm, "_stack_bottom", None), getattr(wm, "_column_top", None))
        for bad in ({}, "w", object()):
            with self.subTest(width=bad):
                with self.assertRaises((TypeError, ValueError)):
                    scena.DropDown(options=["a"], width=bad)
                self.assertEqual(
                    (wm._stack_x, getattr(wm, "_stack_bottom", None), getattr(wm, "_column_top", None)),
                    before)

    def test_rejected_top_left_does_not_move_the_layout_cursor(self):
        """A5 for the point spelling: every widget and Text validate first."""
        from scena.orchestration import ScenaFramework
        wm = ScenaFramework.get_instance().widget_manager

        def cursor():
            return (wm._stack_x, getattr(wm, "_stack_bottom", None),
                    getattr(wm, "_column_top", None), wm._stack_extra_gap)

        st = scena.st
        st.a5_v = 0.5
        st.a5_s = ""
        st.a5_b = False
        makers = {
            "Button": lambda bad: scena.Button(top_left=bad),
            "Slider": lambda bad: scena.Slider(st["a5_v"], top_left=bad),
            "CheckBox": lambda bad: scena.CheckBox(st["a5_b"], top_left=bad),
            "TextInput": lambda bad: scena.TextInput(st["a5_s"], top_left=bad),
            "DropDown": lambda bad: scena.DropDown(options=["a"], top_left=bad),
            "Text": lambda bad: scena.Text("a", top_left=bad),
        }
        before = cursor()
        for name, make in makers.items():
            for bad in ({}, "w", object(), (math.nan, 0), (0, math.inf), (1, 2, 3)):
                with self.subTest(widget=name, top_left=bad):
                    with self.assertRaises((TypeError, ValueError)):
                        make(bad)
                    self.assertEqual(cursor(), before)

    def test_a_rejected_hud_item_leaves_the_column_exactly(self):
        """A5, the whole class: every HUD constructor, every keyword. With a
        live item already in the column (the A5 guards above start from an
        empty one, where the "last participant leaves" rewind hid the move),
        a constructor that raises after taking its slot left the cursor
        advanced: ``Text(glow=[])`` / ``Text(angle="x")`` validated after
        ``begin_hud_item`` (deep serial pass, 2026-10-09). The rollback now
        puts back the cursor the item found, whatever raised."""
        from scena.orchestration import ScenaFramework
        from scena.text import Text as _Text
        from scena.uiwidget import UIWidget
        wm = ScenaFramework.get_instance().widget_manager

        def cursor():
            return (wm._origin_x, wm._origin_top, wm._stack_x, wm._stack_bottom,
                    wm._stack_extra_gap, wm._column_right, wm._column_top,
                    wm._column_origin_x,
                    [r() for r in wm._column_participants], list(wm._label_column))

        st = scena.st
        st.a5c_v = 0.5
        st.a5c_s = ""
        st.a5c_b = False
        base = {
            "Button": {}, "Text": {"text": "a"}, "Menu": {"options": ["a"]},
            "Slider": {"cell": st.a5c_v}, "CheckBox": {"cell": st.a5c_b},
            "TextInput": {"cell": st.a5c_s}, "DropDown": {"options": ["a"]},
        }
        classes = {n: getattr(scena, n) for n in scena.__all__
                   if inspect.isclass(getattr(scena, n))
                   and issubclass(getattr(scena, n), (UIWidget, _Text))}
        self.assertEqual(set(classes) - set(base), set(), "a new HUD class: add its base call")
        junk = (object(), [], "w", math.nan)
        scena.ui.stack_reset()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            keeper = scena.Text("column keeper")
            try:
                for name, cls in classes.items():
                    params = [p for p in inspect.signature(cls).parameters
                              if not p.startswith("_")]
                    for param in params:
                        for bad in junk:
                            before = cursor()
                            try:
                                obj = cls(**{**base[name], param: bad})
                            except Exception:  # noqa: BLE001 — the contract is the cursor
                                with self.subTest(call=f"{name}({param}={bad!r})"):
                                    self.assertEqual(cursor(), before)
                            else:
                                obj.destroy()
                            obj = None
            finally:
                keeper.destroy()


class TestReactiveKnobsTakeFormulas(unittest.TestCase):
    """R8 (Testing Design): the A3 guard rejected functions on every numeric
    knob, including reactive fields the constructor links (``Rain.from_rect``
    passes ``width=lambda: rect.width``). Bug class: a validation list that
    must be kept in sync by hand. Guard: every exported class, every numeric
    knob that names a declared field slot, must accept a formula."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_every_reactive_knob_accepts_a_formula(self):
        from scena.validate import formula_knobs, _is_plain_number
        checked = 0
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not isinstance(cls, type) or not hasattr(cls, "_field_slots"):
                continue
            try:
                params = inspect.signature(cls).parameters
            except (TypeError, ValueError):
                continue
            knobs = formula_knobs(cls)
            for pname, p in params.items():
                if pname not in knobs or not _is_plain_number(p.default):
                    continue
                default = p.default
                checked += 1
                with self.subTest(knob=f"{name}({pname}=fn)"):
                    obj = None
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            obj = cls(**{pname: lambda d=default: d})
                    except TypeError as exc:
                        self.assertNotIn("got a function", str(exc))
                    except Exception:
                        pass  # other required knobs; the numeric guard passed
                    finally:
                        destroy = getattr(obj, "destroy", None)
                        if callable(destroy):
                            destroy()
        self.assertGreaterEqual(checked, 15, "vacuous: no reactive knobs found")

    def test_rain_from_rect_links_the_pad(self):
        rect = scena.Rect(center=(40, 50), width=30, height=40)
        rain = scena.Rain.from_rect(rect)
        try:
            rect.width = 50
            self.assertAlmostEqual(float(rain.width), 50.0)
        finally:
            rain.destroy()
            rect.destroy()


class TestNoFloatAroundFormulaValidators(unittest.TestCase):
    """A7 (Testing Design): ``finite`` / ``magnitude`` let a formula through
    (reactive writes link it), so ``float(finite(x))`` at a fixed-number site
    leaked ``float()``'s message for a function. Fixed-number sites use
    ``validate.number`` / ``validate.fixed_magnitude``."""

    def test_no_float_of_finite_or_magnitude(self):
        import ast
        bad = []
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            if path.endswith(os.sep + "validate.py"):
                continue   # number() itself: the one place that knows the payload is checked
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "float" and node.args
                        and isinstance(node.args[0], ast.Call)):
                    inner = node.args[0].func
                    name = inner.id if isinstance(inner, ast.Name) else getattr(inner, "attr", None)
                    if name in ("finite", "magnitude"):
                        bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} float({name}(...))")
        self.assertEqual(bad, [], "use validate.number / validate.fixed_magnitude")


class TestNumericGuardFastPath(unittest.TestCase):
    """The numeric guard's fast path (``_numbers_fast_ok``, skips
    ``bind_partial``) must never accept what the full check rejects."""

    VALUES = (0, 1, -1, 2, 2.5, -0.5, math.nan, math.inf, True, "x", None, (1, 2))

    def test_fast_accept_implies_full_accept(self):
        from unittest import mock
        from scena import validate as v
        sigs = []
        for name in scena.__all__:
            cls = getattr(scena, name)
            if not isinstance(cls, type):
                continue
            for attr in ("__init__", "__new__"):
                fn = cls.__dict__.get(attr)
                fn = getattr(fn, "__func__", fn)
                if fn is None or not getattr(fn, "_scena_numbers_guarded", False):
                    continue
                try:
                    sigs.append((name, inspect.signature(inspect.unwrap(fn))))
                except (TypeError, ValueError):
                    pass
        self.assertGreater(len(sigs), 50, "vacuous: few guarded constructors found")
        checked = 0
        for name, sig in sigs:
            numeric = v._sig_info(sig)[4]
            for knob in numeric:
                for val in self.VALUES:
                    kwargs = {knob: val}
                    if not v._numbers_fast_ok(sig, (), kwargs):
                        continue
                    checked += 1
                    with self.subTest(call=f"{name}({knob}={val!r})"):
                        with mock.patch.object(v, "_numbers_fast_ok", lambda *a: False):
                            v.check_numeric_params(name, sig, (), kwargs)
        self.assertGreater(checked, 100)


class TestBareMagnitudeOnlyOnReactivePaths(unittest.TestCase):
    """A8 (Testing Design): ``validate.magnitude`` lets a function through
    (reactive writes link it). At a fixed-number site the function was stored
    and crashed later in a frame (timed ``scale_to(fn)``, ``canvas.zoom(fn)``,
    ``Rect(corner_radius=fn)``). Fixed sites call ``fixed_magnitude``; a bare
    ``magnitude(`` is allowed only where the value can become a link."""

    # (file, enclosing function) -> why a formula may pass here.
    ALLOWED = {
        ("state.py", "_coerce_magnitude_slot"): "ScalarSlot write / constructor slot (links a formula)",
        ("state.py", "_coerce_constrained"): "ScalarSlot write / constructor slot (links a formula)",
        ("shapes.py", "_reject_bad_spread"): "callables return before the check",
        ("validate.py", "fixed_magnitude"): "the fixed wrapper itself",
    }

    def test_bare_magnitude_sites_are_allowlisted(self):
        import ast
        found = set()

        def walk(node, stack, fname):
            for ch in ast.iter_child_nodes(node):
                st = stack + [ch.name] if isinstance(
                    ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else stack
                if (isinstance(ch, ast.Call) and isinstance(ch.func, ast.Name)
                        and ch.func.id == "magnitude"):
                    found.add((fname, ".".join(stack) or "<module>"))
                walk(ch, st, fname)

        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            with open(path, encoding="utf-8") as fh:
                walk(ast.parse(fh.read(), path), [], os.path.basename(path))
        self.assertEqual(sorted(found - set(self.ALLOWED)), [],
                         "fixed-number site: use validate.fixed_magnitude")


class TestNoFloatPowerSquares(unittest.TestCase):
    """A8 (Testing Design): ``(x - hx) ** 2`` raised ``OverflowError`` for a
    huge-but-finite author coordinate (Slider handle, Ellipse / Track
    ``contains_point``); ``v * v`` saturates to inf. Engine geometry squares
    with ``_sq`` or a product."""

    # numpy arrays / bounded easing curves (inputs in [0, 1]).
    EXEMPT = {"audio.py", "effects.py"}

    def test_no_power_two_on_expressions(self):
        import ast
        bad = []
        for path in iter_files(os.path.join(ROOT, "scena"), ".py"):
            if os.path.basename(path) in self.EXEMPT:
                continue
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), path)
            for node in ast.walk(tree):
                if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
                        and isinstance(node.right, ast.Constant) and node.right.value == 2):
                    left = node.left
                    if isinstance(left, ast.Constant) or (
                            isinstance(left, ast.Name) and left.id.lstrip("_").isupper()):
                        continue   # a constant squared cannot overflow at run time
                    bad.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")
        self.assertEqual(bad, [], "square with _sq(v) / v * v, not ** 2")

    def test_huge_coordinates_do_not_overflow_hit_tests(self):
        big = (1e200, 1e200)
        made = [scena.Ellipse(center=(0, 0), width=4, height=2),
                scena.Track.circle(center=(0, 0), radius=5),
                scena.Circle(radius=3)]
        try:
            for shape in made:
                with self.subTest(shape=type(shape).__name__):
                    self.assertFalse(shape.contains_point(big))
            s = scena.Slider(top_left=(1e200, 1e200))
            made.append(s)
            s._on_mouse_move(1.0, 1.0)
        finally:
            for m in made:
                m.destroy()


class TestDeadVerbFindings(unittest.TestCase):
    """A6 / A7 (Testing Design): verbs on a destroyed actor, found once the
    P6 fuzzer stopped skipping every method (vacuous argument guessing)."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def _dead(self, make):
        obj = make()
        obj.destroy()
        return obj

    def test_resolve_now_does_not_reenroll_a_dead_actor(self):
        from scena.collision import get_collision_system
        from scena.state import DestroyedError
        c = self._dead(lambda: scena.Circle(radius=3))
        with self.assertRaises(DestroyedError):
            c.resolve_now("nobody")
        self.assertFalse(any(getattr(k, "_shape", None) is c
                             for k in get_collision_system()._colliders))

    def test_absorb_contract(self):
        from scena.state import DestroyedError
        a = scena.Circle(radius=3)
        try:
            with self.assertRaises(TypeError):
                a.absorb(None)
            with self.assertRaises(ValueError):
                a.absorb(a)
            with self.assertRaises(DestroyedError):
                a.absorb(self._dead(lambda: scena.Circle(radius=5)))
            with self.assertRaises(DestroyedError):
                self._dead(lambda: scena.Circle(radius=5)).absorb(scena.Circle(radius=1))
        finally:
            a.destroy()

    def test_square_takes_in_a_square(self):
        # Used to recurse forever (super()._takein, the dispatcher, not the hook).
        a = scena.Square(center=(0, 0), length=4)
        b = scena.Square(center=(5, 6), length=8, angle=30)
        a.absorb(b)
        self.assertEqual((float(a.center.x), float(a.center.y)), (5.0, 6.0))
        self.assertEqual((float(a.length), float(a.width), float(a.angle)), (8.0, 8.0, 30.0))
        t = scena.Square(top_left=(0, 0), length=4)
        t << scena.Square(top_left=(3, 3), length=6)
        self.assertEqual(float(t.length), 6.0)
        r = scena.Rect(center=(0, 0), width=2, height=3)
        r << scena.Square(center=(9, 8), length=5)
        self.assertEqual((float(r.width), float(r.height)), (5.0, 5.0))
        for s in (a, t, r):
            s.destroy()

    def test_debug_and_hitbox_verbs_raise_destroyed(self):
        from scena.state import DestroyedError
        p = self._dead(lambda: scena.Polygon(points=[(0, 0), (10, 0), (0, 10)]))
        for verb in (p.show_handles, p.show_points):
            with self.subTest(verb=verb.__name__):
                with self.assertRaises(DestroyedError):
                    verb()
        sp = self._dead(lambda: scena.Sprite())
        with self.assertRaises(DestroyedError):
            sp.add_hitbox()

    def test_dead_source_shapes_are_refused(self):
        from scena.state import DestroyedError
        c = self._dead(lambda: scena.Circle(radius=5))
        r = self._dead(lambda: scena.Rect(center=(0, 0), width=3, height=4))
        t = self._dead(lambda: scena.Track.circle(center=(0, 0), radius=5))
        for label, call in {
            "tangent_line_from_angle": lambda: c.tangent_line_from_angle(at_angle=10, size=3),
            "tangent_lines_from": lambda: c.tangent_lines_from((20, 20)),
            "Ellipse(from_rect=dead)": lambda: scena.Ellipse(from_rect=r),
            "Track.reversed()": lambda: t.reversed(),
        }.items():
            with self.subTest(call=label):
                with self.assertRaises(DestroyedError):
                    call()

    def test_first_read_on_a_dead_widget_leaves_the_graph_alone(self):
        from scena.state import get_scena_system
        b = self._dead(lambda: scena.Button())
        g = get_scena_system().dependency_graph
        self.enterContext(gc_paused())
        before = settled_graph_size()
        b._displayed_text()
        self.assertEqual(len(g.nodes), before)
        self.assertIsNone(getattr(b.data, "_owner", None))


class TestMethodJunkFindings(unittest.TestCase):
    """A9 (Testing Design): author methods on live instances, found by the
    methods phase of ``test_hyp_surface`` (junk as the first argument)."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def test_junk_arguments_raise_scena_errors(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from hypothesis_support import leak_message
        c = scena.Circle(radius=3)
        track = scena.Track.circle(center=(0, 0), radius=10)
        box = scena.Box(center=(0, 0), width=40, height=20)
        red = scena.Color("red")
        v = scena.Vec2(3, 4)
        cases = {
            "circle.set_alpha(None)": lambda: c.set_alpha(None),
            "circle.look_like(None)": lambda: c.look_like(None),
            "Blur(1).compose(None)": lambda: scena.Blur(1).compose(None),
            "clock.advance(None)": lambda: scena.clock.advance(None),
            "Gradient().darker(None)": lambda: scena.Gradient().darker(None),
            "Texture.set_alpha(None)": lambda: scena.Texture().set_alpha(None),
            "Palette().reset(None)": lambda: scena.Palette().reset(None),
            "History().pop(None)": lambda: scena.History().pop(None),
            "State().remove(None)": lambda: scena.State().remove(None),
            "track.at(None)": lambda: track.at(None),
            "track.angle_at('')": lambda: track.angle_at(""),
            "track.spaced_points(None)": lambda: track.spaced_points(None),
            "track.spaced_points(10**9)": lambda: track.spaced_points(10 ** 9),
            "track.orbit(None)": lambda: track.orbit(None),
            "track.wander(1, seed=1.5)": lambda: track.wander(1, seed=1.5),
            "v.dot(None)": lambda: v.dot(None),
            "v.rotate(None)": lambda: v.rotate(None),
            "v.reflect_about(object())": lambda: v.reflect_about(object()),
            "red.lighter(None)": lambda: red.lighter(None),
            "red.with_alpha('x')": lambda: red.with_alpha("x"),
            "red.jitter(None)": lambda: red.jitter(None),
            "box.inset(None)": lambda: box.inset(None),
            "grid.cell(None)": lambda: box.grid(2, 2).cell(None),
            "grid.cell(1.7)": lambda: box.grid(2, 2).cell(1.7),
        }
        try:
            for label, call in cases.items():
                with self.subTest(call=label):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        with self.assertRaises((TypeError, ValueError)) as ctx:
                            call()
                    self.assertIsNone(leak_message(ctx.exception), str(ctx.exception))
        finally:
            c.destroy()
            track.destroy()

    def test_rejected_fade_in_does_not_show_a_hidden_shape(self):
        # A10: fade_in / dissolve_in set visible = True before validating.
        p = scena.Point(x=1, y=1, visible=False)
        try:
            for verb in (p.fade_in, p.dissolve_in):
                with self.subTest(verb=verb.__name__):
                    with self.assertRaises(TypeError):
                        verb("slow")
                    self.assertFalse(p.visible)
        finally:
            p.destroy()

    def test_rejected_contrail_leaves_no_stroke(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from system_support import registry
        mark = registry()._next_key
        for bad in (-1, -1e308):
            with self.subTest(duration=bad):
                with self.assertRaises(ValueError):
                    scena.Contrail(duration=bad)
                self.assertEqual([k for k in registry().live.keys() if k > mark], [])

    def test_tangent_lines_from_is_all_or_nothing(self):
        from unittest import mock
        import scena.shapes as shapes_mod
        c = scena.Circle(radius=5)
        real_line = shapes_mod.Line
        made = []

        def second_fails(*args, **kwargs):
            if made:
                raise ValueError("second line refused")
            line = real_line(*args, **kwargs)
            made.append(line)
            return line

        try:
            with mock.patch.object(shapes_mod, "Line", side_effect=second_fails):
                with self.assertRaises(ValueError):
                    c.tangent_lines_from((20, 20))
            self.assertEqual(len(made), 1)
            self.assertFalse(made[0].is_alive)  # the first line was rolled back
        finally:
            c.destroy()

    def test_container_errors_are_worded(self):
        with self.assertRaises(IndexError) as ctx:
            scena.History().pop()
        self.assertIn("empty", str(ctx.exception))
        with self.assertRaises(KeyError) as ctx:
            scena.State().remove("nope")
        self.assertIn("nope", str(ctx.exception))

    def test_accepted_forms_still_work(self):
        v = scena.Vec2(3, 4)
        self.assertEqual(v.dot((1, 0)), 3.0)                      # a pair works like a Vec2
        self.assertEqual(scena.Palette().reset(-1)._cursor >= 0, True)   # negative wraps
        g = scena.Box(center=(0, 0), width=40, height=20).grid(2, 2)
        self.assertIs(g.cell(1.0), g.cell(1))                     # a whole float is an index
        self.assertEqual(float(scena.Color("red").with_alpha(2).alpha), 1.0)   # clamped
        scena.Color("red").jitter(1e308)                           # huge range saturates


if __name__ == "__main__":
    unittest.main()
