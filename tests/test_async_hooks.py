"""An ``async def`` where Scena calls a function synchronously raises with the fix.

Bug class: only an async **mode** is driven as a script (``e.mode = fn``,
``then=``). Every other place that takes a function calls it and drops the
result, so an ``async def setup`` / ``on_update`` / ``@every`` / ``on_done``
made a coroutine nobody ran: the body never ran and the only trace was
Python's "coroutine ... was never awaited". Each funnel now refuses it:

* class-body hooks (``setup``, ``on_update``, ``on_click`` …) at the class statement;
* every Scena decorator but ``@on_mode`` (``_claim_decorator_role``);
* ``on_update =`` / ``on_collide =`` / pointer handlers at registration;
* ``after`` / ``every`` / ``on_done=`` (hot calls, no registration check)
  when they fire, in ``_invoke``;
* script hooks (``update``, ``on_key_down`` …) when ``run()`` binds them;
* backstop at the call (``_invoke`` / ``call_truncated``): a sync callback
  that returns a coroutine (``lambda: self.intro()``) raises, coroutine closed.

    python tests/run_tiers.py focused test_async_hooks
"""
from __future__ import annotations

import functools
import gc
import os
import sys
import unittest
import warnings
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scena import (  # noqa: E402
    Act, Button, Circle, Entity, Rect, after, collide, every, exit_mode, on_change,
    on_mode, play_sound, tween, wait, when,
)
from scena.entity import _HOOK_LOOKUP_NAMES  # noqa: E402
from scena.process import _ROLE_LABELS, _claim_decorator_role  # noqa: E402
from scena.validate import call_truncated, is_async_callable  # noqa: E402
from system_support import SystemTestCase, tone  # noqa: E402


async def _coro_fn(*_args):
    await wait(0.1)


async def _agen_fn(*_args):
    yield 1


def _never_awaited(caught):
    return [str(w.message) for w in caught if "never awaited" in str(w.message)]


class AsyncHookCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    def assertRefused(self, body, *needles):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with self.assertRaises(TypeError) as cm:
                body()
            gc.collect()
        msg = str(cm.exception)
        self.assertIn("async", msg)
        for needle in needles:
            self.assertIn(needle, msg)
        self.assertEqual(_never_awaited(caught), [], "a coroutine was made and dropped")
        return msg


class TestDetection(unittest.TestCase):
    def test_kinds(self):
        class Obj:
            async def m(self):
                pass

            def s(self):
                pass

        class AsyncCall:
            async def __call__(self):
                pass

        self.assertTrue(is_async_callable(_coro_fn))
        self.assertTrue(is_async_callable(_agen_fn))
        self.assertTrue(is_async_callable(Obj().m))
        self.assertTrue(is_async_callable(Obj.m))
        self.assertTrue(is_async_callable(functools.partial(_coro_fn, 1)))
        self.assertFalse(is_async_callable(Obj().s))
        self.assertFalse(is_async_callable(lambda: None))
        self.assertFalse(is_async_callable(print))
        self.assertFalse(is_async_callable(None))
        # An object with an async __call__ is not caught at registration;
        # the call backstop catches it (TestBackstop).
        self.assertFalse(is_async_callable(AsyncCall()))


class TestClassHooks(AsyncHookCase):
    def test_every_discovered_hook_name(self):
        # Whole class: a hook added to _HOOK_LOOKUP_NAMES is covered by construction.
        for name in _HOOK_LOOKUP_NAMES:
            with self.subTest(hook=name):
                async def hook(self, *args):
                    await wait(0.1)
                hook.__name__ = name
                msg = self.assertRefused(
                    lambda: type(f"Async_{name}", (Entity,), {name: hook}), name,
                )
                self.assertIn("self.mode = self.", msg)

    def test_shape_and_act_setup(self):
        def make_shape():
            class Bola(Circle):
                async def setup(self):
                    await wait(1)
        self.assertRefused(make_shape, "class Bola:", "setup()")

        def make_act():
            class Fase(Act):
                async def setup(self):
                    await wait(1)
        self.assertRefused(make_act, "class Fase:", "setup()")

    def test_inherited_async_hook_is_refused_on_the_base(self):
        def make():
            class Base(Entity):
                async def on_update(self, dt):
                    pass
        self.assertRefused(make, "class Base:")

    def test_async_mode_and_helpers_stay_legal(self):
        log = []

        class Nave(Entity):
            def setup(self):
                self.mode = self.intro

            @on_mode
            async def intro(self):
                log.append("start")
                await self.piscar()
                log.append("end")

            async def piscar(self):          # plain async helper, awaited by the mode
                await wait(0.1)

        n = self.track(Nave())
        self.w.seconds(0.3)
        self.assertEqual(log, ["start", "end"])
        n.destroy()


