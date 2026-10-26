"""What a test module leaves alive on the shared canvas, and the sweep that
destroys it.

Not a test module (no ``test_`` prefix). Scena keeps one canvas per process:
an actor a module builds and never destroys stays on the draw lists for every
later module of the deep tier's serial pass (one process over every module).
Each later ``census`` / ``full_collect`` walks it, and every ``SystemWorld``
parks and resumes it. So a module destroys what it made::

    from tests.leftovers import module_sweep  # noqa: E402
    setUpModule, tearDownModule = module_sweep()

``tests/run_tiers.py`` checks every module of every tier (``LeftoverCheck``): a
module that leaves one live actor it made fails, and so does one that leaves
more than ``LIMIT`` parts (a part an import-time actor made lazily). Testing
Design, "Harness pitfalls".
"""
from __future__ import annotations

import gc
import sys
import unittest
import warnings
from collections import Counter
from typing import Any, List, Optional, Tuple

# Parts a module may leave behind: lazy parts of the actors it made at import
# (those are its fixtures, made before the mark). Actors: none (WP43).
LIMIT = 50

Mark = Tuple[Optional[Any], int]  # (registry, newest key) — keys are serials


def _current_canvas():
    """The current canvas, or None (no canvas, or Scena not loaded: a module
    that never imported Scena made nothing)."""
    canvas = sys.modules.get("scena.canvas")
    if canvas is None:
        return None
    try:
        return canvas.ScenaCanvas.get_current()
    except RuntimeError:
        return None


def _registry():
    """The current canvas's registry, or None."""
    cv = _current_canvas()
    return cv.registry if cv is not None else None


def _framework_singleton(obj) -> bool:
    """A framework singleton (``_scena_internal``: the HUD labels the first
    ``begin_game`` builds, once per process) is the framework's, not the
    module's that happened to begin a game first."""
    try:
        return bool(object.__getattribute__(obj, "_scena_internal"))
    except AttributeError:
        return False
    except Exception:  # noqa: BLE001 — a half-built item is not a singleton
        return False


def mark() -> Mark:
    """Where the roster stands now; pair with ``made_since``."""
    reg = _registry()
    return (reg, reg._next_key if reg is not None else 0)


def made_since(at: Mark) -> List[Any]:
    """Live roster items registered after ``at``, oldest first.

    A canvas that replaced the one at ``at`` counts whole: everything on it is
    newer, except the canvas's own boundary rect. Framework singletons never
    count. The roster is weak, so
    unreachable garbage can still be listed until the next GC pass.
    """
    cv = _current_canvas()
    if cv is None:
        return []
    reg = cv.registry
    since = at[1] if reg is at[0] else 0
    # The canvas's own boundary rect (``canvas_rect``) is the canvas's, not
    # the module's: a module that made a new canvas did not leave it.
    own = getattr(cv, "canvas_rect", None)
    items = [(k, o) for k, o in list(reg.live.items())
             if k > since and o is not own and not _framework_singleton(o)]
    items.sort(key=lambda kv: kv[0])
    return [o for _k, o in items]


def sweep(at: Mark) -> None:
    """Destroy every actor registered after ``at``, newest first (an owner
    before its parts: parts leave with it).

    Raises ``AssertionError`` when an actor survives ``destroy`` (it would leak
    into every later module); the message names it.
    """
    from scena.entity import is_part
    from scena.state import get_scena_system

    failed = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ss = get_scena_system()
        if ss is not None and ss.update_manager.deferring:
            ss.end_frame_batch()
        for obj in reversed(made_since(at)):
            if is_part(obj) or not getattr(obj, "is_alive", False):
                continue
            try:
                obj.on_destroy = None
            except Exception:  # noqa: BLE001 — not every item has the hook
                pass
            try:
                obj.destroy()
            except Exception as exc:  # noqa: BLE001 — reported below
                failed.append((obj, exc))
    failed = [(o, e) for o, e in failed if getattr(o, "is_alive", True)]
    if failed:
        raise AssertionError(
            "module sweep could not destroy what the module made; it leaks into "
            "every later module:\n" + "\n".join(
                f"  {type(o).__name__}: {type(e).__name__}: {e}" for o, e in failed[:10]))


def module_sweep():
    """``(setUpModule, tearDownModule)`` that destroy what a module registered.

    Module scope, not per test: a test may share actors with the next through
    ``setUpClass`` or a class attribute; nothing a module's tests see changes.
    Layers the module added stay (a later module may expect a framework layer).
    """
    state: dict = {}

    def setUpModule():
        state["at"] = mark()

    def tearDownModule():
        sweep(state.pop("at", (None, 0)))

    return setUpModule, tearDownModule


