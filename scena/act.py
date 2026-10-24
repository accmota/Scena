"""Acts: ``class Fase(Act)``, ``change_act(Fase)``, ``run(Titulo)``.

Design: ``design/Act Design.md``.

One lifetime rule. What the top of the file creates is **the game** and stays.
Everything created after the top level ends belongs to the current act and
leaves with it on ``change_act``; world settings the act changed go back to
their top-level values.

Mechanism: *seal, then diff*. When the top level ends (``_seal``, called from
``ScenaFramework._begin_game``) the manager records the live game objects
(entities, post effects, background extras, leave-playfield handlers, script
``ready`` / ``recently`` slots). An act change removes whatever is not in that
record. Nothing is recorded per spawn, so a bullet pays nothing.
"""
from __future__ import annotations

import builtins
import functools
import inspect
import weakref
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

from ._weakset import OrderedWeakSet
from ._pkg import RetiredClassMeta
from .entity import Entity


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


class ActUsageError(TypeError, AttributeError):
    """An Entity verb that has no meaning on an act.

    Also an ``AttributeError`` so engine probes (``getattr(item, "visible",
    None)``) keep their default instead of crashing on an act.
    """


# ---------------------------------------------------------------------------
# Messages (Act Design.md, "Restrictions and error messages")
# ---------------------------------------------------------------------------

_DRAW_MSG = "Acts do not draw and are not in groups."
_BODY_MSG = (
    "An act has no body to collide, leave, be clicked or hovered. Put the rule on the "
    "entity class (class Heroi), or for this act only write @collide(a, b) "
    "inside setup()."
)
_BODY_HOOKS = (
    "on_click", "on_hover", "on_hover_exit",
    "on_collide", "on_collide_stay", "on_collide_exit",
)
_BODY_TAGS = ("_collide_with_specs", "_leave_playfield_method")
_CLASS_KEYWORDS = ("group", "layer")
_MAX_TEARDOWN_PASSES = 100


def _base_class_message() -> str:
    return (
        "Act is the base class. Write class Titulo(Act): … "
        "then change_act(Titulo)."
    )


