"""Registry citizens: Entity identity/process host and Graphic draw ABC.

``Shape`` / ``Sprite`` inherit ``Graphic``; ``SpatialFx`` inherits ``Entity``.
Pose / pointer / transient implementations stay on ``Shape`` and are published
onto ``Graphic`` via ``shapes._publish_graphic_api()``.
"""
from __future__ import annotations

import math
import os
import re
import traceback
import warnings
from abc import ABC
from collections.abc import Sequence
from functools import wraps
import inspect
from typing import Any, Dict, Optional, Tuple, Union

import skia

from ._defaults import Unset
from .closed import transposed as _transposed
from ._pkg import is_framework_module
from .state import (
    Attribute, CallableAssignError, Container, DestroyedError, LinkedAttributeError,
    _INK_SLOT, _FlagPropertyAnchor, _PropertyAnchor,
    callable_assign_message,
)
from .scenamath import Vec2
from .validate import expect_bool
from .validate import expect_bool as _expect_flag

# Names that stay real properties / instance fields (never ink Attributes).
# Some names (``width``, ``height``, …) are also ScalarSlots on specific types —
# those remain linkable via ``obj["width"] @=`` when ``_resolve_field`` finds a slot.
# Graphic ``angle`` (the heading) / ``scale`` are property-backed (via
# ``_PropertyAnchor``) unless the subclass declares a real ScalarSlot of the
# same name (Rect / Ellipse / Square / RegularPolygon / EquilateralTriangle /
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
    "vel": (
        "The engine writes it (`resolve(..., bounce=)`, `confine(action=\"bounce\")`), "
        "and so does `vel.y -= g * dt`. Set it where it changes: "
        "`ship.vel = vec_from_angle(st.a * 30, 10)` in `on_update`."
    ),
}


_PROPERTY_LINK_FIELDS = frozenset({"angle", "scale"})
# Every name some class may declare linkable through ``_property_link_extra``
# (a property + ``@=``); the cheap pre-check before the per-class lookup.
_PROPERTY_LINK_ANY = _PROPERTY_LINK_FIELDS | frozenset({"enabled"})
_PROPERTY_LINK_BY_CLASS: Dict[type, frozenset] = {}


def _property_link_names(obj) -> frozenset:
    """The property-backed linkable fields of this class, cached per class.

    ``_PROPERTY_LINK_FIELDS`` not backed by a real slot (``angle`` is a slot on
    Rect / Line / Circle, a property on Sprite / Point — and ``x["angle"]`` is
    on the per-frame path), plus the class's own ``_property_link_extra``
    (``SpriteButton.enabled``; names listed in ``_PROPERTY_LINK_ANY``)."""
    cls = type(obj)
    names = _PROPERTY_LINK_BY_CLASS.get(cls)
    if names is None:
        slots = obj._field_slots()
        names = frozenset(n for n in _PROPERTY_LINK_FIELDS if n not in slots)
        names |= frozenset(getattr(cls, "_property_link_extra", ()) or ())
        _PROPERTY_LINK_BY_CLASS[cls] = names
    return names

# The heading used to be ``rotation`` on Graphics; it is ``angle`` now
# (Shapes Design — Geometry contract). A write must not become ink.
_ROTATION_RETIRED = (
    "A Graphic's heading is `angle`, not `rotation`. `x.angle = 30` keeps the "
    "point it was placed by (its center, top_left, p1, a vertex…); "
    "`x.rotate_to(30)` / `x.rotate_by(30)` turn the whole shape about its "
    "center (or `about=`). Link with `x['angle'] @= …`."
)


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


def _ink_link_forbidden_message(owner: "Entity", field: str) -> str:
    """Beginner-facing error when ``@=`` targets a built-in / paint property."""
    kind = type(owner).__name__
    hint = _INK_LINK_FORBIDDEN_HINTS.get(field)
    if hint is None:
        hint = f"Use plain assignment: `{field} = …`."
    drive = (
        "To drive looks from game state, use `on_update`, `@on_change`, or `@when`; "
        "link custom ink (`ship.hp`) or geometry (`ship.center.x`, `rect.width`, …)."
    )
    return (
        f"{kind}.{field} cannot be linked with @= — appearance and built-in "
        f"properties stay outside the reactive graph. {hint} {drive}"
    )

