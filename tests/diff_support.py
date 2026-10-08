"""Shared helpers for the differential suites (``tests/test_diff_*.py``).

Not a test module. A differential test runs the **same** author actions down an
optimized path and down its reference path, then compares what an author (or
the engine) can observe. See ``design/Testing Design.md`` — Strategy.

* ``make_twins(factory)`` — two identical actors; twin B is forced onto the
  slow / batched path for good (``_flag_pull_consumers``: sticky, adds no
  links, sends every later Defining write through ``takein`` / ``mark_dirty``).
  ``assert_fast(a)`` guards against a vacuous pass: twin A must still be on
  the fast path when the comparison runs.
* ``fingerprint(obj)`` — observable pose + geometry read with **engine-side**
  readers that keep Derivates cold (``_center_xy``, bare rotation / scale,
  uncached collision prims), so reading the fast twin does not knock it off
  the fast path.
* ``assert_same(tc, fa, fb, what)`` — tolerant structural compare that names
  the first field that differs.
* ``assert_same_prims(tc, got, want, what)`` — collision prims as a multiset:
  pairs by nearest match, never by sorting raw floats (D10).

Per-pair oracle rules (exact vs tolerance, ignored ties) live next to each
suite's docstring; the defaults here are ``REL = 1e-9`` / ``ABS = 1e-7``.
"""
from __future__ import annotations

import math
import os
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import boot, quiet, require_canaries  # noqa: E402

REL = 1e-9
ABS = 1e-7


# --------------------------------------------------------------------------
# Twins
# --------------------------------------------------------------------------

def force_slow(obj) -> None:
    """Send every later write on ``obj`` down the batched / invalidating path."""
    obj._flag_pull_consumers()


def is_fast(obj) -> bool:
    return not obj._requires_pull_invalidate()


def make_twins(factory: Callable[[], Any]) -> Tuple[Any, Any]:
    with quiet():
        a = factory()
        b = factory()
    force_slow(b)
    return a, b


# --------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------

def _num(v) -> float:
    from scena.shapes import _bare_num
    return float(_bare_num(v))


def _round(x):
    if isinstance(x, float):
        return x
    if isinstance(x, (list, tuple)):
        return tuple(_round(v) for v in x)
    return x


def prims_of(obj) -> tuple:
    """Uncached world collision prims: kind + aabb + params + verts."""
    from scena.collision import _snapshot_shape_uncached
    out = []
    for p in _snapshot_shape_uncached(obj, cache_owner=None):
        out.append((p.kind.name, tuple(p.aabb), tuple(p.params),
                    tuple(tuple(v) for v in (p.verts or ()))))
    return tuple(out)


def fingerprint(obj) -> dict:
    """Pose + geometry, read without warming Derivates."""
    fp = {}
    cxy = getattr(obj, "_center_xy", None)
    if cxy is not None:
        fp["center"] = tuple(float(v) for v in cxy())
    d = obj.__dict__ if hasattr(obj, "__dict__") else {}
    rot = d.get("_rotation")
    if rot is None:
        try:
            rot = object.__getattribute__(obj, "_rotation")
        except AttributeError:
            rot = None
    if rot is None and "angle" in getattr(type(obj), "_setattr_route", {}):
        rot = obj.angle
    if rot is not None:
        fp["angle"] = _num(rot)
    try:
        fp["scale"] = float(object.__getattribute__(obj, "_scale"))
    except AttributeError:
        pass
    for flag in ("_flip_x", "_flip_y"):
        try:
            fp[flag] = bool(object.__getattribute__(obj, flag))
        except AttributeError:
            pass
    fp["prims"] = prims_of(obj)
    return fp