def _check_act_class(value: Any, verb: str) -> None:
    """Raise ``TypeError`` unless ``value`` is a concrete Act subclass."""
    if value is Act:
        raise TypeError(_base_class_message())
    if isinstance(value, Act):
        name = type(value).__name__
        raise TypeError(
            f"{verb} takes the act class. Write {verb}({name}), without ()."
        )
    if isinstance(value, str):
        raise TypeError(
            f"{verb} takes an Act class, not a string. Write {verb}({value})."
        )
    if isinstance(value, type):
        if not issubclass(value, Act):
            raise TypeError(
                f"{value.__name__} is not an Act. Acts are classes like "
                f"class Fase(Act): …"
            )
        return
    raise TypeError(
        f"{verb} takes an Act class, got {type(value).__name__} {value!r}. "
        f"Acts are classes like class Fase(Act): … then {verb}(Fase)."
    )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class ActManager:
    """Process-wide act state: the sealed game record and the current act."""

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        # Top level ended (``_seal``). Before this, everything is the game.
        self.sealed = False
        # ``run(Titulo)`` — a game started with plain ``run()`` has no acts.
        self.act_mode = False
        self.current: Optional[Act] = None
        # True from the leaving act's on_destroy through the restore.
        self.changing = False
        # True only while the framework constructs an act.
        self._building = False
        # Item whose on_destroy is running during a teardown (error messages).
        self._hook_owner: Any = None
        self._leaving: Optional[type] = None
        self._entering: Optional[type] = None
        # ``id()`` of every entity torn down in the current batch.
        self.dying_ids: set = set()
        # --- the sealed game record ---
        self._game_entities = OrderedWeakSet()
        # World settings at the seal (``WORLD_SETTINGS`` name → value).
        self._settings: Dict[str, Any] = {}
        self._game_leave: dict = {}
        # ``group["x"] @=`` formulas at the seal (review 2026-10-09 S4-3).
        self._game_formulas: dict = {}
        # Layer names at the seal: a layer an act creates leaves with the act.
        self._game_layers: frozenset = frozenset()
        self._game_ready_keys: frozenset = frozenset()
        self._game_recently_keys: frozenset = frozenset()
        # Links the current act put on game objects (``hud["text"] @= …``),
        # keyed by ``(id(owner), field)``; undone at the change (PA1).
        self._act_links: Dict[Tuple[int, str], "_ActLink"] = {}
        self._act_link_nodes: set = set()
        from . import state
        state._ACT_LINK_HOOK = None
        from .process import _set_top_level_ended
        _set_top_level_ended(False)

    # --- the top level ends --------------------------------------------------

    def _seal(self, *, act_mode: bool) -> None:
        """Record the game. Everything created after this belongs to an act."""
        from .bounds import get_bounds_system
        registry = _registry()
        self._game_entities = OrderedWeakSet(
            obj for obj in registry.live_objects() if _is_live(obj)
        )
        self._settings = {w.name: w.snapshot() for w in WORLD_SETTINGS}
        self._game_leave = dict(get_bounds_system()._group_handlers)
        self._game_formulas = dict(registry._group_formulas)
        self._game_layers = frozenset(registry.layers._layers)
        ready = getattr(builtins, "ready", None)
        recently = getattr(builtins, "recently", None)
        self._game_ready_keys = frozenset(getattr(ready, "_timers", {}) or ())
        self._game_recently_keys = frozenset(getattr(recently, "_slots", {}) or ())
        from .collision import get_collision_system
        from .process import _set_top_level_ended
        get_collision_system().seal_resolve_pairs()
        self.act_mode = bool(act_mode)
        self.sealed = True
        _set_top_level_ended(True)
        if self.act_mode:
            from . import state
            state._ACT_LINK_HOOK = _note_act_link

    # --- building --------------------------------------------------------------

    def _build(self, cls: type) -> Optional["Act"]:
        """Construct ``cls``; it becomes current before its ``setup`` runs."""
        self._building = True
        try:
            instance = cls()
        except BaseException:
            # The half-built act is gone (rollback dropped its roster entry). Objects
            # its setup made are act objects: the next change removes them.
            self.current = None
            raise
        finally:
            self._building = False
        # A change_act inside setup() already replaced it; keep that one.
        return instance if self.current is instance else self.current

    def enter_first(self, cls: type) -> Optional["Act"]:
        """``run(Titulo)``: build the first act right after the seal."""
        return self._build(cls)

    def _attach(self, act: "Act") -> None:
        """Called from ``Act.__init__`` before ``setup``: make it current."""
        self.current = act

    # --- changing ----------------------------------------------------------------

    def change(self, cls: type) -> "Act":
        # GC policy: thaw so the leaving act's objects can be collected;
        # one collect + freeze at the end of this frame, after the new act is
        # built and the caller's stack (a handler) let go of the old act
        # (gc_policy, review 2026-10-09 S4-7).
        from .gc_policy import request_freeze, thaw_world
        refreeze = thaw_world()
        try:
            return self._change(cls)
        finally:
            if refreeze:
                request_freeze()

    def _change(self, cls: type) -> "Act":
        leaving = self.current
        self.changing = True
        self._leaving = type(leaving) if leaving is not None else None
        self._entering = cls
        first_error: Optional[BaseException] = None
        # The whole batch is known before the first hook runs: formula links
        # between two leaving objects unlink silently (``_unlink_notice``).
        # Held strongly for the whole change: an undrawn entity kept alive only
        # by the leaving act's ink must still get its on_destroy after the
        # act's own teardown clears that ink.
        batch = self._doomed()
        self.dying_ids = {id(o) for o in batch}
        # A game object's link the act installed unlinks silently when what
        # it reads leaves (it is undone in 2b anyway).
        self._act_link_nodes = {
            id(r.node) for r in self._act_links.values() if r.link is not None
        }
        if leaving is not None:
            self.dying_ids.add(id(leaving))
        try:
            # 1. The leaving act's on_destroy runs first, with its objects alive.
            #    registry.destroy also cancels the act's own timers / mode script.
            if leaving is not None and leaving.is_alive:
                first_error = self._destroy_one(leaving, first_error)
            # 2. Everything else created after the top level ended, as one batch.
            #    A runaway teardown raises; the steps below run anyway, so the
            #    act's rules and settings never outlive it (S4-9).
            try:
                first_error = self._teardown(first_error, {id(o) for o in batch})
            finally:
                # 2b. Work and hooks the act handed to game objects (a bound
                #     method of the act, or a function closing over it) leave
                #     with the act.
                if leaving is not None:
                    self._drop_act_callables(leaving)
                # 2c. Links the act put on game objects leave with it: the
                #     field gets back the link or value it had (PA1).
                self._undo_act_links()
                # 3. World settings back to their top-level values.
                self._restore()
            # 4. Layers the act created leave with it (a restart creates them
            #    again; review 2026-10-09 S4-4).
            first_error = self._drop_act_layers(first_error)
        finally:
            del batch
            self.dying_ids = set()
            self._hook_owner = None
            self._leaving = None
            self._entering = None
            self.changing = False
            self.current = None
        # 4. Build the new act.
        try:
            act = self._build(cls)
        except BaseException:
            if first_error is not None:
                raise first_error
            raise
        if first_error is not None:
            raise first_error
        return act

    # Hooks on a game object that can hold an act's callable.
    _GAME_HOOKS = (
        "on_update", "on_click", "on_hover", "on_hover_exit", "on_collide",
        "on_collide_stay", "on_collide_exit", "on_destroy", "on_drag_to",
        "on_drag_over", "on_drop_by", "mode",
    )

    def _drop_act_callables(self, act) -> None:
        """"Closest owner wins" keeps work on a game object; but a callable of
        the leaving act would stack on every restart, keep the dead act alive
        and reach its destroyed ink (review 2026-10-09 X-life-7). Cancel those
        handles and clear those hooks; everything else the game owns stays."""
        from .process import get_scheduler
        for handle in list(get_scheduler()._handles):
            if handle._cancelled or handle._done:
                continue
            if (_belongs_to(handle._fn, act) or _belongs_to(handle._then, act)
                    or _belongs_to(handle._on_done, act)):
                handle.cancel()
        for obj in list(self._game_entities):
            if not _is_live(obj):
                continue
            cls = type(obj)
            for name in self._GAME_HOOKS:
                if not hasattr(cls, name):
                    continue
                try:
                    value = getattr(obj, name)
                except Exception:
                    continue
                if _belongs_to(value, act):
                    setattr(obj, name, None)

    def _undo_act_links(self) -> None:
        """An act's ``obj["field"] @= …`` on a game object goes, and the field
        gets back what it had before the act's first link: the game's own
        link, or its value. The restart then links again with no "overrides"
        warning, and the next act can write the field (review 2026-10-14
        PA1). Best effort: a link the game cannot take back (its source was
        destroyed) leaves the field at its last value."""
        records = list(self._act_links.values())
        self._act_links.clear()
        self._act_link_nodes = set()
        for rec in records:
            owner = rec.owner()
            if rec.link is None or owner is None or not _is_live(owner):
                continue
            node = rec.node
            current = getattr(node, "_link", None)
            try:
                if current is rec.link:
                    owner._unlink_field(rec.name)
                elif current is not None:
                    continue            # not the act's link
                if rec.prior_rhs is not None:
                    src = rec.prior_rhs
                    if getattr(src, "_destroyed", False):
                        continue
                    owner._link_field(rec.name, src)
                elif rec.has_value:
                    setattr(owner, rec.name, rec.prior_value)
            except Exception:  # noqa: BLE001 — keep the last value; finish the change
                continue

    def _drop_act_layers(self, first_error):
        """Delete every layer created after the seal. A game object still on
        one keeps it, and the change raises (after the new act is built)
        naming the layer and the fix."""
        from .registry import BUILT_IN_LAYERS
        stack = _registry().layers
        for name in list(stack._layers):
            if name in self._game_layers or name in BUILT_IN_LAYERS:
                continue
            layer = stack._layers[name]
            layer._compact()
            if layer._objects:
                left = ", ".join(type(o).__name__ for o in layer._objects[:3])
                act = self._leaving.__name__ if self._leaving else "the act"
                err = ActUsageError(
                    f"Layer {name!r} was created in {act} and leaves with it, "
                    f"but game objects are still on it ({left}). Move them to "
                    f"a game layer before the change (obj.layer = \"default\"), "
                    f"or create the layer at the top of the file."
                )
                if first_error is None:
                    first_error = err
                continue
            stack.delete(name)
        return first_error

    def _destroy_one(self, obj, first_error):
        self._hook_owner = obj
        try:
            _registry().destroy(obj)
        except BaseException as exc:  # noqa: BLE001 — author hook; finish the change
            if first_error is None:
                first_error = exc
        finally:
            self._hook_owner = None
        return first_error

    def _doomed(self) -> List[Any]:
        """Root entities created after the top level ended, still alive."""
        game = self._game_entities
        out = []
        for obj in _registry().live_objects():
            if not _is_live(obj):
                continue
            if getattr(obj, "_owner", None) is not None:
                continue  # a part: it leaves with its owner
            if getattr(obj, "_scena_internal", False):
                continue  # framework singletons are never act-owned
            if obj in game:
                continue
            out.append(obj)
        return out

    def _fire_hook(self, obj, first_error):
        from .entity import _fire_on_destroy
        self._hook_owner = obj
        try:
            _fire_on_destroy(obj)
        except BaseException as exc:  # noqa: BLE001 — author hook; finish the change
            if first_error is None:
                first_error = exc
        finally:
            self._hook_owner = None
        return first_error

    def _teardown(self, first_error, batch_ids=None):
        """Tear down everything made after the seal, in two phases.

        1. Every ``on_destroy`` of the batch runs while the **whole** batch is
           alive (as the act's own ``on_destroy`` does), so a hook that reads
           a sibling does not depend on creation order (review 2026-10-09
           X-life-9).
        2. Teardown. An object created during the teardown (by a hook) leaves
           without its own ``on_destroy``: it belongs to the ending act, and a
           self-replacing hook (keep the field full) would otherwise respawn
           forever (X-life-6).
        """
        batch = list(self._doomed())      # held: ids stay unique while used
        if batch_ids is None:
            batch_ids = {id(o) for o in batch}
        for obj in batch:
            if id(obj) in batch_ids and _is_live(obj):
                first_error = self._fire_hook(obj, first_error)
        passes = 0
        try:
            while True:
                doomed = self._doomed()
                if not doomed:
                    break
                passes += 1
                if passes > _MAX_TEARDOWN_PASSES:
                    kinds = sorted({type(o).__name__ for o in doomed})
                    raise RuntimeError(
                        "An act change did not settle: teardown hooks keep "
                        f"creating objects ({', '.join(kinds)}) after "
                        f"{_MAX_TEARDOWN_PASSES} passes."
                    )
                self.dying_ids.update(id(obj) for obj in doomed)
                for obj in doomed:
                    if not _is_live(obj):
                        continue
                    if id(obj) not in batch_ids:
                        # Born during the teardown: leaves without its own hook.
                        object.__setattr__(obj, "_on_destroy", None)
                    first_error = self._destroy_one(obj, first_error)
        finally:
            del batch
            # Also when the cap raised: the act's timers, rules and leave
            # handlers go (review 2026-10-09 S4-9).
            self._drop_script_level_work()
        return first_error

    def _drop_script_level_work(self) -> None:
        """Ownerless work, classless registrations and script-level poll memory
        made after the seal. Runs after the entity drain, so work an
        ``on_destroy`` started (a bare ``after``) goes too."""
        from .bounds import get_bounds_system
        from .collision import get_collision_system
        from .events import get_global_event_system
        from .process import SCOPE_ACT, get_scheduler
        get_scheduler().cancel_ownerless(SCOPE_ACT, release=True)
        get_scheduler().resume_suspended_game_slots()
        get_global_event_system().drop_act_owned()
        get_collision_system().drop_act_pair_handlers()
        from .interaction import drop_act_tag_rules
        drop_act_tag_rules()
        get_collision_system().restore_sealed_resolve_pairs()
        get_collision_system().retire_unused_pair_tags()
        from .cover import drop_act_on_done
        drop_act_on_done()          # the fade stays; the act's on_done goes
        fw = _framework()
        hit = fw.post_fx_stack._hit if fw is not None else None
        if hit is not None:
            hit._clear_pulses()
        # A press, a key or a click the old act's script got does not complete
        # in the new act (S3-8).
        cm = getattr(fw, "canvas_manager", None) if fw is not None else None
        if cm is not None:
            cm.forget_act_input()
        # A key press from the old act never fires ``once`` in the new one.
        keyp = getattr(builtins, "keyp", None)
        swallow = getattr(keyp, "_swallow_edges", None)
        if swallow is not None:
            swallow()
        bounds = get_bounds_system()
        bounds._group_handlers.clear()
        bounds._group_handlers.update(self._game_leave)
        # Formula groups an act bound leave with it; a game formula the act
        # re-bound comes back (S4-3).
        registry = _registry()
        registry._group_formulas.clear()
        registry._group_formulas.update(self._game_formulas)
        registry._group_formula_stack.clear()
        ready = getattr(builtins, "ready", None)
        timers = getattr(ready, "_timers", None)
        if timers is not None:
            for key in [k for k in timers if k not in self._game_ready_keys]:
                del timers[key]
        recently = getattr(builtins, "recently", None)
        slots = getattr(recently, "_slots", None)
        if slots is not None:
            for key in [k for k in slots if k not in self._game_recently_keys]:
                del slots[key]

    def _restore(self) -> None:
        """World settings back to their top-level values (Act Design, Restored)."""
        for w in WORLD_SETTINGS:
            if w.name in self._settings:
                w.restore(self._settings[w.name])


