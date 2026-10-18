"""An ``async def`` where Scena calls a function synchronously raises with the fix.

Bug class: only an async **mode** (``e.mode = fn``, ``then=``) and a task
(``run_task(fn)``) are driven as scripts. Every other place that takes a function calls it and drops the
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
  that returns a coroutine (``lambda: self.intro()``) raises, coroutine closed;
* an async function called without ``await`` anywhere in author code: a
  SCENA WARNING at the calling line (``TestNeverAwaitedHook``);
* predicates and conditions (``group.filter`` / ``any`` / ``all`` /
  ``count_where`` / ``nearest(where=)``, ``until``, ``@when``, the
  ``@on_change`` target, ``resolve(only=)``) and ``@=`` formulas at the call:
  their coroutine is truthy, so a filter kept everything, ``until`` ended at
  once and ``@on_change`` fired every frame (AH2, 2026-10-12).

``TestEveryCallbackDoor`` enumerates the doors from the public surface (every
parameter or setter named like a callback, or annotated ``Callable``), so a new
one cannot land without a case.

    python tests/run_tiers.py focused test_async_hooks
"""
from __future__ import annotations

import functools
import gc
import inspect
import os
import re
import sys
import unittest
import warnings
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scena  # noqa: E402
import scena.process as process  # noqa: E402
from scena import (  # noqa: E402
    Act, Button, Circle, Entity, Rect, after, collide, every, exit_mode, on_change,
    on_mode, play_sound, tween, wait, when,
)
from scena.entity import _HOOK_LOOKUP_NAMES  # noqa: E402
from scena.process import _ROLE_LABELS, _claim_decorator_role  # noqa: E402
from scena.validate import call_truncated, is_async_callable  # noqa: E402
from leftovers import mark, sweep  # noqa: E402
from system_support import SystemTestCase, SystemWorld, tone  # noqa: E402


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



# ---------------------------------------------------------------------------
# Every callback door, from the surface (class guard for AH1 and AH2)
# ---------------------------------------------------------------------------

_DOOR_NAME = re.compile(
    r"^(on_[a-z_]+|then|fn|func|callback|pred|where|condition|target|only)$")


def callback_doors() -> list:
    """Every public door that may take a function, keyed by its defining class.

    ``Owner.method(param)`` for a parameter, ``Owner(param)`` for a
    constructor, ``Owner.name =`` for a setter, ``function(param)`` for an
    exported function. A parameter counts when its name reads like a callback
    or its annotation says ``Callable``. Inherited doors appear once, under
    the class that defines them.
    """
    found = set()

    def scan(fn, label):
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return
        for p in sig.parameters.values():
            if _DOOR_NAME.match(p.name) or "Callable" in str(p.annotation):
                found.add(f"{label}({p.name})")

    objs = [getattr(scena, n) for n in scena.__all__]
    objs += [type(scena.canvas), type(scena.group)]
    for o in objs:
        if inspect.isclass(o):
            if "__init__" in vars(o):
                scan(o.__init__, o.__qualname__)
            for klass in o.__mro__:
                if klass.__module__.split(".")[0] != "scena":
                    continue
                for name, member in vars(klass).items():
                    if name.startswith("_"):
                        continue
                    if inspect.isfunction(member):
                        scan(member, member.__qualname__)
                    elif (isinstance(member, property) and member.fset is not None
                          and _DOOR_NAME.match(name)):
                        found.add(f"{klass.__qualname__}.{name} =")
        elif inspect.isfunction(o):
            scan(o, o.__qualname__)
    return sorted(found)


