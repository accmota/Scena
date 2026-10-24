"""Shared harness for the system / sub-system suites (``tests/test_sys_*.py``).

Not a test module (no ``test_`` prefix). Builds on ``hypothesis_support``.

The system suites drive the **real** frame body headless and deterministic:
``ScenaFramework._simulate_frame(dt=…)`` (the same method ``run()`` calls) then
optionally ``_draw_frame()`` onto a CPU raster surface. GLFW polling and
``glViewport`` are patched; the mixer runs offline (``tick_audio`` pumps it).

What lives here:

* ``SystemWorld`` — a ``WorldTracker`` that also resets what the hyp suites
  leave alone (collision, bounds, cover, FX registries, clock, ready /
  recently, camera, post stack); no time source is pinned: every one reads
  the frame clock it reads in production (Scena Design, "Clocks").
  ``world.step(n, dt, draw)`` runs frames; ``world.probe`` records hooks.
* ``census()`` — a snapshot of every registry that can hold an actor
  (graph, events, scheduler, collision, bounds, registry, FX, mixer, widgets).
  ``diff_census`` names the holder that moved.
* ``zombies()`` — objects any registry still references although they are
  dead. A non-empty list is a lifetime bug.
* ``Probe`` — author hooks append ``(frame, tag, owner_alive)``; the "no
  callback for a dead owner" check reads it.
* ``assert_collected`` — a destroyed actor must be garbage once the test drops
  its own references; on failure the referrer chain names the holder.

    python -m unittest tests.test_sys_lifetime -v
"""
from __future__ import annotations

import gc
import math
import os
import sys
import warnings
import weakref
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import skia  # noqa: E402

from hypothesis_support import BOOT_SIZE, WorldTracker, boot, quiet, registry  # noqa: E402
from graph_support import full_collect  # noqa: E402,F401  (re-exported)

import scena.orchestration as orch  # noqa: E402
from scena import ANYTHING, canvas, clock, init  # noqa: E402
from scena.audio_mixer import get_mixer, make_sine  # noqa: E402
from scena.audio import Sound  # noqa: E402
from scena.bounds import get_bounds_system, reset_bounds_system  # noqa: E402
from scena.collision import get_collision_system, reset_collision_system  # noqa: E402
from scena.cover import reset_cover  # noqa: E402
from scena.level_source import reset_level_sources  # noqa: E402
from scena.orchestration import ScenaFramework  # noqa: E402
from scena.process import get_scheduler, clear_author_error  # noqa: E402
from scena.state import get_scena_system  # noqa: E402
import scena.cover as _cover  # noqa: E402
import scena.events as _events  # noqa: E402
import scena.history as _history  # noqa: E402
import scena.spatial_fx as _spatial_fx  # noqa: E402
import scena.transients as _transients  # noqa: E402
from scena.act import _reset_act_manager  # noqa: E402
import scena.gc_policy as gc_policy  # noqa: E402

FRAME = 1.0 / 60.0


# --------------------------------------------------------------------------
# Probe
# --------------------------------------------------------------------------

class Probe:
    """Records author-hook calls. ``hook(tag, owner)`` wraps a callable.

    Each record is ``(frame, tag, owner_alive)``. ``dead_calls()`` lists the
    records made while their owner was already destroyed — the
    use-after-destroy bug class.
    """

    def __init__(self) -> None:
        self.records: List[Tuple[int, str, bool]] = []

    def hit(self, tag: str, owner: Any = None) -> None:
        alive = True if owner is None else bool(getattr(owner, "is_alive", True))
        self.records.append((clock.frame, tag, alive))

    def hook(self, tag: str, owner: Any = None, then: Optional[Callable] = None):
        # Hold the owner weakly: the probe must not keep an actor alive.
        ref = weakref.ref(owner) if owner is not None else None

        def fn(*_a, **_k):
            o = ref() if ref is not None else None
            if ref is not None and o is None:
                self.records.append((clock.frame, tag, False))
            else:
                self.hit(tag, o)
            if then is not None:
                return then()
        return fn

    def count(self, tag: str) -> int:
        return sum(1 for _f, t, _a in self.records if t == tag)

    def tags(self) -> List[str]:
        return [t for _f, t, _a in self.records]

    def frames(self, tag: str) -> List[int]:
        return [f for f, t, _a in self.records if t == tag]

    # Documented teardown hooks that run for the dying body itself, after
    # ``is_alive`` turned False (Collision Design § Handlers: "the dying body,
    # while it still exists").
    # The dying body's own exit hooks run while it is still alive (review
    # 2026-10-09 X-life-5), so no hook is excused from the dead-call check.
    TEARDOWN_TAGS: Tuple[str, ...] = ()

    def dead_calls(self, allow: Iterable[str] = TEARDOWN_TAGS) -> List[Tuple[int, str, bool]]:
        ok = set(allow)
        return [r for r in self.records if not r[2] and r[1] not in ok]

    def clear(self) -> None:
        self.records.clear()