# ---------------------------------------------------------------------------
# World settings: restored on every change, or kept (Act Design, Lifetime)
# ---------------------------------------------------------------------------
#
# Every author-settable canvas / clock / collision / audio setting is in
# exactly one of ``WORLD_SETTINGS`` (restored) or ``KEPT_SETTINGS`` (kept).
# ``tests/test_act.py`` walks the settable surface and fails on a name in
# neither — a new setter cannot leak across acts unclassified.

class WorldSetting(NamedTuple):
    name: str
    # Author spellings this entry covers (``"canvas.pan_to"``, ``"clock.scale"``).
    covers: Tuple[str, ...]
    snapshot: Callable[[], Any]
    restore: Callable[[Any], None]


def _engine():
    from .canvas import ScenaCanvas
    return ScenaCanvas.get_current()


def _clock():
    return _framework().clock


_CAMERA_FIELDS = ("_zoom", "_look_x", "_look_y", "_look_rest_x", "_look_rest_y", "_rotation")


def _snap_camera():
    e = _engine()
    return tuple(getattr(e, f) for f in _CAMERA_FIELDS)


def _restore_camera(v) -> None:
    e = _engine()
    # A timed camera verb in flight would write the camera again next frame,
    # whatever its owner (a game actor's mode keeps running): the restored
    # pose wins (review 2026-10-09 S9-5).
    from .canvas import CAMERA_ALL_KEYS
    from .process import get_scheduler
    tweens = get_scheduler()._tweens
    for key in CAMERA_ALL_KEYS:
        handle = tweens.get(key)
        if handle is not None:
            handle.cancel()
    for f, x in zip(_CAMERA_FIELDS, v):
        setattr(e, f, x)
    e._sync_camera()


