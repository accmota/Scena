"""A refused call changes nothing (graphics review R2, "check, then write").

The 2026-10-08 graphics review found the same shape at fifteen sites: a verb
wrote part A, then checked part B and raised, so the refusal left a
half-applied change. A flip flag stayed set, a Polygon was half mirrored,
``rect << box`` zeroed the rect, ``tag("a", 5)`` claimed "a", and
``clone(scale="x")`` left a live clone. Tests had checked that the call
raised, but not the state left behind.

This guard enumerates the calls instead of picking cases. Subjects are the
Graphic kinds of ``geometry_support.KINDS``. Calls are every public method
(arguments guessed from the signature, as P6 does) and every setter. Each
call is tried from three refusal sources:

* **dead**: a destroyed actor. Every call raises ``DestroyedError`` or
  changes nothing (Actors Design, "Instant change on a destroyed actor").
* **junk**: one argument replaced by a value of the wrong type. If the call
  raises, it changed nothing.
* **linked**: the whole object linked with ``@=``. If the call raises
  ``LinkedAttributeError``, it changed nothing.

The oracle has no model of its own: every public read of the subject (props,
parts, pose, ink) and the registry census are compared before and after.
Known violations are shrink-only (``graphics_known.ATOMIC``).

    python tests/run_tiers.py focused test_refusal_atomic
"""
from __future__ import annotations

import functools
import inspect
import math
import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import fresh_world, quiet  # noqa: E402

import geometry_support as G  # noqa: E402
import scena  # noqa: E402
from scena.state import DestroyedError, LinkedAttributeError  # noqa: E402
from surface_support import census_diff, surface_census  # noqa: E402
from test_hyp_surface import _AUTHOR_WORDS, _guess_args  # noqa: E402

# Reads that are not state: identity of fresh helpers, wall time, engine caches.
_NOT_STATE = {"is_alive", "is_collapsed", "made_at", "sheet", "image", "hitbox",
              "children", "parts", "owner"}
# Calls that are not refusable writes (pure reads, or the end of life itself).
_NOT_CALLED = {"destroy", "setup", "update", "clone", "look_like", "save_visual",
               "restore_visual", "contains_point", "collides_with", "distance_to",
               "tagged", "cancel_process", "unlink", "unlink_all", "nearest",
               "is_touching", "touching", "test_collision", "resolve_now"}
_ENGINE_PREFIXES = ("on_mouse_", "on_key", "on_char", "draw", "tick", "_")
_JUNK = "junk"

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


def _subjects():
    for kind in sorted(G.KINDS):
        if kind.startswith("Box") or kind.endswith("reversed"):
            continue
        yield kind


def _norm(v, depth=0):
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return "nan" if math.isnan(f) else round(f, 7)
    if isinstance(v, (tuple, list)) and depth < 2:
        return tuple(_norm(x, depth + 1) for x in v)
    if isinstance(v, (set, frozenset)):
        return tuple(sorted(map(str, v)))
    if hasattr(v, "name") and type(v).__class__.__name__ == "EnumMeta":
        return v.name
    if type(v).__name__ == "Color":
        return ("Color",) + tuple(round(float(c), 6) for c in v.rgb)
    if hasattr(v, "x") and hasattr(v, "y") and not callable(v):
        try:
            return (round(float(v.x), 7), round(float(v.y), 7))
        except Exception:  # noqa: BLE001
            pass
    if callable(v):
        return "<callable>"
    return "<" + type(v).__name__ + ">"


@functools.lru_cache(maxsize=None)
def _props(cls):
    out = []
    for name in dir(cls):
        if name.startswith("_") or name in _NOT_STATE:
            continue
        if isinstance(inspect.getattr_static(cls, name, None), property):
            out.append(name)
    return tuple(out)


def observable(obj) -> dict:
    """Every public read of ``obj`` plus its ink and registry facts, normalized."""
    out = {}
    with quiet():
        for name in _props(type(obj)):
            try:
                out[name] = _norm(getattr(obj, name))
            except Exception as e:  # noqa: BLE001
                out[name] = ("raises", type(e).__name__)
        ink = obj.__dict__.get("_ink") or {}
        for k, v in ink.items():
            out["ink." + k] = _norm(getattr(v, "value", v))
        try:
            out["~groups"] = tuple(sorted(obj.groups))
        except Exception:  # noqa: BLE001
            pass
    return out


