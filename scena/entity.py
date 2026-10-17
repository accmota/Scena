"""Registry citizens: Entity identity/process host and Graphic draw ABC.

``Shape`` / ``Sprite`` inherit ``Graphic``; ``SpatialFx`` inherits ``Entity``.
Pose / pointer / transient implementations stay on ``Shape`` and are published
onto ``Graphic`` via ``shapes._publish_graphic_api()``.
"""
from __future__ import annotations

import math
import os
import re
import sys
import warnings
import weakref
from abc import ABC
from collections.abc import Sequence
from functools import wraps
import inspect
from typing import Any, Dict, NamedTuple, Optional, Tuple, Union

import skia

from ._defaults import Unset
from .closed import transposed as _transposed
from ._pkg import is_framework_module
from .state import (
    Attribute, CallableAssignError, Container, DestroyedError, LinkedAttributeError,
    _INK_SLOT, _FlagPropertyAnchor, _PropertyAnchor,
    _PaintChannelAnchor, _AmountChannelAnchor, _FlagChannelAnchor,
    callable_assign_message, probe_private, bump_pose_rev,
)
from .scenamath import Vec2
from .validate import expect_bool, refuse_async
from .validate import expect_bool as _expect_flag

# Names that stay real properties / instance fields (never ink Attributes).
# Some names (``width``, ``height``, …) are also ScalarSlots on specific types —
# those remain linkable via ``obj["width"] @=`` when ``_resolve_field`` finds a slot.
# Graphic ``angle`` (the heading) / ``scale`` are property-backed (via
# ``_PropertyAnchor``) unless the subclass declares a real ScalarSlot of the
# same name (Rect / Ellipse / Square / RegularPolygon / Triangle /
# Line / Circle: ``angle``). ``shape["angle"] @=`` / ``shape["scale"] @=``
# link either way. ``rotation`` is retired on Graphics (``_RETIRED_ATTRS``).
_INK_RESERVED = frozenset({
    "layer", "visible", "active", "mode", "mode_time", "group", "time_scale",
    "collidable", "collider", "is_alive", "center", "angle", "scale",
    "mass", "vel", "touching_sides", "touching_contacts",
    "visual", "color", "fill", "line", "parts", "owner", "name",
    "on_click", "on_hover", "on_hover_exit",
    "on_collide", "on_collide_stay", "on_collide_exit", "on_update",
    "on_destroy",
    "clickable", "draggable", "droppable", "wheel_rotate",
    "soft_edge", "field_type",
    "width", "height", "size", "frame", "offset", "hitbox", "hitboxes",
    "flip_x", "flip_y", "art_angle", "rest_heading", "tilt",
    # Geometry discriminant — plain instance field on every Shape; must not become ink.
    "model",
    # Text caption fields
    "text", "font_size", "background", "align",
    # PaintState channels + appearance stamps (plain properties, not graph cells)
    "line_width", "dash", "line_cap", "line_join", "blend",
    "line_filter", "fill_filter",
    "glow", "shadow", "hue", "gray", "tail",
    "alpha",
    # Paint-only radius on Rect / Square. Not a geometry slot.
    "corner_radius",
})

# Field-specific hints when bracket ``@=`` or ``field = lambda: …`` targets a reserved name.
_INK_LINK_FORBIDDEN_HINTS: Dict[str, str] = {
    "visual": "Assign with `.visual = Neon()` / `Paint(color)` / a `Gradient`.",
    "fill": "Assign with `.fill = Color(…)` / `Gradient(…)` or `.set_color(…)`.",
    "line": "Assign with `.line = Color(…)` or `.set_color(…)`.",
    "color": "Assign with `.color = …` or `.set_color(…)`.",
    "line_width": "Assign with `.line_width = 2` (a plain number).",
    "corner_radius": "Paint only: assign a number with `.corner_radius = 8`.",
    "dash": "Assign with `.dash = 'dash'`.",
    "line_cap": "Assign with `.line_cap = 'round'`.",
    "line_join": "Assign with `.line_join = 'miter'`.",
    "blend": "Assign with `.blend = 'multiply'`.",
    "line_filter": "Assign with `.line_filter = Blur(…)` / `GlowFilter(…)` / …",
    "fill_filter": "Assign with `.fill_filter = …` (an `ImageFilter` wrapper).",
    "glow": "Assign with `.glow = True` / `Glow(…)` / `CheapGlow(…)`.",
    "shadow": "Assign with `.shadow = True` / a shadow look.",
    "hue": "Sprite-only: `.hue = HueShift(…)`; on shapes use `Texture(..., shift=HueShift(…))`.",
    "gray": "Sprite-only: `.gray = True` / a number 0–1 / `Grayscale(…)`.",
    "tail": "Assign with `.tail = True` / `Tail(…)`.",
    "alpha": "Sprite-only: `.alpha = 0.5` (or `set_alpha(0.5)`) fades the body blit, 0–1.",
    "align": "Assign with `.align = 'left'` / `'center'` / `'right'`.",
    "angle": (
        "Link with `shape['angle'] @= source` (Graphics only). Setting the "
        "heading keeps the point the shape was placed by; `rotate_to` / "
        "`rotate_by` turn the whole shape about its center."
    ),
    "tilt": "Sprite-only visual lean: `.tilt = contact` rotates about contact.point. Does not rotate the collider.",
    "scale": "Link with `shape['scale'] @= source` (Graphics only). Assign a number with `.scale = …` / `scale_by(…)`.",
    "visible": "Use `.visible = True` / `False`.",
    "active": "Use `.active = True` / `False` (park / unpark).",
    "touching_sides": "Engine-owned — read only.",
    "collider": "Its collider is `.hitbox`; `.collidable = False` turns collisions off.",
    "vel": (
        "The engine writes it (`resolve(..., bounce=)`, `confine(action=\"bounce\")`), "
        "and so does `vel.y -= g * dt`. Set it where it changes: "
        "`ship.vel = vec_from_angle(st.a * 30, 10)` in `on_update`."
    ),
}


_PROPERTY_LINK_FIELDS = frozenset({"angle", "scale"})
# Appearance fields and flags a class may declare linkable (Reactive Design —
# Appearance links): ``@=`` re-runs ``=`` when the formula's sources change.
# Link targets only: a formula that reads them keeps following the object
# itself, as before (``_TARGET_ONLY_LINKS``).
_CHANNEL_LINK_ANCHORS = {
    "color": _PaintChannelAnchor,
    "fill": _PaintChannelAnchor,
    "line": _PaintChannelAnchor,
    "background": _PaintChannelAnchor,
    "line_width": _AmountChannelAnchor,
    "alpha": _AmountChannelAnchor,
    "visible": _FlagChannelAnchor,
    "flip_x": _FlagChannelAnchor,
    "flip_y": _FlagChannelAnchor,
}
_TARGET_ONLY_LINKS = frozenset(_CHANNEL_LINK_ANCHORS)
# The anchor class of every property link a class may declare
# (``_property_link_extra``); ``angle`` / ``scale`` use ``_PropertyAnchor``.
_PROPERTY_LINK_ANCHORS = dict(_CHANNEL_LINK_ANCHORS, enabled=_FlagPropertyAnchor)
# Every name some class may declare linkable through ``_property_link_extra``
# (a property + ``@=``); the cheap pre-check before the per-class lookup.
_PROPERTY_LINK_ANY = _PROPERTY_LINK_FIELDS | frozenset(_PROPERTY_LINK_ANCHORS)
# Pose fields pulled before draw / collision / hit-test (``_pull_property_anchors``):
# the heading and scale always, a flip where the class links it.
_POSE_PULL_FLIPS = ("flip_x", "flip_y")
# Collision's pose key reads these slots when a class declares them (live
# angle / size); the per-class tuple is ``cls._scena_extra_slots``.
GRAPHIC_EXTRA_SLOTS = (
    "angle", "at_angle", "radius", "width", "height", "length", "side", "spread",
)


def _refuse_class_keywords(cls, kwargs) -> None:
    """Class keywords no family took (Shape, Sprite, SpatialFx and Text take
    theirs before this): an author error naming the fix, not Python's "takes no
    keyword arguments" (the AC2 class). A class later in the MRO with its own
    ``__init_subclass__`` (an author mixin) may still want them."""
    rest = cls.__mro__[cls.__mro__.index(Entity) + 1:]
    if any("__init_subclass__" in k.__dict__ for k in rest if k is not object):
        return
    from ._pkg import is_framework_module
    kind = next((k for k in cls.__mro__[1:] if is_framework_module(k.__module__)), Entity)
    names = ", ".join(f"{k}=" for k in sorted(kwargs))
    first = sorted(kwargs)[0]
    raise TypeError(
        f"class {cls.__name__}({kind.__name__}, {names}): {kind.__name__} subclasses "
        f"take no class keywords (Shape, Sprite, SpatialFx and Text subclasses do). "
        f"Pass them when you make one: {cls.__name__}({first}=...)."
    )


def _framework_kind(cls: type) -> type:
    """The nearest Scena class in ``cls``'s MRO (``Bolha`` → ``Circle``)."""
    from ._pkg import is_framework_module
    return next((k for k in cls.__mro__ if is_framework_module(k.__module__)), Entity)


def _kind_route(kind: type) -> Dict[str, Any]:
    """The Scena kind's setter routes: every public name Scena owns on it."""
    route = kind.__dict__.get("_setattr_route")
    if route is None:
        _install_setattr_route(kind)
        route = kind._setattr_route  # type: ignore[attr-defined]
    return route


def _refuse_class_body_values(cls: type) -> None:
    """A value in an author class body under a name Scena owns (``radius = 30``,
    ``visible = False``, ``group = "laser"``) is never the object's: construction
    writes Scena's own field, and the class value only hides it from reads
    (``radius`` read the default; ``visible`` read ``False`` while the shape
    drew). Refused on the class line with the fix (CB2). Methods, properties
    and other descriptors are the author's to define."""
    from ._pkg import is_framework_module
    kind = _framework_kind(cls)
    route = _kind_route(kind)
    for k in cls.__mro__:
        if k is object or is_framework_module(k.__module__):
            continue
        for name, value in k.__dict__.items():
            if not name or name[0] == "_" or name not in route:
                continue
            if hasattr(type(value), "__get__"):     # a method, property, descriptor
                continue
            raise TypeError(_class_body_value_message(cls, kind, name, value, route[name]))


def _class_body_value_message(cls: type, kind: type, name: str, value: Any, route: Any) -> str:
    shown = repr(value)
    if len(shown) > 40:
        shown = "..."
    bases = ", ".join(b.__name__ for b in cls.__bases__)
    head = f"class {cls.__name__}({bases}): {name} = {shown} in the class body"
    if isinstance(route, _RouteRefusal):
        return f"{head}: {route.message.format(cls=kind.__name__)}"
    if route is _LOOK_MISSING:
        return f"{head}: {_look_missing_text(kind.__name__, name)}"
    why = (f"{head} does not change {name}: Scena keeps {name} on each "
           f"{cls.__name__}, not on the class.")
    if name in cls._class_keywords():
        line = "".join(f", {k}={v!r}" for k, v in _own_class_keywords(cls).items()
                       if k != name)
        return (f"{why} Put it on the class line: "
                f"class {cls.__name__}({bases}{line}, {name}={shown}).")
    return f"{why} Set it in setup(self): self.{name} = {shown}."


# Where each family keeps the merged class keywords of a subclass.
_CLASS_DEFAULT_TABLES = ("_shape_defaults", "_sprite_defaults", "_class_defaults")


def _own_class_keywords(cls: type) -> Dict[str, Any]:
    """The keywords ``cls``'s own class line set (its table minus its parent's)."""
    own: Dict[str, Any] = {}
    parent = cls.__mro__[1]
    for attr in _CLASS_DEFAULT_TABLES:
        mine = cls.__dict__.get(attr) or {}
        theirs = getattr(parent, attr, None) or {}
        own.update((k, v) for k, v in mine.items() if k not in theirs or theirs[k] is not v)
    return own


def _init_owner(fn, cls: type) -> str:
    """The class whose ``__init__`` ``fn`` is (``Bolha``; an author mixin's own name)."""
    parts = getattr(fn, "__qualname__", "").split(".")
    return parts[-2] if len(parts) >= 2 else cls.__name__


def _never_built_message(item) -> str:
    """An author ``__init__`` that never ran Scena's own (CB1)."""
    cls = type(item)
    kind = _framework_kind(cls)
    owner = _init_owner(inspect.unwrap(cls.__init__), cls)
    return (
        f"{owner}.__init__ never called {kind.__name__}'s own __init__, so this "
        f"{cls.__name__} was not built: it is not in the game (nothing draws, "
        f"on_update never runs). Drop __init__ and write def setup(self): Scena "
        f"calls it once the {cls.__name__} is built. An __init__ of your own must "
        f"take **kwargs and call super().__init__(**kwargs)."
    )


def _never_built(item) -> bool:
    """``_construct`` never ran on ``item`` (it sets ``_actor_constructed``)."""
    try:
        object.__getattribute__(item, "_actor_constructed")
    except AttributeError:
        return True
    return False


def _read_before_built_message(item, name: str) -> str:
    """``self.radius`` (or a method, which reads Scena's private fields) in an
    author ``__init__`` before Scena's own ran (CB1)."""
    cls = type(item)
    kind = _framework_kind(cls)
    owner = _init_owner(inspect.unwrap(cls.__init__), cls)
    what = f"has no {name} yet" if name[:1] != "_" else "is not built yet"
    ready = f", with {name} ready" if name[:1] != "_" else ""
    return (
        f"{cls.__name__} {what}: {owner}.__init__ has not called "
        f"{kind.__name__}'s own __init__, which builds it. Drop __init__ and write "
        f"def setup(self): Scena calls it once the {cls.__name__} is built{ready}. "
        f"An __init__ of your own must call super().__init__(**kwargs) before it "
        f"uses self."
    )


def _explain_author_init_keywords(orig, cls: type, kwargs: dict, exc: TypeError) -> None:
    """``Bolha(center=…)`` against an author ``def __init__(self)``: Python's
    complaint names the author's ``__init__``, and the generic rewrite said
    "Write Bolha()" — advice that led straight to the object never built (CB1).
    Raises only for keywords Scena owns; a typo of the author's own parameter
    falls through to the near-miss rewrite."""
    from ._pkg import is_framework_module
    fn = inspect.unwrap(orig)
    if is_framework_module(getattr(fn, "__module__", "") or ""):
        return
    if not str(exc).startswith(f"{getattr(fn, '__qualname__', '')}()"):
        return
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return
    kind = _framework_kind(cls)
    route = _kind_route(kind)
    theirs = [k for k in kwargs if k not in params and k in route]
    if not theirs:
        return
    owner = _init_owner(fn, cls)
    got = ", ".join(f"{k}=" for k in theirs)
    raise TypeError(
        f"{cls.__name__}() got {got}, but {owner}.__init__ does not take "
        f"{'it' if len(theirs) == 1 else 'them'}: it replaced {kind.__name__}'s own "
        f"__init__, which does. Drop __init__ and write def setup(self): Scena "
        f"calls it once the {cls.__name__} is built. An __init__ of your own must "
        f"take **kwargs and call super().__init__(**kwargs)."
    ) from None


# Class-body hook names the engine never calls on an actor (PA3 / PC5).
# The top-of-file callbacks (``orchestration.set_auto_callbacks``) are read
# from the module only; in a class body they are dead code.
_TOP_LEVEL_INPUT_HOOKS = (
    "on_key_down", "on_key_up", "on_key", "on_char",
    "on_mouse_down", "on_mouse_up", "on_mouse_click", "on_mouse_double_click",
    "on_mouse_move", "on_mouse_drag", "on_mouse_scroll",
)
# Hook names an actor class may define (near-miss targets). Engine bases add
# their own ``on_*`` names (``on_drag_to``, ``on_submit``) through the MRO.
_CLASS_HOOK_NAMES = (
    "on_update", "on_destroy", "on_click", "on_hover", "on_hover_exit",
    "on_collide", "on_collide_stay", "on_collide_exit",
    "on_drag_to", "on_drag_over", "on_drop_by",
)
# Other engines' spellings, more than one edit from Scena's.
_FOREIGN_HOOK_NAMES = {
    "on_collision": "on_collide",
    "on_collision_enter": "on_collide",
    "on_collide_enter": "on_collide",
    "on_collision_stay": "on_collide_stay",
    "on_collision_exit": "on_collide_exit",
    "on_mouse_enter": "on_hover",
    "on_mouse_over": "on_hover",
    "on_mouse_exit": "on_hover_exit",
    "on_mouse_leave": "on_hover_exit",
}


def _plain_function(raw) -> bool:
    return inspect.isfunction(raw) and not any(
        getattr(raw, t, None) for t in (
            "_every_spec", "_after_spec", "_collide_with_specs",
            "_leave_playfield_method", "_when_specs",
        )
    )


def _signature_text(fn) -> str:
    """``(self, dt)`` as written, for a message; ``(...)`` if unreadable."""
    import inspect
    try:
        return str(inspect.signature(fn))
    except (TypeError, ValueError):
        return "(...)"


def _check_class_hook_names(cls) -> None:
    """Refuse a class-body method the engine would never call, at the class
    line (review 2026-10-14 PA3 / PC5).

    * ``def update(self, dt)``: on an act it was silently never called; on a
      Shape / Sprite it overrode ``Container.update`` (the graph recalculation)
      and the construction crashed deep in ``state._batch_update``.
    * The top-of-file input callbacks (``on_key_down``, ``on_mouse_click``, …)
      in a class body: never called.
    * A near miss of a hook (``on_colide``, ``on_updat``, ``on_destory``: one
      edit or one swap away), another engine's spelling (``on_collision``),
      and a plain method named ``collide_with`` (the decorator's name).

    Author classes only; names the class's own bases define are theirs
    (an author ``on_hit`` helper is never one edit from a hook name, and a
    base's names were checked with the base).
    """
    from ._pkg import is_framework_module
    if is_framework_module(cls.__module__):
        return
    ns = cls.__dict__
    is_act = bool(getattr(cls, "_scena_is_act", False))
    who = cls.__name__
    for name, raw in ns.items():
        if not _plain_function(raw):
            continue
        if name == "update":
            # Any signature: ``update`` is ``Container.update`` (the graph
            # recalculation) on an act as on an actor, so even a helper
            # ``def update(self)`` shadows it (release audit C15).
            sig = _signature_text(raw)
            if is_act:
                raise TypeError(
                    f"{who}.update{sig}: update is reserved in an act too (it is the "
                    f"engine's own recalculation of linked fields), so the engine "
                    f"would not call it per frame. The per-frame hook is "
                    f"on_update(self, dt) (update(dt) is the top-of-file spelling); "
                    f"a helper of your own needs another name."
                )
            raise TypeError(
                f"{who}.update{sig}: an actor's per-frame hook is "
                f"on_update(self, dt). update is reserved: it is the engine's own "
                f"recalculation of the object's linked fields. Rename it on_update "
                f"(a helper of your own needs another name)."
            )
        if name in _TOP_LEVEL_INPUT_HOOKS:
            raise TypeError(_top_level_hook_message(who, name, is_act))
        if name == "collide_with":
            raise TypeError(
                f"{who}.collide_with is the name of a decorator, not a hook: the "
                f"engine never calls this method. Write on_collide(self, other) "
                f"for every touch, or @collide_with(\"group\") above a method of "
                f"another name for one group."
            )
        if not name.startswith("on_") or name in _CLASS_HOOK_NAMES:
            continue
        if any(name in k.__dict__ for k in cls.__mro__[1:]):
            continue        # the base's own name (engine or author)
        fix = _FOREIGN_HOOK_NAMES.get(name)
        if fix is None:
            pool = set(_CLASS_HOOK_NAMES)
            for k in cls.__mro__[1:]:
                if is_framework_module(k.__module__):
                    pool.update(n for n in k.__dict__ if n.startswith("on_"))
            hits = sorted(c for c in pool if _one_edit_apart(name, c))
            fix = hits[0] if hits else None
        if fix is not None:
            raise TypeError(
                f"{who}.{name} is not a hook name, so the engine would never call "
                f"it. Did you mean {fix}? (A helper of your own: give it a name "
                f"that is not one letter away from a hook.)"
            )


def _top_level_hook_message(who: str, name: str, is_act: bool) -> str:
    keys = name in ("on_key_down", "on_key_up", "on_key", "on_char")
    if is_act:
        if keys:
            how = 'read the key in on_update(self, dt) with keyp.once("SPACE")'
        else:
            how = ("read the mouse in on_update(self, dt) (mouse.press(), mouse.x), "
                   "or give the actor that is clicked an on_click(self)")
        return (
            f"{who}.{name} would never be called: the top-of-file input functions "
            f"do not run on an act. Instead, {how}."
        )
    if keys:
        how = 'read the key in on_update(self, dt) with keyp.once("SPACE")'
    elif name in ("on_mouse_click", "on_mouse_down", "on_mouse_up",
                  "on_mouse_double_click"):
        how = "an actor's click hook is on_click(self)"
    elif name == "on_mouse_move":
        how = "an actor's pointer hooks are on_hover(self) / on_hover_exit(self)"
    elif name == "on_mouse_drag":
        how = "make the actor draggable = True"
    else:
        how = "read the mouse in on_update(self, dt)"
    return (
        f"{who}.{name} would never be called: it is a top-of-file function name, "
        f"and the engine does not call it on an actor. Instead, {how}."
    )