def _snap_playfield():
    pf = _engine().bounds
    return (pf._pad, pf._explicit)


def _restore_playfield(v) -> None:
    pf = _engine().bounds
    pf._pad, pf._explicit = v


def _snap_clock():
    c = _clock()
    return (c._scale, c._paused, c._scale_before_pause)


def _restore_clock(v) -> None:
    c = _clock()
    c._scale, c._paused, c._scale_before_pause = v


def _snap_resolve():
    from .collision import get_collision_system
    return get_collision_system().resolve_enabled


def _restore_resolve(v) -> None:
    from .collision import get_collision_system
    get_collision_system().resolve_enabled = v


def _snap_floor():
    from .collision import get_collision_system
    return get_collision_system().floor


def _restore_floor(v) -> None:
    from .collision import get_collision_system
    get_collision_system().floor = v


def _snap_layer_default():
    return _engine().registry.layers.default


def _restore_layer_default(v) -> None:
    layers = _engine().registry.layers
    if v in layers:
        layers.default = v


def _snap_paint_defaults():
    from .style import PaintState
    return PaintState._default_instance


def _restore_paint_defaults(v) -> None:
    from .style import PaintState
    PaintState._default_instance = v


def _snap_background_base():
    return _framework().background_stack._base


def _restore_background_base(v) -> None:
    _framework().background_stack._base = v


