"""Guard: a cell counts as its number in every exported function (the Numbers rule).

Class guard for PM12 (``deadzone(size=st.x)`` refused a cell, when ``st.x``
was the cell). Since 0.8.0 ``st.x`` is the number; the cells an author still
holds are ``Attribute`` objects (``slider.data``, ``Attribute(0)``), and they
count as their number. ``test_hyp_surface`` fuzzes slots, verbs and
constructors; this module covers the free functions.

Every exported function is in ``CASES`` (a canonical call) or ``NO_NUMBERS``
(with a reason). For each case, every number argument — and every number inside
a pair — is replaced in turn by a cell holding it; the call must give the same
result (or raise the same error type) as with the plain number.

    python -m unittest tests.test_cells_as_numbers -v
"""
from __future__ import annotations

import inspect
import itertools
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import system_world  # noqa: E402

import scena  # noqa: E402
from scena import st  # noqa: E402

_N = itertools.count()


def _shapes():
    from scena import Circle, Rect
    a = Circle(center=(0, 0), radius=10)
    b = Rect(center=(12, 0), width=10, height=10)
    return a, b


# name -> fn(world) -> (args, kwargs, cleanup or None). Numbers in args / kwargs
# (or inside a 2-tuple) are the ones the guard swaps for cells.
CASES = {
    "AuroraFill": lambda w: ((), {"amount": 0.7, "speed": 0.5}),
    "FlameFill": lambda w: ((), {"amount": 0.7, "speed": 0.5}),
    "SwellFill": lambda w: ((), {"amount": 0.7, "speed": 0.5}),
    "WaterFill": lambda w: ((), {"amount": 0.7, "speed": 0.5}),
    "WaveFill": lambda w: ((), {"amount": 0.7, "speed": 0.5}),
    "after": lambda w: ((0.25, lambda: None), {}),
    "every": lambda w: ((0.25, lambda: None), {}),
    "amp_db": lambda w: ((0.5,), {"floor": -40.0}),
    "chance": lambda w: ((1.0,), {}),
    "chase": lambda w: ((2.0, 10.0), {"rate": 8.0, "dt": 0.1}),
    "approach": lambda w: ((2.0, 10.0), {"speed": 8.0, "dt": 0.1}),
    "deadzone": lambda w: (((0.0, 0.0), (300.0, 90.0), (40.0, 120.0)), {}),
    "distance": lambda w: (((0.0, 0.0), (3.0, 4.0)), {}),
    "heading": lambda w: (((0.0, 0.0), (3.0, 4.0)), {}),
    "lerp": lambda w: ((2.0, 10.0, 0.25), {}),
    "middle_point": lambda w: (((0.0, 0.0), (4.0, 2.0)), {"weight": 0.25}),
    "remap": lambda w: ((0.5, 0.0, 1.0, 10.0, 20.0), {}),
    "vec_from_angle": lambda w: ((30.0,), {"length": 2.0}),
    "intersection": lambda w: (_shapes(), {"i": 0}),
    "closest_point": lambda w: ((_shapes()[0], (30.0, 4.0)), {}),
    "nearest": lambda w: (((0.0, 0.0), [(5.0, 0.0), (1.0, 1.0)]), {"within": 20.0}),
}

NO_NUMBERS = {
    # decorators / registrations taking actors, groups or functions
    **{n: "takes targets, not numbers" for n in (
        "click", "hover", "hover_exit", "drag_over", "drag_to", "drop_by",
        "collide", "collide_exit", "collide_stay", "collide_with",
        "collide_with_exit", "collide_with_stay", "leave_playfield",
        "unresolve", "test_collision", "intersections")},
    **{n: "takes functions or handles" for n in (
        "on_change", "on_mode", "exit_mode", "when", "until", "until_empty",
        "parallel", "race", "unregister_event", "run_task")},
    "above": "takes a layer name or number (a layer key, not a quantity)",
    "below": "takes a layer name or number (a layer key, not a quantity)",
    "change_act": "takes an Act class",
    "wait": "only inside an async mode (an await): test_process",
    "flush": "takes nothing",
    "run": "starts the program (harness)",
    "init": "configures the window once (design size): test_canvas",
    "resolve": "bounce= is a cell-aware number via _validate_bounce: test_collision",
    "play_sound": "volume / pan / pitch: test_audio (mixer)",
    "tween": "time= and the destination: test_process (tween suite)",
    "set_defaults": "style values (line_width is a slot): test_set_defaults",
    "set_extrude_focus": "a look knob (process-wide): test_visuals",
    "set_fx_auto": "a bench knob: test_fx_auto",
    "set_watchdog": "takes a flag",
    "show_tracks": "takes a flag",
}


