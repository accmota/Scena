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

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


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
        if obj._field_is_linked(name):
            continue                     # linked by the model itself (relational kinds)
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


class TestInkStoresNewObjects(unittest.TestCase):
    """E7 (graphics review): the ink store compared with ``!=``, so an equal
    but new list or Vec2 was not stored (the old object stayed) and a numpy
    array raised. Immutable values still compare by value."""

    def test_a_new_object_replaces_an_equal_one(self):
        import numpy as np
        c = scena.Circle(center=(0, 0), radius=3)
        try:
            first, second = [1, 2], [1, 2]
            c.dlw_items = first
            c.dlw_items = second
            self.assertIs(c.dlw_items, second)
            v1, v2 = Vec2(1, 2), Vec2(1, 2)
            c.dlw_v = v1
            c.dlw_v = v2
            self.assertIs(c.dlw_v, v2)
            c.dlw_arr = np.zeros(3)
            c.dlw_arr = np.ones(3)
            self.assertEqual(float(c.dlw_arr[0]), 1.0)
        finally:
            c.destroy()


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


# ---------------------------------------------------------------------------
# The write gate (graphics review R1): a pose verb on a linked shape either
# refuses with nothing changed, or runs and keeps the link. Which answer is
# right comes from an unlinked twin, not from a model of the gate: the parts
# the twin's verb changes are the parts the verb writes.
# ---------------------------------------------------------------------------

GATE_PIVOT = (50.0, -20.0)

GATE_VERBS = (
    ("move_by", lambda o: o.move_by(7, -3)),
    ("move_to", lambda o: o.move_to(60, 40)),
    ("rotate_by", lambda o: o.rotate_by(33)),
    ("rotate_by about", lambda o: o.rotate_by(33, about=GATE_PIVOT)),
    ("rotate_to", lambda o: o.rotate_to(float(o.angle) + 50)),
    ("scale_by", lambda o: o.scale_by(1.5)),
    ("scale_by about", lambda o: o.scale_by(1.5, about=GATE_PIVOT)),
    ("flip_x", lambda o: setattr(o, "flip_x", not o.flip_x)),
    ("flip_y", lambda o: setattr(o, "flip_y", not o.flip_y)),
    ("angle =", lambda o: setattr(o, "angle", float(o.angle) + 50)),
    ("scale =", lambda o: setattr(o, "scale", float(o.scale) * 1.5)),
)


def _gate_kinds():
    for kind in sorted(G.KINDS):
        if kind.split()[0] in NO_LINK or kind.startswith("Box") or kind.endswith("reversed"):
            continue                  # Box is a value; a reversed view forwards to its host
        yield kind


def _pose_reads(obj) -> dict:
    out = {}
    for name in ("angle", "scale", "flip_x", "flip_y"):
        try:
            v = getattr(obj, name)
            out["pose." + name] = (float(v),)
        except Exception as e:  # noqa: BLE001
            out["pose." + name] = ("raises", type(e).__name__)
    return out


def _gate_state(obj) -> dict:
    return {**_read_all(obj), **_pose_reads(obj)}


def _keys_of(target: str) -> tuple:
    """The read keys that show a write to ``target``."""
    if target in ("angle", "scale"):
        return (target, "pose." + target)
    return (target, "~" + target)


def _gate_targets(probe):
    """(name, how) for each link target: Defining fields, pose anchors, the whole object."""
    out = [(name, what) for name, what, _slot in _defining_fields(probe)]
    names = {n for n, _ in out}
    for pose in ("angle", "scale"):
        if pose not in names and pose not in probe._field_slots() and hasattr(type(probe), pose):
            out.append((pose, "scalar"))
    out.append(("whole", "whole"))
    return out


def _link(obj, kind, name, how):
    """Link ``name`` to a cell holding its current value (reads do not move)."""
    if how == "whole":
        src = G.build(kind)
        obj @= (lambda s=src: s)
        return src
    if how == "scalar":
        st.gate_s = float(getattr(obj, name))
        obj[name] @= (lambda: st.gate_s)
        return None
    cur = getattr(obj, name)
    st.gate_x, st.gate_y = float(cur.x), float(cur.y)
    getattr(obj, name).__imatmul__(lambda: (st.gate_x, st.gate_y))
    return None


def _changed(before: dict, after: dict) -> set:
    return {k for k, _a, _b in _differences(before, after)}