def _unstable_keys(kind, prepare) -> frozenset:
    """Reads of a prepared ``kind`` that change on their own (three plain reads).

    Computed once per kind and source, then left out of every baseline. A read
    that is not stable by itself is a bug of its own class (GR3, a dead focal
    Ellipse's ``box``): ``unstable_reads`` pins it once, so it does not show up
    again under every call."""
    obj = _build(kind)
    extra = None
    try:
        extra = prepare(obj)
        if extra is False:
            return frozenset()
        a, b, c = observable(obj), observable(obj), observable(obj)
        return frozenset(k for k in set(a) | set(b) | set(c) if not (a.get(k) == b.get(k) == c.get(k)))
    finally:
        with quiet():
            for o in (obj, extra):
                if o is not None and o is not False and getattr(o, "is_alive", False):
                    o.destroy()


def unstable_reads(kinds=None) -> dict:
    """``"kind | alive|dead | read"`` for every public read that changes when read again."""
    out = {}
    with fresh_world():
        for kind in (kinds or _subjects()):
            for state in ("alive", "dead"):
                obj = _build(kind)
                if state == "dead":
                    obj.destroy()
                reads = [observable(obj) for _ in range(3)]
                for k in reads[0]:
                    if not (reads[0][k] == reads[1].get(k) == reads[2].get(k)):
                        out[f"{kind} | {state} | {k}"] = " -> ".join(str(r.get(k))[:30] for r in reads)
                if state == "alive":
                    obj.destroy()
    return out


def _changed(before: dict, after: dict) -> list:
    return sorted(k for k in before if after.get(k) != before[k])


def _methods(cls):
    out = []
    for attr in sorted(dir(cls)):
        if attr in _NOT_CALLED or attr.startswith(_ENGINE_PREFIXES) or attr not in _AUTHOR_WORDS:
            continue
        member = inspect.getattr_static(cls, attr, None)
        if isinstance(member, (property, staticmethod, classmethod)) or not callable(member):
            continue
        guess = _guess_args(getattr(cls, attr))
        if guess is not None:
            out.append((attr, guess))
    return out


def _setters(obj):
    route = getattr(type(obj), "_setattr_route", {}) or {}
    return sorted(a for a, d in route.items() if not a.startswith("_") and hasattr(d, "__set__")
                  and a not in _NOT_STATE)


def _other_value(cur):
    """A different value of the same shape (what a real write would bring)."""
    if isinstance(cur, bool):
        return not cur
    if isinstance(cur, (int, float)):
        return float(cur) * 1.5 + 3.0
    if hasattr(cur, "x") and hasattr(cur, "y") and not callable(cur):
        return (float(cur.x) + 5.0, float(cur.y) - 2.0)
    if isinstance(cur, str):
        return None
    return None


def _build(kind):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return G.build(kind)


def _call(obj, attr, args, kwargs):
    """Run one call; the error class name, or None."""
    try:
        with quiet():
            getattr(obj, attr)(*args, **kwargs)
        return None
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def _write(obj, attr, value):
    try:
        with quiet():
            setattr(obj, attr, value)
        return None
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def _calls(obj):
    """(label, run) for every method and setter of ``obj``."""
    out = []
    for attr, (args, kwargs) in _methods(type(obj)):
        out.append((f"{attr}()", lambda o, a=attr, x=args, k=kwargs: _call(o, a, x, k)))
    for attr in _setters(obj):
        try:
            with quiet():
                nv = _other_value(getattr(obj, attr))
        except Exception:  # noqa: BLE001
            continue
        if nv is not None:
            out.append((f"{attr} =", lambda o, a=attr, v=nv: _write(o, a, v)))
    return out


def _junk_calls(obj):
    """One argument of each method (or a setter's value) replaced by a string."""
    out = []
    for attr, (args, kwargs) in _methods(type(obj)):
        for i in range(len(args)):
            junk = list(args)
            junk[i] = _JUNK
            out.append((f"{attr}(arg{i}=junk)", lambda o, a=attr, x=tuple(junk), k=kwargs: _call(o, a, x, k)))
    for attr in _setters(obj):
        out.append((f"{attr} = junk", lambda o, a=attr: _write(o, a, _JUNK)))
    return out