def _snap_background_items():
    return list(_framework().background_stack._items)


def _restore_background_items(v) -> None:
    _framework().background_stack._items[:] = v


def _snap_post_effects():
    return list(_framework().post_fx_stack._effects)


def _restore_post_effects(game) -> None:
    """The game's effects, in order; the hit-feedback singleton stays."""
    post = _framework().post_fx_stack
    hit = post._hit
    for effect in list(post._effects):
        if effect is hit or any(effect is g for g in game):
            continue
        post.remove(effect)  # releases its GPU resources
    rest = [e for e in post._effects if not any(e is g for g in game)]
    post._effects[:] = list(game) + rest
    post._invalidate()


def _widget_manager():
    fw = _framework()
    return getattr(fw, "widget_manager", None) if fw is not None else None


def _snap_hud_stack():
    wm = _widget_manager()
    return None if wm is None else wm._cursor_state()


def _restore_hud_stack(v) -> None:
    """The HUD column cursor at the seal: an act's omitted-y HUD starts at
    the same slot on every entry (review 2026-10-09 S4-5)."""
    wm = _widget_manager()
    if wm is None or v is None:
        return
    state = list(v)
    state[7] = [r for r in state[7] if r() is not None]   # participants
    state[9] = list(state[9])                              # label column
    wm._restore_cursor_state(tuple(state))


def _flag(obj_fn: Callable[[], Any], attr: str):
    return (lambda: getattr(obj_fn(), attr),
            lambda v: setattr(obj_fn(), attr, v))


WORLD_SETTINGS: Tuple[WorldSetting, ...] = (
    WorldSetting(
        "camera",
        ("canvas.pan_to", "canvas.pan_by", "canvas.zoom_to", "canvas.zoom_by",
         "canvas.rotate_to", "canvas.rotate_by", "canvas.set_origin",
         "canvas.frame_to", "canvas.reset_view", "canvas.zoom", "canvas.pan_x",
         "canvas.pan_y"),
        _snap_camera, _restore_camera),
    WorldSetting(
        "background",
        ("canvas.background", "background.base", "background.reset_base"),
        _snap_background_base, _restore_background_base),
    WorldSetting(
        "background.fields",
        ("background.add", "background.remove", "background.clear",
         "background.set_fly", "canvas.set_fly"),
        _snap_background_items, _restore_background_items),
    WorldSetting(
        "background.enabled", ("background.enabled",),
        *_flag(lambda: _framework().background_stack, "enabled")),
    WorldSetting(
        "effects",
        ("effects.add", "effects.remove", "effects.clear"),
        _snap_post_effects, _restore_post_effects),
    WorldSetting(
        "effects.enabled", ("effects.enabled",),
        *_flag(lambda: _framework().post_fx_stack, "enabled")),
    WorldSetting(
        "playfield",
        ("playfield.pad", "playfield.left", "playfield.bottom", "playfield.right",
         "playfield.top", "playfield.set"),
        _snap_playfield, _restore_playfield),
    WorldSetting(
        "clock", ("clock.scale", "clock.paused"), _snap_clock, _restore_clock),
    WorldSetting(
        "collision.resolve_enabled", ("collision.resolve_enabled",),
        _snap_resolve, _restore_resolve),
    WorldSetting(
        "collision.floor", ("collision.floor",), _snap_floor, _restore_floor),
    WorldSetting(
        "layers.default", ("layers.default",),
        _snap_layer_default, _restore_layer_default),
    WorldSetting(
        "set_defaults", ("set_defaults",),
        _snap_paint_defaults, _restore_paint_defaults),
    WorldSetting(
        "hud_stack",
        ("ui.stack_reset", "ui.stack_origin", "ui.stack_from", "ui.stack_column",
         "ui.gap"),
        _snap_hud_stack, _restore_hud_stack),
)

# Player / engine preferences and debug switches: an act may change them for
# good (an options screen must be able to).
KEPT_SETTINGS: Dict[str, str] = {
    "canvas.fx_quality": "preference",
    "canvas.post_fx_scale": "preference",
    "canvas.shape_fx_scale": "preference",
    "canvas.batch_shared_filters": "preference (engine)",
    "canvas.cull_offscreen": "preference (engine)",
    "canvas.display": "preference (window)",
    "audio.volume": "preference",
    "audio.muted": "preference",
    "audio.level_tau": "preference (analysis)",
    "ui.scale": "preference (theme)",
    "ui.font": "preference (theme)",
    "ui.min_label_space": "preference (theme)",
    "canvas.framerate": "preference (engine)",
    "set_fx_auto": "preference (engine)",
    "set_watchdog": "debug",
    "set_extrude_focus": "debug",
    "show_tracks": "debug",
    "show_processes": "debug",
    "collision.show_colliders": "debug",
    "collision.show_tracks": "debug",
}