# --------------------------------------------------------------------------
# World
# --------------------------------------------------------------------------

def _noop(*_args, **_kwargs) -> None:
    return None


def reset_input_state() -> None:
    """A fresh keyboard, mouse and pointer: nothing held, pending, hovered or
    pressed from an earlier world (review 2026-10-09 X-life-8: a key held and
    a hover target from world 1 reached world 2, whose first frame ran world
    1's ``on_hover_exit``). ``ProgramRun`` and ``SystemWorld`` both start here.
    """
    fw = ScenaFramework._instance
    if fw is None:
        return
    keys = getattr(fw, "keys", None)
    if keys is not None:
        keys._pressed_keys.clear()
        keys._pending_edges.clear()
        keys._once_fired.clear()
        keys._input_masked = False
    m = getattr(fw, "mouse", None)
    if m is not None:
        m._pressed_buttons.clear()
        # Another suite may leave it at a junk position (test_api_robustness
        # fuzzes it), masked, or with a click history that would make the
        # first click a double click.
        m._input_masked = False
        m._mask_latch_buttons.clear()
        m._widget_buttons.clear()
        for hist in (m._last1_click_pos, m._last1_click_time,
                     m._last2_click_pos, m._last2_click_time):
            hist.clear()
        m._sync_position(0.0, 0.0)
        m._end_frame()
    sm = getattr(fw, "shape_manager", None)
    if sm is not None:
        # No pointer yet (a cursor outside the window): no hover target, no
        # press, no remembered position from the previous world.
        sm._set_pressed(None)
        sm._dragging = False
        sm._hover_target = None
        sm._hover_entered = None
        sm._ptr_view = sm._ptr_world = None
        sm._resolved_sig = None
    cm = getattr(fw, "canvas_manager", None)
    if cm is not None:
        cm.clear_input()
    wm = getattr(fw, "widget_manager", None)
    if wm is not None:
        wm.mouse_over_widget = None
        wm.pressed_widget = None
        wm.focused_widget = None
        wm.mouse_down_widget_by_button.clear()
        wm.last_click = None
        wm._claimed_down.clear()
        wm._key_mods = 0
        modal = wm.modal_widget
        if modal is not None and not getattr(modal, "is_alive", True):
            wm.modal_widget = None
        # Widget layout starts from the top-left column, not from wherever the
        # last HUD item anyone placed left the cursor (S4-5).
        wm.reset_hud_stack()


def reset_system_globals() -> None:
    """Reset the singletons ``hypothesis_support.reset_globals`` leaves alone.

    The act manager goes first: its teardown puts the sealed game's leave
    handlers and resolve pairs back, so resetting those singletons before it
    let an old test's rules into every later world (review 2026-10-09 S4-8).
    """
    _reset_act_manager()
    reset_collision_system()
    from scena.interaction import _reset_tag_rules
    _reset_tag_rules()      # a game's @click(group[...]) rules, like its @collide pairs
    reset_bounds_system()
    reset_cover()
    _transients._active_shapes.clear()
    _spatial_fx._active_fx.clear()
    _history._active_histories.clear()
    import builtins
    for name, attr in (("ready", "_timers"), ("recently", "_slots")):
        mgr = getattr(builtins, name, None)
        if mgr is not None:
            getattr(mgr, attr).clear()
    clock.scale = 1.0
    clock.paused = False
    clock._dt = 0.0
    clock._time = 0.0
    clock._real_dt = 0.0
    clock._real_time = 0.0
    # Presentation time (fades, post-fx): a fresh process starts it at 0 too.
    # Left running, a second run's fade read ``(t - t0) / d`` on another base
    # and differed in the last bits (found by the laws E0 equation, LW1).
    clock._ui_time = 0.0
    clock._frame = 0
    canvas.reset_view()
    canvas.effects.clear()
    clear_author_error()
    reset_input_state()
    reset_level_sources()


# World settings ``reset_system_globals`` puts in their fresh state (a camera
# that follows the design size, no effects, clock at 1, resolve on). Writing a
# snapshot back is not the same for them: a restored camera pins its origin.
WORLD_RESETS = frozenset({"camera", "effects", "clock", "collision.resolve_enabled",
                          "hud_stack"})