# Cases a signature cannot guess: review repros, kept as one row each.
def _special_calls(obj):
    out = [
        ("tag('a', 5)", lambda o: _call(o, "tag", ("a", 5), {})),
        ("group = ['a', 5]", lambda o: _write(o, "group", ["a", 5])),
    ]
    # Sources are built here, before any baseline: building one is not the call.
    if isinstance(obj, scena.Rect):
        box = scena.Box(center=(9, 9), width=4, height=2)
        out.append(("<< Box", lambda o, b=box: _shift(o, b)))
    if not isinstance(obj, scena.Sprite):
        look = scena.Recolor("red")
        out.append(("visual = Recolor", lambda o, v=look: _write(o, "visual", v)))
    return out


def _shift(obj, src):
    try:
        with quiet():
            obj << src
        return None
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


# Census counts a refusal must not move. Strong registrations only: graph
# node counts include garbage, and a collect per case costs minutes.
_HELD = ("registry.", "collision.colliders", "collision.tag", "hitbox.", "sched.", "fx.", "bounds.")


def _census_moved(c0) -> dict:
    d = census_diff(c0, surface_census(collect=False))
    return {k: v for k, v in d.items() if k.startswith(_HELD) and k != "sched.every_sites"}


def _default_paints():
    """(color, alpha) of every default paint prototype's materials."""
    from scena.style import PaintState
    seen, out, todo = set(), [], [PaintState]
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        proto = cls.__dict__.get("_default_instance")
        if proto is None or id(proto) in seen:
            continue
        seen.add(id(proto))
        for name in ("_fill", "_line"):
            mat = getattr(proto, name, None)
            if type(mat).__name__ == "Color":
                out.append((mat, mat._a))
    return out


def _probe(kind, run, prepare, accept, skip=frozenset()):
    """One case: build, ``prepare``, baseline, call; the violation or None.

    HP1 (batch 3): ``set_alpha`` mutates the shared default Color, so one case
    would change what the next one starts from. The defaults are put back
    after each case until that is fixed (then this restore is a no-op)."""
    defaults = _default_paints()
    try:
        return _probe_once(kind, run, prepare, accept, skip)
    finally:
        for mat, a in defaults:
            object.__setattr__(mat, "_a", a)


def _probe_once(kind, run, prepare, accept, skip):
    obj = _build(kind)
    extra = None
    try:
        extra = prepare(obj)
        if extra is False:
            return None                       # this source does not apply to the kind
        s0 = {k: v for k, v in observable(obj).items() if k not in skip}
        c0 = surface_census(collect=False)
        err = run(obj)
        if err is None and not accept(None):
            return None                       # ran: other guards judge what it did
        if err is not None and not accept(err):
            return None                       # a different refusal: other guards
        s1 = observable(obj)
        moved = _changed(s0, s1)
        if moved:
            return ("raised " + err if err else "ran") + ": " + ", ".join(moved[:5])
        grew = _census_moved(c0)
        if grew:
            return ("raised " + err if err else "ran") + ": census " + ", ".join(sorted(grew)[:3])
        return None
    finally:
        with quiet():
            for o in (obj, extra):
                if o is not None and o is not False and getattr(o, "is_alive", False):
                    try:
                        o.destroy()
                    except Exception:  # noqa: BLE001
                        pass


def _dead(obj):
    obj.destroy()
    return None


def _whole_link(obj, kind):
    """Link the whole object to a twin; False when the kind takes no whole link."""
    src = _build(kind)
    try:
        obj @= (lambda s=src: s)
    except Exception:  # noqa: BLE001
        src.destroy()
        return False
    return src


