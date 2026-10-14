"""Signature-driven fuzz of the public surface (``scena.__all__``).

Every exported constructor and function is exercised from its signature, with
no hand-written expectations per call. Contracts (API robustness rules; Scena
Design — Numbers and signs, Construct-to-place):

* **P1 no-argument construction** — ``Kind()`` either produces a usable object
  (gradual parameters) or raises a Scena ``TypeError`` / ``ValueError`` that
  names what is missing.
* **P2 junk in any one keyword** — raises only author errors
  (``TypeError`` / ``ValueError`` / named reactive errors) with a Scena message,
  never a Python builtin one (``hypothesis_support.leak_message``).
* **P3 a rejected call leaves no trace** — ``surface_census()`` unchanged.
* **P4 unknown keyword** — ``TypeError`` naming it.
* **P5 construct then remove** — every registry returns to baseline.
* **P6 verbs on a destroyed Entity** — every public method and setter either
  raises ``DestroyedError`` or leaves no trace (no registration, no zombie).
  Generalizes H2 / S5 / S8 / S9.
* **Coverage guard** — a new export must be fuzzed or listed in
  ``surface_support.EXCLUDED`` with a reason.

    python -m unittest tests.test_hyp_surface -v
    SCENA_HYPOTHESIS_PROFILE=ci python -m unittest tests.test_hyp_surface
"""
from __future__ import annotations

import inspect
import math
import os
import sys
import unittest
import weakref

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import (  # noqa: E402
    AUTHOR_ERRORS, fresh_world, junk, leak_message, quiet,
)
from surface_support import (  # noqa: E402
    CONSTRUCTIBLE, CURSOR_KEYS, ENGINE_BUILT, EXCLUDED, GLOBAL_SETTERS, REPRESENTATIVES,
    global_diff, global_restore, global_snapshot, make_instance, census_diff, constructor_names, ctor_params,
    family_of, remove, reset_background_base, settle, surface_census,
)
from system_support import zombies  # noqa: E402
from graph_support import gc_paused  # noqa: E402
from hypothesis import given, note, settings, strategies as hst  # noqa: E402

import scena  # noqa: E402
from scena.state import DestroyedError  # noqa: E402

CENSUS_IGNORE = {"sched.every_sites"}
NAMES = constructor_names()


def _norm(v):
    if v is None:
        return 0
    if isinstance(v, float) and math.isnan(v):
        return "nan"   # nan != nan would flag every comparison
    return v


def _diff(before, after):
    return {k: v for k, v in census_diff(before, after).items()
            if k not in CENSUS_IGNORE and _norm(v[0]) != _norm(v[1])}


def _trace(before, *, cursors=True):
    """Census diff vs ``before``; collect garbage only if something moved (speed).
    ``cursors=False`` ignores widget layout cursors (construct-then-remove)."""
    d = _diff(before, surface_census(collect=False))  # unsettled on purpose: re-checked settled
    if d:
        settle()
        d = _diff(before, surface_census())
    if not cursors:
        d = {k: v for k, v in d.items() if k not in CURSOR_KEYS}
    # ``layer=0`` auto-creates numeric layer 0, which stays by design (Canvas
    # Design, "Numeric layers"); the census counts layers since review
    # 2026-10-09 (act-made layers leave with the act).
    d.pop("registry.layers", None)
    return d


_MISSING_ARG = __import__("re").compile(r"missing \d+ required (?:positional|keyword-only) argument")


def _is_author_error(exc, params=()) -> bool:
    """A Scena author error. Python's own "missing N required argument" is
    accepted when it names a real parameter of the call (clear enough).

    ``IndexError`` / ``KeyError`` are the list / dict contract of container
    verbs (``History.pop()`` on empty, ``State.remove("missing")``): accepted
    only with a Scena sentence, never a bare ``KeyError: None``."""
    if isinstance(exc, LookupError) and not isinstance(exc, AUTHOR_ERRORS):
        msg = exc.args[0] if exc.args else ""
        return isinstance(msg, str) and len(msg.split()) >= 3 and leak_message(exc) is None
    if not isinstance(exc, AUTHOR_ERRORS):
        return False
    leaked = leak_message(exc)
    if leaked is None:
        return True
    return bool(_MISSING_ARG.search(str(exc))) and any(f"'{p}'" in str(exc) for p in params)


def _describe(exc) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


