"""Engine bugs planted to prove each law's check can fail (canaries).

``PLANTS[law]()`` returns fresh ``mock.patch.object`` triples for
``laws.harness.record(..., patches=...)``. Each plant is a realistic bug of
the class the law guards (a destroy deferred to the end of the frame, a
parked actor that keeps running), not a trace edit: the model must see it
through the engine, as it would see a real regression.
"""
from __future__ import annotations

import importlib
import os
import sys
from typing import Callable, Dict, List, Tuple

import scena.act as act
import scena.entity as ent
import scena.orchestration as orch
import scena.process as proc
import scena.registry as reg

importlib.import_module("scena.collision")
col = sys.modules["scena.collision"]      # the package re-exports a facade by that name

Patches = List[Tuple[object, str, object]]
_FIXTURES = os.path.normcase(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures"))


def _registry():
    from scena.canvas import ScenaCanvas
    return ScenaCanvas.get_current().registry


def f1_skip_the_tick() -> Patches:
    """F1: the frame body forgets the process tick."""
    return [(orch, "tick_processes", lambda: None)]


def f2_timers_in_collision() -> Patches:
    """F2: the collision step ticks timers (a refactor merged two loops)."""
    real = col.CollisionSystem.step

    def step(self):
        real(self)
        proc.get_scheduler().tick()
    return [(col.CollisionSystem, "step", step)]


def l1_deferred_destroy() -> Patches:
    """L1: destroy() queues the teardown for the end of the frame."""
    real_destroy = reg.Registry.destroy
    real_predraw = orch.ScenaFramework._tick_pre_draw
    queue: list = []

    def destroy(self, obj):
        if act.get_act_manager().changing:
            return real_destroy(self, obj)
        queue.append((self, obj))

    def predraw(self):
        real_predraw(self)
        while queue:
            r, o = queue.pop(0)
            real_destroy(r, o)
    return [(reg.Registry, "destroy", destroy), (orch.ScenaFramework, "_tick_pre_draw", predraw)]


def l2_hook_twice() -> Patches:
    """L2: on_destroy is not cleared before it runs (a re-entrant destroy fires it again)."""
    def fire(item):
        hook = getattr(item, "_on_destroy", None)
        if hook is None:
            return
        proc.run_on_destroy(hook, item)
        proc.run_on_destroy(hook, item)
        object.__setattr__(item, "_on_destroy", None)
    return [(ent, "_fire_on_destroy", fire)]


def l3_dead_update() -> Patches:
    """L3: the on_update fleet keeps every actor it ever ran, dead or not."""
    seen: Dict[int, tuple] = {}

    def tick_on_update(self, world_dt):
        self._refresh_update_dense()
        for item, fn, form in list(self._update_dense):
            seen.setdefault(id(item), (item, fn, form))
        for item, fn, form in list(seen.values()):
            proc._call_update(fn, form, item, world_dt)
    return [(proc.Scheduler, "cancel_owner", lambda self, *a, **k: None),
            (proc.Scheduler, "_tick_on_update", tick_on_update)]


def l4_park_does_not_stop() -> Patches:
    """L4: park marks the actor but leaves it active."""
    real = ent.Entity._park_self

    def park(self):
        real(self)
        object.__setattr__(self, "_active", True)
    return [(ent.Entity, "_park_self", park)]


def l5_hooks_during_teardown() -> Patches:
    """L5: the act change fires each on_destroy as it tears that object down."""
    return [(act.ActManager, "_fire_hook", lambda self, obj, first_error: first_error)]


def _made_by_a_fixture(o) -> bool:
    """Made by a laws fixture (never a process-wide object such as ``st``:
    a plant must not damage what later runs use)."""
    site = o.__dict__.get("_site")
    return bool(site) and os.path.normcase(os.path.abspath(site[0])).startswith(_FIXTURES)


def l6_top_level_dies() -> Patches:
    """L6: the act change's doomed list takes top-level objects too."""
    real = act.ActManager._doomed

    def doomed(self):
        out = real(self)
        for o in _registry().live_objects():
            if (getattr(o, "_owner", None) is None and o not in out and not isinstance(o, act.Act)
                    and not getattr(o, "_scena_internal", False) and getattr(o, "is_alive", False)
                    and _made_by_a_fixture(o)):
                out.append(o)
        return out
    return [(act.ActManager, "_doomed", doomed)]


def c1_stays_enter_again() -> Patches:
    """C1: the enter loop also walks the pairs that were already touching."""
    real = col.CollisionSystem._dispatch_step

    def dispatch_step(self, current, entered_order, stayed, exited, colliders_for_key,
                      _sort_keys, id_to_collider):
        self._enter_pending |= set(stayed)
        return real(self, current, list(entered_order) + _sort_keys(set(stayed)), stayed, exited,
                    colliders_for_key, _sort_keys, id_to_collider)
    return [(col.CollisionSystem, "_dispatch_step", dispatch_step)]


def c2_exits_first() -> Patches:
    """C2: a refactor runs the exit loop before the enter and stay loops."""
    real = col.CollisionSystem._dispatch_step

    def dispatch_step(self, current, entered_order, stayed, exited, colliders_for_key,
                      _sort_keys, id_to_collider):
        real(self, current, [], set(), exited, colliders_for_key, _sort_keys, id_to_collider)
        real(self, current, entered_order, stayed, set(), colliders_for_key, _sort_keys,
             id_to_collider)
    return [(col.CollisionSystem, "_dispatch_step", dispatch_step)]


def c4_parked_body_in_play() -> Patches:
    """C4: a park leaves the body colliding and in play this step (two guards
    keep a parked body out of its other pairs: the in-play check and the
    collider leaving collision; the plant breaks both)."""
    return [(col.CollisionSystem, "_collider_in_play", lambda self, c: True),
            (ent.Entity, "_leave_collision", lambda self: None)]


def c5_exits_replayed() -> Patches:
    """C5: every exit is run again at the next step (a stale pending set)."""
    real_exit = col.CollisionSystem._run_exit
    real_step = col.CollisionSystem._dispatch_step
    again: list = []

    def run_exit(self, ca, info, runs, was):
        again.append((self, ca, info, runs, was))
        real_exit(self, ca, info, runs, was)

    def dispatch_step(self, current, entered_order, stayed, exited, colliders_for_key,
                      _sort_keys, id_to_collider):
        held = list(again)
        again.clear()
        for args in held:
            real_exit(*args)
        real_step(self, current, entered_order, stayed, exited, colliders_for_key, _sort_keys,
                  id_to_collider)
    return [(col.CollisionSystem, "_run_exit", run_exit),
            (col.CollisionSystem, "_dispatch_step", dispatch_step)]


def c7_dead_kept_in_contacts() -> Patches:
    """C7: a destroy does not end its body's contacts nor drop its collider,
    and the step's prune skips it: the old contact is still committed at the
    next step (three guards keep it out; the plant breaks the three)."""
    return [(col.CollisionSystem, "_end_contacts_of", lambda self, c, emit=True: None),
            (col.CollisionSystem, "_drop_destroyed_collider", lambda self, item, c: None),
            (col.CollisionSystem, "_prune_dead", lambda self: None)]


def c8_resolve_first() -> Patches:
    """C8: resolve runs before the step's handlers."""
    real = col.CollisionSystem._dispatch_step

    def dispatch_step(self, current, entered_order, stayed, exited, colliders_for_key,
                      _sort_keys, id_to_collider):
        if self._resolve_enabled:
            self._apply_auto_resolve(current, id_to_collider)
        real(self, current, entered_order, stayed, exited, colliders_for_key, _sort_keys,
             id_to_collider)
    return [(col.CollisionSystem, "_dispatch_step", dispatch_step)]


def i1_act_change_drops_keys() -> Patches:
    """I1 (PD7): an act change forgets the script's keys and presses."""
    def forget(self):
        self._keys_down.clear()
        self._presses.clear()
    return [(orch.CanvasManager, "forget_act_input", forget)]


def i2_up_without_its_down() -> Patches:
    """I2 (X-life-3): the script's mouse up no longer needs the script's down
    (a press a widget took, released after the widget left, reaches it)."""
    def handle_mouse_up(self, x, y, button, view=None):
        orch.callback_if_exists(self, "on_mouse_up", x, y, button, x, y)
        self._presses.pop(button, None)
    return [(orch.CanvasManager, "handle_mouse_up", handle_mouse_up)]


def i3_every_repeat_to_the_script() -> Patches:
    """I3 (W-P4): every repeat reaches ``on_key``, old act or not."""
    return [(orch.CanvasManager, "repeats_to_script", lambda self, key_name: True)]


def i4_chars_to_the_focused_box() -> Patches:
    """I4 (LW5): a character goes to whatever box has focus now."""
    def handle_char(self, window, char_num):
        char = chr(char_num)
        wm = self.widget_manager
        wm._char_to_script = False
        if not wm.handle_char(char) and not wm._modal_consumes():
            self.canvas_manager.handle_char(char)
    return [(orch.ScenaFramework, "_handle_char", handle_char)]


def i5_widgets_claim_a_given_up_release() -> Patches:
    """I5: the widget side claims the release of a press its widget gave up."""
    real = orch.WidgetManager.handle_mouse_up

    def handle_mouse_up(self, x, y, button):
        rec = self.mouse_down_widget_by_button.get(button)
        if rec is not None and rec.widget is None:
            self.mouse_down_widget_by_button.pop(button)
            return True
        return real(self, x, y, button)
    return [(orch.WidgetManager, "handle_mouse_up", handle_mouse_up)]


def t1_due_without_tolerance() -> Patches:
    """T1 (PM8): "is it due" compares summed float time strictly."""
    return [(proc, "reached", lambda elapsed, target: elapsed >= target)]


def t2_new_work_ticks_at_once() -> Patches:
    """T2: work made inside the tick is ticked in that same tick (the tick
    walks its live buckets, not a snapshot)."""
    real_add = proc.Scheduler.add
    real_tick = proc.Scheduler.tick
    made: list = []

    def add(self, handle):
        out = real_add(self, handle)
        if getattr(self, "_iterating", False) and getattr(handle, "kind", None) == "after":
            made.append(handle)
        return out

    def tick(self):
        real_tick(self)
        from scena import clock
        while made:
            self._tick_once(made.pop(0), clock.dt)
    return [(proc.Scheduler, "add", add), (proc.Scheduler, "tick", tick)]


def t3_parked_owner_ticks() -> Patches:
    """T3: the scheduler's view of ``active`` misses the park (the actor is
    parked; its timers keep counting and firing)."""
    prop = ent.Entity.__dict__["active"]
    return [(ent.Entity, "active", property(lambda self: not getattr(self, "_destroyed", False),
                                            prop.fset))]


def t4_every_uncapped() -> Patches:
    """T4: one tick fires every interval a hitch owes."""
    return [(proc, "_every_fire_budget", lambda interval: 10 ** 9)]


def t6_dead_owner_registers() -> Patches:
    """T6: work on a destroyed actor is registered (the add's check is gone)."""
    real = proc.Scheduler.add

    def add(self, handle):
        owner = handle.owner
        if owner is not None and getattr(owner, "_destroyed", False):
            object.__setattr__(owner, "_destroyed", False)
            try:
                return real(self, handle)
            finally:
                object.__setattr__(owner, "_destroyed", True)
        return real(self, handle)
    return [(proc.Scheduler, "add", add)]


PLANTS: Dict[str, Callable[[], Patches]] = {
    "T1": t1_due_without_tolerance,
    "T2": t2_new_work_ticks_at_once,
    "T3": t3_parked_owner_ticks,
    "T4": t4_every_uncapped,
    "T6": t6_dead_owner_registers,
    "I1": i1_act_change_drops_keys,
    "I2": i2_up_without_its_down,
    "I3": i3_every_repeat_to_the_script,
    "I4": i4_chars_to_the_focused_box,
    "I5": i5_widgets_claim_a_given_up_release,
    "C1": c1_stays_enter_again,
    "C2": c2_exits_first,
    "C4": c4_parked_body_in_play,
    "C5": c5_exits_replayed,
    "C7": c7_dead_kept_in_contacts,
    "C8": c8_resolve_first,
    "F1": f1_skip_the_tick,
    "F2": f2_timers_in_collision,
    "L1": l1_deferred_destroy,
    "L2": l2_hook_twice,
    "L3": l3_dead_update,
    "L4": l4_park_does_not_stop,
    "L5": l5_hooks_during_teardown,
    "L6": l6_top_level_dies,
}