_manager = ActManager()


class _ActLink:
    """What a game object's field had before the current act first linked it."""

    __slots__ = ("owner", "name", "prior_rhs", "prior_value", "has_value",
                 "node", "link")

    def __init__(self, owner, name: str) -> None:
        self.owner = weakref.ref(owner)
        self.name = name
        self.prior_rhs = None
        self.prior_value = None
        self.has_value = False
        self.node = None
        self.link = None
        node = _field_node(owner, name)
        link = getattr(node, "_link", None) if node is not None else None
        if link is not None:
            from .state import DirectLink
            self.prior_rhs = link.source if isinstance(link, DirectLink) else link.expression_fn
            return
        try:
            value = owner._read_field(name)
        except Exception:       # a new ink field: nothing to give back
            return
        from .state import Container
        if isinstance(value, Container):
            x, y = getattr(value, "x", None), getattr(value, "y", None)
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                return
            value = (float(x), float(y))
        self.prior_value = value
        self.has_value = True

    def commit(self) -> None:
        owner = self.owner()
        node = _field_node(owner, self.name) if owner is not None else None
        if node is not None and node._link is not None:
            self.node = node
            self.link = node._link


def _field_node(owner, name: str):
    """The graph node that holds ``owner[name]``'s link, or None."""
    anchors = owner.__dict__.get("_field_anchors")
    if anchors and name in anchors:
        return anchors[name]
    try:
        slot = owner._resolve_field(name)
    except Exception:
        return None
    from .state import Container, ContainerSlot
    if not isinstance(slot, ContainerSlot):
        return None
    try:
        target = slot.cell(owner)      # never a dot read: Text.text reads a str
    except Exception:
        return None
    return target if isinstance(target, Container) else None


def _note_act_link(owner, name: str):
    """``state._ACT_LINK_HOOK``: an act links a field of a game object."""
    m = _manager
    if not m.sealed or m.changing or m.current is None:
        return None
    from .entity import _actor_of
    actor = _actor_of(owner)
    if actor is None or actor not in m._game_entities:
        return None
    key = (id(owner), name)
    rec = m._act_links.get(key)
    if rec is None or rec.owner() is not owner:
        rec = _ActLink(owner, name)
        m._act_links[key] = rec
    return rec.commit


def _unlink_notice(dep, source) -> bool:
    """``state._UNLINK_NOTICE_HOOK``: auto-unlink notices during an act change.

    A dependent leaving in the same batch unlinks silently (a HUD and the hero
    it reads leave together). A dependent that stays (a game object) gets a
    SCENA WARNING naming both objects and both acts. Outside a change the
    generic warning stands (returns False).
    """
    m = _manager
    if not m.changing:
        return False
    if id(dep) in m._act_link_nodes:
        return True             # the act's own link: undone and restored (PA1)
    from .entity import _actor_of, entity_label, part_path
    holder = _actor_of(dep)
    if holder is not None and (
        id(holder) in m.dying_ids or getattr(holder, "_destroyed", False)
    ):
        return True
    from .process import report_author_warning
    src = _actor_of(source) or source
    leaving = m._leaving.__name__ if m._leaving is not None else "the act"
    entering = m._entering.__name__ if m._entering is not None else "the next act"
    if holder is not None:
        what = f"{part_path(dep, holder)} of {entity_label(holder)}"
    else:
        what = str(getattr(dep, "name", dep))
    if getattr(src, "_scena_is_act", False):
        gone = (f"{what} read act {type(src).__name__}, which ended when the "
                f"game changed to {entering}.")
    else:
        gone = (f"{what} read {entity_label(src)}, which belonged to act {leaving} "
                f"and was removed when the game changed to {entering}.")
    report_author_warning(
        "change_act",
        f"{gone} The link was "
        f"dropped (the last value stays). Create it in {leaving}.setup() so it "
        f"leaves with the act.",
        owner=holder,
    )
    return True


def _install_unlink_notice() -> None:
    from . import state
    state._UNLINK_NOTICE_HOOK = _unlink_notice


_install_unlink_notice()


def get_act_manager() -> ActManager:
    return _manager


def is_sealed() -> bool:
    """True once the top level has ended (``run()`` finished startup)."""
    return _manager.sealed


def _reset_act_manager() -> None:
    """Tests: remove the current act and its objects, then forget the seal.

    Hook errors are swallowed: a test's leftovers must not fail the next one.
    """
    m = _manager
    if m.sealed and m.act_mode:
        m.changing = True
        try:
            if m.current is not None and m.current.is_alive:
                m._destroy_one(m.current, None)
            m._teardown(None)
        except Exception:
            pass
    m._reset()