def atomic_violations(kinds=None) -> dict:
    out = {}
    with fresh_world():
        for kind in (kinds or _subjects()):
            probe = _build(kind)
            calls, special, junk = _calls(probe), _special_calls(probe), _junk_calls(probe)
            probe.destroy()
            # dead: whatever the call does (DestroyedError or not), nothing changes.
            skip = _unstable_keys(kind, _dead)
            for label, run in calls + special:
                v = _probe(kind, run, _dead, lambda e: True, skip)
                if v:
                    out[f"{kind} | dead | {label}"] = v
            # junk: a raise changes nothing.
            skip = _unstable_keys(kind, lambda o: None)
            for label, run in junk + special:
                v = _probe(kind, run, lambda o: None, lambda e: e is not None, skip)
                if v:
                    out[f"{kind} | junk | {label}"] = v
            # linked: a link refusal changes nothing.
            link = (lambda o, k=kind: _whole_link(o, k))
            skip = _unstable_keys(kind, link)
            for label, run in calls:
                v = _probe(kind, run, link, lambda e: e == "LinkedAttributeError", skip)
                if v:
                    out[f"{kind} | linked | {label}"] = v
    return out


class TestRefusalIsAtomic(unittest.TestCase):
    def test_every_kind_call_and_source(self):
        from graphics_known import shrink_only
        shrink_only(self, atomic_violations(), "ATOMIC")

    def test_reads_are_stable(self):
        """Reading twice gives the same answer, alive or destroyed."""
        from graphics_known import shrink_only
        shrink_only(self, unstable_reads(), "UNSTABLE_READS")

    def test_canary_a_dead_check_that_lets_writes_through(self):
        from diff_support import assert_catches
        assert_catches(self, "test_refusal_atomic.TestRefusalIsAtomic.test_every_kind_call_and_source",
                       [("scena.entity", "_refuse_if_destroyed", lambda *a, **k: None)],
                       "writes on a destroyed actor that are stored")

class TestRefusedSpriteCallsChangeNothing(unittest.TestCase):
    """R2 sites a signature cannot reach: each refusal leaves the actor as it was."""

    def setUp(self):
        import tempfile
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from tests.test_sprite import _write_grid_png
        self._tmp = tempfile.TemporaryDirectory()
        self.small = os.path.join(self._tmp.name, "small.png")
        self.big = os.path.join(self._tmp.name, "big.png")
        _write_grid_png(self.small, cell=8, cols=2, rows=1)
        _write_grid_png(self.big, cell=16, cols=2, rows=1)

    def tearDown(self):
        self._tmp.cleanup()

    def _sprite(self):
        sheet = scena.Sheet(self.small, cell=(8, 8))
        sheet.clip("idle", [0, 1], fps=8)
        sheet.strip("big", self.big, cols=2, fps=8)
        with quiet():
            return scena.Sprite(sheet, center=(0, 0), height=16)

    def test_play_with_a_linked_size_refuses_before_switching(self):
        # PB1: the clip was half switched, and next= raised from the frame loop.
        with fresh_world():
            s = self._sprite()
            scena.st.ra_w = float(s.width)
            s["width"] @= (lambda: scena.st.ra_w)
            before = observable(s)
            with self.assertRaises(LinkedAttributeError):
                s.play("big")
            with self.assertRaises(LinkedAttributeError):
                s.play("idle", loops=1, next="big")
            self.assertEqual(_changed(before, observable(s)), [])
            s.destroy()

    def test_refused_reset_rotation_keeps_the_tilt(self):
        # PB12: the tilt was cleared, then the call raised.
        with fresh_world():
            s = self._sprite()
            s.tilt = 12.0
            with self.assertRaises(Exception):
                s.reset_rotation(time="soon")
            self.assertAlmostEqual(float(s.tilt), 12.0)
            s.destroy()

    def test_strip_with_a_bad_offset_adds_no_frames(self):
        # PA5: the new cells were appended, then the offset raised.
        sheet = scena.Sheet(self.small, cell=(8, 8))
        n = sheet.nframes
        with self.assertRaises(TypeError):
            sheet.strip("big", self.big, cols=2, offset="bad")
        self.assertEqual(sheet.nframes, n)

    def test_clone_refusals_build_nothing(self):
        # E9: clone(scale="x") left a live, registered clone; a dead source cloned.
        with fresh_world():
            c = scena.Circle(center=(0, 0), radius=3)
            c0 = surface_census(collect=False)
            with self.assertRaises(TypeError):
                c.clone(scale="x")
            self.assertEqual(_census_moved(c0), {})
            c.destroy()
            with self.assertRaises(DestroyedError):
                c.clone()


if __name__ == "__main__":
    unittest.main(verbosity=2)