def _cache_class_tables(cls: type) -> None:
    """Per-class tables the hot paths read as plain class attributes.

    Computed once, when the class is made (``Entity.__init_subclass__``), and
    stored on the class itself — never in a module dict keyed by the class: a
    key is a strong reference, and an author's class (with its module's
    globals) would outlive the program (AC1, tests/test_author_class_lifetime.py).
    """
    slots = set()
    for base in cls.__mro__:
        for name, val in base.__dict__.items():
            if getattr(val, "_is_field_slot", False):
                slots.add(name)
    links = frozenset(n for n in _PROPERTY_LINK_FIELDS if n not in slots)
    # Union over the MRO: a subclass that adds its own (SpriteButton's
    # ``enabled``) keeps its bases' (Sprite's ``alpha`` / ``visible`` / flips);
    # ``_property_link_exclude`` takes names back (Point, Track, Text flips).
    extra, exclude = set(), set()
    for base in cls.__mro__:
        extra.update(base.__dict__.get("_property_link_extra", ()) or ())
        exclude.update(base.__dict__.get("_property_link_exclude", ()) or ())
    links |= frozenset(extra - exclude)
    cls._scena_property_links = links
    cls._scena_target_only = links & _TARGET_ONLY_LINKS
    cls._scena_pose_pull = tuple(sorted(_PROPERTY_LINK_FIELDS)) + tuple(
        n for n in _POSE_PULL_FLIPS if n in links)
    cls._scena_kind_name = _kind_of_class(cls)
    cls._scena_extra_slots = tuple(
        n for n in GRAPHIC_EXTRA_SLOTS
        if getattr(getattr(cls, n, None), "_is_field_slot", False))
    live = cls.__dict__.get("_setattr_route")
    if live is None:
        _install_setattr_route(cls)
        live = cls._setattr_route
    cls._scena_dead_route = _DeadRoute({name: live[name] for name in _DEAD_QUIET if name in live})


def _property_link_names(obj) -> frozenset:
    """The property-backed linkable fields of this class (``_cache_class_tables``).

    ``_PROPERTY_LINK_FIELDS`` not backed by a real slot (``angle`` is a slot on
    Rect / Line / Circle, a property on Sprite / Point — and ``x["angle"]`` is
    on the per-frame path), plus the class's own ``_property_link_extra``
    (``SpriteButton.enabled``; names listed in ``_PROPERTY_LINK_ANY``)."""
    return type(obj)._scena_property_links


# The heading used to be ``rotation`` on Graphics; it is ``angle`` now
# (Shapes Design — Geometry contract). A write must not become ink.
_ROTATION_RETIRED = (
    "A Graphic's heading is `angle`, not `rotation`. `x.angle = 30` keeps the "
    "point it was placed by (its center, top_left, p1, a vertex…); "
    "`x.rotate_to(30)` / `x.rotate_by(30)` turn the whole shape about its "
    "center (or `about=`). Link with `x['angle'] @= …`."
)


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


# The kind that has a reserved name another kind lacks (``rect["text"] @=``).
_RESERVED_FAMILY = {
    "text": "Text", "font_size": "Text", "background": "Text", "align": "Text",
    "frame": "Sprite", "hitboxes": "Sprite", "offset": "Sprite", "tilt": "Sprite",
    "art_angle": "Sprite", "alpha": "Sprite",
    "corner_radius": "Rect / Square", "soft_edge": "SpatialFx", "model": "Shape",
}


def _ink_link_forbidden_message(owner: "Entity", field: str) -> str:
    """The refusal when ``@=`` (or ``= lambda``) targets a reserved name.

    Read from the kind's route table, so every kind answers the same way:
    a field it does not have, a property (set it with ``=``), or a read-only
    value (computed for you). Before, only ``_ink_strict`` kinds (Line, Point)
    said which; the others said "appearance and built-in properties" even for
    a field they lack (``rect["text"]``)."""
    cls = type(owner)
    kind = cls.__name__
    route_map = _kind_route(cls)
    route = route_map.get(field)
    if isinstance(route, _RouteRefusal) and route.link is not None:
        return route.link.format(cls=kind)      # built beside the ``=`` words
    if isinstance(route, _RouteRefusal) and route.kind != "absent":
        if route.kind == "read_only":
            return (f"{kind}.{field} cannot be linked with @= — it is read-only: "
                    f"it is computed for you, so it cannot be set either.")
        return route.message.format(cls=kind)
    absent = isinstance(route, _RouteRefusal) or route is _LOOK_MISSING
    if route is _SET_OBJECT or route is None:
        try:
            object.__getattribute__(owner, field)
        except AttributeError:
            absent = True
    if absent:
        size = ""
        if field in _SIZE_WORDS:
            own = [w for w in _SIZE_WORDS if w != "corner_radius" and w in route_map
                   and not isinstance(route_map.get(w), _RouteRefusal)]
            if own:
                size = " Size it with " + " / ".join(own) + "."
        # The words ``=`` answers with (a bare Entity's ``angle`` adds its hint).
        return _absent_reserved_text(field, ", so @= has nothing to link", size).format(cls=kind)
    hint = _INK_LINK_FORBIDDEN_HINTS.get(field)
    if hint is None:
        hint = f"Set it with `{kind.lower()}.{field} = …`."
    drive = (
        "To drive it from game state, use `on_update`, `@on_change`, or `@when`; "
        "link custom ink (`ship.hp`) or geometry (`ship.center.x`, `rect.width`, …)."
    )
    return f"{kind}.{field} cannot be linked with @= — it is a property. {hint} {drive}"

# Geometry leaf types (Point, Line) set ``_ink_strict = True`` in their own
# class body: bracket typos stay AttributeError (no ink auto-materialize).
# Read from the class's own ``__dict__``: an author subclass (``class
# Laser(Line)``) is where new ink fields live, so only the bare Scena kinds
# refuse unknown keys. It went by class *name*, so an author class named
# ``Point`` became strict (graphics review E18).

# Per-class setattr routing (built in ``__init_subclass__``). Values are either a
# data descriptor (``__set__``) or ``_SET_OBJECT`` for reserved plain fields.
_SET_OBJECT = object()
_LOOK_MISSING = object()


def _require_group_name(value, verb: str) -> str:
    """One non-empty tag for ``add_to_group`` / ``remove_from_group`` / ``tagged``.

    A collection is not a name — several tags go through ``tag`` / ``untag``.
    """
    if isinstance(value, str) and value:
        return value
    plural = "untag" if verb == "remove_from_group" else "tag"
    if isinstance(value, (list, tuple, set, frozenset)):
        raise TypeError(
            f"{verb}() takes one group name; for several write "
            f'{plural}("a", "b").'
        )
    raise TypeError(
        f"{verb}() needs a non-empty group name, "
        f"got {type(value).__name__} {value!r}."
    )


class GroupTags(frozenset):
    """Read-only snapshot of an item's groups (what ``shape.group`` returns).

    ``shape.group`` is mirrored by the registry's group index (``group["x"]``,
    collision tags). A live ``set`` let ``shape.group.add("x")`` edit the
    mirror without the index — ``group["x"]`` never saw the shape. The registry
    swaps in a new snapshot on every tag / untag; in-place mutators raise
    with the synced spelling. ``shape.group |= {"x"}`` still works: it
    rebinds ``shape.group``, which routes through the synced setter.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return repr(frozenset(self))


def _refuse_group_mutation(method: str):
    def refuse(self, *args, **kwargs):
        raise AttributeError(
            f"shape.group is a read-only snapshot, so .group.{method}(...) "
            f"would not reach group[...]. Write shape.tag(\"name\") / "
            f"shape.untag(\"name\"), or assign shape.group = [\"a\", \"b\"]."
        )
    refuse.__name__ = method
    refuse.__doc__ = (
        f"Refused: ``shape.group`` is a read-only snapshot. Use "
        f"``shape.tag(...)`` / ``shape.untag(...)`` or assign ``shape.group``."
    )
    return refuse


for _m in (
    "add", "discard", "remove", "pop", "clear", "update",
    "difference_update", "intersection_update", "symmetric_difference_update",
):
    setattr(GroupTags, _m, _refuse_group_mutation(_m))
del _m


def _normalize_groups(group) -> GroupTags:
    """``None`` / ``"tag"`` / sequence of tags → a fresh :class:`GroupTags`."""
    if group is None:
        return GroupTags()
    if isinstance(group, str) and group:
        return GroupTags((group,))
    if (isinstance(group, (Sequence, set, frozenset)) and not isinstance(group, str)
            and all(isinstance(x, str) and x for x in group)):
        return GroupTags(group)
    if group == "" or (isinstance(group, (Sequence, set, frozenset)) and "" in group):
        # ``group=""`` was a group no ``tag("")`` could name (graphics review E10).
        raise TypeError('group names must be non-empty strings: write group="enemies", or group=None for none')
    raise TypeError(
        f"group expected a tag string or a list of tag strings, got "
        f"{type(group).__name__} {group!r}. Write group=\"enemies\" or "
        f"group=[\"enemies\", \"flying\"]."
    )


# Look / paint properties that exist on some Graphic kinds only. They are
# reserved (never ink), so on a kind without the property the write used to
# land in a plain attribute that nothing reads (``circle.alpha = 0.5``).
_LOOK_FAMILY = frozenset({
    "alpha", "blend", "font_size", "line_width", "line_cap", "line_join",
    "dash", "fill_filter", "line_filter", "hue", "gray", "corner_radius",
})
_INK_SPELLINGS = {
    "colour": "color", "centre": "center", "velocity": "vel", "font": "font_size",
    # Not one edit from ``active`` (different first letter). Listed so the write
    # raises instead of becoming ink that park never reads. Not ``_INK_RESERVED``:
    # a reserved name with no property is stored and still does nothing.
    "enable": "active", "enabled": "active",
    # ``angle`` is too short for the one-edit check below (len >= 6).
    "angel": "angle", "agnle": "angle",
}


def _pose_xy_refused(owner, name: str) -> bool:
    """True when ``name`` is the pose alias Graphics do not have.

    ``x`` / ``y`` stay ink on a bare Entity. On Graphic and SpatialFx they
    would silently store a number the sprite never reads — position is
    ``.center``. Point keeps real ``x`` / ``y`` slots, so the route hits
    first and this guard never runs.
    """
    return name in ("x", "y") and getattr(type(owner), "_pose_xy_guard", False)


def _pose_xy_forbidden_message(owner, name: str) -> str:
    kind = type(owner).__name__
    return (
        f"{kind} has no `.{name}`; its position is `.center`. "
        f"Read with `ship.center.{name}`. "
        f"Move with `move_to(...)` / `move_by(...)`. "
        f"Link with `ship.center['{name}'] @= …`."
    )


# ``Entity.__getattr__`` reads ink directly when the full path would return
# it (tests/test_ink_read_fast.py: same value or error either way). False:
# always the full path (oracle, A/B).
_INK_READ_FAST = True
_obj_getattr = object.__getattribute__


def _retired_attr_message(owner, name: str):
    """The hint for a public name this class retired, or ``None``.

    A class lists them in ``_RETIRED_ATTRS`` (name → message); a subclass's
    own list adds to its bases'. Without this an old spelling
    (``sprite.hitbox_scale = 0.5``, ``ship.rotation = 90``) would silently
    become ink.
    """
    cls = type(owner)
    # Cached on the class itself: a module dict keyed by class pinned author
    # classes defined inside functions (graphics review E17).
    merged = cls.__dict__.get("_scena_retired_merged")
    if merged is None:
        merged = {}
        for klass in reversed(cls.__mro__):
            merged.update(klass.__dict__.get("_RETIRED_ATTRS") or {})
        type.__setattr__(cls, "_scena_retired_merged", merged)
    return merged.get(name) if merged else None


def _look_missing_message(owner, name: str) -> str:
    return _look_missing_text(type(owner).__name__, name)


def _look_missing_text(kind: str, name: str) -> str:
    return _absent_reserved_text(name).format(cls=kind)     # what ``@=`` answers


def _one_edit_apart(a: str, b: str) -> bool:
    """Levenshtein distance 1, or one adjacent transposition."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or a == b:
        return False
    if la == lb:
        diff = [i for i in range(la) if a[i] != b[i]]
        return len(diff) == 1 or _transposed(a, b)
    if la > lb:
        a, b = b, a
    for i in range(len(b)):
        if a == b[:i] + b[i + 1:]:
            return True
    return False


def _ink_exact_name_message(cls: type, name: str, known) -> Optional[str]:
    """A new ink name that is exactly a name of the class (PC2, 2026-10-14).

    ``=`` on a method or a read-only property refuses through the route table
    (R8), but ``obj["name"] @= f`` (and a plain write the route does not see)
    went to ink: a link nothing reads, beside the method or property that
    keeps the name. Same refusal as ``=``. A class may name its own
    near-fields first (``_ink_name_refusal``: Polygon ``points`` / ``vN``).
    """
    own = getattr(cls, "_ink_name_refusal", None)
    if own is not None:
        msg = own(name)
        if msg is not None:
            return msg
    hit = known.get(name)
    if isinstance(hit, _RouteRefusal):
        return hit.message.format(cls=cls.__name__)
    if hit is not None and hit is not _SET_OBJECT and hit is not _LOOK_MISSING:
        # A settable property (Track.is_floating …): ink would hide behind it.
        who = cls.__name__
        return (f"{who}.{name} is a property: set it with {who.lower()}.{name} = …; "
                f"@= cannot link it. A field of your own needs another name.")
    return None


def _ink_near_miss_message(cls: type, name: str, known) -> Optional[str]:
    who = cls.__name__
    exact = _ink_exact_name_message(cls, name, known)
    if exact is not None:
        return exact
    fix = _INK_SPELLINGS.get(name)
    if fix is not None and fix in known:
        if name == "font":
            return (
                f"{who} has no 'font'. Size is {who.lower()}.font_size = …. "
                f"There is no font-family property."
            )
        if fix == "active":
            return f"{who} has no {name!r}. {_INK_LINK_FORBIDDEN_HINTS['active']}"
        return f"{who} has no {name!r}; Scena spells it {fix!r} ({who.lower()}.{fix} = …)."
    # One edit from a retired name (``rotaton``): the retired name's own hint.
    for klass in cls.__mro__:
        for old, hint in (klass.__dict__.get("_RETIRED_ATTRS") or {}).items():
            if len(old) >= 6 and _one_edit_apart(name, old):
                return f"{who} has no {name!r}. {hint}"
    # Two rules (Actors Design, "Ink"): a 6+ letter property one edit away with
    # the same first letter; or a 5+ letter property one adjacent swap away at
    # any position (``anlge``, ``widht``, ``lyaer``, ``nagle``). Plain deletions
    # on short names (``coor``, ``laer``) stay ink.
    hits = sorted(
        c for c in known
        if not c.startswith("on_")
        and (
            (len(c) >= 6 and c[0] == name[0]
             and name != c + "s" and c != name + "s"
             and _one_edit_apart(name, c))
            or (len(c) >= 5 and _transposed(name, c))
        )
    )
    if hits:
        return (
            f"{who} has no {name!r}. Did you mean {hits[0]!r}? "
            f"(A new name would create an ink variable; use a name that is not "
            f"one typo away from a {who} property.)"
        )
    return None


_NO_VALUE = object()
# Short properties whose one-edit neighbours are real field names (``laser`` /
# ``layer``, ``owned`` / ``owner``, ``modo`` / ``mode``), so the one-edit rule
# above skips them. A new name one edit from one of these refuses only when the
# value is the kind the property takes: ``bola.colr = "red"`` is a typo,
# ``self.lime = 3`` is a field (Actors Design, "Ink").
_TYPO_VALUE_KINDS = {
    "color": "paint", "fill": "paint", "line": "paint",
    "alpha": "number", "angle": "number", "scale": "number", "width": "number",
}
_PAINT_TYPES = None


def _is_paint_value(value) -> bool:
    """A value ``color`` / ``fill`` / ``line`` take: an exact colour name, ``#hex``,
    an ``(r, g, b[, a])`` tuple, a Color / Gradient / Paint / Texture. No fuzzy
    name match: it costs 40-240 us and a near-miss value is a second typo."""
    global _PAINT_TYPES
    t = type(value)
    if t is int or t is float or t is bool or value is None:
        return False
    if t is str:
        from .color import ColorNames
        if value.startswith("#"):
            return True
        return ColorNames._peel_modifiers(ColorNames.normalize(value))[1] in ColorNames._COLORS
    if t is tuple:
        return len(value) in (3, 4) and all(type(v) in (int, float) for v in value)
    if _PAINT_TYPES is None:
        from .color import Color
        from .style import Gradient, Texture
        from .visuals import Paint
        _PAINT_TYPES = (Color, Gradient, Paint, Texture)
    return isinstance(value, _PAINT_TYPES)


def _value_near_miss_candidates(name: str, route_map):
    """``((prop, kind), …)`` of ``_TYPO_VALUE_KINDS`` that ``name`` is one edit
    from (same first letter, not a plural, not ``prop`` + digits) and that the
    class has as a property, or ``None``."""
    out = []
    for prop, kind in _TYPO_VALUE_KINDS.items():
        # A property of the kind (slot or setter). Not a reserved name stored
        # plain (``_SET_OBJECT``: a bare Entity's inert ``color``), not a refusal.
        route = route_map.get(prop)
        if route is None or not hasattr(type(route), "__set__") or isinstance(route, _RouteRefusal):
            continue
        if name[0] != prop[0] or name == prop + "s" or prop == name + "s":
            continue
        if name[-1].isdigit() and name.rstrip("0123456789") == prop:
            continue
        if _one_edit_apart(name, prop):
            out.append((prop, kind))
    return tuple(out) or None


def _value_near_miss_message(cls: type, name: str, prop: str) -> str:
    who = cls.__name__
    return (
        f"{who} has no {name!r}. Did you mean {prop!r}? "
        f"(A new name would create a field of your own; use a name that is not "
        f"one typo away from a {who} property.)"
    )


def _check_ink_near_miss(cls: type, name: str, route_map, value=_NO_VALUE) -> None:
    """Raise when a new ink name is a near-miss of a real property (typo guard).

    Cached per ``(class, name)``: the check runs once per new ink name, never
    on later writes of an existing ink field. The entry is the refusal text,
    ``None``, or the ``_TYPO_VALUE_KINDS`` candidates whose refusal depends on
    ``value`` (``=`` passes it; a bracket ``@=`` creation has only a formula,
    so it skips them).
    """
    cache = cls.__dict__.get("_scena_ink_near_miss")      # on the class (E17)
    if cache is None:
        cache = {}
        type.__setattr__(cls, "_scena_ink_near_miss", cache)
    try:
        msg = cache[name]
    except KeyError:
        msg = _ink_near_miss_message(cls, name, route_map)
        if msg is None:
            msg = _value_near_miss_candidates(name, route_map)
        cache[name] = msg
    if msg is not None:
        if msg.__class__ is str:
            raise AttributeError(msg)
        if value is _NO_VALUE:
            return
        for prop, kind in msg:
            if (_is_paint_value(value) if kind == "paint"
                    else type(value) is int or type(value) is float):
                raise AttributeError(_value_near_miss_message(cls, name, prop))


# Routed names a destroyed actor may still be written with, as a quiet no-op
# (Actors Design: ``active = True`` does not revive; ``mode = None`` stays quiet).
# ``on_update`` is scheduled work: like ``after`` / ``every`` on a dead actor,
# setting it does nothing. ``owner``: teardown cuts it.
_DEAD_QUIET = frozenset({"active", "mode", "owner", "on_update"})


class _DeadSetter:
    """Route of every name on a destroyed actor (E14: ``time_scale`` / ``mass`` /
    ``clickable`` / ``corner_radius`` … were stored silently)."""

    __slots__ = ()

    def __set__(self, obj, value) -> None:
        _refuse_if_destroyed(obj, "set")


_DEAD_SETTER = _DeadSetter()


class _DeadRoute(dict):
    """A class's route map for its destroyed instances: the quiet names keep
    their setter, every other name refuses."""

    def get(self, name, default=None):
        hit = dict.get(self, name)
        return _DEAD_SETTER if hit is None else hit


def _mark_routes_dead(obj) -> None:
    """Called where teardown marks ``_destroyed``: give the instance a route map
    that refuses every write but the quiet ones (one check, at destroy time).
    The map is made with the class (``_cache_class_tables``; AC1)."""
    try:
        object.__setattr__(obj, "_setattr_route", type(obj)._scena_dead_route)
    except Exception:
        pass


