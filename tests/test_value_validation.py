"""Every value door applies the Numbers rule (graphics review, validation leaks).

Scena Design, "Numbers and signs": a number is a finite real (``bool`` is
never a number), a point is two finite numbers, and a flag is a real bool (or
0 / 1). A refused value raises a Scena error that names the knob, never
Python's own ``could not convert`` / ``int too large`` from inside the engine.

The 2026-10-08 review found the rule applied on some doors only:

* SA6: ``center = (nan, 0)`` / ``move_to((nan, 0))`` gave a NaN center.
* SA7: ``scale =`` coerced with ``float()``: raw errors, ``True`` accepted.
* E12: ``mass = nan`` / ``True`` accepted, ``mass = "x"`` a raw error.
* SA15: ``angle = 10**400`` stored; every ``finite()`` caller raised
  ``OverflowError`` on a huge int.
* SA12 / PB13 / PA11: ``Point(visible="no")``, ``Sprite(flip_x="no")``,
  ``play(resume="no")``, ``clip(yoyo="no")`` accepted a string as a flag.

The earlier guards walked slot fields (``ScalarSlot``) and constructor flags
whose default is a bool. Property-backed knobs (``scale``, ``mass``), point
fields, flags typed ``Optional[bool]`` or ``Any``, and method flags were
outside the walk, so this guard enumerates from the instances:

* **Setters.** Every public data descriptor (property with a setter, slot) on
  one instance of each export, classified by the value it reads: a number
  gets ``NUM_JUNK``, a point gets ``POINT_JUNK``. Each must raise an author
  error, or be listed in ``ANY_VALUE`` with the reason.
* **Constructor flags.** A keyword that names a bool-valued property of the
  instance (``visible``, ``flip_x``), or whose annotation says ``bool``.
* **Method flags.** A public method's keyword with a bool default: if the
  call works with ``False``, it must refuse ``"no"``.

Known violations are shrink-only (``graphics_known.VALUES``).

    python tests/run_tiers.py focused test_value_validation
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import AUTHOR_ERRORS, fresh_world, leak_message, quiet  # noqa: E402
from surface_support import constructor_names, make_instance, remove  # noqa: E402

import scena  # noqa: E402
from scena.shapes import Point  # noqa: E402

NAN, INF = float("nan"), float("inf")
NUM_JUNK = ("x", [1], True, NAN, INF, 10 ** 400)
POINT_JUNK = ((NAN, 0), (0, INF), (10 ** 400, 0))

# Setters that take any value on purpose, with the reason.
ANY_VALUE = {
    "Attribute.value": "an Attribute holds the author's own value, of any type",
}
# One junk value a setter accepts by contract.
ACCEPTED = {
    ("mass", "inf"): "mass = STATIC (inf) pins the body",
    ("smooth", "True"): "smooth = True is the default smoothing (False is none)",
    ("breathe", "True"): "breathe = True is the default swing (False is none)",
    ("layers", "10**400"): "a whole count past the range clamps to 3, like layers = 7",
}

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _author_error(exc) -> bool:
    if isinstance(exc, UnicodeError):          # a ValueError, but Python's text
        return False
    if isinstance(exc, AttributeError):        # a refusal with a hint (Color.alpha)
        return leak_message(exc) is None and "has no setter" not in str(exc)
    return isinstance(exc, AUTHOR_ERRORS) and leak_message(exc) is None


def _junk_for(value):
    if isinstance(value, bool):
        return None
    if type(value) in (int, float):
        return NUM_JUNK
    if isinstance(value, (Point, scena.Vec2)):
        return POINT_JUNK
    if isinstance(value, tuple) and len(value) == 2 and all(type(v) in (int, float) for v in value):
        return POINT_JUNK
    return None


def _setters(cls):
    for attr in sorted(dir(cls)):
        if attr.startswith("_"):
            continue
        member = inspect.getattr_static(cls, attr, None)
        if isinstance(member, property):
            if member.fset is not None:
                yield attr
        elif member is not None and hasattr(type(member), "__set__"):
            yield attr


def _short(v) -> str:
    r = repr(v)
    return r if len(r) <= 12 else "10**400" if v == 10 ** 400 else r[:12]


def setter_violations() -> dict:
    out = {}
    for name in constructor_names():
        with fresh_world():
            try:
                with quiet():
                    obj = make_instance(name)
            except Exception:  # noqa: BLE001  (needs arguments: other suites)
                continue
            try:
                for attr in _setters(type(obj)):
                    if f"{name}.{attr}" in ANY_VALUE:
                        continue
                    try:
                        with quiet():
                            current = getattr(obj, attr)
                    except Exception:  # noqa: BLE001
                        continue
                    junk = _junk_for(current)
                    for value in junk or ():
                        if (attr, _short(value)) in ACCEPTED:
                            continue
                        key = f"{name}.{attr} = {_short(value)}"
                        try:
                            with quiet():
                                setattr(obj, attr, value)
                        except Exception as e:  # noqa: BLE001
                            if not _author_error(e):
                                out[key] = f"{type(e).__name__}: {str(e)[:60]}"
                            continue
                        out[key] = "accepted"
                        try:
                            with quiet():
                                setattr(obj, attr, current)
                        except Exception:  # noqa: BLE001
                            pass
            finally:
                remove(obj)
    return out


def _bool_typed(param) -> bool:
    ann = param.annotation
    text = ann if isinstance(ann, str) else repr(ann)
    return isinstance(param.default, bool) or "bool" in text


def ctor_flag_violations() -> dict:
    out = {}
    for name in constructor_names():
        cls = getattr(scena, name)
        try:
            params = inspect.signature(cls).parameters
        except (TypeError, ValueError):
            continue
        with fresh_world():
            try:
                with quiet():
                    probe = make_instance(name)
            except Exception:  # noqa: BLE001
                continue
            flags = set()
            for p in params.values():
                if p.kind is not p.KEYWORD_ONLY and p.kind is not p.POSITIONAL_OR_KEYWORD:
                    continue
                reads_bool = False
                member = inspect.getattr_static(type(probe), p.name, None)
                if member is not None and not callable(member) or isinstance(member, property):
                    try:
                        with quiet():
                            reads_bool = isinstance(getattr(probe, p.name), bool)
                    except Exception:  # noqa: BLE001
                        pass
                if reads_bool or _bool_typed(p):
                    flags.add(p.name)
            remove(probe)
            factory = _ctor_factory(name)
            for flag in sorted(flags):
                try:
                    with quiet():
                        ok = factory(**{flag: False})
                except Exception:  # noqa: BLE001  (the flag needs other knobs)
                    continue
                remove(ok)
                try:
                    with quiet():
                        bad = factory(**{flag: "no"})
                except Exception as e:  # noqa: BLE001
                    if not _author_error(e):
                        out[f"{name}({flag}='no')"] = f"{type(e).__name__}: {str(e)[:60]}"
                    continue
                remove(bad)
                out[f"{name}({flag}='no')"] = "accepted"
    return out


def _sheet_path() -> str:
    from tests.test_sprite import _write_grid_png
    d = tempfile.mkdtemp(prefix="scena_vv_")
    path = os.path.join(d, "grid.png")
    _write_grid_png(path, cell=16, cols=2, rows=2)
    return path


_SHEET = None


def _sheet():
    global _SHEET
    if _SHEET is None:
        _SHEET = _sheet_path()
    sheet = scena.Sheet(_SHEET, cell=(16, 16))
    sheet.clip("a", [0, 1], fps=4)
    return sheet


def _ctor_factory(name):
    """A constructor call that works with only the probed keyword added."""
    cls = getattr(scena, name)
    if name in ("Sprite", "SpriteButton"):
        return lambda **kw: cls(_sheet(), center=(50, 50), height=32, **kw)
    if name == "Point":
        return lambda **kw: cls(1, 1, **kw)
    return lambda **kw: cls(**kw)


# Arguments a method call needs to get past arity (a clip that exists).
_ARGS = {"clip": "a", "name": "vv", "frames": [0, 1], "fps": 4}


def _method_instances():
    yield "Sheet", _sheet
    yield "Sprite", lambda: scena.Sprite(_sheet(), center=(50, 50), height=32)
    for name in ("Circle", "Rect", "Line", "Polygon", "Ellipse", "Point", "Text"):
        yield name, (lambda n=name: make_instance(n))


def method_flag_violations() -> dict:
    from test_hyp_surface import _ARG_BY_NAME
    guesses = {**_ARG_BY_NAME, **_ARGS}
    out = {}
    for label, factory in _method_instances():
        with fresh_world():
            for attr in sorted(dir(factory())):
                if attr.startswith("_"):
                    continue
                if not inspect.isfunction(inspect.getattr_static(type(factory()), attr, None)):
                    continue
                with quiet():
                    method = getattr(factory(), attr)
                try:
                    params = list(inspect.signature(method).parameters.values())
                except (TypeError, ValueError):
                    continue
                flags = [p.name for p in params if isinstance(p.default, bool)]
                need = [p for p in params if p.default is p.empty
                        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
                if not flags or any(p.name not in guesses for p in need):
                    continue
                args = [guesses[p.name] for p in need if p.kind is not p.KEYWORD_ONLY]
                kwargs = {p.name: guesses[p.name] for p in need if p.kind is p.KEYWORD_ONLY}
                for flag in flags:
                    try:
                        with quiet():
                            getattr(factory(), attr)(*args, **kwargs, **{flag: False})
                    except Exception:  # noqa: BLE001  (the guess does not fit)
                        continue
                    try:
                        with quiet():
                            getattr(factory(), attr)(*args, **kwargs, **{flag: "no"})
                    except Exception as e:  # noqa: BLE001
                        if not _author_error(e):
                            out[f"{label}.{attr}({flag}='no')"] = f"{type(e).__name__}: {str(e)[:60]}"
                        continue
                    out[f"{label}.{attr}({flag}='no')"] = "accepted"
    return out


def verb_point_violations() -> dict:
    """A non-finite point through a verb: ``move_to`` and ``about=``."""
    from geometry_support import KINDS, build
    out = {}
    verbs = {
        "move_to": lambda o, p: o.move_to(p),
        "rotate_by about": lambda o, p: o.rotate_by(10, about=p),
        "scale_by about": lambda o, p: o.scale_by(2, about=p),
    }
    with fresh_world():
        for kind in KINDS:
            for verb, call in verbs.items():
                for value in POINT_JUNK:
                    with quiet():
                        obj = build(kind)
                    if not hasattr(obj, verb.split()[0]):      # Box: a value, no verbs
                        continue
                    key = f"{kind} | {verb}({_short(value)})"
                    try:
                        with quiet():
                            call(obj, value)
                    except Exception as e:  # noqa: BLE001
                        if not _author_error(e):
                            out[key] = f"{type(e).__name__}: {str(e)[:60]}"
                    else:
                        out[key] = "accepted"
                    getattr(obj, "destroy", lambda: None)()
    return out


def _grid_sprite():
    return scena.Sprite(_sheet(), center=(50, 50), height=32)


def _bad_atlas():
    d = tempfile.mkdtemp(prefix="scena_vv_")
    path = os.path.join(d, "bad.json")
    with open(path, "wb") as f:
        f.write(b'\xff\xfe{"frames":\x80}')
    return path


# The review's named leaks that no walk reaches (exported helpers, Sheet
# parsing, hitbox views): each must raise an author error.
NAMED = {
    "SA15 middle_point(weight='x')": lambda: scena.middle_point((0, 0), (1, 1), weight="x"),
    "SA15 contains_point(nan, 0)": lambda: scena.Circle(center=(0, 0), radius=10).contains_point(NAN, 0),
    "SA15 contains_point(10**400, 0)": lambda: scena.Circle(center=(0, 0), radius=10).contains_point(10 ** 400, 0),
    "SA15 Box.contains_point(nan, 0)": lambda: scena.Rect(center=(0, 0), width=8, height=8).box.contains_point(NAN, 0),
    "SB10 from_corners(radius=lambda)": lambda: scena.Circle.from_corners(point=(0, 0), pos="top-left", radius=lambda: 5),
    "SB10 from_corners(pos=[1])": lambda: scena.Circle.from_corners(point=(0, 0), pos=[1], radius=5),
    "SC9 rp.points['a']": lambda: scena.RegularPolygon(center=(0, 0), radius=10, n=5).points["a"],
    "SC9 Polygon(points='abc')": lambda: scena.Polygon(points="abc"),
    "E10 group=''": lambda: scena.Circle(center=(0, 0), radius=3, group=""),
    "E10 group=['a', '']": lambda: scena.Circle(center=(0, 0), radius=3, group=["a", ""]),
    "E10 c.group = ''": lambda: setattr(scena.Circle(center=(0, 0), radius=3), "group", ""),
    "PA10 cell=(16.9, 16)": lambda: scena.Sheet(_sheet_path(), cell=(16.9, 16)),
    "PA10 cell=(nan, 16)": lambda: scena.Sheet(_sheet_path(), cell=(NAN, 16)),
    "PA8 a binary atlas": lambda: scena.Sheet(_sheet_path(), atlas=_bad_atlas()),
    "HP6 hb.tagged(['a'])": lambda: _grid_sprite().hitbox.tagged(["a"]),
    "HP6 part.tagged(['a'])": lambda: _grid_sprite().add_hitbox(group="hp6").tagged(["a"]),
}


class TestNamedLeaks(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_each_named_leak_raises_an_author_error(self):
        bad = {}
        for label, call in NAMED.items():
            with fresh_world():
                try:
                    with quiet():
                        call()
                except Exception as e:  # noqa: BLE001
                    if not _author_error(e):
                        bad[label] = f"{type(e).__name__}: {str(e)[:80]}"
                    continue
                bad[label] = "accepted"
        self.assertEqual(bad, {})

    def test_a_polygon_takes_a_generator_of_points(self):
        """SC9: a generator leaked "has no len()"; it is read once, like a list."""
        with fresh_world():
            p = scena.Polygon(points=((i, i * i) for i in range(4)))
            self.assertEqual(len(p.points), 4)
            p.destroy()

    def test_a_whole_float_cell_is_whole_pixels(self):
        with fresh_world():
            self.assertEqual(scena.Sheet(_sheet_path(), cell=(16.0, 16)).nframes, 4)

    def test_reprs_do_not_raise_or_run_the_link(self):
        """HP8: ``repr(sprite.hitbox["active"])`` raised AttributeError, and the
        main hitbox repr ran the active link."""
        with fresh_world():
            s = _grid_sprite()
            calls = []
            s.hitbox["active"] @= lambda: calls.append(1) or True
            calls.clear()
            self.assertIn("linked", repr(s.hitbox["active"]))
            self.assertIn("Hitbox main", repr(s.hitbox))
            self.assertEqual(calls, [], "a repr ran the link")
            part = s.add_hitbox(group="hp8")
            self.assertIn("plain", repr(part["active"]))
            s.destroy()

    def test_svg_none_clears_to_the_checker(self):
        """PB15: ``svg = None`` with a good body was a silent no-op."""
        markup = ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                  '<rect width="10" height="10" fill="red"/></svg>')
        with fresh_world():
            sv = scena.Svg(markup, center=(0, 0))
            sv.svg = None
            self.assertIsNone(sv.svg)
            self.assertTrue(sv._placeholder)
            sv.destroy()

    def test_force_no_does_not_unlink(self):
        """A truthy ``force="no"`` unlinked a linked part; it is refused, and
        the link stays."""
        with fresh_world():
            src = scena.Circle(center=(0, 0), radius=3)
            c = scena.Circle(center=lambda: src.center, radius=5)
            with self.assertRaises(TypeError):
                c.rotate_by(10, about=(50, 0), force="no")
            self.assertTrue(c["center"].is_linked if hasattr(c["center"], "is_linked") else c.center._link is not None)
            src.destroy()
            c.destroy()

    def test_equilateral_triangle_does_not_publish_n(self):
        import inspect
        self.assertNotIn("n", inspect.signature(scena.EquilateralTriangle).parameters)
        with fresh_world():
            t = scena.EquilateralTriangle(center=(0, 0), radius=5, n=3)    # still accepted
            self.assertEqual(len(t.points), 3)
            t.destroy()


# Verbs whose one required argument is a point (``pan_by((dx, dy))``).
_POINT_FIRST = {"pan_by", "pan_to"}
# Verbs that need one of ``time=`` / ``speed=`` (no instant form): ``ease=``
# alone is refused by the missing-timing error, which names ``time=``.
_TIMING_REQUIRED = {"move_along": ("circle",)}


def ease_without_time_violations() -> dict:
    """Every public verb with ``time=`` and ``ease=`` refuses ``ease=`` alone:
    an instant call has no curve, and the value was ignored (graphics review
    E18). Same arguments as the flag walk; the canvas camera verbs too."""
    from test_hyp_surface import _ARG_BY_NAME
    guesses = {**_ARG_BY_NAME, **_ARGS, "value": 1.0, "factor": 1.1}
    out = {}
    checked = ease_without_time_violations.checked = []
    subjects = list(_method_instances()) + [("canvas", lambda: scena.canvas)]
    for label, factory in subjects:
        with fresh_world():
            cls = type(factory())
            for attr in sorted(dir(cls)):
                if attr.startswith("_"):
                    continue
                if not callable(inspect.getattr_static(cls, attr, None)):
                    continue
                with quiet():
                    method = getattr(factory(), attr)
                try:
                    params = inspect.signature(method).parameters
                except (TypeError, ValueError):
                    continue
                if "ease" not in params or "time" not in params:
                    continue
                if params["time"].default is params["time"].empty:
                    continue                    # time= is required (tween)
                need = [p for p in params.values() if p.default is p.empty
                        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
                if attr in _POINT_FIRST:
                    args, kwargs = [(1.0, 1.0)], {}
                elif attr in _TIMING_REQUIRED:
                    args, kwargs = list(_TIMING_REQUIRED[attr]), {}
                elif any(p.name not in guesses for p in need):
                    out[f"{label}.{attr}"] = "no argument guess (add one)"
                    continue
                else:
                    args = [guesses[p.name] for p in need if p.kind is not p.KEYWORD_ONLY]
                    kwargs = {p.name: guesses[p.name] for p in need if p.kind is p.KEYWORD_ONLY}
                checked.append(f"{label}.{attr}")
                try:
                    with quiet():
                        getattr(factory(), attr)(*args, **kwargs, ease="in_out")
                except TypeError as e:
                    word = "time=" if attr in _TIMING_REQUIRED else "ease"
                    if word not in str(e):
                        out[f"{label}.{attr}"] = f"TypeError, not about {word}: {str(e)[:60]}"
                    continue
                except Exception as e:  # noqa: BLE001
                    out[f"{label}.{attr}"] = f"{type(e).__name__}: {str(e)[:60]}"
                    continue
                out[f"{label}.{attr}"] = "ease= accepted without time="
    return out


class TestEaseNeedsTime(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_every_timed_verb_refuses_ease_alone(self):
        found = ease_without_time_violations()
        self.assertGreater(len(ease_without_time_violations.checked), 30, "vacuous walk")
        self.assertEqual(found, {})


class TestValueDoors(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter("ignore")

    def test_every_setter_refuses_what_is_not_its_value(self):
        from graphics_known import shrink_only
        shrink_only(self, {**setter_violations(), **verb_point_violations()}, "VALUES")

    def test_every_flag_refuses_a_string(self):
        from graphics_known import shrink_only
        shrink_only(self, {**ctor_flag_violations(), **method_flag_violations()}, "FLAGS")

    def test_the_walks_are_not_vacuous(self):
        n = sum(1 for name in ("Circle", "Rect", "Sprite") for _ in _setters(getattr(scena, name)))
        self.assertGreater(n, 60, "the setter walk found few setters")

    def test_canary_a_finite_that_lets_nan_through(self):
        from diff_support import assert_catches
        assert_catches(self, "test_value_validation.TestValueDoors.test_every_setter_refuses_what_is_not_its_value",
                       [("scena.validate", "finite", lambda value, what: value)],
                       "a finite() that accepts NaN")



class TestLinkPullsKeepTheNumbersRule(unittest.TestCase):
    """GX14 / GX15 (Testing Design): a link pull and a shape's ``vec`` part take
    numbers by the rule ``=`` uses. A pull took ``True`` as 1, leaked
    OverflowError for ``10**400`` (scalars, and points read from cells) and
    named the field "magnitude"; ``rect.vec`` stored ``(0, inf)`` on every path."""

    def test_a_scalar_pull_refuses_a_bool_and_a_huge_int_by_name(self):
        st = scena.State(name="gx14")
        for bad, err in ((True, TypeError), (10 ** 400, ValueError), (float("nan"), ValueError)):
            r = scena.Rect(center=(0, 0), width=10, height=5)
            st.w = 4.0
            r["width"] @= lambda: st.w
            st.w = bad
            with self.assertRaises(err) as ctx:
                r.width
            self.assertTrue(_author_error(ctx.exception), repr(ctx.exception))
            self.assertIn("width", str(ctx.exception))
            st.w = 6.0                      # a good value: it follows again
            self.assertEqual(float(r.width), 6.0)
            st.w = bad
            r["width"].unlink()             # removing a link whose source is bad keeps the last good value
            self.assertEqual(float(r.width), 6.0)
            remove(r)

    def test_a_point_pull_from_cells_refuses_a_bool_and_a_huge_int(self):
        st = scena.State(name="gx14p")
        for bad in (True, 10 ** 400):
            c = scena.Circle(center=(0, 0), radius=3)
            st.x, st.y = 1.0, 2.0
            c["center"] @= lambda: (st.x, st.y)
            st.x = bad
            with self.assertRaises((TypeError, ValueError)) as ctx:
                c.center.x
            self.assertTrue(_author_error(ctx.exception), repr(ctx.exception))
            remove(c)

    def test_a_cell_holding_true_takes_a_number(self):
        st = scena.State(name="flag")
        st.v = True
        st.v = 1.0
        self.assertIs(type(st.v), float)
        st.v = True
        self.assertIs(type(st.v), bool)

    def test_a_shapes_vec_part_takes_two_finite_numbers_on_every_path(self):
        st = scena.State(name="gx15")
        for bad in ((0, float("inf")), (10 ** 400, 0)):
            for path in ("=", "<<", "link"):
                r = scena.Rect(p1=(0, 0), vec=(10, 4))
                with self.assertRaises(ValueError, msg=f"{bad} {path}") as ctx:
                    if path == "=":
                        r.vec = bad
                    elif path == "<<":
                        r.vec << bad
                    else:
                        st.p = bad
                        r["vec"] @= lambda: st.p
                        r.vec.x
                self.assertTrue(_author_error(ctx.exception), repr(ctx.exception))
                remove(r)
        free = scena.Vec2(0, 0)
        free << (float("inf"), 0)               # a free Vec2 is a value: it may hold inf
        self.assertEqual(free.x, float("inf"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