# The name matches, but the parameter does not take a function to call.
NOT_A_CALLBACK = {
    **{k: "a point, shape or group to aim at" for k in (
        "GodRays(target)", "Lamp(target)", "Perspective(target)",
        "Spotlight(target)", "Vortex(target)", "Canvas.frame_to(target)",
        "Graphic.resolve_now(target)", "collide_with(target)",
        "collide_with_exit(target)", "collide_with_stay(target)")},
    **{k: "a number or point" for k in (
        "chase(target)", "approach(target)", "deadzone(target)", "heading(target)",
        "Endless.index_at(where)")},
    "Canvas.set_origin(where)": "a placement word (\"corner\" / \"center\")",
    "Entity.tween(target)": "the field or cell to tween",
    "tween(target)": "the field or cell to tween",
    "Shape.move_along(target)": "the Track to ride",
    "unregister_event(func)": "removes a registration; never calls the function",
    "Text(width)": "a width formula is refused before it is read (layout, not pose)",
    "Text(font_size)": "takes no formula (a look, outside the graph): refused before it is read",
    "UIWidget.on_click =": "refused on every widget but Button, whose door is Button.on_click =",
}

# An async function is the point here: the engine drives it as a mode.
_DRIVES_A_MODE = "takes a mode, which the engine drives (test_then_takes_an_async_mode)"
_DRIVES_A_TASK = "takes an async function and drives it as a task (test_tasks)"
DRIVEN = {"Entity.goto_mode(fn)": _DRIVES_A_MODE, "on_mode(fn)": _DRIVES_A_MODE,
          "run_task(fn)": _DRIVES_A_TASK, "Entity.run_task(fn)": _DRIVES_A_TASK}


def _is_driven(door: str):
    if door.endswith("(then)"):
        return _DRIVES_A_MODE
    return DRIVEN.get(door)


def _ent():
    return Rect(center=(100, 100), width=10, height=10)


def _sprite():
    from media_support import media
    return scena.Sprite(media("space", "enemyGreen1.png"), center=(100, 100), height=20)


def _text():
    return scena.Text("x", center=(100, 100))


def _setter(make, name, t=0.0):
    return (lambda: setattr(make(), name, _coro_fn)), t


def _verb(make, name, *args, t=1.5, **kw):
    """``make().name(*args, on_done=<async>, **kw)``, then ``t`` seconds of frames."""
    return (lambda: getattr(make(), name)(*args, on_done=_coro_fn, **kw)), t


def _canvas(name, *args, t=1.0, **kw):
    return (lambda: getattr(scena.canvas, name)(*args, on_done=_coro_fn, **kw)), t


def _group_pred(name, **kw):
    def arm():
        for i in range(3):
            Rect(center=(i * 30, 0), width=5, height=5, group="ah_doors")
        method = getattr(scena.group["ah_doors"], name)
        return method((0, 0), where=_coro_fn) if name == "nearest" else method(_coro_fn)
    return arm, 0.0


def _resolve_only():
    # Overlapping from the first frame, so the pass asks only= at once.
    a = _ent()
    b = Rect(center=(100, 106), width=40, height=10)
    scena.resolve(a, b, only=_coro_fn)


def _until_in_a_mode():
    class Espera(Entity):
        def setup(self):
            self.mode = self.go

        async def go(self):
            await scena.until(_coro_fn)
    Espera()


def _record():
    import miniaudio
    mic = scena.Microphone(backends=[miniaudio.Backend.NULL])
    mic._device.stop()
    _record.mic = mic
    mic.record(on_done=_coro_fn)
    mic.stop()


def _on_change_target():
    @on_change(_coro_fn)
    def changed(value):
        pass


def _when_condition():
    @when(_coro_fn)
    def fired():
        pass