def gate_violations(kinds=None) -> dict:
    """``"kind | target | verb | verdict"`` -> detail, for every case off the contract."""
    from scena.state import LinkedAttributeError
    out = {}
    for kind in (kinds or _gate_kinds()):
        probe = G.build(kind)
        if not hasattr(probe, "_field_slots"):
            _destroy(probe)
            continue
        targets = _gate_targets(probe)
        _destroy(probe)
        for verb_name, verb in GATE_VERBS:
            twin = G.build(kind)
            try:
                t0 = _gate_state(twin)
                verb(twin)
                t1 = _gate_state(twin)
            except Exception:  # noqa: BLE001  (the verb does not apply to this kind)
                _destroy(twin)
                continue
            _destroy(twin)
            written = _changed(t0, t1)
            for name, how in targets:
                obj = G.build(kind)
                extra = None
                key = f"{kind} | {name} | {verb_name}"
                try:
                    try:
                        extra = _link(obj, kind, name, how)
                    except Exception as e:  # noqa: BLE001
                        if how != "whole":
                            out[f"{key} | link raises"] = type(e).__name__
                        continue
                    # A whole-object link drives everything a copy carries:
                    # geometry and pose (C7), or position only for a Point
                    # (``_whole_link_carries_pose``). Any change of those refuses.
                    if how == "whole":
                        carries_pose = getattr(type(obj), "_whole_link_carries_pose", True)
                        hits = written if carries_pose else {k for k in written if not k.startswith("pose.")}
                    else:
                        hits = written & set(_keys_of(name))
                    s0 = _gate_state(obj)
                    try:
                        verb(obj)
                        err = None
                    except LinkedAttributeError:
                        err = "linked"
                    except Exception as e:  # noqa: BLE001
                        err = type(e).__name__
                    s1 = _gate_state(obj)
                    if err == "linked":
                        if not hits:
                            out[f"{key} | over-strict"] = "refused a verb that does not write it"
                        elif _changed(s0, s1):
                            out[f"{key} | half-applied"] = ", ".join(sorted(_changed(s0, s1))[:4])
                    elif err:
                        out[f"{key} | raises {err}"] = ""
                    elif hits:
                        out[f"{key} | under-strict"] = "ran over a linked part: " + ", ".join(sorted(hits)[:4])
                    else:
                        diff = _differences(s1, t1)
                        if diff:
                            out[f"{key} | diverged"] = ", ".join(k for k, _a, _b in diff[:4])
                        linked = obj._is_linked() if how == "whole" and hasattr(obj, "_is_linked") else (
                            True if how == "whole" else obj._field_is_linked(name))
                        if not linked:
                            out[f"{key} | link dropped"] = ""
                finally:
                    _destroy(obj)
                    if extra is not None:
                        _destroy(extra)
    return out


class TestLinkWriteGate(unittest.TestCase):
    """Graphics review R1 (SA1, SA2 = E6 = PB2, SA3, SB3, SC8): one rule for
    every kind, link target and pose verb. Known violations are shrink-only
    (``graphics_known.GATE``)."""

    def test_every_kind_target_and_verb(self):
        from graphics_known import shrink_only
        shrink_only(self, gate_violations(), "GATE")

    def test_canary_a_gate_that_lets_everything_through(self):
        from diff_support import assert_catches
        assert_catches(self, "test_diff_link_write.TestLinkWriteGate.test_every_kind_target_and_verb",
                       [("scena.shapes", "_ensure_writable", lambda *a, **k: None)],
                       "a write gate that never refuses")



