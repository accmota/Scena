"""Differential: a field driven by a link reads like the same field written with ``=``.

For every geometry model (``geometry_support.KINDS``) and every Defining field
(scalar, Point or Vec2 part): twin A links the field to an ``st`` cell (the
whole part, or one link per axis), twin B gets the same value by a plain write
(``=`` / ``<<``). After the cell changes, every read an author can make —
slots, named points, ``vec`` with its ``length`` / ``angle``, sizes — must
agree. Both twins are read at the same moments (a Rect names its corners at
first use, so reading only one twin would compare two namings).

Bugs this caught (Testing Design D12–D14): a link's raw store left a Vec2's
computed ``length`` / ``angle`` stale; an owner's refresh marked a linked part
clean before it pulled (a linked ``spread`` froze); a link on Track ``begin`` /
``end`` skipped the 0..1 clamp ``=`` applies. Linked ink is checked apart
(``TestLinkedInkFollows``): ink is not a model field.

Run headless:

    python tests/run_tiers.py focused test_diff_link_write
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot  # noqa: E402

boot()

import scena  # noqa: E402
from scena import Vec2, st  # noqa: E402
from scena.state import ContainerSlot, ScalarSlot  # noqa: E402

import geometry_support as G  # noqa: E402

# Kinds whose fields refuse a link on purpose (kind -> reason).
NO_LINK = {
    "Anchor": "a draggable Anchor refuses a position link (the pointer drags it)",
}


def _value(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (float(v),)
    if hasattr(v, "x") and hasattr(v, "y") and not callable(v):
        out = (float(v.x), float(v.y))
        if isinstance(v, Vec2):
            out += (float(v.length), float(v.angle))
        return out
    return None


def _read_all(obj) -> dict:
    """Every observable read: slots, named points, vec parts, sizes."""
    out = {}
    for name in sorted(obj._field_slots()):
        try:
            v = _value(getattr(obj, name))
        except Exception as e:  # a read that raises must raise on both twins
            v = ("raises", type(e).__name__)
        if v is not None:
            out[name] = v
    for readers in (G.point_parts(obj), G.vector_parts(obj), G.scalar_parts(obj)):
        for name, read in readers.items():
            try:
                r = read()
                out["~" + name] = tuple(float(c) for c in (r if isinstance(r, tuple) else (r,)))
            except Exception as e:
                out["~" + name] = ("raises", type(e).__name__)
    return out


def _differences(a: dict, b: dict) -> list:
    bad = []
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if x is None or y is None or len(x) != len(y) or any(isinstance(c, str) for c in x + y):
            if x != y:
                bad.append((key, x, y))
            continue
        for p, q in zip(x, y):
            if math.isclose(p, q, rel_tol=1e-6, abs_tol=1e-6):
                continue
            if "angle" in key and math.isclose(((p - q + 180) % 360) - 180, 0, abs_tol=1e-6):
                continue
            bad.append((key, x, y))
            break
    return bad


def _defining_fields(obj):
    out = []
    for name, slot in obj._field_slots().items():
        if obj._field_is_derivate(name, slot):
            continue
        if isinstance(slot, ScalarSlot):
            v = getattr(obj, name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append((name, "scalar", slot))
        elif isinstance(slot, ContainerSlot) and slot.container_class.__name__ in ("Point", "Vec2"):
            out.append((name, "part", slot))
    return out


def _new_scalar(cur: float, slot) -> float:
    nv = cur * 1.37 + 2.5 if cur else 3.25
    # ``=`` raises past a magnitude's maximum (spread > 360); stay inside it.
    if slot.magnitude and slot.maximum is not None and nv > slot.maximum:
        nv = cur * 0.6
    return nv


def _destroy(*objs):
    for o in objs:
        try:
            o.destroy()
        except Exception:
            pass


class TestLinkReadsLikeWrite(unittest.TestCase):
    def _cases(self):
        for kind in G.KINDS:
            if kind.split()[0] in NO_LINK:
                continue
            probe = G.build(kind)
            if not hasattr(probe, "_field_slots"):
                continue
            fields = _defining_fields(probe)
            _destroy(probe)
            for name, what, slot in fields:
                modes = ("whole", "axis") if what == "part" else ("whole",)
                for mode in modes:
                    for read_first in (False, True):
                        yield kind, name, what, slot, mode, read_first

    def test_every_model_and_defining_field(self):
        checked = 0
        for kind, name, what, slot, mode, read_first in self._cases():
            with self.subTest(kind=kind, field=name, mode=mode, read_first=read_first):
                a, b = G.build(kind), G.build(kind)
                try:
                    if read_first:
                        _read_all(a); _read_all(b)
                    cur = getattr(a, name)
                    if what == "scalar":
                        cur = float(cur)
                        nv = _new_scalar(cur, slot)
                        st.dlw_s = cur
                        a[name] @= lambda: st.dlw_s
                        _read_all(a); _read_all(b)
                        st.dlw_s = nv
                        setattr(b, name, nv)
                    else:
                        cur = (float(cur.x), float(cur.y))
                        nv = (cur[0] + 5.5, cur[1] - 3.25)
                        st.dlw_x, st.dlw_y = cur
                        part = getattr(a, name)
                        if mode == "whole":
                            part @= lambda: (st.dlw_x, st.dlw_y)
                        else:
                            part["x"] @= lambda: st.dlw_x
                            part["y"] @= lambda: st.dlw_y
                        _read_all(a); _read_all(b)
                        st.dlw_x, st.dlw_y = nv
                        getattr(b, name) << nv
                    bad = _differences(_read_all(a), _read_all(b))
                    self.assertEqual(bad, [], f"linked vs written {kind}.{name}: (read, linked, written)")
                    checked += 1
                finally:
                    _destroy(a, b)
        self.assertGreater(checked, 100)     # not vacuous


class TestLinkedInkFollows(unittest.TestCase):
    """``r["hp"] @= …`` read after a Derivate (``r.width``) returned the old hp:
    the owner's refresh cleared the ink anchor's dirty flag before it pulled."""

    def test_ink_after_any_derived_read(self):
        for kind in G.KINDS:
            if kind.split()[0] in NO_LINK or kind.startswith("Box"):
                continue                       # Box is a value: no ink
            for read in ("width", "length", "center", "p1", "top_left", "box"):
                with self.subTest(kind=kind, read=read):
                    obj = G.build(kind)
                    try:
                        if not hasattr(type(obj), read):
                            continue
                        obj.dlw_hp = 0.0
                        st.dlw_hp = 1.0
                        obj["dlw_hp"] @= lambda: st.dlw_hp
                        self.assertEqual(obj.dlw_hp, 1.0)
                        st.dlw_hp = 2.0
                        try:
                            got = getattr(obj, read)
                            getattr(got, "x", None)
                        except Exception:
                            pass
                        self.assertEqual(obj.dlw_hp, 2.0)
                    finally:
                        _destroy(obj)

    def test_linked_spread_after_a_derived_point(self):
        c = scena.Circle(center=(0, 0), radius=5, spread=120)
        try:
            st.dlw_sp = 120.0
            c["spread"] @= lambda: st.dlw_sp
            st.dlw_sp = 150.0
            c.p1.x
            self.assertEqual(c.spread, 150.0)
        finally:
            c.destroy()


class TestLinkedTrackWindowClamps(unittest.TestCase):
    def test_begin_and_end_clamp_like_a_write(self):
        t = scena.Track.line(p1=(0, 0), p2=(40, 0))
        try:
            st.dlw_b, st.dlw_e = 0.0, 1.0
            t["begin"] @= lambda: st.dlw_b
            t["end"] @= lambda: st.dlw_e
            st.dlw_b, st.dlw_e = -2.0, 3.0
            self.assertEqual((t.begin, t.end), (0.0, 1.0))
            st.dlw_b, st.dlw_e = 0.25, 0.75
            self.assertEqual((t.begin, t.end), (0.25, 0.75))
        finally:
            t.destroy()


class TestCellHoldingAPair(unittest.TestCase):
    """``v @= lambda: st.pos`` / ``v << st.pos`` with ``st.pos`` holding a tuple
    or a Vec2 raised TypeError: the Vec2 / Point raw store got the cell, not its
    value (a scalar field already unwrapped it)."""

    def test_link_and_copy_from_a_cell(self):
        makers = {
            "Vec2": lambda: Vec2(0, 0),
            "Point": lambda: scena.Point(0, 0),
            "circle.center": lambda: scena.Circle(center=(0, 0), radius=3).center,
        }
        for held in ("tuple", "Vec2"):
            pair = (lambda x, y: (x, y)) if held == "tuple" else (lambda x, y: Vec2(x, y))
            for name, make in makers.items():
                with self.subTest(target=name, cell_holds=held):
                    st.dlw_pos = pair(1.0, 2.0)
                    linked, copied = make(), make()
                    linked @= lambda: st.dlw_pos
                    copied << st.dlw_pos
                    st.dlw_pos = pair(5.0, 6.0)
                    self.assertEqual((linked.x, linked.y), (5.0, 6.0))
                    self.assertEqual((copied.x, copied.y), (1.0, 2.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
