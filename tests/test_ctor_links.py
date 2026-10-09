"""A constructor validates concrete values and never rewrites a stored input.

A value copies. A lambda links. Every Defining geometry key of every
constructor signature does one or the other — a raw ``float()`` / ``get_xy``
on the author's argument is the bug this file guards (Testing Design:
"a constructor touches a raw input before linking it").

    python -m unittest tests.test_ctor_links -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scena import (
    init, Circle, Rect, Square, Ellipse, Line, Polygon, RegularPolygon,
    EquilateralTriangle, Point, Sprite, Text,
)
from scena.box import Box, _CONSTRUCTOR_SIGNATURES as BOX_SIGNATURES
from scena.state import CallableAssignError
from scena.track import Track

# Keys that name a foreign shape, a count, or a paint/layout flag.
# ``side`` is skipped only when it is the tangent discriminator ('left' /
# 'right'); RegularPolygon.side is a length and must link.
_FIXED = frozenset({
    "padding", "n", "anchor", "use_center", "corner_radius",
    "parallel_to", "perpendicular_to", "circle", "from_rect",
})
_POINT_KEYS = frozenset({
    "center", "p1", "p2", "top_left", "vertex", "fp1", "fp2",
    "perimeter_point", "from_point",
})
_VEC_KEYS = frozenset({"vec"})
_XY_LEAF = {
    "x1": ("p1", "x"), "y1": ("p1", "y"),
    "x2": ("p2", "x"), "y2": ("p2", "y"),
}

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _signatures(cls):
    if cls is Box:
        return BOX_SIGNATURES
    return cls._CONSTRUCTOR_SIGNATURES


def _signature_keys(cls):
    keys = set()
    for _, required in _signatures(cls):
        keys |= required
    return keys


def _matched_signature(cls, kwargs):
    present = set(kwargs) & _signature_keys(cls)
    matched = [name for name, required in _signatures(cls) if required == present]
    if len(matched) != 1:
        raise AssertionError(
            f"{cls.__name__}{sorted(kwargs)} matched {matched}, expected one signature"
        )
    return matched[0]


def _is_fixed(key, value):
    if key in _FIXED:
        return True
    # Tangent discriminator. A numeric ``side`` (RegularPolygon) links.
    return key == "side" and isinstance(value, str)


def _near(a, b, tol=1e-4):
    if isinstance(a, tuple):
        return len(a) == len(b) and all(_near(x, y, tol) for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= tol


def _read(obj, key):
    if key == "from_point":
        # Stored as Defining p1; the keyword is not an attribute.
        return (float(obj.p1.x), float(obj.p1.y))
    if key in _XY_LEAF:
        part, leaf = _XY_LEAF[key]
        return float(getattr(getattr(obj, part), leaf))
    part = getattr(obj, key)
    if hasattr(part, "x") and hasattr(part, "y"):
        return (float(part.x), float(part.y))
    return float(part)


def _snapshot(obj):
    """Defining pose. Same numbers for a plain value and a lambda of that value."""
    frame = getattr(obj, "_oriented_frame", None)
    if frame is not None:
        return tuple(round(float(v), 4) for v in frame())
    bits = []
    for name in ("p1", "p2", "center", "vec", "fp1", "fp2", "vertex", "top_left"):
        part = obj.__dict__.get(name)
        if part is None:
            continue
        try:
            bits.append((name, round(float(part.x), 4), round(float(part.y), 4)))
        except (AttributeError, TypeError, ValueError):
            pass
    for name in (
        "width", "height", "length", "radius", "angle", "angle",
        "side", "major_axis", "dist", "dx", "dy", "spread",
    ):
        if name in obj.__dict__ and not callable(obj.__dict__[name]):
            try:
                bits.append((name, round(float(obj.__dict__[name]), 4)))
            except (TypeError, ValueError):
                pass
    return tuple(bits)


class TestConstructorLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    def setUp(self):
        self.ref_line = Line(p1=(0, 0), p2=(40, 0))
        self.ref_circle = Circle(center=(0, 0), radius=5)
        self.ref_rect = Rect(center=(0, 0), width=80, height=40)

    def _samples(self):
        line = self.ref_line
        circle = self.ref_circle
        rect = self.ref_rect
        return [
            (Line, dict(center=(0, 0), length=30, angle=0)),
            (Line, dict(p1=(0, 0), p2=(40, 0))),
            (Line, dict(p1=(0, 0), vec=(30, 10))),
            (Line, dict(p1=(0, 0), dx=30, dy=10)),
            (Line, dict(p1=(0, 0), angle=0, length=30)),
            (Line, dict(p1=(0, 0), parallel_to=line, length=30)),
            (Line, dict(dist=5, parallel_to=line)),
            (Line, dict(p1=(0, 0), perpendicular_to=line, length=30)),
            (Line, dict(circle=circle, at_angle=0, length=20)),
            (Line, dict(circle=circle, from_point=(30, 0), side="left")),
            (Circle, dict(center=(0, 0), radius=15, angle=0, spread=90)),
            (Circle, dict(center=(0, 0), perimeter_point=(15, 0))),
            (Circle, dict(p1=(-10, 0), p2=(10, 0))),
            (Ellipse, dict(center=(0, 0), width=40, height=20)),
            (Ellipse, dict(center=(0, 0), width=40, height=20, angle=15)),
            (Ellipse, dict(fp1=(0, 0), fp2=(1, 0), major_axis=100)),
            (Ellipse, dict(from_rect=rect)),
            (Ellipse, dict(from_rect=rect, padding=4)),
            (Rect, dict(p1=(0, 0), p2=(80, 40))),
            (Rect, dict(p1=(0, 0), p2=(80, 40), angle=30)),
            (Rect, dict(top_left=(0, 0), width=40, height=20)),
            (Rect, dict(top_left=(0, 0), width=40, height=20, angle=15)),
            (Rect, dict(center=(0, 0), width=40, height=20)),
            (Rect, dict(center=(0, 0), width=40, height=20, angle=15)),
            (Rect, dict(p1=(0, 0), vec=(40, 20))),
            (Rect, dict(p1=(0, 0), vec=(-10, 20), angle=20)),
            (Rect, dict(p1=(0, 0), p2=(50, 0), height=8, anchor="cap")),
            (Square, dict(center=(0, 0), length=20)),
            (Square, dict(center=(0, 0), length=20, angle=15)),
            (Square, dict(top_left=(0, 0), length=20)),
            (Square, dict(top_left=(0, 0), length=20, angle=15)),
            (RegularPolygon, dict(n=5, center=(0, 0), radius=20)),
            (RegularPolygon, dict(n=5, center=(0, 0), radius=20, angle=15)),
            (RegularPolygon, dict(n=5, center=(0, 0), side=12)),
            (RegularPolygon, dict(n=5, center=(0, 0), side=12, angle=15)),
            (RegularPolygon, dict(n=5, vertex=(0, 20), side=12)),
            (RegularPolygon, dict(n=5, vertex=(0, 20), side=12, angle=15)),
            (EquilateralTriangle, dict(center=(0, 0), radius=20)),
            (EquilateralTriangle, dict(center=(0, 0), radius=20, angle=15)),
            (EquilateralTriangle, dict(center=(0, 0), side=12)),
            (EquilateralTriangle, dict(center=(0, 0), side=12, angle=15)),
            (EquilateralTriangle, dict(vertex=(0, 20), side=12)),
            (EquilateralTriangle, dict(vertex=(0, 20), side=12, angle=15)),
            (Box, dict(p1=(0, 0), p2=(80, 40))),
            (Box, dict(p1=(0, 0), p2=(80, 40), angle=30)),
            (Box, dict(top_left=(0, 0), width=40, height=20)),
            (Box, dict(top_left=(0, 0), width=40, height=20, angle=15)),
            (Box, dict(center=(0, 0), width=40, height=20)),
            (Box, dict(center=(0, 0), width=40, height=20, angle=15)),
            (Box, dict(p1=(0, 0), vec=(40, 20))),
            (Box, dict(p1=(0, 0), vec=(-10, 20), angle=20)),
            (Box, dict(p1=(0, 0), p2=(50, 0), height=8, anchor="cap")),
        ]

    def test_every_signature_has_a_sample(self):
        covered = {}
        for cls, kwargs in self._samples():
            covered.setdefault(cls, set()).add(_matched_signature(cls, kwargs))
        classes = (
            Line, Circle, Ellipse, Rect, Square, RegularPolygon,
            EquilateralTriangle, Box,
        )
        for cls in classes:
            missing = {name for name, _ in _signatures(cls)} - covered.get(cls, set())
            self.assertEqual(missing, set(), cls.__name__)

    def test_every_geometry_key_links(self):
        for cls, sample in self._samples():
            sig = _matched_signature(cls, sample)
            for key, value in sample.items():
                if _is_fixed(key, value):
                    continue
                with self.subTest(cls=cls.__name__, sig=sig, key=key):
                    src = Point(10, 20)
                    if key in _POINT_KEYS or key in _VEC_KEYS:
                        concrete = (float(src.x), float(src.y))
                        linked_value = (lambda s=src: (s.x, s.y))
                        after = (13.0, 25.0)
                    else:
                        concrete = float(src.x)
                        linked_value = (lambda s=src: s.x)
                        after = 13.0
                    plain_kw = dict(sample)
                    plain_kw[key] = concrete
                    link_kw = dict(sample)
                    link_kw[key] = linked_value
                    plain = cls(**plain_kw)
                    linked = cls(**link_kw)
                    before = _read(plain, key)
                    self.assertTrue(
                        _near(_read(linked, key), before),
                        f"linked {_read(linked, key)} != plain {before}",
                    )
                    src.x = 13
                    src.y = 25
                    self.assertTrue(
                        _near(_read(linked, key), after),
                        f"did not follow: {_read(linked, key)} != {after}",
                    )
                    self.assertTrue(
                        _near(_read(plain, key), before),
                        "plain value changed when the source moved",
                    )

    def test_plain_and_linked_build_the_same_shape(self):
        """A lambda of the same numbers must not take a different constructor path.

        The rotated-corner rewrite failed this: it moved plain p1/p2 and could
        not move a link, so the two rectangles differed.
        """
        for cls, sample in self._samples():
            sig = _matched_signature(cls, sample)
            link_kw = {}
            any_link = False
            for key, value in sample.items():
                if _is_fixed(key, value):
                    link_kw[key] = value
                    continue
                # Default-arg capture of a Point is a formula source. A bare
                # float default is not — FormulaLink would reject it.
                if key in _POINT_KEYS or key in _VEC_KEYS:
                    if hasattr(value, "x"):
                        x, y = float(value.x), float(value.y)
                    else:
                        x, y = float(value[0]), float(value[1])
                    holder = Point(x, y)
                    link_kw[key] = (lambda h=holder: (h.x, h.y))
                    any_link = True
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    holder = Point(float(value), 0.0)
                    link_kw[key] = (lambda h=holder: h.x)
                    any_link = True
                else:
                    link_kw[key] = value
            if not any_link:
                continue
            with self.subTest(cls=cls.__name__, sig=sig):
                plain = cls(**sample)
                linked = cls(**link_kw)
                self.assertEqual(_snapshot(plain), _snapshot(linked))

    def test_line_home_length_and_angle_link(self):
        src = Point(12, 0)
        by_length = Line(length=lambda: src.x, angle=0)
        by_angle = Line(length=20, angle=lambda: src.x)
        both = Line(center=lambda: src, length=lambda: src.x, angle=0)
        src.x = 18
        src.y = 4
        self.assertAlmostEqual(float(by_length.length), 18.0)
        self.assertAlmostEqual(float(by_angle.angle), 18.0)
        self.assertAlmostEqual(float(both.length), 18.0)
        self.assertAlmostEqual(float(both.center.x), 18.0)
        self.assertAlmostEqual(float(both.center.y), 4.0)

    def test_linked_focal_ellipse_may_collapse(self):
        """A formula skips the major > distance check; a written value still raises."""
        src = Point(10, 0)
        live = Ellipse(fp1=lambda: src, fp2=(0, 0), major_axis=1)
        self.assertTrue(live.is_collapsed)
        src.x = 0.2
        self.assertFalse(live.is_collapsed)
        with self.assertRaises(ValueError) as ctx:
            Ellipse(fp1=(10, 0), fp2=(0, 0), major_axis=1)
        self.assertIn("major_axis", str(ctx.exception))

    def test_fixed_keys_reject_with_scena_message(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from hypothesis_support import assert_author_error

        fn = lambda: 3
        rect = Rect(center=(0, 0), width=40, height=20)

        def set_radius():
            rect.corner_radius = fn

        def link_radius():
            rect["corner_radius"] @= fn

        cases = {
            "Ellipse padding": (
                lambda: Ellipse(from_rect=self.ref_rect, padding=fn), "width",
            ),
            "Polygon points": (
                lambda: Polygon(points=fn), "vertex",
            ),
            "Sprite width": (lambda: Sprite(width=fn), "scale"),
            "Sprite height": (lambda: Sprite(height=fn), "scale"),
            "Sprite size": (lambda: Sprite(size=fn), "scale"),
            "Text width": (lambda: Text("hi", center=(0, 0), width=fn), "center"),
            "Track start": (
                lambda: Track(vectors=[(10, 0), (0, 10)], start=fn), "angle",
            ),
            "corner_radius ctor": (
                lambda: Rect(center=(0, 0), width=10, height=8, corner_radius=fn),
                "@=",
            ),
            "corner_radius set": (set_radius, "@="),
            "corner_radius @=": (link_radius, "@="),
        }
        for label, (call, hint) in cases.items():
            with self.subTest(call=label):
                try:
                    call()
                except BaseException as exc:  # noqa: BLE001
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    # Bracket ``@=`` on a reserved paint name raises AttributeError
                    # (same message as ``= lambda``, which is CallableAssignError).
                    assert_author_error(
                        self, exc, call=label,
                        allowed=(TypeError, ValueError, AttributeError),
                    )
                    self.assertIn(hint, str(exc))
                else:
                    self.fail(f"{label} accepted a function")

    def test_corner_radius_assign_is_callable_assign_error(self):
        rect = Rect(center=(0, 0), width=10, height=8)
        with self.assertRaises(CallableAssignError):
            rect.corner_radius = lambda: 4
        with self.assertRaises(CallableAssignError):
            Rect(center=(0, 0), width=10, height=8, corner_radius=lambda: 4)

    def test_track_rotation_links(self):
        src = Point(15, 0)
        path = Track(center=(0, 0), radius=10, angle=lambda: src.x)
        src.x = 40
        self.assertAlmostEqual(float(path.angle), 40.0)

    def test_polygon_vertex_links(self):
        src = Point(1, 2)
        poly = Polygon(points=[lambda: src, (0, 0), (5, 0)])
        src.x = 7
        src.y = 8
        self.assertAlmostEqual(float(poly.points[0].x), 7.0)
        self.assertAlmostEqual(float(poly.points[0].y), 8.0)
        self.assertAlmostEqual(float(poly.points[1].x), 0.0)


class TestFamilyConstructorLinks(unittest.TestCase):
    """The families without constructor signatures (geometry campaign, H6):
    every geometry keyword takes a lambda that links, and a lambda of the
    same number builds the same shape as the number."""

    @classmethod
    def setUpClass(cls):
        init(width=400, height=300)

    @staticmethod
    def _cases():
        import warnings
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from media_support import media
        img = media("space", "enemyGreen1.png")

        def sprite(**kw):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                return Sprite(img, **kw)
        return [
            # (label, build(**kw), base kwargs, key, value, moved value)
            ("Sprite center", sprite, dict(height=20), "center", (10.0, 5.0), (30.0, -4.0)),
            ("Sprite angle", sprite, dict(center=(0, 0), height=20), "angle", 25.0, 70.0),
            ("Text center", lambda **kw: Text("geo", **kw), dict(), "center", (10.0, 5.0), (30.0, -4.0)),
            ("Text top_left", lambda **kw: Text("geo", **kw), dict(), "top_left", (10.0, 5.0), (30.0, -4.0)),
            ("Text top_right", lambda **kw: Text("geo", **kw), dict(), "top_right", (10.0, 5.0), (30.0, -4.0)),
            ("Text angle", lambda **kw: Text("geo", **kw), dict(center=(0, 0)), "angle", 25.0, 70.0),
            ("Track center", Track, dict(radius=10), "center", (10.0, 5.0), (30.0, -4.0)),
            ("Track radius", Track, dict(center=(0, 0)), "radius", 12.0, 20.0),
            ("Track angle", Track, dict(center=(0, 0), radius=10), "angle", 25.0, 70.0),
        ]

    def test_a_lambda_of_the_value_builds_the_same_shape_and_follows(self):
        from scena import State
        wrong = []
        for label, build, base, key, value, moved in self._cases():
            plain = build(**dict(base, **{key: value}))
            st = State(name="ctorfam")
            st.v = value
            if isinstance(value, tuple):
                linked = build(**dict(base, **{key: lambda: (st.v[0], st.v[1])}))
            else:
                linked = build(**dict(base, **{key: lambda: st.v + 0.0}))
            if not _near(_read(plain, key), _read(linked, key)):
                wrong.append(f"{label}: built {_read(linked, key)} vs {_read(plain, key)}")
            if _snapshot(plain) != _snapshot(linked):
                wrong.append(f"{label}: shape {_snapshot(linked)} vs {_snapshot(plain)}")
            st.v = moved
            if not _near(_read(linked, key), moved):
                wrong.append(f"{label}: does not follow ({_read(linked, key)} vs {moved})")
            for o in (plain, linked):
                o.destroy()
        self.assertEqual(wrong, [])

    def test_fixed_size_knobs_refuse_a_lambda_with_the_fix(self):
        """A Sprite's ``width`` / ``height`` are fixed at construction (play and
        ``frame=`` re-fit the body; Sprite Design): a lambda is refused with
        the linkable spelling, not stored."""
        cases = self._cases()
        sprite = cases[0][1]
        from scena import State
        st = State(name="ctorfixed")
        st.w = 30.0
        for key in ("width", "height"):
            with self.assertRaises(TypeError) as ctx:
                sprite(center=(0, 0), **{key: lambda: st.w + 0.0})
            self.assertIn("scale", str(ctx.exception))