def _plain(v):
    """Comparable form of a result (points / vectors to tuples, cells to values)."""
    from scena.state import Attribute
    if isinstance(v, Attribute):
        v = v.value
    if isinstance(v, (list, tuple)):
        return tuple(_plain(x) for x in v)
    x, y = getattr(v, "x", None), getattr(v, "y", None)
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return (round(float(x), 9), round(float(y), 9))
    if isinstance(v, float):
        return round(v, 9)
    if type(v).__name__ in ("Handle", "ProceduralFill") or callable(v):
        return type(v).__name__
    return v


def _cell(value):
    """The ``Attribute`` an ``st`` cell holds. Since 0.8.0 ``st.name`` is the
    number and ``st["name"]`` a FieldRef (a handle that binds, not a number);
    the cell an author can still hold is an ``Attribute`` (``slider.data``,
    ``Attribute(0)``). Through the dot read this test compared a number with
    itself and its canary stopped catching (SV5)."""
    from scena.state import bound_cell
    name = f"pm12_cell_{next(_N)}"
    setattr(st, name, value)
    return bound_cell(st[name]), name


def _swaps(args, kwargs):
    """Yield (label, args, kwargs, cell names) with one number turned into a cell."""
    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    for i, a in enumerate(args):
        if num(a):
            c, n = _cell(a)
            yield f"arg {i}", args[:i] + (c,) + args[i + 1:], kwargs, [n]
        elif isinstance(a, tuple) and len(a) == 2 and all(num(x) for x in a):
            for j in range(2):
                c, n = _cell(a[j])
                pair = (c, a[1]) if j == 0 else (a[0], c)
                yield f"arg {i}[{j}]", args[:i] + (pair,) + args[i + 1:], kwargs, [n]
    for k, v in kwargs.items():
        if num(v):
            c, n = _cell(v)
            yield f"{k}=", args, {**kwargs, k: c}, [n]
        elif isinstance(v, tuple) and len(v) == 2 and all(num(x) for x in v):
            for j in range(2):
                c, n = _cell(v[j])
                pair = (c, v[1]) if j == 0 else (v[0], c)
                yield f"{k}=[{j}]", args, {**kwargs, k: pair}, [n]


def _call(fn, args, kwargs):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = fn(*args, **kwargs)
        if hasattr(r, "cancel"):
            r.cancel()
        return ("ok", _plain(r))
    except Exception as e:  # noqa: BLE001 — compared, not hidden
        return ("raise", type(e).__name__)


class TestEveryFunctionIsListed(unittest.TestCase):
    def test_coverage(self):
        funcs = {n for n in scena.__all__ if inspect.isfunction(getattr(scena, n))}
        missing = sorted(funcs - set(CASES) - set(NO_NUMBERS))
        self.assertFalse(missing, f"exported functions in neither CASES nor NO_NUMBERS: {missing}")
        stale = sorted((set(CASES) | set(NO_NUMBERS)) - funcs)
        self.assertFalse(stale, f"listed but not exported functions: {stale}")


class TestCellsCountAsNumbers(unittest.TestCase):
    def test_every_number_argument(self):
        for name in sorted(CASES):
            fn = getattr(scena, name)
            with system_world(draw=False) as w:
                made = []
                try:
                    args, kwargs = CASES[name](w)
                    for a in args:
                        if hasattr(a, "is_alive"):
                            made.append(w.track(a))
                    want = _call(fn, args, kwargs)
                    self.assertEqual(want[0], "ok", f"{name}: the canonical call fails: {want}")
                    for label, a2, k2, cells in _swaps(args, kwargs):
                        with self.subTest(function=name, argument=label):
                            got = _call(fn, a2, k2)
                            self.assertEqual(got, want, f"{name}({label} as a cell)")
                        for n in cells:
                            st.remove(n)
                finally:
                    made.clear()


class TestCellsCanary(unittest.TestCase):
    def test_a_helper_that_refuses_cells_is_caught(self):
        from diff_support import assert_catches
        from scena.state import Attribute
        real = scena.amp_db

        def strict(x, floor=-60.0):
            if isinstance(x, Attribute):
                raise TypeError("expected a number")
            return real(x, floor)
        assert_catches(self, "test_cells_as_numbers.TestCellsCountAsNumbers.test_every_number_argument",
                       [("scena", "amp_db", strict)], "a helper refusing a cell")


if __name__ == "__main__":
    unittest.main()