# door -> (arm, seconds of frames after it). The arm hands the door an
# ``async def``; Scena must refuse it (at the call, or when it fires).
CASES = {
    "Button(on_click)": (lambda: Button(label="x", on_click=_coro_fn), 0.0),
    "Button.on_click =": _setter(lambda: Button(label="x"), "on_click"),
    "SpriteButton(on_click)": (lambda: scena.SpriteButton(
        center=(10, 10), width=10, height=10, on_click=_coro_fn), 0.0),
    "SpriteButton.on_click =": _setter(lambda: scena.SpriteButton(
        center=(10, 10), width=10, height=10), "on_click"),
    "Menu(on_choose)": (lambda: scena.Menu(options=["a", "b"], on_choose=_coro_fn), 0.0),
    "TextInput(on_submit)": (lambda: scena.TextInput(on_submit=_coro_fn), 0.0),
    "TextInput.on_submit =": _setter(lambda: scena.TextInput(), "on_submit"),
    "UIWidget.on_hover =": _setter(lambda: scena.CheckBox(), "on_hover"),
    "UIWidget.on_hover_exit =": _setter(lambda: scena.CheckBox(), "on_hover_exit"),
    "UIWidget.flash_text(on_done)": _verb(lambda: Button(label="x"), "flash_text", "y", 0.05),
    "Contrail(on_leave)": (lambda: scena.Contrail(duration=0.1, on_leave=_coro_fn), 0.0),
    "History(on_leave)": (lambda: scena.History(duration=0.1, on_leave=_coro_fn), 0.0),
    "History.on_leave =": _setter(lambda: scena.History(duration=0.1), "on_leave"),
    **{f"Entity.{n} =": _setter(_ent, n) for n in (
        "on_update", "on_destroy", "on_collide", "on_collide_stay", "on_collide_exit")},
    **{f"Collider.{n} =": _setter(lambda: scena.Collider([_ent()]), n) for n in (
        "on_collide", "on_collide_stay", "on_collide_exit")},
    **{f"{owner}.{n} =": _setter(_ent, n) for owner in ("Graphic", "Shape") for n in (
        "on_click", "on_hover", "on_hover_exit", "on_drag_over", "on_drag_to", "on_drop_by")},
    "Entity.after(fn)": (lambda: _ent().after(0.05, _coro_fn), 0.3),
    "Entity.after(on_done)": (lambda: _ent().after(0.05, on_done=_coro_fn), 0.3),
    "Entity.every(fn)": (lambda: _ent().every(0.05, _coro_fn), 0.3),
    "Entity.tween(on_done)": (lambda: (lambda e: e.tween(e["width"], 20, time=0.05,
                                                          on_done=_coro_fn))(_ent()), 0.3),
    "Entity.play_sound(on_done)": (lambda: _ent().play_sound(tone(0.05), on_done=_coro_fn), 0.5),
    "after(fn)": (lambda: after(0.05, _coro_fn), 0.3),
    "after(on_done)": (lambda: after(0.05, on_done=_coro_fn), 0.3),
    "every(fn)": (lambda: every(0.05, _coro_fn), 0.3),
    "tween(on_done)": (lambda: (lambda e: tween(e["width"], 20, time=0.05,
                                                 on_done=_coro_fn))(_ent()), 0.3),
    "play_sound(on_done)": (lambda: play_sound(tone(0.05), on_done=_coro_fn), 0.5),
    **{f"Shape.{n}(on_done)": _verb(_ent, n) for n in (
        "blink", "burn_out", "dissolve_in", "dissolve_out", "fade_in", "fade_out",
        "flash", "implode", "knock", "pop", "pulse_outline", "spark_burst")},
    "Shape.move_by(on_done)": _verb(_ent, "move_by", 10, 0, time=0.05),
    "Shape.move_to(on_done)": _verb(_ent, "move_to", (10, 10), time=0.05),
    "Shape.move_along(on_done)": (lambda: _ent().move_along(
        scena.Track(points=[(0, 0), (100, 0), (100, 100)]), time=0.05,
        on_done=_coro_fn), 0.5),
    "Shape.rotate_by(on_done)": _verb(_sprite, "rotate_by", 10, time=0.05),
    "Shape.rotate_to(on_done)": _verb(_text, "rotate_to", 10, time=0.05),
    "Shape.scale_by(on_done)": _verb(_sprite, "scale_by", 2, time=0.05),
    "Shape.scale_to(on_done)": _verb(_text, "scale_to", 2, time=0.05),
    "Graphic.reset_rotation(on_done)": _verb(_ent, "reset_rotation", time=0.05),
    "Sprite.reset_rotation(on_done)": _verb(_sprite, "reset_rotation", time=0.05),
    "Text.flash_text(on_done)": _verb(_text, "flash_text", "y", 0.05),
    "Text(text)": (lambda: scena.Text(_coro_fn, center=(10, 10)), 0.0),
    "Text(angle)": (lambda: scena.Text("x", center=(10, 10), angle=_coro_fn), 0.0),
    "Canvas.fade_in(on_done)": _canvas("fade_in", 0.05),
    "Canvas.fade_out(on_done)": _canvas("fade_out", 0.05),
    "Canvas.frame_to(on_done)": (lambda: scena.canvas.frame_to(
        _ent(), time=0.05, on_done=_coro_fn), 1.0),
    "Canvas.pan_by(on_done)": _canvas("pan_by", 10, 0, time=0.05),
    "Canvas.pan_to(on_done)": _canvas("pan_to", (10, 10), time=0.05),
    "Canvas.reset_view(on_done)": _canvas("reset_view", time=0.05),
    "Canvas.rotate_by(on_done)": _canvas("rotate_by", 10, time=0.05),
    "Canvas.rotate_to(on_done)": _canvas("rotate_to", 10, time=0.05),
    "Canvas.set_origin(on_done)": _canvas("set_origin", "center", time=0.05),
    "Canvas.zoom_by(on_done)": _canvas("zoom_by", 2, time=0.05),
    "Canvas.zoom_to(on_done)": _canvas("zoom_to", 2, time=0.05),
    "Microphone.record(on_done)": (_record, 0.2),
    "GroupOperator.all(pred)": _group_pred("all"),
    "GroupOperator.any(pred)": _group_pred("any"),
    "GroupOperator.count_where(pred)": _group_pred("count_where"),
    "GroupOperator.filter(pred)": _group_pred("filter"),
    "GroupOperator.nearest(where)": _group_pred("nearest"),
    "nearest(where)": (lambda: scena.nearest((0, 0), [(1, 1), (5, 5)], where=_coro_fn), 0.0),
    "until(pred)": (_until_in_a_mode, 0.3),
    "when(condition)": (_when_condition, 0.0),
    "on_change(target)": (_on_change_target, 0.0),
    "resolve(only)": (_resolve_only, 0.1),
}