def reset_world_settings() -> None:
    """Every world setting an act change restores (``act.WORLD_SETTINGS``) back
    to the framework default, as a fresh process has it: camera, background
    base and fields, post effects, playfield, clock, resolve, floor, default layer,
    paint defaults, HUD column cursor. ``ProgramRun`` starts from here (one program per process
    in real use); guard: ``test_prog_isolation.TestResetWorldSettings``.
    """
    from scena.style import PaintState
    fw = ScenaFramework.get_instance()
    canvas.reset_view()
    bs = fw.background_stack
    bs.reset_base()
    bs.clear()
    bs.enabled = True
    canvas.effects.clear()
    fw.post_fx_stack.enabled = True
    pf = canvas.playfield
    pf._pad = 0.25
    pf._explicit = None
    clock.scale = 1.0
    clock.paused = False
    get_collision_system().resolve_enabled = True
    import importlib
    get_collision_system().floor = importlib.import_module("scena.collision")._FLOOR_DEFAULT
    layers = registry().layers
    if "default" in layers:
        layers.default = "default"
    PaintState._reset_defaults()
    wm = getattr(fw, "widget_manager", None)
    if wm is not None:
        wm.reset_hud_stack()


class SystemWorld(WorldTracker):
    """A headless world that steps real frames.

    Use as ``with system_world() as w:`` or through ``SystemTestCase``.
    """

    def __init__(self, *, draw: bool = True, quarantine: bool = True) -> None:
        super().__init__()
        reset_system_globals()
        # Every act-level world setting (playfield, layer default, background,
        # paint defaults …) as the world found it; teardown gives it back.
        # ``test_noop_cost`` pinned the auto playfield to 400x300 edges and
        # every later program in the process lost its shots there (O8).
        from scena.act import WORLD_SETTINGS
        self._settings_start = [(w, w.snapshot()) for w in WORLD_SETTINGS]
        # GC freeze off: a frozen heap would hide a real leak from census /
        # assert_collected. The policy itself: tests/test_gc_freeze.py.
        self._gc_freeze_was = gc_policy.gc_freeze_enabled()
        gc_policy.set_gc_freeze(False)
        self.draw_default = draw
        self.probe = Probe()
        self.fw = fw = ScenaFramework.get_instance()
        self._saved = dict(
            setup=fw.setup, update=fw.update, post_draw=fw.post_draw,
            _fx_auto=fw._fx_auto, _first_act=fw._first_act,
            _was_using_post=fw._was_using_post,
            _drawing_surface=fw._drawing_surface,
            _drawing_canvas=fw._drawing_canvas,
            skia_canvas=fw._scena_draw.skia_canvas,
        )
        fw.setup = lambda scena_canvas: None
        fw.update = lambda dt, scena_canvas: None
        fw.post_draw = lambda skia_canvas, scene_image=None: None
        fw._fx_auto = False
        fw._was_using_post = False
        # The design size boot() set: ~40 modules init their own in setUp, and
        # a later module's pixels at fixed points read under it (the deep
        # serial pass, 2026-10-24: a rect at y 150 drawn 300 px low after an
        # 800 x 600 init; WP41). The size found is given back at teardown.
        self._design_found = (fw.design_width, fw.design_height)
        if self._design_found != BOOT_SIZE:
            init(width=BOOT_SIZE[0], height=BOOT_SIZE[1])
        w = max(1, int(fw.fb_width or 400))
        h = max(1, int(fw.fb_height or 300))
        self.surface = skia.Surface(w, h)
        fw._drawing_surface = self.surface
        fw._drawing_canvas = self.surface.getCanvas()
        fw._scena_draw.skia_canvas = fw._drawing_canvas
        self._patches = []
        for target, attr in ((orch.glfw, "poll_events"), (orch.GL, "glViewport")):
            # A plain no-op, not a MagicMock: a mock records every call, which
            # a long run sees as a heap leak.
            p = mock.patch.object(target, attr, new=_noop)
            p.start()
            self._patches.append(p)
        # Shape transients and the cover (presentation time), SpatialFx
        # (world time) all read the frame clock in production, so none is
        # pinned: a pin would test a clock the shipped code does not read
        # (review 2026-10-09, S1-7; transients since LW6).
        _transients.set_now_fn(None)
        _spatial_fx.set_now_fn(None)
        _cover.set_now_fn(None)
        self.frames_run = 0
        # Debris another test module left (dead but still registered) is not
        # this world's bug: ``zombies()`` / ``assertNoZombies`` skip it.
        self.preexisting_zombies = {id(o) for _h, o in zombies(ignore=())}
        self._quarantined = []
        if quarantine:
            self.quarantine()

    def quarantine(self) -> None:
        """Park the live actors another module left behind.

        They would draw / tick / collide in this world's frames (lazily growing
        the graph, adding handles). Teardown restores them. Parking moves
        census keys (``registry.draw_live``): a census compared with one taken
        after teardown must be taken before this call (``ProgramRun`` passes
        ``quarantine=False`` and calls it after ``census_before``).
        """
        with quiet():
            for obj in registry().live_objects():
                if getattr(obj, "is_alive", False) and hasattr(type(obj), "active") \
                        and getattr(obj, "active", False):
                    try:
                        obj.active = False
                        self._quarantined.append(weakref.ref(obj))
                    except Exception:
                        pass

    def zombies(self) -> List[Tuple[str, Any]]:
        return zombies(ignore=self.preexisting_zombies)

    # -- driving ----------------------------------------------------------
    def on_update(self, fn: Optional[Callable[[float], Any]]) -> None:
        """Install the script ``update(dt)`` (``None`` = no-op)."""
        self.fw.update = (lambda dt, scena_canvas: None) if fn is None else (
            lambda dt, scena_canvas=None: fn(dt))

    def begin_game(self, first_act=None, setup: Optional[Callable] = None) -> None:
        """End the top level the way ``run()`` does (``fw._begin_game``).

        Everything alive now becomes the game; ``first_act`` (an Act class)
        is built next. ``setup`` is the script-level ``setup(canvas)`` hook.
        """
        if setup is not None:
            self.fw.setup = setup
        self.fw._begin_game(first_act)

    def step(self, n: int = 1, dt: float = FRAME, draw: Optional[bool] = None) -> None:
        do_draw = self.draw_default if draw is None else draw
        fw = self.fw
        for _ in range(int(n)):
            fw._simulate_frame(dt=dt)
            if do_draw:
                # Post FX draw too: with no GL context the scene / FX render
                # targets are raster surfaces (``fw._offscreen_surface``).
                fw._draw_frame()
                fw._scene_image = None
            self.frames_run += 1

    def step_until(self, pred: Callable[[], bool], max_frames: int = 600,
                   dt: float = FRAME, draw: Optional[bool] = None) -> int:
        for i in range(max_frames):
            if pred():
                return i
            self.step(1, dt=dt, draw=draw)
        if pred():
            return max_frames
        raise AssertionError(f"condition not reached in {max_frames} frames")

    def seconds(self, t: float, dt: float = FRAME, draw: Optional[bool] = None) -> None:
        self.step(int(math.ceil(t / dt - 1e-9)), dt=dt, draw=draw)

    # -- teardown ---------------------------------------------------------
    def teardown(self, *, strict: bool = True) -> None:
        fw = self.fw
        try:
            super().teardown(strict=strict)
        finally:
            for p in self._patches:
                p.stop()
            self._patches.clear()
            with quiet():
                for ref in self._quarantined:
                    obj = ref()
                    if obj is not None and getattr(obj, "is_alive", False):
                        try:
                            obj.active = True
                        except Exception:
                            pass
            self._quarantined.clear()
            _transients.set_now_fn(None)
            _spatial_fx.set_now_fn(None)
            _cover.set_now_fn(None)
            fw._scena_draw.skia_canvas = self._saved.pop("skia_canvas")
            for k, v in self._saved.items():
                setattr(fw, k, v)
            if (fw.design_width, fw.design_height) != self._design_found:
                init(width=self._design_found[0], height=self._design_found[1])
            gc_policy.thaw_world()
            gc_policy.set_gc_freeze(self._gc_freeze_was)
            with quiet():
                for w, value in self._settings_start:
                    try:
                        w.restore(value)
                    except Exception:
                        pass
                reset_system_globals()