# Geometry leaf types: bracket typos stay AttributeError (no ink auto-materialize).
# Exact type on purpose: an author subclass (``class Laser(Line)``) is where
# new ink fields live, so only the bare Scena kinds refuse unknown keys.
_GEOMETRY_INK_STRICT = frozenset({"Point", "Line", "Vec2"})

# Per-class setattr routing (built in ``__init_subclass__``). Values are either a
# data descriptor (``__set__``) or ``_SET_OBJECT`` for reserved plain fields.
_SET_OBJECT = object()
_LOOK_MISSING = object()
_SETATTR_ROUTE: Dict[type, Dict[str, Any]] = {}


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
    if isinstance(group, str):
        return GroupTags((group,))
    if isinstance(group, (Sequence, set, frozenset)) and all(isinstance(x, str) for x in group):
        return GroupTags(group)
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
_INK_NEAR_MISS: Dict[Tuple[type, str], Optional[str]] = {}


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


_RETIRED_BY_CLASS: Dict[type, dict] = {}


def _retired_attr_message(owner, name: str):
    """The hint for a public name this class retired, or ``None``.

    A class lists them in ``_RETIRED_ATTRS`` (name → message); a subclass's
    own list adds to its bases'. Without this an old spelling
    (``sprite.hitbox_scale = 0.5``, ``ship.rotation = 90``) would silently
    become ink.
    """
    cls = type(owner)
    merged = _RETIRED_BY_CLASS.get(cls)
    if merged is None:
        merged = {}
        for klass in reversed(cls.__mro__):
            merged.update(klass.__dict__.get("_RETIRED_ATTRS") or {})
        _RETIRED_BY_CLASS[cls] = merged
    return merged.get(name) if merged else None


def _look_missing_message(owner, name: str) -> str:
    kind = type(owner).__name__
    hint = _INK_LINK_FORBIDDEN_HINTS.get(name, "")
    return (
        f"{kind} has no {name!r} — that look property belongs to other actor "
        f"kinds, so the write would do nothing. {hint}".rstrip()
    )


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


def _ink_near_miss_message(cls: type, name: str, known) -> Optional[str]:
    who = cls.__name__
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


def _check_ink_near_miss(cls: type, name: str, route_map) -> None:
    """Raise when a new ink name is a near-miss of a real property (typo guard).

    Cached per ``(class, name)``: the check runs once per new ink name, never
    on later writes of an existing ink field.
    """
    key = (cls, name)
    try:
        msg = _INK_NEAR_MISS[key]
    except KeyError:
        msg = _ink_near_miss_message(cls, name, route_map)
        _INK_NEAR_MISS[key] = msg
    if msg is not None:
        raise AttributeError(msg)


def _install_setattr_route(cls: type) -> None:
    """Cache known public setters so pose writes skip a per-assign MRO walk."""
    route: Dict[str, Any] = {}
    for base in cls.__mro__:
        for name, desc in base.__dict__.items():
            if not name or name[0] == "_" or name in route:
                continue
            if hasattr(desc, "__set__"):
                route[name] = desc
    for name in _LOOK_FAMILY:
        route.setdefault(name, _LOOK_MISSING)
    for name in _INK_RESERVED:
        route.setdefault(name, _SET_OBJECT)
    # ``__slots__`` members (Shape.group) are descriptors too; group needs the registry sync.
    route["group"] = _SET_OBJECT
    _SETATTR_ROUTE[cls] = route
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
        old = getattr(obj, "_rotation", None)      # a class default until first written
    if old is not None and old == value:
        return
    anchors = d.get("_field_anchors")
    if anchors:
        _refuse_linked_pose(obj, anchors, "angle", "rotate")
    object.__setattr__(obj, "_rotation", value)
    _bump_collision_epoch(obj)
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
        old = getattr(obj, "_scale", None)         # a class default until first written
    if old is not None and old == value:
        return
    anchors = d.get("_field_anchors")
    if anchors:
        _refuse_linked_pose(obj, anchors, "scale", "scale")
    object.__setattr__(obj, "_scale", value)
    _bump_collision_epoch(obj)
    if anchors:
        _mark_anchor_dirty(anchors, "scale")


def _bump_collision_epoch(obj) -> None:
    """Invalidate collision snapshot cache for this Graphic / Entity."""
    try:
        object.__setattr__(
            obj, "_collision_epoch", int(getattr(obj, "_collision_epoch", 0)) + 1
        )
    except Exception:
        pass


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
    """Freeze hook + decorator discovery so construct does not walk the MRO."""
    cls._scena_actor_hooks = {name: _lookup_actor_hook(cls, name) for name in _HOOK_LOOKUP_NAMES}
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