class TestEveryCallbackDoor(AsyncHookCase):
    """Every door that takes a function refuses an ``async def`` (AH1, AH2).

    Before 2026-10-12 the predicates (``group.filter``, ``nearest(where=)``,
    ``until``, ``@when``, the ``@on_change`` target, ``resolve(only=)``) took
    one: its coroutine is truthy, so a filter kept every member, ``until``
    ended on its first poll, ``@on_change`` fired every frame and ``only=``
    blocked every contact, with Python's "never awaited" as the only trace.
    The AH1 fix (d017e2d) had listed the doors by hand.
    """

    def test_every_door_is_listed(self):
        doors = set(callback_doors())
        listed = set(CASES) | set(NOT_A_CALLBACK) | set(DRIVEN)
        missing = sorted(d for d in doors - listed if not _is_driven(d))
        self.assertFalse(missing, f"callback doors with no case (add one to CASES, or "
                                  f"a reason to NOT_A_CALLBACK): {missing}")
        stale = sorted(listed - doors)
        self.assertFalse(stale, f"listed doors the surface no longer has: {stale}")
        self.assertGreater(len(doors), 100, "the scan stopped reaching the surface")

    def test_every_door_refuses_async(self):
        for door, (arm, t) in sorted(CASES.items()):
            with self.subTest(door=door):
                # A fresh world per door; what the arm built is destroyed after.
                self.w.teardown(strict=False)
                self.w = SystemWorld(draw=False)
                at = mark()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    gc.collect()        # an earlier door's coroutine is not this one's

                def body():
                    arm()
                    if t:
                        self.w.seconds(t)
                try:
                    self.assertRefused(body)
                finally:
                    mic = getattr(_record, "mic", None)
                    if mic is not None:
                        mic.close()
                        _record.mic = None
                    sweep(at)

    def test_canary_group_predicates_without_the_check(self):
        # Put AH2 back on the group predicates (the coroutine taken as True).
        from diff_support import assert_catches
        assert_catches(
            self, "test_async_hooks.TestEveryCallbackDoor.test_every_door_refuses_async",
            [("scena.registry", "_refuse_async", lambda fn, what: None)],
            "an async group.filter / any / all predicate (AH2)")