def _belongs_to(fn, act) -> bool:
    """True when ``fn`` is a bound method of ``act`` or a function (lambda,
    nested def, ``functools.partial``) whose closure or arguments hold it."""
    if fn is None or act is None:
        return False
    if getattr(fn, "__self__", None) is act:
        return True
    if isinstance(fn, functools.partial):
        if fn.args and any(a is act for a in fn.args):
            return True
        return _belongs_to(fn.func, act)
    func = getattr(fn, "__func__", fn)
    for cell in getattr(func, "__closure__", None) or ():
        try:
            if cell.cell_contents is act:
                return True
        except ValueError:
            continue
    return False


def _framework():
    from .orchestration import ScenaFramework
    return ScenaFramework._instance


def _registry():
    from .canvas import ScenaCanvas
    return ScenaCanvas.get_current().registry


def _is_live(obj) -> bool:
    return obj is not None and not getattr(obj, "_destroyed", False)


# ---------------------------------------------------------------------------
# Act
# ---------------------------------------------------------------------------

class Act(Entity):
    """One part of the game: title, level, game over.

    ``class Fase(Act)`` with ``setup(self)`` to build it, ``on_update`` /
    ``@when`` / modes for its logic. Entered with ``change_act(Fase)`` or
    ``run(Fase)``; never constructed by hand. Everything created while it is
    current leaves with it.
    """

    # Read by ``entity._check_class_hook_names``: an act's messages name the
    # act spellings (``on_update``, ``keyp.once``); ``entity_label`` names an
    # act "act Fase".
    _scena_is_act = True
    _scena_holds_undrawn = False

    def __repr__(self) -> str:
        # Messages name an act by its class: the framework builds it, so a
        # construction line ("made at system_support.py:364") or the raw
        # ``<__main__.Fase object at 0x…>`` says nothing (PA5).
        return f"act {type(self).__name__}"

    __str__ = __repr__

    def __init_subclass__(cls, **kwargs):
        for key in _CLASS_KEYWORDS:
            if key in kwargs:
                raise TypeError(_DRAW_MSG)
        super().__init_subclass__(**kwargs)
        ns = cls.__dict__
        if "__init__" in ns:
            raise TypeError(
                f"{cls.__name__}: build the act in setup(self), not __init__. "
                f"The framework creates the act when the game enters it."
            )
        setup = ns.get("setup")
        if setup is not None and callable(setup):
            try:
                params = list(inspect.signature(setup).parameters.values())
            except (TypeError, ValueError):
                params = []
            if len(params) != 1:
                raise TypeError(
                    "Act setup() takes no parameters. Read game data from st "
                    "(st.vidas)."
                )
        for name, raw in ns.items():
            if name in _BODY_HOOKS:
                raise TypeError(_BODY_MSG)
            if callable(raw) and any(getattr(raw, t, None) for t in _BODY_TAGS):
                raise TypeError(_BODY_MSG)

    def __init__(self):
        cls = type(self)
        if not _manager._building:
            if cls is Act:
                raise TypeError(_base_class_message())
            raise TypeError(
                f"Acts are entered, not built by hand. Write "
                f"change_act({cls.__name__}) — or run({cls.__name__}) for the "
                f"first act."
            )
        self._construct(layer=None)
        # Current before setup() runs (setup is called by the actor wrapper).
        _manager._attach(self)

    # --- Entity verbs that make no sense on an act ------------------------------

    def destroy(self):
        """Refused: an act ends when the game changes act — write ``change_act(Other)``."""
        raise ActUsageError(
            "An act ends when the game changes act. Write "
            "change_act(Titulo)."
        )

    def cancel_process(self):
        """Refused: to start this act over, write ``change_act(ThisAct)``."""
        raise ActUsageError(
            f"To start this act over, write change_act({type(self).__name__})."
        )

    @property
    def active(self) -> bool:
        """Always ``True`` while the act runs; an act cannot be parked (``= False`` raises)."""
        return bool(getattr(self, "_active", True))

    @active.setter
    def active(self, value) -> None:
        raise ActUsageError(
            "Acts are not parked. To pause the game, write clock.paused = True."
        )

    @property
    def visible(self):
        """Refused: an act does not draw (``ActUsageError``). Its actors have ``.visible``."""
        raise ActUsageError(_DRAW_MSG)

    def __getattr__(self, name: str):
        # A property getter that raises an AttributeError falls through to
        # ``__getattr__``; keep the act message instead of the ink one.
        if name == "visible":
            raise ActUsageError(_DRAW_MSG)
        return super().__getattr__(name)

    @visible.setter
    def visible(self, value) -> None:
        raise ActUsageError(_DRAW_MSG)

    @property
    def layer(self):
        """Always ``None``: an act is not on a layer (assigning raises ``ActUsageError``)."""
        return None

    @layer.setter
    def layer(self, value) -> None:
        raise ActUsageError(_DRAW_MSG)

    def tag(self, *names):
        """Refused: an act is not in groups (``ActUsageError``). Tag the actors it creates."""
        raise ActUsageError(_DRAW_MSG)

    def untag(self, *names):
        """Refused: an act is not in groups (``ActUsageError``)."""
        raise ActUsageError(_DRAW_MSG)

    def add_to_group(self, groupid):
        """Refused: an act is not in groups (``ActUsageError``)."""
        raise ActUsageError(_DRAW_MSG)

    def _assign_groups(self, value) -> None:
        raise ActUsageError(_DRAW_MSG)