def _close(a: float, b: float, rel: float, abs_: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def diff_values(a: Any, b: Any, path: str = "", rel: float = REL,
                abs_: float = ABS) -> List[str]:
    """Paths where ``a`` and ``b`` differ (numbers with tolerance)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a == b else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if _close(float(a), float(b), rel, abs_) else [f"{path}: {a!r} != {b!r}"]
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: only in {'b' if k not in a else 'a'}")
            else:
                out.extend(diff_values(a[k], b[k], f"{path}.{k}", rel, abs_))
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff_values(x, y, f"{path}[{i}]", rel, abs_))
        return out
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def assert_same(tc, a: Any, b: Any, what: str = "", rel: float = REL,
                abs_: float = ABS) -> None:
    diffs = diff_values(a, b, "", rel, abs_)
    if diffs:
        tc.fail(f"fast and slow paths diverge{(' after ' + what) if what else ''}: "
                + "; ".join(diffs[:6]) + (" …" if len(diffs) > 6 else ""))


def _prim_row(p) -> tuple:
    return (p.kind.name, tuple(p.aabb), tuple(p.params),
            tuple(tuple(v) for v in (p.verts or ())))


def _flat(x) -> List[float]:
    if isinstance(x, (list, tuple)):
        return [v for item in x for v in _flat(item)]
    return [float(x)] if isinstance(x, (int, float)) and not isinstance(x, bool) else []


def _row_gap(a: tuple, b: tuple) -> float:
    """Largest numeric gap between two prim rows; ``inf`` if not comparable."""
    if a[0] != b[0]:
        return math.inf
    fa, fb = _flat(a[1:]), _flat(b[1:])
    if len(fa) != len(fb):
        return math.inf
    return max((abs(x - y) for x, y in zip(fa, fb)), default=0.0)


def pair_prims(got, want) -> Tuple[list, list]:
    """Rows of ``got`` reordered to line up with ``want`` (nearest match).

    Prim order is not part of the collision contract, and sorting raw floats
    is not a canonical order: an ulp of translate drift reorders prims that tie
    on the first sort fields (D10). Pair each wanted prim with the closest
    unused one of the same kind; leftovers keep their order so a count or kind
    mismatch still shows up as a diff.
    """
    g = [_prim_row(p) for p in got]
    w = [_prim_row(p) for p in want]
    free = list(range(len(g)))
    out = []
    for row in w:
        if not free:
            break
        best = min(free, key=lambda i: _row_gap(g[i], row))
        out.append(g[best])
        free.remove(best)
    out.extend(g[i] for i in free)
    return out, w


def assert_same_prims(tc, got, want, what: str = "", rel: float = REL,
                      abs_: float = ABS) -> None:
    """``got`` and ``want`` hold the same prims (any order), within tolerance."""
    g, w = pair_prims(got, want)
    assert_same(tc, g, w, what, rel=rel, abs_=abs_)


def assert_fast(tc, obj, what: str = "") -> None:
    """The comparison is only meaningful while twin A is still on the fast path."""
    if not is_fast(obj):
        tc.fail(f"twin A left the fast path{(' after ' + what) if what else ''} — "
                "the differential would compare slow vs slow")


# --------------------------------------------------------------------------
# Global switches
# --------------------------------------------------------------------------

@contextmanager
def module_flag(module_name: str, attr: str, value) -> Iterator[None]:
    """Temporarily set a module global (patch the real module, not a facade:
    ``scena.collision`` / ``scena.canvas`` / ``scena.audio`` are shadowed)."""
    mod = sys.modules[module_name]
    old = getattr(mod, attr)
    setattr(mod, attr, value)
    try:
        yield
    finally:
        setattr(mod, attr, old)


def assert_catches(tc, test_id: str, patches, what: str) -> None:
    """Canary: run ``test_id`` (``module.Class.method``) with ``patches`` applied
    and require it to FAIL. ``patches`` is a list of ``(target, attr, value)``;
    a ``str`` target is a module name patched through ``sys.modules``
    (facade-safe), anything else (a class) is patched directly.

    Runs under the ``canary`` Hypothesis profile (no DB, fixed seed).
    Skipped when ``SCENA_CANARIES=0`` (the quick tier).
    """
    require_canaries(tc)
    import unittest
    from unittest import mock
    from hypothesis import settings as hsettings
    stack = []
    previous = hsettings.get_current_profile_name()
    hsettings.load_profile("canary")
    try:
        for target, attr, value in patches:
            owner = sys.modules[target] if isinstance(target, str) else target
            p = mock.patch.object(owner, attr, value)
            p.start()
            stack.append(p)
        # Run a fresh private copy of the test module: re-running the SAME
        # @given function from another TestCase instance trips Hypothesis's
        # differing_executors check on the suite's own later run.
        import importlib.util
        mod_name, _, rest = test_id.partition(".")
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), mod_name + ".py")
        spec = importlib.util.spec_from_file_location(f"_canary_{mod_name}", path)
        copy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(copy)
        suite = unittest.defaultTestLoader.loadTestsFromName(rest, copy)
        result = unittest.TestResult()
        suite.run(result)
    finally:
        for p in reversed(stack):
            p.stop()
        hsettings.load_profile(previous)
    if result.wasSuccessful():
        tc.fail(f"canary: {test_id} did not catch {what}")


boot()