class _RouteRefusal:
    """A route that refuses the write with a hint (graphics review R8). It sits in
    the per-class route table, so names that are writable pay nothing for it."""

    __slots__ = ("message", "kind", "link")

    def __init__(self, message: str, kind: str = "absent", link: Optional[str] = None):
        self.message = message
        # "read_only" (a property without a setter), "method", or "absent"
        # (a size / point / relation / shape word the kind lacks). The @=
        # refusal of a reserved name reads it (``_ink_link_forbidden_message``).
        self.kind = kind
        # The words @= answers with, when built with the write's (a closed
        # non-Graphic kind's own hint), so both stay the same by construction.
        self.link = link

    def __set__(self, obj, value) -> None:
        raise AttributeError(self.message.format(cls=type(obj).__name__))


# Words an author expects to resize any Graphic. On a kind without the word,
# ``circle.width = 20`` became a plain attribute nothing reads (E13).
_SIZE_WORDS = ("width", "height", "radius", "side", "length", "size",
               "corner_radius", "major_axis")
# Points and relations of some kind that another kind lacks: ``circle.top_left
# = (0, 0)`` was a dead attribute, read as a placement (E13). Generic words an
# author may use for a field of their own (x, u, text, begin, end, cursor …)
# are not reserved.
_POINT_WORDS = ("top_left", "top_right", "bottom_left", "bottom_right",
                "top_center", "bottom_center", "left_center", "right_center",
                "left_square_center", "right_square_center", "p1", "p2", "fp1", "fp2",
                "vertex", "centroid", "perimeter_point", "vec")
_RELATION_WORDS = ("dist", "at_angle", "signed_area", "perimeter_length")
# Shape inputs of one kind: ``circle.base_ratio = 0.6`` would be a dead attribute.
_SHAPE_WORDS = {"base_ratio": "Triangle", "scoop": "Concave"}


# Hints that still apply where the kind lacks the name ("Graphics only",
# "Sprite-only"); the others say how to set it, which an absent name cannot.
_ABSENT_HINTED = frozenset({"angle", "scale", "hue", "gray", "collider"})


def _absent_reserved_text(name: str, verb: str = "", size: str = "",
                          hint: Optional[str] = None) -> str:
    """``{cls} has no field 'text' (a Text field).`` — the answer to ``=`` and
    ``@=`` on a reserved name the kind lacks (``verb``: ``", so @= has nothing
    to link"``). ``hint``: the kind's own (``"Its caption is `.label`."``;
    ``""`` for none) in place of the Graphic one. ``{cls}`` is filled in by
    the caller."""
    family = _RESERVED_FAMILY.get(name)
    msg = f"{{cls}} has no field {name!r}" + (f" (a {family} field)" if family else "")
    if family:
        size = ""
    if hint is None:
        hint = _INK_LINK_FORBIDDEN_HINTS.get(name) if name in _ABSENT_HINTED else None
    return (msg + verb + "." + size + (f" {hint}" if hint else "")
            + " A field of your own needs another name.")


def _install_setattr_route(cls: type) -> None:
    """Cache known public setters so pose writes skip a per-assign MRO walk.

    The first definition of a public name in the MRO decides its route:

    * a settable descriptor routes to its setter;
    * a property without a setter refuses with a hint (E12 / SA17: Python's
      own "property … has no setter");
    * a method refuses (E8: ``c.tag = "boss"`` replaced the method);
    * on a Graphic, a size word the kind lacks refuses (E13), and so does any
      other reserved name it does not define (``rect.text``, RN1), with the
      words ``@=`` answers (``_absent_reserved_text``);
    * on a closed non-Graphic kind (``_scena_reserved_strict``: UI widgets,
      SpatialFx), any reserved name it neither defines nor lists in
      ``_reserved_fields`` refuses the same way, with the kind's own hint from
      ``_absent_hints`` (``button.text``: "Its caption is `.label`.", RN2).
    """
    route: Dict[str, Any] = {}
    seen = set()
    methods = []
    for base in cls.__mro__:
        for name, desc in base.__dict__.items():
            if not name or name[0] == "_":
                continue
            seen.add(name)
            if name in route:
                continue
            if hasattr(desc, "__set__"):
                if isinstance(desc, property) and desc.fset is None:
                    route[name] = _RouteRefusal(
                        f"{{cls}}.{name} is read-only: it is computed for you, so it "
                        f"cannot be set. A field of your own needs another name.",
                        "read_only")
                else:
                    route[name] = desc
            elif (name not in _CALLABLE_RESERVED and name != "setup"
                  and (inspect.isfunction(desc) or isinstance(desc, (staticmethod, classmethod)))):
                methods.append(name)
    # A setter anywhere in the MRO wins over a method of the same name
    # (``Track.line()`` builds a track; ``track.line = color`` is the paint).
    for name in methods:
        if name not in route:
            route[name] = _RouteRefusal(
                f"{{cls}}.{name} is a method: call it ({name}(...)). Writing it "
                f"would replace the method. A field of your own needs another name.",
                "method")
    if getattr(cls, "_scena_is_graphic", False):
        own = [w for w in _SIZE_WORDS if w in seen and w != "corner_radius"]
        sized_by = (" Size it with " + " / ".join(own) + ".") if own else ""
        for word in _SIZE_WORDS:
            if word not in seen:    # the words ``@=`` answers with
                route[word] = _RouteRefusal(_absent_reserved_text(word, size=sized_by))
        for word in _POINT_WORDS:
            if word not in seen:
                route[word] = _RouteRefusal(
                    f"{{cls}} has no {word}. To place it, write move_to(x, y) (or "
                    f"move_to(x, y, about=point) to put one of its points there). "
                    f"A field of your own needs another name.")
        for word in _RELATION_WORDS:
            if word not in seen:
                route[word] = _RouteRefusal(
                    f"{{cls}} has no {word} (a Line / Polygon field). A field of "
                    f"your own needs another name.")
        for word, kind in _SHAPE_WORDS.items():
            if word not in seen:
                route[word] = _RouteRefusal(
                    f"{{cls}} has no {word} (a {kind} field). A field of your own "
                    f"needs another name.")
        # Any other reserved name the kind does not define: ``rect.text = "hi"``,
        # ``circle.frame = 3`` stored a plain attribute nothing reads, while
        # ``rect["text"] @=`` already said "has no field" (RN1).
        for name in _INK_RESERVED:
            if name not in seen and name not in route and name not in _LOOK_FAMILY:
                route[name] = _RouteRefusal(_absent_reserved_text(name), "absent")
    elif getattr(cls, "_scena_reserved_strict", False):
        # Widgets and SpatialFx keep their reserved fields in ``__init__`` as
        # plain attributes (``button.width``, ``fire.soft_edge``), so the kind
        # lists them; the MRO alone cannot see them (RN2).
        held = set()
        hints: Dict[str, str] = {}
        for base in reversed(cls.__mro__):
            held.update(base.__dict__.get("_reserved_fields", ()))
            hints.update(base.__dict__.get("_absent_hints", {}))
        for name in _INK_RESERVED:
            if (name not in seen and name not in held and name not in route
                    and name not in _LOOK_FAMILY and name != "group"):
                hint = hints.get(name, "")
                route[name] = _RouteRefusal(
                    _absent_reserved_text(name, hint=hint), "absent",
                    _absent_reserved_text(name, ", so @= has nothing to link", hint=hint))
    for name in _LOOK_FAMILY:
        route.setdefault(name, _LOOK_MISSING)
    for name in _INK_RESERVED:
        route.setdefault(name, _SET_OBJECT)
    # ``__slots__`` members (Shape.group) are descriptors too; group needs the registry sync.
    route["group"] = _SET_OBJECT
    cls._setattr_route = route  # type: ignore[attr-defined]

def _notify_property_anchor(obj, name: str) -> None:
    """Invalidate dependents of a source-only ``angle`` / ``scale`` PropertyAnchor.

    Formulas that *read* ``shape.angle`` create a ``_PropertyAnchor`` via
    source extraction. Author ``rotate_to`` / ``scale_to`` write ``_rotation`` /
    ``_scale`` directly, so the graph only learns about the change if we fan
    out here. Uses ``mark_dirty`` rather than ``anchor.update()`` because pose
    writes often run under ``@batch_update_self()``, which sets
    ``_in_batch_update`` on every part — including the PropertyAnchor —
    causing ``update()`` to no-op. No-op when the field was never used as a
    link source (unlinked hot path: ``_field_anchors`` is missing or has no
    entry).
    """
    anchors = obj.__dict__.get("_field_anchors")
    if not anchors:
        return
    _mark_anchor_dirty(anchors, name)


def _mark_anchor_dirty(anchors, name: str) -> None:
    anchor = anchors.get(name)
    if anchor is None:
        return
    ss = getattr(anchor, "_scena_system", None)
    if ss is None:
        return
    ss.update_manager.mark_dirty(anchor)


def _refuse_linked_pose(obj, anchors, name: str, operation: str, force: bool = False) -> None:
    """A linked pose refuses a verb's write instead of dropping it (SA1, SA2 =
    E6 = PB2). Two links drive the pose:

    * a whole-object link (``obj @= other``): a copy carries the pose (C7), so
      the link drives it; the link's own pull passes (``_resolving``);
    * a property-backed pose field (``["angle"]`` / ``["scale"]`` on a Sprite,
      Point, Polygon, Text); the anchor's own ``_takein`` passes (``_writing``).
      Slot-backed fields are gated by ``_ensure_writable`` in their verbs:
      their link echoes into ``_rotation`` through here.

    ``force`` unlinks with a warning (the verbs' up-front gates pass it)."""
    d = obj.__dict__
    if (d.get("_link") is not None and not d.get("_resolving")
            and type(obj)._whole_link_carries_pose):
        from .shapes import _ensure_writable
        _ensure_writable(obj, operation, force=force)
    if not anchors or name is None:
        return
    from .state import _PropertyAnchor
    anchor = anchors.get(name)
    if (anchor is None or anchor._link is None or not isinstance(anchor, _PropertyAnchor)
            or anchor.__dict__.get("_writing")):
        return
    from .shapes import _ensure_writable
    _ensure_writable(obj[name], operation, force=force)


def _part_is_linked(part) -> bool:
    """A part a verb would write has an ``@=`` formula on it or under it
    (property anchors aside — their own writers gate them)."""
    from .state import FieldRef, _PropertyAnchor
    if isinstance(part, FieldRef):
        return part.is_linked
    return any(node._link is not None and not isinstance(node, _PropertyAnchor)
               for node in part._iter_subtree())


# Graphics with a linked appearance field or flag: the draw-head refresh
# (``refresh_linked_channels``) pulls them once per frame, before culling and
# look grouping read them. Pruned when a host has none left.
_LINKED_CHANNEL_HOSTS = weakref.WeakSet()


def refresh_linked_channels() -> None:
    """Bring every linked appearance field / flag up to date (head of the draw;
    ``visible`` also at the start of hover). A pull where it is used, not a new
    phase (Laws F2). Parked and destroyed hosts are skipped (L3, L4)."""
    if not _LINKED_CHANNEL_HOSTS:
        return
    for host in list(_LINKED_CHANNEL_HOSTS):
        if getattr(host, "_destroyed", False):
            _LINKED_CHANNEL_HOSTS.discard(host)
            continue
        anchors = host.__dict__.get("_field_anchors")
        if not anchors:
            _LINKED_CHANNEL_HOSTS.discard(host)
            continue
        skip = getattr(host, "_active", True) is False or host._in_visual_apply
        linked = False
        for name in type(host)._scena_target_only:
            a = anchors.get(name)
            if a is not None and a._link is not None:
                linked = True
                if a._dirty and not skip:   # clean: nothing to pull
                    a._ensure_fresh()
        if not linked:
            _LINKED_CHANNEL_HOSTS.discard(host)


def refresh_linked_visible() -> None:
    """``visible`` only: hover and clicks read it right after the collision
    handlers, before the draw-head refresh."""
    if not _LINKED_CHANNEL_HOSTS:
        return
    from .state import _pull_channel_links
    for host in list(_LINKED_CHANNEL_HOSTS):
        if getattr(host, "_destroyed", False) or getattr(host, "_active", True) is False:
            continue
        _pull_channel_links(host, ("visible",))


def _refuse_linked_channel(obj, names, operation: str) -> None:
    """An author write to a linked appearance field or flag raises before it
    writes anything (a formula is the only exclusive driver — Shapes Design,
    Persistent drivers). The hot setters check the ``_alinks`` slot first, so
    an unlinked object pays one slot read.

    Passes: the link's own write (the anchor's ``_writing``) and a look
    applying itself (``_in_visual_apply``), which writes the live channels a
    linked ``color`` stays the identity of. Park writes ``visible`` through
    ``_engine_flag_write``."""
    anchors = obj.__dict__.get("_field_anchors")
    if not anchors:
        return
    if getattr(obj, "_in_visual_apply", False) or obj.__dict__.get("_engine_flag_write"):
        return
    for name in names:
        anchor = anchors.get(name)
        if anchor is None or anchor._link is None:
            continue
        if any(a.__dict__.get("_writing") for a in anchors.values()):
            return          # a link of this object is writing (color → fill / line)
        from .state import driver_conflict_message
        raise LinkedAttributeError(driver_conflict_message(
            new=operation, subject=entity_label(obj), part=name,
            existing="has an @= formula",
            undo=f"Unlink it first ({obj.name}['{name}'].unlink())",
        ))


def _gate_pose_anchor(obj, name: str, operation: str, force: bool = False) -> None:
    """Verb entry check for a property-backed pose field: refuse (or with
    ``force`` unlink) before the verb writes anything else."""
    d = obj.__dict__
    anchors = d.get("_field_anchors")
    if anchors or d.get("_link") is not None:
        _refuse_linked_pose(obj, anchors, name, operation, force)


def _pose_rotation_set(obj, value: float) -> None:
    """Write ``_rotation`` without entering ``Entity.__setattr__``.

    Tier 1.2: skip property-anchor notify when the value is unchanged (common
    when ``_update_impl`` echoes Defining rotation). Always notify when the
    value differs (author ``rotate_to``, SPINE Derivate rotation, …).
    """
    _refuse_if_destroyed(obj, "angle")
    value = float(value)
    d = obj.__dict__
    old = d.get("_rotation")
    if old is None:
        old = probe_private(obj, "_rotation", None)      # a class default until first written
    if old is not None and old == value:
        return
    anchors = d.get("_field_anchors")
    if anchors:
        _refuse_linked_pose(obj, anchors, "angle", "rotate")
    object.__setattr__(obj, "_rotation", value)
    _bump_collision_epoch(obj)
    if anchors:
        _mark_anchor_dirty(anchors, "angle")


def _pose_rotation_publish(obj, value: float) -> None:
    """An update publishes a heading it derived from the geometry (Rect).

    Not an author write: a linked ``angle`` drives that geometry, so this is
    the link's own echo. Through ``_pose_rotation_set`` the backstop refused
    it, and every read of a SPINE Rect with ``angle`` linked raised (found by
    the gate's reactive machine after batch 4)."""
    value = float(value)
    d = obj.__dict__
    old = d.get("_rotation")
    if old is None:
        old = getattr(obj, "_rotation", None)
    if old is not None and old == value:
        return
    object.__setattr__(obj, "_rotation", value)
    _bump_collision_epoch(obj)
    anchors = d.get("_field_anchors")
    if anchors:
        _mark_anchor_dirty(anchors, "angle")


def _pose_rotation_add(obj, delta: float) -> None:
    _refuse_if_destroyed(obj, "rotate_by")
    anchors = obj.__dict__.get("_field_anchors")
    if anchors:
        _refuse_linked_pose(obj, anchors, "angle", "rotate_by")
    object.__setattr__(obj, "_rotation", obj._rotation + delta)
    _bump_collision_epoch(obj)
    if anchors:
        _mark_anchor_dirty(anchors, "angle")


def _pose_scale_set(obj, value: float) -> None:
    """Write ``_scale`` without entering ``Entity.__setattr__``.

    Tier 1.2: skip property-anchor notify when the value is unchanged.
    """
    _refuse_if_destroyed(obj, "scale")
    value = float(value)
    d = obj.__dict__
    old = d.get("_scale")
    if old is None:
        old = probe_private(obj, "_scale", None)         # a class default until first written
    if old is not None and old == value:
        return
    anchors = d.get("_field_anchors")
    if anchors:
        _refuse_linked_pose(obj, anchors, "scale", "scale")
    object.__setattr__(obj, "_scale", value)
    _bump_collision_epoch(obj)
    if anchors:
        _mark_anchor_dirty(anchors, "scale")


# Author ``=`` on a pose that is placement for collision (Collision Design,
# "Motion vs placement"): ``center =``, ``center.x =`` / ``.y =`` on an actor's
# part. Placement clears the frame's pending motion, as instant ``move_to``
# does: after a ``move_by`` a respawn by ``center =`` was swept along a segment
# the body never travelled (review 2026-10-09 X-writers-4).
_PLACEMENT_WRITES = frozenset({"center", "x", "y"})


def _placement_write(obj) -> None:
    col = getattr(obj, "_collider", None) if getattr(obj, "_scena_is_entity", False) else None
    actor = obj
    if col is None:
        actor = _actor_of(obj)
        if actor is None or actor is obj:
            return
        col = getattr(actor, "_collider", None)
        if col is None:
            return
    if col._pending_motion_dx != 0.0 or col._pending_motion_dy != 0.0:
        from .collision import note_collider_placement
        note_collider_placement(actor)


from . import state as _state_module          # noqa: E402
_state_module._PLACEMENT_HOOK = _placement_write


def _bump_collision_epoch(obj) -> None:
    """Invalidate collision snapshot cache for this Graphic / Entity."""
    try:
        object.__setattr__(
            obj, "_collision_epoch", int(getattr(obj, "_collision_epoch", 0)) + 1
        )
    except Exception:
        pass
    bump_pose_rev(obj)


def _geom_path_cache_set(obj, path, key) -> None:
    """Write polygon path cache without entering ``Entity.__setattr__``.

    ``_geometry_draw`` rebuilds the path when pose/verts change; those two
    private stores would otherwise pay Python ``__setattr__`` every rebuild.
    """
    object.__setattr__(obj, "_geom_path", path)
    object.__setattr__(obj, "_geom_path_key", key)


_USE_LAYER_DEFAULT = Unset("<default layer>")
# Omit ``group=`` on ``clone()`` → copy the source's current groups. Explicit
# ``group=`` is a full replacement (including ``group=None`` → no groups).
_COPY_GROUPS = Unset("<same groups>")

# Sentinel: omit paint override → use shape PaintState paints (fill_paint=None means skip).
_STYLE_PAINT = Unset("<default style>")

_ACTOR_HOOK_NAMES = (
    "on_update",
    "on_click",
    "on_hover",
    "on_hover_exit",
    "on_drag_to",
    "on_drag_over",
    "on_drop_by",
    "on_collide",
    "on_collide_stay",
    "on_collide_exit",
    "on_destroy",
)

# Reserved names whose job is a callable (plain assignment, not an ink @= link).
# Distinct from _ACTOR_HOOK_NAMES: mode is not a discovered class-body hook.
_CALLABLE_RESERVED = _ACTOR_HOOK_NAMES + ("mode",)

_HOOK_LOOKUP_NAMES = _ACTOR_HOOK_NAMES + ("setup",)
_TAG_ATTRS = (
    "_every_spec",
    "_after_spec",
    "_collide_with_specs",
    "_leave_playfield_method",
    "_when_specs",
)


def _lookup_actor_hook(cls, name: str):
    """Callable defined on an Entity subclass (not the Entity default). Uncached walk."""
    for c in cls.__mro__:
        if c is Entity:
            break
        raw = c.__dict__.get(name)
        if callable(raw) and not isinstance(raw, (property, staticmethod, classmethod)):
            return raw
    return None


def _find_actor_hook(cls, name: str):
    """Callable defined on an Entity subclass (not the Entity default)."""
    bag = getattr(cls, "_scena_actor_hooks", None)
    if bag is not None and name in bag:
        return bag[name]
    return _lookup_actor_hook(cls, name)


def _collect_tagged_methods(cls, tag_attr: str) -> Tuple[Tuple[str, Any], ...]:
    """First MRO definition of each name that has ``tag_attr``. Stops at ``Entity``."""
    found = []
    seen = set()
    for c in cls.__mro__:
        if c is Entity:
            break
        for name, raw in c.__dict__.items():
            if name in seen:
                continue
            seen.add(name)
            if not callable(raw) or isinstance(raw, (property, staticmethod, classmethod)):
                continue
            if getattr(raw, tag_attr, None) is not None:
                found.append((name, raw))
    return tuple(found)


def _iter_tagged_methods(cls, tag_attr: str):
    """Yield ``(name, raw_fn)`` for the first MRO definition of each name that has ``tag_attr``.

    Stops at ``Entity``. A subclass override without the tag shadows the parent
    (same rule as ``_find_actor_hook``). Cached per class in ``__init_subclass__``.
    """
    cache = getattr(cls, "_scena_tagged_methods", None)
    if cache is not None:
        return iter(cache.get(tag_attr, ()))
    return iter(_collect_tagged_methods(cls, tag_attr))


