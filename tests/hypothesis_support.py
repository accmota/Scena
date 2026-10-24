"""Shared Hypothesis infrastructure for the property / state-machine suites.

Not a test module (no ``test_`` prefix): ``tests/test_hyp_*.py`` import it.

Profiles (pick with ``SCENA_HYPOTHESIS_PROFILE``, default ``dev``)::

    dev    — 40 examples / state-machine runs, fast enough for every suite run
    ci     — 200 examples, longer machine runs
    deep   — 2000 examples; run by hand when hunting (minutes)
    replay — no generation, only the saved failure database (fast re-check)

    SCENA_HYPOTHESIS_PROFILE=deep python -m unittest tests.test_hyp_canvas -v

Failing examples are saved in ``<repo>/.hypothesis/`` and replayed first on
the next run, so a found bug stays found until it is fixed.

What lives here:

* ``fresh_world()`` / ``WorldTracker`` — reset the global singletons
  (canvas, registry, event system, scheduler) between examples. Scena
  keeps one ``ScenaFramework`` for the whole process, so every example must
  undo what it did.
* Strategies that mirror the author's input space: finite / signed numbers,
  magnitudes, the "junk" universe (strings, None, bools, NaN, containers,
  callables), ink names, pool names for groups / ids / layers.
* ``assert_author_error`` — the robustness contract: a bad call raises
  ``TypeError`` / ``ValueError`` whose message is Scena's, not a Python
  builtin message leaking from inside the engine.
"""
from __future__ import annotations

import math
import os
import re
import string
import sys
import warnings
from contextlib import contextmanager
from typing import Any, Iterable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hypothesis import HealthCheck, Phase, settings, strategies as hst
from hypothesis.database import DirectoryBasedExampleDatabase

# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

# SCENA_HYPOTHESIS_DB=0: no example database (mutation runs: a failure under a
# mutant is not a failure of the real code and must not be replayed later).
_DB = (None if os.environ.get("SCENA_HYPOTHESIS_DB", "1") == "0"
       else DirectoryBasedExampleDatabase(os.path.join(ROOT, ".hypothesis", "examples")))
_COMMON = dict(
    database=_DB,
    # First skia / font calls are slow; timing is not what these suites test.
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    print_blob=True,
)

