"""Vec2 metamorphic relations: twins that must agree, invariances that must hold.

Testing Design, "Vec2 battery". No expected value is written anywhere:

* **Twins.** One sequence of author writes runs on every kind of vector at
  once — a free vector read cold, one read after every step (warm), one forced
  onto the slow path (``force_slow``), one whose A3 bare-read cache is cleared
  before every step, an actor's ``vel``, an st cell's vector, a watched ink
  field's vector, and each Defining shape part. After every step all hold the
  same bits, their length / angle agree with their x / y, and every formula
  reading a holder shows the holder's value, read at a Hypothesis-chosen
  moment ("agreement beats prediction").
* **Door equivalence.** ``v += w``, ``v = v + w``, ``v << v + w`` and two axis
  writes leave the same bits.
* **Invariances.** Rotating both operands keeps dot, cross, lengths and
  distance; translating by integers keeps distance exactly; scaling scales;
  swapping or negating the axes moves ``angle`` as geometry says.

    python -m unittest tests.test_vec2_metamorphic -v
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import given, strategies as hst  # noqa: E402

import hypothesis_support as hs  # noqa: E402
from diff_support import force_slow  # noqa: E402
from scena import Circle, Line, Rect, State, Vec2, init  # noqa: E402
from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()

exact = hst.integers(min_value=-500, max_value=500).map(float)
pair = hst.tuples(exact, exact)
quarter = hst.sampled_from([90.0, -90.0, 180.0, 30.0, -45.0])
coord = hst.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
angle = hst.floats(min_value=-720.0, max_value=720.0, allow_nan=False, allow_infinity=False)

# One author step: (door, operand). ``.x =`` / ``.y =`` are absent: an st
# cell's vector refuses them by design (CS4).
step = hst.one_of(
    hst.tuples(hst.just("+="), pair),
    hst.tuples(hst.just("-="), pair),
    hst.tuples(hst.just("<<"), pair),
    hst.tuples(hst.just("= whole"), pair),
    hst.tuples(hst.just("do_rotation"), quarter),
    hst.tuples(hst.just("*="), hst.sampled_from([2.0, -1.0, 0.5, 3.0])),
)
steps = hst.lists(hst.tuples(step, hst.booleans()), min_size=1, max_size=12)


class _Twin:
    """One holder of the twin set: ``get()`` is its vector now, ``write`` the
    author spelling, ``watch`` what a formula reading the holder shows."""

    def __init__(self, name, get, assign, *, watch=None, every_step=None):
        self.name = name
        self.get = get
        self.assign = assign          # obj.attr = value through the holder
        self.watch = watch
        self.every_step = every_step  # something the twin does before each step

    def apply(self, door, o):
        v = self.get()
        if door == "+=":
            v += o
            self.assign(v)
        elif door == "-=":
            v -= o
            self.assign(v)
        elif door == "<<":
            v << o
        elif door == "= whole":
            self.assign(Vec2(*o))     # a cell / ink field holds what it is given
        elif door == "do_rotation":
            v.do_rotation(o)
        elif door == "*=":
            v *= o
            self.assign(v)


def _twins(owned):
    def holder(obj, attr):
        return (lambda: getattr(obj, attr)), (lambda val: setattr(obj, attr, val))

    def free(name, prepare=None, every_step=None):
        box = {"v": Vec2(1, 2)}
        if prepare:
            prepare(box["v"])

        def assign(val):
            # A free vector is rebound by ``v = …``; ``v << val`` keeps the
            # object (the twins compare values).
            if val is not box["v"]:
                box["v"] << val
        return _Twin(name, lambda: box["v"], assign, every_step=every_step)

    def warm(t):
        v = t.get()
        v.length, v.angle

    def drop_a3(t):
        t.get().__dict__.pop("_scalar_bare_ok", None)

    twins = [free("free cold"), free("free warm", every_step=warm),
             free("free slow", prepare=force_slow), free("free no A3", every_step=drop_a3)]

    c = Circle(center=(100, 100), radius=5)
    owned.append(c)
    c.vel = (1, 2)
    get, assign = holder(c, "vel")
    w = Circle(center=lambda: c.vel, radius=1)
    owned.append(w)
    twins.append(_Twin("vel", get, assign, watch=lambda: (w.center.x, w.center.y)))

    st = State(name="vb_meta")
    st.pos = Vec2(1, 2)
    get, assign = holder(st, "pos")
    w2 = Circle(center=lambda: st.pos, radius=1)
    owned.append(w2)
    twins.append(_Twin("st", get, assign, watch=lambda: (w2.center.x, w2.center.y)))

    ship = Circle(center=(0, 0), radius=5)
    owned.append(ship)
    ship.aim = Vec2(1, 2)
    get, assign = holder(ship, "aim")
    w3 = Circle(center=lambda: ship.aim, radius=1)
    owned.append(w3)
    twins.append(_Twin("ink", get, assign, watch=lambda: (w3.center.x, w3.center.y)))

    line = Line(p1=(0, 0), vec=(1, 2))
    rect = Rect(p1=(0, 0), vec=(1, 2))
    owned.extend([line, rect])
    for name, obj in (("Line.vec", line), ("Rect.vec", rect)):
        get, assign = holder(obj, "vec")
        twins.append(_Twin(name, get, assign))
    return twins


def _bits(v):
    return (float(v.x), float(v.y))


class TestTwinsAgree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    @given(steps)
    def test_one_sequence_every_kind(self, seq):
        owned: list = []
        try:
            twins = _twins(owned)
            for i, ((door, o), read_now) in enumerate(seq):
                for t in twins:
                    if t.every_step:
                        t.every_step(t)
                    with hs.quiet():
                        t.apply(door, o)
                want = _bits(twins[0].get())
                for t in twins:
                    v = t.get()
                    where = f"step {i} {door} {o!r} on {t.name}"
                    self.assertEqual(_bits(v), want, where)
                    self.assertEqual(v.length, math.sqrt(v.x * v.x + v.y * v.y), where)
                    self.assertEqual(v.angle, math.degrees(math.atan2(v.y, v.x)), where)
                    if t.watch is not None and (read_now or i == len(seq) - 1):
                        self.assertEqual(t.watch(), want, where + " (formula)")
        finally:
            for obj in reversed(owned):
                obj.destroy()


class TestDoorsAgree(unittest.TestCase):
    """Four spellings of one displacement leave the same bits."""

    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    @given(coord, coord, coord, coord)
    def test_displacement_spellings(self, x, y, dx, dy):
        a, b, c, d = (Vec2(x, y) for _ in range(4))
        a += (dx, dy)
        b = b + (dx, dy)
        c << c + (dx, dy)
        d.x = d.x + dx
        d.y = d.y + dy
        self.assertEqual(_bits(a), _bits(b))
        self.assertEqual(_bits(a), _bits(c))
        self.assertEqual(_bits(a), _bits(d))
        for v in (a, b, c, d):
            self.assertEqual(v.length, math.sqrt(v.x * v.x + v.y * v.y))

    @given(coord, coord, angle)
    def test_rotation_spellings(self, x, y, t):
        a, b = Vec2(x, y), Vec2(x, y)
        a.do_rotation(t)
        b << b.rotate(t)
        self.assertEqual(_bits(a), _bits(b))


def _near(a, b, scale, ulps=512):
    return abs(a - b) <= ulps * math.ulp(max(1.0, abs(scale)))


class TestInvariances(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init(width=800, height=600)

    @given(coord, coord, coord, coord, angle)
    def test_rotating_both_keeps_the_relations(self, ax, ay, bx, by, t):
        a, b = Vec2(ax, ay), Vec2(bx, by)
        ra, rb = a.rotate(t), b.rotate(t)
        s = max(1.0, a.length, b.length)
        self.assertTrue(_near(ra.length, a.length, s))
        self.assertTrue(_near(ra.dot(rb), a.dot(b), s * s, ulps=4096))
        self.assertTrue(_near(ra.cross(rb), a.cross(b), s * s, ulps=4096))
        self.assertTrue(_near(ra.distance(rb), a.distance(b), s, ulps=1024))

    @given(exact, exact, exact, exact, exact, exact)
    def test_translating_keeps_distance_exactly(self, ax, ay, bx, by, tx, ty):
        a, b = Vec2(ax, ay), Vec2(bx, by)
        self.assertEqual((a + (tx, ty)).distance(b + (tx, ty)), a.distance(b))
        self.assertEqual(((a + (tx, ty)) - (b + (tx, ty))).length, (a - b).length)

    @given(exact, exact, exact, exact, hst.integers(min_value=-20, max_value=20).map(float))
    def test_scaling(self, ax, ay, bx, by, k):
        a, b = Vec2(ax, ay), Vec2(bx, by)
        self.assertEqual((a * k).dot(b), k * a.dot(b))
        self.assertEqual((a * k).cross(b), k * a.cross(b))
        self.assertTrue(_near((a * k).length, abs(k) * a.length, abs(k) * a.length + 1))

    @given(coord, coord)
    def test_mirrors_move_the_angle(self, x, y):
        v = Vec2(x, y)
        if v.length == 0:
            return
        # Swapping the axes mirrors about the 45° line: angle -> 90 - angle.
        swapped = Vec2(y, x).angle
        turn = (swapped - (90.0 - v.angle)) % 360.0
        self.assertLess(min(turn, 360.0 - turn), 1e-9)
        # Negating turns by a half turn.
        turn = ((-v).angle - v.angle) % 360.0
        self.assertLess(abs(turn - 180.0), 1e-9)
        # Conjugating (y -> -y) negates the angle, except on the -x axis.
        if not (v.y == 0 and v.x < 0):
            self.assertEqual(Vec2(x, -y).angle, -v.angle)


if __name__ == "__main__":
    unittest.main()
