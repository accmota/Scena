"""A constructor that raises leaves nothing behind; one that succeeds is finished.

Graphics review R4 (2026-10-08):

* E4: the finish step (hooks, ``@every``, ``setup()``, ``@when``) ran outside
  the rollback wrapper, so a ``setup()`` that raised left a live, drawn,
  grouped actor whose ``@every`` kept ticking.
* E4, second cause: the rollback was a hand-kept partial copy of teardown.
  An ``__init__`` that set ``on_collide`` and then raised leaked a Collider.
* E5: ``class Enemy(Mixin, Circle)``, where the mixin defines ``__init__``,
  never ran ``setup`` / ``on_update`` / ``@every``, and nothing rolled back.

The guard enumerates base kind × raise point × class layout (direct, mixin
first, mixin last). The oracle is the registry census and zombies before and
after, plus whether the actor's timer or update ever ran. A successful build
in each layout must run every finish hook. Known violations are shrink-only
(``graphics_known.CONSTRUCT``).

    python tests/run_tiers.py focused test_construct_failure
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from system_support import SystemTestCase, census, diff_census  # noqa: E402

import scena  # noqa: E402
from scena import every  # noqa: E402

BASES = {
    "Circle": (scena.Circle, dict(center=(0, 0), radius=5)),
    "Rect": (scena.Rect, dict(center=(0, 0), width=4, height=2)),
    "Polygon": (scena.Polygon, dict(points=[(0, 0), (4, 0), (2, 3)])),
    "Sprite": (scena.Sprite, dict(source="cf_missing.png", center=(0, 0))),
    "Text": (scena.Text, dict(text="t", center=(0, 0))),
    "Entity": (scena.Entity, dict()),
}

# Where the constructor raises. ``in setup`` raises from the finish step.
POINTS = ("before super", "after super", "after on_collide", "after every",
          "after tag", "after collidable", "in setup")
LAYOUTS = ("direct", "mixin first", "mixin last")
IGNORE = ("sched.every_sites",)

from tests.leftovers import module_sweep  # noqa: E402

setUpModule, tearDownModule = module_sweep()  # destroy what the tests made


class Boom(Exception):
    pass


def _make_class(base_name, point, layout, log):
    """A subclass of the base that raises at ``point`` (None: never raises).

    Real ``class`` statements: ``@every`` on a method is told from a
    module-level ``@every`` by the class-body frame it runs in."""
    base, _kw = BASES[base_name]

    def body(self, init_super, kw):
        if point == "before super":
            raise Boom
        init_super(**kw)
        if point == "after on_collide":
            self.on_collide = lambda other, info=None: None
        elif point == "after every":
            self.every(0.05, lambda: log.append("tick"))
        elif point == "after tag":
            self.tag("cf_tagged")
        elif point == "after collidable" and hasattr(type(self), "collidable"):
            self.collidable = True
        if point is not None and point != "in setup":
            raise Boom

    class Hooks:
        def setup(self):
            log.append("setup")
            if point == "in setup":
                raise Boom

        def on_update(self, dt):
            log.append("update")

    class Direct(base):
        setup = Hooks.setup
        on_update = Hooks.on_update

        def __init__(self, **kw):
            body(self, lambda **k: base.__init__(self, **k), kw)

        @every(0.05)
        def pulse(self):
            log.append("pulse")

    class Mixin:
        def __init__(self, **kw):
            body(self, lambda **k: super(Mixin, self).__init__(**k), kw)

    class MixinFirst(Mixin, base):
        setup = Hooks.setup
        on_update = Hooks.on_update

        @every(0.05)
        def pulse(self):
            log.append("pulse")

    class MixinLast(base, Mixin):
        setup = Hooks.setup
        on_update = Hooks.on_update

        def __init__(self, **kw):
            body(self, lambda **k: base.__init__(self, **k), kw)

        @every(0.05)
        def pulse(self):
            log.append("pulse")

    return {"direct": Direct, "mixin first": MixinFirst, "mixin last": MixinLast}[layout]


def _cases():
    for base_name in BASES:
        for layout in LAYOUTS:
            for point in POINTS:
                yield base_name, layout, point


class TestConstructFailure(SystemTestCase, unittest.TestCase):
    world_draw = False

    def _build(self, base_name, layout, point, log):
        cls = _make_class(base_name, point, layout, log)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return cls(**BASES[base_name][1])

    def failures(self) -> dict:
        out = {}
        for base_name, layout, point in _cases():
            key = f"{base_name} | {layout} | {point}"
            log = []
            self.w.step(1)
            before = census()
            try:
                obj = self._build(base_name, layout, point, log)
            except Boom:
                obj = None
            except Exception as e:  # noqa: BLE001
                out[key + " | raised"] = type(e).__name__
                continue
            if obj is not None:
                out[key + " | did not raise"] = ""
                obj.destroy()
                continue
            ran = len(log)
            self.w.step(4)
            if len(log) > ran:
                out[key + " | ticks after failing"] = ",".join(sorted(set(log[ran:])))
            moved = diff_census(before, census(), IGNORE)
            if moved:
                out[key + " | leaves"] = ", ".join(sorted(moved)[:4])
            z = [type(o).__name__ for _w, o in self.w.zombies()]
            if z:
                out[key + " | zombies"] = ",".join(z)
        return out

    def unfinished(self) -> dict:
        """A build that succeeds runs setup, on_update and the method @every."""
        out = {}
        for base_name in BASES:
            for layout in LAYOUTS:
                log = []
                obj = self._build(base_name, layout, None, log)
                self.w.step(6)
                for hook in ("setup", "update", "pulse"):
                    if hook not in log:
                        out[f"{base_name} | {layout} | {hook} never ran"] = ""
                obj.destroy()
        return out

    def test_a_failed_construction_leaves_nothing(self):
        from graphics_known import shrink_only
        shrink_only(self, {**self.failures(), **self.unfinished()}, "CONSTRUCT")

    def test_canary_no_rollback(self):
        from diff_support import assert_catches
        assert_catches(self, "test_construct_failure.TestConstructFailure.test_a_failed_construction_leaves_nothing",
                       [("scena.place", "_drop_failed_construct", lambda obj: None)],
                       "a constructor that raises and is not rolled back")



class TestCloneScaleIsAtomic(unittest.TestCase):
    """clone(scale=) refuses before the copy exists, or removes the copy
    (review 2026-10-09 S5-6, an E9 regression)."""

    def test_bad_scales_leave_no_copy(self):
        from scena import Circle
        from scena.canvas import ScenaCanvas
        reg = ScenaCanvas.get_current().registry
        c = Circle(radius=5)
        try:
            n0 = len([o for o in reg.live_objects() if isinstance(o, Circle)])
            for bad, err in ((True, TypeError), (-1, ValueError), (1e308, ValueError),
                             (float("nan"), ValueError)):
                with self.subTest(scale=bad):
                    with self.assertRaises(err):
                        c.clone(scale=bad)
                    n = len([o for o in reg.live_objects() if isinstance(o, Circle)])
                    self.assertEqual(n, n0)
        finally:
            c.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