async def _show():
    await wait(0.1)


def _drop_show():
    _show()  # the dropping line: the message names it
    return inspect.currentframe().f_lineno - 1


@unittest.skipUnless(process._UNAWAITED_HOOK_ACTIVE,
                     "this interpreter does not call warnings._warn_unawaited_coroutine")
class TestNeverAwaitedHook(unittest.TestCase):
    """``show()`` without ``await`` in author code: a SCENA WARNING naming the
    line and the fix, at the statement (not at a later gc). Python's own text
    stays for everything that is not author code (process.install_unawaited_hook)."""

    def setUp(self):
        scena.process.clear_author_error()
        self.addCleanup(scena.process.clear_author_error)

    def _caught(self, body):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = body()
            before_gc = [str(w.message) for w in caught]
            gc.collect()
        return result, before_gc, caught

    def test_author_drop_names_the_line_and_the_fix(self):
        line, msgs, caught = self._caught(_drop_show)
        self.assertEqual(len(msgs), 1, msgs)
        msg = msgs[0]
        self.assertIn("SCENA WARNING", msg)
        self.assertIn("never awaited", msg)           # _never_awaited() keeps seeing it
        self.assertIn("_show() was called at test_async_hooks.py, line %d" % line, msg)
        self.assertIn("await _show()", msg)
        self.assertEqual(caught[0].lineno, line, "the warning points at the dropping line")
        self.assertEqual(os.path.basename(caught[0].filename), "test_async_hooks.py")
        self.assertIsNotNone(scena.process.last_author_error(), "the banner shows it")

    def test_library_drop_keeps_pythons_text(self):
        import asyncio

        def drop():
            asyncio.sleep(0)
            return inspect.currentframe().f_lineno - 1

        line, msgs, caught = self._caught(drop)
        self.assertEqual(msgs, ["coroutine 'sleep' was never awaited"])
        self.assertEqual(caught[0].lineno, line)
        self.assertIsNone(scena.process.last_author_error())

    def test_awaited_or_closed_coroutine_is_silent(self):
        def close_it():
            c = _show()
            c.close()

        _, msgs, _ = self._caught(close_it)
        self.assertEqual(msgs, [])

    def test_install_twice_keeps_one_hook(self):
        self.assertTrue(process.install_unawaited_hook())
        self.assertTrue(process.install_unawaited_hook())
        self.assertIs(warnings._warn_unawaited_coroutine, process._warn_unawaited)
        self.assertIsNot(process._UNAWAITED_ORIGINAL, process._warn_unawaited)
        _, msgs, _ = self._caught(_drop_show)
        self.assertEqual(len(msgs), 1, msgs)

    def test_internal_failure_falls_back_to_python(self):
        def boom(_coro):
            raise RuntimeError("hook bug")

        old = process._unawaited_message
        process._unawaited_message = boom
        try:
            _, msgs, _ = self._caught(_drop_show)
        finally:
            process._unawaited_message = old
        self.assertEqual(msgs, ["coroutine '_show' was never awaited"])


if __name__ == "__main__":
    unittest.main()