class TestDecorators(AsyncHookCase):
    def test_every_role_but_mode_refuses_async(self):
        # Whole class: a decorator role added to _ROLE_LABELS is covered.
        for role in _ROLE_LABELS:
            if role in ("mode", "exit"):
                continue
            with self.subTest(role=role):
                async def handler():
                    pass
                self.assertRefused(lambda: _claim_decorator_role(handler, role),
                                   _ROLE_LABELS[role])
                self.assertFalse(getattr(handler, "_scena_roles", None))

    def test_on_mode_accepts_async(self):
        async def intro(self):
            pass
        self.assertIs(on_mode(intro), intro)

    def test_exit_mode_keeps_its_message(self):
        def enter(self):
            pass
        with self.assertRaises(TypeError) as cm:
            @exit_mode(enter)
            async def leave(self):
                pass
        self.assertIn("exit_mode hooks must be a plain function", str(cm.exception))

    def test_public_decorators(self):
        def module_every():
            @every(1)
            async def tick():
                pass
        self.assertRefused(module_every, "@every / @after")

        def module_after():
            @after(1)
            async def later():
                pass
        self.assertRefused(module_after, "@every / @after")

        def class_when():
            class Nave(Entity):
                @when(lambda: False)
                async def boom(self):
                    pass
        self.assertRefused(class_when, "@when")

        def change():
            @on_change(lambda: 1)
            async def changed(value):
                pass
        self.assertRefused(change, "@on_change")

        def collides():
            @collide("ah_a", "ah_b")
            async def hit(me, other, info):
                pass
        self.assertRefused(collides, "@collide")


class TestRegistration(AsyncHookCase):
    def assertRefusedAtFire(self, arm, *needles, t=0.3):
        """``after`` / ``every`` / ``on_done=`` are hot calls: no registration
        check; ``_invoke`` refuses the async callback when it fires."""
        arm()
        return self.assertRefused(lambda: self.w.seconds(t), *needles)

    def test_after_every_on_done(self):
        fix = "self.mode = self."
        self.assertRefusedAtFire(lambda: after(0.05, _coro_fn), "callback _coro_fn()", fix)
        self.assertRefusedAtFire(lambda: after(0.05, on_done=_coro_fn), "_coro_fn()")
        self.assertRefusedAtFire(lambda: every(0.05, _coro_fn), "_coro_fn()")
        self.assertRefusedAtFire(lambda: after(0.05, functools.partial(_coro_fn, 2)), "cannot be async")

    def test_entity_timers_and_tweens(self):
        e = self.track(Rect(center=(100, 100), width=10, height=10))
        self.assertRefusedAtFire(lambda: e.after(0.05, _coro_fn), "_coro_fn()")
        self.assertRefusedAtFire(lambda: e.every(0.05, _coro_fn), "_coro_fn()")
        self.assertRefusedAtFire(lambda: e.move_by(10, 0, time=0.05, on_done=_coro_fn), "_coro_fn()")
        self.assertRefusedAtFire(lambda: tween(e["width"], 50, time=0.05, on_done=_coro_fn), "_coro_fn()")

    def test_play_sound_on_done(self):
        self.assertRefusedAtFire(lambda: play_sound(tone(0.05), on_done=_coro_fn), "_coro_fn()", t=0.5)

    def test_hook_setters(self):
        e = self.track(Rect(center=(100, 100), width=10, height=10))
        self.assertRefused(lambda: setattr(e, "on_update", _coro_fn), "on_update =")
        self.assertRefused(lambda: setattr(e, "on_destroy", _coro_fn), "on_destroy =")
        for attr in ("on_collide", "on_collide_stay", "on_collide_exit"):
            with self.subTest(attr=attr):
                self.assertRefused(lambda: setattr(e, attr, _coro_fn), f"{attr} =")
        self.assertRefused(lambda: setattr(e, "on_click", _coro_fn), "on_click")
        self.assertRefused(lambda: setattr(e, "on_hover", _coro_fn), "on_hover")
        self.assertIsNone(e.on_update)
        self.assertIsNone(e.on_destroy)

    def test_button(self):
        self.assertRefused(lambda: Button(label="x", on_click=_coro_fn), "on_click")

    def test_then_takes_an_async_mode(self):
        log = []

        class Nave(Entity):
            def setup(self):
                self.after(0.1, then=self.intro)

            async def intro(self):
                await wait(0.1)
                log.append("ran")

        n = self.track(Nave())
        self.w.seconds(0.4)
        self.assertEqual(log, ["ran"])
        n.destroy()

    def test_script_hooks(self):
        from scena.orchestration import ScenaFramework

        fake = SimpleNamespace(canvas_manager=SimpleNamespace())
        for name in ("setup", "update", "post_draw", "on_key_down", "on_mouse_click"):
            with self.subTest(hook=name):
                self.assertRefused(
                    lambda: ScenaFramework.set_auto_callbacks(fake, {name: _coro_fn}),
                    "script hook",
                )
        # A plain hook still binds.
        def update(dt):
            pass
        ScenaFramework.set_auto_callbacks(fake, {"update": update})
        self.assertIs(fake.update, update)


class TestBackstop(AsyncHookCase):
    def test_lambda_calling_an_async_helper_raises_at_the_fire(self):
        class Nave(Entity):
            async def anda(self):
                await wait(0.1)

        n = self.track(Nave())
        n.after(0.05, lambda: n.anda())
        msg = self.assertRefused(lambda: self.w.seconds(0.2), "anda()", "without await")
        self.assertIn("<lambda>", msg)
        n.destroy()

    def test_call_truncated(self):
        self.assertRefused(lambda: call_truncated(lambda: _coro_fn()), "_coro_fn()")

        class AsyncCall:
            async def __call__(self):
                pass
        self.assertRefused(lambda: call_truncated(AsyncCall()), "without await")

    def test_sync_results_pass(self):
        self.assertIsNone(call_truncated(lambda: 5))
        e = self.track(Rect(center=(100, 100), width=10, height=10))
        fired = []
        e.after(0.05, lambda: fired.append(1) or e.move_by(1, 0))  # returns a value
        self.w.seconds(0.2)
        self.assertEqual(fired, [1])


if __name__ == "__main__":
    unittest.main()