def _cache_actor_lookups(cls) -> None:
    """Freeze hook + decorator discovery so construct does not walk the MRO.

    An ``async def`` hook (``setup``, ``on_update``, ``on_click`` …) raises
    here, at the class statement: the engine calls hooks, it does not drive
    them, so its body would never run.
    """
    from .validate import refuse_async
    hooks = {name: _lookup_actor_hook(cls, name) for name in _HOOK_LOOKUP_NAMES}
    for hook in hooks.values():
        if hook is not None:
            refuse_async(hook, what=f"class {cls.__name__}:")
    cls._scena_actor_hooks = hooks
    cls._scena_tagged_methods = {tag: _collect_tagged_methods(cls, tag) for tag in _TAG_ATTRS}


def _claim_deferred_every_specs(cls) -> None:
    """Cancel any act handle left on a class-body ``@every`` (safety net).

    The decorator normally tags only inside a class body. If detection missed
    and an act timer was created, drop it here so timers start at construct.
    """
    for raw in cls.__dict__.values():
        if not callable(raw) or getattr(raw, "_every_spec", None) is None:
            continue
        handle = getattr(raw, "handle", None)
        if handle is None:
            continue
        cancel = getattr(handle, "cancel", None)
        if callable(cancel):
            cancel()
        try:
            delattr(raw, "handle")
        except AttributeError:
            pass


def _claim_deferred_after_specs(cls) -> None:
    """Cancel any act handle left on a class-body ``@after`` (safety net)."""
    for raw in cls.__dict__.values():
        if not callable(raw) or getattr(raw, "_after_spec", None) is None:
            continue
        handle = getattr(raw, "handle", None)
        if handle is None:
            continue
        cancel = getattr(handle, "cancel", None)
        if callable(cancel):
            cancel()
        try:
            delattr(raw, "handle")
        except AttributeError:
            pass


def _install_method_every(item) -> None:
    """Arm entity-scoped ``@every`` from tagged methods (Proposal A)."""
    cls = type(item)
    tagged = tuple(_iter_tagged_methods(cls, "_every_spec"))
    if not tagged:
        return
    from .process import every_on
    for _name, raw in tagged:
        interval, tname = raw._every_spec
        bound = raw.__get__(item, cls)
        every_on(item, interval, bound, name=tname)


def _install_method_after(item) -> None:
    """Arm entity-scoped ``@after`` from tagged methods."""
    cls = type(item)
    tagged = tuple(_iter_tagged_methods(cls, "_after_spec"))
    if not tagged:
        return
    from .process import after_on
    for _name, raw in tagged:
        delay, tname = raw._after_spec
        bound = raw.__get__(item, cls)
        after_on(item, delay, bound, name=tname)


_ANYTHING_ON_COLLIDE_PHASES = (
    ("on_collide", "enter"),
    ("on_collide_stay", "stay"),
    ("on_collide_exit", "exit"),
)


def _target_includes_anything(target) -> bool:
    from .collision import ANYTHING
    if target is ANYTHING:
        return True
    if isinstance(target, (list, tuple)):
        return any(t is ANYTHING for t in target)
    return False


def _warn_anything_and_on_collide(item, specs) -> None:
    """Once per class: ``on_collide*`` + ``@collide_with(ANYTHING)`` double-dispatch."""
    cls = type(item)
    if getattr(cls, "_scena_warned_anything_on_collide", False):
        return
    anything_names = [
        name for name, target, _phase in specs
        if _target_includes_anything(target)
    ]
    if not anything_names:
        return
    hook_names = [
        hook for hook, _phase in _ANYTHING_ON_COLLIDE_PHASES
        if _find_actor_hook(cls, hook) is not None
    ]
    if not hook_names:
        return
    cls._scena_warned_anything_on_collide = True
    warnings.warn(
        f"{cls.__name__} defines both {hook_names[0]} and "
        f"@collide_with(ANYTHING) on {anything_names[0]} — both fire for the "
        f"same contact (shape callbacks run before pair handlers). Keep one "
        f"spelling.",
        stacklevel=3,
    )


def _install_method_leave_playfield(item) -> None:
    """Bind class ``@leave_playfield`` handlers for this instance."""
    cls = type(item)
    tagged = tuple(_iter_tagged_methods(cls, "_leave_playfield_method"))
    if not tagged:
        return
    from .bounds import get_bounds_system
    sys = get_bounds_system()
    for _name, raw in tagged:
        # The plain function, not raw.__get__(item): a bound method stored as
        # the WeakKeyDictionary value would keep ``item`` alive forever.
        sys.add_instance_handler(item, raw)


def _install_method_collide_with(item) -> None:
    """Enroll ``@collide_with*`` pair handlers for this instance (Proposal C)."""
    cls = type(item)
    tagged = tuple(_iter_tagged_methods(cls, "_collide_with_specs"))
    if not tagged:
        return
    from .collision import (
        get_collision_system,
        _normalize_side,
        _pair_method_adapter,
    )
    specs = []
    sys = get_collision_system()
    for name, raw in tagged:
        bound = raw.__get__(item, cls)
        adapter = _pair_method_adapter(bound)
        for target, phase in raw._collide_with_specs:
            specs.append((name, target, phase))
            for b in _normalize_side(target):
                sys.add_pair_handler(item, b, adapter, phase=phase)
    if specs:
        _warn_anything_and_on_collide(item, specs)


def _bind_when_condition(condition_fn, item):
    """Zero-arg condition that still closes over ``item``.

    Polled every frame; if ``item`` has been destroyed the exception
    disables the registration (liveness guard).
    """
    expr = lambda: condition_fn(item)
    return expr


def _install_method_when(item) -> None:
    """Register per-instance ``@when`` / ``@on_change`` from tagged methods."""
    cls = type(item)
    tagged = tuple(_iter_tagged_methods(cls, "_when_specs"))
    if not tagged:
        return
    from .events import get_global_event_system
    sys = get_global_event_system()
    for _name, raw in tagged:
        bound = raw.__get__(item, cls)
        for condition_fn, kind in raw._when_specs:
            expr = _bind_when_condition(condition_fn, item)
            sys.register_event(expr, bound, kind=kind, owner=item)


def _destroyed_access_message(obj, base: str) -> str:
    """Existing destroyed-access text, plus a History breadcrumb when one was recorded."""
    try:
        note = object.__getattribute__(obj, "_destroyed_by")
    except AttributeError:
        note = None
    if note:
        return f"{base} — {note}"
    return base


# ``scena/entity.py`` lives in the package directory. Author frames sit outside it.
_SCENA_PKG = os.path.dirname(os.path.abspath(__file__))


class _Site(NamedTuple):
    filename: str
    lineno: int
    name: str


def _frame_outside_scena() -> Optional[_Site]:
    """Nearest stack frame that is not Scena itself (the author's call).

    A ``sys._getframe`` walk with the cached file test of ``_author_site``:
    ``traceback.extract_stack`` built every frame summary and read source
    lines, a third of each ``destroy()`` (graphics review E16)."""
    try:
        f = sys._getframe(1)
    except (AttributeError, ValueError):
        return None
    while f is not None:
        code = f.f_code
        if not _is_scena_file(code.co_filename):
            return _Site(code.co_filename, f.f_lineno, code.co_name)
        f = f.f_back
    return None


# co_filename -> True when that file is Scena itself (or a non-author pseudo
# file like ``<frozen ...>``). Cached: construction pays a dict hit per frame.
_SCENA_FILE_CACHE: Dict[str, bool] = {}


def _is_scena_file(fn: str) -> bool:
    inside = _SCENA_FILE_CACHE.get(fn)
    if inside is None:
        if not fn or fn.startswith("<"):
            inside = fn not in ("<string>", "<stdin>")
        else:
            absfn = os.path.abspath(fn)
            inside = absfn == _SCENA_PKG or absfn.startswith(_SCENA_PKG + os.sep)
        _SCENA_FILE_CACHE[fn] = inside
    return inside


def _author_site() -> Optional[Tuple[str, int]]:
    """``(filename, lineno)`` of the nearest author frame, or ``None``.

    Same rule as ``_frame_outside_scena`` (first frame outside the package;
    ``<string>`` / ``<stdin>`` count as author code), but a bare
    ``sys._getframe`` walk: no ``extract_stack``, no source lines, no frame kept
    alive. Cheap enough for every top-level construction (~0.5 µs).
    """
    import sys
    try:
        f = sys._getframe(1)
    except (AttributeError, ValueError):
        return None
    while f is not None:
        fn = f.f_code.co_filename
        if not _is_scena_file(fn):
            return (fn, f.f_lineno)
        f = f.f_back
    return None


# ``clone()`` hands its source to the copy's construction (the first
# top-level ``_construct`` pops it), so a message raised while the copy
# joins its groups already reads "a clone of …".
_PENDING_CLONE_SOURCES: list = []


def _clone_note(source, site: Optional[Tuple[str, int]]) -> str:
    """``a clone of the one from line 121`` (same file) / ``… from app.py:121``."""
    src = source.__dict__.get("_site")
    if src is None:
        return "a clone"
    if site is not None and src[0] == site[0]:
        return f"a clone of the one from line {src[1]}"
    return f"a clone of the one from {os.path.basename(src[0])}:{src[1]}"


def _actor_of(node):
    """The top-level Entity that owns ``node`` (a part, FieldRef, or actor)."""
    from .state import FieldRef
    if isinstance(node, FieldRef):
        node = node.owner
    top = None
    cur = node
    while cur is not None:
        if getattr(type(cur), "_scena_is_entity", False):
            top = cur
        nxt = getattr(cur, "_owner", None)
        if nxt is None:
            # An engine node held by a shape but not its part: the fit node
            # of a ``box=<formula>`` shape (box.py ``_BoxFit``).
            ref = getattr(cur, "__dict__", {}).get("_host_ref")
            nxt = ref() if ref is not None else None
        cur = nxt
    return top


def part_path(node, actor=None) -> str:
    """``center`` / ``center.x`` / ``angle`` — ``node``'s path under its actor."""
    from .state import FieldRef
    if isinstance(node, FieldRef):
        return str(node.name)
    if actor is None:
        actor = _actor_of(node)
    names = []
    cur = node
    while cur is not None and cur is not actor:
        names.append(str(getattr(cur, "_attr_name", cur)))
        cur = getattr(cur, "_owner", None)
    # The actor itself (a draggable Point / Anchor linked whole): its position.
    return ".".join(reversed(names)) if names else "position"


def made_at(obj) -> str:
    """``made at app.py:40`` for ``repr`` / debug text; ``""`` when unknown.

    Actors have no author ids: the construction line is how a beginner finds
    the one a message or ``print`` is talking about.
    """
    actor = _actor_of(obj)
    if actor is None:           # ``or`` would skip a destroyed (falsy) actor (R9; E18)
        actor = obj
    site = getattr(actor, "__dict__", {}).get("_site")
    if site is None:
        return ""
    return f"made at {os.path.basename(site[0])}:{site[1]}"


def is_part(obj) -> bool:
    """An Entity owned by another (a shape's ``center`` / ``p1`` / vertex Point)."""
    if not getattr(type(obj), "_scena_is_entity", False):
        return False  # before any attribute read: GroupOperator forwards them
    try:
        d = object.__getattribute__(obj, "__dict__")
    except AttributeError:
        return False
    return d.get("_owner") is not None


def refuse_part_as_actor(obj, verb: str, kind: str, name: Any = None) -> None:
    """A part is geometry of its owner, not an actor: refuse actor-only verbs.

    ``kind``: ``"tags"`` (groups), ``"body"`` (collision), ``"life"``
    (``destroy`` / ``active``). No-op for anything that is not a part. See
    Actors Design — "A part is not an actor".
    """
    if not is_part(obj):
        return
    actor = _actor_of(obj)
    cls = type(actor).__name__ if actor is not None else "owner"
    var = cls.lower()
    path = part_path(obj)
    head = f"{path} is a part of {entity_label(obj)}"
    if kind == "tags":
        shown = f"{name!r}" if isinstance(name, str) else "'name'"
        text = (
            f"{head} and has no tags of its own ({verb} refused). Tag the {cls} "
            f"itself: {var}.tag({shown}). A part leaves with its owner."
        )
    elif kind == "body":
        text = (
            f"{head} and is not a collision body ({verb} refused). Collide with "
            f"the {cls} itself: @collide({var}, wall) — info.point is where they "
            f"touch. For a point test: wall.contains_point({var}.{path}). For a "
            f"body of its own, make one that follows it: "
            f"tip = Point(lambda: {var}.{path})."
        )
    else:
        text = (
            f"{head} ({verb} refused): a part lives, parks and dies with its "
            f"owner. Use {var}.destroy() or {var}.active = False."
        )
    raise TypeError(text)


def entity_label(obj) -> str:
    """How an error names an actor a beginner can find in their own file.

    The construction line (``the Sprite made at app.py:151``), plus the clone
    source when there is one. Parts and FieldRefs are named by their top-level
    actor. There are no author ids: the line is what the author can find.
    """
    actor = _actor_of(obj)
    if actor is None:
        return str(getattr(obj, "name", obj))
    cls = type(actor).__name__
    if getattr(actor, "_scena_is_act", False):
        return f"act {cls}"        # built by the framework: no author line (PA5)
    d = actor.__dict__
    site = d.get("_site")
    if site is None:
        return f"the {cls}"
    text = f"the {cls} made at {os.path.basename(site[0])}:{site[1]}"
    note = d.get("_clone_note")
    if note:
        text += f" ({note})"
    return text


def _record_destroy_site(obj) -> None:
    """Remember where ``destroy()`` was called, unless History already wrote a note.

    Destroy is not a per-frame path. The note is appended to later
    ``DestroyedError`` text (``destroyed at app.py:89 in atingiu``).
    """
    try:
        note = object.__getattribute__(obj, "_destroyed_by")
    except AttributeError:
        note = None
    if note:
        return
    frame = _frame_outside_scena()
    if frame is None:
        text = "destroyed"
    else:
        text = (
            f"destroyed at {os.path.basename(frame.filename)}:{frame.lineno} in {frame.name}"
        )
    object.__setattr__(obj, "_destroyed_by", text)


def _parked(obj) -> bool:
    """Alive but ``active = False`` — flag writes go to the park stash."""
    return getattr(obj, "_active", True) is False and not getattr(obj, "_destroyed", False)


def _stash_flag(obj, flag: str, value: bool) -> None:
    """Record ``visible`` / ``collidable`` for resume (Actors Design — active)."""
    object.__setattr__(obj, f"_active_saved_{flag}", bool(value))


def _tag_names(names, verb: str):
    """Every name checked before the first is claimed: ``tag("a", 5)`` claimed
    "a" and then raised (graphics review E10 / HP11)."""
    for n in names:
        if not isinstance(n, str) or not n:
            raise TypeError(f"{verb}() names must be non-empty strings")
    return names


_COLLIDE_HOOKS = ("on_collide", "on_collide_stay", "on_collide_exit")

# A drag gesture as a class method: ``self`` is already one side of the drag,
# so the method takes the other side and ``pos`` — ``on_drag_to(self, alvo,
# pos)``, ``on_drag_over(self, alvo, pos)``, ``on_drop_by(self, peca, pos)`` —
# as ``on_collide`` takes ``(other, info)``. Installed through the property
# setter, the method turns ``draggable`` / ``droppable`` on, like ``on_click``
# turns ``clickable`` on (CH1, 2026-10-14: a class method did neither, and the
# engine passed it ``(self, alvo)``).
_DRAG_HOOKS = ("on_drag_to", "on_drag_over", "on_drop_by")


def _drag_method_adapter(bound, name: str):
    """Engine payload ``(from_shape, to_shape, pos)`` → the method's ``(other, pos)``."""
    from .validate import call_truncated, check_handler_arity
    dropped_on = name == "on_drop_by"
    check_handler_arity(bound, ("from_shape" if dropped_on else "to_shape", "pos"),
                        what=f"{type(bound.__self__).__name__}.{name}")
    if dropped_on:
        def handler(from_shape, to_shape, pos):
            call_truncated(bound, from_shape, pos)
    else:
        def handler(from_shape, to_shape, pos):
            call_truncated(bound, to_shape, pos)
    handler.__name__ = getattr(bound, "__name__", name)
    return handler


def _keep_collide_callbacks(item, col) -> None:
    """Copy ``col``'s callbacks onto the actor before ``col`` is dropped (E1).

    The Collider may hold callbacks the actor's store lacks (an author who set
    them on a bound ``Collider([shape])``), so the Collider's view wins."""
    cbs = {n: getattr(col, n) for n in _COLLIDE_HOOKS if getattr(col, n, None) is not None}
    object.__setattr__(item, "_collide_cbs", cbs or None)


def _time_scale_value(item, value) -> float:
    """One check for every ``time_scale`` (Entity, Sprite): alive, a real
    number (not a bool), finite, >= 0. Sprite's own setter skipped it: -1 and
    NaN froze silently and ``inf`` crashed every draw (PB6 / E12)."""
    _refuse_if_destroyed(item, "time_scale")
    if isinstance(value, bool):
        raise TypeError("time_scale expected a number, got bool")
    from .validate import number
    v = number(value, "time_scale")
    if v < 0.0:
        raise ValueError(f"time_scale must be >= 0, got {v}")
    return v


def _wants_collision(item) -> bool:
    """Collidable now, or stashed to be collidable on resume."""
    if getattr(item, "_collidable", False) or getattr(item, "_collider", None) is not None:
        return True
    return _parked(item) and bool(getattr(item, "_active_saved_collidable", False))


# Classes outside Entity (Box, Vec2, builtins) that the framework owns:
# immortal, so a dict keyed by them pins nothing (AC1).
_SCENA_KIND_CACHE: dict = {}


def scena_kind(obj) -> str:
    """Name of the nearest Scena class in ``obj``'s MRO: what kind of thing it is.

    An author subclass reads as its Scena base (``class Pad(Rect)`` → ``"Rect"``),
    so engine dispatch by kind never refuses a subclass. Scena's own subclasses
    keep their own name (``Square``, ``Svg``); for the Sprite family use
    :func:`is_sprite_family`. Never dispatch on ``type(obj).__name__`` — that
    refused every author subclass (Testing Design, bug catalogue).
    """
    cls = obj if isinstance(obj, type) else type(obj)
    kind = getattr(cls, "_scena_kind_name", None)   # every Entity class has its own (AC1)
    if kind is not None:
        return kind
    kind = _SCENA_KIND_CACHE.get(cls)
    if kind is None:
        kind = _kind_of_class(cls)
        if is_framework_module(getattr(cls, "__module__", "") or "") or cls.__module__ == "builtins":
            _SCENA_KIND_CACHE[cls] = kind     # immortal classes only: no author class pinned
    return kind


def _kind_of_class(cls: type) -> str:
    for k in cls.__mro__:
        mod = getattr(k, "__module__", "") or ""
        if is_framework_module(mod):
            return k.__name__
    return cls.__name__


def is_sprite_family(obj) -> bool:
    """True for every bitmap-bodied Graphic: Sprite, Svg, SpriteButton, author subclasses."""
    return bool(getattr(type(obj), "_is_sprite_body", False))


def _drawn(obj) -> bool:
    """Engine check: is ``obj`` on screen NOW (not an author's stashed value)."""
    v = getattr(obj, "_visible", None)
    return bool(obj.visible) if v is None else bool(v)


def _refuse_if_destroyed(obj, action: str) -> None:
    """Raise when ``action`` would change a destroyed actor. Reads stay legal.

    Living actors pay one attribute lookup. The message names the destroy site
    (when teardown recorded one) and the call, and suggests ``if nave:``.
    """
    try:
        destroyed = object.__getattribute__(obj, "_destroyed")
    except AttributeError:
        return
    if not destroyed:
        return
    import linecache
    frame = _frame_outside_scena()
    line = ""
    site = ""
    if frame is not None:
        line = linecache.getline(frame.filename, frame.lineno)
        site = (
            f"called from {os.path.basename(frame.filename)}:{frame.lineno} in {frame.name}"
        )
    shown = f"{action}()" if line and re.search(rf"\.{re.escape(action)}\s*\(", line) else action
    guard = "if actor:"
    if line:
        found = re.search(
            rf"([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*{re.escape(action)}\b",
            line,
        )
        if found:
            guard = f"if {found.group(1)}:"
    if getattr(type(obj), "_scena_is_act", False):
        # The only way an act's own code meets its act destroyed: it ran on
        # after change_act ended the act (immediate, Act Design), e.g. later
        # lines of its setup (CD5). "Guard the call" was the wrong fix.
        name = type(obj).__name__
        base = f"{name}.{shown} cannot change act {name}"
        if site:
            base = f"{base} ({site})"
        base = (f"{base}: act {name} ended when the game changed act, and code "
                f"after change_act() runs on the act that is gone. Write "
                f"change_act(...) last, or return right after it.")
        raise DestroyedError(_destroyed_access_message(obj, base))
    base = f"{type(obj).__name__}.{shown} cannot change a destroyed actor"
    if site:
        base = f"{base} ({site})"
    base = f"{base}. Guard the call: {guard}"
    raise DestroyedError(_destroyed_access_message(obj, base))