# ---------------------------------------------------------------------------
# Coverage guard
# ---------------------------------------------------------------------------

# Families that are not calls to fuzz: errors and enums are types an author
# catches / names; values are singletons (canvas, st, mouse …) with their own
# suites.
NOT_CALLED_FAMILIES = {"error": "exception types", "enum": "enum types",
                       "value": "singletons (own suites)"}


class TestCoverage(unittest.TestCase):
    def test_every_export_is_fuzzed_or_excluded(self):
        missing = []
        for name in scena.__all__:
            fam = family_of(name)
            if name in EXCLUDED or fam in NOT_CALLED_FAMILIES:
                continue
            if fam in CONSTRUCTIBLE and name in NAMES:
                continue
            if fam == "callable" and name in CALLABLES:
                continue
            missing.append(f"{name} ({fam})")
        self.assertEqual(missing, [], "new exports must be fuzzed or listed in "
                         "surface_support.EXCLUDED with a reason")


# ---------------------------------------------------------------------------
# P1 / P4 / P5 — deterministic per constructor
# ---------------------------------------------------------------------------

class TestConstructors(unittest.TestCase):
    def test_no_argument_construction(self):
        for name in NAMES:
            cls = getattr(scena, name)
            with self.subTest(export=name):
                with fresh_world():
                    reset_background_base()
                    settle()
                    before = surface_census()
                    err = None
                    try:
                        with quiet():
                            obj = cls()
                    except Exception as exc:  # noqa: BLE001
                        params = [p for p, _d in ctor_params(cls)] + _init_params(cls)
                        err = (_is_author_error(exc, params), _describe(exc))
                    if err is not None:
                        # Checked after the except block: the exception's
                        # traceback keeps the half-built object alive until then.
                        self.assertTrue(err[0], f"{name}() raised {err[1]}")
                        self.assertEqual(_trace(before), {}, f"{name}() raised but left a trace")
                        continue
                    remove(obj)
                    obj = None
                    self.assertEqual(_trace(before, cursors=False), {},
                                     f"{name}() then remove: registries did not return to baseline")

    def test_unknown_keyword_is_type_error_naming_it(self):
        for name in NAMES:
            cls = getattr(scena, name)
            with self.subTest(export=name):
                with fresh_world():
                    settle()
                    before = surface_census()
                    try:
                        with quiet():
                            obj = cls(zz_not_a_knob=1)
                    except TypeError as exc:
                        self.assertIn("zz_not_a_knob", str(exc), f"{name}: {_describe(exc)}")
                    except Exception as exc:  # noqa: BLE001
                        self.fail(f"{name}(zz_not_a_knob=1) raised {_describe(exc)}")
                    else:
                        remove(obj)
                        self.fail(f"{name}(zz_not_a_knob=1) accepted an unknown keyword")
                    self.assertEqual(_trace(before), {}, f"{name}(zz_not_a_knob=1) left a trace")


# ---------------------------------------------------------------------------
# P2 / P3 — junk in one keyword, one generated test per constructor
# ---------------------------------------------------------------------------

