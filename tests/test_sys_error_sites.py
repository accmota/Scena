"""Author error × callback site: an exception in any author hook leaves a
consistent engine behind it.

Interaction campaign, class 7 (design/Testing Design.md, "Interaction
campaign"). ``test_sys_frame_order.TestAuthorErrorMidFrame`` checks four
sites; here ``SITES`` arms every kind of author callback the engine runs
(update, timers, ``every``, tween / transient / cover / sound ``on_done``,
sync and async mode bodies, an ``@exit_mode`` hook, an actor's ``on_update``
and ``on_destroy``, collision enter / stay / exit, a leave handler, hover and
hover-exit, click, drag and drop, a widget's click and submit, ``@when`` and
``@on_change``, a formula, an ``until`` predicate, an act's ``setup``,
``on_update`` and ``on_destroy``, an Endless builder) to raise **once** in a
frame, and checks the same contract for each (Actors Design, Protections,
"Author errors are loud"):

* the error propagates out of the frame exactly once (the fire, edge or
  contact is consumed: stepping on does not raise again);
* the frame batch is closed and the dirty stack empty;
* the next frames run (a script-level ``every`` keeps ticking);
* no registry holds a destroyed object, no pointer state names a dead one;
* a second, unrelated actor's work is untouched (its ``every`` count grows).

A guard requires every callback-taking export of ``scena.__all__`` and every
``on_*`` attribute of a Graphic to be covered by a site or excused with a
reason. ``KNOWN`` is shrink-only.

    python -m unittest tests.test_sys_error_sites -v
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Callable, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diff_support import assert_catches  # noqa: E402
from system_support import SystemTestCase, quiet, tone  # noqa: E402

import scena  # noqa: E402
from scena import (Act, Button, Circle, Endless, Entity, Rect, TextInput, after, canvas,  # noqa: E402
                   change_act, clock, collide, collide_exit, collide_stay, drag_to, drop_by,
                   exit_mode, hover, hover_exit, leave_playfield, on_change, run_task, st,
                   tween, until, wait, when)
from scena.input import Mouse  # noqa: E402
from scena.state import get_scena_system  # noqa: E402

N = 3   # the frame the error fires in (or the frame the arming act happens)


class Boom(RuntimeError):
    pass


def _once(log: List[int]):
    """A callback that raises on its first call only (the fire is consumed)."""
    def fn(*_a, **_k):
        if not log:
            log.append(clock.frame)
            raise Boom("boom")
    return fn


class Site:
    """One author callback site: ``arm(tc, log)`` installs a hook that raises
    once; ``covers`` names the exports / attributes it stands for."""

    def __init__(self, name: str, arm: Callable[[Any, List[int]], None], covers=(),
                 raises=Boom) -> None:
        self.name, self.arm, self.covers, self.raises = name, arm, tuple(covers), raises


def _pair(tc):
    a = tc.track(Circle(center=(0, 0), radius=5, group="ex"))
    b = tc.track(Circle(center=(300, 0), radius=5, group="ey"))
    return a, b


# --------------------------------------------------------------------------
# The sites
# --------------------------------------------------------------------------

def arm_update(tc, log):
    f = _once(log)
    tc.w.on_update(lambda dt: f() if clock.frame >= N else None)


def arm_after(tc, log):
    after(0.03, _once(log))


def arm_every(tc, log):
    e = tc.track(Entity())
    e.every(0.03, _once(log))


def arm_tween_on_done(tc, log):
    e = tc.track(Entity())
    e.x = 0.0
    tween(e["x"], 1.0, time=0.03, on_done=_once(log))


def arm_mode_sync(tc, log):
    e = tc.track(Entity())
    f = _once(log)

    def body(self):
        f()
    tc.w.on_update(lambda dt: setattr(e, "mode", body) if clock.frame == N else None)


def arm_mode_async(tc, log):
    e = tc.track(Entity())
    f = _once(log)

    async def body(self):
        await wait(0.03)
        f()
    e.mode = body


def arm_run_task(tc, log):
    f = _once(log)

    async def body():
        await wait(0.03)
        f()
    run_task(body)


def arm_exit_mode(tc, log):
    e = tc.track(Entity())
    f = _once(log)

    def first(self):
        pass

    @exit_mode(first)
    def _leave(self):
        f()

    def second(self):
        pass
    e.mode = first
    tc.w.on_update(lambda dt: setattr(e, "mode", second) if clock.frame == N else None)


def arm_on_update(tc, log):
    e = tc.track(Entity())
    f = _once(log)
    e.on_update = lambda self, dt: f() if clock.frame >= N else None


def arm_on_destroy(tc, log):
    e = tc.track(Entity())
    e.on_destroy = _once(log)
    after(0.03, e.destroy)


def arm_collide(tc, log):
    a, b = _pair(tc)
    collide("ex", "ey")(_once(log))
    tc.w.on_update(lambda dt: b.move_to(0, 0) if clock.frame == N else None)


def arm_collide_stay(tc, log):
    a, b = _pair(tc)
    collide_stay("ex", "ey")(_once(log))
    b.move_to(0, 0)


def arm_collide_exit(tc, log):
    a, b = _pair(tc)
    collide_exit("ex", "ey")(_once(log))
    b.move_to(0, 0)
    tc.w.on_update(lambda dt: b.move_to(300, 0) if clock.frame == N else None)


def arm_leave(tc, log):
    a, _b = _pair(tc)
    leave_playfield("ex")(_once(log))
    tc.w.on_update(lambda dt: a.move_to(99999, 0) if clock.frame == N else None)


def _card(tc, x=100.0, y=100.0):
    c = tc.track(Circle(center=(x, y), radius=20))
    c.clickable = True
    return c


def arm_hover(tc, log):
    c = _card(tc)
    hover(c)(_once(log))
    sm = tc.w.fw.shape_manager
    tc.w.on_update(lambda dt: sm.note_pointer(world_xy=(100.0, 100.0)) if clock.frame == N else None)


def arm_hover_exit(tc, log):
    c = _card(tc)
    hover_exit(c)(_once(log))
    sm = tc.w.fw.shape_manager
    sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(100.0, 100.0))
    tc.w.on_update(lambda dt: sm.note_pointer(world_xy=(-1e6, -1e6)) if clock.frame == N else None)


def arm_click(tc, log):
    c = _card(tc)
    c.on_click = _once(log)
    sm = tc.w.fw.shape_manager

    def press(dt):
        if clock.frame == N:
            sm.handle_mouse_down(100.0, 100.0, Mouse.BTN_LEFT)
            sm.handle_mouse_up(100.0, 100.0, Mouse.BTN_LEFT)
    tc.w.on_update(press)


def arm_drag_to(tc, log):
    c = _card(tc)
    drag_to(c)(_once(log))
    sm = tc.w.fw.shape_manager

    def drag(dt):
        if clock.frame == N:
            sm.handle_mouse_down(100.0, 100.0, Mouse.BTN_LEFT)
            sm.handle_mouse_move(140.0, 100.0)
            sm.handle_mouse_up(140.0, 100.0, Mouse.BTN_LEFT)
    tc.w.on_update(drag)


def arm_drop_by(tc, log):
    c = _card(tc)
    c.draggable = True
    target = tc.track(Rect(center=(200.0, 100.0), width=60, height=60))
    drop_by(target)(_once(log))
    sm = tc.w.fw.shape_manager

    def drag(dt):
        if clock.frame == N:
            sm.handle_mouse_down(100.0, 100.0, Mouse.BTN_LEFT)
            sm.handle_mouse_move(200.0, 100.0)
            sm.handle_mouse_up(200.0, 100.0, Mouse.BTN_LEFT)
    tc.w.on_update(drag)


def arm_widget_click(tc, log):
    b = tc.track(Button(label="Boom", on_click=_once(log)))
    wm = tc.w.fw.widget_manager

    def click(dt):
        if clock.frame == N:
            x, y = (b._x1 + b._x2) / 2.0, (b._y1 + b._y2) / 2.0
            wm.handle_mouse_down(x, y, Mouse.BTN_LEFT)
            wm.handle_mouse_up(x, y, Mouse.BTN_LEFT)
    tc.w.on_update(click)


def arm_widget_submit(tc, log):
    st.es_nome = ""
    ti = tc.track(TextInput(st["es_nome"], top_left=(10, 290), width=100, on_submit=_once(log)))
    wm = tc.w.fw.widget_manager

    def submit(dt):
        if clock.frame == N:
            ti.focus()
            wm.handle_char("a")
            wm.handle_key_down("ENTER")
            wm.handle_key("ENTER")
    tc.w.on_update(submit)


def arm_when(tc, log):
    e = tc.track(Entity())
    e.v = 0
    when(lambda: e.v > 0)(_once(log))
    after(0.03, lambda: setattr(e, "v", 1))


def arm_on_change(tc, log):
    e = tc.track(Entity())
    e.v = 0
    on_change(lambda: e.v)(_once(log))
    after(0.03, lambda: setattr(e, "v", 1))


def arm_formula(tc, log):
    """A formula that divides by a cell: the cell is zero for one read."""
    e = tc.track(Entity())
    e.v = 1.0
    e.w = 0.0
    st.es_den = 1.0
    e["w"] @= (lambda: e.v / st.es_den)

    def read(dt):
        if clock.frame == N and not log:
            log.append(clock.frame)
            st.es_den = 0.0
        try:
            e.w                      # a read inside the frame pulls the formula
        finally:
            st.es_den = 1.0
    tc.w.on_update(read)


def arm_until(tc, log):
    e = tc.track(Entity())
    f = _once(log)

    async def body(self):
        # The first check is eager (at the call); the engine polls the rest.
        await until(lambda: (f() if clock.frame >= N else False) or clock.frame > 1000)
    e.mode = body


def arm_flash_on_done(tc, log):
    c = tc.track(Circle(center=(0, 0), radius=5))
    c.flash(0.06, on_done=_once(log))


def arm_cover_on_done(tc, log):
    canvas.fade_out(0.03, on_done=_once(log))


def arm_sound_on_done(tc, log):
    e = tc.track(Entity())
    e.play_sound(tone(0.03), on_done=_once(log))


def arm_endless_builder(tc, log):
    canvas.layers.create("es_pista", below="default")
    f = _once(log)

    def piece(slot):
        f()
        return Rect(top_left=(slot.left, 20), width=slot.right - slot.left, height=20)
    tc._endless_layer = "es_pista"
    tc.w.on_update(lambda dt: Endless("es_pista", piece, step=100) if clock.frame == N else None)


def arm_act_setup(tc, log):
    f = _once(log)

    class Vazia(Act):
        pass

    class Ruim(Act):
        def setup(self):
            f()
    tc.w.begin_game(Vazia)
    after(0.03, lambda: change_act(Ruim))


def arm_act_on_update(tc, log):
    f = _once(log)

    class Corre(Act):
        def on_update(self, dt):
            if clock.frame >= N:
                f()
    tc.w.begin_game(Corre)


def arm_act_on_destroy(tc, log):
    f = _once(log)

    class Vazia(Act):
        pass

    class Sai(Act):
        def on_destroy(self):
            f()
    tc.w.begin_game(Sai)
    after(0.03, lambda: change_act(Vazia))


SITES: List[Site] = [
    Site("update", arm_update, ["update"]),
    Site("after", arm_after, ["after"]),
    Site("every", arm_every, ["every"]),
    Site("tween on_done", arm_tween_on_done, ["tween"]),
    Site("mode body (sync)", arm_mode_sync, ["mode", "on_mode"]),
    Site("mode body (async)", arm_mode_async, ["wait"]),
    Site("task body", arm_run_task, ["run_task"]),
    Site("@exit_mode", arm_exit_mode, ["exit_mode"]),
    Site("on_update", arm_on_update, ["on_update"]),
    Site("on_destroy", arm_on_destroy, ["on_destroy"]),
    Site("collide enter", arm_collide, ["collide", "collide_with", "on_collide"]),
    Site("collide stay", arm_collide_stay, ["collide_stay", "collide_with_stay", "on_collide_stay"]),
    Site("collide exit", arm_collide_exit, ["collide_exit", "collide_with_exit", "on_collide_exit"]),
    Site("leave_playfield", arm_leave, ["leave_playfield", "on_leave_playfield"]),
    Site("hover", arm_hover, ["hover", "on_hover"]),
    Site("hover_exit", arm_hover_exit, ["hover_exit", "on_hover_exit"]),
    Site("click", arm_click, ["click", "on_click"]),
    Site("drag_to", arm_drag_to, ["drag_to", "drag_over", "on_drag_to", "on_drag_over"]),
    Site("drop_by", arm_drop_by, ["drop_by", "on_drop_by"]),
    Site("widget on_click", arm_widget_click, ["Button", "SpriteButton", "CheckBox", "Menu"]),
    Site("widget on_submit", arm_widget_submit, ["TextInput"]),
    Site("@when", arm_when, ["when"]),
    Site("@on_change", arm_on_change, ["on_change"]),
    Site("formula", arm_formula, ["Attribute", "State"], raises=ZeroDivisionError),
    Site("until predicate", arm_until, ["until"]),
    Site("flash on_done", arm_flash_on_done, ["flash", "blink", "dissolve_out"]),
    Site("cover on_done", arm_cover_on_done, ["fade_out", "fade_in"]),
    Site("sound on_done", arm_sound_on_done, ["play_sound", "Sound"]),
    Site("Endless builder", arm_endless_builder, ["Endless"]),
    Site("Act.setup", arm_act_setup, ["Act", "change_act"]),
    Site("Act.on_update", arm_act_on_update, []),
    Site("Act.on_destroy", arm_act_on_destroy, []),
]

# Exports that take or run author callbacks but need no site of their own.
EXCUSED: Dict[str, str] = {
    "parallel": "composes Handles; its branches are after / tween / wait sites",
    "race": "composes Handles; its branches are after / tween / wait sites",
    "Handle": "the value, not a site",
    "Slider": "no author callback parameter (binds a cell)",
    "DropDown": "no author callback parameter (binds a cell)",
    "Level": "builds shapes; no callback",
    "History": "engine-fed; no author callback",
    "Contrail": "engine-fed; no author callback",
    "Microphone": "no author callback",
    "unregister_event": "removes a watch",
    "on_destroy_of": "not an export",
}

# Shrink-only: site name -> reason (a finding or a settled contract).
KNOWN: Dict[str, str] = {
}

CALLBACK_EXPORTS = {
    "when", "on_change", "click", "hover", "hover_exit", "drag_to", "drag_over", "drop_by",
    "collide", "collide_stay", "collide_exit", "collide_with", "collide_with_stay",
    "collide_with_exit", "leave_playfield", "exit_mode", "on_mode", "after", "every",
    "tween", "until", "wait", "parallel", "race", "play_sound", "Endless", "Act",
    "change_act", "Button", "SpriteButton", "CheckBox", "Menu", "TextInput", "Slider",
    "DropDown", "Attribute", "State", "Handle", "Level", "History", "Contrail",
    "Microphone", "unregister_event", "Sound", "run_task",
}


class ErrorSiteCase(SystemTestCase, unittest.TestCase):
    world_draw = False

    def setUp(self):
        super().setUp()
        self._endless_layer = None

    def tearDown(self):
        with quiet():
            sm = self.w.fw.shape_manager
            try:
                sm.handle_mouse_up(-1e6, -1e6, Mouse.BTN_LEFT)
            except Exception:
                pass
            sm.note_pointer(view_xy=(-1e6, -1e6), world_xy=(-1e6, -1e6))
            if self._endless_layer and self._endless_layer in canvas.layers:
                from hypothesis_support import registry
                for o in list(registry().live_objects()):
                    if isinstance(o, Endless) and o.is_alive:
                        o.destroy()
                try:
                    canvas.layers[self._endless_layer].delete(destroy_shapes=True)
                except Exception:
                    pass
        super().tearDown()

    def _run_site(self, site: Site) -> None:
        w = self.w
        log: List[int] = []
        ticks: List[int] = []
        bystander = self.track(Entity())
        bystander.every(1e-4, lambda: ticks.append(clock.frame))
        site.arm(self, log)
        raised = 0
        with quiet():
            for _ in range(14):
                try:
                    w.step(1)
                except site.raises:
                    raised += 1
        msgs = []
        if raised != 1:
            msgs.append(f"the error reached the frame {raised} times, want exactly once "
                        f"(fired at frames {log})")
        if not log:
            msgs.append("the site never fired")
        ss = get_scena_system()
        if ss.update_manager.deferring:
            msgs.append("frame batch left open")
        if len(ss.update_manager._dirty_stack):
            msgs.append("dirty stack not empty")
        n = len(ticks)
        with quiet():
            w.step(3)
        if len(ticks) <= n:
            msgs.append("frames after the error do not run (a bystander's every stopped)")
        z = w.zombies()
        if z:
            msgs.append("registries hold a destroyed object: "
                        + ", ".join(f"{h}: {type(o).__name__}" for h, o in z[:5]))
        sm = w.fw.shape_manager
        for attr in ("_pressed_shape", "_hover_target"):
            obj = getattr(sm, attr, None)
            if obj is not None and not getattr(obj, "is_alive", True):
                msgs.append(f"pointer state {attr} names a destroyed shape")
        if msgs:
            if site.name in KNOWN:
                self.skipTest(f"known: {KNOWN[site.name]}")
            self.fail(f"{site.name}:\n  " + "\n  ".join(msgs))
        elif site.name in KNOWN:
            self.fail(f"KNOWN entry no longer fails; remove it: {site.name!r}")


class TestEverySite(ErrorSiteCase):
    pass


for _site in SITES:
    setattr(TestEverySite, "test_" + "".join(ch if ch.isalnum() else "_" for ch in _site.name),
            (lambda s: lambda self: self._run_site(s))(_site))


class TestAxes(unittest.TestCase):
    def test_every_callback_export_is_covered_or_excused(self):
        covered = {c for s in SITES for c in s.covers}
        missing = sorted(n for n in CALLBACK_EXPORTS if n not in covered and n not in EXCUSED)
        self.assertFalse(missing, f"callback-taking exports with no site: {missing}")

    def test_callback_exports_exist(self):
        for n in CALLBACK_EXPORTS:
            self.assertIn(n, scena.__all__, n)

    def test_every_on_attribute_of_a_graphic_is_covered(self):
        names = sorted(n for n in dir(Circle) if n.startswith("on_") and not n.startswith("on__"))
        covered = {c for s in SITES for c in s.covers}
        missing = [n for n in names if n not in covered and n not in EXCUSED]
        self.assertFalse(missing, f"on_* attributes with no site: {missing}")

    def test_site_names_are_unique(self):
        names = [s.name for s in SITES]
        self.assertEqual(len(names), len(set(names)))


class TestCanaries(unittest.TestCase):
    def test_catches_a_frame_batch_left_open(self):
        from scena.state import ScenaSystem
        assert_catches(self, "test_sys_error_sites.TestEverySite.test_after",
                       [(ScenaSystem, "end_frame_batch", lambda self: None)],
                       "a frame body that leaves the batch open after an error")

if __name__ == "__main__":
    unittest.main()