def _ink_callable_message(owner, field: str, value) -> str:
    """Why ``ship.field = value`` (a callable) is refused.

    Ink holds any value except a function. A group view is callable, so
    storing one lands here; it gets its own sentence (Act Design, ink rule).
    """
    from .registry import GroupOperator
    if isinstance(value, GroupOperator):
        gid = value._named() or "inimigo"
        return (
            f"A group is looked up, not stored. Write group[{gid!r}] where you "
            f"need it (not {type(owner).__name__}.{field} = group[{gid!r}])."
        )
    return callable_assign_message(owner, field)


def _fire_on_destroy(item) -> None:
    """Run ``on_destroy`` once, while ``item`` is still fully alive.

    Idempotent: the hook is cleared before the call so a re-entrant
    ``destroy()`` (or ``registry.destroy`` after ``Entity.destroy``) cannot
    fire it twice. An exception propagates; callers finish teardown in a
    ``finally`` first.
    """
    hook = getattr(item, "_on_destroy", None)
    if hook is None:
        return
    object.__setattr__(item, "_on_destroy", None)
    from .process import run_on_destroy
    run_on_destroy(hook, item)


def _install_subclass_hooks(item) -> None:
    cls = type(item)
    for name in _ACTOR_HOOK_NAMES:
        hook = _find_actor_hook(cls, name)
        if hook is None:
            continue
        bound = hook.__get__(item, cls)
        if name in _COLLIDE_HOOKS:
            # The collider calls ``fn(me, other, info)``; the method's ``self``
            # is already ``me``: give it ``(other, info)``, as ``@collide_with``
            # does (AC6: it received ``other = self``).
            from .collision import _pair_method_adapter
            bound = _pair_method_adapter(bound)
        elif name in _DRAG_HOOKS:
            bound = _drag_method_adapter(bound, name)
        assigned = False
        for c in cls.__mro__:
            desc = c.__dict__.get(name)
            if isinstance(desc, property) and desc.fset is not None:
                desc.fset(item, bound)
                assigned = True
                break
        if not assigned:
            object.__setattr__(item, name, bound)


def _finish_actor_construct(item) -> None:
    """Discover subclass hooks, method decorators, and call ``setup()`` once, after the most-derived ``__init__``.

    Order: fixed hooks → ``@every`` / ``@after`` / ``@collide_with*`` → ``setup()`` (ink) →
    ``@when`` / ``@on_change`` → group collision enroll.

    ``_construct`` sets ``_actor_constructed``; an author ``__init__`` that never
    called Scena's own left it unset, and the object was never built (CB1).
    """
    done = getattr(item, "_actor_constructed", None)
    if done:
        return
    if done is None:
        raise TypeError(_never_built_message(item))
    object.__setattr__(item, "_actor_constructed", True)
    _install_subclass_hooks(item)
    _install_method_every(item)
    _install_method_after(item)
    _install_method_collide_with(item)
    _install_method_leave_playfield(item)
    setup = _find_actor_hook(type(item), "setup")
    if setup is not None:
        setup(item)
    # After setup so ink the condition reads (``self.hp``) already exists.
    _install_method_when(item)
    from .collision import enroll_item_groups
    from .registry import ParallaxLayerError, UiLayerError
    try:
        enroll_item_groups(item)
    except (ParallaxLayerError, UiLayerError):
        pass        # a decoration / HUD layer member of a pair group: no body (E18)


def _wrap_construct_rollback(cls) -> None:
    """A constructor that raises leaves no roster, group, or draw entry behind.

    Wraps the class's own ``__init__`` (inside the actor wrapper, so
    ``_wrap_actor_init``'s ``type(self).__init__ is wrapped`` test still sees
    the outermost wrapper).
    """
    orig = cls.__dict__.get("__init__")
    if orig is None or orig is object.__init__ or getattr(orig, "_scena_rollback", False):
        return

    @wraps(orig)
    def wrapped(self, *args, **kw):
        try:
            orig(self, *args, **kw)
        except BaseException:
            from .place import _drop_failed_construct
            _drop_failed_construct(self)
            raise

    wrapped._scena_rollback = True
    cls.__init__ = wrapped


def _wrap_actor_init(cls) -> None:
    orig = cls.__dict__.get("__init__")
    if orig is None or getattr(orig, "_scena_actor_init", False):
        return
    if orig is object.__init__:
        return

    @wraps(orig)
    def wrapped(self, *args, **kwargs):
        try:
            orig(self, *args, **kwargs)
        except TypeError as exc:
            if type(self).__init__ is wrapped:
                _explain_author_init_keywords(orig, type(self), kwargs, exc)
                # Python's "Polygon.__init__() got an unexpected keyword"
                # → Did you mean / Valid (validate.install_friendly_constructor).
                from .validate import explain_raw_call_error
                explain_raw_call_error(
                    inspect.unwrap(orig), type(self).__name__, args, kwargs, exc,
                    example=getattr(type(self), "_call_example", None),
                    hints=getattr(type(self), "_call_hints", None),
                )
            raise
        if type(self).__init__ is wrapped:
            try:
                from .process import call_without_owner
                call_without_owner(_finish_actor_construct, self)
            except BaseException:
                # The finish step (setup, method timers, watches, enroll) is
                # part of construction: a raise rolls back like one in __init__ (E4).
                from .place import _drop_failed_construct
                _drop_failed_construct(self)
                raise
            # Built: the HUD cursor a rollback would restore is not needed.
            self.__dict__.pop("_hud_cursor_before", None)

    wrapped._scena_actor_init = True
    cls.__init__ = wrapped


def _adopt_mixin_init(cls) -> None:
    """Give ``cls`` its own ``__init__`` when it inherits one from a mixin (E5).

    ``class Enemy(Damageable, Circle)``: ``Enemy.__init__`` resolves to the
    mixin's plain ``__init__``, so no Scena wrapper would see the most-derived
    call: ``setup()`` / ``on_update`` / ``@every`` never ran and a raise never
    rolled back. A thin forwarder makes it this class's ``__init__``, which
    the rollback and actor-init wraps then take as usual.
    """
    if "__init__" in cls.__dict__:
        return
    inherited = cls.__init__
    if inherited is object.__init__ or getattr(inherited, "_scena_actor_init", False):
        return

    @wraps(inherited)
    def __init__(self, *args, **kwargs):
        inherited(self, *args, **kwargs)

    cls.__init__ = __init__