@contextmanager
def system_world(**kw):
    world = SystemWorld(**kw)
    try:
        yield world
    except BaseException:
        world.teardown(strict=False)    # never mask the body's own failure
        raise
    world.teardown()


# --------------------------------------------------------------------------
# Census: every registry that can hold an actor
# --------------------------------------------------------------------------

def _len(x) -> int:
    try:
        return len(x)
    except Exception:
        return -1


def all_layers(sc) -> List[Any]:
    """Every layer of the registry, drawn or not (hidden layers and ``ui``)."""
    stack = sc.layers
    layers = getattr(stack, "_layers", None)
    if isinstance(layers, dict):
        return list(layers.values())
    return list(stack.iter_draw_order())


def census(*, collect: bool = True) -> Dict[str, int]:
    """Sizes of every holder. Compare two censuses with ``diff_census``."""
    if collect:
        full_collect()
    out: Dict[str, int] = {}
    ss = get_scena_system()
    if ss is not None:
        g = ss.dependency_graph
        out["graph.nodes"] = _len(g.nodes)
        out["graph.dependencies"] = sum(len(v) for v in g.dependencies.values())
        out["graph.dependents"] = sum(len(v) for v in g.dependents.values())
        out["graph.dep_keys"] = sum(1 for v in g.dependencies.values() if v)
        out["update.dirty_stack"] = _len(ss.update_manager._dirty_stack)
    es = _events._global_event_system
    if es is not None:
        out["events.live"] = sum(1 for r in es._events if not getattr(r, "_drop", False))
        out["events.all"] = _len(es._events)
        out["events.by_owner"] = _len(es._by_owner)
    sch = get_scheduler()
    for name in ("_handles", "_every", "_once", "_tween", "_await_family", "_sound",
                 "_by_owner", "_named", "_tweens", "_tasks", "_mode_owners",
                 "_update_owners", "_every_sites"):
        out["sched." + name.lstrip("_")] = _len(getattr(sch, name))
    col = get_collision_system()
    for name in ("_colliders", "_collider_index", "_pair_handlers", "_resolve_pairs",
                 "_prev_contacts", "_solve_contacts", "_contact_memory",
                 "_resolve_cache", "_partner_ident_cache", "_partner_only_cache",
                 "_passing", "_solve_contact_sides", "_solve_bottom_count"):
        out["collision." + name.lstrip("_")] = _len(getattr(col, name))
    out["collision.pair_tags"] = _len(col._pair_tags)
    out["collision.anything_targets"] = sum(
        1 for c in col._colliders if any(t is ANYTHING for t in c._pair_targets))
    out["collision.tag_colliders"] = sum(len(v) for v in col._tag_colliders.values())
    out["collision.tag_index"] = sum(len(v) for v in col._tag_index.values())
    b = get_bounds_system()
    out["bounds.group_handlers"] = _len(b._group_handlers)
    out["bounds.instance_handlers"] = _len(b._instance_handlers)
    out["bounds.seen_inside"] = _len(b._seen_inside)
    sc = registry()
    out["registry.live"] = _len(sc.live)
    out["registry.group_members"] = sum(len(v) for v in sc.group_map.values())
    out["registry.group_formulas"] = _len(getattr(sc, "_group_formulas", ()))
    out["registry.layers"] = _len(getattr(sc.layers, "_layers", ()))
    # Live draw entries only: tombstones (``None`` holes) are compacted lazily,
    # so the raw list length may go either way; ``draw_slots`` reports it.
    # Every layer, hidden ones and ``ui`` included: ``iter_draw_order`` skips
    # them, which hid their objects from the census and from ``zombies()``
    # (interaction campaign, class 2).
    live = 0
    for layer in all_layers(sc):
        live += sum(1 for o in layer._objects if o is not None)
    out["registry.draw_live"] = live
    out["fx.transient_shapes"] = _len(_transients._active_shapes)
    out["fx.spatial_fx"] = _len(_spatial_fx._active_fx)
    out["fx.histories"] = _len(_history._active_histories)
    mixer = get_mixer()
    out["mixer.voices"] = _len(mixer.voices)
    out["mixer.finished_pending"] = _len(mixer._finished_pending)
    fw = ScenaFramework.get_instance()
    wm = getattr(fw, "widget_manager", None)
    if wm is not None:
        out["widgets"] = _len(wm.widgets)
    import builtins
    out["ready.timers"] = _len(getattr(getattr(builtins, "ready", None), "_timers", ()))
    out["recently.slots"] = _len(getattr(getattr(builtins, "recently", None), "_slots", ()))
    return out