def _frame_outside_scena():
    """Nearest stack frame that is not Scena itself (the author's call)."""
    prefix = _SCENA_PKG + os.sep
    for frame in reversed(traceback.extract_stack()):
        fn = frame.filename
        if not fn:
            continue
        if fn.startswith("<"):
            if fn in ("<string>", "<stdin>"):
                return frame
            continue
        absfn = os.path.abspath(fn)
        if absfn == _SCENA_PKG or absfn.startswith(prefix):
            continue
        return frame
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
        cur = getattr(cur, "_owner", None)
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
    actor = _actor_of(obj) or obj
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


def _keep_collide_callbacks(item, col) -> None:
    """Copy ``col``'s callbacks onto the actor before ``col`` is dropped (E1).

    The Collider may hold callbacks the actor's store lacks (an author who set
    them on a bound ``Collider([shape])``), so the Collider's view wins."""
    cbs = {n: getattr(col, n) for n in _COLLIDE_HOOKS if getattr(col, n, None) is not None}
    object.__setattr__(item, "_collide_cbs", cbs or None)


def _wants_collision(item) -> bool:
    """Collidable now, or stashed to be collidable on resume."""
    if getattr(item, "_collidable", False) or getattr(item, "_collider", None) is not None:
        return True
    return _parked(item) and bool(getattr(item, "_active_saved_collidable", False))


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
    kind = _SCENA_KIND_CACHE.get(cls)
    if kind is None:
        kind = cls.__name__
        for k in cls.__mro__:
            mod = getattr(k, "__module__", "") or ""
            if is_framework_module(mod):
                kind = k.__name__
                break
        _SCENA_KIND_CACHE[cls] = kind
    return kind


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
    from .process import _invoke
    _invoke(hook, item)