settings.register_profile("dev", max_examples=40, stateful_step_count=30, **_COMMON)
settings.register_profile("ci", max_examples=200, stateful_step_count=50, **_COMMON)
settings.register_profile("deep", max_examples=2000, stateful_step_count=80, **_COMMON)
settings.register_profile(
    "replay", max_examples=40, phases=[Phase.explicit, Phase.reuse], **_COMMON
)
# Canaries run a suite with a known bug patched back in: no example DB (a
# deliberate failure must not be replayed later), a fixed seed, and no shrink
# phase (a canary only needs "it failed"; shrinking a failing state machine
# costs minutes).
settings.register_profile(
    "canary", max_examples=150, stateful_step_count=30, database=None,
    derandomize=True, deadline=None,
    phases=[Phase.explicit, Phase.generate],
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
# A canary whose machine finds its plant only on some runs at 150 examples:
# the Vec2 stale-length canary missed it in the deep serial pass once the
# process had imported other modules (object addresses, not the seed, steer
# which steps the machine takes). The canary tries 150, then 300, then 600
# (``assert_catches(profile=(...))``) (2026-10-09).
settings.register_profile(
    "canary_wide", settings.get_profile("canary"), max_examples=300,
)
settings.register_profile(
    "canary_wider", settings.get_profile("canary"), max_examples=600,
)
PROFILE = os.environ.get("SCENA_HYPOTHESIS_PROFILE", "dev")
settings.load_profile(PROFILE)

# Tests of the tests (canaries, vacuity guards) re-run a whole suite with a
# fixed example budget, whatever the profile. On by default; the quick tier
# (tests/run_tiers.py) sets SCENA_CANARIES=0. They only prove a suite CAN
# fail, so they matter when a suite or the engine path it guards changes.
CANARIES = os.environ.get("SCENA_CANARIES", "1") != "0"


def require_canaries(tc) -> None:
    """Skip ``tc`` when canaries are off (``SCENA_CANARIES=0``)."""
    if not CANARIES:
        tc.skipTest("canaries off (SCENA_CANARIES=0)")


# The look intern caches: a look is built once per key and bakes some of its
# state in ``__init__`` (Metal's rim from ``_metal_edge``).
_INTERN_CACHES = (("scena.recipes", "_RECIPE_CACHE"),
                  ("scena.visuals", "_VISUAL_CACHE"),
                  ("scena.filters", "_FILTER_CACHE"))


@contextmanager
def fresh_interns() -> Iterable[None]:
    """Empty the look intern caches for a canary's plant, then put the old
    entries back. Without it a plant on a function a look calls at
    construction misses a look an earlier test interned, and a look built
    under the plant stays interned for every later test (the Metal rim
    canary after ``test_visual_color_param``, 2026-10-13)."""
    import importlib
    saved = []
    for mod_name, attr in _INTERN_CACHES:
        cache = getattr(importlib.import_module(mod_name), attr)
        saved.append((cache, dict(cache)))
        cache.clear()
    try:
        yield
    finally:
        for cache, old in saved:
            cache.clear()
            cache.update(old)

# --------------------------------------------------------------------------
# Scena bootstrap + world reset
# --------------------------------------------------------------------------

import scena  # noqa: E402  (after sys.path)
from scena import canvas, init  # noqa: E402
from scena.canvas import ScenaCanvas  # noqa: E402
from scena.events import cleanup_global_event_system  # noqa: E402
from scena.state import (  # noqa: E402
    DerivedAttributeError, LinkedAttributeError, get_scena_system,
)

_BOOTED = False
BOOT_SIZE = (400.0, 300.0)   # the design size a test process starts from


def boot() -> None:
    """``init`` once per process (design size only; no window)."""
    global _BOOTED
    if not _BOOTED:
        init(width=BOOT_SIZE[0], height=BOOT_SIZE[1])
        _BOOTED = True


def registry():
    return ScenaCanvas.get_current().registry


def roster_mark() -> int:
    """The newest roster key so far; pair with ``new_in_roster``."""
    return registry()._next_key


def new_in_roster(mark: int) -> list:
    """Items registered after ``mark`` (keys are serials, never reused), parts included.

    Compare this, not ``len(registry().live)``: the roster is weak, so an
    unrelated dropped actor can leave it at any allocation. A failed
    constructor retires its Point parts too (``Registry.retire_part``).
    """
    return [o for k, o in list(registry().live.items()) if k > mark]


def reset_globals() -> None:
    """Drop author-global state that survives an example.

    Order matters: end a frame batch before cleaning events so a pending
    flush does not run against a half-torn-down world.
    """
    ss = get_scena_system()
    if ss is not None and ss.update_manager.deferring:
        ss.end_frame_batch()
    cleanup_global_event_system()
    from scena.process import reset_process_scheduler
    reset_process_scheduler()
    try:
        registry().clear_group_formulas()
    except Exception:
        pass
    canvas.layers.default = "default"


class WorldTracker:
    """Records what an example created so ``teardown`` can remove exactly that.

    Objects created by other test modules may already sit on ``default``;
    the tracker never touches them, and invariants filter to tracked objects.
    """

    def __init__(self) -> None:
        boot()
        reset_globals()
        scrub_pools()
        self.objects: List[Any] = []
        self.layers_before = set(canvas.layers)

    def track(self, obj):
        self.objects.append(obj)
        return obj

    def teardown(self, *, strict: bool = True) -> None:
        """Destroy what the example made, drop its layers, reset globals.

        ``strict``: a tracked object that is still alive afterwards raises
        ``AssertionError`` (after cleanup finishes). It survives into every
        later module on ``default`` — a junk write that left it undestroyable
        (``circle.owner = 1.0`` once did) then crashes an unrelated draw test
        in the deep tier's serial pass.
        """
        survivors = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ss = get_scena_system()
            if ss is not None and ss.update_manager.deferring:
                ss.end_frame_batch()
            for obj in reversed(self.objects):
                if not hasattr(obj, "is_alive"):
                    continue                    # not an Entity (Contrail, …)
                try:
                    if obj.is_alive:
                        obj.on_destroy = None
                        obj.destroy()
                except Exception as exc:  # noqa: BLE001 — reported below
                    survivors.append((obj, exc))
            survivors = [(o, e) for o, e in survivors if _still_alive(o)]
            self.objects.clear()
            for name in list(canvas.layers):
                if name in self.layers_before:
                    continue
                try:
                    registry().layers[name].delete(destroy_shapes=True)
                except Exception:
                    pass
            scrub_pools()
            reset_globals()
        if strict and survivors:
            raise AssertionError(
                "teardown could not destroy what the example made; it leaks "
                "into every later test:\n" + "\n".join(
                    f"  {type(o).__name__}: {type(e).__name__}: {e}"
                    for o, e in survivors))


def _still_alive(obj) -> bool:
    try:
        return bool(obj.is_alive)
    except Exception:  # noqa: BLE001 — a broken object counts as alive
        return True


def scrub_pools() -> None:
    """Force the pool names (groups, ids, custom layers) back to empty.

    Belt and braces: a bug under test (a zombie object that survived
    ``destroy``, a half-built constructor) must not leak into the next
    example, or Hypothesis reports a flaky test instead of the bug.
    """
    sc = registry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for g in GROUP_POOL:
            bucket = sc.group_map.get(g)
            for obj in list(bucket or ()):
                try:
                    obj.on_destroy = None
                except Exception:
                    pass
                try:
                    obj.destroy()
                except Exception:
                    pass
                sc.remove_from_group(obj, g)
        for name in LAYER_POOL:
            layer = sc.layers.get(name)
            if layer is None:
                continue
            layer._compact()
            for obj in list(layer._objects):
                try:
                    obj.destroy()
                except Exception:
                    pass
            layer._objects.clear()
            layer._tombstones = 0
            try:
                sc.layers.delete(name)
            except Exception:
                pass


@contextmanager
def fresh_world():
    """Context manager form for ``@given`` bodies."""
    world = WorldTracker()
    try:
        yield world
    except BaseException:
        world.teardown(strict=False)    # never mask the body's own failure
        raise
    world.teardown()


@contextmanager
def quiet():
    """Silence Scena's RuntimeWarnings (relink, unknown colour) inside a call."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


# --------------------------------------------------------------------------
# The author-error contract
# --------------------------------------------------------------------------

# Numbers rule / typo guards raise TypeError / ValueError; the reactive guards
# raise their own named types (not subclasses of either).
AUTHOR_ERRORS = (TypeError, ValueError, LinkedAttributeError, DerivedAttributeError)

# Python's own messages. When one of these reaches the author, the value got
# past Scena's validators and failed somewhere inside the engine — the
# "engine errors reaching the author" bug class of the robustness plan.
_LEAK_PATTERNS = [
    r"could not convert",
    r"unsupported operand type",
    r"object is not subscriptable",
    r"object is not iterable",
    r"object is not callable",
    r"has no attribute",
    r"^float\(\) argument must be",
    r"^int\(\) argument must be",
    r"must be real number, not",
    r"cannot unpack non-iterable",
    r"not enough values to unpack",
    r"too many values to unpack",
    r"'[<>]=?' not supported between",
    r"unhashable type",                 # graphics review HP6: hb.tagged(["a"])
    r"has no len\(\)",                  # SC9: Polygon(points=<generator>)
    r"int too large to convert",        # SA15: angle = 10**400
    r"codec can't decode",              # PA8: a binary file as atlas=
    r"indices must be integers",
    r"math domain error",
    r"cannot convert float NaN to integer",
    r"cannot convert float infinity to integer",
    r"can't multiply sequence",
    r"can only concatenate",
    r"takes \d+ positional argument",
    r"missing \d+ required positional argument",
]
_LEAK_RE = re.compile("|".join(_LEAK_PATTERNS))


def leak_message(exc: BaseException) -> Optional[str]:
    """The matching builtin pattern if ``exc`` looks like an engine leak."""
    m = _LEAK_RE.search(str(exc))
    return m.group(0) if m else None


def assert_author_error(testcase, exc: BaseException, *, call: str,
                        allowed=AUTHOR_ERRORS) -> None:
    """Fail unless ``exc`` is an allowed type with a Scena-written message."""
    if not isinstance(exc, allowed):
        testcase.fail(
            f"{call} raised {type(exc).__name__}: {exc!s} — "
            f"expected one of {[t.__name__ for t in allowed]}"
        )
    leaked = leak_message(exc)
    if leaked:
        testcase.fail(
            f"{call} leaked an engine error ({type(exc).__name__}: {exc!s}); "
            f"the message is Python's ({leaked!r}), not Scena's"
        )


def call_as_author(testcase, fn, *args, call: str, allowed=AUTHOR_ERRORS, **kwargs):
    """Run ``fn``; return ``(ok, result_or_exc)`` after checking any error."""
    try:
        with quiet():
            result = fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 — classified below
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        assert_author_error(testcase, exc, call=call, allowed=allowed)
        return False, exc
    return True, result


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

# Coordinates in a sane design range; float arithmetic stays exact enough for
# round-trip checks with a tolerance.
coords = hst.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
small_coords = hst.integers(min_value=-500, max_value=500).map(float)
points = hst.tuples(coords, coords)
magnitudes = hst.floats(min_value=0.0, max_value=1e4, allow_nan=False, allow_infinity=False)
positive_magnitudes = hst.floats(min_value=0.5, max_value=1e4, allow_nan=False,
                                 allow_infinity=False)
negative_numbers = hst.floats(max_value=-1e-6, min_value=-1e6, allow_nan=False,
                              allow_infinity=False)
angles = hst.floats(min_value=-720.0, max_value=720.0, allow_nan=False,
                    allow_infinity=False)
non_finite = hst.sampled_from([math.nan, math.inf, -math.inf])
durations = hst.floats(min_value=0.01, max_value=100.0, allow_nan=False,
                       allow_infinity=False)


def _a_function():
    return lambda: 3


# Values an author might pass where a number goes, that are not numbers.
not_numbers = hst.one_of(
    hst.text(max_size=8),
    hst.sampled_from(["10", "big", "", " ", "1e3", "nan", "inf"]),
    hst.none(),
    hst.booleans(),
    hst.lists(hst.integers(), max_size=3),
    hst.tuples(hst.integers(), hst.integers()),
    hst.dictionaries(hst.text(max_size=2), hst.integers(), max_size=2),
    hst.complex_numbers(allow_nan=False, allow_infinity=False, max_magnitude=10),
    hst.just(object()),
    hst.builds(_a_function),
)

# Anything at all an author might write in an argument slot.
junk = hst.one_of(
    not_numbers,
    non_finite,
    hst.integers(min_value=-10**6, max_value=10**6),
    hst.floats(allow_nan=True, allow_infinity=True),
)

# Anything that is *not* a valid 2D point.
not_points = hst.one_of(
    not_numbers.filter(lambda v: not (isinstance(v, tuple) and len(v) == 2)),
    hst.tuples(coords),
    hst.tuples(coords, coords, coords),
    hst.tuples(non_finite, coords),
    hst.tuples(coords, not_numbers.filter(lambda v: not isinstance(v, tuple))),
    hst.integers(),
    non_finite,
)

# Author-style identifiers for ink names: lower snake case.
ink_names = hst.from_regex(r"[a-z][a-z_]{1,10}", fullmatch=True).filter(
    lambda s: not s.endswith("_") and "__" not in s
)

# Small name pools so collisions (same group, same layer) actually happen.
GROUP_POOL = ["hyp_g1", "hyp_g2", "hyp_g3"]
LAYER_POOL = ["hyp_bg", "hyp_mid", "hyp_fx"]
group_names = hst.sampled_from(GROUP_POOL)
custom_layer_names = hst.sampled_from(LAYER_POOL)
numeric_layers = hst.integers(min_value=-5, max_value=12)

key_like_text = hst.one_of(
    hst.text(alphabet=string.ascii_letters + string.digits + "+_- ", max_size=12),
    hst.sampled_from([
        "ESC", "ESCAPE", "SPACE", "SPACEBAR", "LEFT", "left", "A", "a",
        "ctrl+a", "CTRL+SHIFT+A", "shift+", "+", "", "F1", "F13", "ENTER",
        "RETURN", "UP", "arrow_up", "CONTROL", "option+a", "LALT",
    ]),
)


def approx_equal(a: float, b: float, *, rel: float = 1e-9, abs_tol: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_tol)


def xy(p) -> tuple:
    """(x, y) of a Point / Vec2 / tuple."""
    if isinstance(p, tuple):
        return float(p[0]), float(p[1])
    return float(p.x), float(p.y)


def live(objs: Iterable[Any]) -> List[Any]:
    return [o for o in objs if getattr(o, "is_alive", False)]