def draw_slots() -> int:
    """Raw draw-list length incl. tombstones (bounded, not baseline-exact)."""
    return sum(len(layer._objects) for layer in all_layers(registry()))


def diff_census(before: Dict[str, int], after: Dict[str, int],
                ignore: Iterable[str] = ()) -> Dict[str, Tuple[int, int]]:
    skip = set(ignore)
    keys = set(before) | set(after)
    return {k: (before.get(k, 0), after.get(k, 0)) for k in sorted(keys)
            if k not in skip and before.get(k, 0) != after.get(k, 0)}


def format_diff(diff: Dict[str, Tuple[int, int]]) -> str:
    return ", ".join(f"{k}: {a}→{b}" for k, (a, b) in diff.items())


def roster_snapshot() -> set:
    """The roster keys currently registered (pair with ``describe_new_live``)."""
    return set(registry().live.keys())


def describe_new_live(before: set, limit: int = 8) -> str:
    """Registered objects that were not there at ``before`` — for messages."""
    from scena.entity import made_at
    out = []
    for key, obj in list(registry().live.items()):
        if key in before:
            continue
        owner = getattr(obj, "_owner", None)
        where = made_at(obj) or f"#{key}"
        out.append(f"{type(obj).__name__} {where} alive={getattr(obj, 'is_alive', '?')}"
                   + (f" owner={type(owner).__name__}" if owner is not None else ""))
        if len(out) >= limit:
            break
    return "; ".join(out)