class Entity(Container):
    """Registry citizen: identity, groups, process host, ink.

    Owns registry membership (roster / layer / groups), soft/hard removal, and optional
    collision enrollment. Does **not** own paint, transforms, pointer hit-testing,
    or geometry models — those stay on Graphic / Shape / Sprite.

    Bare ``Entity()`` is undrawn (``layer=None``) — directors / spawners.
    ``Graphic`` and ``SpatialFx`` pass a draw-layer default when they construct.

    Note: ``Entity`` / ``Graphic`` stay unslotted so ``Shape(Graphic, PaintState)``
    and ``Sprite(Graphic, PaintState)`` keep a single slotted MI leaf (PaintState
    + Shape/Sprite). Hot privates are slotted on those leaves.

    Args:
        layer: Draw layer; ``None`` (default) = not drawn (directors, spawners).
        group: Group tag(s). Tags are the only lookup by name (``group["boss"]``);
            there are no ids — keep the actor in a variable.
    """

    _scena_is_entity = True
    # Graphics and SpatialFx set this so ``.x`` / ``.y`` raise instead of
    # becoming ink. Bare Entity keeps those names as ordinary ink.
    _pose_xy_guard = False
    # Hitbox parts live on Sprite slots; class defaults keep the collision
    # engine's per-item probes off ``__getattr__`` for every other Entity.
    _hitbox_claims = None
    _hitbox_parts = ()
    # Class defaults so a hot read never reaches ``__getattr__`` (ink lookup):
    # set during a destroy teardown (X-life-5) and during an @exit_mode hook
    # (S2-3).
    _dying = False
    _mode_leaving = None
    # A whole-object link (``obj @= other``) drives the pose too (a copy carries
    # it, C7); Point overrides: its link follows position only.
    _whole_link_carries_pose = True
    # ``on_collide*`` callbacks the actor keeps while it has no Collider (park,
    # ``collidable = False``); ``ensure_collider`` copies them into a new one.
    _collide_cbs = None
    # ``collidable = True`` written by the author: the body stays in collision
    # when a pair tag that enrolled it retires (review 2026-10-09 S8-7).
    _collision_opt_in = False
    # Probed for every moving actor every frame (collision proxy, plain-blit
    # draw): a class default keeps them off ``__getattr__``, which costs an
    # exception per miss (graphics review E15: about 0.5 µs each).
    _main_hitbox_off = False
    _touching_sides = frozenset()
    _blit_plain = None

    def __init_subclass__(cls, **kwargs):
        # One hook only: a second ``__init_subclass__`` in this class body would
        # silently replace this one (routes, actor finish, deferred specs lost).
        if kwargs:
            _refuse_class_keywords(cls, kwargs)
        super().__init_subclass__(**kwargs)
        from ._pkg import is_framework_module
        if not is_framework_module(cls.__module__):
            _refuse_class_body_values(cls)
        _check_class_hook_names(cls)   # a hook the engine would never call (PA3)
        _adopt_mixin_init(cls)         # a mixin's __init__ becomes this class's own
        _wrap_construct_rollback(cls)  # inner: undo registration on raise
        _wrap_actor_init(cls)          # outer: setup() / watches after __init__
        _install_setattr_route(cls)
        _cache_class_tables(cls)
        _claim_deferred_every_specs(cls)
        _claim_deferred_after_specs(cls)
        _cache_actor_lookups(cls)

    @classmethod
    def _class_keywords(cls) -> frozenset:
        """Names an author subclass may set on its class line (``class Bolha(Circle,
        radius=30)``); a family that takes class keywords overrides this."""
        return frozenset()

    def __init__(
        self,
        *,
        layer: Any = None,
        group: Optional[Union[str, Sequence[str]]] = None,
    ):
        self._construct(layer=layer, group=group)

    def _construct(
        self,
        *,
        layer: Any = None,
        group: Optional[Union[str, Sequence[str]]] = None,
        attr_name: Optional[str] = None,
        owner: Optional[Container] = None,
        register: bool = True,
    ):
        name = attr_name if attr_name is not None else self.__class__.__name__

        Container.__init__(self, owner=owner, attr_name=name)

        if owner is None and not getattr(self, "_ephemeral", False):
            # Where the author made this actor — error messages name it by line
            # (``entity_label``). Parts are named through their owner.
            d = self.__dict__
            site = _author_site()
            d["_site"] = site
            if _PENDING_CLONE_SOURCES:
                src = _PENDING_CLONE_SOURCES.pop()
                d["_clone_note"] = _clone_note(src, site)

        from .canvas import ScenaCanvas
        self._scenacanvas = ScenaCanvas.get_current()

        if layer is _USE_LAYER_DEFAULT:
            layer = self._scenacanvas.registry.layers.default

        self._reg_key = None  # roster serial; set by ``Registry.register``
        self._layer = layer
        self._visible = True
        self._destroyed = False  # True only after hard destroy()
        self._collidable = False
        self._collider = None
        # Author ``collidable = False`` opts out of ``@collide`` group
        # auto-enroll. Cleared on ``collidable = True``.
        self._collision_opt_out = False
        self._time_scale = 1.0
        self._active = True
        self._active_saved_visible = None  # None when active; else stashed bool
        self._active_saved_collidable = None
        self._mode = None
        self._mode_time = 0.0
        self._on_update = None
        self._on_destroy = None
        self._mode_script = None
        self._frozen_warned = False
        self._actor_constructed = False
        self._collision_epoch = 0
        # Ink bag stays None until the first unknown author write (``ship.hp = 3``).
        # Empty ``{}`` on every Shape/Point was a steady tax for labs that never use ink.
        self._ink = None

        object.__setattr__(self, "group", _normalize_groups(group))

        # Ephemeral temps (e.g. Point.temp) must not enter the roster / layers.
        if register and not getattr(self, "_ephemeral", False):
            self._scenacanvas.registry.register(self, layer)

        if type(self).__init__ is Entity.__init__:
            from .process import call_without_owner
            call_without_owner(_finish_actor_construct, self)

    def draw(self, skia_canvas) -> None:
        """No visual on bare Entity. Safe if moved onto a draw layer."""
        return

    def __setattr__(self, name: str, value: Any) -> None:
        # Private / internal writes: still enter this method (Python tax for any
        # ``__setattr__``), but skip ink/route. Hot pose code should prefer
        # ``object.__setattr__`` for ``_rotation`` / ``_scale`` when tight.
        if not name or name[0] == "_":
            object.__setattr__(self, name, value)
            return
        # Known API / geometry first — never consult ink (pose / ContainerSlots).
        # The instance's own map first: a destroyed actor carries one in which
        # every name refuses (``_mark_routes_dead``), so a live write pays no
        # dead check at all.
        route_map = getattr(self, "_setattr_route", None)
        if route_map is None:
            _install_setattr_route(type(self))
            route_map = type(self)._setattr_route  # type: ignore[attr-defined]
        route = route_map.get(name)
        if callable(value) and not isinstance(value, type):
            if (
                name in _PROPERTY_LINK_ANY
                and isinstance(self, Graphic)
                and name in type(self)._scena_property_links
            ):
                raise CallableAssignError(callable_assign_message(self, name)) from None
            try:
                self._resolve_field(name)
            except AttributeError:
                # Reserved paint / engine fields cannot be live-linked. Actor
                # hooks and mode are also reserved (not ink) but their job is a
                # callable (e.mode = diving, e.on_update = fn).
                if name in _INK_RESERVED and name not in _CALLABLE_RESERVED:
                    raise CallableAssignError(_ink_link_forbidden_message(self, name)) from None
        if route is not None:
            if route is _SET_OBJECT:
                if name == "group":
                    self._assign_groups(value)
                    return
                object.__setattr__(self, name, value)
            elif route is _LOOK_MISSING:
                raise AttributeError(_look_missing_message(self, name))
            else:
                route.__set__(self, value)
                if name in _PLACEMENT_WRITES:
                    _placement_write(self)
            return
        # Unknown public name → ink (lazy bag of bare scalars).
        try:
            object.__getattribute__(self, name)
            if value.__class__ is _state_module._KEY_NAME:
                value = str(value)      # see the ink store below
            object.__setattr__(self, name, value)
            return
        except AttributeError:
            pass
        try:
            destroyed = object.__getattribute__(self, "_destroyed")
        except AttributeError:
            destroyed = False
        if destroyed:
            raise DestroyedError(_destroyed_access_message(
                self, f"{type(self).__name__} is destroyed and cannot set {name!r}"
            ))
        if _pose_xy_refused(self, name):
            raise AttributeError(_pose_xy_forbidden_message(self, name))
        retired = _retired_attr_message(self, name)
        if retired is not None:
            raise AttributeError(retired, name=name, obj=None)
        try:
            ink = object.__getattribute__(self, "_ink")
        except AttributeError:
            object.__setattr__(self, name, value)
            return
        if isinstance(value, Attribute):
            value = value.value
        # Callables via plain `=` do not install a link — same rule as
        # Attribute/State/property-link fields. Use `obj['field'] @= …`.
        if callable(value) and not isinstance(value, type):
            raise CallableAssignError(_ink_callable_message(self, name, value)) from None
        if ink is None:
            _check_ink_near_miss(type(self), name, route_map, value)
            ink = {}
            object.__setattr__(self, "_ink", ink)
        elif name in ink:
            self._write_field(name, value)
            return
        else:
            _check_ink_near_miss(type(self), name, route_map, value)
        # A key from ``on_key_*`` is stored as a plain ``str``: its loud ``==``
        # is for the handler, not for every later compare (IN2 in Testing
        # Design). A rewrite unwraps it in ``_write_field``.
        if value.__class__ is _state_module._KEY_NAME:
            value = str(value)
        ink[name] = value

    # Private names go straight to object.__setattr__ (state._container_dict_init).
    __setattr__._scena_private_passthrough = True

    def __getattr__(self, name: str):
        # Fast path: an author field (ink) read on a live actor, when the slow
        # path below would return it too: not destroyed, not the refused
        # ``x`` / ``y`` alias, not a retired name (Actors Design, "Ink").
        if _INK_READ_FAST and name != "x" and name != "y":
            try:
                ink = _obj_getattr(self, "_ink")       # a slot on most classes
                destroyed = _obj_getattr(self, "_destroyed")
            except AttributeError:
                ink = None
                destroyed = True
            if ink is not None and name in ink and not destroyed:
                d = self.__dict__
                merged = type(self).__dict__.get("_scena_retired_merged")
                if merged is None:
                    retired = _retired_attr_message(self, name) is not None  # builds the map
                else:
                    retired = name in merged
                if not retired:
                    anchors = d.get("_field_anchors")
                    if anchors and name in anchors:
                        anchors[name]._ensure_fresh()
                    return ink[name]
        return self._ink_read_slow(name)

    def _ink_read_slow(self, name: str):
        """``__getattr__`` in full: refusals first, then ink."""
        try:
            destroyed = object.__getattribute__(self, "_destroyed")
        except AttributeError:
            destroyed = False
        if destroyed:
            raise DestroyedError(_destroyed_access_message(
                self, f"{type(self).__name__} is destroyed"
            ))
        if _pose_xy_refused(self, name):
            raise AttributeError(_pose_xy_forbidden_message(self, name)) from None
        retired = _retired_attr_message(self, name)
        if retired is not None:
            raise AttributeError(retired, name=name, obj=None) from None
        try:
            ink = object.__getattribute__(self, "_ink")
        except AttributeError:
            if _never_built(self):
                # ``self.radius`` / ``self.move_by(…)`` in an author ``__init__``
                # before (or without) ``super().__init__`` (CB1).
                raise AttributeError(_read_before_built_message(self, name)) from None
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}"
            ) from None
        if ink is not None and name in ink:
            anchors = self.__dict__.get('_field_anchors')
            if anchors and name in anchors:
                anchors[name]._ensure_fresh()
            return ink[name]
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    def __getitem__(self, key: str):
        """Bracket link handle; unknown entity ink names defer until ``@=``."""
        from .state import FieldRef

        if isinstance(key, str):
            retired = _retired_attr_message(self, key)
            if retired is not None:
                raise AttributeError(retired, name=key, obj=None)
        if type(self).__dict__.get("_ink_strict", False):  # own class only: subclasses add ink
            try:
                self._resolve_field(key)
            except AttributeError:
                # No ink here: name a method / read-only property as ``=`` does.
                if isinstance(key, str) and not key.startswith("_"):
                    if key in _INK_RESERVED:    # the same answer as every kind
                        raise AttributeError(_ink_link_forbidden_message(self, key)) from None
                    route_map = getattr(type(self), "_setattr_route", None)
                    if route_map is None:
                        _install_setattr_route(type(self))
                        route_map = type(self)._setattr_route
                    exact = _ink_exact_name_message(type(self), key, route_map)
                    if exact is not None:
                        raise AttributeError(exact) from None
                raise
        else:
            try:
                self._resolve_field(key)
            except AttributeError:
                if not isinstance(key, str) or key.startswith("_"):
                    raise
                if key in _INK_RESERVED:
                    raise AttributeError(_ink_link_forbidden_message(self, key)) from None
                if _pose_xy_refused(self, key):
                    raise AttributeError(_pose_xy_forbidden_message(self, key)) from None
                route_map = getattr(type(self), "_setattr_route", None)
                if route_map is None:
                    _install_setattr_route(type(self))
                    route_map = type(self)._setattr_route
                _check_ink_near_miss(type(self), key, route_map)
        return FieldRef(owner=self, name=key)

    def _ensure_ink_field(self, name: str) -> None:
        """Ensure ``name`` exists in ink (writes/links may create; reads may not)."""
        if type(self).__dict__.get("_ink_strict", False):  # own class only: subclasses add ink
            raise AttributeError(f"{type(self).__name__} has no field {name!r}")
        if _pose_xy_refused(self, name):
            raise AttributeError(_pose_xy_forbidden_message(self, name))
        ink = getattr(self, "_ink", None)
        if ink is None:
            ink = {}
            object.__setattr__(self, "_ink", ink)
        if name not in ink:
            route_map = getattr(type(self), "_setattr_route", None)
            if route_map is None:
                _install_setattr_route(type(self))
                route_map = type(self)._setattr_route
            _check_ink_near_miss(type(self), name, route_map)
            ink[name] = 0.0

    def _link_field(self, name: str, source) -> None:
        try:
            self._resolve_field(name)
        except AttributeError:
            if name in _INK_RESERVED:
                raise AttributeError(_ink_link_forbidden_message(self, name)) from None
            if _pose_xy_refused(self, name):
                raise AttributeError(_pose_xy_forbidden_message(self, name)) from None
            self._ensure_ink_field(name)
            try:
                super()._link_field(name, source)
            except BaseException:
                # The link failed (formula raised on first evaluation): the
                # ink cell this call created must not survive (W3).
                try:
                    ink = object.__getattribute__(self, "_ink")   # a slot, not __dict__
                except AttributeError:
                    ink = None
                if ink is not None:
                    ink.pop(name, None)
                raise
            return
        super()._link_field(name, source)

    def _clean_up(self) -> None:
        try:
            from .process import get_scheduler
            get_scheduler().watch_mode(self, False)
            get_scheduler().watch_update(self, False)
        except Exception:
            pass
        object.__setattr__(self, "_mode", None)
        object.__setattr__(self, "_on_update", None)
        object.__setattr__(self, "_on_destroy", None)
        object.__setattr__(self, "_mode_script", None)
        Container._clean_up(self)
        ink = getattr(self, "_ink", None)
        if ink is not None:
            ink.clear()
        object.__setattr__(self, "_ink", None)

    # --- canvas placement --------------------------------------------------------

    @property
    def layer(self) -> Optional[Union[str, int]]:
        """Draw layer (str name, int position, or ``None`` if undrawn)."""
        return self._layer

    def _is_on_parallax_layer(self) -> bool:
        """True when this item's current layer has a non-neutral camera response."""
        name = self._layer
        if name is None:
            return False
        try:
            layer = self._scenacanvas.registry.layers.get(name)
        except Exception:
            return False
        return layer is not None and not layer._is_neutral_response

    def _is_on_ui_layer(self) -> bool:
        """True when this item is on the reserved view-space ``ui`` layer."""
        from .registry import layer_is_ui
        return layer_is_ui(self._layer)

    def _reject_if_parallax_layer(self, feature: str) -> None:
        """Raise :class:`ParallaxLayerError` if this item is on a parallax layer."""
        if not self._is_on_parallax_layer():
            return
        from .registry import ParallaxLayerError
        raise ParallaxLayerError(
            f"Cannot set {feature}=True on {self!r} in parallax layer "
            f"{self._layer!r}: parallax layers are decoration-only "
            f"(no hit-testing or collision)"
        )

    def _reject_if_ui_layer(self, feature: str) -> None:
        """Raise :class:`UiLayerError` if this item is on the reserved ``ui`` layer."""
        if not self._is_on_ui_layer():
            return
        from .registry import UiLayerError
        raise UiLayerError(
            f"Cannot set {feature}=True on {self!r} in layer 'ui': "
            f"the ui layer is view-space (no collision)"
        )

    def _reject_move_to_parallax_if_interactive(self, target_layer: Optional[Union[str, int]]) -> None:
        """Block moving interactive/collidable items onto a non-neutral layer."""
        if target_layer is None:
            return
        try:
            layer = self._scenacanvas.registry.layers.get(target_layer)
        except Exception:
            return
        if layer is None or layer._is_neutral_response:
            return
        interactive = bool(
            getattr(self, "_clickable", False)
            or getattr(self, "_draggable", False)
            or getattr(self, "_droppable", False)
            or getattr(self, "_wheel_rotate", False)
            or getattr(self, "_on_hover", None) is not None
            or getattr(self, "_on_hover_exit", None) is not None
            or _wants_collision(self)
        )
        if not interactive:
            return
        from .registry import ParallaxLayerError
        raise ParallaxLayerError(
            f"Cannot move {self!r} into parallax layer {target_layer!r}: "
            f"item is interactive or collidable; clear those flags first "
            f"(parallax layers are decoration-only)"
        )

    def _reject_move_to_ui_if_collidable(self, target_layer: Optional[Union[str, int]]) -> None:
        """Block moving collidable items onto the reserved ``ui`` layer."""
        from .registry import layer_is_ui, UiLayerError
        if not layer_is_ui(target_layer):
            return
        if not _wants_collision(self):
            return
        raise UiLayerError(
            f"Cannot move {self!r} into layer 'ui': item is collidable; "
            f"clear collidable first (ui is view-space, no collision)"
        )

    def _reject_move_to_ui_if_spatial(self, target_layer: Optional[Union[str, int]]) -> None:
        """Block moving SpatialFx onto the reserved ``ui`` layer."""
        from .registry import layer_is_ui
        if not layer_is_ui(target_layer):
            return
        from .spatial_fx import SpatialFx
        if isinstance(self, SpatialFx):
            from .registry import UiLayerError
            raise UiLayerError(
                f"Cannot move {self!r} into layer 'ui': "
                f"SpatialFx stays on world layers"
            )

    @layer.setter
    def layer(self, value: Optional[Union[str, int]]) -> None:
        """Set the layer (str name, int position, or ``None`` → undrawn)."""
        if not self.is_alive:
            raise DestroyedError(_destroyed_access_message(self, "layer"))
        from .registry import normalize_layer_name
        target = normalize_layer_name(value)
        current = normalize_layer_name(self._layer)
        if target != current:
            owner = self.__dict__.get("_owner")
            if owner is not None and getattr(type(owner), "_draws_parts", False):
                raise TypeError(
                    f"{self.name} is drawn by its {type(owner).__name__}; it has no "
                    f"layer of its own. Move the {type(owner).__name__} instead."
                )
            self._reject_move_to_parallax_if_interactive(target)
            self._reject_move_to_ui_if_collidable(target)
            self._reject_move_to_ui_if_spatial(target)
            # change_layer sets ``_layer`` (normalized); do not assign again.
            self._scenacanvas.registry.change_layer(self, value)

    def undraw(self) -> "Entity":
        """Soft remove: stop drawing; keep graph/roster entry (and remaining timers if any).

        The item stays ``is_alive``. Prefer ``destroy()`` for hard delete.
        """
        self._scenacanvas.registry.unregister_draw(self)
        return self

    @property
    def is_alive(self) -> bool:
        """True until hard ``destroy()``. Independent of visibility, layer, and park.

        After ``destroy()``, ``active`` also reads False. Soft ``undraw()`` and
        ``active = False`` leave ``is_alive`` True.
        """
        return not bool(getattr(self, "_destroyed", False))

    def __bool__(self) -> bool:
        """False after ``destroy()``. ``if actor:`` is the same check as ``is_alive``.

        A dead actor is still a Python object (the name is not cleared). Boolean
        context is how ``if nave:`` skips it, the same way an empty group is falsy.
        """
        return self.is_alive

    def destroy(self) -> "Entity":
        """Hard remove from Scena: drop draw layer, roster entry, groups, and reactive graph.

        A second call is a no-op, so it cannot touch a later actor (roster keys are never reused).

        After this, ``is_alive`` and ``active`` are False. Python references you
        still hold are not deleted, but must not be treated as live Scena objects.
        Cancels process handles owned by this item (``after`` / ``every`` / tweens).
        ``on_destroy`` (if set) runs first, while this item is still fully alive.
        """
        if _SOLVER_READING:
            refuse_if_solver_reading('destroy()')
        if not self.is_alive or getattr(self, "_dying", False):
            return self     # dead, or a hook of its own teardown (X-life-5)
        refuse_part_as_actor(self, "destroy()", "life")
        try:
            _fire_on_destroy(self)
        finally:
            self._scenacanvas.registry.destroy(self)  # teardown completes; error re-raises
        return self

    def cancel_process(self) -> "Entity":
        """Cancel owned timers / tweens / sounds / mode script; Entity stays alive.

        Same cancel path as ``destroy()`` for process Handles (all scopes), then
        quietly clears ``mode`` to ``None`` without firing ``@exit_mode`` or
        ``on_destroy``. Does not touch ink, tags, groups, ``active``,
        ``on_update``, ``@when``, or transients (use ``clear_transients()``).

        Held ``Handle`` instances become ``.cancelled`` (safe to ignore or
        cancel again). Returns ``self`` for chaining.
        """
        from .process import get_scheduler
        sched = get_scheduler()
        sched.cancel_owner(self)
        object.__setattr__(self, "_mode", None)
        object.__setattr__(self, "_mode_time", 0.0)
        object.__setattr__(self, "_mode_idle_from", 0.0)
        object.__setattr__(self, "_frozen_warned", False)
        sched.watch_mode(self, False)
        return self

    def prepare_fx(self, *looks) -> "Entity":
        """Warm silhouette FX caches (Sprite). No-op on Shape / SpatialFx / Entity.

        Advanced load-screen hook. Beginners: assigning ``.visual`` is enough.
        Sprite overrides to bake FrameFx for listed looks (or the current visual
        when called with no args). Always returns ``self`` for chaining.
        """
        return self

    @property
    def time_scale(self) -> float:
        """Multiplier on world ``clock.dt`` for this actor's timers. Default 1."""
        return self._time_scale

    @time_scale.setter
    def time_scale(self, value) -> None:
        self._time_scale = _time_scale_value(self, value)

    @property
    def active(self) -> bool:
        """If False, park this actor: no draw, no collision, process timers pause.

        Orthogonal to ``mode`` and to hard ``destroy()`` while this item is alive.
        After ``destroy()``, reads False; ``active = True`` does not revive.
        ``@when`` on ink still runs. Re-enabling restores prior ``visible`` /
        ``collidable`` and resumes owned timers where they left off.
        """
        return bool(getattr(self, "_active", True))

    @active.setter
    def active(self, value) -> None:
        want = _expect_flag(value, 'active')
        if self.is_alive:
            refuse_part_as_actor(self, "active =", "life")
        was = bool(getattr(self, "_active", True))
        if want == was:
            return
        if not self.is_alive:
            return
        # A part parks with its owner (Actors Design — "A part is not an
        # actor"): shown handles hide and stop taking the pointer, their
        # timers pause, and resume puts back exactly what was there.
        from .registry import entity_parts
        if not want:
            self._park_self()
            for part in entity_parts(self):
                if part.is_alive and getattr(part, "_active", True):
                    part._park_self()
            return
        self._resume_self()
        for part in entity_parts(self):
            if part.is_alive and not getattr(part, "_active", True):
                part._resume_self()

    def _park_self(self) -> None:
        """Park this item alone: stash and force off draw + collision; keep handles."""
        # A bare Entity has neither flag; skip the ones it does not own.
        try:
            vis = self.visible
        except AttributeError:
            vis = None
        try:
            col = self.collidable
        except AttributeError:
            col = None
        # Turn both off while still active (the setters stash once parked),
        # then stash the author's values and mark parked. Only a shown item is
        # written: hiding an already hidden one is not a no-op everywhere (a
        # hidden Point on a layer leaves it), and resume must put back exactly
        # what was there.
        if vis:
            d = self.__dict__
            d["_engine_flag_write"] = True      # passes a linked ``visible``
            try:
                self.visible = False
            finally:
                d.pop("_engine_flag_write", None)
        object.__setattr__(self, "_active_saved_visible", vis)
        object.__setattr__(self, "_active_saved_collidable", col)
        object.__setattr__(self, "_active", False)
        # Leave collision last: its exit handlers (author code) see a parked
        # actor, and a ``visible`` / ``collidable`` write there goes to the
        # stash. Before, they ran while ``active`` still read True and a
        # ``me.visible = True`` left a parked actor drawn (review X-life-1).
        if col:
            self._leave_collision()       # not ``collidable = False``: no opt-out (E2)

    def _resume_self(self) -> None:
        """Resume this item alone: restore stashed flags it owns."""
        object.__setattr__(self, "_active", True)
        saved_vis = getattr(self, "_active_saved_visible", True)
        saved_col = getattr(self, "_active_saved_collidable", False)
        object.__setattr__(self, "_active_saved_visible", None)
        object.__setattr__(self, "_active_saved_collidable", None)
        linked = getattr(self, "_channel_linked", None)
        if linked is not None and linked("visible"):
            # A linked ``visible`` takes its formula's value now, not the
            # stash (the formula may have changed while parked; a read here
            # would pull and the stash would then overwrite it).
            from .state import _reapply_channel_links
            _reapply_channel_links(self)
        # Hidden then and hidden now: nothing to write (see ``_park_self``).
        elif saved_vis is not None and bool(saved_vis) != bool(self.visible):
            self.visible = bool(saved_vis)
        # The stash was validated when it was written (E11); rejoin through the
        # same path as ``collidable = True`` so callbacks and every pair group
        # declared meanwhile come back (E1, GR8).
        if saved_col and not getattr(self, "_collision_opt_out", False):
            self._enter_collision()
        elif not getattr(self, "_collision_opt_out", False):
            from .collision import enroll_item_groups
            enroll_item_groups(self)

    @property
    def mode(self):
        """Current mode callable, or ``None``."""
        return self._mode

    @mode.setter
    def mode(self, value) -> None:
        """Enter ``value`` if different from the current mode (idempotent).

        Same-mode reassignment is a no-op. Use :meth:`goto_mode` to force
        exit+enter.
        """
        self._validate_mode_value(value)
        self._refuse_mode_in_exit_hook()
        if value == self._mode:
            return
        self._goto_mode(value)

    def _refuse_mode_in_exit_hook(self) -> None:
        leaving = getattr(self, "_mode_leaving", None)
        if leaving is not None:
            # It re-ran its own exit hook ~200 times, then RecursionError (S2-3).
            name = getattr(leaving, "__name__", "the mode")
            raise TypeError(
                f"{self.name}.mode = … inside @exit_mode({name}): the change of mode is "
                f"already under way. Choose the next mode where the change is made "
                f"(the line that assigns mode, or then=), not in the exit hook."
            )

    def goto_mode(self, fn) -> None:
        """Always exit, then enter the mode ``fn`` — even when ``fn`` is the
        current mode (a restart). ``e.mode = fn`` does nothing when ``fn`` is
        already running."""
        self._validate_mode_value(fn)
        self._refuse_mode_in_exit_hook()
        self._goto_mode(fn)

    @staticmethod
    def _validate_mode_value(value) -> None:
        if value is None:
            return
        if isinstance(value, str):
            raise TypeError(
                "mode is a function, not a string. Write e.mode = diving."
            )
        if not callable(value):
            raise TypeError(
                "mode must be a function. You assigned "
                f"{type(value).__name__} — if you wrote e.mode = diving(), "
                "drop the ()."
            )

    def _goto_mode(self, value) -> None:
        if getattr(self, "_destroyed", False):
            # A dead actor has no modes: entering one would run its body (and
            # arm its timers) for an actor that no longer exists. Clearing is
            # a quiet no-op, like a second destroy().
            if value is None:
                return
            raise DestroyedError(_destroyed_access_message(self, "mode"))
        from .process import _invoke, get_scheduler, SCOPE_MODE
        sched = get_scheduler()
        old_mode = self._mode
        sched.cancel_owner(self, scopes=(SCOPE_MODE,), release=True)

        exit_fn = getattr(old_mode, "_exit_mode", None) if old_mode is not None else None
        if exit_fn is not None:
            from .process import no_owner
            object.__setattr__(self, "_mode_leaving", old_mode)
            try:
                with no_owner():         # no owning() context (S2-1)
                    _invoke(exit_fn, self)
            except BaseException:
                # Finish the transition (never leave a cancelled, frozen old
                # mode), then re-raise — a watchdog trip too (S2-12). An
                # error entering the new mode chains onto this one.
                object.__setattr__(self, "_mode_leaving", None)
                if not getattr(self, "_destroyed", False):
                    self._enter_mode(value)
                raise
            object.__setattr__(self, "_mode_leaving", None)
            if getattr(self, "_destroyed", False):
                # The exit hook destroyed the actor: no next body runs on a
                # dead actor (S2-4; Protections: the body never runs).
                return
        self._enter_mode(value)

    def _enter_mode(self, value) -> None:
        from .process import (
            _invoke, _is_async_callable, _spawn_coro, get_scheduler, owning, SCOPE_MODE,
        )
        sched = get_scheduler()
        object.__setattr__(self, "_mode", value)
        object.__setattr__(self, "_mode_time", 0.0)
        object.__setattr__(self, "_mode_idle_from", 0.0)
        object.__setattr__(self, "_frozen_warned", False)
        if value is None:
            sched.watch_mode(self, False)
            return
        sched.watch_mode(self, True)
        with owning(self, scope=SCOPE_MODE):
            if _is_async_callable(value):
                coro = _spawn_coro(value, self)
                sched.start_mode_script(self, coro)
            else:
                _invoke(value, self)

    @property
    def mode_time(self) -> float:
        """Seconds in the current mode (effective time). 0 on enter / re-enter."""
        return float(getattr(self, "_mode_time", 0.0))

    @property
    def on_update(self):
        """Per-frame hook ``fn(e, dt)`` or method ``fn(self, dt)``. Runs during process tick, including while an async mode is suspended."""
        return self._on_update

    @on_update.setter
    def on_update(self, value) -> None:
        if value is not None and not callable(value):
            raise TypeError(
                f"on_update expected a function, got {type(value).__name__}."
            )
        refuse_async(value, what="on_update =")
        object.__setattr__(self, "_on_update", value)
        from .process import get_scheduler
        get_scheduler().watch_update(self, value is not None)

    @property
    def on_destroy(self):
        """Called once from ``destroy()``, before any other teardown step."""
        return self._on_destroy

    @on_destroy.setter
    def on_destroy(self, value) -> None:
        if value is not None and not callable(value):
            raise TypeError(
                f"on_destroy expected a function, got {type(value).__name__}."
            )
        refuse_async(value, what="on_destroy =")
        object.__setattr__(self, "_on_destroy", value)

    def setup(self) -> None:
        """Called once after construct. Override on a subclass instead of ``__init__``.

        Script-level ``setup(canvas)`` is the app hook; this is the per-actor hook.
        """

    def after(self, delay: float, fn=None, *, then=None, on_done=None, name: Optional[str] = None):
        """``after`` owned by this item (survives mode changes; dies on destroy).

        ``then=`` is the mode to enter when the timer finishes.
        ``on_done=`` calls a function (same channel as positional ``fn``).
        """
        from .process import after_on
        return after_on(self, delay, fn, then=then, on_done=on_done, name=name)

    def every(self, interval: float, fn=None, *, name: Optional[str] = None):
        """``every`` owned by this item (dies on destroy). Named timers replace themselves."""
        from .process import every_on
        return every_on(self, interval, fn, name=name)

    def ready(self, name: str, interval: Optional[float] = None) -> bool:
        """``ready`` scoped to this Entity — independent cooldown slot per instance."""
        from .process import ready_on
        return ready_on(self, name, interval)

    def recently(self, name: str, value, hold: float = 0.1) -> bool:
        """``recently`` scoped to this Entity — independent memory per instance."""
        from .process import recently_on
        return recently_on(self, name, value, hold)

    def tween(self, target, to, *, time: float, ease="linear", then=None, on_done=None, force: bool = False, name: Optional[str] = None, loops: object = 1, yoyo: bool = False, start=None):
        """Entity-scoped tween. Survives mode changes; dies on destroy."""
        from .process import tween_on
        return tween_on(
            self, target, to, time=time, ease=ease, then=then, on_done=on_done,
            force=force, name=name, loops=loops, yoyo=yoyo, start=start,
        )

    def play_sound(
        self,
        source,
        *,
        volume=None,
        pan=0.0,
        pitch=1.0,
        loops=1,
        fade_in=None,
        crossfade=None,
        on_done=None,
        then=None,
        name: Optional[str] = None,
    ):
        """Play a sound owned by this item (survives mode changes; dies on destroy)."""
        from .audio import play_sound_on
        return play_sound_on(
            self, source,
            volume=volume, pan=pan, pitch=pitch, loops=loops,
            fade_in=fade_in, crossfade=crossfade,
            on_done=on_done, then=then, name=name,
        )

    def _refuse_part_tags(self, verb: str, name: Any = None) -> None:
        refuse_part_as_actor(self, verb, "tags", name)

    def tag(self, *names: str) -> "Entity":
        """Add this item to named groups (tag sugar). Refused on a part."""
        self._refuse_part_tags("tag", names[0] if names else None)
        for n in _tag_names(names, "tag"):
            self.add_to_group(n)
        return self

    def untag(self, *names: str) -> "Entity":
        """Remove this item from named groups (tag sugar). Refused on a part."""
        self._refuse_part_tags("untag", names[0] if names else None)
        for n in _tag_names(names, "untag"):
            self.remove_from_group(n)
        return self

    def tagged(self, name: str) -> bool:
        """True if this item is in the named group."""
        name = _require_group_name(name, "tagged")
        return name in self.group

    def _assign_groups(self, value) -> None:
        """``obj.group = …`` replaces the tag set and keeps the registry index in sync."""
        new = _normalize_groups(value)
        if new:
            self._refuse_part_tags("group =", next(iter(sorted(new))))
        old = getattr(self, "group", None)
        registry = None
        if old is not None:
            registry = self._scenacanvas.registry
            if not registry.is_live(self):
                registry = None
        if registry is None:
            object.__setattr__(self, "group", new)
            return
        for gid in list(old - new):
            registry.remove_from_group(self, gid)
        for gid in sorted(new - old):
            registry.add_to_group(self, gid)

    def add_to_group(self, groupid: str) -> "Entity":
        """Add this object to a named group."""
        groupid = _require_group_name(groupid, "add_to_group")
        if not self.is_alive:
            raise DestroyedError(_destroyed_access_message(self, "tag"))
        self._refuse_part_tags("add_to_group", groupid)
        self._scenacanvas.registry.add_to_group(self, groupid)
        return self

    def remove_from_group(self, groupid: str) -> "Entity":
        """Remove this object from a named group."""
        groupid = _require_group_name(groupid, "remove_from_group")
        self._refuse_part_tags("remove_from_group", groupid)
        self._scenacanvas.registry.remove_from_group(self, groupid)
        return self

    # --- collision enrollment (same API for Shape and SpatialFx) --------------

    @property
    def collidable(self) -> bool:
        """If True, this item participates in the collision system (implicit Collider).

        While parked this reads False (parked never collides); a write goes to
        the stash that resume restores.
        """
        return self._collidable

    @collidable.setter
    def collidable(self, value: bool) -> None:
        _refuse_if_destroyed(self, "collidable")
        value = _expect_flag(value, 'collidable')
        if value:
            refuse_part_as_actor(self, "collidable = True", "body")
            # Checked where it is written, parked or not: a stashed True on the
            # ui / parallax layer used to raise only on resume (E11).
            self._reject_if_parallax_layer("collidable")
            self._reject_if_ui_layer("collidable")
        elif is_part(self):
            return                  # a part is never a body: False is a no-op clear
        # The author's switch, recorded whatever the current state: False is a
        # sticky opt-out even before any ``@collide`` enrolled the actor (E3).
        object.__setattr__(self, "_collision_opt_out", not value)
        object.__setattr__(self, "_collision_opt_in", value)
        if _parked(self):
            _stash_flag(self, "collidable", value)  # parked never collides; resume applies
            return
        if value == self._collidable:
            return
        if value:
            self._enter_collision()
        else:
            self._leave_collision()

    def _enter_collision(self) -> None:
        """Join collision: the one path for ``collidable = True``, a callback
        opt-in and resume. The new Collider gets the actor's callbacks and the
        actor enrolls in every pair group declared so far."""
        from .collision import ensure_collider, enroll_item_groups
        ensure_collider(self)
        # ensure_collider sets _collidable / _collider on success.
        self._collidable = True
        enroll_item_groups(self)

    def _leave_collision(self) -> None:
        """Leave collision (exits fire); callbacks stay on the actor (E1).

        Park calls this directly: it never writes the author's opt-out."""
        col = self._collider
        if col is not None:
            _keep_collide_callbacks(self, col)
            col._unregister()
            self._collider = None
        self._collidable = False
        # ``touching_*`` is written by the collision step, which no longer
        # visits this body: clear it, or a parked / ghosted body reads
        # "bottom" in mid-air and floor-snaps when it rejoins (review
        # 2026-10-09 S8-5).
        ink = getattr(self, "_ink", None)
        if (isinstance(ink, dict) and ink.get("touching_sides")) or \
                getattr(self, "_touching_contacts", None):
            self._collision_set_touching(frozenset(), ())
        # Hitbox parts share the host's switch (Sprite only).
        retire = getattr(type(self), "_retire_hitbox_parts", None)
        if retire is not None:
            retire(self)

    def _collide_callback(self, attr: str):
        col = self._collider
        if col is not None:
            return getattr(col, attr)
        cbs = self._collide_cbs
        return cbs.get(attr) if cbs else None

    @property
    def on_collide(self):
        """Callback on collision enter: ``fn(me, other, info)``.

        Opts the item into the collision system with ``ANYTHING`` interest
        (this body vs every other enrolled participant) while any
        ``on_collide*`` callback is set. Clearing all three to ``None`` drops
        callback-sourced ``ANYTHING`` (see ``Collider._sync_anything_interest``).
        The callback belongs to the actor: it survives park and
        ``collidable = False`` / ``True`` (Actors Design — active).
        """
        return self._collide_callback("on_collide")

    def _bind_on_collide_callback(self, attr: str, value) -> None:
        _refuse_if_destroyed(self, attr)
        if value is not None:
            refuse_part_as_actor(self, f"{attr} =", "body")
            if not callable(value):
                raise TypeError(
                    f"{attr} takes a function fn(me, other, info), or None to clear it; "
                    f"got {type(value).__name__}."
                )
            refuse_async(value, what=f"{attr} =")
        cbs = dict(self._collide_cbs or ())
        if value is None:
            cbs.pop(attr, None)
        else:
            cbs[attr] = value
        object.__setattr__(self, "_collide_cbs", cbs or None)
        if value is not None:
            # A callback opts the body in, like ``collidable = True``.
            object.__setattr__(self, "_collision_opt_out", False)
            if _parked(self):
                _stash_flag(self, "collidable", True)   # joins on resume (E2)
                return
            if self._collider is None:
                self._enter_collision()               # copies every callback
                return
        if self._collider is not None:
            setattr(self._collider, attr, value)

    @on_collide.setter
    def on_collide(self, value) -> None:
        self._bind_on_collide_callback("on_collide", value)

    @property
    def on_collide_stay(self):
        """Callback every frame while overlapping: ``fn(me, other, info)``."""
        return self._collide_callback("on_collide_stay")

    @on_collide_stay.setter
    def on_collide_stay(self, value) -> None:
        self._bind_on_collide_callback("on_collide_stay", value)

    @property
    def on_collide_exit(self):
        """Callback when overlap ends: ``fn(me, other, info)``."""
        return self._collide_callback("on_collide_exit")

    @on_collide_exit.setter
    def on_collide_exit(self, value) -> None:
        self._bind_on_collide_callback("on_collide_exit", value)

    def collides_with(self, group: Any = None):
        """Return identities currently overlapping this entity's geometry.

        ``group=`` omitted is every enrolled body. A tag, ``group['name']``,
        or a list / set of those tests that group's members — no ``@collide``
        or ``resolve`` required, and the query does not enroll them.
        """
        from .collision import collision
        return collision.query_shape(self, group=group)


