"""A destroyed actor refuses first: every verb that refuses a destroyed actor
with good arguments raises ``DestroyedError`` with bad ones too (DV1 in
Testing Design).

The bug class: a verb checks its arguments, then the dead receiver, so
``dead.move_to((nan, 0))`` said "a point takes two finite numbers" and sent the
author after the number, when the number does not matter (the actor is gone).
VB15 was the same order bug on a dead part's in-place Vec2 ops.

The walk reuses P6's enumeration (``test_hyp_surface``: every Entity kind ×
every public method, arguments guessed by name). A verb is *refusing* when a
call with good arguments raises ``DestroyedError``; each of its parameters
then takes each junk value, one at a time, and the call must still raise
``DestroyedError``. Verbs that do not refuse (reads, no-ops that leave no
trace) are P6's business.

    python tests/run_tiers.py focused test_dead_verb_order
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_hyp_surface as p6  # noqa: E402
from hypothesis_support import fresh_world, quiet  # noqa: E402

import scena  # noqa: E402
from scena.process import Handle, _R_DEAD_AT_START, get_scheduler  # noqa: E402
from scena.state import DestroyedError  # noqa: E402

# One value per refusal the verbs make: not finite, too big for a float, the
# wrong type, a flag where a number goes, a point of the wrong length, a
# function (a link) where a value goes.
JUNK = (
    math.nan, math.inf, -math.inf, 10 ** 400, "p6", True,
    (1.0,), (1.0, 2.0, 3.0), object(), (lambda: 0.0),
)


# Good values by name, for a parameter the base call leaves out: P6's guesses
# and ``speed=`` (a timed call at a rate).
_GOOD = {**p6._ARG_BY_NAME, "speed": 10.0}


def _params(fn):
    return [p for p in inspect.signature(fn).parameters.values()
            if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]


def _bases(fn, params):
    """Calls with good arguments: P6's guess (required parameters only); every
    leading positional filled by name (``move_to(1.0, 1.0)``: P6's guess for it
    is ``move_to()``); each of those with ``time=`` (the timed path)."""
    out = []
    guess = p6._guess_args(fn)
    if guess is not None:
        out.append(guess)
    lead = []
    for p in params:
        if p.kind == p.KEYWORD_ONLY or p.name not in p6._ARG_BY_NAME:
            break
        lead.append(p6._ARG_BY_NAME[p.name])
    if lead:
        out.append((lead, {}))
    if any(p.name == "time" for p in params):
        out += [(args, {**kwargs, "time": 0.1}) for args, kwargs in list(out)]
    return out


def _refuses(fn, args, kwargs) -> bool:
    try:
        with quiet():
            fn(*args, **kwargs)
    except DestroyedError:
        return True
    except Exception:  # noqa: BLE001 — not a refusing call (P6 judges it)
        return False
    return False


def _with_junk(params, i, args, kwargs, value):
    p = params[i]
    args, kwargs = list(args), dict(kwargs)
    if p.kind != p.KEYWORD_ONLY and i < len(args):
        args[i] = value
    elif p.kind == p.POSITIONAL_ONLY:
        return None
    else:
        kwargs[p.name] = value
    return args, kwargs


def _call_junk(fn, a, k):
    """What a junk call raised, or ``None`` when it raised ``DestroyedError``."""
    try:
        with quiet():
            fn(*a, **k)
    except DestroyedError:
        return None
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:90]}"
    return "accepted"


def _walk_verbs(name, obj, verbs, bad):
    for attr in sorted(dir(type(obj))):
        if attr.startswith("_") or attr in p6._READ_OK:
            continue
        member = inspect.getattr_static(type(obj), attr, None)
        if isinstance(member, property) or not callable(member):
            continue
        fn = getattr(obj, attr)
        try:
            params = _params(fn)
        except (TypeError, ValueError):
            continue
        for args, kwargs in _bases(fn, params):
            if not _refuses(fn, args, kwargs):
                continue
            verbs.add(attr)
            calls = []
            if all(p.default is not inspect.Parameter.empty for p in params):
                calls.append(("(no arguments)", None, [], {}))   # ``dead.move_to()``
            for i in range(len(params)):
                p = params[i]
                if p.name in _GOOD and p.name not in kwargs and not (
                        p.kind != p.KEYWORD_ONLY and i < len(args)):
                    # A parameter that picks another path: ``time=`` on a verb
                    # whose timed call on a dead actor returns a cancelled
                    # Handle (T6). With a good value that call does not refuse,
                    # so a bad one is P6's business, not this order rule's.
                    twin = _with_junk(params, i, args, kwargs, _GOOD[p.name])
                    if twin is not None and not _refuses(fn, *twin):
                        continue
                for value in JUNK:
                    call = _with_junk(params, i, args, kwargs, value)
                    if call is not None:
                        calls.append((params[i].name, value, *call))
            for pname, value, a, k in calls:
                got = _call_junk(fn, a, k)
                if got is not None:
                    bad.append((f"{attr}({pname}=…)", value, got))


def _walk_setters(obj, setters, bad):
    """A setter refuses when writing back what it reads raises ``DestroyedError``
    (P6's call); then every junk value must too (``dead.x = lambda: 0`` said
    "use @=" first)."""
    route = getattr(type(obj), "_setattr_route", {}) or {}
    for attr in sorted(route):
        if attr.startswith("_") or not hasattr(route[attr], "__set__"):
            continue
        try:
            with quiet():
                current = getattr(obj, attr)
        except Exception:  # noqa: BLE001 — a dead read may raise
            continue
        assign = lambda v, attr=attr: setattr(obj, attr, v)   # noqa: E731
        if not _refuses(assign, (current,), {}):
            continue
        setters.add(attr)
        for value in JUNK:
            got = _call_junk(assign, (value,), {})
            if got is not None:
                bad.append((f"{attr} = …", value, got))


def _walk(name):
    """``(refusing verbs, refusing setters, failures)`` for one kind: a failure
    is ``(call, junk, what it raised)``."""
    verbs, setters, bad = set(), set(), []
    with fresh_world():
        obj = p6._dead(name)
        if obj is not None:
            _walk_verbs(name, obj, verbs, bad)
            _walk_setters(obj, setters, bad)
    return verbs, setters, bad


class TestADestroyedActorRefusesFirst(unittest.TestCase):
    """DV1: on a destroyed actor, a bad argument or value never hides the
    ``DestroyedError`` of a verb or setter that refuses it (one test per
    Entity kind)."""
    maxDiff = None
    for _n in p6.ENTITY_NAMES:
        def _test(self, name=_n):
            _, _, bad = _walk(name)
            seen = {}
            for call, value, got in bad:
                seen.setdefault(call, (value, got))
            self.assertEqual(
                [f"dead {name}.{c} with {v!r:.30} raised {g}" for c, (v, g) in sorted(seen.items())],
                [], f"dead {name}: a bad argument hid the DestroyedError")
        _test.__doc__ = f"{_n}: every refusing verb and setter refuses first, whatever the value."
        locals()[f"test_{_n}"] = _test
    del _n, _test

    def test_the_walk_reaches_the_verbs(self):
        # Vacuity guard: the walk finds the pose verbs on the kinds the bug was
        # found on, and hundreds of refusing verbs and setters in all.
        verbs_n = setters_n = 0
        for name in p6.ENTITY_NAMES:
            verbs, setters, _ = _walk(name)
            verbs_n += len(verbs)
            setters_n += len(setters)
            if name in ("Circle", "Rect", "Sprite", "Text"):
                for verb in ("move_to", "move_by", "rotate_to", "rotate_by",
                             "scale_to", "scale_by", "reset_rotation", "add_to_group"):
                    self.assertIn(verb, verbs, f"{name}.{verb} not walked")
                for setter in ("center", "angle", "visible"):
                    self.assertIn(setter, setters, f"{name}.{setter} = … not walked")
        self.assertGreater(verbs_n, 300, f"DV1 walks only {verbs_n} refusing verbs")
        self.assertGreater(setters_n, 2000, f"DV1 walks only {setters_n} refusing setters")


# The timed verbs, with good arguments; ``move_along`` gets a fresh Track.
_TIMED = (
    ("move_to", lambda: ((5.0, 5.0), {"time": 0.1})),
    ("move_by", lambda: ((5.0, 5.0), {"time": 0.1})),
    ("move_to", lambda: ((5.0, 5.0), {"speed": 10.0})),
    ("rotate_to", lambda: ((30.0,), {"time": 0.1})),
    ("rotate_by", lambda: ((30.0,), {"time": 0.1})),
    ("scale_to", lambda: ((2.0,), {"time": 0.1})),
    ("scale_by", lambda: ((2.0,), {"time": 0.1})),
    ("move_along", lambda: ((scena.Track.line(100.0),), {"time": 0.1})),
)


class TestATimedVerbOnTheDeadComesBackCancelled(unittest.TestCase):
    """DV3, law T6: a timed move, turn or scale on a destroyed actor returns an
    already-cancelled Handle that was never registered, on every kind. A
    timed ``scale_to`` / ``scale_by`` and a Point's timed moves raised
    ``DestroyedError`` from their call-time writability probe instead, while
    Actors Design promised the Handle."""

    def test_every_kind_every_timed_verb(self):
        reached = set()
        for name in p6.ENTITY_NAMES + ["Point"]:
            for verb, args in _TIMED:
                with fresh_world():
                    if name == "Point":
                        obj = scena.Point(1.0, 1.0)
                        obj.destroy()
                    else:
                        obj = p6._dead(name)
                    fn = getattr(obj, verb, None) if obj is not None else None
                    if fn is None:
                        continue
                    a, k = args()
                    with self.subTest(kind=name, verb=verb, kwargs=k):
                        before = len(get_scheduler()._handles)
                        try:
                            with quiet():
                                h = fn(*a, **k)
                        except TypeError as exc:
                            # The pose verbs' signatures hide ``time=`` (a
                            # wrapper takes it), so the call is the test: skip
                            # only a kind without the timed form.
                            if "unexpected keyword" in str(exc):
                                continue
                            raise
                        self.assertIsInstance(h, Handle)
                        self.assertTrue(h.cancelled)
                        self.assertEqual(getattr(h, "_cancel_reason", None), _R_DEAD_AT_START)
                        self.assertEqual(len(get_scheduler()._handles), before, "registered work for the dead")
                        reached.add((name, verb))
        # Vacuity: the kinds the bug was found on.
        for pair in (("Circle", "scale_to"), ("Rect", "scale_by"), ("Point", "move_to"),
                     ("Point", "move_by"), ("Point", "move_along")):
            self.assertIn(pair, reached)

    def test_an_instant_verb_still_refuses(self):
        # The cancelled Handle is for timed work only: an instant change on the
        # dead raises, whatever the argument (DV1).
        with fresh_world():
            c = scena.Circle()
            c.destroy()
            for call in (lambda: c.scale_to(2.0), lambda: c.scale_to(math.nan),
                         lambda: c.move_to(5.0, 5.0)):
                with self.assertRaises(DestroyedError):
                    call()
            p = scena.Point(1.0, 1.0)
            p.destroy()
            with self.assertRaises(DestroyedError):
                p.move_by(1.0, 0.0)


class TestADeadTrackStillReads(unittest.TestCase):
    """DV2: reads on a destroyed Track work (reads stay legal on the dead). The
    first read of a never-sampled track builds its tables, and the refresh
    published ``length`` through the dead route map: ``at`` raised "Track.length
    cannot change a destroyed object"."""

    def _reads(self, t):
        return {
            "at": t.at(0.5), "local_at": t.local_at(0.5), "tangent_at": t.tangent_at(0.5),
            "angle_at": t.angle_at(0.5), "sample_span": t.sample_span(0.0, 1.0, 4),
            "spaced_points": t.spaced_points(3), "length": t.length,
        }

    def test_cold_and_dirty_dead_tracks_read_like_a_live_twin(self):
        with fresh_world():
            for make in (scena.Track, scena.Track.eight, lambda: scena.Track.line(100.0)):
                for dirty in (False, True):
                    live, dead = make(), make()
                    if dirty:
                        for t in (live, dead):
                            t.at(0.5)
                            t.scale = 2.0    # the tables rebuild on the next read
                    dead.destroy()           # a cold one never built them
                    with self.subTest(make=make, dirty=dirty):
                        self.assertEqual(self._reads(dead), self._reads(live))


if __name__ == "__main__":
    unittest.main()