def frame_report(world: "SystemWorld", *objs: Any) -> str:
    """What a frame was drawn under, for a pixel assertion's message.

    The deep serial pass fails a few pixel tests now and then (WP44: a blank
    frame, a dot off its mapped point, an effect knob with no visible change)
    and passes them on the next run in the same order: a failure that cannot
    be bisected has to say what it saw. Each probe is guarded; the report
    never raises.
    """
    _canvas_mod = sys.modules["scena.canvas"]     # ``scena.canvas`` the name is the facade
    from scena.entity import made_at
    from scena.cover import is_cover_active
    parts = [f"hashseed={os.environ.get('PYTHONHASHSEED', 'random')}"]

    def probe(label, fn):
        try:
            parts.append(f"{label}={fn()}")
        except Exception as exc:  # noqa: BLE001 — a report, not a check
            parts.append(f"{label}=<{type(exc).__name__}: {exc}>")

    fw = world.fw
    sd = fw._scena_draw
    probe("camera", lambda: (sd._look_x, sd._look_y, sd._zoom, sd._rotation))
    probe("design", lambda: (fw.design_width, fw.design_height, fw.view_scale,
                             fw._letterbox_pad_x, fw._letterbox_pad_y, fw.pixel_ratio))
    probe("surface", lambda: (world.surface.width(), world.surface.height(),
                              fw._drawing_surface is world.surface))
    probe("post", lambda: (getattr(fw._post_fx_stack, "enabled", None),
                           [type(e).__name__ for e in (getattr(fw._post_fx_stack, "_effects", None) or [])]))
    probe("cover", is_cover_active)
    probe("cull", lambda: canvas.cull_offscreen)
    reg = registry()
    probe("live", lambda: len(reg.live))
    probe("active_live", lambda: sum(1 for o in reg.live_objects()
                                     if getattr(o, "is_alive", False) and getattr(o, "active", True)))
    probe("quarantined", lambda: len(world._quarantined))
    probe("layers", lambda: [(getattr(l, "name", "?"), _len(getattr(l, "_objects", ())),
                              getattr(l, "visible", "?")) for l in all_layers(reg)])
    probe("handles", lambda: _len(get_scheduler()._handles))
    probe("frames", lambda: world.frames_run)
    for o in objs:
        probe(type(o).__name__, lambda o=o: dict(
            at=made_at(o), alive=getattr(o, "is_alive", "?"), active=getattr(o, "active", "?"),
            visible=getattr(o, "visible", "?"), layer=getattr(getattr(o, "layer", None), "name",
                                                            getattr(o, "layer", "?")),
            box=_canvas_mod._cull_box(o)))
    return "; ".join(parts)


# --------------------------------------------------------------------------
# Zombies: dead objects a registry still references
# --------------------------------------------------------------------------

def _dead(obj) -> bool:
    return obj is not None and getattr(obj, "is_alive", True) is False