_install_setattr_route(Entity)
_cache_class_tables(Entity)


# Orbit motion (Collision Design — Motion vs placement). ``rotate_by`` about a
# pivot other than the pose anchor carries the anchor along an arc; the
# outermost call notes that chord on the motion channel, so the sweep sees an
# orbit as it sees a ``move_by``. Placement turns (instant ``rotate_to``, face
# snaps) raise the depth, so the ``rotate_by`` they call notes nothing; an
# override that calls ``super().rotate_by`` notes once.
_rotate_depth = 0
_ORBIT_EPS2 = 1e-12          # (1e-6 DU)²: float noise of a turn about the anchor


def _rotate_as_motion(shape, fn, value, kwargs):
    """Run ``fn(shape, value, **kwargs)`` (a ``rotate_by`` with ``about=``) and
    note the pose anchor's chord as motion. Unenrolled shapes pay one getattr."""
    global _rotate_depth
    if _rotate_depth or getattr(shape, "_collider", None) is None:
        return fn(shape, value, **kwargs)
    from .collision import _collision_pose_xy, note_collider_motion
    x0, y0 = _collision_pose_xy(shape)
    turn = None
    try:
        deg = float(value)
        if abs(deg) > _ORBIT_STEP_DEG and math.isfinite(deg):
            turn = (deg, shape._pivot_xy(kwargs.get("about")))
    except Exception:
        turn = None
    _rotate_depth += 1
    try:
        out = fn(shape, value, **kwargs)
    finally:
        _rotate_depth -= 1
    x1, y1 = _collision_pose_xy(shape)
    dx = x1 - x0
    dy = y1 - y0
    if turn is not None:
        _note_orbit_path(shape, x0, y0, x1, y1, turn[0], turn[1])
    if dx * dx + dy * dy > _ORBIT_EPS2 or turn is not None:
        note_collider_motion(shape, dx, dy)
    return out


# A turn larger than this per call is swept as an arc of chords this size or
# smaller, not one straight chord: a hitch multiplies the angle per frame, and
# one chord cut across the circle and missed targets on the arc (review
# 2026-10-09 W-T5, decided). Collision Design, "Orbit chord".
_ORBIT_STEP_DEG = 16.0


def _note_orbit_path(shape, x0, y0, x1, y1, deg, pivot) -> None:
    """The arc's waypoints from ``(x0, y0)`` about ``pivot`` by ``deg``; only
    when that arc ends where the turn did (a pivot that moved, or a sign
    convention that differs, leaves the single chord)."""
    px, py = pivot
    n = int(math.ceil(abs(deg) / _ORBIT_STEP_DEG))
    rx, ry = x0 - px, y0 - py
    radius = math.hypot(rx, ry)
    if radius <= 1e-9:
        return
    rad = math.radians(deg)
    ex = px + rx * math.cos(rad) - ry * math.sin(rad)
    ey = py + rx * math.sin(rad) + ry * math.cos(rad)
    if abs(ex - x1) + abs(ey - y1) > 1e-6 * (1.0 + radius):
        return
    pts = []
    for k in range(1, n):
        a = rad * k / n
        wx = px + rx * math.cos(a) - ry * math.sin(a)
        wy = py + rx * math.sin(a) + ry * math.cos(a)
        pts.append((wx - x0, wy - y0))
    if pts:
        from .collision import note_collider_path
        note_collider_path(shape, pts)


def _rotate_as_placement(fn, *args, **kwargs):
    """Run a placement turn: the ``rotate_by`` inside it notes no orbit motion."""
    global _rotate_depth
    _rotate_depth += 1
    try:
        return fn(*args, **kwargs)
    finally:
        _rotate_depth -= 1


def _install_timed_pose(cls) -> None:
    """Add ``time=`` / ``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=`` to subclass pose overrides
    (and ``speed=`` to the turns: a scale has no distance to cover at a rate)."""
    specs = (
        ("rotate_to", "timed_rotate_to"),
        ("rotate_by", "timed_rotate_by"),
        ("scale_to", "timed_scale_to"),
        ("scale_by", "timed_scale_by"),
    )
    for meth_name, helper_name in specs:
        orig = cls.__dict__.get(meth_name)
        if orig is None or getattr(orig, "_timed_wrapped", False):
            continue

        def _make(orig_fn=orig, helper=helper_name, name=meth_name):
            # Only a turn about a pivot can carry the pose anchor (orbit).
            orbit = name == "rotate_by"
            placement = name == "rotate_to"
            turn = orbit or placement

            @wraps(orig_fn)
            def wrapped(
                self, value, *, time=None, ease="linear", then=None, on_done=None,
                loops=1, yoyo=False, **kwargs,
            ):
                # Instant path is the per-frame hot path (angle= / scale=).
                # Do not import process or validate completion kwargs unless used.
                if kwargs:
                    f = kwargs.get("force", False)
                    if f is not False and f is not True:    # force="no" is truthy: it unlinked
                        kwargs["force"] = expect_bool(f, f"{name}(force=)")
                    if "speed" in kwargs:
                        if not turn:
                            raise TypeError(
                                f"{name}() has no speed=: a scale has no distance to "
                                f"cover at a rate. Pass time= (seconds)."
                            )
                        if kwargs["speed"] is not None:
                            # A turn at a rate: the timed helper reads speed=.
                            from . import process as _proc
                            return getattr(_proc, helper)(
                                self, value, time=time, ease=ease, then=then,
                                on_done=on_done, loops=loops, yoyo=yoyo, **kwargs,
                            )
                        del kwargs["speed"]
                if time is None:
                    if then is not None or on_done is not None or ease != "linear":
                        from .process import _NO_SPEED, _require_timed_completion
                        _require_timed_completion(
                            time=time, then=then, on_done=on_done, ease=ease, call_name=name,
                            speed=None if turn else _NO_SPEED,
                        )
                    if loops != 1 or yoyo:
                        from .process import _NO_SPEED, _require_loop_kwargs
                        _require_loop_kwargs(
                            loops=loops, yoyo=yoyo, time=time, call_name=name,
                            speed=None if turn else _NO_SPEED,
                        )
                    if kwargs.get("about") is not None:
                        if orbit:
                            return _rotate_as_motion(self, orig_fn, value, kwargs)
                        if placement:
                            return _rotate_as_placement(orig_fn, self, value, **kwargs)
                    return orig_fn(self, value, **kwargs)
                from . import process as _proc
                timed = getattr(_proc, helper)
                return timed(
                    self, value, time=time, ease=ease, then=then, on_done=on_done,
                    loops=loops, yoyo=yoyo, **kwargs,
                )
            wrapped._timed_wrapped = True
            return wrapped

        setattr(cls, meth_name, _make())