# ---------------------------------------------------------------------------
# change_act
# ---------------------------------------------------------------------------

def change_act(act, *args, **kwargs) -> None:
    """Leave the current act and enter ``act`` (an Act class). Immediate.

    Everything the old act created is removed; world settings go back to how
    the top of the file left them. Always builds a fresh instance, even for the
    current act's own class (restart). Game data goes in ``st``.
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('change_act()')
    _check_act_class(act, "change_act")
    if args or kwargs:
        raise TypeError(
            "change_act takes only the act. Put game data in st: "
            "st.vidas = 2, then change_act(Fase)."
        )
    m = _manager
    if not m.sealed:
        from .process import get_scheduler
        if get_scheduler()._running is not None:
            # Law F2: a task's first step runs where run_task is called, so a
            # storyboard started at the top of the file reached change_act
            # before run() (showcase B8).
            raise RuntimeError(
                f"change_act({act.__name__}) ran in a task before the game started: "
                f"a task runs its first step where run_task is called, before "
                f"run(). Wait first (await wait(0)) so it runs once the game is "
                f"going, or start the task in the first act's setup()."
            )
        raise RuntimeError(
            "The game has not started. Start the first act with run(Titulo)."
        )
    if not m.act_mode:
        # The target is rarely where the game begins: a title at the top of
        # the file changing to the level was told run(Fase), and lost its
        # title screen (persona probes R3-4).
        name = act.__name__
        raise RuntimeError(
            f"This game started with run(), with no act, so change_act({name}) has "
            f"nothing to change from. With acts, the game starts in its first act: "
            f"make the title (or whatever comes first) an act too, class "
            f"Titulo(Act), start with run(Titulo), and call change_act({name}) "
            f"from it. If the game begins in {name}, start with run({name})."
        )
    if m.changing:
        owner = m._hook_owner
        where = f"{type(owner).__name__}.on_destroy" if owner is not None else "a hook"
        leaving = m._leaving.__name__ if m._leaving is not None else "the act"
        raise RuntimeError(
            f"change_act({act.__name__}) was called from {where} while the "
            f"game was leaving {leaving}. Put act flow in the act: a @when "
            f"method on {leaving} that calls change_act."
        )
    m.change(act)


# ``*args, **kwargs`` exist only to refuse extra values with the ``st`` fix;
# help() / autocomplete show the one real parameter.
def _publish_change_act_signature() -> None:
    import inspect
    change_act.__signature__ = inspect.Signature(
        [inspect.Parameter("act", inspect.Parameter.POSITIONAL_OR_KEYWORD)],
        return_annotation=None,
    )


_publish_change_act_signature()


# ---------------------------------------------------------------------------
# Retired names (0.6.0): Scene → Act, change_scene → change_act
# ---------------------------------------------------------------------------
#
# Loud, never silent (Scena Design, "Compatibility and versions"): the old
# spelling raises with the new one. ``scena/__init__.py`` answers
# ``scena.Scene`` / ``from scena import Scene`` with these (module
# ``__getattr__``). They are not in ``__all__`` (not API) nor in builtins, so a
# star import does not bring them: ``class Fase(Scene)`` there is a plain
# ``NameError``. Keep them at least until 1.0.

def _retired_scene_message(name: str = "Fase") -> str:
    return (
        f"Scene was renamed to Act in 0.6.0. Write class {name}(Act), "
        f"and change_act({name}) to enter it."
    )


class _RetiredScene(metaclass=RetiredClassMeta):
    """``Scene`` was renamed ``Act`` in 0.6.0; using it raises with the fix
    (a call, a subclass, ``isinstance`` / ``issubclass``)."""

    @staticmethod
    def _retired_type_test(spelling: str) -> str:
        return ("Scene was renamed to Act in 0.6.0. Write "
                + spelling.format(new="Act") + ".")

    def __init_subclass__(cls, **kwargs):
        raise TypeError(_retired_scene_message(cls.__name__))

    def __new__(cls, *args, **kwargs):
        raise TypeError(_retired_scene_message())


_RetiredScene.__name__ = _RetiredScene.__qualname__ = "Scene"


def _retired_change_scene(*args, **kwargs):
    """``change_scene`` was renamed ``change_act`` in 0.6.0; calling it raises with the fix."""
    target = args[0] if args else kwargs.get("scene")
    name = getattr(target, "__name__", None) if isinstance(target, type) else None
    raise TypeError(
        f"change_scene was renamed to change_act in 0.6.0. "
        f"Write change_act({name or 'Fase'})."
    )


_retired_change_scene.__name__ = _retired_change_scene.__qualname__ = "change_scene"

RETIRED_NAMES: Dict[str, Any] = {
    "Scene": _RetiredScene,
    "change_scene": _retired_change_scene,
}
