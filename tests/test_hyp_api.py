"""Property-based tests for the author API (Hypothesis).

Generalizes the hand-picked probes in ``test_api_robustness.py``: instead of
five bad values per knob, Hypothesis searches the whole input space an author
can type, and shrinks any failure to the smallest call that shows it.

Contracts under test (Scena Design — Numbers and signs; API Robustness plan):

* **Author errors only.** Any call with any junk argument either succeeds or
  raises ``TypeError`` / ``ValueError`` (or the named reactive errors) with a
  Scena message — never a Python builtin message from inside the engine.
* **Failed calls do not half-apply.** A rejected write or verb leaves the
  object as it was; a rejected constructor leaves nothing in the registry.
* **Numbers rule.** Magnitudes: negative → ``ValueError``; NaN / inf →
  ``ValueError``; not a number (incl. ``bool``) → ``TypeError``; any finite
  non-negative round-trips. Signed values: any finite value round-trips.
* **Pose algebra.** ``move_by`` / ``rotate_by`` are exact deltas and undo.
* **Reactive links** (``@=``): every linked value equals its formula after any
  sequence of writes, relinks, unlinks, and rejected cycles.

    python -m unittest tests.test_hyp_api -v
    SCENA_HYPOTHESIS_PROFILE=ci python -m unittest tests.test_hyp_api -v
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import (  # noqa: E402
    AUTHOR_ERRORS, GROUP_POOL, WorldTracker, angles, approx_equal, assert_author_error, boot,
    call_as_author, coords, durations, fresh_world, group_names, ink_names, junk,
    new_in_roster, roster_mark,
    key_like_text, magnitudes, negative_numbers, non_finite, not_numbers,
    not_points, points, quiet, registry, small_coords, xy,
)
from hypothesis import assume, example, given, note, strategies as hst
from hypothesis.stateful import (
    Bundle, RuleBasedStateMachine, invariant, precondition, rule,
)

from scena import (
    Box, Circle, Ellipse, Entity, EquilateralTriangle, Line, Point, Polygon, Rect,
    RegularPolygon, Square, Text, after, chance, every, keyp,
)
from scena.state import (
    Attribute, CircularReferenceError, LinkedAttributeError,
)

boot()

# --------------------------------------------------------------------------
# Fixtures: one factory per kind, in the "center model" so size slots are
# Defining (writable), not Derivate.
# --------------------------------------------------------------------------

FACTORIES = {
    "Circle": lambda: Circle(center=(0, 0), radius=5),
    "Rect": lambda: Rect(center=(0, 0), width=10, height=6),
    "Square": lambda: Square(center=(0, 0), length=8),
    "Ellipse": lambda: Ellipse(center=(0, 0), width=10, height=6),
    "RegularPolygon": lambda: RegularPolygon(center=(0, 0), radius=5, n=5),
    "EquilateralTriangle": lambda: EquilateralTriangle(center=(0, 0), side=6),
}

# (kind, slot) pairs whose value is a magnitude and is Defining in the model
# built above.
MAGNITUDE_SLOTS = [
    ("Circle", "radius"),
    ("Circle", "line_width"),
    ("Rect", "width"),
    ("Rect", "height"),
    ("Rect", "line_width"),
    ("Square", "length"),
    ("Ellipse", "width"),
    ("Ellipse", "height"),
    ("RegularPolygon", "radius"),
    ("EquilateralTriangle", "side"),
]

SIGNED_SLOTS = [
    ("Rect", "angle"),
    ("Ellipse", "angle"),
    ("Square", "angle"),
    ("RegularPolygon", "angle"),
    ("Circle", "angle"),
]

POSE_KINDS = sorted(FACTORIES)


def _read(obj, slot):
    v = getattr(obj, slot)
    return float(v)


class TestMagnitudeSlots(unittest.TestCase):
    """Every magnitude slot obeys the Numbers rule, and a rejected write keeps the value."""

    @given(slot=hst.sampled_from(MAGNITUDE_SLOTS), value=magnitudes)
    def test_finite_non_negative_round_trips(self, slot, value):
        kind, name = slot
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            setattr(obj, name, value)
            self.assertEqual(_read(obj, name), value)

    @given(slot=hst.sampled_from(MAGNITUDE_SLOTS),
           value=hst.one_of(negative_numbers, non_finite))
    def test_negative_or_non_finite_is_value_error_and_keeps_value(self, slot, value):
        kind, name = slot
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            before = _read(obj, name)
            with self.assertRaises(ValueError):
                setattr(obj, name, value)
            self.assertEqual(_read(obj, name), before)

    @given(slot=hst.sampled_from(MAGNITUDE_SLOTS), value=not_numbers)
    def test_not_a_number_is_type_error_and_keeps_value(self, slot, value):
        kind, name = slot
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            before = _read(obj, name)
            try:
                setattr(obj, name, value)
            except TypeError as exc:
                assert_author_error(self, exc, call=f"{kind}.{name} = {value!r}")
            else:
                self.fail(f"{kind}.{name} = {value!r} was accepted")
            self.assertEqual(_read(obj, name), before)


class TestSignedSlots(unittest.TestCase):
    @given(slot=hst.sampled_from(SIGNED_SLOTS), value=angles)
    def test_any_finite_angle_round_trips(self, slot, value):
        kind, name = slot
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            setattr(obj, name, value)
            self.assertTrue(approx_equal(_read(obj, name), value),
                            f"{kind}.{name}: wrote {value}, read {_read(obj, name)}")

    @given(slot=hst.sampled_from(SIGNED_SLOTS), value=hst.one_of(not_numbers, non_finite))
    def test_bad_angle_is_author_error_and_keeps_value(self, slot, value):
        kind, name = slot
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            before = _read(obj, name)
            ok, _ = call_as_author(self, setattr, obj, name, value,
                                   call=f"{kind}.{name} = {value!r}")
            self.assertFalse(ok, f"{kind}.{name} = {value!r} was accepted")
            self.assertEqual(_read(obj, name), before)


class TestPoseAlgebra(unittest.TestCase):
    """``move_by`` / ``move_to`` / ``rotate_by`` are exact and invertible."""

    @given(kind=hst.sampled_from(POSE_KINDS), start=points,
           dx=small_coords, dy=small_coords)
    def test_move_by_is_a_delta_and_undoes(self, kind, start, dx, dy):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.move_to(*start)
            x0, y0 = xy(obj.center)
            obj.move_by(dx, dy)
            x1, y1 = xy(obj.center)
            self.assertTrue(approx_equal(x1, x0 + dx) and approx_equal(y1, y0 + dy),
                            f"move_by({dx}, {dy}) from {(x0, y0)} landed at {(x1, y1)}")
            obj.move_by(-dx, -dy)
            x2, y2 = xy(obj.center)
            self.assertTrue(approx_equal(x2, x0) and approx_equal(y2, y0))

    @given(kind=hst.sampled_from(POSE_KINDS), target=points)
    def test_move_to_lands_on_target(self, kind, target):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.move_to(*target)
            x, y = xy(obj.center)
            self.assertTrue(approx_equal(x, target[0]) and approx_equal(y, target[1]))

    @given(kind=hst.sampled_from(POSE_KINDS), a=angles, b=angles)
    def test_rotate_by_composes_and_undoes(self, kind, a, b):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            r0 = float(obj.angle)
            obj.rotate_by(a)
            obj.rotate_by(b)
            self.assertTrue(approx_equal(float(obj.angle), r0 + a + b, abs_tol=1e-6))
            obj.rotate_by(-a - b)
            self.assertTrue(approx_equal(float(obj.angle), r0, abs_tol=1e-6))

    @given(kind=hst.sampled_from(POSE_KINDS), a=angles)
    def test_rotate_to_sets_rotation(self, kind, a):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.rotate_to(a)
            self.assertTrue(approx_equal(float(obj.angle), a))


# Every kind with its own ``rotate_by`` (Line, Point, Polygon and Box do not
# share the Shape pose path), read at the vertex level.
ROTATION_FACTORIES = {
    **FACTORIES,
    "Line": lambda: Line(p1=(-6, -2), p2=(9, 4)),
    "Polygon": lambda: Polygon(points=[(0, 0), (12, 3), (4, 9), (-3, 5)]),
    "Point": lambda: Point(3, -2),
    "Box": lambda start=(0, 0): Box(center=start, width=10, height=6),
}
ROTATION_KINDS = sorted(ROTATION_FACTORIES)
pivots = hst.one_of(hst.none(), hst.tuples(small_coords, small_coords))


def _vertices(obj):
    """World points that pin the pose: corners / points / ends, then center."""
    if isinstance(obj, Box):
        pts = [obj.top_left, obj.top_right, obj.bottom_left, obj.bottom_right]
    elif isinstance(obj, Line):
        pts = [obj.p1, obj.p2]
    elif hasattr(obj, "corners"):
        pts = list(obj.corners)
    elif hasattr(obj, "points"):
        pts = list(obj.points)
    else:
        pts = []
    return [xy(p) for p in pts] + [xy(obj.center)]


def _heading(obj):
    """Unit vector of the rotation: makes a full turn visible on a Circle."""
    r = math.radians(float(obj.angle if isinstance(obj, Box) else obj.angle))
    return math.cos(r), math.sin(r)


def _turned(p, pivot, deg):
    a = math.radians(deg)
    dx, dy = p[0] - pivot[0], p[1] - pivot[1]
    return (pivot[0] + dx * math.cos(a) - dy * math.sin(a),
            pivot[1] + dx * math.sin(a) + dy * math.cos(a))


def _placed(w, kind, start, r0):
    if kind == "Box":           # a measure, not an actor: no move_to, nothing to track
        obj = ROTATION_FACTORIES[kind](start)
    else:
        obj = w.track(ROTATION_FACTORIES[kind]())
        obj.move_to(*start)
    obj.rotate_to(r0)
    return obj


class TestRotationGeometry(unittest.TestCase):
    """``rotate_by`` moves the geometry, not only the ``angle`` number.

    ``angle`` accumulates (a full turn reads ``+360``), so identity and
    undo are checked on the world vertices and the heading.
    """

    def assert_same_points(self, got, want, what):
        self.assertEqual(len(got), len(want))
        for g, e in zip(got, want):
            self.assertTrue(approx_equal(g[0], e[0], abs_tol=1e-6)
                            and approx_equal(g[1], e[1], abs_tol=1e-6),
                            f"{what}: {got} != {want}")

    def _rotate(self, obj, deg, pivot):
        if pivot is None:
            obj.rotate_by(deg)
        else:
            obj.rotate_by(deg, about=pivot)

    @given(kind=hst.sampled_from(ROTATION_KINDS), start=hst.tuples(small_coords, small_coords),
           r0=angles, a=angles, pivot=pivots)
    # Point about itself kept its heading (Testing Design, bug G1).
    @example(kind="Point", start=(0.0, 0.0), r0=0.0, a=1.0, pivot=None)
    def test_rotate_by_turns_every_vertex_about_the_pivot(self, kind, start, r0, a, pivot):
        with fresh_world() as w:
            obj = _placed(w, kind, start, r0)
            before, heading = _vertices(obj), _heading(obj)
            p = pivot if pivot is not None else xy(obj.center)
            self._rotate(obj, a, pivot)
            self.assert_same_points(_vertices(obj), [_turned(v, p, a) for v in before],
                                    f"{kind}.rotate_by({a}, about={pivot})")
            self.assert_same_points([_heading(obj)], [_turned(heading, (0.0, 0.0), a)],
                                    f"{kind} heading")

    @given(kind=hst.sampled_from(ROTATION_KINDS), start=hst.tuples(small_coords, small_coords),
           r0=angles, a=angles, b=angles, pivot=pivots)
    def test_rotate_by_about_composes_and_undoes(self, kind, start, r0, a, b, pivot):
        with fresh_world() as w:
            obj = _placed(w, kind, start, r0)
            before, heading = _vertices(obj), _heading(obj)
            p = pivot if pivot is not None else xy(obj.center)
            self._rotate(obj, a, p)
            self._rotate(obj, b, p)
            self._rotate(obj, -(a + b), p)
            self.assert_same_points(_vertices(obj), before, f"{kind} after +{a} +{b} -{a + b}")
            self.assert_same_points([_heading(obj)], [heading], f"{kind} heading")

    @given(kind=hst.sampled_from(ROTATION_KINDS), start=hst.tuples(small_coords, small_coords),
           r0=angles, turns=hst.sampled_from([-3, -2, -1, 1, 2, 3]),
           quarters=hst.booleans(), pivot=pivots)
    def test_full_turns_leave_the_geometry(self, kind, start, r0, turns, quarters, pivot):
        with fresh_world() as w:
            obj = _placed(w, kind, start, r0)
            before, heading = _vertices(obj), _heading(obj)
            r_before = float(obj.angle if kind == "Box" else obj.angle)
            p = pivot if pivot is not None else xy(obj.center)
            if quarters:
                for _ in range(4 * abs(turns)):
                    self._rotate(obj, math.copysign(90.0, turns), p)
            else:
                self._rotate(obj, 360.0 * turns, p)
            self.assert_same_points(_vertices(obj), before, f"{kind} after {turns} turn(s)")
            self.assert_same_points([_heading(obj)], [heading], f"{kind} heading")
            r_after = float(obj.angle if kind == "Box" else obj.angle)
            self.assertTrue(approx_equal(r_after, r_before + 360.0 * turns, abs_tol=1e-6),
                            "rotation accumulates: a full turn reads +360, not 0")


class TestRotationGeometryCanaries(unittest.TestCase):
    """The vertex oracle catches a pivot slip on one kind (SCENA_CANARIES)."""

    def test_line_turning_about_p1_is_caught(self):
        from diff_support import assert_catches
        original = Line.rotate_by

        def about_p1(self, angle, *, about=None, force=False):
            return original(self, angle, about=about if about is not None else self.p1,
                            force=force)

        assert_catches(self, "test_hyp_api.TestRotationGeometry.test_rotate_by_turns_every_vertex_about_the_pivot",
                       [(Line, "rotate_by", about_p1)], "Line.rotate_by about p1")

# Verb call shapes: (label, callable(obj, bad)).
_BAD_VERB_CALLS = [
    ("move_by(bad, 0)", lambda o, v: o.move_by(v, 0)),
    ("move_by(0, bad)", lambda o, v: o.move_by(0, v)),
    ("move_to(bad)", lambda o, v: o.move_to(v)),
    ("move_to(bad, 0)", lambda o, v: o.move_to(v, 0)),
    ("rotate_by(bad)", lambda o, v: o.rotate_by(v)),
    ("rotate_to(bad)", lambda o, v: o.rotate_to(v)),
    ("scale_to(bad)", lambda o, v: o.scale_to(v)),
    ("scale_by(bad)", lambda o, v: o.scale_by(v)),
    ("move_to((1,1), time=bad)", lambda o, v: o.move_to((1, 1), time=v)),
    ("rotate_by(10, time=bad)", lambda o, v: o.rotate_by(10, time=v)),
    ("flash(duration=bad)", lambda o, v: o.flash(duration=v)),
]


def _verb_junk_test(label, call):
    """One test per verb: Hypothesis reports one failure per raise site, so a
    shared test would let the first broken verb hide the others."""

    @given(kind=hst.sampled_from(POSE_KINDS), value=hst.one_of(not_numbers, non_finite))
    def test(self, kind, value):
        # None is legal where it means "omitted": time=None (instant) and one
        # axis of move_by / move_to (per-axis move). As the whole target of
        # move_to(bad) it must raise (see TestNoTarget).
        assume(not (value is None and label != "move_to(bad)"))
        # A 2-tuple or 2-list of numbers is a valid point for move_to(bad)
        # (a list reads like the tuple: test_pair_reading).
        assume(not (label == "move_to(bad)" and isinstance(value, (tuple, list))))
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.move_to(3, 4)
            before = (xy(obj.center), float(obj.angle), float(obj.scale))
            ok, result = call_as_author(self, call, obj, value, call=f"{kind}.{label} bad={value!r}")
            note(f"ok={ok} result={result!r}")
            self.assertFalse(ok, f"{kind}.{label} accepted {value!r}")
            after_ = (xy(obj.center), float(obj.angle), float(obj.scale))
            self.assertEqual(before, after_, f"{kind}.{label} half-applied {value!r}")

    test.__doc__ = f"{label}: junk is an author error and the pose is untouched."
    return test


class TestVerbsRejectJunk(unittest.TestCase):
    """Any junk into a pose verb: an author error, and the pose is untouched."""

    for _label, _call in _BAD_VERB_CALLS:
        _name = "test_" + "".join(ch if ch.isalnum() else "_" for ch in _label).strip("_")
        locals()[_name] = _verb_junk_test(_label, _call)
    del _label, _call, _name

    @given(kind=hst.sampled_from(POSE_KINDS),
           call=hst.sampled_from([
               ("move_to()", lambda o: o.move_to()),
               ("move_to(None)", lambda o: o.move_to(None)),
               ("move_to(None, None)", lambda o: o.move_to(None, None)),
               ("move_by()", lambda o: o.move_by()),
               ("move_by(None)", lambda o: o.move_by(None)),
               ("move_by(None, None)", lambda o: o.move_by(None, None)),
           ]))
    def test_no_target_is_type_error_not_a_silent_no_op(self, kind, call):
        label, fn = call
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.move_to(3, 4)
            with self.assertRaises(TypeError, msg=label):
                fn(obj)
            self.assertEqual(xy(obj.center), (3.0, 4.0))

    @given(kind=hst.sampled_from(POSE_KINDS), x=small_coords, y=small_coords)
    def test_one_none_axis_keeps_that_axis(self, kind, x, y):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            obj.move_to(3, 4)
            obj.move_to(None, y)
            self.assertEqual(xy(obj.center), (3.0, y))
            obj.move_to(x, None)
            self.assertEqual(xy(obj.center), (x, y))
            obj.move_by(None, 1.0)
            self.assertTrue(approx_equal(xy(obj.center)[1], y + 1.0))

    @given(kind=hst.sampled_from(POSE_KINDS), value=negative_numbers)
    def test_negative_scale_is_value_error(self, kind, value):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            with self.assertRaises(ValueError):
                obj.scale_to(value)
            with self.assertRaises(ValueError):
                obj.scale = value


# --------------------------------------------------------------------------
# Constructor fuzz
# --------------------------------------------------------------------------

_POINT_PARAMS = {"center", "p1", "p2", "top_left", "fp1", "fp2",
                 "perimeter_point", "vertex", "from_point"}
_MAGNITUDE_PARAMS = {"radius", "width", "height", "length", "side", "major_axis",
                     "corner_radius", "padding", "line_width", "dist"}
_SIGNED_PARAMS = {"angle", "angle", "dx", "dy", "x1", "y1", "x2", "y2"}
_SPREAD_PARAMS = {"spread"}


def _valid_value(param):
    if param in _POINT_PARAMS:
        return points
    if param in _MAGNITUDE_PARAMS:
        return hst.floats(min_value=0.5, max_value=500, allow_nan=False)
    if param in _SIGNED_PARAMS:
        return angles
    if param in _SPREAD_PARAMS:
        return hst.floats(min_value=0.0, max_value=360.0, allow_nan=False, allow_infinity=False)
    if param == "n":
        return hst.integers(min_value=3, max_value=12)
    if param == "color":
        return hst.sampled_from(["red", "blue", "#00ff00", (1.0, 0.5, 0.0)])
    if param == "layer":
        return hst.sampled_from(["default", "top", 3])
    if param == "group":
        return hst.one_of(group_names, hst.lists(group_names, max_size=2, unique=True))
    if param == "use_center":
        return hst.booleans()
    return None


CONSTRUCTORS = [Circle, Rect, Square, Ellipse, Line, RegularPolygon, EquilateralTriangle]


def _fuzzable_params(cls):
    return [p for p in inspect.signature(cls).parameters
            if _valid_value(p) is not None]


@hst.composite
def constructor_calls(draw):
    cls = draw(hst.sampled_from(CONSTRUCTORS))
    params = _fuzzable_params(cls)
    chosen = draw(hst.lists(hst.sampled_from(params), max_size=4, unique=True))
    corrupt = draw(hst.booleans())
    kwargs = {}
    for p in chosen:
        if corrupt and draw(hst.booleans()):
            kwargs[p] = draw(junk)
        else:
            kwargs[p] = draw(_valid_value(p))
    return cls, kwargs


def _registry_census():
    """Draw-list sizes and group sizes — what a failed constructor must not change.

    Roster entries are checked separately (``new_in_roster``)."""
    sc = registry()
    layers = {}
    for name in list(sc.layers):
        layer = sc.layers.get(name)
        layer._compact()
        if isinstance(name, int) and not layer._objects:
            continue  # numeric layers auto-create on first use; empty ones draw nothing
        layers[name] = len(layer._objects)
    groups = {g: sc.group_live_count(g) for g in GROUP_POOL}
    return layers, groups


class TestConstructorFuzz(unittest.TestCase):
    """Any keyword mix: a placed, readable shape, or an author error that leaves no trace."""

    @given(call=constructor_calls())
    def test_constructor_contract(self, call):
        cls, kwargs = call
        label = f"{cls.__name__}(**{kwargs!r})"
        with fresh_world() as w:
            before = _registry_census()
            mark = roster_mark()
            ok, result = call_as_author(self, cls, call=label, **kwargs)
            if not ok:
                self.assertEqual(_registry_census(), before,
                                 f"{label} raised {result!r} but left a trace in the registry")
                self.assertEqual(new_in_roster(mark), [],
                                 f"{label} raised {result!r} but left a roster entry")
                return
            obj = w.track(result)
            self.assertTrue(obj.is_alive)
            x, y = xy(obj.center)
            self.assertTrue(math.isfinite(x) and math.isfinite(y), f"{label}: center {x, y}")
            self.assertTrue(registry().is_live(obj))
            if obj.layer is not None:
                self.assertIn(obj, registry().objects_on_layer(obj.layer))
            if "center" in kwargs:
                cx, cy = kwargs["center"]
                self.assertTrue(approx_equal(x, cx) and approx_equal(y, cy),
                                f"{label}: center landed at {(x, y)}")
            for name in ("radius", "width", "height", "length", "side"):
                if name in kwargs and hasattr(type(obj), name):
                    got = float(getattr(obj, name))
                    self.assertTrue(approx_equal(got, float(kwargs[name]), rel=1e-6),
                                    f"{label}: {name} read back {got}")

    @given(cls=hst.sampled_from(CONSTRUCTORS), value=junk)
    def test_positional_argument_is_type_error(self, cls, value):
        with fresh_world():
            before = _registry_census()
            mark = roster_mark()
            with self.assertRaises(TypeError):
                with quiet():
                    cls(value)
            self.assertEqual(_registry_census(), before)
            self.assertEqual(new_in_roster(mark), [])

    @given(cls=hst.sampled_from(CONSTRUCTORS), name=ink_names, value=hst.integers())
    def test_unknown_keyword_is_type_error_naming_it(self, cls, name, value):
        assume(name not in inspect.signature(cls).parameters)
        with fresh_world():
            before = _registry_census()
            mark = roster_mark()
            with self.assertRaises(TypeError) as ctx:
                with quiet():
                    cls(**{name: value})
            self.assertIn(name, str(ctx.exception))
            self.assertEqual(_registry_census(), before)
            self.assertEqual(new_in_roster(mark), [])

    @given(color=hst.text(max_size=12))
    def test_any_colour_string_never_crashes(self, color):
        # Unknown colour policy: warn + magenta, never raise.
        with fresh_world() as w:
            with quiet():
                w.track(Circle(center=(0, 0), radius=5, color=color))


# --------------------------------------------------------------------------
# Flags, ink, keys, durations, chance
# --------------------------------------------------------------------------

_FLAGS = ("visible", "flip_x", "flip_y")


def _is_flag(value) -> bool:
    return isinstance(value, bool) or (type(value) is int and value in (0, 1))


class TestFlags(unittest.TestCase):
    @given(kind=hst.sampled_from(POSE_KINDS), flag=hst.sampled_from(_FLAGS),
           value=hst.one_of(junk, hst.sampled_from([0, 1, True, False])))
    def test_flags_take_bools_or_0_1_only(self, kind, flag, value):
        with fresh_world() as w:
            obj = w.track(FACTORIES[kind]())
            before = getattr(obj, flag)
            ok, _ = call_as_author(self, setattr, obj, flag, value,
                                   call=f"{kind}.{flag} = {value!r}")
            if _is_flag(value):
                self.assertTrue(ok, f"{kind}.{flag} = {value!r} rejected")
                self.assertIs(getattr(obj, flag), bool(value))
            else:
                self.assertFalse(ok, f"{kind}.{flag} = {value!r} accepted")
                self.assertIs(getattr(obj, flag), before)


class TestInk(unittest.TestCase):
    """New names become ink or raise a typo/look error; real properties are never clobbered."""

    @given(kind=hst.sampled_from(["Circle", "Rect", "Entity"]), name=ink_names,
           value=hst.one_of(hst.integers(), hst.text(max_size=5), hst.none()))
    def test_ink_round_trips_or_raises_typo_error(self, kind, name, value):
        with fresh_world() as w:
            obj = w.track(Entity() if kind == "Entity" else FACTORIES[kind]())
            real = hasattr(type(obj), name)
            assume(not real)  # real properties have their own contracts
            before = xy(obj.center) if kind != "Entity" else None
            try:
                with quiet():
                    setattr(obj, name, value)
            except (AttributeError, TypeError) as exc:
                # near-miss / look family / reserved names: must say what to do
                self.assertIn(name, str(exc))
                self.assertIsNone(leak_free_msg(exc), str(exc))
                return
            self.assertEqual(getattr(obj, name), value)
            if before is not None:
                self.assertEqual(xy(obj.center), before)

    @given(name=ink_names, a=hst.integers(-100, 100), b=hst.integers(-100, 100),
           k=hst.integers(-5, 5))
    def test_bracket_link_on_ink_follows_its_source(self, name, a, b, k):
        with fresh_world() as w:
            src = w.track(Entity())
            dst = w.track(Entity())
            try:
                with quiet():
                    src.v = a
                    dst[name] @= (lambda s=src, k=k: s.v * k)
            except (AttributeError, TypeError):
                return  # name is a near-miss / reserved: covered above
            self.assertEqual(getattr(dst, name), a * k)
            src.v = b
            self.assertEqual(getattr(dst, name), b * k)
            with self.assertRaises(LinkedAttributeError):
                setattr(dst, name, 0)


def leak_free_msg(exc):
    from hypothesis_support import leak_message
    return leak_message(exc)


class TestKeyNames(unittest.TestCase):
    @given(spec=key_like_text)
    def test_keyp_returns_bool_or_names_the_fix(self, spec):
        ok, result = call_as_author(self, keyp, spec, call=f"keyp({spec!r})")
        if ok:
            self.assertIsInstance(result, bool)
            self.assertFalse(result)  # nothing is pressed in a headless test
            self.assertIs(keyp(spec), result)  # cached path agrees
        else:
            self.assertIn("keyp(", str(result))

    @given(spec=hst.one_of(not_numbers.filter(lambda v: not isinstance(v, str)),
                           hst.integers()))
    def test_non_string_key_is_type_error(self, spec):
        ok, result = call_as_author(self, keyp, spec, call=f"keyp({spec!r})")
        self.assertFalse(ok)
        self.assertIsInstance(result, TypeError)


class TestDurations(unittest.TestCase):
    @given(value=hst.one_of(not_numbers, non_finite, negative_numbers),
           verb=hst.sampled_from(["after", "every"]))
    def test_bad_duration_is_author_error(self, value, verb):
        fn = after if verb == "after" else every
        with fresh_world():
            ok, result = call_as_author(self, fn, value, lambda: None,
                                        call=f"{verb}({value!r}, fn)")
            if ok:
                # Only a zero / negative `every` may be legal (frame hooks); a
                # handle must come back either way.
                result.cancel()
                self.assertIsInstance(value, (int, float))
                self.assertFalse(isinstance(value, bool))

    @given(value=durations, verb=hst.sampled_from(["after", "every"]))
    def test_positive_duration_returns_cancellable_handle(self, value, verb):
        fn = after if verb == "after" else every
        with fresh_world():
            h = fn(value, lambda: None)
            self.assertTrue(math.isclose(h.remaining, value, rel_tol=1e-9, abs_tol=1e-9)
                            or h.remaining <= value)
            h.cancel()


class TestChance(unittest.TestCase):
    @given(p=hst.floats(min_value=0.0, max_value=1.0))
    def test_probability_in_unit_range_is_bool(self, p):
        r = chance(p)
        self.assertIsInstance(r, bool)
        if p == 0.0:
            self.assertFalse(r)
        if p == 1.0:
            self.assertTrue(r)

    @given(p=hst.one_of(
        hst.floats(min_value=1.0, exclude_min=True, allow_nan=False, allow_infinity=False),
        hst.floats(max_value=0.0, exclude_max=True, allow_nan=False, allow_infinity=False),
        non_finite, not_numbers))
    def test_outside_unit_range_is_author_error(self, p):
        ok, _ = call_as_author(self, chance, p, call=f"chance({p!r})")
        self.assertFalse(ok, f"chance({p!r}) accepted")


# --------------------------------------------------------------------------
# Reactive links: a state machine over Attributes and Entity ink
# --------------------------------------------------------------------------


class _Node:
    """One linkable cell: a bare ``Attribute`` or an Entity ink field ``v``."""

    def __init__(self, kind: str, value: int, world):
        self.kind = kind
        if kind == "attr":
            self.obj = Attribute(value)
        else:
            self.obj = world.track(Entity())
            self.obj.v = value

    def get(self):
        return self.obj.value if self.kind == "attr" else self.obj.v

    def set(self, value):
        if self.kind == "attr":
            self.obj.value = value
        else:
            self.obj.v = value

    def ref(self):
        """RHS reference usable inside a formula (read through `.get`)."""
        return self.obj

    def link(self, fn):
        if self.kind == "attr":
            self.obj @= fn
        else:
            self.obj["v"] @= fn

    def unlink(self):
        if self.kind == "attr":
            self.obj.unlink()
        else:
            self.obj["v"].unlink()

    def __repr__(self):
        return f"<{self.kind} {id(self.obj):x}>"


def _reader(node):
    """Formula-side read that names the Container source for dependency detection."""
    if node.kind == "attr":
        return lambda a=node.obj: a.value
    return lambda e=node.obj: e.v


def _make_formula(k, terms):
    """``k + Σ c·src`` with each source a default-arg capture (detectable)."""
    objs = [(c, n.obj, n.kind) for c, n in terms]
    if len(objs) == 1:
        (c0, a, ka), = objs
        if ka == "attr":
            return lambda a=a, c0=c0, k=k: k + c0 * a.value
        return lambda a=a, c0=c0, k=k: k + c0 * a.v
    (c0, a, ka), (c1, b, kb) = objs[:2]
    if ka == "attr" and kb == "attr":
        return lambda a=a, b=b, c0=c0, c1=c1, k=k: k + c0 * a.value + c1 * b.value
    if ka == "attr":
        return lambda a=a, b=b, c0=c0, c1=c1, k=k: k + c0 * a.value + c1 * b.v
    if kb == "attr":
        return lambda a=a, b=b, c0=c0, c1=c1, k=k: k + c0 * a.v + c1 * b.value
    return lambda a=a, b=b, c0=c0, c1=c1, k=k: k + c0 * a.v + c1 * b.v


class ReactiveLinksMachine(RuleBasedStateMachine):
    """Random author code over ``=`` / ``@=`` / ``unlink``; values always match the model."""

    nodes = Bundle("nodes")

    def __init__(self):
        super().__init__()
        from hypothesis_support import WorldTracker
        self.world = WorldTracker()
        self.values = {}     # node -> stored value (unlinked nodes)
        self.formulas = {}   # node -> (k, [(c, src)])
        self.all_nodes = []

    def teardown(self):
        self.world.teardown()

    # --- model -----------------------------------------------------------
    def expected(self, node, _seen=None):
        f = self.formulas.get(node)
        if f is None:
            return self.values[node]
        k, terms = f
        return k + sum(c * self.expected(src) for c, src in terms)

    def reaches(self, start, goal):
        """True if ``start``'s value depends (transitively) on ``goal``."""
        stack, seen = [start], set()
        while stack:
            n = stack.pop()
            if n is goal:
                return True
            if id(n) in seen:
                continue
            seen.add(id(n))
            f = self.formulas.get(n)
            if f:
                stack.extend(src for _, src in f[1])
        return False

    # --- rules -------------------------------------------------------------
    @rule(target=nodes, kind=hst.sampled_from(["attr", "ink"]),
          value=hst.integers(-50, 50))
    def new_node(self, kind, value):
        node = _Node(kind, value, self.world)
        self.values[node] = value
        self.all_nodes.append(node)
        return node

    @rule(node=nodes, value=hst.integers(-50, 50))
    def write(self, node, value):
        if node in self.formulas:
            with self.assertRaisesCtx(LinkedAttributeError):
                node.set(value)
        else:
            node.set(value)
            self.values[node] = value

    @rule(target_node=nodes, srcs=hst.lists(nodes, min_size=1, max_size=2),
          coefs=hst.lists(hst.integers(-3, 3), min_size=2, max_size=2),
          k=hst.integers(-10, 10))
    def link(self, target_node, srcs, coefs, k):
        terms = list(zip(coefs, srcs))
        cyclic = any(src is target_node or self.reaches(src, target_node)
                     for _, src in terms)
        fn = _make_formula(k, terms)
        if cyclic:
            before = {n: n.get() for n in self.all_nodes}
            with quiet():
                with self.assertRaisesCtx(CircularReferenceError):
                    target_node.link(fn)
            # A rejected cycle must leave every value where it was.
            for n in self.all_nodes:
                assert n.get() == before[n], f"rejected cycle changed {n}"
            return
        with quiet():
            target_node.link(fn)
        self.formulas[target_node] = (k, terms)

    @rule(node=nodes)
    def unlink(self, node):
        if node not in self.formulas:
            return
        frozen = self.expected(node)
        node.unlink()
        del self.formulas[node]
        self.values[node] = frozen

    # --- invariants ----------------------------------------------------------
    @invariant()
    def values_match_model(self):
        for n in self.all_nodes:
            got, want = n.get(), self.expected(n)
            assert got == want, f"{n}: read {got!r}, model says {want!r}"

    # unittest-style helper usable inside a state machine
    class _Raises:
        def __init__(self, exc):
            self.exc = exc

        def __enter__(self):
            return self

        def __exit__(self, et, ev, tb):
            if et is None:
                raise AssertionError(f"expected {self.exc.__name__}, nothing raised")
            if not issubclass(et, self.exc):
                return False
            return True

    def assertRaisesCtx(self, exc):
        return self._Raises(exc)