class Graphic(Entity, ABC):
    """Internal ABC: actors that draw. Pose, transients, pointer, ``.visual``.

    Not a public constructor. ``Shape`` (geometry + paint) and ``Sprite``
    (image body) inherit this. ``isinstance(x, Graphic)`` is the draw-able
    registry citizen; ``isinstance(x, Shape)`` is false for Sprite.

    ``_pose_xy_guard`` refuses ``.x`` / ``.y``: position is ``.center``.
    The heading is ``.angle``; ``rotation`` is retired and raises with a hint.
    """

    # Size words this kind lacks refuse on write (``_install_setattr_route``, E13).
    _scena_is_graphic = True

    _pose_xy_guard = True
    _RETIRED_ATTRS = {"rotation": _ROTATION_RETIRED}

    # ``clone(frame=)`` picks a sheet frame (Sprite only; the others refuse it).
    _clone_takes_frame = False
    # ``clone(center=)``: the constructor places a Sprite / Svg / Text copy; a
    # Shape copy is moved there after the geometry copy (``Graphic.clone``).
    _clone_places_center = False

    def __init__(
        self,
        *,
        layer: Any = _USE_LAYER_DEFAULT,
        group: Optional[Union[str, Sequence[str]]] = None,
    ):
        self._construct(layer=layer, group=group)

    def _construct(
        self,
        *,
        layer: Any = _USE_LAYER_DEFAULT,
        group: Optional[Union[str, Sequence[str]]] = None,
        attr_name: Optional[str] = None,
        owner: Optional[Container] = None,
        register: bool = True,
    ):
        Entity._construct(
            self,
            layer=layer,
            group=group,
            attr_name=attr_name,
            owner=owner,
            register=register,
        )
        _pose_rotation_set(self, 0.0)
        _pose_scale_set(self, 1.0)
        object.__setattr__(self, "_flip_x", False)
        object.__setattr__(self, "_flip_y", False)
        # Construct defaults should not leave a dirty collision epoch.
        object.__setattr__(self, "_collision_epoch", 0)
        object.__setattr__(self, "_plain_blit", True)
        # Registration above already appended to a layer and set the index;
        # overwriting it would break the O(1) tombstone and the hit order.
        try:
            object.__getattribute__(self, "_draw_index")
        except AttributeError:
            object.__setattr__(self, "_draw_index", -1)
        self._clickable = False
        self._draggable = False
        self._droppable = False
        self._wheel_rotate = False
        self._resolve_enrolled = False
        self._resolve_enroll_count = 0
        self._on_click = None
        self._on_drag_to = None
        self._on_drag_over = None
        self._on_drop_by = None
        self._on_hover = None
        self._on_hover_exit = None
        self._pointer_hover = False
        self._pointer_pressed = False
        _geom_path_cache_set(self, None, None)
        self._tx_state = None
        object.__setattr__(self, "_mass", 1.0)
        object.__setattr__(self, "_vel", None)
        object.__setattr__(self, "_touching_contacts", ())

    @property
    def mass(self) -> float:
        """Push weight for collision resolution (default ``1.0``). Use ``STATIC`` for immovable."""
        return self._mass

    @mass.setter
    def mass(self, value: float) -> None:
        from .collision import STATIC
        from .validate import number
        mv = STATIC if value == STATIC and type(value) is float else number(value, "mass")
        if mv <= 0.0 and mv != STATIC:
            raise ValueError(f"mass must be positive or STATIC, got {value!r}")
        object.__setattr__(self, "_mass", mv)

    @property
    def vel(self):
        """Velocity for ``bounce=`` resolution. ``None`` until first assigned."""
        return self._vel

    @vel.setter
    def vel(self, value) -> None:
        if value is None:
            object.__setattr__(self, "_vel", None)
            return
        if value is self._vel:
            # ``ship.vel += w`` / ``-= w``: ``Vec2.__iadd__`` already wrote both
            # axes through the guarded field writes and hands the held object
            # back; writing them again is a same-value no-op (~2 µs). Only the
            # finite check is left: a batched ``+=`` write does not run it.
            from .validate import number
            number(value.x, f"{self.name}.vel x")
            number(value.y, f"{self.name}.vel y")
            return
        if callable(value) and not isinstance(value, Vec2):
            raise CallableAssignError(callable_assign_message(self, "vel"))
        if isinstance(value, Vec2):
            raw = (value.x, value.y)
        elif (
            not isinstance(value, (str, bytes))
            and hasattr(value, "__len__") and hasattr(value, "__getitem__")
            and len(value) == 2
        ):
            raw = (value[0], value[1])
        else:
            raise TypeError(
                f"{self.name}.vel expected a 2D velocity, got "
                f"{type(value).__name__} {value!r}. Write vel = (vx, vy) or "
                f"vel = Vec2(vx, vy); vel = None stops physics motion."
            )
        from .validate import number
        from .state import as_payload
        if any(callable(as_payload(c)) for c in raw):
            raise CallableAssignError(callable_assign_message(self, "vel"))
        vx = number(as_payload(raw[0]), f"{self.name}.vel x")
        vy = number(as_payload(raw[1]), f"{self.name}.vel y")
        existing = self._vel
        if existing is None:
            v = Vec2(x=vx, y=vy, owner=self, attr_name=f"{self.name}_vel")
            # The engine writes .vel (bounce=, confine): ``ship.vel @= …`` and
            # ``ship.vel["x"] @= …`` refuse like ``ship["vel"] @= …``.
            object.__setattr__(v, "_link_refused", "vel")
            object.__setattr__(self, "_vel", v)
        else:
            existing.x = vx
            existing.y = vy

    @property
    def touching_sides(self) -> frozenset:
        """Sides of this body currently in contact (``top``/``bottom``/``left``/``right``)."""
        ink = getattr(self, "_ink", None)
        if ink is not None and "touching_sides" in ink:
            return ink["touching_sides"]
        return getattr(self, "_touching_sides", frozenset())

    @property
    def touching_contacts(self):
        """Per-pair contact summaries for every current touch."""
        return self._touching_contacts

    @property
    def hitbox(self):
        """The main :class:`Hitbox`: the collider this Graphic answers with.

        ``hitbox.box`` measures it; ``hitbox.active`` switches it alone. On a
        Sprite its knobs are ``shape`` / ``source`` / ``anchor`` / ``scale``
        (``Sprite(hitbox_shape=…)`` sets them at construction). A Shape's
        hitbox is its own geometry. ``sprite.add_hitbox`` adds extra ones.
        """
        if type(self)._has_no_hitbox:
            raise TypeError(
                f"{type(self).__name__} has no hitbox — it does not collide. "
                "Measure it with .box."
            )
        from .hitbox import _main_hitbox_of
        return _main_hitbox_of(self)

    @hitbox.setter
    def hitbox(self, value) -> None:
        raise TypeError(
            "sprite.hitbox is the main Hitbox, not a setting. Set its knobs: "
            'sprite.hitbox.shape = "rect", sprite.hitbox.scale = 0.8 '
            "(Sprite(hitbox_shape=…) when constructing)."
        )

    # Graphics without a collider (Text) refuse ``.hitbox``.
    _has_no_hitbox = False

    def floor_below(self, *, dx: Any = 0, depth: Any = None, group: Any = None):
        """The floor this body would stand on after stepping ``dx``, or None.

        Uses the hitbox, the solver's floor rule (``"bottom"``, ±45°), and a
        drop deeper than ``depth`` (default: the floor-snap reach) is a fall.
        Ground is what the body ``resolve()``\\ s against, or ``group=``.
        ``dx`` is a signed step (``+`` right). A read: no motion, no enroll.
        """
        from .collision import get_collision_system
        return get_collision_system().floor_below(self, dx=dx, depth=depth, group=group)

    def _channel_linked(self, name: str) -> bool:
        """Is the appearance field / flag ``name`` linked (``@=``)?"""
        anchors = self.__dict__.get("_field_anchors")
        anchor = anchors.get(name) if anchors else None
        return anchor is not None and anchor._link is not None

    def _pull_property_anchor(self, name: str) -> None:
        """Pull a linked property-backed field (``angle`` / ``scale``) on read."""
        anchors = self.__dict__.get("_field_anchors")
        if not anchors:
            return
        anchor = anchors.get(name)
        if anchor is not None:
            anchor._ensure_fresh()

    def _pull_property_anchors(self) -> None:
        """Pull the linked pose (angle / scale, and a flip where the class
        links it) so draw / collision / hit-test see current geometry."""
        anchors = self.__dict__.get("_field_anchors")
        if not anchors:
            return
        for name in type(self)._scena_pose_pull:
            anchor = anchors.get(name)
            if anchor is not None:
                anchor._ensure_fresh()

    def _scalar_anchor_class(self, name: str):
        if name in _PROPERTY_LINK_ANY and name in type(self)._scena_property_links:
            return _PROPERTY_LINK_ANCHORS.get(name, _PropertyAnchor)
        return super()._scalar_anchor_class(name)

    def _linkable_source(self, name: str):
        # An appearance field or flag is a link target only: as a source no
        # writer would dirty it (Reactive Design — Appearance links).
        if name in type(self)._scena_target_only:
            raise TypeError(
                f"{self.name}['{name}'] cannot be the source of a link: it is a "
                f"link target only. Link both fields to the same formula, e.g. "
                f"other['{name}'] @= lambda: … (the formula {self.name}['{name}'] follows)"
            )
        return super()._linkable_source(name)

    def _resolve_field(self, key: str):
        if key == "touching_sides":
            return _INK_SLOT
        if key in _PROPERTY_LINK_ANY and key in type(self)._scena_property_links:
            return _INK_SLOT              # reuse the existing "ink-shaped" dispatch branch
        return super()._resolve_field(key)

    def _write_field(self, name: str, value) -> None:
        # Property-backed ``angle`` / ``scale`` resolve to the ink-shaped
        # slot for linking, but their value lives behind the real property
        # (rotate_to / scale_to side effects). A write — e.g. a tween on
        # ``shape["angle"]`` — goes through the setter, like
        # ``_PropertyAnchor._takein`` does; the ink path would crash (no ink
        # dict) or store a dead ink value the pose never reads.
        if name in _PROPERTY_LINK_ANY and name in type(self)._scena_property_links:
            anchors = self.__dict__.get("_field_anchors")
            anchor = anchors.get(name) if anchors else None
            if anchor is not None and anchor._link is not None:
                raise LinkedAttributeError(
                    f"{self.name}.{name} is linked — call {self.name}['{name}'].unlink() first"
                )
            if isinstance(value, Attribute):
                value = value.value
            if name == "line_width":
                # A tween / act restore writes a size as a formula does:
                # an overshoot below zero reads 0 (Scena Design — Numbers).
                from .validate import clamp_magnitude
                if not isinstance(value, bool) and isinstance(value, (int, float)):
                    value = clamp_magnitude(value)
            setattr(self, name, value)
            return
        super()._write_field(name, value)

    def _link_field(self, name: str, source) -> None:
        from .state import _refuse_link_on_dead
        _refuse_link_on_dead(self, f"{name} @=")   # also covers property anchors (W2)
        if name == "touching_sides":    # a source (``_resolve_field``), never a target
            raise AttributeError(_ink_link_forbidden_message(self, name))
        if name in _PROPERTY_LINK_ANY and name in type(self)._scena_property_links:
            channel = name in type(self)._scena_target_only
            if channel:
                self._refuse_channel_link_conflict(name)
                if name in _POSE_PULL_FLIPS:
                    self._refuse_flip_link_conflict(name)
                elif name == "visible":
                    from .transients import visibility_verb_running
                    verb = visibility_verb_running(self)
                    if verb is not None:
                        from .state import driver_conflict_message
                        raise LinkedAttributeError(driver_conflict_message(
                            new="link", subject=entity_label(self), part="visible",
                            existing=f"{verb}() shows or hides it when it ends",
                            undo="Link it after the effect ends (on_done=), or "
                                 "clear_transients() first"))
            anchors = self.__dict__.get("_field_anchors")
            had_anchor = bool(anchors) and name in anchors
            anchor = self._ensure_scalar_anchor(name, anchor_cls=self._scalar_anchor_class(name))
            try:
                anchor._assign_formula(source)
            except BaseException:
                # A refused link (wheel_rotate, a raising formula) installs
                # nothing: drop the anchor this call made (W3; GX11).
                if not had_anchor:
                    self._drop_scalar_anchor(name)
                raise
            if channel:
                object.__setattr__(self, "_alinks", True)      # sticky (PaintState slot)
                _LINKED_CHANNEL_HOSTS.add(self)
            return
        super()._link_field(name, source)

    def _flip_written_parts(self, axis: str) -> list:
        """What a flip on ``axis`` writes besides its flag: the heading
        (``rotate_to``) on a Sprite / Text. Shapes add the parts the mirror
        moves. Link-time checks read it, both orders (never the first write)."""
        if "angle" in type(self)._scena_property_links:
            return [self["angle"]]
        return []

    def _flip_link_refusal(self, flip: str, part, *, linking_flip: bool):
        from .state import driver_conflict_message, FieldRef
        label = str(part.name) if isinstance(part, FieldRef) else part_path(part, self)
        if linking_flip:
            msg = driver_conflict_message(
                new="link", subject=entity_label(self), part=flip,
                existing=f"its {label} has an @= formula, and a flip rewrites it",
                undo=f"Unlink {label} first, or leave {flip} unlinked")
        else:
            msg = driver_conflict_message(
                new="link", subject=entity_label(self), part=label,
                existing=f"its {flip} has an @= formula and mirrors it",
                undo=f"Unlink {self.name}['{flip}'] first, or leave {label} unlinked")
        return LinkedAttributeError(msg)

    def _refuse_flip_link_conflict(self, name: str) -> None:
        """Linking ``flip_x`` / ``flip_y``: the parts the flip writes must be
        free, and so must the whole object (``obj @= other`` drives the pose)."""
        if self._link is not None:
            raise self._flip_link_refusal(name, self, linking_flip=True)
        from .state import FieldRef
        for part in self._flip_written_parts(name[-1]):
            if _part_is_linked(part):
                raise self._flip_link_refusal(name, part, linking_flip=True)

    def _refuse_link_under_flip(self, target) -> None:
        """The other order: a link on a part a linked flip writes (or on the
        whole object) refuses (``_ensure_can_link_attribute``)."""
        anchors = self.__dict__.get("_field_anchors")
        if not anchors:
            return
        for flip in ("flip_x", "flip_y"):
            anchor = anchors.get(flip)
            if anchor is None or anchor._link is None or target is anchor:
                continue
            if target is self:
                raise self._flip_link_refusal(flip, self, linking_flip=False)
            from .shapes import _link_overlaps_part
            for part in self._flip_written_parts(flip[-1]):
                if _link_overlaps_part(target, part):
                    raise self._flip_link_refusal(flip, part, linking_flip=False)

    def _ensure_can_link_attribute(self, target) -> None:
        self._refuse_link_under_flip(target)

    def _refuse_channel_link_conflict(self, name: str) -> None:
        """Two links on one paint package refuse at link time, in either order
        (``color`` writes ``fill`` and ``line`` on a shape): never left to the
        first write (Reactive Design — Appearance links)."""
        fields = getattr(type(self), "_paint_fields", None)
        if not fields:
            return
        for other in fields.get(name, ()):
            if other != name and self._channel_linked(other):
                from .state import driver_conflict_message
                raise LinkedAttributeError(driver_conflict_message(
                    new="link", subject=entity_label(self), part=name,
                    existing=f"its {other} has an @= formula, and {name} writes "
                             f"the same paint",
                    undo=f"Link one of them, or unlink {self.name}['{other}'] first",
                ))

    def _ensure_touching_sides_storage(self) -> None:
        ink = getattr(self, "_ink", None)
        if ink is None:
            ink = {}
            object.__setattr__(self, "_ink", ink)
        if "touching_sides" not in ink:
            ink["touching_sides"] = getattr(self, "_touching_sides", frozenset())

    def _collision_set_touching(self, sides: frozenset, contacts) -> None:
        self._ensure_touching_sides_storage()
        anchors = self.__dict__.get("_field_anchors")
        if anchors and "touching_sides" in anchors:
            self._write_field("touching_sides", sides)
        else:
            ink = self._ink
            if ink.get("touching_sides") != sides:
                ink["touching_sides"] = sides
        object.__setattr__(self, "_touching_contacts", contacts)

    def resolve_now(self, target, bounce: Optional[float] = None):
        """Detect overlaps with ``target`` now and resolve each hit. Returns ``CollisionInfo`` list."""
        from .collision import (
            ANYTHING,
            CollisionInfo,
            _PHASE_STAY,
            _refuse_part_resolve_side,
            ensure_collider,
            get_collision_system,
        )
        sys = get_collision_system()
        # Same rule as ``resolve()``: a hitbox part (or its group) only detects.
        for side in (target if isinstance(target, (list, tuple)) else (target,)):
            _refuse_part_resolve_side(sys, side)
        if _parked(self):
            return []          # out of collision while parked; nothing is built (E2)
        ensure_collider(self)
        ca = self._collider
        if isinstance(target, (list, tuple)):
            seen: set = set()
            rights = []
            for g in target:
                for c in sys._resolve_now_colliders(g):
                    cid = id(c)
                    if cid not in seen:
                        seen.add(cid)
                        rights.append(c)
        elif target is ANYTHING:
            rights = [c for c in sys._colliders if c._part is None]
        elif isinstance(target, str):
            rights = sys._resolve_now_colliders(target)
        else:
            rights = sys._colliders_for_target(target)
        # Hitbox parts never push (``ANYTHING`` is bodies; own parts skipped).
        rights = [c for c in rights if c._part is None]
        hits = []
        for cb in rights:
            if cb is ca:
                continue
            info = sys._collision_info_for_colliders(ca, cb)
            if info is None:
                continue
            oriented = sys._oriented_info(ca, cb, ca, info, _PHASE_STAY)
            oriented.resolve(bounce=bounce)
            hits.append(oriented)
        return hits

    def _refresh_plain_blit(self) -> None:
        """Sticky textured-quad flag: no visual, no stamps, no filters, no transients."""
        if getattr(self, "_visual", None) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_glow", None) is not None or getattr(self, "_shadow", None) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        if (getattr(self, "_hue", None) is not None or getattr(self, "_gray", None) is not None
                or getattr(self, "_tail", None) is not None):
            object.__setattr__(self, "_plain_blit", False)
            return
        if getattr(self, "_fill_filter", None) is not None or getattr(
            self, "_line_filter", None
        ) is not None:
            object.__setattr__(self, "_plain_blit", False)
            return
        st = getattr(self, "_tx_state", None)
        if st is not None and st.any_active():
            object.__setattr__(self, "_plain_blit", False)
            return
        object.__setattr__(self, "_plain_blit", True)

    def _geometry_draw(
        self,
        skia_canvas: skia.Canvas,
        fill_paint=_STYLE_PAINT,
        stroke_paint=_STYLE_PAINT,
    ) -> None:
        raise NotImplementedError(f"{type(self).__name__} must implement _geometry_draw")

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> "Graphic":
        raise NotImplementedError(f"{type(self).__name__} must implement _move_by")

    def _move_to(self, x: float, y: float, *, force: bool = False) -> "Graphic":
        raise NotImplementedError(f"{type(self).__name__} must implement _move_to")

    @property
    def rest_heading(self) -> float:
        """Heading at rest for this body (``0`` for Shape; Sprite overrides)."""
        return 0.0

    def _rotation_value(self) -> float:
        """The heading, for engine readers (Shapes override: Defining inputs only)."""
        return float(self.angle)

    def _init_heading(self, angle) -> None:
        """Constructor ``angle=`` on a pose-only kind (Sprite, Svg, Text): the
        heading at construction. A function links it, like ``x["angle"] @= …``;
        a number sets it, like ``x.angle = …`` (these kinds are placed by their
        center, so the heading turns about it)."""
        if isinstance(angle, Attribute):
            angle = angle.value
        if callable(angle) and not isinstance(angle, type):
            self._link_field("angle", angle)
            return
        from .validate import number
        self.angle = number(angle, f"{type(self).__name__} angle")

    def reset_rotation(
        self,
        *,
        time: Optional[float] = None,
        speed: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        about=None,
        force: bool = False,
    ) -> "Graphic":
        """``rotate_to(rest_heading)`` — untilt without clearing flip.

        ``speed=`` (degrees per second) instead of ``time=``, as on ``rotate_to``.
        No ``loops=`` / ``yoyo=``: a single fixed destination has nothing to bounce toward.
        """
        return self.rotate_to(
            self.rest_heading,
            time=time,
            speed=speed,
            ease=ease,
            then=then,
            on_done=on_done,
            about=about,
            force=force,
        )

    @property
    def box(self):
        """Fresh measuring ``Box`` from this Graphic's frame, if it has one."""
        from .box import box_from_graphic
        return box_from_graphic(self)

    @property
    def flip_x(self) -> bool:
        """Mirror left-right about ``center``: a stored flag (setting the same
        value again changes nothing)."""
        if self._alinks:
            self._pull_property_anchor("flip_x")
        return bool(getattr(self, "_flip_x", False))

    @flip_x.setter
    def flip_x(self, value) -> None:
        value = expect_bool(value, f"{type(self).__name__}.flip_x")
        if self._alinks:
            _refuse_linked_channel(self, ("flip_x",), "set flip_x on")
        self._apply_flip("x", value)

    @property
    def flip_y(self) -> bool:
        """Mirror up-down about ``center``: a stored flag (setting the same
        value again changes nothing)."""
        if self._alinks:
            self._pull_property_anchor("flip_y")
        return bool(getattr(self, "_flip_y", False))

    @flip_y.setter
    def flip_y(self, value) -> None:
        value = expect_bool(value, f"{type(self).__name__}.flip_y")
        if self._alinks:
            _refuse_linked_channel(self, ("flip_y",), "set flip_y on")
        self._apply_flip("y", value)

    def _apply_flip(self, axis: str, value, *, force: bool = False) -> None:
        """Sprite / Text default: toggle the flag and mirror the heading.

        Shapes override this and rewrite geometry so read-backs stay true.
        """
        value = bool(value)
        flag = "_flip_x" if axis == "x" else "_flip_y"
        if value == bool(getattr(self, flag, False)):
            return
        _refuse_if_destroyed(self, f"flip_{axis}")
        rot = float(self._rotation)
        new = 180.0 - rot if axis == "x" else -rot
        # A flip is a pose write; the heading is gated only when it changes.
        _gate_pose_anchor(self, "angle" if new != rot else None, "flip", force)
        object.__setattr__(self, flag, value)
        bump_pose_rev(self)
        try:
            self.rotate_to(new, force=force)
        except BaseException:
            object.__setattr__(self, flag, not value)       # check, then write (SA5)
            raise

    @property
    def is_collapsed(self) -> bool:
        """True when body extent has no interior.

        Default ``False`` (Point, Text, Track, free Polygon). Subclasses with
        width/height/radius/length override. Not ``fill`` / ``visible`` /
        ``is_alive``. Scale ``0`` is collapsed.
        """
        return float(getattr(self, "_scale", 1.0)) == 0.0

    def confine(
        self,
        region,
        *,
        by: str = "center",
        action: str = "clamp",
    ) -> frozenset:
        """Keep this graphic inside ``region`` (a Box or frame-like Graphic).

        Stateless math helper — call after your own ``move_by``. Does not
        register, does not run later in the frame, and does not arbitrate
        against tweens / ``move_along`` / ``resolve``.

        ``by``: ``"center"`` (default), ``"box"`` (own frame stays inside),
        or ``"overlap"`` (act only once own frame has fully left).
        ``action``: ``"clamp"`` (default), ``"bounce"`` (needs ``self.vel``),
        or ``"wrap"``.

        Returns the frozenset of region-local edges acted on this call
        (``left`` / ``right`` / ``top`` / ``bottom``), or empty if none.
        """
        from .confine import confine_graphic
        return confine_graphic(self, region, by=by, action=action)

    def _takein_impl(self, other) -> None:
        """``a << b`` copies a Shape (Shapes Design, C7). A Graphic with no copy
        of its own (Sprite, Svg, Text) refuses with the fix; it used to leak
        Python's NotImplementedError (GX9 in Testing Design)."""
        kind = type(self).__name__
        raise TypeError(
            f"{kind} << …: a {kind} does not take in another actor. Make a copy "
            f"with other.clone(), or place this one: {self.name}.center = other.center"
        )

    def clone(
        self,
        *,
        center=None,
        scale: float = 1.0,
        layer: Any = _USE_LAYER_DEFAULT,
        group: Any = _COPY_GROUPS,
        frame: Optional[Union[int, str]] = None,
    ) -> "Graphic":
        """Return a new actor that looks like this one (new registry identity).

        Construction + ``setup()`` always run, then ``look_like`` snapshots the
        source's current appearance. ``mode``, timers, ink, and playhead start
        clean. ``visual`` is shared by reference (interned looks batch).

        ``layer`` is placement, not a copy: omit → class constructor default
        (Sprite / Circle → ``canvas.layers.default``; Point stays undrawn).
        Explicit ``layer=None`` → undrawn. ``layer=<int>`` → numeric position
        (auto-created, frozen z). ``group`` omitted copies the source;
        passing ``group=`` replaces membership (not a merge).
        """
        # Every check before the copy exists: a bad scale used to raise after
        # the clone was built and registered, and a destroyed source cloned (E9).
        _refuse_if_destroyed(self, "clone")
        if scale.__class__ is not float or scale != 1.0:
            # Every value, ``True`` too (``True != 1.0`` is False, so it used
            # to skip the check): a scale is a non-negative number (S5-6).
            from .validate import number
            scale = number(scale, "clone(scale=)")
            if scale < 0.0:
                raise ValueError(f"clone(scale=) is a magnitude: got {scale:g} (>= 0)")
        if frame is not None and not type(self)._clone_takes_frame:
            # Only a Sprite has sheet frames; the others ignored frame= (PC1).
            kind = type(self).__name__
            raise TypeError(
                f"{kind}.clone(frame=): a {kind} has no frames to pick (frame= "
                f"chooses a Sprite's sheet frame). Leave it out.")
        place = None
        if center is not None and type(self)._clone_places_center:
            # A Shape's recipe copies the geometry where it is; ``center=`` then
            # moves the copy (PC1: it was ignored). Read now, before the copy
            # exists, so a bad point builds nothing.
            place = self._clone_center_xy(center)
            center = None
        kwargs: Dict[str, Any] = {}
        if layer is not _USE_LAYER_DEFAULT:
            kwargs["layer"] = layer
        if group is _COPY_GROUPS:
            # Groups a hitbox part answers for come back through ``setup()``'s
            # ``add_hitbox``; copying them would let the clone's body answer.
            claims = getattr(self, "_hitbox_claims", None) or ()
            groups = tuple(g for g in self.group if g not in claims)
            if groups:
                kwargs["group"] = groups
        else:
            kwargs["group"] = group
        if self.__dict__.get("_field_anchors"):
            # The copy is a snapshot of this frame's values: pull the pose
            # (a linked flip) and the appearance links before the recipe reads
            # them raw. The copy has no links (Shapes Design — A copy has no links).
            from .state import _pull_channel_links
            self._pull_property_anchors()
            _pull_channel_links(self, type(self)._scena_target_only)
        _PENDING_CLONE_SOURCES.append(self)
        mark = len(_PENDING_CLONE_SOURCES)
        try:
            copy = self._clone_recipe(center=center, frame=frame, **kwargs)
        finally:
            # Not consumed (the recipe built nothing top-level): drop it so a
            # later, unrelated construction does not read as a clone.
            if len(_PENDING_CLONE_SOURCES) == mark and _PENDING_CLONE_SOURCES[-1] is self:
                _PENDING_CLONE_SOURCES.pop()
        look_like = getattr(copy, "look_like", None)
        if callable(look_like):
            look_like(self)
        copy._clone_pose_from(self)
        from .shapes import Point
        if isinstance(self, Point) and isinstance(copy, Point):
            copy._marker_style_auto = getattr(self, "_marker_style_auto", True)
        # A parked source reads hidden; the copy takes what it will show on
        # resume (E9: a clone of a parked actor was invisible).
        saved = getattr(self, "_active_saved_visible", None) if _parked(self) else None
        copy.visible = self._visible if saved is None else bool(saved)
        if place is not None or scale != 1.0:
            try:
                if place is not None:
                    copy.move_to(*place)
                if scale != 1.0:
                    copy.scale_by(float(scale))
            except BaseException:
                # A scale the copy's sizes cannot take (``1e308`` overflows):
                # the copy leaves, nothing half-built stays (review S5-6, E9).
                copy.destroy()
                raise
        return copy

    def _clone_pose_from(self, source: "Graphic") -> None:
        """Take ``source``'s pose on its fresh copy, before ``clone(scale=)`` multiplies.

        Default (Sprite / Svg / Text): the recipe placed the copy at the
        source's point with its flips; ``angle`` and ``scale`` are pose
        stores, copied as they are, so the copy is drawn where the source is.
        Shape overrides (its geometry already carries the pose).
        """
        for flag in ("_flip_x", "_flip_y"):
            object.__setattr__(self, flag, bool(getattr(source, flag, False)))
        bump_pose_rev(self)
        # The heading as read (a Defining ``angle`` may be ahead of the pose store).
        _pose_rotation_set(self, float(source._rotation_value()))
        _pose_scale_set(self, float(source._scale))

    def _clone_center_xy(self, center) -> Tuple[float, float]:
        """``clone(center=)`` for a kind that moves its copy: one point, read now
        (Point, Vec2, ``(x, y)``, a Graphic's center, mouse, a state cell)."""
        kind = type(self).__name__
        if callable(center) and not isinstance(center, type):
            raise TypeError(
                f"{kind}.clone(center=) takes a point to put the copy at, read "
                f"now, not a function. To make the copy follow something, link "
                f"it after the clone: copy.center @= lambda: ….")
        from .shapes import _read_xy
        xy = _read_xy(center)
        if xy is None:
            raise TypeError(
                f"{kind}.clone(center=) expected a point — (x, y), a Point, a "
                f"Vec2 or an actor — got {type(center).__name__} {center!r:.60}.")
        return xy

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "Graphic":
        """Construct the free copy. Shape uses ``_clone_geometry``; Sprite overrides."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement _clone_recipe for clone()"
        )