class TestFieldRefSourceFollowsEveryWriter(unittest.TestCase):
    """A link that reads one field of another object (``q["x"] @= p["x"]``,
    the Guia's spelling) follows every writer of that field, not only ``=``:
    copies, part writes, pose verbs (instant and timed), flips, tweens, and
    a Derivate scalar it reads stays live (review 2026-10-09 S5-1, S5-2,
    S6-5). The oracle is the source itself, read raw."""

    KINDS = {
        "Circle": (lambda: _sc().Circle(center=(10, 20), radius=10), "center", "radius",
                   lambda: _sc().Circle(center=(70, 80), radius=17)),
        "Rect": (lambda: _sc().Rect(top_left=(10, 20), width=10, height=6), "top_left", "width",
                 lambda: _sc().Rect(top_left=(70, 80), width=17, height=9)),
        "Line": (lambda: _sc().Line(p1=(10, 20), p2=(30, 20)), "p1", None,
                 lambda: _sc().Line(p1=(70, 80), p2=(90, 85))),
        "Ellipse": (lambda: _sc().Ellipse(center=(10, 20), width=10, height=6), "center", "width",
                    lambda: _sc().Ellipse(center=(70, 80), width=17, height=9)),
        "RegularPolygon": (lambda: _sc().RegularPolygon(center=(10, 20), radius=10, n=5), "center", "radius",
                           lambda: _sc().RegularPolygon(center=(70, 80), radius=17, n=5)),
    }

    WRITERS = (
        ("part =", lambda s, L, S, other: setattr(s, L.attr_name, (55, 66))),
        ("leaf <<", lambda s, L, S, other: L << (55, 66)),
        ("<<", lambda s, L, S, other: s << other()),
        ("absorb", lambda s, L, S, other: s.absorb(other())),
        ("move_to", lambda s, L, S, other: s.move_to(55, 66)),
        ("move_by", lambda s, L, S, other: s.move_by(5, 7)),
        ("rotate_by about", lambda s, L, S, other: s.rotate_by(30, about=(0, 0))),
        ("scale_by about", lambda s, L, S, other: s.scale_by(2, about=(0, 0))),
        ("rotate_by", lambda s, L, S, other: s.rotate_by(30)),
        ("flip_x", lambda s, L, S, other: setattr(s, "flip_x", True)),
        ("tween leaf", lambda s, L, S, other: _sc().tween(L, (55, 66), time=0.25)),
        ("move_to time", lambda s, L, S, other: s.move_to(55, 66, time=0.25)),
    )

    def test_every_kind_and_writer(self):
        from tests.system_support import system_world
        sc = _sc()
        stale = []
        for kind, (make, lname, sname, other) in self.KINDS.items():
            for wname, write in self.WRITERS:
                with system_world(draw=False) as w:
                    s = make()
                    L = getattr(s, lname)
                    qx = sc.Point(0, 0)
                    qx["x"] @= L["x"]
                    ks = None
                    if sname:
                        ks = sc.Circle(center=(0, 0), radius=1)
                        ks["radius"] @= s[sname]
                    w.step(1, dt=1 / 60)
                    write(s, L, sname, other)
                    w.step(20, dt=1 / 60)
                    if qx.x != L.__dict__.get("x"):
                        stale.append((kind, wname, "leaf x"))
                    if ks is not None and ks.radius != max(0.0, s.__dict__.get(sname)):
                        stale.append((kind, wname, sname))
        self.assertEqual(stale, [])

    def test_vec2_and_text_sources(self):
        from tests.system_support import system_world
        sc = _sc()
        with system_world(draw=False) as w:
            v = sc.Vec2(1, 2)
            z = sc.Point(0, 0)
            z["x"] @= v["x"]
            v << (9, 9)
            w.step(1, dt=1 / 60)
            self.assertEqual(z.x, 9)
            t = sc.Text("abc", top_left=(0, 0))
            d = sc.Point(0, 0)
            d["x"] @= t.top_left["x"]
            t.move_by(10, 0)
            w.step(1, dt=1 / 60)
            self.assertEqual(d.x, t.top_left.x)
            t.destroy()

    def test_a_derivate_scalar_read_by_a_link_stays_live(self):
        from tests.system_support import system_world
        sc = _sc()
        with system_world(draw=False) as w:
            ln = sc.Line(p1=(0, 0), p2=(10, 0))
            k = sc.Circle(center=(0, 0), radius=1)
            k["radius"] @= ln["length"]
            ln.p2 = (30, 0)
            w.step(1, dt=1 / 60)
            self.assertEqual(ln.length, 30.0)      # froze at 10 for every reader
            self.assertEqual(k.radius, 30.0)
            v = sc.Vec2(3, 4)
            m = sc.Point(0, 0)
            m["x"] @= v["length"]
            v.x = 6
            w.step(1, dt=1 / 60)
            self.assertAlmostEqual(v.length, (36 + 16) ** 0.5)
            self.assertAlmostEqual(m.x, v.length)


def _sc():
    import scena
    return scena


if __name__ == "__main__":
    unittest.main(verbosity=2)