TestReactiveLinks = ReactiveLinksMachine.TestCase


class TestNamedGroupQueryOracle(unittest.TestCase):
    """A named ``query_shape`` matches circle overlap, before and after ``resolve``.

    ``@given`` calls this method once per example and ``setUp`` only once, so
    each example builds and tears down its own world.
    """

    @given(
        rows=hst.lists(
            hst.fixed_dictionaries({
                "x": hst.integers(-30, 30),
                "r": hst.integers(4, 10),
                "tag": hst.sampled_from(GROUP_POOL),
                "opt_out": hst.booleans(),
            }),
            min_size=1,
            max_size=5,
        ),
        asked=hst.lists(
            hst.sampled_from(GROUP_POOL), min_size=0, max_size=3, unique=True,
        ),
    )
    def test_named_query_matches_overlap_before_and_after_resolve(self, rows, asked):
        from scena.collision import collision, reset_collision_system, resolve
        world = WorldTracker()
        reset_collision_system()
        try:
            probe = world.track(Circle(center=(0, 0), radius=18))
            live = []
            for row in rows:
                assume(abs(abs(row["x"]) - (18 + row["r"])) > 1.0)
                obj = world.track(Circle(
                    center=(row["x"], 0), radius=row["r"], group=row["tag"],
                ))
                if row["opt_out"]:
                    obj.collidable = True
                    obj.collidable = False
                live.append((row, obj))

            def oracle():
                want = set()
                for row, obj in live:
                    if row["tag"] not in asked or row["opt_out"]:
                        continue
                    if not obj.is_alive or not obj.active:
                        continue
                    if abs(row["x"]) < 18 + row["r"]:
                        want.add(id(obj))
                return want

            def hits(group):
                return {id(h) for h in collision.query_shape(probe, group=group)}

            want = oracle()
            self.assertEqual(hits(list(asked)), want)
            self.assertEqual(hits(set(asked)), want)
            if asked:
                resolve(probe, asked[0])
                self.assertEqual(hits(list(asked)), want)
                self.assertEqual(hits(set(asked)), want)
        finally:
            reset_collision_system()
            world.teardown()


if __name__ == "__main__":
    unittest.main()