def _actors(items: List[Any]) -> List[Any]:
    """The live, non-part items of ``items``: the actors themselves."""
    from scena.entity import is_part
    out = []
    for o in items:
        try:
            if getattr(o, "is_alive", False) and not is_part(o):
                out.append(o)
        except Exception:  # noqa: BLE001 — a half-built item counts
            out.append(o)
    return out


def _tagged(items: List[Any]) -> List[Any]:
    """The live, non-part actors of ``items`` that carry a group tag."""
    from scena.entity import is_part
    out = []
    for o in items:
        try:
            if getattr(o, "is_alive", False) and not is_part(o) and getattr(o, "group", None):
                out.append(o)
        except Exception:  # noqa: BLE001 — a half-built item reads as untagged
            pass
    return out


def describe(items: List[Any], top: int = 6) -> str:
    counts = Counter(type(o).__name__ for o in items)
    return ", ".join(f"{n} {name}" for name, n in counts.most_common(top))


def sites(items: List[Any], top: int = 6) -> str:
    """Where the first ``top`` of ``items`` were made, for a message."""
    from scena.entity import made_at
    out = []
    for o in items[:top]:
        try:
            out.append(f"{type(o).__name__} {made_at(o) or '(no site)'}")
        except Exception:  # noqa: BLE001 — a message, not a check
            out.append(type(o).__name__)
    return "; ".join(out)


class LeftoverCheck(unittest.TestCase):
    """Runs after a module's ``tearDownModule`` (``tests/run_tiers.py`` puts one
    after each module): fails when the module left a live actor it made, or
    more than ``LIMIT`` live parts."""

    def __init__(self, module: str, state: dict) -> None:
        super().__init__("test_module_cleans_up")
        self.module = module
        self.state = state          # shared: "at" is the mark for the next module

    def __str__(self) -> str:
        return f"leftovers of {self.module} (tests.leftovers.LeftoverCheck)"

    def id(self) -> str:
        return f"tests.leftovers.{self.module}"

    def run(self, result=None):
        # A check, not one of the module's tests: "Ran N tests" stays the
        # module's own count (tests/run_tiers.py compares them).
        out = super().run(result)
        if result is not None:
            result.testsRun -= 1
        return out

    def test_module_cleans_up(self):
        try:
            left = made_since(self.state["at"])
            if len(left) > LIMIT or _actors(left):
                # Only when it matters: the roster is weak, so garbage still
                # lists. Drop our own references first, or they keep it alive.
                left = None
                gc.collect()
                left = made_since(self.state["at"])
        finally:
            self.state["at"] = mark()
        tagged = _tagged(left)
        if tagged:
            # LIMIT is for untagged debris. A group name is process-wide: a
            # tagged leftover answers every later ``group["heroi"]``, and every
            # later ``resolve`` / ``@collide`` on its name moves bodies against
            # it (deep serial pass 2026-10-22: test_collision_floor's "heroi"
            # and "chao" Rects broke test_concave's ride and every game that
            # reads ``group["heroi"]``).
            names = sorted({g for o in tagged for g in o.group})
            self.fail(
                f"{self.module} left {len(tagged)} live actors with a group "
                f"({describe(tagged)}; groups {names[:8]}): every later module's "
                "group[...] and collision rules see them. Destroy what the tests make: "
                "`setUpModule, tearDownModule = module_sweep()` (tests/leftovers.py)")
        actors = _actors(left)
        if actors:
            # Untagged too: a later test that counts a kind on the roster
            # counts them (deep serial pass 2026-10-24: test_diff_pose's
            # reference Lines read as string_theory's strings, WP42), and
            # every SystemWorld parks and resumes them.
            self.fail(
                f"{self.module} left {len(actors)} live actors ({describe(actors)}; "
                f"{sites(actors)}): "
                "later modules that count the roster see them. Destroy what the tests "
                "make: `setUpModule, tearDownModule = module_sweep()` (tests/leftovers.py)")
        if len(left) > LIMIT:
            self.fail(
                f"{self.module} left {len(left)} live roster items (limit {LIMIT}): "
                f"{describe(left)}. Destroy what the tests make: "
                "`setUpModule, tearDownModule = module_sweep()` (tests/leftovers.py)")