def _junk_test(name):
    cls = getattr(scena, name)
    params = [p for p, _d in ctor_params(cls)]

    @settings(max_examples=max(4, settings().max_examples // 5))
    @given(data=hst.data())
    def test(self, data):
        if not params:
            return
        param = data.draw(hst.sampled_from(params), label="param")
        value = data.draw(junk, label="value")
        call = f"{name}({param}={value!r})"
        with fresh_world() as world:
            reset_background_base()
            # A live item already in the HUD column: alone there, a rejected
            # HUD item that took a slot is rewound by the "last participant
            # leaves" rule and its cursor move goes unseen (the deep serial
            # pass, with leftovers in the column, saw Text(glow=[]) move it).
            with quiet():
                world.track(scena.Text("column keeper"))
            settle()
            before = surface_census()
            err = None
            try:
                with quiet():
                    obj = cls(**{param: value})
            except Exception as exc:  # noqa: BLE001
                err = (_is_author_error(exc, params + _init_params(cls)), _describe(exc))
            if err is not None:   # after the except block (traceback released)
                self.assertTrue(err[0], f"{call} raised {err[1]}")
                self.assertEqual(_trace(before), {}, f"{call} raised but left a trace")
                return
            remove(obj)
            obj = None
            self.assertEqual(_trace(before, cursors=False), {},
                             f"{call} accepted; remove did not return to baseline")

    test.__doc__ = f"{name}: junk in any one keyword is an author error with no trace."
    return test


class TestConstructorJunk(unittest.TestCase):
    for _n in NAMES:
        locals()["test_" + _n] = _junk_test(_n)
    del _n


# ---------------------------------------------------------------------------
# Callables — junk as the first argument
# ---------------------------------------------------------------------------

def _param_names(fn):
    try:
        return list(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return []


def _init_params(cls):
    """Parameter names of the real ``__init__`` (published signatures may hide some)."""
    try:
        return list(inspect.signature(cls.__init__).parameters)
    except (TypeError, ValueError):
        return []


def _first_param(fn):
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return None
    for p in params:
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL):
            return p
    return None


CALLABLES = sorted(n for n in scena.__all__
                   if family_of(n) == "callable" and n not in EXCLUDED
                   and _first_param(getattr(scena, n)) is not None)


def _fill_required(fn):
    """Valid guesses for the required parameters after the first, so junk in
    the first one reaches the code instead of Python's "missing argument"
    (``set_extrude_focus(junk)`` never reached its ``float(x)``)."""
    try:
        params = list(inspect.signature(fn).parameters.values())[1:]
    except (TypeError, ValueError):
        return [], {}
    args, kwargs = [], {}
    for p in params:
        if p.default is not inspect.Parameter.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name not in _ARG_BY_NAME:
            return [], {}   # cannot guess: fall back to the bare call
        if p.kind == p.KEYWORD_ONLY:
            kwargs[p.name] = _ARG_BY_NAME[p.name]
        else:
            args.append(_ARG_BY_NAME[p.name])
    return args, kwargs


def _callable_test(name):
    fn = getattr(scena, name)

    is_global = name in GLOBAL_SETTERS

    @settings(max_examples=max(4, settings().max_examples // 5))
    @given(value=junk)
    def test(self, value):
        call = f"{name}({value!r})"
        with fresh_world():
            settle()
            before = surface_census()
            snap = global_snapshot() if is_global else None
            err = None
            try:
                try:
                    rest, kw = _fill_required(fn)
                    with quiet():
                        result = fn(value, *rest, **kw)
                except Exception as exc:  # noqa: BLE001
                    err = (_is_author_error(exc, _param_names(fn)), _describe(exc))
                if err is not None:   # after the except block (traceback released)
                    self.assertTrue(err[0], f"{call} raised {err[1]}")
                    self.assertEqual(_trace(before), {}, f"{call} raised but left a trace")
                    if is_global:
                        self.assertEqual(global_diff(snap, global_snapshot()), {},
                                         f"rejected {call} changed global state")
                    return
            finally:
                if is_global:
                    global_restore(snap)
            note(f"{call} returned {type(result).__name__}")
            # Accepted: undo what it may have registered (handles, decorators).
            cancel = getattr(result, "cancel", None)
            if callable(cancel):
                cancel()

    test.__doc__ = f"{name}: junk as the first argument is an author error."
    return test


class TestGlobalSetters(unittest.TestCase):
    """The five process-wide setters are fuzzed like any callable, inside
    ``global_snapshot`` / ``global_restore``. These pin the harness itself:
    every setter's effect is captured, and restore puts it all back (a gap
    here would leak one test's framerate / defaults into the next)."""

    # Each call moves its setting AWAY from the current value (another module
    # may already have left FX-Auto off, tracks on, …): a no-op call would
    # make "the snapshot sees the change" fail for the wrong reason.
    @staticmethod
    def _fw():
        from scena.orchestration import ScenaFramework
        return ScenaFramework.get_instance()

    VALID = {
        "set_fx_auto": lambda: scena.set_fx_auto(not TestGlobalSetters._fw()._fx_auto),
        "set_watchdog": lambda: scena.set_watchdog(
            not __import__("scena.process", fromlist=["x"]).WATCHDOG_ENABLED),
        "set_defaults": lambda: scena.set_defaults(
            "coral", line_width=5.5 if scena.set_defaults()._line_width != 5.5 else 6.5),
        "show_tracks": lambda: scena.show_tracks(
            not __import__("scena.track", fromlist=["x"])._show_tracks),
        "set_extrude_focus": lambda: scena.set_extrude_focus(
            *((3, 4) if __import__("scena.recipes", fromlist=["x"]).get_extrude_focus() != (3.0, 4.0)
              else (5, 6))),
    }

    def test_every_global_setter_has_a_valid_call(self):
        self.assertEqual(sorted(self.VALID), sorted(GLOBAL_SETTERS))
        self.assertFalse(GLOBAL_SETTERS & set(EXCLUDED))

    def test_snapshot_sees_the_change_and_restore_undoes_it(self):
        for name, call in self.VALID.items():
            with self.subTest(setter=name):
                before = global_snapshot()
                try:
                    with quiet():
                        call()
                    self.assertNotEqual(global_diff(before, global_snapshot()), {},
                                        f"{name}: snapshot missed its effect")
                finally:
                    global_restore(before)
                self.assertEqual(global_diff(before, global_snapshot()), {},
                                 f"{name}: restore left a change")


def _flag_params(fn):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    return [p.name for p in sig.parameters.values()
            if p.name not in ("self", "cls")
            and (isinstance(p.default, bool) or p.annotation in (bool, "bool"))]


class TestFlagsTakeARealBool(unittest.TestCase):
    """A12 (Testing Design; Scena Design — Numbers and signs): a flag takes a
    real bool (or 0 / 1). ``"no"`` is truthy in Python and silently switched
    ``Stars(enabled="no")`` ON; 36 flags did that. P2 cannot see it — an
    accepted value is not an error — so this walks every flag parameter."""

    BAD = ("no", 2, None, object())

    def test_every_flag_rejects_a_non_bool(self):
        checked, bad = 0, []
        for name in NAMES:
            cls = getattr(scena, name)
            for flag in _flag_params(cls):
                for value in self.BAD:
                    checked += 1
                    with fresh_world():
                        try:
                            with quiet():
                                obj = cls(**{flag: value})
                        except (TypeError, ValueError):
                            continue
                        except Exception:  # noqa: BLE001 — other required knobs
                            continue
                        remove(obj)
                        bad.append(f"{name}({flag}={value!r})")
        for name in sorted(set(CALLABLES) | GLOBAL_SETTERS):
            fn = getattr(scena, name)
            for flag in _flag_params(fn):
                for value in self.BAD:
                    checked += 1
                    snap = global_snapshot()
                    try:
                        with quiet():
                            fn(**{flag: value})
                    except (TypeError, ValueError):
                        continue
                    except Exception:  # noqa: BLE001
                        continue
                    finally:
                        global_restore(snap)
                    bad.append(f"{name}({flag}={value!r})")
        self.assertGreater(checked, 100, "vacuous: few flags found")
        self.assertEqual(bad, [])

    def test_every_flag_setter_rejects_a_non_bool(self):
        # The same contract on properties: ``shape.collidable = "no"``.
        checked, bad = 0, []
        for name in NAMES:
            with fresh_world():
                try:
                    with quiet():
                        obj = make_instance(name)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    for attr in sorted(dir(type(obj))):
                        member = inspect.getattr_static(type(obj), attr, None)
                        if attr.startswith("_") or not isinstance(member, property) \
                                or member.fset is None:
                            continue
                        try:
                            with quiet():
                                current = getattr(obj, attr)
                        except Exception:  # noqa: BLE001
                            continue
                        if not isinstance(current, bool):
                            continue
                        checked += 1
                        try:
                            with quiet():
                                setattr(obj, attr, "no")
                        except (TypeError, ValueError):
                            continue
                        bad.append(f"{name}.{attr} = 'no'")
                        with quiet():
                            setattr(obj, attr, current)
                finally:
                    remove(obj)
        self.assertGreater(checked, 100, "vacuous: few flag setters found")
        self.assertEqual(bad, [])


class TestCallableJunk(unittest.TestCase):
    for _n in CALLABLES:
        locals()["test_" + _n] = _callable_test(_n)
    del _n


# ---------------------------------------------------------------------------
# P6 — verbs on a destroyed Entity
# ---------------------------------------------------------------------------

# Argument guesses by parameter name (enough to get past arity; values that a
# live actor would accept).
_ARG_BY_NAME = {
    "x": 1.0, "y": 1.0, "dx": 1.0, "dy": 1.0, "angle": 10.0, "value": 1.0,
    "factor": 1.5, "distance": 1.0, "time": 0.1, "duration": 0.1, "delay": 0.1,
    "interval": 0.1, "name": "p6", "names": "p6", "group": "p6", "groupid": "p6",
    "text": "p6", "color": "red", "look": None, "target": (1.0, 1.0),
    "point": (1.0, 1.0), "p": (1.0, 1.0), "center": (1.0, 1.0), "about": None,
    "fn": (lambda *a: None), "callback": (lambda *a: None), "on_done": None,
    "to": 1.0, "hold": 0.1, "times": 1, "rate": 1.0, "intensity": 0.5,
    "other": None, "layer": "default", "scale": 1.0,
    "u": 0.5, "a": 0.0, "b": 1.0, "n": 3, "size": 1.0, "seed": 1, "alpha": 0.5,
    "dt": 1 / 60, "t": 0.0, "region": None, "part": None,
    "key": "a", "char": "a", "button": 1, "x_scroll": 0.0, "y_scroll": 1.0,
    "click_x": 1.0, "click_y": 1.0,
}
# Optional parameters P6 always passes: without ``fn``, ``after`` / ``every``
# return a decorator and schedule nothing (the S9 canary proved it).
_ALWAYS_PASS = {"fn"}
# Pure reads / identity: legal on a dead reference.
_READ_OK = {"contains_point", "is_alive", "tagged", "look_like", "collides_with",
            "distance_to", "clone"}


def _guess_args(method):
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return None
    args, kwargs = [], {}
    params = list(sig.parameters.values())
    if params and params[0].name in ("self", "cls"):
        params = params[1:]   # unbound function: the receiver is not an argument
    for p in params:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is not inspect.Parameter.empty and p.name not in _ALWAYS_PASS:
            continue
        if p.name not in _ARG_BY_NAME:
            return None
        if p.kind == p.KEYWORD_ONLY:
            kwargs[p.name] = _ARG_BY_NAME[p.name]
        else:
            args.append(_ARG_BY_NAME[p.name])
    return args, kwargs


ENTITY_NAMES = sorted(n for n in NAMES if family_of(n) in ("entity", "spatialfx", "widget"))


def _dead(name):
    cls = getattr(scena, name)
    try:
        with quiet():
            obj = cls()
    except Exception:
        return None
    remove(obj)
    return obj


def _dead_verbs(obj):
    """Public methods of a dead ``obj`` with guessable arguments: ``(attr, args, kwargs)``."""
    out = []
    for attr in sorted(dir(type(obj))):
        if attr.startswith("_") or attr in _READ_OK:
            continue
        member = inspect.getattr_static(type(obj), attr, None)
        if isinstance(member, property) or not callable(member):
            continue
        guess = _guess_args(getattr(type(obj), attr))
        if guess is not None:
            out.append((attr, *guess))
    return out


def _dead_methods_test(name):
    def test(self):
        with fresh_world():
            obj = _dead(name)
            if obj is None:
                return
            settle()
            base = surface_census()
            for attr, args, kwargs in _dead_verbs(obj):
                with self.subTest(method=attr):
                    try:
                        try:
                            with quiet():
                                getattr(obj, attr)(*args, **kwargs)
                        except DestroyedError:
                            continue
                        except Exception as exc:  # noqa: BLE001
                            self.assertTrue(_is_author_error(exc, _param_names(getattr(type(obj), attr))),
                                            f"dead {name}.{attr}() raised {_describe(exc)}")
                        z = [(h, type(o).__name__) for h, o in zombies() if o is obj]
                        self.assertEqual(z, [], f"dead {name}.{attr}() re-registered the actor")
                        self.assertEqual(_trace(base), {}, f"dead {name}.{attr}() left a trace")
                    finally:
                        base = surface_census()   # no cascade into later subtests

    test.__doc__ = f"{name}: every public method on a destroyed one raises DestroyedError or leaves no trace."
    return test


def _dead_setters_test(name):
    def test(self):
        with fresh_world():
            obj = _dead(name)
            if obj is None:
                return
            settle()
            base = surface_census()
            route = getattr(type(obj), "_setattr_route", {}) or {}
            for attr in sorted(route):
                desc = route[attr]
                if not hasattr(desc, "__set__") or attr.startswith("_"):
                    continue
                with self.subTest(setter=attr):
                    try:
                        with quiet():
                            current = getattr(obj, attr)
                    except Exception:  # noqa: BLE001 — a dead read may raise
                        continue
                    # Baseline AFTER the read: a read may materialize a part
                    # (``box``, ``centroid``); only the write is under test.
                    base = surface_census()
                    try:
                        try:
                            with quiet():
                                setattr(obj, attr, current)
                        except DestroyedError:
                            continue
                        except Exception as exc:  # noqa: BLE001
                            self.assertTrue(_is_author_error(exc) or isinstance(exc, AttributeError),
                                            f"dead {name}.{attr} = … raised {_describe(exc)}")
                        z = [(h, type(o).__name__) for h, o in zombies() if o is obj]
                        self.assertEqual(z, [], f"dead {name}.{attr} = … re-registered the actor")
                        self.assertEqual(_trace(base), {}, f"dead {name}.{attr} = … left a trace")
                    finally:
                        base = surface_census()

    test.__doc__ = f"{name}: every setter on a destroyed one raises DestroyedError or leaves no trace."
    return test


class TestDeadEntityVerbs(unittest.TestCase):
    """P6, one test per Entity kind and verb kind (``test_Circle_methods``,
    ``test_Circle_setters``): ``run_tiers.SPLIT`` shards the class in CHUNK
    tests; the walk over every kind in one test was the gate's longest job."""
    for _n in ENTITY_NAMES:
        locals()[f"test_{_n}_methods"] = _dead_methods_test(_n)
        locals()[f"test_{_n}_setters"] = _dead_setters_test(_n)
    del _n

    def test_verbs_are_called(self):
        # Vacuity guard: an argument-guessing bug once skipped every method.
        calls = 0
        for name in ENTITY_NAMES:
            with fresh_world():
                obj = _dead(name)
                if obj is not None:
                    calls += len(_dead_verbs(obj))
        self.assertGreater(calls, 500, f"P6 calls only {calls} dead verbs")


class TestDeadEntityLinks(unittest.TestCase):
    """P6 for ``@=`` (W2): linking any field of a destroyed actor — a slot, a
    part, or a new ink cell — raises ``DestroyedError`` and registers nothing.
    An operator, so the method / setter walks above never reached it."""

    def test_links_on_a_destroyed_entity(self):
        from scena.state import get_scena_system
        checked = 0
        src = scena.Circle(radius=1)
        self.enterContext(gc_paused())  # no collection lands between two counts (O9)
        try:
            for name in ENTITY_NAMES:
                with fresh_world():
                    obj = _dead(name)
                    if obj is None:
                        continue
                    fields = sorted(getattr(type(obj), "_setattr_route", {}) or {})
                    for field in [f for f in fields if not f.startswith("_")] + ["p6_ink"]:
                        with self.subTest(export=name, field=field):
                            graph = get_scena_system().dependency_graph
                            before = len(graph.nodes)
                            try:
                                with quiet():
                                    obj[field] @= (lambda s=src: s.radius)
                            except DestroyedError:
                                pass
                            except Exception as exc:  # noqa: BLE001 — not linkable at all
                                self.assertTrue(_is_author_error(exc) or isinstance(exc, AttributeError),
                                                f"dead {name}[{field!r}] @= raised {_describe(exc)}")
                            else:
                                self.fail(f"dead {name}[{field!r}] @= was accepted")
                            checked += 1
                            self.assertEqual(len(graph.nodes), before,
                                             f"dead {name}[{field!r}] @= grew the graph")
        finally:
            src.destroy()
        self.assertGreater(checked, 100, f"P6 links: only {checked} fields tried")


# ---------------------------------------------------------------------------
# Methods — junk as the first argument of every public method (live instance)
# ---------------------------------------------------------------------------

# Engine callbacks: the engine calls them with engine values, not the author.
_ENGINE_PREFIXES = ("on_mouse_", "on_key", "on_char", "draw", "tick")
_NOT_FUZZED = {"destroy", "setup", "update"}


def _author_words():
    """Names the author may call: spelled in the Guia, or kept public on
    purpose (``test_api_surface``). Other public names are engine hooks
    (``advance_scroll``, look ``apply``) and are not part of the contract."""
    import test_api_surface as surface
    return surface._guia_words() | surface.SURFACE_NOT_IN_GUIA


_AUTHOR_WORDS = _author_words()


def _public_methods(cls):
    out = []
    for attr in sorted(dir(cls)):
        if attr.startswith("_") or attr in _NOT_FUZZED or attr.startswith(_ENGINE_PREFIXES):
            continue
        if attr not in _AUTHOR_WORDS:
            continue
        member = inspect.getattr_static(cls, attr, None)
        if isinstance(member, (property, staticmethod, classmethod)) or not callable(member):
            continue
        fn = getattr(cls, attr)
        try:
            params = list(inspect.signature(fn).parameters.values())[1:]
        except (TypeError, ValueError):
            continue
        if params and params[0].kind in (params[0].POSITIONAL_ONLY, params[0].POSITIONAL_OR_KEYWORD):
            out.append(attr)
    return out


def _method_junk_test(name):
    cls = getattr(scena, name)
    methods = _public_methods(cls)

    @settings(max_examples=max(4, settings().max_examples // 5))
    @given(data=hst.data())
    def test(self, data):
        if not methods:
            return
        attr = data.draw(hst.sampled_from(methods), label="method")
        value = data.draw(junk, label="value")
        call = f"{name}().{attr}({value!r})"
        with fresh_world():
            reset_background_base()
            with quiet():
                obj = make_instance(name)   # no-arg or a listed representative
            try:
                settle()
                before = surface_census()
                err = None
                try:
                    with quiet():
                        getattr(obj, attr)(value)
                except DestroyedError:
                    pass   # e.g. a method that destroys, then a later step
                except Exception as exc:  # noqa: BLE001
                    err = (_is_author_error(exc, _param_names(getattr(cls, attr))), _describe(exc))
                if err is not None:   # after the except block (traceback released)
                    self.assertTrue(err[0], f"{call} raised {err[1]}")
                    self.assertEqual(_trace(before), {}, f"{call} raised but left a trace")
            finally:
                remove(obj)

    test.__doc__ = f"{name}: junk as the first argument of a public method is an author error."
    return test


def _constructible(name) -> bool:
    if name in REPRESENTATIVES:
        return True
    try:
        with fresh_world():
            with quiet():
                remove(getattr(scena, name)())
        return True
    except Exception:  # noqa: BLE001
        return False


METHOD_NAMES = sorted(n for n in NAMES
                      if n not in ENGINE_BUILT and _public_methods(getattr(scena, n))
                      and _constructible(n))


class TestMethodCoverage(unittest.TestCase):
    def test_every_class_with_author_methods_is_fuzzed(self):
        # A class whose no-arg construction fails must get a representative
        # (surface_support.REPRESENTATIVES) or be ENGINE_BUILT: otherwise the
        # methods phase silently skips it (Color was skipped until A9).
        missing = sorted(n for n in NAMES
                         if n not in ENGINE_BUILT and _public_methods(getattr(scena, n))
                         and n not in METHOD_NAMES)
        self.assertEqual(missing, [])


class TestMethodJunk(unittest.TestCase):
    for _n in METHOD_NAMES:
        locals()["test_" + _n] = _method_junk_test(_n)
    del _n

# ---------------------------------------------------------------------------
# Canaries — put a known bug back; the property must fail
# ---------------------------------------------------------------------------

def _scheduler_add_without_dead_owner_guard():
    """``Scheduler.add`` rebuilt from source minus the S9 refusal block."""
    import textwrap
    from scena import process as pr
    src = textwrap.dedent(inspect.getsource(pr.Scheduler.add))
    start = src.index("    if owner is not None and _is_entity(owner)")
    end = src.index("        return handle\n", start) + len("        return handle\n")
    ns: dict = {}
    exec(compile(src[:start] + src[end:], pr.__file__, "exec"), pr.__dict__, ns)
    return ns["add"]


class TestSurfaceCanaries(unittest.TestCase):
    def test_p3_catches_a_constructor_without_rollback(self):
        from diff_support import assert_catches
        from scena.place import _drop_failed_construct
        leaked = []
        try:
            assert_catches(self, "test_hyp_surface.TestConstructorJunk.test_Circle",
                           [("scena.place", "_drop_failed_construct", leaked.append)],
                           "a failed constructor that is not rolled back (H1)")
        finally:
            # The canary leaks half-built actors on purpose; drop them for real
            # or later modules draw a Circle with no model.
            with quiet():
                for obj in leaked:
                    _drop_failed_construct(obj)

    def test_p6_catches_work_scheduled_on_a_dead_owner(self):
        from diff_support import assert_catches
        from scena.process import Scheduler
        assert_catches(self, "test_hyp_surface.TestDeadEntityVerbs.test_Circle_methods",
                       [(Scheduler, "add", _scheduler_add_without_dead_owner_guard())],
                       "after / every on a destroyed owner (S9)")


if __name__ == "__main__":
    unittest.main()