def _install_subclass_hooks(item) -> None:
    cls = type(item)
    for name in _ACTOR_HOOK_NAMES:
        hook = _find_actor_hook(cls, name)
        if hook is None:
            continue
        bound = hook.__get__(item, cls)
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
    """
    if getattr(item, "_actor_constructed", False):
        return
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
                _finish_actor_construct(self)
            except BaseException:
                # The finish step (setup, method timers, watches, enroll) is
                # part of construction: a raise rolls back like one in __init__ (E4).
                from .place import _drop_failed_construct
                _drop_failed_construct(self)
                raise

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
    # A whole-object link (``obj @= other``) drives the pose too (a copy carries
    # it, C7); Point overrides: its link follows position only.
    _whole_link_carries_pose = True
    # ``on_collide*`` callbacks the actor keeps while it has no Collider (park,
    # ``collidable = False``); ``ensure_collider`` copies them into a new one.
    _collide_cbs = None

    def __init_subclass__(cls, **kwargs):
        # One hook only: a second ``__init_subclass__`` in this class body would
        # silently replace this one (routes, actor finish, deferred specs lost).
        super().__init_subclass__(**kwargs)
        _adopt_mixin_init(cls)         # a mixin's __init__ becomes this class's own
        _wrap_construct_rollback(cls)  # inner: undo registration on raise
        _wrap_actor_init(cls)          # outer: setup() / watches after __init__
        _install_setattr_route(cls)
        _claim_deferred_every_specs(cls)
        _claim_deferred_after_specs(cls)
        _cache_actor_lookups(cls)

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
            _finish_actor_construct(self)

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
        route_map = getattr(type(self), "_setattr_route", None)
        if route_map is None:
            _install_setattr_route(type(self))
            route_map = type(self)._setattr_route  # type: ignore[attr-defined]
        route = route_map.get(name)
        if callable(value) and not isinstance(value, type):
            if (
                name in _PROPERTY_LINK_ANY
                and isinstance(self, Graphic)
                and name in _property_link_names(self)
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
            return
        # Unknown public name → ink (lazy bag of bare scalars).
        try:
            object.__getattribute__(self, name)
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
            _check_ink_near_miss(type(self), name, route_map)
            ink = {}
            object.__setattr__(self, "_ink", ink)
        elif name in ink:
            self._write_field(name, value)
            return
        else:
            _check_ink_near_miss(type(self), name, route_map)
        ink[name] = value

    # Private names go straight to object.__setattr__ (state._container_dict_init).
    __setattr__._scena_private_passthrough = True

    def __getattr__(self, name: str):
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
        if type(self).__name__ in _GEOMETRY_INK_STRICT:  # exact-type: subclasses add their own ink
            self._resolve_field(key)
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
        if type(self).__name__ in _GEOMETRY_INK_STRICT:  # exact-type: subclasses add their own ink
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
        if not self.is_alive:
            return self
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
        v = float(value)
        if not math.isfinite(v):
            raise ValueError(f"time_scale must be finite, got {v}")
        if v < 0.0:
            raise ValueError(f"time_scale must be >= 0, got {v}")
        self._time_scale = v

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
        # then stash the author's values and mark parked.
        if vis is not None:
            self.visible = False
        if col:
            self._leave_collision()       # not ``collidable = False``: no opt-out (E2)
        object.__setattr__(self, "_active_saved_visible", vis)
        object.__setattr__(self, "_active_saved_collidable", col)
        object.__setattr__(self, "_active", False)

    def _resume_self(self) -> None:
        """Resume this item alone: restore stashed flags it owns."""
        object.__setattr__(self, "_active", True)
        saved_vis = getattr(self, "_active_saved_visible", True)
        saved_col = getattr(self, "_active_saved_collidable", False)
        object.__setattr__(self, "_active_saved_visible", None)
        object.__setattr__(self, "_active_saved_collidable", None)
        if saved_vis is not None:
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
        if value == self._mode:
            return
        self._goto_mode(value)

    def goto_mode(self, fn) -> None:
        """Always exit, then enter the mode ``fn`` — even when ``fn`` is the
        current mode (a restart). ``e.mode = fn`` does nothing when ``fn`` is
        already running."""
        self._validate_mode_value(fn)
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
            try:
                _invoke(exit_fn, self)  # no owning() context: entity-scoped by default
            except Exception:
                # Finish the transition (never leave a cancelled, frozen old
                # mode), then re-raise. An error entering the new mode chains
                # onto this one.
                self._enter_mode(value)
                raise
        self._enter_mode(value)

    def _enter_mode(self, value) -> None:
        from .process import (
            _invoke, _is_async_callable, _spawn_coro, get_scheduler, owning, SCOPE_MODE,
        )
        sched = get_scheduler()
        object.__setattr__(self, "_mode", value)
        object.__setattr__(self, "_mode_time", 0.0)
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
    _rotate_depth += 1
    try:
        out = fn(shape, value, **kwargs)
    finally:
        _rotate_depth -= 1
    x1, y1 = _collision_pose_xy(shape)
    dx = x1 - x0
    dy = y1 - y0
    if dx * dx + dy * dy > _ORBIT_EPS2:
        note_collider_motion(shape, dx, dy)
    return out


def _rotate_as_placement(fn, *args, **kwargs):
    """Run a placement turn: the ``rotate_by`` inside it notes no orbit motion."""
    global _rotate_depth
    _rotate_depth += 1
    try:
        return fn(*args, **kwargs)
    finally:
        _rotate_depth -= 1


def _install_timed_pose(cls) -> None:
    """Add ``time=`` / ``ease=`` / ``then=`` / ``on_done=`` / ``loops=`` / ``yoyo=`` to subclass pose overrides."""
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

            @wraps(orig_fn)
            def wrapped(
                self, value, *, time=None, ease="linear", then=None, on_done=None,
                loops=1, yoyo=False, **kwargs,
            ):
                # Instant path is the per-frame hot path (angle= / scale=).
                # Do not import process or validate completion kwargs unless used.
                if time is None:
                    if then is not None or on_done is not None:
                        from .process import _require_timed_completion
                        _require_timed_completion(
                            time=time, then=then, on_done=on_done, call_name=name,
                        )
                    if loops != 1 or yoyo:
                        from .process import _require_loop_kwargs
                        _require_loop_kwargs(
                            loops=loops, yoyo=yoyo, time=time, call_name=name,
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

    _pose_xy_guard = True
    _RETIRED_ATTRS = {"rotation": _ROTATION_RETIRED}

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
        mv = float(value)
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

    def _pull_property_anchor(self, name: str) -> None:
        """Pull a linked property-backed field (``angle`` / ``scale``) on read."""
        anchors = self.__dict__.get("_field_anchors")
        if not anchors:
            return
        anchor = anchors.get(name)
        if anchor is not None:
            anchor._ensure_fresh()

    def _pull_property_anchors(self) -> None:
        """Pull linked angle/scale so draw/collision see current geometry."""
        anchors = self.__dict__.get("_field_anchors")
        if not anchors:
            return
        for name in _PROPERTY_LINK_FIELDS:
            anchor = anchors.get(name)
            if anchor is not None:
                anchor._ensure_fresh()

    def _scalar_anchor_class(self, name: str):
        if name in _PROPERTY_LINK_ANY and name in (_PROPERTY_LINK_BY_CLASS.get(type(self)) or _property_link_names(self)):
            flags = getattr(type(self), "_property_link_flags", ())
            return _FlagPropertyAnchor if name in flags else _PropertyAnchor
        return super()._scalar_anchor_class(name)

    def _resolve_field(self, key: str):
        if key == "touching_sides":
            return _INK_SLOT
        if key in _PROPERTY_LINK_ANY and key in (_PROPERTY_LINK_BY_CLASS.get(type(self)) or _property_link_names(self)):
            return _INK_SLOT              # reuse the existing "ink-shaped" dispatch branch
        return super()._resolve_field(key)

    def _write_field(self, name: str, value) -> None:
        # Property-backed ``angle`` / ``scale`` resolve to the ink-shaped
        # slot for linking, but their value lives behind the real property
        # (rotate_to / scale_to side effects). A write — e.g. a tween on
        # ``shape["angle"]`` — goes through the setter, like
        # ``_PropertyAnchor._takein`` does; the ink path would crash (no ink
        # dict) or store a dead ink value the pose never reads.
        if name in _PROPERTY_LINK_ANY and name in (_PROPERTY_LINK_BY_CLASS.get(type(self)) or _property_link_names(self)):
            anchors = self.__dict__.get("_field_anchors")
            anchor = anchors.get(name) if anchors else None
            if anchor is not None and anchor._link is not None:
                raise LinkedAttributeError(
                    f"{self.name}.{name} is linked — call {self.name}['{name}'].unlink() first"
                )
            if isinstance(value, Attribute):
                value = value.value
            setattr(self, name, value)
            return
        super()._write_field(name, value)

    def _link_field(self, name: str, source) -> None:
        from .state import _refuse_link_on_dead
        _refuse_link_on_dead(self, f"{name} @=")   # also covers property anchors (W2)
        if name == "touching_sides":
            raise AttributeError(
                f"{self.name}.touching_sides is engine-owned and cannot be linked with @="
            )
        if name in _PROPERTY_LINK_ANY and name in (_PROPERTY_LINK_BY_CLASS.get(type(self)) or _property_link_names(self)):
            self._ensure_scalar_anchor(
                name, anchor_cls=self._scalar_anchor_class(name))._assign_formula(source)
            return
        super()._link_field(name, source)

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
        ease: str = "linear",
        then=None,
        on_done=None,
        about=None,
        force: bool = False,
    ) -> "Graphic":
        """``rotate_to(rest_heading)`` — untilt without clearing flip.

        No ``loops=`` / ``yoyo=``: a single fixed destination has nothing to bounce toward.
        """
        return self.rotate_to(
            self.rest_heading,
            time=time,
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
        """Mirror left-right about ``center``. Setting it twice is the identity."""
        return bool(getattr(self, "_flip_x", False))

    @flip_x.setter
    def flip_x(self, value) -> None:
        self._apply_flip("x", expect_bool(value, f"{type(self).__name__}.flip_x"))

    @property
    def flip_y(self) -> bool:
        """Mirror up-down about ``center``. Setting it twice is the identity."""
        return bool(getattr(self, "_flip_y", False))

    @flip_y.setter
    def flip_y(self, value) -> None:
        self._apply_flip("y", expect_bool(value, f"{type(self).__name__}.flip_y"))

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
        if scale != 1.0:
            from .validate import number
            scale = number(scale, "clone(scale=)")
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
        if scale != 1.0:
            copy.scale_by(float(scale))
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
        # The heading as read (a Defining ``angle`` may be ahead of the pose store).
        _pose_rotation_set(self, float(source._rotation_value()))
        _pose_scale_set(self, float(source._scale))

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> "Graphic":
        """Construct the free copy. Shape uses ``_clone_geometry``; Sprite overrides."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement _clone_recipe for clone()"
        )