def zombies(ignore: Iterable[int] = ()) -> List[Tuple[str, Any]]:
    """``(holder, obj)`` for every destroyed object a registry still holds.

    ``ignore``: ids of objects to skip (``SystemWorld.zombies`` passes the
    debris that existed before the world started).
    """
    found: List[Tuple[str, Any]] = []
    skip = set(ignore)

    def check(where, obj):
        if _dead(obj) and id(obj) not in skip:
            found.append((where, obj))

    sch = get_scheduler()
    for h in list(sch._handles):
        if not (getattr(h, "cancelled", False) or getattr(h, "done", False)):
            check("sched.handle.owner", getattr(h, "owner", None))
    for owner in list(sch._mode_owners):
        check("sched.mode_owners", owner)
    for owner in list(sch._update_owners):
        check("sched.update_owners", owner)
    col = get_collision_system()
    for c in list(col._colliders):
        check("collision.colliders", getattr(c, "identity", None))
        for s in getattr(c, "_shapes", ()) or ():
            check("collision.collider.shape", s)
        # S6: a survivor's pair targets must not keep destroyed bodies.
        for t in list(getattr(c, "_pair_targets", ()) or ()):
            if isinstance(t, str):
                continue   # a group name / ANYTHING, not a body
            check("collision._pair_targets", getattr(t, "identity", t))
    for tag, lst in col._tag_colliders.items():
        for c in lst:
            check(f"collision.tag[{tag}]", getattr(c, "identity", None))
    for a, bb, _cb, _phase in list(col._pair_handlers):
        check("collision.pair_handlers", a)
        check("collision.pair_handlers", bb)
    es = _events._global_event_system
    if es is not None:
        for r in list(es._events):
            if not getattr(r, "_drop", False):
                check("events.owner", getattr(r, "_owner", None))
    b = get_bounds_system()
    for obj in list(b._instance_handlers.keys()):
        check("bounds.instance_handlers", obj)
    sc = registry()
    for key, obj in list(sc.live.items()):
        check(f"registry.live[{key}]", obj)
    for g, members in sc.group_map.items():
        for obj in list(members):
            check(f"registry.group[{g}]", obj)
    for layer in all_layers(sc):
        for obj in layer._objects:
            check(f"registry.layer[{layer.name}]", obj)
    for obj in list(_transients._active_shapes):
        check("fx.transient_shapes", obj)
    for obj in list(_spatial_fx._active_fx):
        check("fx.spatial_fx", obj)
    return found


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def referrer_chain(obj, depth: int = 3) -> str:
    """Human-readable referrers of ``obj`` (for a leak message)."""
    lines = []
    frontier = [obj]
    seen = {id(obj)}
    for level in range(depth):
        nxt = []
        for o in frontier:
            for r in gc.get_referrers(o):
                if id(r) in seen or r is frontier or r is nxt:
                    continue
                if isinstance(r, type(sys._getframe())):
                    continue
                seen.add(id(r))
                desc = type(r).__name__
                if isinstance(r, dict):
                    keys = [k for k, v in r.items() if v is o][:3]
                    desc += f" keys={keys!r}"
                lines.append("  " * level + f"<- {desc} @{id(r):x}")
                nxt.append(r)
                if len(lines) > 40:
                    return "\n".join(lines)
        frontier = nxt
    return "\n".join(lines)


def assert_collected(testcase, ref: "weakref.ref", what: str = "actor") -> None:
    full_collect()
    if ref() is None:
        return
    obj = ref()
    chain = referrer_chain(obj)
    obj = None
    testcase.fail(f"{what} was not garbage-collected after destroy; referrers:\n{chain}")


# --------------------------------------------------------------------------
# Test case base
# --------------------------------------------------------------------------

class SystemTestCase:
    """unittest mixin: ``self.w`` is a fresh ``SystemWorld`` per test."""

    world_draw = True

    def setUp(self):  # noqa: D401
        boot()
        self.w = SystemWorld(draw=self.world_draw)
        self.probe = self.w.probe

    def tearDown(self):
        self.w.teardown()

    def track(self, obj):
        return self.w.track(obj)

    # -- assertions -------------------------------------------------------
    def assertNoDeadCalls(self):
        dead = self.probe.dead_calls()
        self.assertEqual(dead, [], f"hooks ran for a destroyed owner: {dead}")

    def assertNoZombies(self):
        z = self.w.zombies()
        self.assertEqual(z, [], "registries still hold destroyed objects: "
                         + ", ".join(f"{w}: {type(o).__name__}" for w, o in z))

    def assertCensusEqual(self, before, after=None, ignore=()):
        after = census() if after is None else after
        d = diff_census(before, after, ignore)
        self.assertEqual(d, {}, "registry sizes changed: " + format_diff(d))


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------

def tone(duration: float = 0.3, freq: float = 440.0, amp: float = 0.2) -> Sound:
    """An in-memory Sound (no file I/O)."""
    return Sound._from_pcm(make_sine(freq, duration, amp=amp))


# --------------------------------------------------------------------------
# Kitchen sink: one actor wired into every subsystem
# --------------------------------------------------------------------------

class Sink:
    """What ``kitchen_sink`` built: the actor plus its side objects."""

    def __init__(self, actor, *, partner=None, source=None, dependent=None,
                 contrail=None, track=None, handles=None):
        self.actor = actor
        self.partner = partner
        self.source = source
        self.dependent = dependent
        self.contrail = contrail
        self.track = track
        self.handles = handles or {}


def kitchen_sink(world: SystemWorld, *, kind: str = "circle", center=(0.0, 0.0),
                 tag: str = "sink", partner_tag: str = "rock", partner: bool = True,
                 sound: bool = True, links: bool = True, path: bool = True,
                 layer: Any = None) -> Sink:
    """Build an actor that touches every subsystem, all hooks probed.

    Class hooks: method ``@when`` (owned watch), ``@collide_with`` /
    ``@collide_with_exit`` on ``partner_tag``, instance ``@leave_playfield``.
    Instance work: ``after`` / ``every`` / tween (yoyo forever) / async mode
    awaiting ``wait`` / ``on_update`` / entity ``play_sound`` (forever loop) / ``flash`` /
    ``.glow`` / ``move_along`` a Track / an object-literal ``@collide`` pair
    handler / a Contrail fed from ``on_update``; an inbound ``@=`` (actor ←
    source) and an outbound one (dependent ← actor).

    Every hook records into ``world.probe`` with the actor as owner, so
    ``probe.dead_calls()`` catches any call after destroy.
    """
    from scena import (Circle, Contrail, Entity, Sprite, Track, collide,
                       collide_with, collide_with_exit, leave_playfield, wait, when)

    probe = world.probe

    def rec(tag_, self_):
        probe.hit(tag_, self_)

    base = {"circle": Circle, "sprite": Sprite}[kind]

    class SinkActor(base):  # type: ignore[misc, valid-type]
        @when(lambda self: getattr(self, "hp", 5) <= 0)
        def low(self):
            rec("when", self)

        @collide_with(partner_tag)
        def hit(self, other, info=None):
            rec("collide", self)

        @collide_with_exit(partner_tag)
        def unhit(self, other, info=None):
            rec("collide_exit", self)

        @leave_playfield
        def left(self):
            rec("leave", self)

    extra = {} if layer is None else {"layer": layer}
    with quiet():
        if kind == "circle":
            a = SinkActor(center=center, radius=6, group=tag, **extra)
        else:
            a = SinkActor("system_missing.png", center=center, width=12, height=12,
                          hitbox_shape="rect", group=tag, **extra)
            a.add_hitbox()
    world.track(a)
    a.hp = 5
    a.speed = 0
    a.on_destroy = probe.hook("on_destroy", a)
    handles = {}
    handles["after"] = a.after(1e6, probe.hook("after", a))
    handles["every"] = a.every(0.05, probe.hook("every", a))
    if kind == "circle":
        handles["tween"] = a.tween(a["radius"], 9, time=0.4, loops="forever", yoyo=True)

    async def roaming(e):
        while True:
            await wait(0.05)
            rec("mode", e)

    a.mode = roaming

    contrail = Contrail(max_points=8, color="red")
    world.track(contrail)

    def on_up(e, dt):
        rec("on_update", e)
        contrail.snapshot(e)

    a.on_update = on_up
    if sound:
        # A forever loop: it must stop on destroy. A finite sound would ring
        # out (Sound Design — When the owner ends) and hold a voice past it.
        handles["sound"] = a.play_sound(tone(0.3), loops="forever",
                                        on_done=probe.hook("sound_done", a))
    a.flash(1e6, on_done=probe.hook("flash_done", a))
    a.glow = "red"
    trk = None
    if path:
        trk = world.track(Track(points=[center, (center[0] + 30, center[1]),
                                        (center[0] + 30, center[1] + 30)]))
        handles["path"] = a.move_along(trk, time=1.0, loops="forever")
    rock = None
    if partner:
        rock = world.track(Circle(center=(center[0] + 400, center[1]), radius=6,
                                  group=partner_tag))

        @collide(a, rock)
        def _pair(x, y, info=None):
            rec("pair", a_ref())

    a_ref = weakref.ref(a)
    src = dep = None
    if links:
        src = world.track(Entity())
        src.value = 1.0
        a["speed"] @= (lambda: src.value * 2)
        dep = world.track(Entity())
        dep["mirror"] @= (lambda: a.hp + 1)
    return Sink(a, partner=rock, source=src, dependent=dep, contrail=contrail,
                track=trk, handles=handles)
