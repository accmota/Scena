import inspect
import math
import os
import sys
import warnings
from typing import Any, Optional, Union, Tuple, overload, List, Callable, Dict, Set, Literal, TYPE_CHECKING
from enum import Enum
import skia
from collections.abc import Sequence
from abc import ABC, abstractmethod

from functools import wraps

from ._defaults import Unset
from .style import PaintState, LookLike
from .color import Color, ColorLike
from .scenamath import Vec2, vec_from_angle
from .state import (
    _notify_source_anchors,
    Attribute, Container, ContainerSlot, ScalarSlot, ScalarAnchor, FieldRef, FieldType,
    batch_update_attrs, batch_update_self, ephemeral_creation, LinkedAttributeError, DestroyedError,
    CallableAssignError,
    driver_conflict_message,
    _init_scalar,
    _init_composite,
    _PropertyAnchor,
    bump_pose_rev,
    _pose_cell_of,
    DIRTY_POSE_CELLS,
    _point_index_refusal,
)
from .transients import compose_draw_mods, draw_with_transients
from .stamps import draw_body_with_stamps
from .validate import HINT_EXTENT, HINT_SCALE, MIN_SCALE, clamp_magnitude, expect_bool, finite, magnitude, fixed_magnitude
from .validate import expect_bool as _expect_flag
from .validate import check_pointer_handler as _check_pointer_handler
from .validate import refuse_async as _refuse_async
from .entity import (
    Entity, Graphic,
    _INK_RESERVED, _SET_OBJECT,
    _ink_link_forbidden_message,
    _install_setattr_route, _install_timed_pose,
    _pose_rotation_set, _pose_rotation_add, _pose_rotation_publish, _pose_scale_set,
    _refuse_linked_pose, _gate_pose_anchor,
    _bump_collision_epoch, _geom_path_cache_set, _placement_write,
    _USE_LAYER_DEFAULT, _COPY_GROUPS, _STYLE_PAINT,
    _fire_on_destroy, _refuse_if_destroyed,
    _parked, _stash_flag,
    _wrap_actor_init, _finish_actor_construct,
    _rotate_as_motion, _rotate_as_placement,
    _is_scena_file,
)


def _sq(v: float) -> float:
    """``v * v``. Not ``v ** 2``: a float power raises OverflowError for a
    huge-but-finite author coordinate; a product saturates to inf."""
    return v * v

if TYPE_CHECKING:
    from .process import Handle



def _bare_attr(attr) -> float:
    """Bare float from an Attribute leaf, or from a already-bare scalar.

    Caches the sync-Defining decision on Attribute instances (``_bare_ok``)
    so draw hot paths avoid repeated owner-chain walks. Bare floats/ints
    (ScalarSlot leaves) pass through.
    """
    if not isinstance(attr, Attribute):
        return float(attr)
    if attr._link is not None:
        return float(attr.value)
    flag = attr.__dict__.get('_bare_ok')
    if flag is True:
        return float(attr._raw_value)
    if flag is False:
        return float(attr.value)
    ok = (
        attr._formula_driven_ancestor() is None
        and attr._derivate_source() is None
    )
    attr.__dict__['_bare_ok'] = ok
    return float(attr._raw_value if ok else attr.value)


def _takein_xy_float(point, x=None, y=None) -> bool:
    """A1 write of a Point's bare x/y — no graph, no Attribute unpack."""
    changed = False
    d = point.__dict__
    if x is not None:
        fx = float(x)
        if d.get('x') != fx:
            d['x'] = fx
            changed = True
    if y is not None:
        fy = float(y)
        if d.get('y') != fy:
            d['y'] = fy
            changed = True
    if changed:
        # bump_pose_rev(point), inline (every A1 move lands here)
        cell = d.get('_pose_cell')
        if cell is None:
            cell = _pose_cell_of(point)
        cell[0] += 1
        if d.get('_pose_mover'):
            cell[4] += 1                 # a translation of its root (the cull shifts)
        if not cell[1]:
            cell[1] = True
            DIRTY_POSE_CELLS.append(cell)
    return changed


def _pose_fast_ok(container, *, force: bool = False) -> bool:
    """True when A1 bare-float pose writes are safe (no pull consumers, not force).

    Invariant: callers must fall back to ``takein`` / ``ScalarSlot`` writes when
    this is false so outbound ``@=`` / live Derivates stay fresh (A4).
    """
    return not force and not container._requires_pull_invalidate()


def _translate_point_float(point, dx=None, dy=None) -> bool:
    """A1 relative translate of one Point via bare ``__dict__`` writes."""
    d = point.__dict__
    nx = None if dx is None else float(d.get('x', 0.0)) + float(dx)
    ny = None if dy is None else float(d.get('y', 0.0)) + float(dy)
    return _takein_xy_float(point, x=nx, y=ny)


def _translate_points_float(points, dx=None, dy=None) -> bool:
    """A1 relative translate of several Points (same dx/dy each)."""
    changed = False
    for point in points:
        if _translate_point_float(point, dx, dy):
            changed = True
    return changed


def _bare_num(v: Any) -> float:
    """Unwrap Attribute (or numeric) to a plain float.

    Defining leaves without a formula / Derivate ancestor read ``_raw_value``
    directly (A3) — draw/transform hot paths avoid ``_ensure_fresh``.
    """
    if isinstance(v, Attribute):
        return _bare_attr(v)
    return float(v)


def _concrete_float(value):
    """Plain float for a construction/write value, or None when it is a link.

    Callables and non-numeric inputs are left for ``_init_scalar`` / ``_write_field``.
    ``bool`` is not a number. Not used on draw or hit-test paths.
    """
    if callable(value) and not isinstance(value, type):
        return None
    if isinstance(value, Attribute):
        value = value.value
        if callable(value) and not isinstance(value, type):
            return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _concrete_xy(value):
    """Plain ``(x, y)`` for a construction check, or None when it is a link.

    A callable, or a 2-sequence with a callable component, is a formula the
    constructor must not snapshot. Anything else resolves like a location
    (Point, Vec2, tuple, Graphic ``.center``).
    """
    if callable(value) and not isinstance(value, type):
        return None
    if isinstance(value, (tuple, list)) and len(value) == 2:
        if any(callable(c) and not isinstance(c, type) for c in value):
            return None
    return _xy_of(value, required=True)


def _reject_non_finite(value, *, what: str) -> None:
    """Raise if a concrete number is NaN, infinite, or not a number. Links pass through."""
    finite(value, what)


def _clamped_spread(value: float) -> float:
    """Live arc opening for draw and outline. Outside ``[0, 360]`` reads as the endpoint."""
    s = float(value)
    if s < 0.0:
        return 0.0
    if s > 360.0:
        return 360.0
    return s


def _is_full_turn(spread: float) -> bool:
    """True when an opening draws and collides as a full circle.

    The same cutoff in paint and in the circle primitive, so a full turn never
    pays for arc polygons.
    """
    return spread >= 360.0 - 1e-6


def _point_in_filled_arc(
    x: float, y: float, cx: float, cy: float, radius: float,
    angle_deg: float, spread_deg: float, use_center: bool,
) -> bool:
    """True when ``(x, y)`` is inside the painted Circle fill.

    A full turn is the disk. A shorter opening is the pie (``use_center``)
    or the chord-closed segment. ``spread`` of 0 misses. Outline queries
    stay the full circumference.
    """
    r = abs(float(radius))
    dx = x - cx
    dy = y - cy
    if dx * dx + dy * dy > r * r:
        return False
    spread = _clamped_spread(spread_deg)
    if _is_full_turn(spread):
        return True
    if spread <= 0.0 or r <= 0.0:
        return False
    if dx == 0.0 and dy == 0.0:
        if use_center:
            return True
        return spread >= 180.0
    point = math.degrees(math.atan2(dy, dx))
    delta = (point - float(angle_deg) + 180.0) % 360.0 - 180.0
    if abs(delta) > spread * 0.5 + 1e-4:
        return False
    if use_center:
        return True
    half = math.radians(spread * 0.5)
    ang = math.radians(float(angle_deg))
    c0, s0 = math.cos(ang - half), math.sin(ang - half)
    c1, s1 = math.cos(ang + half), math.sin(ang + half)
    p0x, p0y = cx + c0 * r, cy + s0 * r
    p1x, p1y = cx + c1 * r, cy + s1 * r
    abx, aby = p1x - p0x, p1y - p0y
    if abx * abx + aby * aby < 1e-18:
        return False
    mx, my = cx + math.cos(ang) * r, cy + math.sin(ang) * r
    cross_p = abx * (y - p0y) - aby * (x - p0x)
    cross_m = abx * (my - p0y) - aby * (mx - p0x)
    return cross_p * cross_m >= -1e-8


def _reject_bad_spread(value) -> None:
    """Author ``spread`` is in ``[0, 360]``. A formula passes through.

    Negatives raise via ``magnitude``. Above 360 raises here. A linked or
    tweened value outside the range is clamped when the arc is drawn.
    """
    if callable(value) and not isinstance(value, type):
        return
    if isinstance(value, Attribute):
        value = value.value
        if callable(value) and not isinstance(value, type):
            return
    from .validate import magnitude
    n = magnitude(value, "spread")
    if isinstance(n, bool) or not isinstance(n, (int, float)):
        return
    if float(n) > 360.0:
        raise ValueError(f"spread must be <= 360, got {float(n)}")


_POSITIONAL_EXAMPLES = {
    "Line": "Line(p1=(0, 0), p2=(100, 0))",
    "Circle": "Circle(center=(0, 0), radius=10)",
    "Ellipse": "Ellipse(center=(0, 0), width=40, height=20)",
    "RegularPolygon": "RegularPolygon(center=(0, 0), radius=30, n=6)",
    "Rect": "Rect(center=(0, 0), width=10, height=20)",
    "Square": "Square(center=(0, 0), length=10)",
    "Triangle": "Triangle(center=(0, 0), radius=30)",
    "Polygon": "Polygon(points=[(0, 0), (40, 0), (20, 30)])",
}


def _reject_positional_shape_args(cls: type, args: tuple) -> None:
    """Shapes are keyword-only; positional values used to be dropped silently."""
    if not args:
        return
    name = cls.__name__
    example = next(
        (_POSITIONAL_EXAMPLES[k.__name__] for k in cls.__mro__ if k.__name__ in _POSITIONAL_EXAMPLES),
        None,
    )
    shown = ", ".join(repr(a) for a in args[:3]) + (", …" if len(args) > 3 else "")
    raise TypeError(
        f"{name}() takes keyword arguments only, got positional {shown}. "
        + (f"Name each value, e.g. {name}{example[example.index('('):]}." if example else "Name each value.")
    )


def _unwrap_deg(raw: float, acc: float) -> float:
    """``raw`` (an ``atan2`` direction) moved by whole turns to the nearest of
    ``acc`` — a derived heading keeps the turns the pose store has counted, so
    ``rotate_by(400)`` reads ``+400``, not ``40``."""
    return acc + ((raw - acc + 180.0) % 360.0 - 180.0)


def _finite_deg(value, what: str) -> float:
    """Author angle in degrees: a finite number (``TypeError`` / ``ValueError`` otherwise).

    Runs up to 3× per ``angle =`` (setter → rotate_to → rotate_by); the
    exact-type test keeps the already-float inner calls near free.
    """
    t = type(value)
    if t is float:
        if math.isfinite(value):
            return value
    elif t is int:
        if -1e308 < value < 1e308:      # 10**400: finite() refuses it below
            return float(value)
    n = finite(_bare_num(value) if isinstance(value, Attribute) else value, what)
    if callable(n):
        raise TypeError(f"{what} expected a number, got a function")
    return float(n)


def _reject_bad_length(value, *, what: str = "length") -> None:
    """Raise if a concrete length is non-finite or negative. Links pass through.

    Length is a magnitude: it must agree with ``angle`` / ``vec``. A negative
    factor on ``scale_by`` uses ``abs`` so it never stores a signed length.
    """
    n = _concrete_float(value)
    if n is None:
        return
    if not math.isfinite(n) or n < 0.0:
        raise ValueError(f"{what} must be finite and >= 0")


def _rad(deg) -> float:
    return math.radians(_bare_num(deg))


def _deg(rad) -> float:
    return math.degrees(float(rad))


def _rotate_xy(x: float, y: float, cx: float, cy: float, angle: float) -> Tuple[float, float]:
    """Rotate (x, y) about (cx, cy) by angle radians."""
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    dx = x - cx
    dy = y - cy
    return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a


def _scale_xy(x: float, y: float, cx: float, cy: float, factor: float) -> Tuple[float, float]:
    """Scale (x, y) about (cx, cy) by factor."""
    return cx + (x - cx) * factor, cy + (y - cy) * factor


def _scale_geom_and_store(old: float, *, value=None, factor=None):
    """Geometry multiplier and the scale value to store.

    Stored scale is exact, including 0. Geometry uses ``MIN_SCALE`` so a later
    ``scale_to`` can restore the collapsed shape.
    """
    from .validate import HINT_SCALE, MIN_SCALE, magnitude

    old = float(old)
    if value is not None:
        store = fixed_magnitude(value, "scale", hint=HINT_SCALE)
    else:
        store = fixed_magnitude(factor, "scale", hint=HINT_SCALE)
    if callable(store):
        raise TypeError("scale expected a number, got a function")
    store = float(store)
    if value is None:
        store = old * store
    geom = max(store, MIN_SCALE) / max(old, MIN_SCALE)
    return geom, store


def _near_pivot(px, py, cx, cy) -> bool:
    """One rule for "this point is the pivot": the turn / scale leaves it
    where it is, so it is not written and may stay linked. Relative to the
    coordinates' size (a centre computed another way differs by rounding).
    The gates compared exactly and the verbs with 1e-12, so one pivot passed
    ``rotate_by`` and was refused by ``scale_by`` (review 2026-10-09 S6-4)."""
    tol = 1e-12 * max(1.0, abs(cx), abs(cy))
    return abs(px - cx) <= tol and abs(py - cy) <= tol


def _fresh_pose(obj) -> None:
    """Pull a linked ``angle`` / ``scale`` into the stores before a verb
    computes from them: ``force=True`` unlinks after the delta was computed,
    so ``scale_to(2, force=True)`` scaled from the value of the last pull
    (review 2026-10-09 S6-1). One dict probe when nothing is linked."""
    if obj.__dict__.get("_field_anchors"):
        type(obj)._pull_property_anchors(obj)


def _resolve_scale_apply(obj, factor: float, *, force: bool = False):
    """``scale_to`` passes a geometry factor plus a pending store; ``scale_by`` does not.

    Every ``scale_by`` starts here, so the linked ``["scale"]`` refusal runs
    before the verb writes any geometry (SA2; a refusal after the writes
    half-applied the verb)."""
    pending = obj.__dict__.get("_pending_scale_store", None)
    if pending is None:
        _fresh_pose(obj)
        geom, store = _scale_geom_and_store(obj._scale, factor=factor)
    else:
        geom, store = float(factor), float(pending)
    if not (geom == 1.0 and store == float(obj._scale)):
        d = obj.__dict__
        anchors = d.get("_field_anchors")
        if anchors or d.get("_link") is not None:
            _refuse_linked_pose(obj, anchors, "scale", "scale_by", force)
    return geom, store


def _link_reads(link, ref) -> bool:
    """Does ``link`` read ``ref`` (the reference of a relational shape)?"""
    for src in getattr(link, 'sources', None) or ():
        root = src._ownership_root() if isinstance(src, Container) else None
        if root is ref:
            return True
    return False


def _scale_gate_at_call(obj, *, value=None, factor=None, about=None, force: bool = False,
                        verb: str = "scale_by") -> None:
    """Everything an instant ``scale_by`` / ``scale_to`` checks before its first
    write, without writing: the timed verbs run it at the call, so they refuse
    (or unlink with ``force=True``) where the instant verb does, not from a
    later tick after part of the motion ran (GX4 in Testing Design). One gate
    per kind (``_scale_gate``), shared with the instant verb."""
    _refuse_if_destroyed(obj, verb)
    _fresh_pose(obj)
    geom, store = _scale_geom_and_store(obj._scale, value=value, factor=factor)
    if geom == 1.0 and store == float(obj._scale):
        return                              # the instant verb is a no-op
    d = obj.__dict__
    anchors = d.get("_field_anchors")
    if anchors or d.get("_link") is not None:
        _refuse_linked_pose(obj, anchors, "scale", verb, force)
    gate = getattr(obj, "_scale_gate", None)
    if gate is not None:
        gate(about, force)


def _scale_to_via(obj, value, *, about, force):
    _fresh_pose(obj)
    geom, store = _scale_geom_and_store(obj._scale, value=value)
    obj.__dict__["_pending_scale_store"] = store
    try:
        return obj.scale_by(geom, about=about, force=force)
    finally:
        obj.__dict__.pop("_pending_scale_store", None)


def _about_is_pose_center(obj, about) -> bool:
    """True when ``about`` is omitted or coincides with ``obj.center`` (pose pivot)."""
    if about is None:
        return True
    cx, cy = get_xy(obj.center, bare=True)
    px, py = get_xy(about, bare=True)
    return _near_pivot(px, py, cx, cy)


def _parallel_offset_point(ref: 'Line', dist_attr: Attribute) -> Tuple[float, float]:
    """p1 for Line's PARALLEL_DIST model: ref.p1 shifted along ref's left-normal by dist.

    Uses ``ref._segment_xy()`` (Defining inputs only) so this formula never
    materializes Derivate ``ref.vec`` / ``ref.p2`` / ``ref.center``.
    """
    x1, y1, x2, y2 = ref._segment_xy()
    vx, vy = x2 - x1, y2 - y1
    seg_len = math.hypot(vx, vy)
    nx, ny = (0.0, 0.0) if seg_len == 0 else (-vy / seg_len, vx / seg_len)
    d = _bare_num(dist_attr)
    return (x1 + nx * d, y1 + ny * d)


def _circle_point_at_angle(circle: 'Circle', angle_attr: Attribute) -> Tuple[float, float]:
    """p1 for Line's TANGENT_ANGLE model: point on circle at the given angle."""
    cx, cy = get_xy(circle.center, bare=True)
    r = abs(_bare_num(circle.radius))
    a = _rad(angle_attr)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def _circle_tangent_touch_point(circle: 'Circle', from_point: 'Point', side: str) -> Tuple[float, float]:
    """p2 for Line's TANGENT_POINT model: the tangent touch point on circle, disambiguated by side.

    If from_point is inside (or on) the circle, there is no real tangent; degenerates to
    from_point itself (a zero-length line).
    """
    cx, cy = get_xy(circle.center, bare=True)
    # Signed radius is the same disk; side stays stable when radius goes negative.
    r = abs(_bare_num(circle.radius))
    px, py = get_xy(from_point, bare=True)
    ex, ey = px - cx, py - cy
    dist = math.hypot(ex, ey)
    if dist <= r:
        return (px, py)
    base_angle = math.atan2(ey, ex)
    offset = math.acos(r / dist)
    touch_angle = base_angle + offset if side == 'left' else base_angle - offset
    return (cx + r * math.cos(touch_angle), cy + r * math.sin(touch_angle))


# Persistent-driver declarations (pointer drag / wheel / standing resolve).
# Only a formula is exclusive: these never refuse a motion in flight (both
# compose — see Shapes Design, Persistent drivers), and they have no
# ``force=`` escape over a formula.
_PERSISTENT_DECLARATION_OPS = frozenset({
    "set draggable", "set wheel_rotate", "resolve()",
})

# How a refused op reads in front of the actor label.
_OP_PHRASE = {
    "set draggable": "set draggable on",
    "set wheel_rotate": "set wheel_rotate on",
}


# Record mode (``_gate_parts``): the gate lists what it would write instead of
# checking it. A timed verb claims those parts, so a link made while it runs
# is refused at the ``@=`` (GX6 in Testing Design), not from a later tick.
_GATE_RECORD: Optional[list] = None


def _gate_parts(gate) -> list:
    """The parts ``gate()`` would write: every part it gates, less the points
    that sit on the pivot it names (a verb about them does not move them)."""
    global _GATE_RECORD
    prev, _GATE_RECORD = _GATE_RECORD, []
    try:
        gate()
        rec = _GATE_RECORD
    finally:
        _GATE_RECORD = prev
    out = []
    for part, pivot in rec:
        if pivot is not None and not isinstance(part, FieldRef):
            d = part.__dict__
            x, y = d.get('x'), d.get('y')
            if x is not None and y is not None and _near_pivot(x, y, pivot[0], pivot[1]):
                continue
        out.append(part)
    return out


def _ensure_writable(
    part, operation: str, *, force: bool = False,
    context: str = "", undo_extra: str = "", pivot=None,
) -> None:
    """The write gate: may a geometric transform write ``part``? (Shapes Design
    — Linked parts.) One rule for every kind and verb:

    * a link on the part's subtree refuses, and so does a whole-object link on
      an owner (``shape @= other`` drives every part; SA1);
    * property-backed pose anchors (``["angle"]`` / ``["scale"]`` on a Sprite,
      Point, Polygon, Text) are not position parts: their own writers
      (``_pose_rotation_*`` / ``_pose_scale_set``) refuse a linked anchor, so a
      linked heading does not block a move (SA3);
    * ``pivot=(x, y)``: a point that sits on the verb's pivot is not moved by a
      turn, scale or mirror about it, so it is not written and may stay linked
      (SB3 / SC8: ``Circle(center=lambda: …).rotate_by(5)``).

    By default a refusal raises (a formula is the only exclusive driver).
    ``force=True`` unlinks with a warning instead (one-shot transforms only);
    persistent declarations (``draggable`` / ``wheel_rotate`` / ``resolve()``)
    have no ``force``. ``context`` follows the actor label in the message;
    ``undo_extra`` extends the undo hint. Accepts a FieldRef or a Container.
    """
    if _GATE_RECORD is not None:
        _GATE_RECORD.append((part, pivot))
        return
    if isinstance(part, FieldRef):
        owner = part.owner
        if not part.is_linked:
            if not isinstance(owner, Container) or not owner._requires_pull_invalidate():
                return                      # no @= anywhere in the tree
            holder = owner if owner._link is not None else owner._formula_driven_ancestor()
            if holder is None:
                return
            part = holder                   # the whole-object link refuses
            linked = [holder]
    else:
        if not part._requires_pull_invalidate():
            return                          # no @= anywhere in the tree (sticky flag)
        if pivot is not None:
            d = part.__dict__
            if 'x' in d and d.get('y') is not None and _near_pivot(
                    d['x'], d['y'], pivot[0], pivot[1]):
                return
        linked = [node for node in part._iter_subtree()
                  if node._link is not None and not isinstance(node, _PropertyAnchor)]
        holder = part._formula_driven_ancestor()
        if holder is not None:
            linked.append(holder)
        if not linked:
            return
    # Refusal path only below (the common unlinked write never imports).
    from .entity import _actor_of, entity_label, part_path

    no_force = operation in _PERSISTENT_DECLARATION_OPS
    if isinstance(part, FieldRef):
        if force and not no_force:
            warnings.warn(
                f"{part.owner.name}[{part.name!r}] was unlinked because {operation} "
                f"must write it",
                RuntimeWarning,
            )
            part.unlink()
            drop = getattr(part.owner, "_drop_relational", None)
            if drop is not None:
                drop()
            return
        linked_names = str(part.name)
        if _actor_of(part.owner) is None:
            # A State bag (``hud["count"]``): its name is the author's own.
            owner_name = str(part.owner.name)
            undo = f"Call {owner_name}['{part.name}'].unlink() first"
            if not no_force:
                undo += ", or pass force=True"
            raise LinkedAttributeError(
                driver_conflict_message(
                    new=_OP_PHRASE.get(operation, operation),
                    subject=owner_name + context,
                    part=linked_names,
                    existing="has an @= formula",
                    undo=undo + undo_extra,
                )
            )
        subject = entity_label(part.owner)
    else:
        if force and not no_force:
            names = ", ".join(getattr(n, 'name', str(n)) for n in linked)
            warnings.warn(
                f"{part.name} was unlinked because {operation} must write it "
                f"(had links on: {names})",
                RuntimeWarning,
            )
            part.unlink_all()
            for node in linked:
                if node._link is not None:      # a linked owner: drop its link too
                    node.unlink()
            actor = _actor_of(part) or part
            drop = getattr(actor, "_drop_relational", None)
            if drop is not None:
                drop()
            return
        linked_names = ", ".join(part_path(n) for n in linked)
        subject = entity_label(part)
    undo = "Unlink it first (unlink() / unlink_all())"
    if not no_force:
        undo += ", or pass force=True"
    undo += undo_extra
    raise LinkedAttributeError(
        driver_conflict_message(
            new=_OP_PHRASE.get(operation, operation),
            subject=subject + context,
            part=linked_names,
            existing="has an @= formula",
            undo=undo,
        )
    )


def _link_overlaps_part(target: Container, part) -> bool:
    """True if linking ``target`` would cover any node under ``part`` (or vice versa)."""
    if isinstance(part, FieldRef):
        if isinstance(target, ScalarAnchor):
            return (
                target._scalar_parent is part.owner
                and target._scalar_name == part.name
            )
        return False
    part_ids = {id(n) for n in part._iter_subtree()}
    for n in target._iter_subtree():
        if id(n) in part_ids:
            return True
    cur: Optional[Container] = part
    while cur is not None:
        if cur is target:
            return True
        cur = cur._owner
    return False


GeneralPoint = Union['Point', tuple, 'Shape', Vec2]

# Minimum hit-test padding in design units (thin lines / Points stay grabbable).
HIT_PADDING = 6.0

# Empty constructors (``Line()``, ``Circle()``, …) place a visible shape at the
# design-space center. Size is a fraction of the shorter design side
# (≈72 on the default 2000×1200 canvas).
_DEFAULT_EXTENT_FRAC = 0.06


def _default_pose(canvas=None) -> Tuple[Tuple[float, float], float]:
    """Return ``((cx, cy), unit)`` for visible empty-constructor geometry.

    ``unit`` is ``_DEFAULT_EXTENT_FRAC * min(width, height)`` of the current
    design space. Call after the framework has a canvas (normal after ``init()``).
    """
    if canvas is None:
        from .canvas import ScenaCanvas
        canvas = ScenaCanvas.get_current()
    w = float(canvas.width)
    h = float(canvas.height)
    unit = _DEFAULT_EXTENT_FRAC * min(w, h)
    return (w * 0.5, h * 0.5), unit


# Omit ``layer`` → use ``canvas.layers.default``. Explicit ``None`` → undrawn.
# ``layer=<int>`` → numeric position (auto-created, frozen z). Point defaults
# to ``None``. Do not use the string ``\"default\"`` as a stand-in for
# \"construction default\", or ``canvas.layers.using(...)`` would break.


def _point_in_polygon(x: float, y: float, vertices: Sequence) -> bool:
    """Ray-casting point-in-polygon test over a sequence of Point-like vertices."""
    n = len(vertices)
    if n < 3:
        return False
    inside = False
    xj, yj = get_xy(vertices[-1], bare=True)
    for i in range(n):
        xi, yi = get_xy(vertices[i], bare=True)
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        xj, yj = xi, yi
    return inside


def get_xy(obj: GeneralPoint, bare: bool = False) -> Tuple[float, float]:
    """ Extract a Point from various object types.

    Hot path (called from every draw()/_update_impl() for corner/vertex
    access): Point.x/y and Vec2.x/y are bare ScalarSlot floats. Under
    ``bare=True``, leftover Attribute leaves (tuple coords, boxed cells)
    still unwrap via ``_bare_num``.
    """
    if isinstance(obj, (Point, Vec2)):
        if bare:
            return _bare_num(obj.x), _bare_num(obj.y)
        return obj.x, obj.y

    if isinstance(obj, (tuple, list)) and len(obj) == 2:
        x, y = obj
        tx, ty = type(x), type(y)
        # Exact float / int (never bool): the common case, one test each.
        if (tx is float or tx is int) and (ty is float or ty is int):
            # An author tuple: NaN / inf refused (SA6), inline (hot path).
            try:
                fx = float(x)
                fy = float(y)
            except OverflowError:
                return _finite_xy(obj, x, y)
            if (fx - fx) or (fy - fy):
                return _finite_xy(obj, x, y)
            return fx, fy
        if (not (isinstance(x, (int, float, Attribute)) and isinstance(y, (int, float, Attribute)))
                or tx is bool or ty is bool):
            raise TypeError("Tuple coordinates must be numbers")
        if bare:
            if isinstance(x, Attribute):
                x = _bare_attr(x)
            if isinstance(y, Attribute):
                y = _bare_attr(y)
        return x, y

    raise TypeError(f"Cannot convert {type(obj)} to Point")


_POINT_IADD_MSG = (
    "`ship.center += …` would teleport past walls. "
    "Use `ship.move_by(dx, dy)` to move, "
    "or `ship.center = ship.center + (dx, dy)` to place."
)


# ``Point ==`` keeps identity (PE1): the engine needs it (weak sets and weak
# dicts key on Points, the registry scans its lists with ``in`` / ``remove``,
# and two handles often share a spot). Author code that compares a Point with
# a position (``c.center == (400, 120)``), or with another Point on the same
# spot, meant the position and would get a silent always-False: it gets a
# warning instead, once per line. Engine compares stay silent.
_POINT_EQ_WARNED: Set[Tuple[str, int]] = set()
# Code that compares for its caller (``cell == point`` → ``cell.value == point``).
_POINT_EQ_PASSTHROUGH: Set[Any] = set()
_POINT_EQ_WARN_SKIP = (os.path.dirname(os.path.abspath(__file__)) + os.sep,)


def _point_compare_site() -> Optional[Tuple[str, int]]:
    """``(file, line)`` of the author code whose ``==`` reached ``Point.__eq__``.

    ``None`` for engine code. Frame 2 is the comparing code: ``==``, ``in``
    and ``list.remove`` run in C and add no frame of their own.
    """
    if not _POINT_EQ_PASSTHROUGH:
        _POINT_EQ_PASSTHROUGH.add(Attribute.__eq__.__code__)
    try:
        f = sys._getframe(2)
    except ValueError:
        return None
    while f is not None and f.f_code in _POINT_EQ_PASSTHROUGH:
        f = f.f_back
    if f is None:
        return None
    fn = f.f_code.co_filename
    if _is_scena_file(fn):
        return None
    return (fn, f.f_lineno)


def _warn_point_compare(point: 'Point', other: Any, site: Tuple[str, int]) -> None:
    if site in _POINT_EQ_WARNED:
        return
    _POINT_EQ_WARNED.add(site)
    if isinstance(other, Point):
        msg = (
            f"two different Points at the same position ({point.x:g}, {point.y:g}) "
            "are not ==: == on Points compares the objects, not their positions. "
            "Same position: distance(a, b) == 0. Same object: a is b."
        )
    else:
        kind = "Vec2" if isinstance(other, Vec2) else type(other).__name__
        msg = (
            f"Point == {kind} is always False (and != always True): == on a Point "
            "compares the object, not its position. Test the position with "
            "distance(point, (x, y)) == 0, or < 1 when the motion does not land exactly."
        )
    warnings.warn(msg, RuntimeWarning, skip_file_prefixes=_POINT_EQ_WARN_SKIP)


def _point_delta(other: Any, *, op: str) -> Tuple[float, float]:
    """Vec2 or ``(dx, dy)`` numbers for Point ``+`` / ``-``.

    A tuple is a delta here (same as ``Vec2 + tuple``), not a second point.
    ``Point + Point`` stays an error: the midpoint is ``middle_point``.
    """
    if isinstance(other, Vec2):
        return other.x, other.y
    if isinstance(other, Attribute):
        other = other.value          # a cell holding a pair / Vec2, read fresh
        if isinstance(other, Vec2):
            return other.x, other.y
    if isinstance(other, (tuple, list)) and len(other) == 2:
        x, y = other
        if isinstance(x, Attribute):
            x = x.value
        if isinstance(y, Attribute):
            y = y.value
        if (
            isinstance(x, (int, float)) and isinstance(y, (int, float))
            and not isinstance(x, bool) and not isinstance(y, bool)
        ):
            return x, y
    if isinstance(other, Point):
        raise TypeError(
            "Cannot add two Points. Use `middle_point(a, b)` for the midpoint, "
            "or `a - b` for the vector between them."
        )
    verb = "add" if op == "add" else "subtract"
    raise TypeError(
        f"Cannot {verb} Point and {type(other).__name__}. "
        "Use a Vec2 or a (dx, dy) tuple."
    )


def _pair_numbers(seq) -> Optional[Tuple[float, float]]:
    """A tuple / list of exactly two numbers (cells unwrapped), else None.

    Booleans are not coordinates; a longer sequence is not a point (it used
    to be read as its first two items in some places)."""
    if len(seq) != 2:
        return None
    x, y = seq
    # A cell's value as stored: ``_bare_attr`` floats it, so ``True`` read as
    # 1 and a huge int leaked OverflowError (GX14 in Testing Design).
    if isinstance(x, Attribute):
        x = x.value
    if isinstance(y, Attribute):
        y = y.value
    tx, ty = type(x), type(y)
    if tx is bool or ty is bool or not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return _finite_xy(seq, x, y)


def _finite_xy(seq, x, y) -> Tuple[float, float]:
    """``(float(x), float(y))``, refusing NaN / inf / a huge int (graphics
    review SA6: ``center = (nan, 0)`` stored a NaN center, ``(10**400, 0)``
    leaked ``OverflowError``). A point is two finite numbers (Scena Design —
    Numbers and signs)."""
    try:
        fx = float(x)
        fy = float(y)
    except OverflowError:
        fx = fy = math.inf
    if (fx - fx) or (fy - fy):      # nan / inf - itself is nan (truthy); finite is 0.0
        raise ValueError(f"a point takes two finite numbers, got {_short_point(seq)}")
    return fx, fy


def _short_point(seq) -> str:
    r = repr(tuple(seq)) if isinstance(seq, (tuple, list)) else repr(seq)
    return r if len(r) <= 40 else r[:39] + "…"


def _xy_of(obj: Any, *, required: bool = False) -> Optional[Tuple[float, float]]:
    """The one reading of a point-like as ``(x, y)``; see :func:`_read_xy`.

    Point / Vec2 return here (the formula / contrail / linked-takein hot path:
    the same signature as before, no extra keyword defaults to fill)."""
    if isinstance(obj, Point):
        return _bare_num(obj.x), _bare_num(obj.y)
    if isinstance(obj, Vec2):       # a value type: it may hold NaN, a Point may not
        return _finite_xy(obj, obj.x, obj.y)
    if isinstance(obj, (tuple, list)) and len(obj) == 2:
        x, y = obj
        tx, ty = type(x), type(y)
        if (tx is float or tx is int) and (ty is float or ty is int):
            try:
                fx = float(x)
                fy = float(y)
            except OverflowError:
                return _finite_xy(obj, x, y)            # raises with the hint
            if (fx - fx) or (fy - fy):                  # NaN / inf (SA6)
                return _finite_xy(obj, x, y)
            return fx, fy
    return _read_xy(obj, required, True, True)


def _read_xy(
    obj: Any, required: bool = False, graphic_center: bool = True, duck: bool = True,
) -> Optional[Tuple[float, float]]:
    """The one reading of a point-like as ``(x, y)`` (Track C item 3).

    In order: Point / Vec2 (the formula / contrail hot path, no exception),
    a tuple or list of exactly two numbers (booleans refused), a state cell
    (read fresh, then the same rules), a Graphic's ``.center``, then any
    object with ``.x`` / ``.y`` (mouse). Policies for the callers that differ
    on purpose: ``graphic_center=False`` / ``duck=False`` for a delta (a
    direction is not a Graphic). Vec2, where a Point is a place and not a
    displacement, refuses it itself (``_xy_refusal(points=False)`` words it).
    ``required`` raises TypeError instead of None.
    """
    # Lockstep with get_xy's Point/Vec2 branch. Do not call get_xy here:
    # that would add a second call on every linked takein and stamp rebuild.
    if isinstance(obj, Point):
        return _bare_num(obj.x), _bare_num(obj.y)
    if isinstance(obj, Vec2):
        return _finite_xy(obj, obj.x, obj.y)
    if isinstance(obj, (tuple, list)):
        xy = _pair_numbers(obj)
        if xy is not None:
            return xy
    elif isinstance(obj, Attribute):
        return _read_xy(obj.value, required, graphic_center, duck)
    else:
        if graphic_center:
            center = getattr(obj, "center", None)
            if center is not None and center is not obj:
                if isinstance(center, (Point, Vec2)):
                    return _bare_num(center.x), _bare_num(center.y)
                if isinstance(center, (tuple, list)):
                    xy = _pair_numbers(center)
                    if xy is not None:
                        return xy
                try:
                    return float(center.x), float(center.y)
                except (AttributeError, TypeError, ValueError):
                    pass
        if duck:
            try:
                return float(obj.x), float(obj.y)
            except (AttributeError, TypeError, ValueError):
                pass
    if required:
        raise TypeError(_xy_refusal(obj, graphic_center=graphic_center))
    return None


def _xy_refusal(obj, *, graphic_center: bool = True, points: bool = True) -> str:
    """Why ``obj`` is not a point here."""
    if isinstance(obj, (tuple, list)):
        return (f"expected (x, y) — exactly two numbers — got {type(obj).__name__} "
                f"{obj!r:.60}")
    if not points:
        if isinstance(obj, Point):
            return ("expected a Vec2 or (x, y), got a Point: a Point is a place, not a "
                    "displacement. The vector between two points is p - q.")
        return f"expected a Vec2 or (x, y), got {type(obj).__name__}"
    if not graphic_center:
        return f"expected Point, Vec2, or (x, y), got {type(obj).__name__}"
    return (f"expected Point, Vec2, (x, y), or an object with .center / .x/.y, "
            f"got {type(obj).__name__}")


def middle_point(p1: Any, p2: Any, weight: float = 0.5) -> Tuple[float, float]:
    """Return ``(x, y)`` between two positions with optional weighting.

    Returns a bare coordinate tuple (not a ``Point``), suitable for constructors
    and ``@=`` formulas without creating a canvas object.

    Args:
        p1: First position (Point, Vec2, tuple, Graphic, mouse, …)
        p2: Second position (same family)
        weight: 0.0 → p1, 1.0 → p2, 0.5 → midpoint

    Raises:
        ValueError: If weight is not between 0.0 and 1.0
        TypeError: If p1 or p2 cannot be converted to coordinates
    """
    from .validate import number
    weight = number(weight, "middle_point weight")
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"middle_point weight must be between 0.0 and 1.0, got {weight:g}")

    x1, y1 = _xy_of(p1, required=True)
    x2, y2 = _xy_of(p2, required=True)

    x = x1 + weight * (x2 - x1)
    y = y1 + weight * (y2 - y1)
    return (x, y)


def distance(p1: Any, p2: Any) -> float:
    """Euclidean distance between two positions.

    Accepts ``Point``, ``Vec2``, ``(x, y)``, or an object with ``.center`` /
    ``.x``/``.y`` (Shape, Sprite, mouse) — the same family as ``heading`` /
    ``nearest``. Returns a bare float (always ≥ 0); wrap in a lambda for a
    live ``@=`` formula.

    ``Point.distance`` / ``Vec2.distance`` are the same metric as a method.

    Args:
        p1: A point (tuple, Point, Vec2, Graphic, mouse).
        p2: Another point.
    """
    x1, y1 = _xy_of(p1, required=True)
    x2, y2 = _xy_of(p2, required=True)
    return math.hypot(x2 - x1, y2 - y1)


def heading(origin: Any, target: Any) -> float:
    """Bearing from ``origin`` to ``target`` in degrees (0 = +x, CCW).

    Same position family as ``distance`` / ``nearest``. Range is −180…180
    (``atan2``). Coincident positions → ``0``. Order is from, then to —
    swapping the arguments flips the angle by 180°.

    Sugar for ``(target.center - origin.center).angle``. ``Point.heading``
    is the same value as a method. Assign onto ``.angle`` to point a
    Graphic (Sprite ``art_angle`` is already folded into world heading).
    """
    x1, y1 = _xy_of(origin, required=True)
    x2, y2 = _xy_of(target, required=True)
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def nearest(
    origin: Any,
    items: Any,
    *,
    within: Optional[float] = None,
    where: Optional[Callable] = None,
) -> Any:
    """Closest item to ``origin``, or ``None`` if none match.

    ``origin`` is a Point, Vec2, ``(x, y)``, or an object with ``.center`` /
    ``.x``/``.y`` (Shape, Sprite, mouse). ``items`` is any iterable (list,
    ``group["wasp"]``, ``poly.points``). Returns the original item, not a
    new Point. Items without a known position are skipped. Ties: first wins.

    ``within=`` caps Euclidean distance (inclusive). ``where=`` is
    ``pred(item) -> bool``. Empty / no match → ``None``.

    Fleet spelling: ``group["wasp"].nearest(origin)`` — same metric.
    """
    ox, oy = _xy_of(origin, required=True)
    if within is not None:
        within = float(within)
        if within < 0.0:
            raise ValueError("within= must be >= 0")
        within_d2 = within * within
    else:
        within_d2 = None
    if where is not None:
        if not callable(where):
            raise TypeError(
                f"nearest() where= expected a function, got {type(where).__name__}."
            )
        # An async where= returns a (truthy) coroutine: every item would pass.
        _refuse_async(where, what="nearest() where=")
    if getattr(type(items), "_scena_point_value", False):
        # A Point / Vec2 / mouse iterates as its (x, y): not a list of items.
        raise TypeError(
            f"items must be a list (or group) of actors or points, got one "
            f"{type(items).__name__}. Write nearest(origin, [a, b, ...])."
        )
    try:
        iterator = iter(items)
    except TypeError:
        raise TypeError(
            f"items must be iterable, got {type(items).__name__}"
        ) from None

    best = None
    best_d2 = None
    for item in iterator:
        if where is not None and not where(item):
            continue
        xy = _xy_of(item)
        if xy is None:
            continue
        dx = xy[0] - ox
        dy = xy[1] - oy
        d2 = dx * dx + dy * dy
        if within_d2 is not None and d2 > within_d2:
            continue
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best = item
    return best


class Pos(Enum):
    CENTER = "center"
    TOP_LEFT = "top-left"
    BOTTOM_LEFT = "bottom-left"
    TOP_RIGHT = "top-right"
    BOTTOM_RIGHT = "bottom-right"
    TOP_CENTER = "top-center"
    BOTTOM_CENTER = "bottom-center"
    LEFT_CENTER = "left-center"
    RIGHT_CENTER = "right-center"

class XPos(Enum):
    """Horizontal alignment: ``Text(align=)`` takes these or the strings
    ``"left"`` / ``"center"`` / ``"right"``."""

    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"

class YPos(Enum):
    TOP = "top"
    BOTTOM = "bottom"
    CENTER = "center"




# Pose / pointer / transient / draw envelope live on Shape (historical) and are
# published onto Graphic after the Shape class body so Sprite shares them
# without a second copy. See ``_publish_graphic_api`` below.


# Class kwargs allowed on every Shape subclass (plus per-class ``_HOME_SIZE_KEYS``).
_SHAPE_STYLE_KEYS = frozenset({"color", "visual", "group"})
_SHAPE_PLACEMENT_KEYS = frozenset({"center", "layer"})


def _live_ref(ref, owner: str, kind: str, param: str):
    """A construct-time source shape (``Line(circle=c)``, ``Ellipse(from_rect=r)``).

    Must be a live ``kind`` (``"Circle"``, ``"Line"``, ``"Rect"``; subclasses
    count): anything else raises ``TypeError`` naming the parameter (A11 —
    ``Ellipse(from_rect=False)`` leaked ``'bool' object has no attribute
    'center'``); a destroyed one raises ``DestroyedError`` instead of linking a
    new live shape to it (A7; same contract as ``@=`` to a dead source)."""
    expected = globals()[kind]
    if not isinstance(ref, expected):
        raise TypeError(
            f"{owner}({param}=) expects a {kind}, got {type(ref).__name__} {ref!r:.40}"
        )
    if getattr(ref, "_destroyed", False):
        from .entity import _destroyed_access_message
        raise DestroyedError(_destroyed_access_message(
            ref, f"{owner}() cannot take a destroyed {type(ref).__name__} as its source"))
    return ref


def _graphic_rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Shape':
    """Instant ``rotate_by`` body (Sprite path): CTM turn, orbit ``center``."""
    dθ_deg = _finite_deg(angle, "rotate_by angle")
    if dθ_deg == 0.0:
        return self
    _gate_pose_anchor(self, "angle", "rotate_by", force)      # before the orbit write
    if not _about_is_pose_center(self, about):
        px, py = get_xy(about, bare=True)
        cx, cy = get_xy(self.center, bare=True)
        nx, ny = _rotate_xy(cx, cy, px, py, _rad(dθ_deg))
        if not force and not self._requires_pull_invalidate():
            _takein_xy_float(self.center, nx, ny)
        else:
            _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
            self.center._takein((nx, ny))
    _pose_rotation_add(self, dθ_deg)
    return self


class Shape(Graphic, PaintState):
    """
    Abstract base class for all shapes.

    Args:
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
    """
    __slots__ = (
        '_scenacanvas', '_visible', '_rotation', '_scale', '_reg_key', 'group',
        '_layer', '_in_batch_update', '_defining_parts',
        '_clickable', '_draggable', '_droppable', '_wheel_rotate',
        '_on_click', '_on_drag_to', '_on_drag_over', '_on_drop_by',
        '_on_hover', '_on_hover_exit',
        '_pointer_hover', '_pointer_pressed',
        '_collidable', '_collider', '_collision_opt_out', '_time_scale',
        '_active', '_active_saved_visible', '_active_saved_collidable',
        '_mode', '_mode_time', 'model', '_ink',
        '_on_update', '_on_destroy', '_mode_script', '_frozen_warned', '_mode_idle_from',
        '_actor_constructed',
        '_geom_path', '_geom_path_key', '_tx_state',
        '_collision_epoch',
        '_plain_blit',
        '_draw_index',
        '__weakref__',
    )

    # Merged class look / size defaults from ``class X(Circle, radius=8, color=…)``.
    _shape_defaults: Dict[str, Any] = {}
    # Home-model gradual construction (None = no home fill; Point / Polygon).
    _HOME_KEYS: Optional[frozenset] = None
    _HOME_OPTIONAL_KEYS: frozenset = frozenset()
    _HOME_SIZE_KEYS: frozenset = frozenset()

    @classmethod
    def _class_keywords(cls) -> frozenset:
        return _SHAPE_STYLE_KEYS | (getattr(cls, '_HOME_SIZE_KEYS', frozenset()) or frozenset())

    def __init_subclass__(cls, **kwargs):
        incoming: Dict[str, Any] = {}
        unexpected: Dict[str, Any] = {}
        allowed = cls._class_keywords()
        for key in list(kwargs):
            if key in allowed:
                incoming[key] = kwargs.pop(key)
            elif key in _SHAPE_PLACEMENT_KEYS:
                raise TypeError(
                    f"{key}= is instance placement, not a class default. "
                    f"Pass {key}= when constructing {cls.__name__}(...)."
                )
            else:
                unexpected[key] = kwargs.pop(key)
        if unexpected:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(
                cls.__name__,
                unexpected,
                valid=allowed,
                where="class defaults",
            )
        merged: Dict[str, Any] = {}
        for base in cls.__mro__[1:]:
            base_defs = getattr(base, '_shape_defaults', None)
            if base_defs:
                merged = dict(base_defs)
                break
        merged.update(incoming)
        cls._shape_defaults = merged
        super().__init_subclass__(**kwargs)
        _install_timed_pose(cls)

    @classmethod
    def _apply_home_fill(cls, kwargs: Dict[str, Any]) -> None:
        """Inject omitted home keys: class size defaults, then pose. Mutates ``kwargs``."""
        home_keys = cls._HOME_KEYS
        if not home_keys:
            return
        defaults = getattr(cls, '_shape_defaults', None) or {}
        size_keys = getattr(cls, '_HOME_SIZE_KEYS', frozenset()) or frozenset()
        optional = getattr(cls, '_HOME_OPTIONAL_KEYS', frozenset()) or frozenset()
        for key in home_keys | optional:
            if key not in kwargs and key in size_keys and key in defaults:
                kwargs[key] = defaults[key]
        pose = cls._home_pose_values(kwargs)
        for key in home_keys:
            if key not in kwargs:
                kwargs[key] = pose[key]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Pose defaults for omitted home keys. Subclasses with ``_HOME_KEYS`` override."""
        raise NotImplementedError(
            f"{cls.__name__} must implement _home_pose_values for home fill"
        )

    def __init__(self, *, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, Sequence[str]]] = None,
                 visual: Optional[LookLike] = None, color: Optional[ColorLike] = None,
                 line_width: Optional[float] = None):
        self._construct(layer=layer, group=group, visual=visual, color=color, line_width=line_width)

    def _construct(self, *, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, Sequence[str]]] = None,
                 attr_name: Optional[str] = None, owner: Optional[Container] = None,
                 visual: Optional[LookLike] = None, color: Optional[ColorLike] = None,
                 line_width: Optional[float] = None):

        if visual is not None and color is not None:
            raise ValueError("use color= or visual=, not both")
        if line_width is not None:
            from .validate import magnitude
            line_width = fixed_magnitude(line_width, "line_width")

        # PaintState before Container so look/style slots exist before parts.
        PaintState.__init__(self)
        Graphic._construct(
            self,
            layer=layer,
            group=group,
            attr_name=attr_name,
            owner=owner,
        )

        # Thickness is not part of the primary package. Omit keeps the prototype.
        # Written before the look: after it, the write would re-apply the look
        # (same picture, one more apply).
        if line_width is not None:
            self.line_width = line_width
        # Appearance: color= writes the primary paint package (not a Paint costume).
        # Mutually exclusive with visual=. set_color uses fill on area shapes, stroke on Line.
        if color is not None:
            self.set_color(color)
        elif visual is not None:
            self.visual = visual

        # All shapes expose ``center`` (Point or Point-like) for pivots / drag / move_to.
        # Subclasses must implement it (ContainerSlot, property alias, etc.).

    def __str__(self) -> str:
        """String representation of the shape."""
        from .entity import made_at
        where = made_at(self)
        return f"{self._name} ({where})" if where else self._name

    def __repr__(self) -> str:
        return self.__str__()

    @property
    def center(self) -> 'Point':
        """Geometric center / default pivot. Every Shape subclass must provide this."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement a center Point (slot or property)"
        )

    # ``clone(center=)`` moves the geometry copy there (``Graphic.clone``, PC1).
    _clone_places_center = True

    def _clone_recipe(self, *, center=None, frame=None, **kwargs) -> 'Shape':
        """Shape clone builds via ``_clone_geometry``. ``Graphic.clone`` reads
        ``center=`` first and moves the copy after its pose; a Shape has no
        frames (``frame=`` refuses there)."""
        return self._clone_geometry(**kwargs)

    def _publish_angle_input(self) -> None:
        """Where ``angle`` is a Defining input of the current model (Rect,
        Square, Ellipse by size, Line by length, RegularPolygon …), the pose
        store follows an ``angle =`` write. It lagged until the next verb on
        every such kind: nothing drew wrong, because each verb reads ``angle``
        and republishes, but any reader of ``_rotation`` in between saw the old
        heading. Batched verbs publish themselves (``_pose_rotation_add``).

        Per-frame path (``ship.angle = …``): the stored value is read raw and
        the store written directly; the full ``_pose_rotation_set`` (property
        anchor notify) only when the shape has anchors. No collision-epoch
        bump: the pose key already reads the ``angle`` slot."""
        if self._in_batch_update:
            return
        d = self.__dict__
        defining = d.get('_defining_part_names')
        if not defining or 'angle' not in defining:
            return
        v = d.get('angle')
        if type(v) is not float:
            v = _bare_num(self.angle)
        if d.get('_field_anchors'):
            _pose_rotation_set(self, v)
        else:
            object.__setattr__(self, '_rotation', v)

    def _takein_pose(self, other) -> None:
        """A whole-object copy (``<<``, ``absorb``, a whole ``@=`` pull) carries
        the source's pose: flips, heading with its turn count, scale (C7).
        Before, a copy read alike but diverged on the next ``rotate_to`` /
        ``flip`` (SC7 / SB7)."""
        from .entity import Graphic
        if isinstance(other, Graphic):
            if other is not self:
                self._clone_pose_from(other)
            return
        # A source with no pose (``rect << box``): the heading is the copy's own
        # Defining ``angle``, which the takein stored raw; the store kept the old
        # heading (sentinel I-heading, geometry campaign wave 2).
        defining = self.__dict__.get('_defining_part_names')
        if defining and 'angle' in defining:
            _pose_rotation_set(self, self._rotation_value())

    def _drop_relational(self) -> None:
        """The relation is gone: a relational model becomes its free twin,
        keeping the values it has, and every link that reads the reference is
        removed with it (Q3b in Testing Design: no hybrid). Reached from every
        way a relation goes: ``force=True`` (SB5: a forced move then did
        nothing), ``unlink()`` / ``unlink_all()`` of a relational link, and a
        destroyed reference (which unlinks its dependents): see
        ``_relation_unlinked``."""
        model = getattr(self, 'model', None)
        if model is None or self._free_model(model) is model:
            return
        d = self.__dict__
        if d.get('_dropping_relation'):
            return                          # the unlinks below come back here
        d['_dropping_relation'] = True
        try:
            free = self._free_model(model)
            old = set(d.get('_defining_part_names') or ())
            # The parts that become inputs keep the value they read now (a cold
            # computed field would otherwise start from its slot default).
            keep = {}
            for name in (self._defining_names_for(free) or ()):
                if name in old:
                    continue
                value = getattr(self, name)
                keep[name] = get_xy(value, bare=True) if isinstance(value, Point) else _bare_num(value)
            ref = d.get('_ref')
            if ref is not None:
                for node in list(self._iter_subtree()):
                    if node._link is not None and _link_reads(node._link, ref):
                        node.unlink()           # keeps its current value
            self._adopt_model_of(self)
            d['_ref'] = None
            for name, value in keep.items():
                if isinstance(value, tuple):
                    getattr(self, name)._takein(value)
                else:
                    _init_scalar(self, name, value)
            if 'angle' in (d.get('_defining_part_names') or ()):
                # A heading that becomes an input publishes the store, which a
                # tangent's ``at_angle`` pull never moved (sentinel I-heading).
                object.__setattr__(self, '_rotation', float(self._rotation_value()))
        finally:
            d.pop('_dropping_relation', None)

    def _relation_unlinked(self, link) -> None:
        """A part's link was removed (``Container.unlink``): if it carried the
        relation, the shape becomes its free twin."""
        d = self.__dict__
        if d.get('_destroyed') or d.get('_ref') is None:
            return                          # its own teardown unlinks its parts
        if _link_reads(link, d['_ref']):
            self._drop_relational()

    def _clone_geometry(self, **kwargs) -> 'Shape':
        """Construct a free (unlinked) copy with matching geometry. Subclasses implement."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement _clone_geometry for clone()"
        )

    @property
    def visible(self) -> bool:
        """Draw it or not (``True`` / ``False``). Hiding only stops drawing (and clicks);
        to take a shape out of the game, park it with ``.active = False``."""
        return self._visible

    @visible.setter 
    def visible(self, value: bool) -> None:
        _refuse_if_destroyed(self, "visible")
        value = expect_bool(value, f"{type(self).__name__}.visible")
        if _parked(self):
            _stash_flag(self, "visible", value)  # parked stays hidden; resume applies
            return
        if value != self._visible:
            self._visible = value
            self._sync_interactive_registry()

    def _sync_interactive_registry(self) -> None:
        """Keep Registry interactive list in sync with flags + visibility."""
        active = (
            self._visible
            and (
                self._clickable or self._draggable or self._droppable or self._wheel_rotate
                or self._on_hover is not None or self._on_hover_exit is not None
            )
        )
        registry = self._scenacanvas.registry
        registry.set_interactive(self, active)
        # A held press / hover cannot outlive what made it possible (hidden,
        # parked, no longer pressable). No author callback runs here: the
        # hover exit waits for the next ``step_hover``.
        for manager in list(getattr(registry, "_pointer_managers", ()) or ()):
            manager.forget_pointer_target(self)

    @property
    def clickable(self) -> bool:
        """Receives clicks (``on_click`` / ``@click``). Set automatically when ``on_click`` is set."""
        return self._clickable

    @clickable.setter
    def clickable(self, value: bool) -> None:
        value = _expect_flag(value, 'clickable')
        if value != self._clickable:
            if value:
                self._reject_if_parallax_layer("clickable")
            self._clickable = value
            self._sync_interactive_registry()

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        """Defining parts ``move_to`` / ``_move_by`` write. Override per shape/model."""
        return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        """Parts ``rotate_by`` about center writes (wheel_rotate path).

        Include ``self["angle"]`` (a FieldRef) whenever the gesture updates
        the heading — a ``_PropertyAnchor``-backed ``angle`` (Point / Sprite /
        Text / Polygon, derived models) or a real ``ScalarSlot`` (Rect /
        Ellipse / Line / Circle / …). Same for a future scale gesture and
        ``self["scale"]``.
        """
        return (self["angle"],)

    def _parts_written_by_resolve(self) -> Tuple:
        """Parts standing ``resolve()`` / settle / floor-snap write (usually center)."""
        center = getattr(self, "center", None)
        if center is None:
            return ()
        return (center,)

    def _ensure_drag_parts_writable(self) -> None:
        for part in self._parts_written_by_drag():
            _ensure_writable(part, "set draggable")

    def _ensure_wheel_rotate_parts_writable(self) -> None:
        for part in self._parts_written_by_wheel_rotate():
            _ensure_writable(part, "set wheel_rotate")

    def _ensure_resolve_parts_writable(self, group: Optional[str] = None) -> None:
        """Formula check for standing ``resolve()``; ``group`` = the tag that enrolled us."""
        context = undo_extra = ""
        if group is not None:
            context = f', group "{group}"'
            if self.__dict__.get("_clone_note"):
                undo_extra = f', or keep the clone out of "{group}" with clone(group=None)'
            else:
                undo_extra = f', or take it out of group "{group}"'
        for part in self._parts_written_by_resolve():
            _ensure_writable(part, "resolve()", context=context, undo_extra=undo_extra)

    def _note_resolve_enroll(self, group: Optional[str] = None) -> None:
        """Mark this Graphic as claimed by standing ``resolve()`` (idempotent)."""
        if getattr(self, "_resolve_enrolled", False):
            return
        self._ensure_resolve_parts_writable(group)
        self._resolve_enrolled = True

    def _note_resolve_unenroll(self) -> None:
        """Clear standing ``resolve()`` claim when no longer on any resolve side."""
        self._resolve_enrolled = False
        self._resolve_enroll_count = 0

    def _ensure_can_link_attribute(self, target: Container) -> None:
        """Reject inbound links that would conflict with persistent drivers.

        Called from ``Container._assign_formula`` for every Shape on the owner
        chain. Outbound links *to* this shape are fine (checked on the other side).
        Property-anchored ``angle`` / ``scale`` are covered when listed in
        ``_parts_written_by_*`` as FieldRefs — no per-family special case.
        """
        from .entity import entity_label, part_path

        def refuse(part, existing: str, undo: str):
            name = part_path(part, self) if not isinstance(part, FieldRef) else str(part.name)
            raise LinkedAttributeError(
                driver_conflict_message(
                    new="link",
                    subject=entity_label(self),
                    part=name,
                    existing=existing,
                    undo=f"{undo}, or leave {name} unlinked",
                )
            )

        if self._draggable:
            for part in self._parts_written_by_drag():
                if _link_overlaps_part(target, part):
                    refuse(part, "draggable = True drags it", "Set draggable = False first")
        if self._wheel_rotate:
            for part in self._parts_written_by_wheel_rotate():
                if _link_overlaps_part(target, part):
                    refuse(
                        part, "wheel_rotate = True turns it",
                        "Set wheel_rotate = False first",
                    )
        if getattr(self, "_resolve_enrolled", False):
            for part in self._parts_written_by_resolve():
                if _link_overlaps_part(target, part):
                    from .collision import resolve_calls_for
                    calls = resolve_calls_for(self)
                    if calls:
                        existing = " and ".join(f"resolve{c}" for c in calls) + " nudges it"
                        undo = "Call " + " and ".join(f"unresolve{c}" for c in calls) + " first"
                    else:
                        existing = "resolve() nudges it"
                        undo = "Call unresolve(a, b) for its pair first"
                    refuse(part, existing, undo)

    @property
    def draggable(self) -> bool:
        """Can be dragged with the mouse. Set automatically by ``on_drag_to`` / ``on_drag_over``."""
        return self._draggable

    @draggable.setter
    def draggable(self, value: bool) -> None:
        value = _expect_flag(value, 'draggable')
        if value and not self._draggable:
            self._reject_if_parallax_layer("draggable")
            self._ensure_drag_parts_writable()
        if value != self._draggable:
            self._draggable = value
            self._sync_interactive_registry()
        if not value:
            # A pointer hold in progress ends now: held motion runs again at
            # once (the pointer manager drops the drag on its next event).
            from .process import release_hold
            release_hold(self)

    def _iter_defining_points(self):
        """Yield owned Defining ``Point`` parts (and ``self`` when it is a Point)."""
        if isinstance(self, Point):
            yield self
            return
        for part in self._parts:
            if isinstance(part, Point) and (
                getattr(part, '_field_type', FieldType.Defining) == FieldType.Defining
            ):
                yield part

    def _iter_free_defining_points(self):
        """Yield Defining Points with no inbound link: not in their subtree, and
        not on the shape (a whole-object link drives every point; GR10 —
        ``show_handles()`` registered handles, then refused)."""
        if self._link is not None or self._formula_driven_ancestor() is not None:
            return
        for part in self._iter_defining_points():
            if any(node._link is not None for node in part._iter_subtree()):
                continue
            yield part

    def _iter_point_slot_names(self) -> List[str]:
        """Names of ``Point`` ContainerSlots declared on this shape's class."""
        names: List[str] = []
        seen = set()
        for cls in type(self).mro():
            for key, val in vars(cls).items():
                if key in seen:
                    continue
                if isinstance(val, ContainerSlot) and issubclass(val.container_class, Point):
                    seen.add(key)
                    names.append(key)
        return names

    def _include_point_slot_in_debug(self, name: str) -> bool:
        """Whether ``show_points`` may materialize the named Point slot.

        Override to skip inactive alternate-model inputs (e.g. RegularPolygon.vertex
        when the model is not VERTEX_SIDE) or redundant aliases (centroid vs center).
        """
        return True

    def _iter_debug_points(self, *, materialize: bool = False):
        """Yield Point parts for geometry debugging.

        With ``materialize=False``, only already-created Points (no cold Derivate
        access). With ``materialize=True``, also access declared Point slots and
        dynamic vertices (marks cold Derivates live — debug cost until released).
        Each Point is yielded at most once (by identity).
        """
        if isinstance(self, Point):
            yield self
            return

        seen: set = set()
        vertex_ids = {id(v) for v in (getattr(self, '_vertices', None) or ())}
        for part in list(self._parts):
            if not isinstance(part, Point) or id(part) in seen:
                continue
            # When materializing, defer dynamic vertices to the ensure/place loop
            # below — cold verts sit at (0,0) and would false-dedup each other.
            if materialize and id(part) in vertex_ids:
                continue
            attr = getattr(part, '_attr_name', None)
            if attr and not self._include_point_slot_in_debug(attr):
                continue
            seen.add(id(part))
            yield part

        if not materialize:
            return

        for name in self._iter_point_slot_names():
            if not self._include_point_slot_in_debug(name):
                continue
            part = getattr(self, name)  # may materialize a cold Derivate
            if isinstance(part, Point) and id(part) not in seen:
                seen.add(id(part))
                yield part

        vertices = getattr(self, '_vertices', None)
        if not vertices:
            return
        for i, vtx in enumerate(vertices):
            if not isinstance(vtx, Point):
                continue
            if (
                getattr(vtx, '_field_type', None) == FieldType.Derivate
                and not vtx._is_derivate_live()
            ):
                ensure = getattr(self, '_ensure_vertex_live', None)
                if ensure is not None:
                    ensure(i)
                else:
                    vtx._derivate_live = True
                    vtx._flag_pull_consumers()
            if id(vtx) not in seen:
                seen.add(id(vtx))
                yield vtx

    @staticmethod
    def _marker_xy_key(point: 'Point', places: int = 4) -> Tuple[float, float]:
        x, y = get_xy(point, bare=True)
        return (round(float(x), places), round(float(y), places))

    def show_handles(self) -> 'Shape':
        """Show free Defining Points as editable handles (``Point.handle``).

        Linked Defining Points are **skipped** (no error) so bulk enable stays
        gradual. Setting ``point.handle = True`` on a linked Point still raises
        ``LinkedAttributeError``. Derivate Points are never included.
        Does not set whole-shape ``draggable``. Returns ``self`` for chaining.
        Raises ``DestroyedError`` on a destroyed shape (A7).
        """
        from .entity import _refuse_if_destroyed
        _refuse_if_destroyed(self, "show_handles")
        for p in self._iter_free_defining_points():
            p.handle = True
        return self

    def no_handles(self) -> 'Shape':
        """Hide Defining Point markers and clear their ``handle`` role."""
        for p in self._iter_defining_points():
            p.handle = False
            p.visible = False
        return self

    def show_points(self) -> 'Shape':
        """Show all Point parts for geometry debugging (Defining + Derivate).

        Named ``show_points`` (not ``points``) so it does not clash with
        ``Polygon.points`` / ``RegularPolygon.points`` vertex accessors.

        Materializes cold Derivate Points (they become live and refresh each
        cycle). Markers are visible only — not handles. Prefer ``show_handles()``
        for editable Defining loci. Pair with ``no_points`` to drop markers
        and release Derivate liveness when nothing else depends on them.

        Coincident Points (same world position) are shown once: an existing
        handle wins over a guide; otherwise the first marker keeps the spot.
        Raises ``DestroyedError`` on a destroyed shape (A7).
        """
        from .entity import _refuse_if_destroyed
        _refuse_if_destroyed(self, "show_points")
        tracked = getattr(self, '_debug_points', None)
        if tracked is None:
            self._debug_points = tracked = []

        was_cold: set = set()
        for part in self._parts:
            if (
                isinstance(part, Point)
                and getattr(part, '_field_type', None) == FieldType.Derivate
                and not part._is_derivate_live()
            ):
                was_cold.add(id(part))
        for name in self._iter_point_slot_names():
            if name not in self.__dict__ and self._include_point_slot_in_debug(name):
                was_cold.add(name)
        for vtx in getattr(self, '_vertices', None) or ():
            if (
                isinstance(vtx, Point)
                and getattr(vtx, '_field_type', None) == FieldType.Derivate
                and not vtx._is_derivate_live()
            ):
                was_cold.add(id(vtx))

        # Prefer handles / already-visible markers at a given locus.
        occupied: Dict[Tuple[float, float], Point] = {}
        for p in self._iter_debug_points(materialize=False):
            if p.visible or p.handle:
                occupied[self._marker_xy_key(p)] = p

        for p in self._iter_debug_points(materialize=True):
            key = self._marker_xy_key(p)
            existing = occupied.get(key)
            if existing is not None and existing is not p:
                # Another marker already owns this locus (handle preferred).
                continue

            if p.handle:
                # Already the handle glyph; do not also treat as a debug guide.
                occupied[key] = p
                if p not in tracked:
                    tracked.append(p)
                continue

            # Re-show after no_points leaves named Derivate slots in __dict__
            # with _derivate_live=False. Revive + refresh so _update_impl tracks
            # them again (Rect/Square corners, VERTEX_SIDE center, etc.).
            # Vertices are already revived in _iter_debug_points via
            # _ensure_vertex_live; this covers ContainerSlot Points.
            if (
                getattr(p, '_field_type', None) == FieldType.Derivate
                and not p._is_derivate_live()
            ):
                p._derivate_live = True
                p._flag_pull_consumers()
                materialize = getattr(self, '_materialize_derivate_part', None)
                attr = getattr(p, '_attr_name', None)
                if materialize is not None and attr:
                    materialize(attr)
                p._debug_made_live = True
            elif id(p) in was_cold or getattr(p, '_attr_name', None) in was_cold:
                p._debug_made_live = True

            p.visible = True
            occupied[key] = p
            if p not in tracked:
                tracked.append(p)
        return self

    def no_points(self) -> 'Shape':
        """Hide debug Point markers; release Derivate liveness if unused."""
        tracked = getattr(self, '_debug_points', None) or []
        for p in list(tracked):
            if not p.handle:
                p.visible = False
            if getattr(p, '_debug_made_live', False):
                if not p._has_external_dependents():
                    p._derivate_live = False
                p._debug_made_live = False
        self._debug_points = []
        return self

    @property
    def droppable(self) -> bool:
        """Is a drop target for dragged shapes (``on_drop_by`` / ``@drop_by``)."""
        return self._droppable

    @droppable.setter
    def droppable(self, value: bool) -> None:
        value = _expect_flag(value, 'droppable')
        if value != self._droppable:
            if value:
                self._reject_if_parallax_layer("droppable")
            self._droppable = value
            self._sync_interactive_registry()

    @property
    def wheel_rotate(self) -> bool:
        """If True, mouse-wheel rotates this shape while the mouse is held on it."""
        return self._wheel_rotate

    @wheel_rotate.setter
    def wheel_rotate(self, value: bool) -> None:
        value = _expect_flag(value, 'wheel_rotate')
        if value and not self._wheel_rotate:
            self._reject_if_parallax_layer("wheel_rotate")
            self._ensure_wheel_rotate_parts_writable()
        if value != self._wheel_rotate:
            self._wheel_rotate = value
            # The pointer only reaches what the registry lists (SA9: the
            # documented one-liner ``wheel_rotate = True`` did nothing alone).
            self._sync_interactive_registry()

    @property
    def on_click(self):
        """Function called on a click, ``fn(shape)``, or ``None``. Setting it makes the shape clickable."""
        return self._on_click

    @on_click.setter
    def on_click(self, value) -> None:
        self._on_click = _check_pointer_handler(value, ("shape",), what="on_click")
        self.clickable = value is not None

    def _draggable_from_callbacks(self, on: bool) -> None:
        """A drag callback set or cleared turns ``draggable`` on or off (an
        Anchor overrides: it is always draggable)."""
        self.draggable = on

    @property
    def on_drag_to(self):
        """Called when a drag of this shape ends: ``fn(from_shape, to_shape_or_None, pos)``."""
        return self._on_drag_to

    @on_drag_to.setter
    def on_drag_to(self, value) -> None:
        self._on_drag_to = _check_pointer_handler(
            value, ("from_shape", "to_shape", "pos"), what="on_drag_to")
        self._draggable_from_callbacks(value is not None or self._on_drag_over is not None)

    @property
    def on_drag_over(self):
        """Called while this shape is dragged: ``fn(from_shape, to_shape_or_None, pos)``."""
        return self._on_drag_over

    @on_drag_over.setter
    def on_drag_over(self, value) -> None:
        self._on_drag_over = _check_pointer_handler(
            value, ("from_shape", "to_shape", "pos"), what="on_drag_over")
        self._draggable_from_callbacks(value is not None or self._on_drag_to is not None)

    @property
    def on_drop_by(self):
        """Called on this drop target when something is dropped on it: ``fn(from_shape, to_shape, pos)``."""
        return self._on_drop_by

    @on_drop_by.setter
    def on_drop_by(self, value) -> None:
        self._on_drop_by = _check_pointer_handler(
            value, ("from_shape", "to_shape", "pos"), what="on_drop_by")
        self.droppable = value is not None

    @property
    def on_hover(self):
        """Called when the pointer starts hovering this shape, ``fn(shape)``, or ``None``.

        Setting it makes the shape a hover target without making it clickable:
        clicks pass through to what is below.
        """
        return self._on_hover

    @on_hover.setter
    def on_hover(self, value) -> None:
        value = _check_pointer_handler(value, ("shape",), what="on_hover")
        if value is not None:
            self._reject_if_parallax_layer("on_hover")
        self._on_hover = value
        self._sync_interactive_registry()

    @property
    def on_hover_exit(self):
        """Called when the pointer stops hovering this shape, ``fn(shape)``, or ``None``."""
        return self._on_hover_exit

    @on_hover_exit.setter
    def on_hover_exit(self, value) -> None:
        value = _check_pointer_handler(value, ("shape",), what="on_hover_exit")
        if value is not None:
            self._reject_if_parallax_layer("on_hover_exit")
        self._on_hover_exit = value
        self._sync_interactive_registry()

    def _no_click(self) -> 'Shape':
        """Clear ``on_click`` and ``clickable``."""
        self.on_click = None
        return self

    def no_drag(self) -> 'Shape':
        """Clear drag callbacks and ``draggable``."""
        self.on_drag_to = None
        self.on_drag_over = None
        return self

    def no_drop(self) -> 'Shape':
        """Clear ``on_drop_by`` and ``droppable``."""
        self.on_drop_by = None
        return self

    def no_wheel_rotate(self) -> 'Shape':
        """Clear ``wheel_rotate``."""
        self.wheel_rotate = False
        return self

    def contains_point(self, x, y=None) -> bool:
        """Pointer hit-test in design space (same coords as ``mouse.x`` / ``mouse.y``).

        Two spellings: ``contains_point(x, y)`` or ``contains_point(p)`` where
        ``p`` is Point, Vec2, ``(x, y)``, mouse, or an object with ``.center`` /
        ``.x``/``.y``. Same test ``@click`` / ``pointer_hover`` use (draw
        geometry, not the collision hitbox). Sprite: current-frame alpha,
        not the PNG rect and not the hitbox. Circle: the filled arc
        (pie or chord). Rect ``corner_radius`` rounds the pointer fill;
        collision stays the oriented box.

        A destroyed actor (or a part of one) contains nothing: a destroyed
        object is nowhere, as for ``collision.query_point``. A parked actor
        keeps its geometric answer (park turns collision off, not geometry).
        """
        if y is None:
            px, py = _xy_of(x, required=True)
        else:
            px, py = _xy_of((x, y), required=True)   # numbers, finite (SA15)
        if getattr(self, "_destroyed", False) or getattr(self, "_host_destroyed", False):
            return False                     # review 2026-10-09 S6-8
        # A linked angle / scale is pulled, as draw and collision pull it: an
        # undrawn shape answered with its old pose (review 2026-10-09 S6-6).
        # One dict probe when nothing is linked (the pointer walk is hot).
        if self.__dict__.get("_field_anchors") or getattr(type(self), "_is_hitbox_part", False):
            type(self)._pull_property_anchors(self)
        return self._hit_test_xy(px, py)

    @property
    def is_collapsed(self) -> bool:
        """True when body extent has no interior (at least one axis ``0``).

        Uses ``_oriented_frame`` when present (Rect / Square). Circle, Ellipse,
        Line, RegularPolygon override. Point / free Polygon / Track stay False.
        Scale ``0`` is collapsed even when baked geometry sits at ``MIN_SCALE``.
        """
        if float(self._scale) == 0.0:
            return True
        frame = getattr(self, "_oriented_frame", None)
        if not callable(frame):
            return False
        _cx, _cy, w, h, _ang = frame()
        return w == 0.0 or h == 0.0

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Subclass geometry after ``contains_point`` unpacks author args."""
        return False

    def _set_pointer_hover(self, hovered: bool) -> None:
        """Framework-driven hover bit (topmost pressable under the cursor)."""
        hovered = bool(hovered)
        if hovered == self._pointer_hover:
            return
        self._pointer_hover = hovered
        self._on_pointer_hover_changed()

    def _on_pointer_hover_changed(self) -> None:
        """Subclass hook when pointer hover enter/leave changes."""
        pass

    @property
    def pointer_hover(self) -> bool:
        """True when this shape is the hover target: the topmost clickable, draggable or hover-handler shape under the pointer (read-only; updated once per frame)."""
        return self._pointer_hover

    def _set_pointer_pressed(self, pressed: bool) -> None:
        """Framework-driven press bit (held on this shape and the pointer over it)."""
        pressed = bool(pressed)
        if pressed == self._pointer_pressed:
            return
        self._pointer_pressed = pressed
        self._on_pointer_pressed_changed()

    def _on_pointer_pressed_changed(self) -> None:
        """Subclass hook when the press bit changes."""
        pass

    @property
    def pointer_pressed(self) -> bool:
        """True while the left button, pressed on this shape, is held and the pointer is over it (read-only).

        Goes False when the pointer leaves (a release there would not click)
        and True again when it comes back; a drag keeps it True. Ends on
        release, and when the shape is hidden, parked, destroyed, stops being
        clickable / draggable, or a modal menu opens.
        """
        return self._pointer_pressed

    def _accepts_press(self) -> bool:
        """Engine hook: False swallows a press on this shape (no click, no drag)."""
        return True

    def _fire_click(self) -> None:
        """Engine hook: run the click handler (press + release inside)."""
        from .validate import call_truncated
        call_truncated(self.on_click, self)

    def move_to_front(self) -> 'Shape':
        """Move this shape to the end of its layer's draw list (topmost within the layer)."""
        self._scenacanvas.registry.move_to_front(self)
        return self

    def move_to_back(self) -> 'Shape':
        """Move this shape to the start of its layer's draw list (bottommost within the layer)."""
        self._scenacanvas.registry.move_to_back(self)
        return self

    def _apply_flip(self, axis: str, value, *, force: bool = False) -> None:
        """Rewrite geometry so a mirror reads back true. ``force`` unlinks.

        Check, then write (graphics review R2): a dead actor and a linked pose
        refuse before anything changes, and every ``_mirror_geometry`` gates all
        its parts before it writes one. The flag goes first (mirror code reads
        it) and is put back if the mirror refuses (SA5 / SC3 / E14)."""
        value = bool(value)
        flag = "_flip_x" if axis == "x" else "_flip_y"
        if value == bool(getattr(self, flag, False)):
            return
        _refuse_if_destroyed(self, f"flip_{axis}")
        rot = float(self._rotation)
        turned = (180.0 - rot) if axis == "x" else -rot
        # A flip is a pose write; the heading is gated only when it changes.
        _gate_pose_anchor(self, "angle" if turned != rot else None, "flip", force)
        object.__setattr__(self, flag, value)
        bump_pose_rev(self)
        try:
            self._mirror_geometry(axis, force=force)
        except BaseException:
            object.__setattr__(self, flag, not value)
            raise

    def _mirror_points(self):
        # Parts live in the instance dict (getattr would not pull either).
        d = self.__dict__
        out = []
        for name in d.get('_defining_part_names') or ():
            pt = d.get(name)
            if pt is None:
                pt = getattr(self, name, None)
            if isinstance(pt, Point):
                out.append(pt)
        return out

    def _mirror_scalar_parts(self, axis: str) -> List:
        """The Defining scalars / vector a mirror rewrites (gated before any write)."""
        names = getattr(self, "_defining_part_names", ()) or ()
        out = []
        if "angle" in names:
            out.append(self["angle"])
        if "dx" in names and axis == "x":
            out.append(self["dx"])
        if "dy" in names and axis == "y":
            out.append(self["dy"])
        if "vec" in names:
            out.append(self.vec)
        return out

    def _mirror_scalars(self, axis: str, names) -> None:
        # Gated by the caller (``_mirror_geometry``, every part before any write).
        if "angle" in names:
            ang = _bare_num(self.angle)
            self.angle = (180.0 - ang) if axis == "x" else -ang
        if "dx" in names and axis == "x":
            self.dx = -_bare_num(self.dx)
        if "dy" in names and axis == "y":
            self.dy = -_bare_num(self.dy)
        if "vec" in names:
            if axis == "x":
                self.vec.x = -_bare_num(self.vec.x)
            else:
                self.vec.y = -_bare_num(self.vec.y)

    def _mirror_geometry(self, axis: str, *, force: bool = False) -> None:
        cx, cy = self._center_xy()
        points = self._mirror_points()
        # Every part first: a linked vertex k used to leave vertices 0..k-1 mirrored.
        for pt in points:
            _ensure_writable(pt, "flip", force=force, pivot=(cx, cy))
        for part in self._mirror_scalar_parts(axis):
            _ensure_writable(part, "flip", force=force)
        names = getattr(self, "_defining_part_names", ()) or ()
        turned = False
        if "angle" not in names:
            # A heading kept only as pose (Point, Polygon, a p1/p2 Line) mirrors
            # by the convention too — it used to stay put. Set it before the
            # points move: a derived heading is unwrapped toward the pose store,
            # and a zero-length segment has no direction of its own, so it reads
            # the store as it is during the update (GX2 in Testing Design).
            rot = float(self._rotation)
            new = (180.0 - rot) if axis == "x" else -rot
            _pose_rotation_set(self, new)
            turned = new != rot
        moved = False
        for pt in points:
            x, y = get_xy(pt, bare=True)
            nxy = (2.0 * cx - x, y) if axis == "x" else (x, 2.0 * cy - y)
            if nxy != (x, y):
                moved = True
                pt._takein(nxy)
        self._mirror_scalars(axis, names)
        if turned and not moved:
            # A point write is what refreshes a derived heading. With none (a
            # zero-length segment, a diameter on the mirror axis) a warm
            # ``angle`` kept its pre-flip value while the store turned (GX2,
            # GX21). A batch around the writes did it too, but cost every
            # flip 3-7 us.
            self.update()

    def _center_xy(self) -> Tuple[float, float]:
        """Bare center from current Defining pose when possible.

        Prefer ``_oriented_frame()`` (always derived from Defining parts) over
        a possibly-stale Derivate ``center`` cache. Falls back to ``self.center``.
        """
        oriented = getattr(self, '_oriented_frame', None)
        if callable(oriented):
            cx, cy, *_rest = oriented()
            return cx, cy
        return get_xy(self.center, bare=True)

    def _rotation_value(self) -> float:
        """The heading from Defining inputs (``_oriented_frame`` when the kind
        has one). ``angle`` is a Derivate on some models (Rect spine, Ellipse
        foci, a p1/p2 Line); reading it would wake it (D3 in Testing Design).
        Engine readers use this, never ``.angle``."""
        oriented = getattr(self, '_oriented_frame', None)
        if callable(oriented):
            return float(oriented()[4])
        return _bare_num(self.angle)

    def _pivot_xy(self, about: Optional[GeneralPoint] = None) -> Tuple[float, float]:
        """Resolve pivot to bare (x, y); default is shape center.

        ``about=None`` stays on ``_center_xy`` (the common rotate/scale path).
        An explicit pivot is any point-like, including mouse.
        """
        if about is None:
            return self._center_xy()
        return _xy_of(about, required=True)

    @property
    def angle(self) -> float:
        """The heading in degrees: where the graphic points (0 = +x, counter-clockwise)."""
        self._pull_property_anchor("angle")
        return self._rotation

    @angle.setter
    def angle(self, value: float) -> None:
        """Set the heading, keeping the point the graphic was placed by.

        Kinds with no heading input (Point, free Polygon, Sprite, Text, Track)
        are placed by their center, so this is ``rotate_to(value)``. Kinds whose
        model has ``angle`` as an input declare it as a geometry slot instead.
        """
        self.rotate_to(_finite_deg(value, "angle"))

    def rotate_to(self, value: float, *, time: Optional[float] = None, speed: Optional[float] = None, ease: str = "linear", then=None, on_done=None, about: Optional[GeneralPoint] = None, force: bool = False, loops: object = 1, yoyo: bool = False) -> Union['Shape', 'Handle']:
        """
        Set absolute rotation in degrees about a pivot (default: center).
        With ``time=``, interpolate the shortest arc (CCW+; 180° tie → CCW) and return a Handle.
        ``speed=`` (degrees per second) instead of ``time=``: the duration is that arc ÷ speed.
        force=True unlinks Defining parts that must be written (default: raise).
        """
        if force is not False and force is not True:      # "no" is truthy: it unlinked
            force = _expect_flag(force, "rotate_to(force=)")
        if time is not None or speed is not None:
            from .process import timed_rotate_to
            return timed_rotate_to(
                self, value, time=time, speed=speed, ease=ease, then=then, on_done=on_done,
                about=about, force=force, loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, speed=speed, then=then, on_done=on_done, ease=ease, call_name="rotate_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="rotate_to")
        delta = _finite_deg(value, "rotate_to angle") - float(self.angle)
        if about is not None:
            # Placement: the orbit this turn makes is not motion.
            return _rotate_as_placement(self.rotate_by, delta, about=about, force=force)
        return self.rotate_by(delta, about=about, force=force)

    def rotate_by(self, angle: float, *, time: Optional[float] = None, speed: Optional[float] = None, ease: str = "linear", then=None, on_done=None, about: Optional[GeneralPoint] = None, force: bool = False, loops: object = 1, yoyo: bool = False) -> Union['Shape', 'Handle']:
        """Rotate by angle degrees about a pivot (default: center).

        With ``time=``, interpolate the signed delta as written (Handle).
        ``speed=`` (degrees per second) instead of ``time=``: the duration is |angle| ÷ speed.
        Default Graphic path (Sprite): CTM ``_rotation``; orbit ``center`` when
        ``about`` is not the pose pivot. Geometry subclasses override.
        """
        if force is not False and force is not True:      # "no" is truthy: it unlinked
            force = _expect_flag(force, "rotate_by(force=)")
        if time is not None or speed is not None:
            from .process import timed_rotate_by
            return timed_rotate_by(
                self, angle, time=time, speed=speed, ease=ease, then=then, on_done=on_done,
                about=about, force=force, loops=loops, yoyo=yoyo,
            )
        _refuse_if_destroyed(self, "rotate_by")
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, speed=speed, then=then, on_done=on_done, ease=ease, call_name="rotate_by")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="rotate_by")
        if about is not None:
            # Orbit: the outermost call notes the center's chord as motion.
            return _rotate_as_motion(
                self, _graphic_rotate_by, angle, {"about": about, "force": force},
            )
        return _graphic_rotate_by(self, angle, about=about, force=force)

    @property
    def scale(self) -> float:
        """Get the uniform scale factor of the object."""
        self._pull_property_anchor("scale")
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        """Alias for scale_to(value) about center. Prefer scale_to/scale_by when pivot ≠ center."""
        from .validate import number
        self.scale_to(number(value, f"{type(self).__name__}.scale"))

    def scale_to(self, value: float, *, time: Optional[float] = None, ease: str = "linear", then=None, on_done=None, about: Optional[GeneralPoint] = None, force: bool = False, loops: object = 1, yoyo: bool = False) -> Union['Shape', 'Handle']:
        """
        Set absolute uniform scale about a pivot (default: center).
        With ``time=``, interpolate and return a Handle.
        force=True unlinks Defining parts that must be written (default: raise).
        """
        if force is not False and force is not True:      # "no" is truthy: it unlinked
            force = _expect_flag(force, "scale_to(force=)")
        if time is not None:
            from .process import timed_scale_to
            return timed_scale_to(
                self, value, time=time, ease=ease, then=then, on_done=on_done,
                about=about, force=force, loops=loops, yoyo=yoyo,
            )
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="scale_to")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="scale_to")
        return _scale_to_via(self, value, about=about, force=force)

    def scale_by(self, factor: float, *, time: Optional[float] = None, ease: str = "linear", then=None, on_done=None, about: Optional[GeneralPoint] = None, force: bool = False, loops: object = 1, yoyo: bool = False) -> Union['Shape', 'Handle']:
        """Multiply uniform scale by factor about a pivot (default: center).

        With ``time=``, interpolate the frozen factor and return a Handle.
        Default Graphic path (Sprite): CTM ``_scale``; orbit ``center`` when
        ``about`` is not the pose pivot. Geometry subclasses override.
        """
        if force is not False and force is not True:      # "no" is truthy: it unlinked
            force = _expect_flag(force, "scale_by(force=)")
        if time is not None:
            from .process import timed_scale_by
            return timed_scale_by(
                self, factor, time=time, ease=ease, then=then, on_done=on_done,
                about=about, force=force, loops=loops, yoyo=yoyo,
            )
        _refuse_if_destroyed(self, "scale_by")
        if then is not None or on_done is not None or ease != "linear":
            from .process import _require_timed_completion
            _require_timed_completion(time=time, then=then, on_done=on_done, ease=ease, call_name="scale_by")
        if loops != 1 or yoyo:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, call_name="scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        old = float(self._scale)
        if geom == 1.0 and store == old:
            return self
        if not _about_is_pose_center(self, about):
            # A pose zoom draws at the stored scale: the center orbits by the
            # same ratio, or the drawing stops being similar below MIN_SCALE
            # (GX5 in Testing Design: the center took the geometry kinds'
            # clamp). A scale of 0 counts as MIN_SCALE, so it can come back.
            factor = (store if store > 0.0 else MIN_SCALE) / (old if old > 0.0 else MIN_SCALE)
            px, py = get_xy(about, bare=True)
            cx, cy = get_xy(self.center, bare=True)
            nx, ny = _scale_xy(cx, cy, px, py, factor)
            if not force and not self._requires_pull_invalidate():
                _takein_xy_float(self.center, nx, ny)
            else:
                self._scale_gate(about, force)
                self.center._takein((nx, ny))
        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        """The checks ``scale_by`` makes before its first write (one per kind;
        the timed verbs run it at the call: ``_scale_gate_at_call``). Here the
        pose zoom: only an orbit about another point moves ``center``."""
        if not _about_is_pose_center(self, about):
            _ensure_writable(self.center, "scale_by", force=force, pivot=get_xy(about, bare=True))

    def move_by(
        self,
        dx: Optional[Union[Vec2, float]] = None,
        dy: Optional[float] = None,
        *,
        angle: Optional[float] = None,
        distance: Optional[float] = None,
        time: Optional[float] = None,
        speed: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        force: bool = False,
        loops: object = 1,
        yoyo: bool = False,
        face: bool = False,
    ) -> Union['Shape', 'Handle']:
        """
        Move by a cartesian delta (dx/dy or Vec2) or polar ``angle=`` + ``distance=``.
        ``distance=`` alone moves along the heading (``.angle``, read at the call);
        negative backs up. Families are exclusive. A Point, Graphic, or mouse is a
        location — use ``move_to``.
        With ``time=``, interpolate the frozen delta and return a Handle.
        ``speed=`` (units per second) instead of ``time=``: the duration is the
        delta's length ÷ speed, read at the call.
        ``face=True`` aims ``.angle`` at the travel direction (zero delta holds);
        it needs an explicit ``angle=`` in the polar family.
        force=True unlinks Defining parts that must be written (default: raise).
        """
        if time is None and (then is not None or on_done is not None or ease != "linear") \
                and speed is None:
            from .process import _require_timed_completion
            _require_timed_completion(time=time, speed=speed, then=then, on_done=on_done, ease=ease, call_name="move_by")
        if time is None and (loops != 1 or yoyo) and speed is None:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="move_by")
        if dx is not None and dy is None and not isinstance(dx, (int, float, Vec2)):
            # Locations (Point, Graphic, mouse, (x, y)) are move_to, not a delta.
            # Numbers and Vec2 stay on the paths below — this branch is the miss.
            if isinstance(dx, Point) or _xy_of(dx, required=False) is not None:
                raise TypeError(
                    "move_by does not accept a location (Point, Graphic, mouse, (x, y)). "
                    "Use move_to(...), or move_by(dx, dy) / move_by(v) / "
                    "move_by(angle=…, distance=…)."
                )

        polar = angle is not None or distance is not None
        vector = dx if (dx is not None and isinstance(dx, Vec2)) else None
        if vector is not None and dy is not None:
            # A second argument used to be dropped silently (SA16).
            raise TypeError(
                f"move_by(v) takes one Vec2; got a second argument ({type(dy).__name__}). "
                "Write move_by(v) or move_by(dx, dy)."
            )
        cartesian = vector is not None or dx is not None or dy is not None
        if not polar and not cartesian:
            # ``move_by(None)`` is usually a location / vector that turned out
            # missing; a silent no-op hides it. One axis may be None (per-axis).
            raise TypeError(
                "move_by needs a delta, got nothing (None). Write move_by(dx, dy), "
                "move_by(v), or move_by(angle=…, distance=…)."
            )

        if polar and cartesian:
            raise TypeError(
                "move_by got both cartesian (dx, dy / Vec2) and polar "
                "(angle, distance). Use one family: move_by(dx, dy), "
                "move_by(v), or move_by(angle=…, distance=…)."
            )
        if polar:
            if distance is None:
                raise TypeError(
                    "move_by(angle=…) needs distance=. Write move_by(angle=…, distance=…), "
                    "or move_by(distance=…) to move along the heading."
                )
            if angle is None:
                # ``distance=`` alone moves along the heading, read now (like
                # ``raycast(length=)``). ``face=`` would write the heading it read.
                if face:
                    raise TypeError(
                        "move_by(distance=…) without angle= already moves along the "
                        "heading; face=True would turn the shape by its own motion. "
                        "Drop face=True (back up with a negative distance), or turn "
                        "first with rotate_by(180), or pass angle= explicitly."
                    )
                angle = self.angle
            ang = finite(angle, "move_by angle=")
            dist = finite(distance, "move_by distance=")
            if callable(ang) or callable(dist):
                raise TypeError("move_by expected a number, got a function")
            rad = math.radians(float(ang))
            dist = float(dist)
            to_dx = dist * math.cos(rad)
            to_dy = dist * math.sin(rad)
        elif vector is not None:
            to_dx = finite(vector.x, "move_by")
            to_dy = finite(vector.y, "move_by")
            if callable(to_dx) or callable(to_dy):
                raise TypeError("move_by expected a number, got a function")
        else:
            to_dx = finite(dx, "move_by dx") if dx is not None else None
            to_dy = finite(dy, "move_by dy") if dy is not None else None
            if callable(to_dx) or callable(to_dy):
                raise TypeError("move_by expected a number, got a function")

        step_dx = 0.0 if to_dx is None else to_dx
        step_dy = 0.0 if to_dy is None else to_dy
        if time is not None or speed is not None:
            from .process import timed_move_by
            return timed_move_by(
                self, step_dx, step_dy,
                time=time, speed=speed, ease=ease, then=then, on_done=on_done, force=force,
                loops=loops, yoyo=yoyo, face=face,
            )
        _refuse_if_destroyed(self, "move_by")
        result = self._move_by(to_dx, to_dy, force=force)
        from .collision import note_collider_motion
        note_collider_motion(self, step_dx, step_dy)
        if face:
            from .process import apply_face_delta
            apply_face_delta(self, step_dx, step_dy, force=force)
        return result

    def move_to(
        self,
        x: Optional[Union[Vec2, float, 'Point']] = None,
        y: Optional[float] = None,
        *,
        about: Optional[GeneralPoint] = None,
        time: Optional[float] = None,
        speed: Optional[float] = None,
        ease: str = "linear",
        then=None,
        on_done=None,
        force: bool = False,
        loops: object = 1,
        yoyo: bool = False,
        face: bool = False,
    ):
        """
        Move to an absolute position (default: geometric center lands on the target).
        Two numbers ``(x, y)``, or one point-like (Point, Vec2, ``(x, y)``,
        Graphic, mouse). ``move_to(x)`` with a number still sets x only.
        ``about=`` names a different point that lands on the target instead.
        With ``time=``, interpolate and return a Handle; otherwise returns self.
        ``speed=`` (units per second) instead of ``time=``: the duration is the
        distance to the target ÷ speed, read at the call (the target does not
        move with it afterwards).
        ``face=True`` aims ``.angle`` at the travel direction (zero delta holds).
        Combined with ``about=``, the face-rotation pivots about the same point.
        force=True unlinks Defining parts that must be written (default: raise).
        """
        if time is None and (then is not None or on_done is not None or ease != "linear") \
                and speed is None:
            from .process import _require_timed_completion
            _require_timed_completion(time=time, speed=speed, then=then, on_done=on_done, ease=ease, call_name="move_to")
        if time is None and (loops != 1 or yoyo) and speed is None:
            from .process import _require_loop_kwargs
            _require_loop_kwargs(loops=loops, yoyo=yoyo, time=time, speed=speed, call_name="move_to")
        if x is None and y is None:
            # ``move_to(info.point)`` with a missing point: say so, do not no-op.
            # One axis may be None (``move_to(None, 5)`` keeps x).
            raise TypeError(
                "move_to needs a target, got nothing (None). Write move_to(x, y) "
                "or move_to(point); move_to(None, y) keeps x."
            )
        if y is not None and x is not None and not isinstance(x, (int, float)):
            # A point-like target and a second number: the number was dropped (SA16).
            raise TypeError(
                f"move_to(point) takes one target; got a second argument ({type(y).__name__}). "
                "Write move_to(point) or move_to(x, y)."
            )
        if isinstance(x, Vec2):
            vector = x
            to_x = vector.x
            to_y = vector.y
        elif isinstance(x, Point):
            p = x
            to_x = p.x
            to_y = p.y
        elif y is None and x is not None and not isinstance(x, (int, float)):
            to_x, to_y = _xy_of(x, required=True)
        else:
            to_x = None if x is None else finite(x, "move_to x")
            to_y = None if y is None else finite(y, "move_to y")
            if callable(to_x) or callable(to_y):
                raise TypeError("move_to expected a number, got a function")

        if time is not None or speed is not None:
            from .process import timed_move_to
            return timed_move_to(
                self, to_x, to_y, about=about, time=time, speed=speed, ease=ease, then=then, on_done=on_done,
                force=force, loops=loops, yoyo=yoyo, face=face,
            )
        _refuse_if_destroyed(self, "move_to")
        if about is None and not face:
            # The common instant move: no pivot to read (graphics review SA14:
            # a Rect spent 1.85 of 4.6 µs on a pivot it never used).
            result = self._move_to(to_x, to_y, force=force)
            from .collision import note_collider_placement
            note_collider_placement(self)
            return result
        px, py = self._pivot_xy(about)
        dx = None if to_x is None else to_x - px
        dy = None if to_y is None else to_y - py
        if about is None:
            result = self._move_to(to_x, to_y, force=force)
        else:
            result = self._move_by(dx, dy, force=force)
        from .collision import note_collider_placement
        note_collider_placement(self)
        if face:
            from .process import apply_face_delta
            step_dx = 0.0 if dx is None else dx
            step_dy = 0.0 if dy is None else dy
            apply_face_delta(self, step_dx, step_dy, about=about, force=force)
        return result

    # Abstract properties and methods - need be implemented by subclasses --------------------------------------------------------

    def draw(self, skia_canvas: skia.Canvas) -> None:
        """Draw shape; optional transient envelope, then stamps + visual/geometry.

        Compiled GlowRim / Halo high: ``_geometry_draw`` then
        ``_overlay_after_filters`` (unfiltered rim). The canvas batcher draws
        the halo via a filter RT and calls the overlay once per segment instead.
        """
        self._pull_property_anchors()
        tx = getattr(self, "_tx_state", None)
        if tx is not None and tx.any_active():
            mods = compose_draw_mods(self)
            if mods is not None and not mods.is_identity():
                draw_with_transients(self, skia_canvas, mods)
                return
        if (
            getattr(self, "_glow", None) is not None
            or getattr(self, "_shadow", None) is not None
            or getattr(self, "_hue", None) is not None
            or getattr(self, "_gray", None) is not None
            or getattr(self, "_tail", None) is not None
        ):
            draw_body_with_stamps(self, skia_canvas)
            return
        visual = getattr(self, "visual", None)
        if visual is not None:
            render_sprite = getattr(visual, "_render_sprite_body", None)
            if callable(render_sprite) and getattr(type(self), "_is_sprite_body", False):
                render_sprite(self, skia_canvas)
                return
            if getattr(visual, "_is_multipass", False):
                visual._render(self, skia_canvas)
                return
        self._geometry_draw(skia_canvas)
        fn = getattr(visual, "_overlay_after_filters", None) if visual is not None else None
        if callable(fn):
            fn(self, skia_canvas)

    def _blit_plain(self, skia_canvas: skia.Canvas) -> None:
        """Plain-geometry fast path used when ``_plain_blit`` is True.

        Skips transient / stamp / visual ceremony (all unset by construction when
        the sticky flag is True). Canvas ``_draw_plain_object`` calls this instead
        of ``draw``. Pulls linked ``angle`` / ``scale`` first — same contract
        as ``Sprite._blit_plain`` / full ``draw``.
        """
        self._pull_property_anchors()
        self._geometry_draw(skia_canvas)

    def _geometry_draw(
        self,
        skia_canvas: skia.Canvas,
        fill_paint=_STYLE_PAINT,
        stroke_paint=_STYLE_PAINT,
    ) -> None:
        """Rasterize geometry once. Subclasses override.

        Pass ``fill`` / ``stroke_paint`` to override PaintState paints.
        Pass ``None`` to skip that paint; omit args to use PaintState paints.
        """
        raise NotImplementedError("Subclasses must implement _geometry_draw")

    def dissolve_out(
        self,
        duration: float = 0.5,
        *,
        style: Literal["noise", "vortex", "wipe", "fade"] = "noise",
        angle: float = 0.0,
        on_done: Optional[Callable] = None,
    ):
        """Disappear by dissolving, then hide. Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.5).
            style: ``"noise"`` (default) · ``"vortex"`` · ``"wipe"`` · ``"fade"``.
            angle: wipe direction / vortex bias in degrees (0 = +x).
            on_done: optional function called at the end.
        """
        from .transients import dissolve_out as _dissolve
        return _dissolve(self, duration=duration, on_done=on_done, style=style, angle=angle)

    def dissolve_in(
        self,
        duration: float = 0.5,
        *,
        style: Literal["noise", "vortex", "wipe", "fade"] = "noise",
        angle: float = 0.0,
        on_done: Optional[Callable] = None,
    ):
        """Appear by materializing (shows the shape first). Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.5).
            style: ``"noise"`` (default) · ``"vortex"`` · ``"wipe"`` · ``"fade"``.
            angle: wipe direction / vortex bias in degrees (0 = +x).
            on_done: optional function called at the end.
        """
        from .transients import dissolve_in as _di
        return _di(self, duration=duration, on_done=on_done, style=style, angle=angle)

    def fade_out(self, duration: float = 0.35, *, on_done=None):
        """Fade to transparent, then hide. Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.35).
            on_done: optional function called at the end.
        """
        from .transients import fade_out as _fo
        return _fo(self, duration=duration, on_done=on_done)

    def fade_in(self, duration: float = 0.35, *, on_done=None):
        """Show the shape and fade it in from transparent. Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.35).
            on_done: optional function called at the end.
        """
        from .transients import fade_in as _fi
        return _fi(self, duration=duration, on_done=on_done)

    def implode(self, duration: float = 0.28, *, scale_end: float = 0.05, on_done=None):
        """Shrink to a point while fading, then hide. Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.28).
            scale_end: final size as a fraction of the original (default 0.05).
            on_done: optional function called at the end.
        """
        from .transients import implode as _imp
        return _imp(self, duration=duration, on_done=on_done, scale_end=scale_end)

    def burn_out(
        self,
        duration: float = 0.55,
        *,
        intensity: float = 1.0,
        on_done=None,
        **retired,
    ):
        """Glow hot and burn away, then hide. Replaces any other appear / disappear effect running on this shape.

        Args:
            duration: seconds (default 0.55).
            intensity: heat strength (default 1).
            on_done: optional function called at the end.
        """
        if retired:
            _refuse_retired_burn_kwargs(retired)
        from .transients import burn_out as _burn
        return _burn(self, duration=duration, on_done=on_done, intensity=intensity)

    # ``**retired`` only catches the removed ``fidelity=`` to name the fix;
    # help() / autocomplete show the real keywords.
    burn_out.__signature__ = inspect.Signature([
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("duration", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=0.55),
        inspect.Parameter("intensity", inspect.Parameter.KEYWORD_ONLY, default=1.0),
        inspect.Parameter("on_done", inspect.Parameter.KEYWORD_ONLY, default=None),
    ])

    def flash(self, duration: float = 0.12, *, intensity: float = 1.0, on_done=None):
        """Brighten for a moment (a hit flash). A new flash / blink replaces it.

        Args:
            duration: seconds (default 0.12).
            intensity: 0 … 1 (default 1).
            on_done: optional function called at the end.
        """
        from .transients import flash as _flash
        return _flash(self, duration=duration, intensity=intensity, on_done=on_done)

    def blink(
        self,
        duration: float = 0.8,
        *,
        rate: float = 8.0,
        intensity: float = 1.0,
        on_done=None,
    ):
        """Strobe the shape's opacity (invulnerability frames, attention).

        Replaces a running ``flash``; a second ``blink`` restarts it.

        Args:
            duration: seconds (default 0.8).
            rate: blinks per second (default 8).
            intensity: how far it dims, 0 … 1 (default 1).
            on_done: optional function called at the end.
        """
        from .transients import blink as _blink
        return _blink(self, duration=duration, rate=rate, intensity=intensity, on_done=on_done)

    def pulse_outline(
        self,
        duration: float = 0.25,
        *,
        color=(1.0, 1.0, 1.0, 1.0),
        on_done=None,
    ):
        """Flash the outline in a color for a moment.

        Args:
            duration: seconds (default 0.25).
            color: pulse color (default white).
            on_done: optional function called at the end.
        """
        from .transients import pulse_outline as _pulse
        return _pulse(self, color=color, duration=duration, on_done=on_done)

    def pop(self, duration: float = 0.18, *, scale: float = 1.2, on_done=None):
        """Grow and settle back (a "boing"). Drawing only — geometry is unchanged.

        Args:
            duration: seconds (default 0.18).
            scale: peak size (default 1.2).
            on_done: optional function called at the end.
        """
        from .transients import pop as _pop
        return _pop(self, scale=scale, duration=duration, on_done=on_done)

    def knock(
        self,
        duration: float = 0.14,
        *,
        distance: float = None,
        angle: float = None,
        dx: float = 0.0,
        dy: float = 0.0,
        on_done=None,
    ):
        """Jolt the drawing sideways and back (a hit reaction). Geometry is unchanged.

        Give ``distance`` + ``angle`` (degrees, y-up) or ``dx`` / ``dy`` (design
        units). A new knock replaces the previous one; it stacks with ``pop``.

        Args:
            duration: seconds (default 0.14).
            distance, angle: push length and direction.
            dx, dy: push as a vector.
            on_done: optional function called at the end.
        """
        from .transients import knock as _knock
        return _knock(
            self,
            duration=duration,
            dx=dx,
            dy=dy,
            distance=distance,
            angle=angle,
            on_done=on_done,
        )

    def spark_burst(
        self,
        duration: float = 0.35,
        *,
        amount: float = 1.0,
        color=(1.0, 0.92, 0.75, 1.0),
        on_done=None,
    ):
        """Throw a short burst of sparks outward. Stacks with other effects.

        Args:
            duration: seconds (default 0.35).
            amount: how many sparks (default 1 = normal).
            color: spark color (default warm white).
            on_done: optional function called at the end.
        """
        from .transients import spark_burst as _spark
        return _spark(self, duration=duration, amount=amount, color=color, on_done=on_done)

    def clear_transients(self) -> "Shape":
        """Stop every running effect (flash, fade, pop, …) on this shape. Returns the shape."""
        from .transients import clear_transients as _clear
        _clear(self)
        return self

    def move_along(
        self,
        target,
        *,
        time: Optional[float] = None,
        speed: Optional[float] = None,
        ease: str = "linear",
        span: Tuple[float, float] = (0.0, 1.0),
        phase: float = 0.0,
        loops: Union[int, str] = 1,
        yoyo: bool = False,
        face: bool = False,
        at=None,
        then=None,
        on_done=None,
        force: bool = False,
    ):
        """Travel along a Track, a Shape outline, or a preset name string.

        Preset strings are 1:1 aliases for zero-arg Track constructors
        (``"eight"`` → ``Track.eight()``, ``"shuttle"`` → ``Track.shuttle()``, …). Same
        defaults as the classmethod — ``loops=1`` unless you pass ``loops=``.

        Slide to a point: ``move_to(..., time=)``. ``time=`` is one lap;
        ``speed=`` (units per second along the track) instead sets the lap to
        ``length × |span window| ÷ speed``, read at the call. One of the two is required.
        ``span=(1, 0)`` reverses this trip; ``phase=`` is a per-rider u-offset.
        ``loops="forever"`` never fires ``on_done``. ``yoyo=True`` swaps
        start/end each odd lap (flips ``span``, not ``phase``).
        """
        from .process import timed_move_along
        return timed_move_along(
            self, target, time=time, speed=speed, ease=ease, span=span, phase=phase,
            loops=loops, yoyo=yoyo, face=face, at=at, then=then, on_done=on_done,
            force=force,
        )

    @abstractmethod
    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Shape':
        raise NotImplementedError("Subclasses must implement _move_by")

    @abstractmethod
    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Shape':
        raise NotImplementedError("Subclasses must implement _move_to")

    def absorb(self, other: 'Shape') -> 'Shape':
        """Copy ``other`` into this shape via takein, then destroy ``other``.

        ``<<`` is takein only (the other object stays on the canvas).
        """
        self._refuse_author_write()
        if not self.is_alive:
            from .entity import _destroyed_access_message
            raise DestroyedError(_destroyed_access_message(self, "absorb"))
        if not isinstance(other, Shape):
            raise TypeError(
                f"absorb() takes a Shape to copy and destroy, got "
                f"{type(other).__name__}"
            )
        if other is self:
            raise ValueError("absorb() cannot absorb the shape itself (it would destroy it)")
        if not other.is_alive:
            from .entity import _destroyed_access_message
            raise DestroyedError(_destroyed_access_message(other, "absorb"))
        self._takein(other)
        self._scenacanvas.registry.destroy(other)
        return self


# Share Shape's pose / pointer / transient / draw envelope with Sprite via Graphic.
# Keep the implementations on Shape (subclasses override rotate_to / scale_to);
# copy the unbound functions onto Graphic so Sprite inherits them without a
# second source. Do not copy geometry-only helpers (handles, absorb).
# ``clone`` lives on Graphic (Sprite + Shape share the group / layer contract).
_GRAPHIC_SHARED = (
    "visible",
    "_sync_interactive_registry",
    "clickable",
    "on_click",
    "on_drag_to",
    "on_drag_over",
    "_draggable_from_callbacks",
    "on_drop_by",
    "on_hover",
    "on_hover_exit",
    "_no_click",
    "no_drag",
    "no_drop",
    "no_wheel_rotate",
    "contains_point",
    "_hit_test_xy",
    "_set_pointer_hover",
    "_on_pointer_hover_changed",
    "pointer_hover",
    "_set_pointer_pressed",
    "_on_pointer_pressed_changed",
    "pointer_pressed",
    "_accepts_press",
    "_fire_click",
    "move_to_front",
    "move_to_back",
    "_center_xy",
    "_pivot_xy",
    "angle",
    "rotate_to",
    "rotate_by",
    "scale",
    "scale_to",
    "scale_by",
    "_scale_gate",
    "move_by",
    "move_to",
    "draw",
    "dissolve_out",
    "dissolve_in",
    "fade_out",
    "fade_in",
    "implode",
    "burn_out",
    "flash",
    "blink",
    "pulse_outline",
    "pop",
    "knock",
    "spark_burst",
    "clear_transients",
    "move_along",
    "_parts_written_by_drag",
    "_parts_written_by_wheel_rotate",
    "_parts_written_by_resolve",
    "_ensure_drag_parts_writable",
    "_ensure_wheel_rotate_parts_writable",
    "_ensure_resolve_parts_writable",
    "_note_resolve_enroll",
    "_note_resolve_unenroll",
    "_ensure_can_link_attribute",
    "draggable",
    "droppable",
    "wheel_rotate",
)


def _refresh_graphic_subclass_routes() -> None:
    """Re-build setattr routes after descriptors are copied onto Graphic."""
    _install_setattr_route(Graphic)
    for sub in Graphic.__subclasses__():
        _install_setattr_route(sub)


def _publish_graphic_api() -> None:
    for name in _GRAPHIC_SHARED:
        setattr(Graphic, name, getattr(Shape, name))
    # Descriptors landed on Graphic after its first ``__init_subclass__`` pass.
    _refresh_graphic_subclass_routes()


_publish_graphic_api()


# Sentinel so ``Point(pt)`` (one arg) is distinct from ``Point(x, y=0)``.
_POINT_UNSET = Unset("<unset>")


def _is_xy_scalar(v: Any) -> bool:
    """True for constructor leaf coords: number or Attribute (not bool-special)."""
    return isinstance(v, (int, float, Attribute))


_MARKER_FILLS: Dict[tuple, Color] = {}


def _marker_fill(color, alpha) -> Color:
    """``Color(color).with_alpha(alpha)``, one per (color, alpha) value: what
    ``fill = Color(color)`` then ``set_alpha(alpha)`` gave a marker Point."""
    try:
        key = (color, float(alpha))
        hit = _MARKER_FILLS.get(key)
    except TypeError:                     # an unhashable color spec
        return Color(color).with_alpha(alpha)
    if hit is None:
        hit = _MARKER_FILLS[key] = Color(color).with_alpha(alpha)
    return hit


class Point(Shape):
    """XY locus. Undrawn by default (``layer=None``, ``visible=False``) for efficiency.

    Constructors:
      ``Point(x, y)`` — beginner scalars (``Point(3)`` → ``(3, 0)``).
      ``Point(point_like)`` — copy from Point / Vec2 / ``(x, y)`` / Graphic /
      mouse-like (``.center`` or ``.x``/``.y``). Snapshot, not a live link.
      ``Point(lambda: …)`` — whole-point formula (callable must return a
      point-like); same as ``Circle(center=lambda: …)``. Link one axis with
      two args: ``Point(lambda: mouse.x, 0)``.

    ``color=`` paints the marker and shows it as a guide (not a handle), unless
    ``visible=False`` is also passed. ``visible=True`` promotes onto layer
    ``top`` (restored on hide). ``handle=True`` means visible + draggable
    (grab-handle role; same underlying drag machinery as ``Shape.draggable``).

    Marker colors follow role while ``_marker_style_auto`` is True (default):
    guides (visible, not draggable) use ``GUIDE_COLOR``; handles use
    ``HANDLE_COLOR``. Explicit ``color=`` / ``set_color`` / ``fill = …`` opts out.

    Args:
        x: x coordinate (or a point / function as the only value).
        y: y coordinate (y-up).
        layer: Draw layer when shown; default ``None`` (not drawn).
        group: Group tag or list of tags (``group["enemies"]``).
        color: Solid color (fill on area shapes, stroke on lines).
        visible: Show it as a marker.
    """
    x = ScalarSlot()
    y = ScalarSlot()

    # Handle / guide glyph.
    HANDLE_RADIUS = 8.0
    HANDLE_HOVER_RADIUS = 10.0
    GUIDE_RADIUS = 4.0
    HANDLE_COLOR = "red"
    HANDLE_ALPHA = 0.5
    GUIDE_COLOR = "steel blue"
    GUIDE_ALPHA = 0.45

    # Empty _update_impl — dirty visits only need to fan out to dependents.
    _passthrough_update = True
    _ink_strict = True          # bracket typos stay AttributeError (Entity.__getitem__)
    # Iterates as its (x, y) value (``x, y = p``). An entry that takes "a list
    # of points" tests this first: one point is not a list of two numbers.
    _scena_point_value = True

    def __setattr__(self, name: str, value: Any) -> None:
        # ``x`` / ``y`` are the motion hot path (Line/Circle centers). Bypass
        # Entity ink routing and call the ContainerSlot directly.
        if name == "x" or name == "y":
            Point.__dict__[name].__set__(self, value)
            owner = self._owner
            if owner is not None:
                # ``center.x =`` is placement: it ends the frame's pending
                # motion (X-writers-4). The usual owner is the actor itself:
                # one slot read and a compare when nothing moved.
                try:
                    col = owner._collider
                except AttributeError:          # a nested part: find the actor
                    _placement_write(self)
                else:
                    if col is not None and (col._pending_motion_dx != 0.0
                                            or col._pending_motion_dy != 0.0):
                        _placement_write(self)
            return
        if not name or name[0] == "_":
            object.__setattr__(self, name, value)
            return
        Entity.__setattr__(self, name, value)

    __setattr__._scena_private_passthrough = True

    def __init__(
        self,
        x: Any = _POINT_UNSET,
        y: Any = _POINT_UNSET,
        *,
        layer: Optional[Union[str, int]] = None,
        group: Optional[Union[str, Sequence[str]]] = None,
        color: Optional[ColorLike] = None,
        visible: Optional[bool] = None,
        **_engine,
    ):
        attr_name = _engine.pop("attr_name", None)
        owner = _engine.pop("owner", None)
        if _engine:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(
                type(self).__name__,
                _engine,
                valid=("x", "y", "layer", "group", "color", "visible"),
            )
        self._construct(
            x, y, layer=layer, group=group, color=color, visible=visible,
            attr_name=attr_name, owner=owner,
        )

    def _construct(
        self,
        x: Any = _POINT_UNSET,
        y: Any = _POINT_UNSET,
        *,
        layer: Optional[Union[str, int]] = None,
        group: Optional[Union[str, Sequence[str]]] = None,
        color: Optional[ColorLike] = None,
        visible: Optional[bool] = None,
        attr_name: Optional[str] = None,
        owner: Optional[Container] = None,
    ):
        defaults = getattr(type(self), '_shape_defaults', None) or {}
        if color is None and 'color' in defaults:
            color = defaults['color']
        if group is None and 'group' in defaults:
            group = defaults['group']

        Shape._construct(
            self, layer=layer, group=group, attr_name=attr_name, owner=owner,
        )

        # Marker defaults (used when shown); unused while layer=None.
        self.line = None
        self._marker_style_auto = True
        self._apply_role_marker_style()

        # Undrawn Points stay off the draw list. Explicit layer ⇒ shown.
        self._point_layer_saved = False
        self._layer_before_visible = None
        if self._layer is None:
            self._visible = False
        else:
            self._visible = True
            self._apply_role_marker_style()

        # Dual signature: Point(x, y) | Point(point_like) | Point(lambda: …).
        if y is _POINT_UNSET:
            if x is _POINT_UNSET or x is None:
                _init_scalar(self, 'x', 0.0)
                _init_scalar(self, 'y', 0.0)
            elif callable(x) and not isinstance(x, type):
                # Whole-point formula (must return a point-like).
                self._assign_formula(x)
            elif isinstance(x, tuple) and len(x) == 2:
                # Per-component copy/link — same as Circle(center=(…, …)).
                _init_composite(self, x)
            elif _is_xy_scalar(x):
                # Point(3) → (3, 0); Attribute on x still links that leaf.
                _init_scalar(self, 'x', x)
                _init_scalar(self, 'y', 0.0)
            else:
                # Point / Vec2 / Graphic / mouse-like — snapshot via _xy_of.
                cx, cy = _xy_of(x, required=True)
                _init_scalar(self, 'x', cx)
                _init_scalar(self, 'y', cy)
        else:
            # Two-arg path: scalars only (including None → 0).
            if x is None:
                x = 0.0
            if y is None:
                y = 0.0
            if not _is_xy_scalar(x) or not _is_xy_scalar(y):
                raise TypeError(
                    "Point(x, y) expects numbers (or Attribute); "
                    "for a point-like use Point(pt) or Point(lambda: …)"
                )
            _init_scalar(self, 'x', x)
            _init_scalar(self, 'y', y)

        # color= paints and shows a guide (not a handle). Explicit visible= wins.
        if color is not None:
            self.set_color(color)
            if visible is None:
                visible = True
        if visible is not None:
            self.visible = visible       # the setter refuses "no" (SA12)

    def _apply_role_marker_style(self) -> None:
        """Paint guide vs handle colors when still on auto marker style."""
        if not getattr(self, '_marker_style_auto', True):
            return
        if self._draggable:
            color, alpha = self.HANDLE_COLOR, self.HANDLE_ALPHA
        elif self._visible:
            color, alpha = self.GUIDE_COLOR, self.GUIDE_ALPHA
        else:
            # Dormant seed (matches legacy / Anchor default until shown).
            color, alpha = self.HANDLE_COLOR, self.HANDLE_ALPHA

        # Bypass set_color so we keep _marker_style_auto True. The faded
        # marker Color is built once per (color, alpha): a Color is a value
        # (immutable, shared like the default paint), and parsing it plus
        # ``set_alpha`` cost ~20 µs per Graphic built, since every Graphic's
        # center Point paints its marker at construction (C4a).
        self.fill = _marker_fill(color, alpha)
        self.line = None  # no_line already; keep stroke off

    def set_color(self, *args) -> 'Point':
        """Author color override — stops automatic guide/handle painting.

        Markers stay fill-only (no contrast stroke), matching role auto-style.
        """
        PaintState.set_color(self, *args)
        self.line = None
        self._marker_style_auto = False
        return self

    @property
    def center(self) -> 'Point':
        """A Point is its own center (for Shape.move_to / pivot defaults)."""
        return self

    @property
    def visible(self) -> bool:
        """Show the point as a marker (``True``) or not. Showing an undrawn point puts it on ``top``."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        """Show/hide marker; promote ``layer=None`` → ``top``, restore on hide."""
        _refuse_if_destroyed(self, "visible")
        value = expect_bool(value, "Point.visible")
        if _parked(self):
            _stash_flag(self, "visible", value)
            return
        if value:
            back = self.__dict__.pop('_layer_while_hidden', None)
            if back is not None and self._layer is None:
                # Hidden off the layer it was built on: show it there again
                # (SA13: it came back on 'top').
                self.layer = back
            if not self._point_layer_saved:
                self._layer_before_visible = self._layer
                self._point_layer_saved = True
            if self._layer is None:
                self.layer = 'top'
        else:
            if self._point_layer_saved:
                prev = self._layer_before_visible
                self._point_layer_saved = False
                self._layer_before_visible = None
                if self._layer != prev:
                    self.layer = prev
            elif self._layer is not None:
                # Constructed on a layer (or moved there) without a save — drop off
                # the draw list for efficiency, remembering where it was.
                self.__dict__['_layer_while_hidden'] = self._layer
                self.layer = None

        if value != self._visible:
            self._visible = value
            self._sync_interactive_registry()
        self._apply_role_marker_style()

    @property
    def handle(self) -> bool:
        """Grab-handle role: visible + draggable. Name for Point; uses ``_draggable``."""
        return self._draggable

    @handle.setter
    def handle(self, value: bool) -> None:
        value = _expect_flag(value, 'handle')
        if value:
            if not self._draggable:          # every check before a write (SA11)
                self._reject_if_parallax_layer("draggable")
                self._ensure_drag_parts_writable()
            self.visible = True
            self.draggable = True
        else:
            self.draggable = False
            self._apply_role_marker_style()

    @property
    def draggable(self) -> bool:
        """Drag it with the mouse. ``True`` also shows the marker."""
        return self._draggable

    @draggable.setter
    def draggable(self, value: bool) -> None:
        value = _expect_flag(value, 'draggable')
        if value and not self._draggable:    # every check before a write (SA11)
            self._reject_if_parallax_layer("draggable")
            self._ensure_drag_parts_writable()
        if value:
            self.visible = True
        if value != self._draggable:
            self._draggable = value
            self._sync_interactive_registry()
        if not value:
            # A pointer hold in progress ends now: held motion runs again at
            # once (the pointer manager drops the drag on its next event).
            from .process import release_hold
            release_hold(self)
        self._apply_role_marker_style()

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        return (self,)

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        # rotate_by about self is a no-op (early-return before _pose_rotation_add).
        return ()

    def _parts_written_by_resolve(self) -> Tuple:
        return (self,)

    def _clone_geometry(self, **kwargs) -> 'Point':
        x, y = get_xy(self, bare=True)
        return type(self)(x, y, **kwargs)

    @classmethod
    def temp(cls, x: float = 0.0, y: float = 0.0) -> 'Point':
        """Create an unregistered Point for use as an arithmetic result.

        Always copies bare numeric values — never links to sources
        (linking would register the temp into the dependency graph).
        """
        if isinstance(x, Attribute):
            x = x.value
        if isinstance(y, Attribute):
            y = y.value
        with ephemeral_creation():
            return cls(float(x), float(y), layer=None)

    def _marker_radius(self) -> float:
        """Draw radius: larger for handles, smaller for guides."""
        return self.HANDLE_RADIUS if self._draggable else self.GUIDE_RADIUS

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw marker glyph; handles get a hover ring when pressable under cursor."""
        cx, cy = get_xy(self, bare=True)
        r = self._marker_radius()

        fill = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        if fill:
            skia_canvas.drawCircle(cx, cy, r, fill)

        # Markers default to no line; resolve PaintState only when asked.
        # Explicit None skips stroke (and auto hover) for multipass callers.
        # Hover ring is independent of an author/contrast stroke.
        if stroke_paint is _STYLE_PAINT:
            stroke = self._to_skia_line_paint()
            if stroke is not None:
                skia_canvas.drawCircle(cx, cy, r, stroke)
            if self._pointer_hover and self._draggable:
                base = self.fill
                if isinstance(base, Color) and base:
                    ring_color = base.lighter(0.25).with_alpha(0.9)
                else:
                    ring_color = Color(1.0, 1.0, 1.0, 0.75)
                ring = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=1.0,
                )
                ring.setColor4f(ring_color.color4f)
                skia_canvas.drawCircle(cx, cy, r + 2.5, ring)
        elif stroke_paint is not None:
            skia_canvas.drawCircle(cx, cy, r, stroke_paint)

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit target: generous for handles; guides match their smaller disk."""
        px, py = get_xy(self, bare=True)
        radius = self.HANDLE_HOVER_RADIUS if self._draggable else self.GUIDE_RADIUS
        return math.hypot(x - px, y - py) <= radius

    def _update_impl(self):
        pass

    # Ownership-tree leaf: x/y are Defining; no structural Derivate fan-out of its own.
    # UpdateManager skips pass-through recalc when this node was written mid-cycle.
    # A whole-object link on a Point (``dst @= src``) follows the source's
    # position only; the heading and zoom stay the point's own (Shapes Design —
    # Linked parts). Shapes carry their pose in a copy, so their link drives it.
    _whole_link_carries_pose = False

    _leaf_composite = True

    def _takein(self, new_value):
        """
        Take in a new value.
        Batches the part subtree so x/y writes do not each start a cycle.

        Nested under an outer batch: still fan out ``mark_dirty`` to this Point
        and to leaf ``x``/``y`` when the ownership tree has pull consumers —
        otherwise outbound ``@=`` on ``center`` / ``center.x`` stays stale
        after ``Rect.move_to`` / similar batched pose writes.

        Tier 1.5: Point has no Container parts (x/y are ScalarSlots), so the
        non-nested path flips ``_in_batch_update`` on self only — same mark_dirty
        / update contract as before.
        """
        if new_value is self:
            return
        d = self.__dict__
        if d.get('_destroyed'):             # a part of a dead host is marked too (retire_part)
            # The dispatcher for ``c.center = …`` / ``p << xy``: a destroyed
            # point (or a part of a destroyed shape) refuses here (SA10).
            _refuse_if_destroyed(self, "move")

        if self._in_batch_update:
            if self._takein_impl(new_value):
                if self._requires_pull_invalidate() and self._node_id is not None:
                    self._scena_system.update_manager.mark_dirty(self)
                if d.get('_field_anchors'):
                    _notify_source_anchors(self)    # q["x"] @= p["x"] (S5-1)
            return

        # Leaf: no ownership children — skip subtree push/restore walks.
        # The slot, not ``d[...]`` (a dict write is shadowed by Shape's
        # ``_in_batch_update`` slot: review 2026-10-09 S5-4).
        object.__setattr__(self, '_in_batch_update', True)
        try:
            changed = self._takein_impl(new_value)
        finally:
            object.__setattr__(self, '_in_batch_update', False)

        if changed:
            if d.get('_field_anchors'):
                _notify_source_anchors(self)        # q["x"] @= p["x"] (S5-1)
            self.update()

    def _takein_impl(self, other: 'GeneralPoint') -> bool:
        # One call. Point / Vec2 return inside _xy_of before any fallback
        # (same bare read as get_xy). Mouse / Graphic resolve only on miss.
        if isinstance(other, Attribute):
            other = other.value      # an st cell holding (x, y) / a Vec2: ``p << st.pos``
        x, y = _xy_of(other, required=True)

        old_x = self.__dict__.get('x', 0.0)
        old_y = self.__dict__.get('y', 0.0)

        if old_x != x or old_y != y:
            d = self.__dict__
            d['x'] = float(x)
            d['y'] = float(y)
            # bump_pose_rev(self), inline
            cell = d.get('_pose_cell')
            if cell is None:
                cell = _pose_cell_of(self)
            cell[0] += 1
            if d.get('_pose_mover'):
                cell[4] += 1             # a translation of its root (the cull shifts)
            if not cell[1]:
                cell[1] = True
                DIRTY_POSE_CELLS.append(cell)
            return True
        else:
            return False

    @batch_update_self()
    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Point':
        _ensure_writable(self, "move_by", force=force)
        nx = float(self.x) if dx is None else float(self.x) + float(dx)
        ny = float(self.y) if dy is None else float(self.y) + float(dy)
        if dx is not None:
            self.x = nx
        if dy is not None:
            self.y = ny
        return self

    @batch_update_self()
    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Point':
        _ensure_writable(self, "move_to", force=force)
        if x is not None:
            self.x = float(x)
        if y is not None:
            self.y = float(y)
        return self

    @batch_update_self()
    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Point':
        """Turn so ``angle`` becomes ``value``: ``rotate_by(value - angle)`` about
        the pivot (default: the point itself, which then only turns its heading).
        It placed the point at polar angle ``value`` about the pivot instead,
        unlike every other kind (C2; graphics review SA4)."""
        _refuse_if_destroyed(self, "rotate_to")
        target = _finite_deg(value, "rotate_to angle")
        _fresh_pose(self)
        return self.rotate_by(target - float(self._rotation), about=about, force=force)

    @batch_update_self()
    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Point':
        """Rotate this point about a pivot by angle degrees."""
        _refuse_if_destroyed(self, "rotate_by")
        angle = _finite_deg(angle, "rotate_by angle")
        if angle:
            _gate_pose_anchor(self, "angle", "rotate_by", force)
        px, py = self._pivot_xy(about)
        x, y = get_xy(self, bare=True)
        if x == px and y == py:
            # No-op for position only: the heading still turns (as rotate_to).
            _pose_rotation_add(self, angle)
            return self
        _ensure_writable(self, "rotate_by", force=force)
        nx, ny = _rotate_xy(x, y, px, py, _rad(angle))
        self.x = nx
        self.y = ny
        _pose_rotation_add(self, angle)
        return self

    @batch_update_self()
    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Point':
        """Set distance from pivot so cumulative scale matches value."""
        return _scale_to_via(self, value, about=about, force=force)

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Point':
        """Scale distance from pivot by factor."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        px, py = self._pivot_xy(about)
        x, y = get_xy(self, bare=True)
        if force or self._requires_pull_invalidate():   # nothing linked: nothing refuses
            self._scale_gate(about, force, (px, py))
        nx, ny = _scale_xy(x, y, px, py, factor)
        if nx != x or ny != y:              # a point on its pivot does not move
            self.x = nx
            self.y = ny
        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        _ensure_writable(self, "scale_by", force=force,
                         pivot=self._pivot_xy(about) if pivot is None else pivot)

    # Operator overloading --------------------------------------------------------------------------------------------

    def __add__(self, other: Union[Vec2, Tuple[Any, Any]]) -> 'Point':
        """Translate this point, returning a new detached Point.

        ``other`` is a ``Vec2`` or a ``(dx, dy)`` tuple of numbers. Adding two
        Points raises — use ``middle_point`` or ``a - b``.
        """
        dx, dy = _point_delta(other, op="add")
        return Point.temp(self.x + dx, self.y + dy)

    def __radd__(self, other: Union[Vec2, Tuple[Any, Any]]) -> 'Point':
        """``(dx, dy) + point`` — same translation as ``point + (dx, dy)``."""
        dx, dy = _point_delta(other, op="add")
        return Point.temp(self.x + dx, self.y + dy)

    def __sub__(self, other: Union[Vec2, Tuple[Any, Any], 'Point']) -> Union['Point', Vec2]:
        """Subtract a delta or another point.

        - Point - Vec2 / ``(dx, dy)`` = Point (translation by the negated delta)
        - Point - Point = Vec2 (vector between points)
        """
        if isinstance(other, Point):
            return Vec2.temp(x=self.x - other.x, y=self.y - other.y)
        dx, dy = _point_delta(other, op="subtract")
        return Point.temp(self.x - dx, self.y - dy)

    def __iter__(self):
        """``x, y = p`` / ``tuple(p)``: the coordinates now, as two floats.

        A value snapshot, like ``track.at()``: the names do not follow the
        point. Passing the Point itself keeps its meaning everywhere (a place
        to copy, a source to link with ``@=`` or a lambda): every entry reads
        a Point by type, never by iterating it (Shapes Design, "Point")."""
        return iter((_bare_num(self.x), _bare_num(self.y)))

    def __getitem__(self, key):
        # ``p["x"] @= …`` links an axis; a number is not an index.
        if not isinstance(key, str):
            raise TypeError(_point_index_refusal(self, key))
        return Shape.__getitem__(self, key)

    def __iadd__(self, other: Any) -> 'Point':
        raise TypeError(_POINT_IADD_MSG)

    def __isub__(self, other: Any) -> 'Point':
        raise TypeError(_POINT_IADD_MSG)

    def distance(self, other: Any) -> float:
        """Euclidean distance to another position (same family as the free ``distance``)."""
        return distance(self, other)

    def heading(self, other: Any) -> float:
        """Bearing toward another position in degrees (same as free ``heading``)."""
        return heading(self, other)

    # Identity ``==`` and hash; author compares with a position warn (PE1,
    # ``_point_compare_site``). ``Vec2 == point`` hands over here.
    _point_eq_warns = True

    def __eq__(self, other: Any) -> bool:
        if other is self:
            return True
        if isinstance(other, (Point, Vec2)) or (
            isinstance(other, (tuple, list)) and len(other) == 2
        ):
            site = _point_compare_site()
            if site is not None and (
                not isinstance(other, Point)
                or (other.x == self.x and other.y == self.y)
            ):
                _warn_point_compare(self, other, site)
            return False
        return NotImplemented

    __hash__ = object.__hash__

    def _assign_formula(self, formula: Union['Container', Tuple[float, float], Callable[[], Any]]):
        if isinstance(formula, tuple):
            # special case for Point @= (x, y): both axes must be linkable.
            if len(formula) != 2:
                raise ValueError("A tuple of two numbers is expected")

            x, y = formula
            for value in (x, y):
                if not (callable(value) or isinstance(value, Container)):
                    label = self.name or type(self).__name__
                    raise TypeError(
                        f"@= tuple form links both axes — use '{label}.x = value; "
                        f"{label}.y = value' for a plain copy, "
                        f"or '{label}[\"x\"] @= lambda: …' per axis for a partial link"
                    )

            with self._batch_update():
                self._link_field('x', x)
                self._link_field('y', y)
        else:
            super()._assign_formula(formula)
  

class LineModel(Enum):
    CENTER_LENGTH_ANGLE = "center_length_angle"
    POINT_POINT = "point_point"
    POINT_VEC = "point_vec"
    POINT_ANGLE_LENGTH = "point_ang_len"
    POINT_DX_DY = "point_dx_dy"
    PARALLEL_POINT = "parallel_point"
    PARALLEL_DIST = "parallel_dist"
    PERPENDICULAR_POINT = "perpendicular_point"
    TANGENT_ANGLE = "tangent_angle"
    TANGENT_POINT = "tangent_point"


# Defining parts per Line model (as the constructor sets them).
_LINE_MODEL_DEFINING = {
    LineModel.CENTER_LENGTH_ANGLE: ('center', 'angle', 'length'),
    LineModel.POINT_POINT: ('p1', 'p2'),
    LineModel.POINT_VEC: ('p1', 'vec'),
    LineModel.POINT_DX_DY: ('p1', 'dx', 'dy'),
    LineModel.POINT_ANGLE_LENGTH: ('p1', 'angle', 'length'),
    LineModel.PARALLEL_POINT: ('p1', 'angle', 'length'),
    LineModel.PERPENDICULAR_POINT: ('p1', 'angle', 'length'),
    LineModel.PARALLEL_DIST: ('dist', 'angle', 'length', 'p1'),
    LineModel.TANGENT_ANGLE: ('p1', 'at_angle', 'length'),
    LineModel.TANGENT_POINT: ('p1', 'p2'),
}

# The free twin a copy takes for a relational model (no reference to follow).
_LINE_FREE_MODEL = {
    LineModel.PARALLEL_POINT: LineModel.POINT_ANGLE_LENGTH,
    LineModel.PERPENDICULAR_POINT: LineModel.POINT_ANGLE_LENGTH,
    LineModel.PARALLEL_DIST: LineModel.POINT_ANGLE_LENGTH,
    LineModel.TANGENT_ANGLE: LineModel.POINT_ANGLE_LENGTH,
    LineModel.TANGENT_POINT: LineModel.POINT_POINT,
}

def _rotation_is_derived(shape, name: str = 'angle') -> bool:
    """True when the heading field is a Derivate of the model (heading from the placement points)."""
    if name in (getattr(shape, '_defining_part_names', None) or ()):
        return False                     # a model input: the per-frame write path
    slot = shape._field_slots().get(name)
    return slot is not None and shape._field_is_derivate(name, slot)


class _DerivedRotationRoute:
    """``angle =`` / ``["angle"] @=`` where the heading is derived (Geometry contract).

    Where ``angle`` is one of the model's inputs, setting it keeps the other
    inputs (the field). Where it is derived from the placement points (Rect
    spine, Ellipse foci, a p1/p2 Line, a Circle placed by its rim), setting it
    is ``rotate_to`` about the center and a link drives ``rotate_to`` through a
    property anchor — the same as a Sprite. (The tangent Line's ``rotate_to``
    orbits its circle, so there the heading write moves ``at_angle``.) It used
    to raise ``DerivedAttributeError``.
    """

    _HEADING_FIELD = 'angle'

    def _write_field(self, name: str, value) -> None:
        if name == self._HEADING_FIELD and _rotation_is_derived(self, name):
            if isinstance(value, Attribute):
                value = value.value
            if self._in_batch_update:
                # The model's own refresh of the Derivate (``_update_impl``):
                # store it — the link, if any, drives the verb, not this value.
                self.__dict__[name] = float(value)
                return
            if callable(value) and not isinstance(value, type):
                # ``=`` copies; ``@=`` links — same refusal as every slot write.
                from .state import CallableAssignError, callable_assign_message
                raise CallableAssignError(callable_assign_message(self, name))
            self.rotate_to(_finite_deg(value, name))
            return
        super()._write_field(name, value)

    def _link_field(self, name: str, source) -> None:
        if name == self._HEADING_FIELD and _rotation_is_derived(self, name):
            from .state import _refuse_link_on_dead
            _refuse_link_on_dead(self, f"{name} @=")
            self._refuse_heading_link_over_linked_parts()
            self._ensure_scalar_anchor(name)._assign_formula(source)
            self._note_heading_link_installed()
            return
        super()._link_field(name, source)

    def _ensure_scalar_anchor(self, name: str, anchor_cls: type = None):
        anchor = super()._ensure_scalar_anchor(name, anchor_cls)
        if name == self._HEADING_FIELD and isinstance(anchor, _PropertyAnchor):
            self.__dict__['_heading_anchor'] = anchor       # read by _pull_heading (D18)
        return anchor

    def _heading_driven_parts(self) -> Tuple:
        """Parts ``rotate_to`` rewrites when the heading is derived (besides ``angle``).

        A linked heading drives that verb, which refuses to write a part that
        has its own formula; the two links are exclusive, and are refused when
        the second is installed, not on a later read (D17). Kinds whose heading
        is derived override this next to their ``rotate_by``; the test
        ``test_heading_link`` pins the list to what the verb refuses.
        """
        return ()

    def _heading_pivot_inputs(self) -> Tuple:
        """Parts the derived heading is measured from that its turn does not
        rewrite (a rim-placed Circle's ``center``). A linked heading turns the
        shape again each time one of them moves, from wherever it was last
        read, so the result would depend on which frames read it: the two
        links are exclusive too. ``test_heading_link`` finds these parts by
        writing each input and watching ``angle``."""
        return ()

    def _heading_exclusive(self):
        """``(part, label, is_pivot)`` for every part a heading link excludes."""
        from .entity import part_path
        out = []
        for parts, pivot in ((self._heading_driven_parts(), False),
                             (self._heading_pivot_inputs(), True)):
            for part in parts:
                label = str(part.name) if isinstance(part, FieldRef) else part_path(part, self)
                out.append((part, label, pivot))
        return out

    def _heading_conflict_text(self, label: str, pivot: bool, heading_linked: bool) -> str:
        h = self._HEADING_FIELD
        if pivot:
            again = (f"each move of {label} would turn the shape again, by an "
                     f"amount that depends on which frames read it")
            if heading_linked:
                return f"{h} has an @= formula and is measured from {label}: {again}"
            return f"its {label} has an @= formula, and {h} is measured from it: {again}"
        if heading_linked:
            return f"{h} has an @= formula that turns the shape by rewriting {label}"
        return (f"its {label} has an @= formula, and a linked {h} turns the shape "
                f"by rewriting {label}")

    def _resolve_structural(self) -> None:
        # A linked heading turns the shape with ``rotate_to``, which only runs
        # when the anchor is pulled. A resolve of the shape (a read of a
        # Derivate, or of a point the turn rewrites) pulls it first, outside
        # the update batch: inside it ``angle`` is stored, not applied (D18).
        self._pull_heading()
        super()._resolve_structural()

    def _pull_heading(self) -> None:
        """Apply a pending linked heading before anything reads the points it
        rewrites. Never inside the shape's own update (a batch): there ``angle``
        is stored, not applied."""
        a = self.__dict__.get('_heading_anchor')
        if (a is not None and a._dirty and a._link is not None
                and not self._resolving and not self._in_batch_update):
            a._ensure_fresh()

    def _note_heading_link_installed(self) -> None:
        """Route reads of the points the turn rewrites through this shape."""
        for part in self._heading_driven_parts():
            target = self if isinstance(part, FieldRef) else part
            target.__dict__['_pull_owner'] = self
        self._invalidate_bare_reads()

    def _heading_link_active(self) -> bool:
        anchor = (self.__dict__.get('_field_anchors') or {}).get(self._HEADING_FIELD)
        return anchor is not None and anchor._link is not None

    def _refuse_heading_link_over_linked_parts(self) -> None:
        """``angle @=`` while a part its turn rewrites, or a part it is
        measured from (``_heading_pivot_inputs``), is linked."""
        for part, label, pivot in self._heading_exclusive():
            if isinstance(part, FieldRef):
                linked = part.is_linked
            else:
                linked = any(n._link is not None for n in part._iter_subtree())
            if linked:
                from .entity import entity_label
                raise LinkedAttributeError(driver_conflict_message(
                    new="link", subject=entity_label(self), part=self._HEADING_FIELD,
                    existing=self._heading_conflict_text(label, pivot, False),
                    undo=(f"Unlink {label} first, or leave {self._HEADING_FIELD} unlinked"
                          + self._heading_pivot_hint(pivot))))

    def _heading_pivot_hint(self, pivot: bool) -> str:
        return ""

    def _ensure_can_link_attribute(self, target) -> None:
        super()._ensure_can_link_attribute(target)
        if (self._heading_link_active() and _rotation_is_derived(self, self._HEADING_FIELD)):
            anchor = self.__dict__['_field_anchors'][self._HEADING_FIELD]
            if target is anchor:
                return
            for part, label, pivot in self._heading_exclusive():
                if _link_overlaps_part(target, part):
                    from .entity import entity_label
                    raise LinkedAttributeError(driver_conflict_message(
                        new="link", subject=entity_label(self), part=label,
                        existing=self._heading_conflict_text(label, pivot, True),
                        undo=(f"Unlink {self._HEADING_FIELD} first, or leave {label} unlinked"
                              + self._heading_pivot_hint(pivot))))

    def _scalar_anchor_class(self, name: str):
        # One anchor type for every use of ``["angle"]`` (link or formula
        # source): a property anchor, whose writes go through ``rotate_to``.
        if name == self._HEADING_FIELD and _rotation_is_derived(self, name):
            from .state import _PropertyAnchor
            return _PropertyAnchor
        return super()._scalar_anchor_class(name)


class _HeadingFromGeometry:
    """Where the heading ``angle`` is derived from the geometry (Line ``p1 → p2``,
    a Circle placed by its rim), its anchor is a property anchor, not a stored
    value.

    A formula that names ``shape.angle`` depends on that anchor, which only the
    pose verbs mark dirty. Here the anchor also depends on the shape, so every
    change that reaches the shape — a written or dragged endpoint, a flip —
    re-runs those formulas (G18: a heading arrow linked to the heading stayed
    put on ``flip_x``). A Defining ``angle`` is a plain slot: its own writes
    notify it.
    """

    def _ensure_scalar_anchor(self, name: str, anchor_cls: type = None):
        anchor = super()._ensure_scalar_anchor(name, anchor_cls)
        if (name == 'angle' and isinstance(anchor, _PropertyAnchor)
                and not anchor.__dict__.get('_reads_owner')):
            ss = getattr(self, '_scena_system', None)
            if ss is not None:
                ss.add_dependency(anchor, self)      # once per anchor (a rebuilt one re-adds)
                anchor.__dict__['_reads_owner'] = True
        return anchor


# Line models whose heading follows a circle (a flip gates their points with no pivot).
_LINE_TANGENT_MODELS = frozenset({LineModel.TANGENT_ANGLE, LineModel.TANGENT_POINT})

# Line models whose about-center turn writes only free inputs (SB11 fast path).
_LINE_FAST_TURN_MODELS = frozenset({
    LineModel.POINT_POINT, LineModel.CENTER_LENGTH_ANGLE, LineModel.POINT_ANGLE_LENGTH,
})


class Line(_HeadingFromGeometry, _DerivedRotationRoute, Shape):
    """
    Line Constructor parameters:
    (see __new__ signatures for proper usage, not all parameters are required at the same time)
      - center, length, angle: Home model
      - p1 and p2: Points defining the line
      - x1, y1, x2, y2: Coordinates defining the line
      - vec: Vector from p1 to p2
      - angle: Angle of the line
      - length: Length of the line
      - dx, dy: Delta x and y defining the line from p1

    Common optional parameters come from the shared Shape extractor
    (``_extract_common_params_and_signature``), not from a Line signature:
      - layer, group, visual, color, line_width
    ``line_width`` is stroke thickness; omit it to keep the paint prototype (1.5).

    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        length: Length (with ``angle``, around ``center``; or from ``p1``).
        angle: Direction in degrees.
        p1: Start point.
        p2: End point.
        vec: From ``p1``: the line as a vector.
        dx: From ``p1``: x extent (with ``dy``).
        dy: From ``p1``: y extent.
        parallel_to: A Line to copy the direction of (with ``p1`` + ``length``, or
            ``dist``).
        dist: With ``parallel_to``: offset of the parallel copy (positive = left of its
            direction).
        perpendicular_to: A Line to stand perpendicular to, starting at ``p1`` (with
            ``length``).
        circle: A Circle: tangent line (with ``at_angle`` + ``length``, or ``from_point`` +
            ``side``).
        from_point: With ``circle``: the outside point the tangent starts from.
        side: With ``circle`` + ``from_point``: ``"left"`` or ``"right"`` tangent.
    """

    p1     = ContainerSlot(Point)
    p2     = ContainerSlot(Point)
    vec    = ContainerSlot(Vec2, FieldType.Derivate)
    angle  = ScalarSlot(label="Line.angle")
    length = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="Line.length")
    center = ContainerSlot(Point, FieldType.Derivate)
    dx     = ScalarSlot()
    dy     = ScalarSlot()
    dist   = ScalarSlot()
    # Tangent model only: the touch point's position around the circle (degrees).
    # The heading ``angle`` is then ``at_angle + 90``.
    at_angle = ScalarSlot(label="Line.at_angle")

    # Home model = CENTER_LENGTH_ANGLE (same as Line() / Line(center=…)).
    _ink_strict = True          # bracket typos stay AttributeError (Entity.__getitem__)
    _HOME_KEYS = frozenset({"center", "length", "angle"})
    _HOME_OPTIONAL_KEYS = frozenset()
    _HOME_SIZE_KEYS = frozenset({"length", "angle"})

    # Scalar endpoints are a spelling other frameworks use; Line takes points.
    _CTOR_KWARG_HINTS = {
        key: "Line takes points: p1=(x1, y1), p2=(x2, y2)"
        for key in ("x1", "y1", "x2", "y2")
    }

    # The list of valid signatures, each with (name, exact_keys)
    _CONSTRUCTOR_SIGNATURES = [
        ("center_length_angle", {"center", "length", "angle"}),
        ("point_point",   {"p1", "p2"}),
        ("point_vec",     {"p1", "vec"}),
        ("point_dx_dy",   {"p1", "dx", "dy"}),
        ("point_ang_len", {"p1", "angle", "length"}),
        ("parallel_point",      {"p1", "parallel_to", "length"}),
        ("parallel_dist",       {"dist", "parallel_to"}),
        ("perpendicular_point", {"p1", "perpendicular_to", "length"}),
        ("tangent_angle",       {"circle", "at_angle", "length"}),
        ("tangent_point",       {"circle", "from_point", "side"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Defaults for omitted home keys only.

        ``_apply_home_fill`` injects a key the author left out. Do not read
        keys they passed: a lambda there is a link, and ``float()`` / ``number()``
        on it rejects the home form while every other Line form accepts it.
        """
        del kwargs
        (cx, cy), unit = _default_pose()
        return {"center": (cx, cy), "length": 2.0 * unit, "angle": 0.0}

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...
    @overload
    def __new__(cls, *, center: GeneralPoint, length: float, angle: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...
    
    @overload
    def __new__(cls, *, p1: GeneralPoint, p2: GeneralPoint, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...
    
    @overload
    def __new__(cls, *, p1: GeneralPoint, vec: Vec2, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...
    
    @overload
    def __new__(cls, *, p1: GeneralPoint, angle: float, length: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...
    
    @overload
    def __new__(cls, *, p1: GeneralPoint, dx: float, dy: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, parallel_to: 'Line', length: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    @overload
    def __new__(cls, *, dist: float, parallel_to: 'Line', layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, perpendicular_to: 'Line', length: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    @overload
    def __new__(cls, *, circle: 'Circle', at_angle: float, length: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    @overload
    def __new__(cls, *, circle: 'Circle', from_point: GeneralPoint, side: str, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Line': ...

    def __new__(cls, *args, **kwargs):
        # Create the instance
        return super().__new__(cls)
        

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        if "circle" in kwargs and "angle" in kwargs:
            raise TypeError(
                "Line(circle=, angle=…): the touch point's position around the circle "
                "is at_angle= — Line(circle=c, at_angle=40, length=20). The line's "
                "heading (angle) is then at_angle + 90."
            )
        # Extract common Shape parameters and determine signature
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs, 
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )

        # Initialize the base class
        super().__init__(**base_params)

        # Plain (non-reactive) references used by the relational models below.
        self._ref = None
        self._tangent_side = None

        # Dispatch to the right initialization path based on signature:
        match signature:
            case "center_length_angle":
                # Home: Line() / Line(center=…) / Line(length=, angle=) / full.
                self.model = LineModel.CENTER_LENGTH_ANGLE
                self._set_defining_parts('center', 'angle', 'length')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _reject_non_finite(kwargs['angle'], what="Line.angle")
                    _reject_bad_length(kwargs['length'], what="Line.length")
                    _init_scalar(self, 'angle', kwargs['angle'])
                    _init_scalar(self, 'length', kwargs['length'])

            case "point_point":
                # Example: Line(p1=(100, 100), p2=c1.center)
                # Bare args copy; callables install a live link (same for scalars).
                p1 = kwargs['p1']
                p2 = kwargs['p2']

                # Set the proper attributes
                self.model = LineModel.POINT_POINT
                self._set_defining_parts('p1', 'p2')
                with self._batch_update():
                    _init_composite(self.p1, p1)
                    _init_composite(self.p2, p2)
                
            case "point_vec":
                p1 = kwargs['p1']
                vec = kwargs['vec']
                
                # Set the proper attributes
                self.model = LineModel.POINT_VEC
                self._set_defining_parts('p1', 'vec')
                with self._batch_update():
                    _init_composite(self.p1, p1)
                    _init_composite(self.vec, vec)


            case "point_dx_dy":
                p1 = kwargs['p1']
                dx = kwargs['dx']
                dy = kwargs['dy']
                
                # Set the proper attributes
                self.model = LineModel.POINT_DX_DY
                self._set_defining_parts('p1', 'dx', 'dy')
                with self._batch_update():
                    _init_composite(self.p1, p1)
                    _init_scalar(self, 'dx', dx)
                    _init_scalar(self, 'dy', dy)

            case "point_ang_len":
                p1 = kwargs['p1']
                angle = kwargs['angle']
                length = kwargs['length']
                
                # Set the proper attributes
                self.model = LineModel.POINT_ANGLE_LENGTH
                self._set_defining_parts('p1', 'angle', 'length')
                with self._batch_update():
                    _init_composite(self.p1, p1)
                    _reject_non_finite(angle, what="Line.angle")
                    _reject_bad_length(length, what="Line.length")
                    _init_scalar(self, 'angle', angle)
                    _init_scalar(self, 'length', length)

            case "parallel_point":
                # Example: Line(p1=p, parallel_to=ref_line, length=L)
                ref = kwargs['parallel_to']
                self._ref = _live_ref(ref, type(self).__name__, "Line", "parallel_to")
                self.model = LineModel.PARALLEL_POINT
                self._set_defining_parts('p1', 'angle', 'length')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    self["angle"] @= (lambda: ref.angle)
                    _reject_bad_length(kwargs['length'], what="Line.length")
                    _init_scalar(self, 'length', kwargs['length'])

            case "perpendicular_point":
                # Example: Line(p1=p, perpendicular_to=ref_line, length=L)
                ref = kwargs['perpendicular_to']
                self._ref = _live_ref(ref, type(self).__name__, "Line", "perpendicular_to")
                self.model = LineModel.PERPENDICULAR_POINT
                self._set_defining_parts('p1', 'angle', 'length')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    self["angle"] @= (lambda: ref.angle + 90.0)
                    _reject_bad_length(kwargs['length'], what="Line.length")
                    _init_scalar(self, 'length', kwargs['length'])

            case "parallel_dist":
                # Example: Line(dist=d, parallel_to=ref_line) -- a full offset copy of ref_line.
                ref = kwargs['parallel_to']
                self._ref = _live_ref(ref, type(self).__name__, "Line", "parallel_to")
                self.model = LineModel.PARALLEL_DIST
                self._set_defining_parts('dist', 'angle', 'length', 'p1')
                with self._batch_update():
                    _init_scalar(self, 'dist', kwargs['dist'])
                    self["angle"] @= (lambda: ref.angle)
                    self["length"] @= (lambda: ref.length)
                    # Bind a ScalarAnchor so the formula depends on `dist`, not
                    # on `self` (which would cycle: p1 is a part of the Line).
                    dist_src = self._ensure_scalar_anchor('dist')
                    self.p1 @= (lambda: _parallel_offset_point(ref, dist_src.value))

            case "tangent_angle":
                # Example: Line(circle=c, at_angle=theta, length=L) -- tangent at a
                # given position around the circle. The heading is at_angle + 90.
                circle = kwargs['circle']
                self._ref = _live_ref(circle, type(self).__name__, "Circle", "circle")
                self.model = LineModel.TANGENT_ANGLE
                self._set_defining_parts('p1', 'at_angle', 'length')
                with self._batch_update():
                    _reject_non_finite(kwargs['at_angle'], what="Line.at_angle")
                    _reject_bad_length(kwargs['length'], what="Line.length")
                    _init_scalar(self, 'at_angle', kwargs['at_angle'])
                    _init_scalar(self, 'length', kwargs['length'])
                    at_src = self._ensure_scalar_anchor('at_angle')
                    self.p1 @= (lambda: _circle_point_at_angle(circle, at_src.value))

            case "tangent_point":
                # Example: Line(circle=c, from_point=p, side='left'|'right')
                circle = kwargs['circle']
                side = kwargs['side']
                if side not in ('left', 'right'):
                    raise ValueError(f"side must be 'left' or 'right', got {side!r}")
                self._ref = _live_ref(circle, type(self).__name__, "Circle", "circle")
                self._tangent_side = side
                self.model = LineModel.TANGENT_POINT
                self._set_defining_parts('p1', 'p2')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['from_point'])
                    self.p2 @= (lambda: _circle_tangent_touch_point(circle, self.p1, side))

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        # ``angle`` is the heading (direction p1 → p2): the pose store starts there
        # (a Defining ``angle`` as written, so ``angle=290`` keeps its turn).
        _pose_rotation_set(self, self._rotation_value())

    def _heading_value(self) -> float:
        """Direction ``p1 → p2`` in degrees, from Defining inputs only (D3-cold).

        Unwrapped to the turn of the accumulated pose value, so a full turn
        still reads ``+360`` (the heading contract of every kind) while the
        value always matches the segment.
        """
        acc = float(getattr(self, '_rotation', 0.0) or 0.0)   # a slot, not __dict__
        x1, y1, x2, y2 = self._segment_xy()
        if not (x2 - x1 or y2 - y1):
            return acc
        return _unwrap_deg(math.degrees(math.atan2(y2 - y1, x2 - x1)), acc)

    def _rotation_value(self) -> float:
        """The heading from Defining inputs only (never wakes a Derivate ``angle``)."""
        if 'angle' in (getattr(self, '_defining_part_names', None) or ()):
            return _bare_num(self.angle)
        if self.model is LineModel.TANGENT_ANGLE:
            # The model's own heading, as ``angle`` reads it (SB4: 290 vs -70,
            # so ``rotate_to(l.angle)`` added a full turn).
            return _bare_num(self.at_angle) + 90.0
        return self._heading_value()

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark Defining parts; leave cold Derivates unregistered until access/link."""
        self._mark_defining_parts(
            *defining,
            catalog=('p1', 'p2', 'vec', 'angle', 'length', 'center', 'dx', 'dy', 'dist', 'at_angle'),
        )

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access via model ``_update_impl``."""
        self._pull_heading()
        with self._no_update():
            self._update_impl()

    def _defining_names_for(self, model) -> Optional[Tuple[str, ...]]:
        return _LINE_MODEL_DEFINING.get(model)

    @staticmethod
    def _free_model(model):
        return _LINE_FREE_MODEL.get(model, model)

    def _takein_impl(self, other: 'Line') -> None:
        """Copy Line-specific attributes based on the line model.

        Copies current resolved *values* only. A relational source (parallel /
        perpendicular / tangent) arrives as its free twin with no ``_ref``
        (``_free_model``): a copy has no links to follow.
        """
        # Always copy the model first
        self._adopt_model_of(other)
        same = self.model is other.model
        self._ref = other._ref if same else None
        self._tangent_side = other._tangent_side if same else None

        # Copy only the defining attributes for the current model
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                self.center._takein(other.center)
                _init_scalar(self, 'angle', other.angle)
                _init_scalar(self, 'length', other.length)
            case LineModel.POINT_POINT:
                self.p1._takein(other.p1)
                self.p2._takein(other.p2)
            case LineModel.POINT_VEC:
                self.p1._takein(other.p1)
                self.vec._takein(other.vec)
            case LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT | LineModel.PERPENDICULAR_POINT:
                self.p1._takein(other.p1)
                _init_scalar(self, 'angle', other.angle)
                _init_scalar(self, 'length', other.length)
            case LineModel.POINT_DX_DY:
                self.p1._takein(other.p1)
                _init_scalar(self, 'dx', other.dx)
                _init_scalar(self, 'dy', other.dy)
            case LineModel.PARALLEL_DIST:
                _init_scalar(self, 'dist', other.dist)
                _init_scalar(self, 'angle', other.angle)
                _init_scalar(self, 'length', other.length)
                self.p1._takein(other.p1)
            case LineModel.TANGENT_ANGLE:
                _init_scalar(self, 'at_angle', other.at_angle)
                _init_scalar(self, 'length', other.length)
                self.p1._takein(other.p1)
            case LineModel.TANGENT_POINT:
                self.p1._takein(other.p1)
                self.p2._takein(other.p2)
            case _:
                raise ValueError(f"Unknown line model: {self.model}")

    def _update_impl(self) -> None:
        """Update derived attributes based on the line model."""
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                self._update_impl_center_length_angle()
            case LineModel.POINT_POINT | LineModel.TANGENT_POINT:
                self._update_impl_pointpoint()
            case LineModel.POINT_VEC:
                self._update_impl_pointvec()
            case LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT | LineModel.PERPENDICULAR_POINT | LineModel.PARALLEL_DIST:
                self._update_impl_pointanglen()
            case LineModel.POINT_DX_DY:
                self._update_impl_pointdxdy()
            case LineModel.TANGENT_ANGLE:
                self._update_impl_tangent_angle()
            case _:
                raise ValueError(f"Unknown line model: {self.model}")

    def _segment_xy(self) -> Tuple[float, float, float, float]:
        """World ``(x1, y1, x2, y2)`` from Defining inputs only.

        Never ``getattr`` Derivate ``p2`` / ``center`` / ``vec`` — collision
        proxy / pose keys and relational helpers must not wake cold slots.
        """
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                cx, cy = get_xy(self.center, bare=True)
                half = 0.5 * _bare_num(self.length)
                rad = math.radians(_bare_num(self.angle))
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                return (
                    cx - half * cos_a, cy - half * sin_a,
                    cx + half * cos_a, cy + half * sin_a,
                )
            case LineModel.POINT_POINT | LineModel.TANGENT_POINT:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                return (x1, y1, x2, y2)
            case LineModel.POINT_VEC:
                x1, y1 = get_xy(self.p1, bare=True)
                vx, vy = _bare_num(self.vec.x), _bare_num(self.vec.y)
                return (x1, y1, x1 + vx, y1 + vy)
            case (LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT
                  | LineModel.PERPENDICULAR_POINT | LineModel.PARALLEL_DIST):
                x1, y1 = get_xy(self.p1, bare=True)
                length = _bare_num(self.length)
                rad = math.radians(_bare_num(self.angle))
                dx = length * math.cos(rad)
                dy = length * math.sin(rad)
                return (x1, y1, x1 + dx, y1 + dy)
            case LineModel.POINT_DX_DY:
                x1, y1 = get_xy(self.p1, bare=True)
                dx, dy = _bare_num(self.dx), _bare_num(self.dy)
                return (x1, y1, x1 + dx, y1 + dy)
            case LineModel.TANGENT_ANGLE:
                # ``at_angle`` is the circle-position; the heading is at_angle + 90°.
                x1, y1 = get_xy(self.p1, bare=True)
                length = _bare_num(self.length)
                rad = math.radians(_bare_num(self.at_angle) + 90.0)
                dx = length * math.cos(rad)
                dy = length * math.sin(rad)
                return (x1, y1, x1 + dx, y1 + dy)
            case _:
                raise ValueError(f"Unknown line model: {self.model}")

    def _collision_pose_anchor(self) -> Tuple[float, float]:
        """Segment midpoint from Defining geometry (does not wake Derivate center).

        The home model's center is Defining: read it, not the mean of the ends
        recomputed from it. That mean drifts an ulp after a scale about a
        linked center, the gate compares the pivot exactly, and every later
        verb about the center was refused (GX16 in Testing Design)."""
        if self.model is LineModel.CENTER_LENGTH_ANGLE:
            return get_xy(self.center, bare=True)
        x1, y1, x2, y2 = self._segment_xy()
        return (0.5 * (x1 + x2), 0.5 * (y1 + y2))

    def _center_xy(self) -> Tuple[float, float]:
        """Pose center from Defining inputs only — never materialize Derivate ``center``."""
        return self._collision_pose_anchor()

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, line_width, dx1, dy1, dx2, dy2)`` — midpoint-relative ends.

        Pose keys are ``(epoch, cx, cy, *extra)``. Relative ends stay identical
        under rigid translation (proxy translate fast-path) and change when the
        segment rotates, stretches, or an endpoint moves independently. Built
        from ``_segment_xy()`` so Derivate ``center`` / ``p2`` / ``vec`` stay cold.
        ``line_width`` is included so thickness changes rebuild the thin OBB.
        """
        try:
            rot = float(self._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(self._scale)
        except Exception:
            scale = 1.0
        try:
            lw = float(self.line_width)
        except Exception:
            lw = 1.0
        x1, y1, x2, y2 = self._segment_xy()
        mx = 0.5 * (x1 + x2)
        my = 0.5 * (y1 + y2)
        return (rot, scale, lw, x1 - mx, y1 - my, x2 - mx, y2 - my)

    def _update_impl_tangent_angle(self) -> None:
        """Update live Derivates from p1 (touch) + heading (at_angle + 90°)."""
        x1, y1, x2, y2 = self._segment_xy()
        dx, dy = x2 - x1, y2 - y1
        self._takein_live_derivate('angle', _bare_num(self.at_angle) + 90.0)
        self._takein_live_derivate('vec', (dx, dy))
        self._takein_live_derivate('p2', (x2, y2))
        self._takein_live_derivate('center', (0.5 * (x1 + x2), 0.5 * (y1 + y2)))
        self._takein_live_derivate('dx', dx)
        self._takein_live_derivate('dy', dy)

    def _update_impl_center_length_angle(self) -> None:
        """Derive endpoints from Defining center, angle, length (home model)."""
        half = 0.5 * _bare_num(self.length)
        rad = math.radians(_bare_num(self.angle))
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        cx, cy = get_xy(self.center, bare=True)
        dx = half * cos_a * 2.0  # full span
        dy = half * sin_a * 2.0
        self._takein_live_derivate('p1', (cx - half * cos_a, cy - half * sin_a))
        self._takein_live_derivate('p2', (cx + half * cos_a, cy + half * sin_a))
        self._takein_live_derivate('vec', (dx, dy))
        self._takein_live_derivate('dx', dx)
        self._takein_live_derivate('dy', dy)

    @batch_update_attrs('vec', 'center', 'length', 'angle', 'dx', 'dy')
    def _update_impl_pointpoint(self) -> None:
        """Update live derived attributes based on p1 and p2."""
        dx = _bare_num(self.p2.x) - _bare_num(self.p1.x)
        dy = _bare_num(self.p2.y) - _bare_num(self.p1.y)

        vec = self.__dict__.get('vec')
        if vec is not None and (vec._field_type == FieldType.Defining or vec._is_derivate_live()):
            self.vec.x = dx
            self.vec.y = dy
            self.vec._update_impl()
            length_val = _bare_num(self.vec.length)
        else:
            length_val = math.hypot(dx, dy)
        # Keeps full turns (+400, not 40): unwrapped to the pose store.
        acc = float(getattr(self, '_rotation', 0.0) or 0.0)
        angle_val = _unwrap_deg(_deg(math.atan2(dy, dx)), acc) if (dx or dy) else acc

        center = self.__dict__.get('center')
        if center is not None and (
            center._field_type == FieldType.Defining or center._is_derivate_live()
        ):
            # The slot directly: an engine recompute is not an author
            # placement (``Point.__setattr__`` notes one, X-writers-4).
            c = self.center
            Point.__dict__["x"].__set__(c, (_bare_num(self.p1.x) + _bare_num(self.p2.x)) / 2)
            Point.__dict__["y"].__set__(c, (_bare_num(self.p1.y) + _bare_num(self.p2.y)) / 2)

        length = self.__dict__.get('length')
        if self._field_is_derivate('length'):
            self.length = length_val
        elif isinstance(length, Container) and (
            length._field_type == FieldType.Defining or length._is_derivate_live()
        ):
            self.length = length_val

        angle = self.__dict__.get('angle')
        if self._field_is_derivate('angle'):
            self.angle = angle_val
        elif isinstance(angle, Container) and (
            angle._field_type == FieldType.Defining or angle._is_derivate_live()
        ):
            self.angle = angle_val

        for name, val in (('dx', dx), ('dy', dy)):
            if self._field_is_derivate(name):
                setattr(self, name, val)
                continue
            part = self.__dict__.get(name)
            if isinstance(part, Container) and (
                part._field_type == FieldType.Defining or part._is_derivate_live()
            ):
                part._takein(val)

    def _update_impl_pointvec(self) -> None:
        """Update live Derivates from Defining p1 + vec."""
        x1, y1 = get_xy(self.p1, bare=True)
        vx, vy = _bare_num(self.vec.x), _bare_num(self.vec.y)
        # Keep Vec2's own Derivate length/angle fresh when present.
        self.vec._update_impl()
        x2, y2 = x1 + vx, y1 + vy
        self._takein_live_derivate('p2', (x2, y2))
        self._takein_live_derivate('center', (0.5 * (x1 + x2), 0.5 * (y1 + y2)))
        self._takein_live_derivate('length', math.hypot(vx, vy))
        self._takein_live_derivate('angle', self._heading_value())
        self._takein_live_derivate('dx', vx)
        self._takein_live_derivate('dy', vy)

    def _update_impl_pointanglen(self) -> None:
        """Update live Derivates from Defining p1, angle, and length."""
        x1, y1, x2, y2 = self._segment_xy()
        dx, dy = x2 - x1, y2 - y1
        self._takein_live_derivate('vec', (dx, dy))
        self._takein_live_derivate('p2', (x2, y2))
        self._takein_live_derivate('center', (0.5 * (x1 + x2), 0.5 * (y1 + y2)))
        self._takein_live_derivate('dx', dx)
        self._takein_live_derivate('dy', dy)

    def _update_impl_pointdxdy(self) -> None:
        """Update live Derivates from Defining p1, dx, and dy."""
        x1, y1, x2, y2 = self._segment_xy()
        dx, dy = x2 - x1, y2 - y1
        self._takein_live_derivate('p2', (x2, y2))
        self._takein_live_derivate('center', (0.5 * (x1 + x2), 0.5 * (y1 + y2)))
        self._takein_live_derivate('vec', (dx, dy))
        self._takein_live_derivate('length', math.hypot(dx, dy))
        self._takein_live_derivate('angle', self._heading_value())


    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw in midpoint-local CTM so Gradient/Texture shaders align with the segment.

        Local +x runs along p1→p2; the segment is ``[-half_len, +half_len]`` on x.
        """
        skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if not skia_line_paint:
            return
        x1, y1, x2, y2 = self._segment_xy()  # Defining only (D3)
        cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
        dx, dy = x2 - x1, y2 - y1
        half = 0.5 * math.hypot(dx, dy)
        ang = math.degrees(math.atan2(dy, dx)) if (dx or dy) else 0.0
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        skia_canvas.drawLine(-half, 0.0, half, 0.0, skia_line_paint)
        skia_canvas.restore()

    @property
    def is_collapsed(self) -> bool:
        """True when segment length is ``0``."""
        if float(self._scale) == 0.0:
            return True
        x1, y1, x2, y2 = self._segment_xy()     # Defining only: a cold length stays cold
        return x1 == x2 and y1 == y2

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit-test against the segment p1→p2 with line_width/HIT_PADDING tolerance."""
        # Defining inputs only: one hover used to wake p2 / length for good (SC6).
        x1, y1, x2, y2 = self._segment_xy()
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        radius = max(self.line_width / 2.0, HIT_PADDING)
        if length_sq == 0.0:
            return math.hypot(x - x1, y - y1) <= radius
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(x - proj_x, y - proj_y) <= radius

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                return (self.center,)
            case LineModel.POINT_POINT:
                return (self.p1, self.p2)
            case LineModel.PARALLEL_DIST:
                # p1 is formula-linked; the free input the drag actually writes is dist.
                return (self["dist"],)
            case (LineModel.POINT_VEC | LineModel.POINT_ANGLE_LENGTH | LineModel.POINT_DX_DY
                  | LineModel.PARALLEL_POINT | LineModel.PERPENDICULAR_POINT
                  | LineModel.TANGENT_POINT | LineModel.TANGENT_ANGLE):
                return (self.p1,)
            case _:
                return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        # Matches rotate_by(..., about=None) — center pivot + the heading.
        rot = self["angle"]
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                return (rot,)
            case LineModel.POINT_POINT:
                return (self.p1, self.p2, rot)
            case LineModel.POINT_VEC:
                return (self.p1, self.vec, rot)
            case (LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT
                  | LineModel.PERPENDICULAR_POINT | LineModel.PARALLEL_DIST):
                return (self.p1, rot)
            case LineModel.TANGENT_ANGLE:
                return (self["at_angle"], rot)
            case LineModel.TANGENT_POINT:
                return (self.p1, rot)
            case LineModel.POINT_DX_DY:
                return (self.p1, self["dx"], self["dy"], rot)
            case _:
                return (rot,)

    def _clone_geometry(self, **kwargs) -> 'Line':
        # The copy keeps a free model (SB6: every clone was POINT_POINT, so
        # ``clone().length = 20`` raised); a relational model takes its free
        # twin. One path with ``<<``: build, then take the source in.
        x1, y1, x2, y2 = self._segment_xy()
        copy = type(self)(p1=(x1, y1), p2=(x2, y2), **kwargs)
        copy._takein(self)
        return copy

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Line':
        """Translate Defining position inputs only (model-aware).

        Unlinked free models use A1 bare-float writes (A4). Linked / relational
        models (and ``force=True``) take the batched Attribute path.
        """
        if _pose_fast_ok(self, force=force):
            match self.model:
                case LineModel.CENTER_LENGTH_ANGLE:
                    _translate_point_float(self.center, dx, dy)
                    return self
                case LineModel.POINT_POINT:
                    _translate_points_float((self.p1, self.p2), dx, dy)
                    return self
                case (LineModel.POINT_VEC | LineModel.POINT_ANGLE_LENGTH
                      | LineModel.POINT_DX_DY | LineModel.PARALLEL_POINT
                      | LineModel.PERPENDICULAR_POINT | LineModel.TANGENT_POINT):
                    _translate_point_float(self.p1, dx, dy)
                    return self
                case LineModel.PARALLEL_DIST | LineModel.TANGENT_ANGLE:
                    # p1 is formula-linked at construction — pull flag is set;
                    # fall through to batched path.
                    pass
                case _:
                    raise ValueError(f"Unknown line model: {self.model}")
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> 'Line':
        """Batched translate — used when pull consumers exist or force=True."""
        if self.model is LineModel.TANGENT_POINT:
            # Moving the from-point re-solves the tangent. Gated whatever the
            # amount, like every linked part: the timed verbs probe with a
            # zero move (GX4 in Testing Design).
            self._gate_tangent("move_by", force)
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                _ensure_writable(self.center, "move_by", force=force)
                if dx is not None:
                    self.center.x += dx
                if dy is not None:
                    self.center.y += dy
            case LineModel.POINT_POINT:
                _ensure_writable(self.p1, "move_by", force=force)
                _ensure_writable(self.p2, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                    self.p2.x += dx
                if dy is not None:
                    self.p1.y += dy
                    self.p2.y += dy
            case (LineModel.POINT_VEC | LineModel.POINT_ANGLE_LENGTH
                  | LineModel.POINT_DX_DY | LineModel.PARALLEL_POINT
                  | LineModel.PERPENDICULAR_POINT | LineModel.TANGENT_POINT):
                _ensure_writable(self.p1, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                if dy is not None:
                    self.p1.y += dy
            case LineModel.PARALLEL_DIST:
                # p1 stays linked to the reference. Project the delta onto the
                # reference left-normal and add it to dist. Along-track motion
                # is ignored. A zero-length reference has no normal: no-op.
                _ensure_writable(self["dist"], "move_by", force=force)
                ref = self._ref
                if ref is None:
                    return self
                x1, y1, x2, y2 = ref._segment_xy()
                vx, vy = x2 - x1, y2 - y1
                seg_len = math.hypot(vx, vy)
                if seg_len == 0.0:
                    return self
                nx, ny = -vy / seg_len, vx / seg_len
                ddx = 0.0 if dx is None else float(dx)
                ddy = 0.0 if dy is None else float(dy)
                self.dist = _bare_num(self.dist) + ddx * nx + ddy * ny
            case LineModel.TANGENT_ANGLE:
                # Touch point is pinned to the circle. Slide with angle=, not a
                # translation. force=True unlinks p1 (same as other linked parts).
                _ensure_writable(self.p1, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                if dy is not None:
                    self.p1.y += dy
            case _:
                raise ValueError(f"Unknown line model: {self.model}")
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Line':
        """Move the line's center to absolute x and/or y coordinates.

        Writes both axes in one translate (not two sequential ``_move_by``
        calls) so POINT_POINT pays 2 Point takeins, not 4 ScalarSlot writes.
        """
        if self.model == LineModel.CENTER_LENGTH_ANGLE:
            if _pose_fast_ok(self, force=force):
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                nx = cx if x is None else float(x)
                ny = cy if y is None else float(y)
                if nx != cx:
                    _takein_xy_float(self.center, x=nx)
                if ny != cy:
                    _takein_xy_float(self.center, y=ny)
                return self
            return self._move_to_center(x, y, force=force)

        cx, cy = self._center_xy()
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
            return self
        return self._move_by(dx, dy, force=force)

    @batch_update_self()
    def _move_to_center(self, x: float, y: float, *, force: bool = False) -> 'Line':
        _ensure_writable(self.center, "move_to", force=force)
        cx, cy = get_xy(self.center, bare=True)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if nx != cx or ny != cy:
            self.center._takein((nx, ny))
        return self

    def _relational_move_hint(self, var: str) -> Optional[str]:
        """A parallel-by-distance line cannot put a point anywhere: a move
        only changes ``dist`` (Shapes Design — relational models). The
        DerivedAttributeError hint said ``move_to(…)``, which landed
        elsewhere (graphics review GR2)."""
        if self.model is LineModel.PARALLEL_DIST:
            return (f"It stays parallel to its reference, so a move only changes its distance: "
                    f"write {var}.dist = …, or move the reference.")
        return None

    def _mirror_geometry(self, axis: str, *, force: bool = False) -> None:
        model = self.model
        if model in _LINE_TANGENT_MODELS:
            # A tangent line's heading is the circle's tangent at its touch
            # point. At length 0 its points sit on the pivot, so the pivot
            # exemption let a flip through and the pose store left the drawn
            # heading (GX3 in Testing Design): gate them as at any length.
            for pt in self._mirror_points():
                _ensure_writable(pt, "flip", force=force)
        # A zero-length segment moves no point: the generic mirror refreshes
        # the derived heading from the mirrored store itself (GX2).
        Shape._mirror_geometry(self, axis, force=force)

    def _heading_driven_parts(self) -> Tuple:
        # The parts rotate_by writes where ``angle`` is derived (see rotate_by).
        match self.model:
            case LineModel.POINT_POINT:
                return (self.p1, self.p2)
            case LineModel.POINT_VEC:
                return (self.p1, self.vec)
            case LineModel.POINT_DX_DY:
                return (self.p1, self["dx"], self["dy"])
            case LineModel.TANGENT_ANGLE:
                return (self["at_angle"],)
            case LineModel.TANGENT_POINT:
                return (self.p1,)
        return ()

    _TANGENT_HINT = (" A tangent line keeps touching its circle: it turns about the"
                     " circle's center (the default pivot). Move the circle, or its"
                     " from-point / at_angle, to place it.")

    def _tangent_circle_xy(self):
        return self._ref._center_xy() if self._ref is not None else None

    def _gate_tangent(self, operation: str, force: bool, about=None) -> None:
        """What a tangent Line's pose verbs do (Shapes Design — relational lines):
        a turn orbits the circle's center (the default pivot); a TANGENT_ANGLE
        scale changes the length about the pinned touch point; anything else
        refuses (SB1 / SB4: an explicit ``about=`` was silently ignored, and a
        from-point tangent turned about the from-point and stretched).
        ``force=True`` frees the line and the verb runs on its free twin."""
        model = self.model
        if model not in (LineModel.TANGENT_ANGLE, LineModel.TANGENT_POINT):
            return
        turn = operation in ("rotate_by", "rotate_to")
        if about is None and (turn or (operation == "scale_by" and model is LineModel.TANGENT_ANGLE)):
            return
        if about is not None and turn:
            c = self._tangent_circle_xy()
            ax, ay = get_xy(about, bare=True)
            if c is not None and abs(ax - c[0]) <= 1e-9 and abs(ay - c[1]) <= 1e-9:
                return
        if about is not None and operation == "scale_by" and model is LineModel.TANGENT_ANGLE:
            ax, ay = get_xy(about, bare=True)
            tx, ty = get_xy(self.p1, bare=True)
            if abs(ax - tx) <= 1e-9 and abs(ay - ty) <= 1e-9:
                return
        linked = self.p1 if model is LineModel.TANGENT_ANGLE else self.p2
        _ensure_writable(linked, operation, force=force, undo_extra=self._TANGENT_HINT)

    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Line':
        """Rotate Defining geometry about a pivot by angle degrees.

        A free line turned about its center takes bare float writes, as
        Ellipse and Rect do (graphics review SB11: 32 µs against 10–15 for
        its siblings). Anything linked, pulled or read falls to the batch."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        model = self.model
        if (model in _LINE_FAST_TURN_MODELS and not force
                and not self._requires_pull_invalidate()):
            x1, y1, x2, y2 = self._segment_xy()
            cx, cy = 0.5 * (x1 + x2), 0.5 * (y1 + y2)
            if about is not None:
                px, py = get_xy(about, bare=True)
            if about is None or (_near_pivot(px, py, cx, cy)):
                dθ_rad = _rad(dθ_deg)
                if model is LineModel.POINT_POINT:
                    _takein_xy_float(self.p1, *_rotate_xy(x1, y1, cx, cy, dθ_rad))
                    _takein_xy_float(self.p2, *_rotate_xy(x2, y2, cx, cy, dθ_rad))
                    _pose_rotation_add(self, dθ_deg)
                else:
                    if model is LineModel.POINT_ANGLE_LENGTH:
                        _takein_xy_float(self.p1, *_rotate_xy(x1, y1, cx, cy, dθ_rad))
                    # The ``angle`` write publishes the pose store (Shape._write_field).
                    self.angle = _bare_num(self.angle) + dθ_deg
                return self
        return self._rotate_by_batched(dθ_deg, about=about, force=force)

    @batch_update_self()
    def _rotate_by_batched(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Line':
        dθ_rad = _rad(dθ_deg)
        self._gate_tangent("rotate_by", force, about)
        if about is None and self.model is LineModel.TANGENT_POINT:
            # The default pivot of a tangent line is its circle's center.
            about = self._tangent_circle_xy()
        px, py = self._pivot_xy(about)

        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self["angle"], "rotate_by", force=force)
                cx, cy = get_xy(self.center, bare=True)
                about_center = (about is None) or (
                    _near_pivot(px, py, cx, cy)
                )
                if not about_center:
                    self.center._takein(_rotate_xy(cx, cy, px, py, dθ_rad))
                self.angle = _bare_num(self.angle) + dθ_deg
            case LineModel.POINT_POINT:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self.p2, "rotate_by", force=force, pivot=(px, py))
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                nx2, ny2 = _rotate_xy(x2, y2, px, py, dθ_rad)
                self.p1._takein((nx1, ny1))
                self.p2._takein((nx2, ny2))
            case LineModel.POINT_VEC:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self.vec, "rotate_by", force=force)
                x1, y1 = get_xy(self.p1, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                self.p1._takein((nx1, ny1))
                self.vec._takein(self.vec.rotate(dθ_deg))
            case LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT | LineModel.PERPENDICULAR_POINT:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self["angle"], "rotate_by", force=force)
                x1, y1 = get_xy(self.p1, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                self.p1._takein((nx1, ny1))
                self.angle = _bare_num(self.angle) + dθ_deg
            case LineModel.PARALLEL_DIST:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self["angle"], "rotate_by", force=force)
                x1, y1 = get_xy(self.p1, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                self.p1._takein((nx1, ny1))
                self.angle = _bare_num(self.angle) + dθ_deg
            case LineModel.TANGENT_ANGLE:
                # p1 is derived from circle + at_angle; turning shifts at_angle, which
                # moves the touch point (p1) around the circle: the default turn
                # orbits the circle's center (the touch point is pinned to it).
                _ensure_writable(self["at_angle"], "rotate_by", force=force)
                self.at_angle = _bare_num(self.at_angle) + dθ_deg
            case LineModel.TANGENT_POINT:
                # p2 (touch point) is derived from circle + p1; rotating p1 recomputes it.
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_rotate_xy(x1, y1, px, py, dθ_rad))
            case LineModel.POINT_DX_DY:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self["dx"], "rotate_by", force=force)
                _ensure_writable(self["dy"], "rotate_by", force=force)
                x1, y1 = get_xy(self.p1, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                self.p1._takein((nx1, ny1))
                dxv, dyv = _bare_num(self.dx), _bare_num(self.dy)
                rdx, rdy = _rotate_xy(dxv, dyv, 0.0, 0.0, dθ_rad)
                self.dx = rdx
                self.dy = rdy
            case _:
                raise ValueError(f"Unknown line model: {self.model}")

        _pose_rotation_add(self, dθ_deg)
        return self

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Line':
        """Rotate so the heading ``angle`` becomes value (degrees).

        Measured from the heading on every model — on the tangent model that is
        ``at_angle + 90``, not the position ``at_angle`` (it used to read back
        90° off).
        """
        current = self._rotation_value()     # Derivate ``angle``: the Defining segment (D3)
        return self.rotate_by(_finite_deg(value, "rotate_to angle") - current, about=about, force=force)

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Line':
        """Scale Defining geometry about a pivot by factor."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        px, py = self._pivot_xy(about)
        self._gate_tangent("scale_by", force, about)
        # The writes follow the model as the tangent gate leaves it (a forced
        # tangent runs on its free twin); a forced unlink below keeps them
        # (PARALLEL_DIST still scales ``dist``; Q3b decides that in its wave).
        model = self.model
        if force or self._requires_pull_invalidate():   # nothing linked: nothing refuses
            self._scale_gate(about, force, (px, py))     # every check before any write

        match model:
            case LineModel.CENTER_LENGTH_ANGLE:
                cx, cy = get_xy(self.center, bare=True)
                about_center = (about is None) or (
                    _near_pivot(px, py, cx, cy)
                )
                if not about_center:
                    self.center._takein(_scale_xy(cx, cy, px, py, factor))
                # Length is a magnitude. Signed factor would flip endpoints
                # while angle stayed put, so vec and angle would disagree.
                self.length = _bare_num(self.length) * factor
            case LineModel.POINT_POINT:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.p2._takein(_scale_xy(x2, y2, px, py, factor))
            case LineModel.POINT_VEC:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.vec.x = _bare_num(self.vec.x) * factor
                self.vec.y = _bare_num(self.vec.y) * factor
            case LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT | LineModel.PERPENDICULAR_POINT:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.length = _bare_num(self.length) * factor
            case LineModel.PARALLEL_DIST:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.dist = _bare_num(self.dist) * factor
                self.length = _bare_num(self.length) * factor
            case LineModel.TANGENT_ANGLE:
                # p1 stays pinned to the circle; only the tangent segment's length scales.
                self.length = _bare_num(self.length) * factor
            case LineModel.TANGENT_POINT:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
            case LineModel.POINT_DX_DY:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.dx = _bare_num(self.dx) * factor
                self.dy = _bare_num(self.dy) * factor
            case _:
                raise ValueError(f"Unknown line model: {self.model}")

        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        if pivot is None:
            pivot = self._pivot_xy(about)
        self._gate_tangent("scale_by", force, about)
        match self.model:
            case LineModel.CENTER_LENGTH_ANGLE:
                _ensure_writable(self.center, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["length"], "scale_by", force=force)
            case LineModel.POINT_POINT:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "scale_by", force=force, pivot=pivot)
            case LineModel.POINT_VEC:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.vec, "scale_by", force=force)
            case (LineModel.POINT_ANGLE_LENGTH | LineModel.PARALLEL_POINT
                  | LineModel.PERPENDICULAR_POINT | LineModel.PARALLEL_DIST):
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["length"], "scale_by", force=force)
            case LineModel.TANGENT_ANGLE:
                _ensure_writable(self["length"], "scale_by", force=force)
            case LineModel.TANGENT_POINT:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
            case LineModel.POINT_DX_DY:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["dx"], "scale_by", force=force)
                _ensure_writable(self["dy"], "scale_by", force=force)

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Line':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)

class CircleModel(Enum):
    CENTER_RADIUS = "center_radius"
    CENTER_PERIMETER = "center_perimeter"
    TWO_POINTS = "two_points"


class Circle(_HeadingFromGeometry, _DerivedRotationRoute, Shape):
    """
    Circle with multi-model constructors (Line/Rect-style) and an optional arc window.

    Models:
      - CENTER_RADIUS: center, radius are Defining.
      - CENTER_PERIMETER: center, perimeter_point are Defining; radius = distance(center, perimeter_point).
      - TWO_POINTS: p1, p2 are opposite ends of a diameter; center/radius are derived.

    Any model may add angle/spread (degrees) to draw an arc instead of a full circle.
    angle is the heading (0 = +x, counterclockwise); spread is the full opening, so the
    arc covers [angle - spread/2, angle + spread/2]. Defaults are angle=0, spread=360
    (a full turn). Either keyword may be given alone. spread must be in [0, 360];
    a linked value outside that range is clamped when drawn. use_center (plain,
    non-reactive, default True) draws a partial arc as a pie. False draws an open
    arc stroke and a chord-closed segment for the fill. Same heading and opening
    as collision.query_sector. Collision and the pointer follow that filled
    body; a full turn stays one circle primitive. Outline queries stay the
    full circumference.

    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        radius: Radius in design units (with ``center``).
        angle: Arc heading in degrees — the middle of the arc (0 = +x).
        spread: Arc opening in degrees (360 = full circle).
        use_center: Arcs: draw a pie slice (``True``) or just the curve.
        perimeter_point: With ``center``: a point on the edge (sets the radius).
        p1: One end of a diameter (with ``p2``).
        p2: The other end.
    """

    center = ContainerSlot(Point)
    radius = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    perimeter_point = ContainerSlot(Point, FieldType.Derivate)
    p1 = ContainerSlot(Point, FieldType.Derivate)
    p2 = ContainerSlot(Point, FieldType.Derivate)
    angle = ScalarSlot(label="Circle.angle")
    spread = ScalarSlot(magnitude=True, maximum=360.0)

    # angle/spread ride along on every model; they are not signature keys.
    _CTOR_EXTRA_KEYS = frozenset({"use_center", "angle", "spread"})

    # Placed by its rim (``perimeter_point=`` / ``p1=, p2=``) the heading is
    # derived: ``angle`` is the direction to ``p1`` (_DerivedRotationRoute).
    _HEADING_FIELD = 'angle'

    # Home model = CENTER_RADIUS (same as Circle() / Circle(radius=…)).
    _HOME_KEYS = frozenset({"center", "radius"})
    _HOME_OPTIONAL_KEYS = frozenset()
    _HOME_SIZE_KEYS = frozenset({"radius"})

    _CONSTRUCTOR_SIGNATURES = [
        ("center_radius",    {"center", "radius"}),
        ("center_perimeter", {"center", "perimeter_point"}),
        ("two_points",       {"p1", "p2"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        (cx, cy), unit = _default_pose()
        return {"center": (cx, cy), "radius": unit}

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Circle': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, radius: float, angle: float = 0.0, spread: float = 360.0, use_center: bool = True, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Circle': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, perimeter_point: GeneralPoint, angle: float = 0.0, spread: float = 360.0, use_center: bool = True, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Circle': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, p2: GeneralPoint, angle: float = 0.0, spread: float = 360.0, use_center: bool = True, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Circle': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        if "theta1" in kwargs or "theta2" in kwargs:
            raise TypeError(
                "Circle(theta1=, theta2=) was replaced by Circle(angle=, spread=). "
                "angle=(theta1 + theta2) / 2 is the heading; "
                "spread=theta2 - theta1 is the full opening in degrees."
            )
        from .box import apply_box_to_shape_kwargs
        apply_box_to_shape_kwargs(
            "Circle", kwargs, family="inscribe", size_keys=("radius",),
        )
        _reject_bad_spread(kwargs.get("spread", 360.0))
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs,
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )
        super().__init__(**base_params)

        # Cosmetic flag and arc window: allowed on every model, not signature keys.
        self._use_center = expect_bool(kwargs.get('use_center', True), "Circle use_center")
        arc_angle = kwargs.get('angle', 0.0)
        arc_spread = kwargs.get('spread', 360.0)

        match signature:
            case "center_radius":
                self.model = CircleModel.CENTER_RADIUS
                self._set_defining_parts('center', 'radius', 'angle', 'spread')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _init_scalar(self, 'radius', kwargs['radius'])
                    _init_scalar(self, 'angle', arc_angle)
                    _init_scalar(self, 'spread', arc_spread)

            case "center_perimeter":
                self.model = CircleModel.CENTER_PERIMETER
                self._set_defining_parts('center', 'perimeter_point', 'spread')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _init_composite(self.perimeter_point, kwargs['perimeter_point'])
                    _init_scalar(self, 'spread', arc_spread)

            case "two_points":
                self.model = CircleModel.TWO_POINTS
                self._set_defining_parts('p1', 'p2', 'spread')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    _init_composite(self.p2, kwargs['p2'])
                    _init_scalar(self, 'spread', arc_spread)

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        if self.model == CircleModel.CENTER_RADIUS:
            _pose_rotation_set(self, _bare_num(self.angle))
        else:
            # The heading is the direction to the rim point; ``angle=`` turns
            # the rim there about the center (the rule for a derived heading).
            _pose_rotation_set(self, self._rim_heading())
            if 'angle' in kwargs:
                self._turn_rim_at_construction(kwargs['angle'])

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark Defining parts; leave cold Derivates unregistered until access/link."""
        self._mark_defining_parts(
            *defining,
            catalog=('center', 'radius', 'perimeter_point', 'p1', 'p2', 'angle', 'spread'),
        )

    def _write_field(self, name: str, value) -> None:
        # The rules (finite angle, spread in 0..360) are on the slots.
        super()._write_field(name, value)
        # Outside a batch the shared write path publishes (Shape._publish_angle_input);
        # inside one (a flip mirrors ``angle``) this keeps the store in step.
        if name == "angle" and self._in_batch_update and self.model == CircleModel.CENTER_RADIUS:
            self._sync_rotation_to_angle()

    def _sync_rotation_to_angle(self) -> None:
        """``CENTER_RADIUS``: ``angle`` reads the Defining ``angle``; keep the pose
        value (and its property anchor) in step, so a formula that names
        ``circle.angle`` re-runs when a flip, an ``angle =`` write or an
        ``angle`` link turns the circle (G18 — only the verbs notified it)."""
        _pose_rotation_set(self, _bare_num(self.angle))

    def _heading_driven_parts(self) -> Tuple:
        # What rotate_by writes where ``angle`` is derived (placed by the rim).
        # The turn is about the center, which stays put (the pivot rule).
        match self.model:
            case CircleModel.TWO_POINTS:
                return (self.p1, self.p2)
            case CircleModel.CENTER_PERIMETER:
                return (self.perimeter_point,)
        return ()

    def _heading_pivot_inputs(self) -> Tuple:
        # Placed by its rim, the heading points from the center to the rim
        # point; the turn keeps the center. Linked with the heading, every
        # center move moved the heading and the link turned the rim back, so
        # the radius followed the center's path as far as reads had seen it.
        if self.model == CircleModel.CENTER_PERIMETER:
            return (self.center,)
        return ()

    def _heading_pivot_hint(self, pivot: bool) -> str:
        if pivot:
            return (". To drive both, place the circle with center= and radius=: "
                    "there angle is an input")
        return ""

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access via model ``_update_impl``."""
        self._pull_heading()
        with self._no_update():
            self._update_impl()

    def _takein_impl(self, other: 'Circle') -> None:
        """Copy only the defining attributes for the current model."""
        self._adopt_model_of(other)
        self._use_center = other._use_center
        match self.model:
            case CircleModel.CENTER_RADIUS:
                self.center._takein(other.center)
                self.radius = float(other.radius)
            case CircleModel.CENTER_PERIMETER:
                self.center._takein(other.center)
                self.perimeter_point._takein(other.perimeter_point)
            case CircleModel.TWO_POINTS:
                self.p1._takein(other.p1)
                self.p2._takein(other.p2)
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")
        if self.model == CircleModel.CENTER_RADIUS:
            self.angle = float(other.angle)
        _pose_rotation_set(self, other._arc_angle())      # the turn count too
        self.spread = _clamped_spread(other.spread)

    def _update_impl(self) -> None:
        """Update derived attributes based on the circle model."""
        match self.model:
            case CircleModel.CENTER_RADIUS:
                self._update_impl_center_radius()
            case CircleModel.CENTER_PERIMETER:
                self._update_impl_center_perimeter()
            case CircleModel.TWO_POINTS:
                self._update_impl_two_points()
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")

    # One reference rim point (Geometry contract): ``p1 ≡ perimeter_point``,
    # ``p2`` opposite. Placed by center + radius they sit on the heading
    # (``angle``) — the circle's frame, so they turn with ``rotate_by`` and
    # mirror on flips (they used to stay at world ±x). Placed by a rim point
    # (``perimeter_point=``) or a diameter (``p1=, p2=``) they are those points.

    def _rim_heading(self) -> float:
        """Direction center → ``p1`` in degrees, from Defining inputs only (the circle's frame)."""
        return self._arc_angle()

    def _arc_angle(self) -> float:
        """The heading (``angle`` / ``angle``) from Defining inputs only (D3-cold).

        ``CENTER_RADIUS``: the Defining ``angle``. Placed by its rim: the
        direction center → ``p1``, unwrapped to the accumulated pose turn so a
        full ``rotate_by(360)`` still reads ``+360`` (like Line). A zero-size
        circle keeps the accumulated value.
        """
        acc = float(getattr(self, '_rotation', 0.0) or 0.0)   # a slot, not __dict__
        match self.model:
            case CircleModel.CENTER_PERIMETER:
                cx, cy = get_xy(self.center, bare=True)
                px, py = get_xy(self.perimeter_point, bare=True)
            case CircleModel.TWO_POINTS:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                cx, cy, px, py = (x1 + x2) / 2.0, (y1 + y2) / 2.0, x1, y1
            case _:
                return _bare_num(self.angle)
        if px == cx and py == cy:
            return acc
        heading = math.degrees(math.atan2(py - cy, px - cx))
        return acc + ((heading - acc + 180.0) % 360.0 - 180.0)

    def _turn_rim_at_construction(self, value) -> None:
        """``Circle(perimeter_point=, angle=)`` / ``Circle(p1=, p2=, angle=)``: turn the rim to ``angle``.

        The drawn arc is where ``angle=`` always put it; the rim point moves
        onto the heading (it used to stay where it was, off the arc's frame).
        """
        if callable(value) and not isinstance(value, type):
            self._link_field('angle', value)          # the link drives the turn (rotate_to)
            return
        if isinstance(value, Attribute):
            value = value.value
        target = _finite_deg(value, "Circle angle")
        rim = (self.perimeter_point,) if self.model == CircleModel.CENTER_PERIMETER else (self.p1, self.p2)
        if any(node._link is not None for pt in rim for node in pt._iter_subtree()):
            raise TypeError(
                f"Circle({'perimeter_point' if len(rim) == 1 else 'p1=, p2'}=<link>, angle=): the heading "
                "of a circle placed by its rim is the direction to the rim point, so angle= would "
                "have to move a linked point. Drop angle= (the arc opens toward the rim point), "
                "or place it by center= + radius= + angle=."
            )
        self.rotate_by(target - self._arc_angle())
        _pose_rotation_set(self, target)

    def _write_live_rim(self, cx: float, cy: float, rx: float, ry: float) -> None:
        """``p1`` / ``perimeter_point`` at ``(rx, ry)``, ``p2`` opposite — live Derivates only."""
        for name, pt in (('perimeter_point', (rx, ry)), ('p1', (rx, ry)),
                         ('p2', (2.0 * cx - rx, 2.0 * cy - ry))):
            self._takein_live_derivate(name, pt)

    @batch_update_attrs('perimeter_point', 'p1', 'p2')
    def _update_impl_center_radius(self) -> None:
        """center/radius define the circle; the rim points sit on the heading."""
        self._sync_rotation_to_angle()             # an ``angle`` link lands here
        cx, cy = get_xy(self.center, bare=True)
        r = _bare_num(self.radius)
        a = _rad(_bare_num(self.angle))
        self._write_live_rim(cx, cy, cx + r * math.cos(a), cy + r * math.sin(a))

    @batch_update_attrs('radius', 'p1', 'p2', 'angle')
    def _update_impl_center_perimeter(self) -> None:
        """center + perimeter_point define the circle; radius is the distance, angle the direction."""
        cx, cy = get_xy(self.center, bare=True)
        px, py = get_xy(self.perimeter_point, bare=True)
        self._takein_live_derivate('radius', math.hypot(px - cx, py - cy))
        self._takein_live_derivate('angle', self._arc_angle())
        self._write_live_rim(cx, cy, px, py)

    @batch_update_attrs('center', 'radius', 'perimeter_point', 'angle')
    def _update_impl_two_points(self) -> None:
        """p1/p2 are opposite ends of a diameter; perimeter_point is p1; angle points at p1."""
        x1, y1 = get_xy(self.p1, bare=True)
        x2, y2 = get_xy(self.p2, bare=True)
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        self._takein_live_derivate('center', (cx, cy))
        self._takein_live_derivate('radius', math.hypot(x2 - x1, y2 - y1) / 2.0)
        self._takein_live_derivate('perimeter_point', (x1, y1))
        self._takein_live_derivate('angle', self._arc_angle())

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, r, angle, spread, pie)`` from Defining inputs (R7).

        ``radius`` is a Derivate on CENTER_PERIMETER / TWO_POINTS: the generic
        extra read it from ``__dict__`` (stale while cold), so a perimeter-point
        or endpoint write kept a stale collision hull. Built from
        ``_radius_value()`` so the key covers every input the prims read.
        """
        try:
            rot = float(self._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(self._scale)
        except Exception:
            scale = 1.0
        return (
            rot, scale, float(self._radius_value()),
            float(self._arc_angle()), float(_bare_num(self.spread)),
            1.0 if self.__dict__.get("_use_center") else 0.0,
        )

    def _radius_value(self) -> float:
        """Radius from Defining inputs — ``radius`` is a Derivate on CENTER_PERIMETER
        and TWO_POINTS; reading it would wake it (D3 in Testing Design)."""
        match self.model:
            case CircleModel.CENTER_RADIUS:
                return _bare_num(self.radius)
            case CircleModel.CENTER_PERIMETER:
                cx, cy = get_xy(self.center, bare=True)
                px, py = get_xy(self.perimeter_point, bare=True)
                return math.hypot(px - cx, py - cy)
            case CircleModel.TWO_POINTS:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                return 0.5 * math.hypot(x2 - x1, y2 - y1)
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")

    def _center_xy(self) -> Tuple[float, float]:
        """Pose center from Defining inputs — do not wake Derivate ``center`` on TWO_POINTS."""
        match self.model:
            case CircleModel.CENTER_RADIUS | CircleModel.CENTER_PERIMETER:
                return get_xy(self.center, bare=True)
            case CircleModel.TWO_POINTS:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                return (0.5 * (x1 + x2), 0.5 * (y1 + y2))
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")

    def _rotation_value(self) -> float:
        """The heading from Defining inputs only (never wakes a Derivate ``angle``)."""
        return self._arc_angle()

    @classmethod
    def from_square(cls, square: 'Square', *, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, List[str]]] = None) -> 'Circle':
        """Create a circle inscribed in a square (one-shot convenience, not a live link)."""
        return cls(
            center=get_xy(square.center, bare=True),
            radius=_bare_num(square.length) / 2,
            layer=layer, group=group
        )

    @classmethod
    def from_rect(cls, rect: 'Rect', *, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, List[str]]] = None) -> 'Circle':
        """Create the largest circle that fits inside a rectangle (one-shot convenience, not a live link)."""
        return cls(
            center=get_xy(rect.center, bare=True),
            radius=min(_bare_num(rect.width), _bare_num(rect.height)) / 2,
            layer=layer, group=group
        )

    @classmethod
    def from_points(cls, center: GeneralPoint, perimeter: GeneralPoint, *, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, List[str]]] = None) -> 'Circle':
        """Create a circle from a center point and a point on the perimeter (CENTER_PERIMETER).

        Same rule as the constructor: a point is copied, a function links.
        ``Circle.from_points(ship.center, tip)`` is where they are now;
        ``Circle.from_points(lambda: ship.center, lambda: tip)`` follows them.
        (It used to link a plain point: the opposite rule, graphics review SB9.)
        """
        return cls(center=center, perimeter_point=perimeter, layer=layer, group=group)

    @classmethod
    def from_corners(cls, *, point: GeneralPoint, pos: Pos, radius: float, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, List[str]]] = None) -> 'Circle':
        """
        Create a circle from a boundary point and radius (one-shot convenience, not a live link).
        Args:
            point: The reference point
            radius: The circle's radius
            pos: Position type from Pos enum (TOP_LEFT, CENTER, etc.)
            layer: Optional layer name
        Returns: A new Circle with the calculated center
        """
        from .validate import coerce_enum
        # A copy: a function radius has nothing to link (SB10 leaked the formula
        # checker's "could not be parsed").
        radius = fixed_magnitude(radius, "from_corners radius")
        pos = coerce_enum(pos, Pos, what="from_corners pos")
        px, py = get_xy(point, bare=True)
        if pos == Pos.TOP_LEFT:
            center = (px + radius, py - radius)
        elif pos == Pos.TOP_RIGHT:
            center = (px - radius, py - radius)
        elif pos == Pos.BOTTOM_LEFT:
            center = (px + radius, py + radius)
        elif pos == Pos.BOTTOM_RIGHT:
            center = (px - radius, py + radius)
        elif pos == Pos.TOP_CENTER:
            center = (px, py - radius)
        elif pos == Pos.BOTTOM_CENTER:
            center = (px, py + radius)
        elif pos == Pos.LEFT_CENTER:
            center = (px + radius, py)
        elif pos == Pos.RIGHT_CENTER:
            center = (px - radius, py)
        elif pos == Pos.CENTER:
            center = (px, py)
        else:
            raise ValueError(f"Invalid position type: {pos}")

        return cls(
            center=center,
            radius=radius,
            layer=layer, group=group
        )

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw circle/arc in a local CTM so Gradient/Texture shaders rotate with the shape."""
        cx, cy = self._center_xy()
        r = abs(self._radius_value())
        ang = self._arc_angle()
        spread = _clamped_spread(_bare_num(self.spread))
        rot = float(self._rotation)

        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if rot:
            skia_canvas.rotate(rot)

        skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint

        if _is_full_turn(spread):
            if skia_fill_paint:
                skia_canvas.drawCircle(0.0, 0.0, r, skia_fill_paint)
            if skia_line_paint:
                skia_canvas.drawCircle(0.0, 0.0, r, skia_line_paint)
        else:
            # angle/spread are world-oriented; express the arc in the rotated local frame.
            start_local = ang - spread * 0.5 - rot
            rect = skia.Rect.MakeLTRB(-r, -r, r, r)
            if skia_fill_paint:
                skia_canvas.drawArc(rect, start_local, spread, self._use_center, skia_fill_paint)
            if skia_line_paint:
                skia_canvas.drawArc(rect, start_local, spread, self._use_center, skia_line_paint)

        skia_canvas.restore()

    @property
    def is_collapsed(self) -> bool:
        """True when radius is ``0``."""
        return float(self._scale) == 0.0 or abs(self._radius_value()) == 0.0

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit-test the painted fill: full disk, pie, or chord segment."""
        cx, cy = self._center_xy()              # Defining only (SC6)
        return _point_in_filled_arc(
            x, y, cx, cy, abs(self._radius_value()),
            self._arc_angle(), _bare_num(self.spread),
            bool(self._use_center),
        )

    def point_at_angle(self, angle: float) -> Point:
        """
        Returns a point on the circle's circumference at the specified angle.
        Args:
            angle: Angle in degrees (0 is right, positive is counterclockwise)
        Returns: Point object on the circle's circumference
        """
        # Create vector from angle with length = radius
        vec = vec_from_angle(angle, abs(float(self.radius)))
        
        # Add vector to center point to get point on circumference
        return self.center + vec

    def tangent_line_from_angle(self, *, at_angle: float, size: float, layer: Any = _USE_LAYER_DEFAULT, group: Optional[Union[str, List[str]]] = None) -> 'Line':
        """
        Creates a line tangent to the circle at the given position around it (reactive:
        see Line's TANGENT_ANGLE model — the tangent tracks this circle if it later moves).
        Args:
            at_angle: Position around the circle in degrees where the tangent touches
                (the line's heading is then ``at_angle + 90``)
            size: Length of the tangent line
        Returns: Line object tangent to the circle
        """
        return Line(circle=self, at_angle=at_angle, length=size, layer=layer, group=group)

    def tangent_lines_from(self, point: GeneralPoint, *, layer: Any = _USE_LAYER_DEFAULT,
                            group: Optional[Union[str, List[str]]] = None) -> Tuple['Line', 'Line']:
        """
        Creates the two lines tangent to the circle from an external point (reactive: see
        Line's TANGENT_POINT model). If point is inside the circle, the touch point
        computation degenerates gracefully to point==touch point (zero-length lines).
        """
        line1 = Line(circle=self, from_point=point, side='left', layer=layer, group=group)
        try:
            line2 = Line(circle=self, from_point=point, side='right', layer=layer, group=group)
        except BaseException:
            line1.destroy()   # all or nothing: a rejected call leaves no line (A10)
            raise
        return (line1, line2)

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        match self.model:
            case CircleModel.CENTER_RADIUS:
                return (self.center,)
            case CircleModel.CENTER_PERIMETER:
                return (self.center, self.perimeter_point)
            case CircleModel.TWO_POINTS:
                return (self.p1, self.p2)
            case _:
                return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        # center / endpoints / arc heading + PropertyAnchor rotation (_pose_rotation_add).
        rot = self["angle"]
        match self.model:
            case CircleModel.CENTER_RADIUS:
                return (self.center, self["angle"], rot)
            case CircleModel.CENTER_PERIMETER:
                return (self.center, self.perimeter_point, rot)
            case CircleModel.TWO_POINTS:
                return (self.p1, self.p2, rot)
            case _:
                return (rot,)

    def _clone_geometry(self, **kwargs) -> 'Circle':
        # Same model: a rim point / diameter placed by the author stays that point.
        arc = dict(angle=self._arc_angle(), spread=_clamped_spread(_bare_num(self.spread)),
                   use_center=self._use_center)
        match self.model:
            case CircleModel.CENTER_PERIMETER:
                place = dict(center=get_xy(self.center, bare=True),
                             perimeter_point=get_xy(self.perimeter_point, bare=True))
            case CircleModel.TWO_POINTS:
                place = dict(p1=get_xy(self.p1, bare=True), p2=get_xy(self.p2, bare=True))
            case _:
                place = dict(center=get_xy(self.center, bare=True), radius=_bare_num(self.radius))
        return type(self)(**place, **arc, **kwargs)

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Circle':
        """Translate Defining position part(s) only (model-aware)."""
        if _pose_fast_ok(self, force=force):
            match self.model:
                case CircleModel.CENTER_RADIUS:
                    _translate_point_float(self.center, dx, dy)
                    return self
                case CircleModel.CENTER_PERIMETER:
                    _translate_points_float((self.center, self.perimeter_point), dx, dy)
                    return self
                case CircleModel.TWO_POINTS:
                    _translate_points_float((self.p1, self.p2), dx, dy)
                    return self
                case _:
                    raise ValueError(f"Unknown circle model: {self.model}")
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> 'Circle':
        match self.model:
            case CircleModel.CENTER_RADIUS:
                _ensure_writable(self.center, "move_by", force=force)
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                if dx is not None:
                    cx = cx + float(dx)
                if dy is not None:
                    cy = cy + float(dy)
                self.center._takein((cx, cy))
            case CircleModel.CENTER_PERIMETER:
                _ensure_writable(self.center, "move_by", force=force)
                _ensure_writable(self.perimeter_point, "move_by", force=force)
                if dx is not None:
                    self.center.x += dx
                    self.perimeter_point.x += dx
                if dy is not None:
                    self.center.y += dy
                    self.perimeter_point.y += dy
            case CircleModel.TWO_POINTS:
                _ensure_writable(self.p1, "move_by", force=force)
                _ensure_writable(self.p2, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                    self.p2.x += dx
                if dy is not None:
                    self.p1.y += dy
                    self.p2.y += dy
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Circle':
        """Move the circle's center to absolute x and/or y coordinates."""
        if self.model == CircleModel.CENTER_RADIUS:
            if _pose_fast_ok(self, force=force):
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                nx = cx if x is None else float(x)
                ny = cy if y is None else float(y)
                if nx != cx:
                    _takein_xy_float(self.center, x=nx)
                if ny != cy:
                    _takein_xy_float(self.center, y=ny)
                return self
            return self._move_to_center_radius(x, y, force=force)
        cx, cy = self._center_xy()
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
            return self
        return self._move_by(dx, dy, force=force)

    @batch_update_self()
    def _move_to_center_radius(self, x: float, y: float, *, force: bool = False) -> 'Circle':
        _ensure_writable(self.center, "move_to", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if nx != cx or ny != cy:
            self.center._takein((nx, ny))
        return self

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Circle':
        """Rotate so the arc heading (``angle``) becomes value (degrees)."""
        current = self._arc_angle()
        return self.rotate_by(_finite_deg(value, "rotate_to angle") - current, about=about, force=force)

    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Circle':
        """Rotate Defining geometry about a pivot by angle degrees; the arc heading turns with it."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        # About-center CENTER_RADIUS: pose is rotation-invariant; only spin the heading.
        if self.model == CircleModel.CENTER_RADIUS and not force:
            px, py = self._pivot_xy(about)
            cx, cy = get_xy(self.center, bare=True)
            about_center = (about is None) or (
                _near_pivot(px, py, cx, cy)
            )
            if about_center and not self._requires_pull_invalidate():
                self.__dict__['angle'] = float(self.angle) + dθ_deg
                _pose_rotation_add(self, dθ_deg)
                return self
        return self._rotate_by_batched(dθ_deg, about=about, force=force)

    @batch_update_self()
    def _rotate_by_batched(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Circle':
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)

        match self.model:
            case CircleModel.CENTER_RADIUS:
                _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self["angle"], "rotate_by", force=force)   # before any write (SB2b)
                cx, cy = get_xy(self.center, bare=True)
                self.center._takein(_rotate_xy(cx, cy, px, py, dθ_rad))
            case CircleModel.CENTER_PERIMETER:
                _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self.perimeter_point, "rotate_by", force=force, pivot=(px, py))
                cx, cy = get_xy(self.center, bare=True)
                ppx, ppy = get_xy(self.perimeter_point, bare=True)
                self.center._takein(_rotate_xy(cx, cy, px, py, dθ_rad))
                self.perimeter_point._takein(_rotate_xy(ppx, ppy, px, py, dθ_rad))
            case CircleModel.TWO_POINTS:
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=(px, py))
                _ensure_writable(self.p2, "rotate_by", force=force, pivot=(px, py))
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_rotate_xy(x1, y1, px, py, dθ_rad))
                self.p2._takein(_rotate_xy(x2, y2, px, py, dθ_rad))
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")

        if self.model == CircleModel.CENTER_RADIUS:
            _ensure_writable(self["angle"], "rotate_by", force=force)
            self.angle = _bare_num(self.angle) + dθ_deg      # syncs the pose store (_write_field)
        else:
            # Placed by its rim, ``angle`` is the direction to p1: the points
            # turned it; the pose value keeps the turn count.
            _pose_rotation_add(self, dθ_deg)
        return self

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Circle':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Circle':
        """Scale Defining geometry about a pivot by factor. angle/spread are unaffected."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        px, py = self._pivot_xy(about)
        if force or self._requires_pull_invalidate():   # nothing linked: nothing refuses
            self._scale_gate(about, force, (px, py))     # every check before any write

        match self.model:
            case CircleModel.CENTER_RADIUS:
                cx, cy = get_xy(self.center, bare=True)
                self.center._takein(_scale_xy(cx, cy, px, py, factor))
                self.radius = _bare_num(self.radius) * factor
            case CircleModel.CENTER_PERIMETER:
                cx, cy = get_xy(self.center, bare=True)
                ppx, ppy = get_xy(self.perimeter_point, bare=True)
                ncx, ncy = _scale_xy(cx, cy, px, py, factor)
                ang = math.atan2(ppy - cy, ppx - cx)
                r = math.hypot(ppx - cx, ppy - cy) * factor
                self.center._takein((ncx, ncy))
                self.perimeter_point._takein((ncx + r * math.cos(ang), ncy + r * math.sin(ang)))
            case CircleModel.TWO_POINTS:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.p2._takein(_scale_xy(x2, y2, px, py, factor))
            case _:
                raise ValueError(f"Unknown circle model: {self.model}")

        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        if pivot is None:
            pivot = self._pivot_xy(about)
        match self.model:
            case CircleModel.CENTER_RADIUS:
                _ensure_writable(self.center, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["radius"], "scale_by", force=force)
            case CircleModel.CENTER_PERIMETER:
                _ensure_writable(self.center, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.perimeter_point, "scale_by", force=force, pivot=pivot)
            case CircleModel.TWO_POINTS:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "scale_by", force=force, pivot=pivot)


class EllipseModel(Enum):
    CENTER_WH = "center_wh"
    FOCAL_POINTS = "focal_points"
    FROM_RECT = "from_rect"


class Ellipse(_DerivedRotationRoute, Shape):
    """
    Ellipse with multi-model constructors (Rect/Circle-style).

    Models:
      - CENTER_WH: center, width, height, angle are Defining. Derivate: fp1, fp2 (focus
        points, placed along whichever of abs(width)/abs(height) is larger), c (focal
        distance), major_axis (= max(abs(width), abs(height))). A negative stored axis
        (scale_by(-1)) is the same ellipse.
      - FOCAL_POINTS: fp1, fp2, major_axis are Defining. Derivate: center (midpoint), angle
        (direction fp1->fp2), width/height (major_axis sets the extent along fp1->fp2), c.
        Raises ValueError if major_axis < distance(fp1, fp2) (equal is a collapsed ellipse) when every input is a
        concrete number. A linked input skips that check (a formula cannot be
        snapshotted). A later value that shrinks major_axis below the focal distance
        collapses onto the segment joining the foci (a = c, b = 0).
      - FROM_RECT: center/width/height/angle are each formula-linked to a foreign Rect's
        corresponding fields (width/height are max(0, host - 2*padding) -- padding is a
        fixed, non-reactive value captured at construction). Overflow is a collapsed
        ellipse. Reuses CENTER_WH's derived-attribute math.

    Optional angle defaults to 0 when omitted (CENTER_WH only; FOCAL_POINTS/FROM_RECT derive it).

    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        width: Full width (with ``center``).
        height: Full height.
        angle: Heading in degrees (counter-clockwise). Setting it keeps the point
            the shape was placed by; ``rotate_to`` turns it about its center.
        fp1: First focus (with ``fp2`` + ``major_axis``).
        fp2: Second focus.
        major_axis: Length of the long axis.
        from_rect: A Rect to inscribe in (follows it).
        padding: With ``from_rect``: margin inside the rect.
    """

    center = ContainerSlot(Point)
    width = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    height = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    angle = ScalarSlot()
    fp1 = ContainerSlot(Point, FieldType.Derivate)
    fp2 = ContainerSlot(Point, FieldType.Derivate)
    c = ScalarSlot()
    major_axis = ScalarSlot(magnitude=True, hint=HINT_EXTENT)

    # Home model = CENTER_WH (same as Ellipse()).
    _HOME_KEYS = frozenset({"center", "width", "height"})
    _HOME_OPTIONAL_KEYS = frozenset({"angle"})
    _HOME_SIZE_KEYS = frozenset({"width", "height", "angle"})

    _CONSTRUCTOR_SIGNATURES = [
        ("center_wh",           {"center", "width", "height"}),
        ("center_wh_angle",     {"center", "width", "height", "angle"}),
        ("focal_points",        {"fp1", "fp2", "major_axis"}),
        ("from_rect",           {"from_rect"}),
        ("from_rect_padding",   {"from_rect", "padding"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        (cx, cy), unit = _default_pose()
        return {
            "center": (cx, cy),
            "width": 2.0 * unit,
            "height": 1.25 * unit,
        }

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Ellipse': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, width: float, height: float, angle: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Ellipse': ...

    @overload
    def __new__(cls, *, fp1: GeneralPoint, fp2: GeneralPoint, major_axis: float, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Ellipse': ...

    @overload
    def __new__(cls, *, from_rect: 'Rect', padding: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Ellipse': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        from .box import apply_box_to_shape_kwargs
        apply_box_to_shape_kwargs("Ellipse", kwargs, family="fill")
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs,
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )
        super().__init__(**base_params)

        self._ref = None

        match signature:
            case "center_wh" | "center_wh_angle":
                self.model = EllipseModel.CENTER_WH
                self._set_defining_parts('center', 'width', 'height', 'angle')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _init_scalar(self, 'width', kwargs['width'])
                    _init_scalar(self, 'height', kwargs['height'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "focal_points":
                fp1, fp2, major_axis = kwargs['fp1'], kwargs['fp2'], kwargs['major_axis']
                # Numbers rule: a value the author writes raises; a formula
                # collapses later (a < c in _update_impl_focal_points). Check
                # only when every input is a concrete number — a link cannot
                # be snapshotted, and get_xy / float on it is a raw TypeError.
                xy1 = _concrete_xy(fp1)
                xy2 = _concrete_xy(fp2)
                major = _concrete_float(major_axis)
                if xy1 is not None and xy2 is not None and major is not None:
                    if not math.isfinite(major):
                        raise ValueError(f"major_axis ({major}) must be finite")
                    dist = math.hypot(xy2[0] - xy1[0], xy2[1] - xy1[1])
                    # Equal is a legal collapsed ellipse (the segment fp1–fp2, or a
                    # point at zero size), like a zero-width Rect.
                    if major < dist:
                        raise ValueError(
                            f"major_axis ({major}) must be at least "
                            f"distance(fp1, fp2) ({dist}) to form an ellipse"
                        )
                self.model = EllipseModel.FOCAL_POINTS
                self._set_defining_parts('fp1', 'fp2', 'major_axis')
                with self._batch_update():
                    _init_composite(self.fp1, fp1)
                    _init_composite(self.fp2, fp2)
                    _init_scalar(self, 'major_axis', major_axis)

            case "from_rect" | "from_rect_padding":
                rect = kwargs['from_rect']
                self._ref = _live_ref(rect, type(self).__name__, "Rect", "from_rect")
                padding = kwargs.get('padding', 0.0)
                if callable(padding) and not isinstance(padding, type):
                    raise TypeError(
                        "Ellipse padding is fixed. For a live inset, link the size: "
                        "Ellipse(center=lambda: r.center, "
                        "width=lambda: r.width - 2 * p, "
                        "height=lambda: r.height - 2 * p, "
                        "angle=lambda: r.angle)."
                    )
                from .validate import number
                padding = number(padding, "Ellipse padding")
                self.model = EllipseModel.FROM_RECT
                self._set_defining_parts('center', 'width', 'height', 'angle')
                with self._batch_update():
                    self.center @= (lambda: rect.center)
                    self["width"] @= (lambda: max(0.0, rect.width - 2.0 * padding))
                    self["height"] @= (lambda: max(0.0, rect.height - 2.0 * padding))
                    self["angle"] @= (lambda: rect.angle)

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        if self.model == EllipseModel.FOCAL_POINTS:
            # Angle is Derivate — compute from Defining foci (A4 / cold-Derivate).
            x1, y1 = get_xy(self.fp1, bare=True)
            x2, y2 = get_xy(self.fp2, bare=True)
            _pose_rotation_set(self, _deg(math.atan2(y2 - y1, x2 - x1)))
        else:
            _pose_rotation_set(self, _bare_num(self.angle))

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark Defining parts; leave cold Derivates unregistered until access/link."""
        self._mark_defining_parts(
            *defining,
            catalog=('center', 'width', 'height', 'angle', 'fp1', 'fp2', 'c', 'major_axis'),
        )

    def _heading_driven_parts(self) -> Tuple:
        # What rotate_by writes where ``angle`` is derived (placed by its foci).
        if self.model == EllipseModel.FOCAL_POINTS:
            return (self.fp1, self.fp2)
        return ()

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access via model ``_update_impl``."""
        self._pull_heading()
        with self._no_update():
            self._update_impl()

    @staticmethod
    def _free_model(model):
        # A FROM_RECT copy is a free CENTER_WH ellipse (it has no Rect to follow).
        return EllipseModel.CENTER_WH if model == EllipseModel.FROM_RECT else model

    def _defining_names_for(self, model) -> Optional[Tuple[str, ...]]:
        if model == EllipseModel.FOCAL_POINTS:
            return ('fp1', 'fp2', 'major_axis')
        return ('center', 'width', 'height', 'angle')

    def _takein_impl(self, other: 'Ellipse') -> None:
        """Copy only the defining attributes for the current model."""
        self._adopt_model_of(other)
        self._ref = getattr(other, '_ref', None) if self.model is other.model else None
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                self.center._takein(other.center)
                _init_scalar(self, 'width', other.width)
                _init_scalar(self, 'height', other.height)
                _init_scalar(self, 'angle', other.angle)
            case EllipseModel.FOCAL_POINTS:
                self.fp1._takein(other.fp1)
                self.fp2._takein(other.fp2)
                _init_scalar(self, 'major_axis', other.major_axis)
            case _:
                raise ValueError(f"Unknown ellipse model: {self.model}")

    def _update_impl(self) -> None:
        """Update derived attributes based on the ellipse model."""
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                self._update_impl_center_wh()
            case EllipseModel.FOCAL_POINTS:
                self._update_impl_focal_points()
            case _:
                raise ValueError(f"Unknown ellipse model: {self.model}")

    @batch_update_attrs('fp1', 'fp2', 'c', 'major_axis')
    def _update_impl_center_wh(self) -> None:
        """center/width/height/angle define the ellipse; foci lie along the longer axis."""
        cx, cy = get_xy(self.center, bare=True)
        # Signed Defining axes (scale_by(-1)) are the same ellipse.
        w = abs(_bare_num(self.width))
        h = abs(_bare_num(self.height))
        ang = _bare_num(self.angle)
        a = max(w, h) / 2.0
        b = min(w, h) / 2.0
        c = math.sqrt(max(a * a - b * b, 0.0))
        # Foci sit along whichever local axis is longer (width -> local +x / angle;
        # height -> local +y / angle + pi/2). A flip turns the heading to
        # 180 - angle / -angle, which reverses the +pi/2 side: after an odd
        # number of flips the height axis is angle - pi/2, so each focus lands
        # on its own mirror (GX1 in Testing Design: tall foci swapped names).
        if w >= h:
            foci_angle = ang
        elif self._flip_x != self._flip_y:
            foci_angle = ang - 90.0
        else:
            foci_angle = ang + 90.0
        fx = math.cos(_rad(foci_angle)) * c
        fy = math.sin(_rad(foci_angle)) * c

        self.fp1._takein((cx - fx, cy - fy))
        self.fp2._takein((cx + fx, cy + fy))
        self.c = c
        self.major_axis = 2.0 * a

    def _foci_heading(self) -> float:
        """Direction ``fp1 → fp2`` (Defining only), keeping the pose store's full turns."""
        x1, y1 = get_xy(self.fp1, bare=True)
        x2, y2 = get_xy(self.fp2, bare=True)
        acc = float(getattr(self, '_rotation', 0.0) or 0.0)
        if not (x2 - x1 or y2 - y1):
            return acc
        return _unwrap_deg(_deg(math.atan2(y2 - y1, x2 - x1)), acc)

    @batch_update_attrs('center', 'angle', 'width', 'height', 'c')
    def _update_impl_focal_points(self) -> None:
        """fp1, fp2, major_axis define the ellipse; center/angle/width/height/c are derived."""
        x1, y1 = get_xy(self.fp1, bare=True)
        x2, y2 = get_xy(self.fp2, bare=True)
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        ang = self._foci_heading()
        c = math.hypot(x2 - x1, y2 - y1) / 2.0
        a = _bare_num(self.major_axis) / 2.0
        # A later write can shrink major below the foci. Collapse onto the
        # segment between them (the a == c ellipse) instead of a shorter oval
        # with the foci sticking out. Construction still rejects that case.
        if a < c:
            a = c
        b = math.sqrt(max(a * a - c * c, 0.0))

        self.center._takein((cx, cy))
        self.angle = ang
        self.width = 2.0 * a
        self.height = 2.0 * b
        self.c = c

    def _center_xy(self) -> Tuple[float, float]:
        """Pose center from Defining inputs — FOCAL_POINTS must not wake Derivate ``center``."""
        if self.model == EllipseModel.FOCAL_POINTS:
            x1, y1 = get_xy(self.fp1, bare=True)
            x2, y2 = get_xy(self.fp2, bare=True)
            return (0.5 * (x1 + x2), 0.5 * (y1 + y2))
        return get_xy(self.center, bare=True)

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, ang, w, h)`` from ``_oriented_frame`` (R7).

        FOCAL_POINTS: ``width`` / ``height`` / ``angle`` are Derivates; the
        generic extra read them stale from ``__dict__`` while cold, so
        ``flip_x`` / a ``major_axis`` write kept a stale collision hull.
        """
        try:
            rot = float(self._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(self._scale)
        except Exception:
            scale = 1.0
        _cx, _cy, w, h, ang = self._oriented_frame()
        return (rot, scale, float(ang), float(w), float(h))

    def _oriented_frame(self) -> Tuple[float, float, float, float, float]:
        """``(cx, cy, w, h, ang)`` with non-negative extents.

        Same numbers draw and ``Track(ellipse)`` use. Defining ``width`` /
        ``height`` may stay signed after ``scale_by(-1)``.
        """
        cx, cy = self._center_xy()
        if self.model == EllipseModel.FOCAL_POINTS:
            # width / height / angle are Derivates here: compute them from
            # the foci and major_axis (same math as _update_impl_focal_points).
            x1, y1 = get_xy(self.fp1, bare=True)
            x2, y2 = get_xy(self.fp2, bare=True)
            c = math.hypot(x2 - x1, y2 - y1) / 2.0
            a = max(abs(_bare_num(self.major_axis)) / 2.0, c)
            b = math.sqrt(max(a * a - c * c, 0.0))
            return (cx, cy, 2.0 * a, 2.0 * b, self._foci_heading())
        return (
            cx, cy,
            abs(_bare_num(self.width)),
            abs(_bare_num(self.height)),
            _bare_num(self.angle),
        )

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw the ellipse from world-space center/width/height/angle (geometric-first).

        ``scale_by`` already writes ``width`` / ``height`` (and ``_scale``). Do not
        also CTM-scale here — that would draw at factor² while collision uses
        the geometric size once.
        """
        skia_canvas.save()

        cx, cy, w, h, ang = self._oriented_frame()
        skia_canvas.translate(cx, cy)

        if ang:
            skia_canvas.rotate(ang)

        rect = skia.Rect.MakeLTRB(-w / 2.0, -h / 2.0, w / 2.0, h / 2.0)

        skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        if skia_fill_paint:
            skia_canvas.drawOval(rect, skia_fill_paint)

        skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if skia_line_paint:
            skia_canvas.drawOval(rect, skia_line_paint)

        skia_canvas.restore()

    @property
    def is_collapsed(self) -> bool:
        """True when either axis extent is ``0``."""
        if float(self._scale) == 0.0:
            return True
        _cx, _cy, w, h, _ang = self._oriented_frame()   # Defining only (SC6)
        return abs(w) == 0.0 or abs(h) == 0.0

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit-test via inverse-rotate into local ellipse frame."""
        cx, cy, w, h, ang = self._oriented_frame()   # Defining only (D3)
        if w == 0.0 or h == 0.0:
            return False
        dx = x - cx
        dy = y - cy
        if ang:
            cos_a = math.cos(_rad(-ang))
            sin_a = math.sin(_rad(-ang))
            lx = dx * cos_a - dy * sin_a
            ly = dx * sin_a + dy * cos_a
        else:
            lx, ly = dx, dy
        hw, hh = w / 2.0, h / 2.0
        return _sq(lx / hw) + _sq(ly / hh) <= 1.0

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                return (self.center,)
            case EllipseModel.FOCAL_POINTS:
                return (self.fp1, self.fp2)
            case _:
                return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple[Container, ...]:
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                return (self["angle"],)
            case EllipseModel.FOCAL_POINTS:
                return (self.fp1, self.fp2)
            case _:
                return ()

    def _clone_geometry(self, **kwargs) -> 'Ellipse':
        # A free model is kept (SB6: FOCAL_POINTS cloned as CENTER_WH);
        # FROM_RECT takes its free twin. One path with ``<<``.
        cx, cy, w, h, ang = self._oriented_frame()
        copy = type(self)(center=(cx, cy), width=abs(w), height=abs(h), angle=ang, **kwargs)
        copy._takein(self)
        return copy

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Ellipse':
        """Translate Defining position part(s) only (model-aware)."""
        if _pose_fast_ok(self, force=force):
            match self.model:
                case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                    _translate_point_float(self.center, dx, dy)
                    return self
                case EllipseModel.FOCAL_POINTS:
                    _translate_points_float((self.fp1, self.fp2), dx, dy)
                    return self
                case _:
                    raise ValueError(f"Unknown ellipse model: {self.model}")
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> 'Ellipse':
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                _ensure_writable(self.center, "move_by", force=force)
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                if dx is not None:
                    cx = cx + float(dx)
                if dy is not None:
                    cy = cy + float(dy)
                self.center._takein((cx, cy))
            case EllipseModel.FOCAL_POINTS:
                _ensure_writable(self.fp1, "move_by", force=force)
                _ensure_writable(self.fp2, "move_by", force=force)
                if dx is not None:
                    self.fp1.x += dx
                    self.fp2.x += dx
                if dy is not None:
                    self.fp1.y += dy
                    self.fp2.y += dy
            case _:
                raise ValueError(f"Unknown ellipse model: {self.model}")
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Ellipse':
        """Move the ellipse's center to absolute x and/or y coordinates."""
        if self.model in (EllipseModel.CENTER_WH, EllipseModel.FROM_RECT):
            if _pose_fast_ok(self, force=force):
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                nx = cx if x is None else float(x)
                ny = cy if y is None else float(y)
                if nx != cx:
                    _takein_xy_float(self.center, x=nx)
                if ny != cy:
                    _takein_xy_float(self.center, y=ny)
                return self
        cx, cy = self._center_xy()
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
            return self
        return self._move_by(dx, dy, force=force)

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Ellipse':
        """Set geometric rotation (degrees) about a pivot (default: center)."""
        current = self._rotation_value()
        return self.rotate_by(_finite_deg(value, "rotate_to angle") - current, about=about, force=force)

    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Ellipse':
        """Rotate about a pivot by angle degrees; updates Defining parts + angle."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        if (
            self.model in (EllipseModel.CENTER_WH, EllipseModel.FROM_RECT)
            and not force
            and not self._requires_pull_invalidate()
        ):
            px, py = self._pivot_xy(about)
            cx, cy = _bare_attr(self.center.x), _bare_attr(self.center.y)
            about_center = (about is None) or (
                _near_pivot(px, py, cx, cy)
            )
            if about_center:
                new_angle = _bare_num(self.angle) + dθ_deg
                self.angle = new_angle
                _pose_rotation_set(self, new_angle)
                return self
        return self._rotate_by_batched(dθ_deg, about=about, force=force)

    @batch_update_self()
    def _rotate_by_batched(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Ellipse':
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)
        cx, cy = self._center_xy()  # Defining only (D3)
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )

        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                _ensure_writable(self["angle"], "rotate_by", force=force)
                new_angle = _bare_num(self.angle) + dθ_deg
                if about_center:
                    self.angle = new_angle
                else:
                    _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
                    ncx, ncy = _rotate_xy(cx, cy, px, py, dθ_rad)
                    self.center._takein((ncx, ncy))
                    self.angle = new_angle
                _pose_rotation_set(self, new_angle)
            case EllipseModel.FOCAL_POINTS:
                _ensure_writable(self.fp1, "rotate_by", force=force)
                _ensure_writable(self.fp2, "rotate_by", force=force)
                x1, y1 = get_xy(self.fp1, bare=True)
                x2, y2 = get_xy(self.fp2, bare=True)
                nx1, ny1 = _rotate_xy(x1, y1, px, py, dθ_rad)
                nx2, ny2 = _rotate_xy(x2, y2, px, py, dθ_rad)
                self.fp1._takein((nx1, ny1))
                self.fp2._takein((nx2, ny2))
                _pose_rotation_add(self, dθ_deg)       # the heading keeps full turns
            case _:
                raise ValueError(f"Unknown ellipse model: {self.model}")

        return self

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Ellipse':
        """Uniformly scale Defining geometry about a pivot."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom

        px, py = self._pivot_xy(about)
        cx, cy = self._center_xy()  # Defining only (D3)
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )

        if force or self._requires_pull_invalidate():   # every check before any write (SB2c)
            self._scale_gate(about, force, (px, py))
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                self.width = _bare_num(self.width) * factor
                self.height = _bare_num(self.height) * factor
                if not about_center:
                    self.center._takein(_scale_xy(cx, cy, px, py, factor))
            case EllipseModel.FOCAL_POINTS:
                x1, y1 = get_xy(self.fp1, bare=True)
                x2, y2 = get_xy(self.fp2, bare=True)
                self.fp1._takein(_scale_xy(x1, y1, px, py, factor))
                self.fp2._takein(_scale_xy(x2, y2, px, py, factor))
                self.major_axis = _bare_num(self.major_axis) * factor
            case _:
                raise ValueError(f"Unknown ellipse model: {self.model}")

        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        match self.model:
            case EllipseModel.CENTER_WH | EllipseModel.FROM_RECT:
                _ensure_writable(self["width"], "scale_by", force=force)
                _ensure_writable(self["height"], "scale_by", force=force)
                if about is not None:
                    px, py = self._pivot_xy(about) if pivot is None else pivot
                    cx, cy = self._center_xy()  # Defining only (D3)
                    if not (_near_pivot(px, py, cx, cy)):
                        _ensure_writable(self.center, "scale_by", force=force, pivot=(px, py))
            case EllipseModel.FOCAL_POINTS:
                _ensure_writable(self.fp1, "scale_by", force=force)
                _ensure_writable(self.fp2, "scale_by", force=force)
                _ensure_writable(self["major_axis"], "scale_by", force=force)

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Ellipse':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)


class _VertexTuple(tuple):
    """``Polygon.points``: a tuple of the vertex Points that takes back its own
    vertex, so ``poly.points[i] @= f`` links vertex ``i`` the way
    ``line.p1 @= f`` links an endpoint.

    Python runs ``points[i] @= f`` as ``v = points[i]; v @= f; points[i] = v``:
    the link is on the vertex before the store. A plain tuple refused the
    store with "'tuple' object does not support item assignment" after the
    link was already installed (PC3). Any other store refuses with the fix.
    """

    __slots__ = ()

    def __setitem__(self, index, value) -> None:
        try:
            current = tuple.__getitem__(self, index)
        except (IndexError, TypeError):
            current = None
        if value is current and current is not None:
            return                          # ``points[i] @= f``: already linked
        raise TypeError(_vertex_store_message(index))

    def __delitem__(self, index) -> None:
        raise TypeError(_vertex_store_message(index))


def _vertex_store_message(index) -> str:
    i = index if isinstance(index, int) else "i"
    return (f"poly.points[{i}] = …: the vertex list is fixed (one Point per vertex). "
            f"Move a vertex with poly.points[{i}].move_to(x, y), or link it with "
            f"poly.points[{i}] @= lambda: ….")


class Polygon(Shape):
    """
    Polygon with a fixed-at-construction number of owned, Defining vertex Points.

    Unlike Point/Line/Rect/Circle/Ellipse, Polygon has a single constructor signature
    (points=[...]) rather than multiple models -- but its N vertices are dynamic-arity
    parts (owned directly, not via ContainerSlot; see class docstring pattern #5 in the
    design doc), each individually linkable exactly like any other Defining part.

    Common Shape kwargs ``color=`` / ``visual=`` / ``line_width=`` /
    ``layer=`` / ``group=`` are accepted (class style defaults for color/visual/group
    apply like other shapes; ``line_width`` is not a class default).

    ``Polygon()`` (no points) builds an irregular quadrilateral at the design
    center — clearly free-form, not a triangle or regular n-gon.

    Defining: vertex Points v0..v(n-1) (each linkable if given an Attribute-bearing source).
    Derivate: centroid (Point, vertex-average -- NOT the true area centroid), signed_area
    (positive = counter-clockwise winding), perimeter_length.

    `center` aliases `centroid` (uniform pivot API, matching Point/Rect/Circle/Ellipse).
    """

    # Computed fields come from the vertices (``Container._derived_field_message``).
    _derived_from = "points"

    @classmethod
    def _ink_name_refusal(cls, name: str) -> Optional[str]:
        """``poly["points"] @= f`` / ``poly["v1"] @= f`` linked a new ink field
        that nothing reads (PC2). A vertex is linked through ``points[i]``."""
        if name == "points":
            index = "i"
        elif name[:1] == "v" and name[1:].isdigit():
            index = str(int(name[1:]))
        else:
            return None
        who = cls.__name__
        if issubclass(cls, _RadialPolygon):         # RegularPolygon, Triangle
            return (f"{who}.{name}: the vertices of a {who} are computed from its "
                    f"{cls._computed_from}; link one of those instead "
                    f"(poly.center @= lambda: ...).")
        what = ("is the fixed vertex list (one Point per vertex), not a field"
                if name == "points" else f"is not a field (vertex {index} is "
                f"poly.points[{index}])")
        return (f"{who}.{name} {what}. Link one vertex: poly.points[{index}] @= "
                f"lambda: ..., move it: poly.points[{index}].move_to(x, y), or build "
                f"the polygon with linked vertices: "
                f"Polygon(points=[lambda: a.center, (0, 0), (5, 0)]).")

    centroid = ContainerSlot(Point, FieldType.Derivate)
    signed_area = ScalarSlot(FieldType.Derivate)
    perimeter_length = ScalarSlot(FieldType.Derivate)

    def __init__(self, *args,
                 points: Optional[List[GeneralPoint]] = None,
                 layer: Any = _USE_LAYER_DEFAULT,
                 group: Optional[Union[str, List[str]]] = None,
                 visual: Optional[LookLike] = None, color: Optional[ColorLike] = None,
                 line_width: Optional[float] = None):
        _reject_positional_shape_args(type(self), args)
        # Style / group class defaults (same keys as _extract_common_params_and_signature).
        defaults = getattr(type(self), '_shape_defaults', None) or {}
        if color is None and 'color' in defaults:
            color = defaults['color']
        if visual is None and 'visual' in defaults:
            visual = defaults['visual']
        if group is None and 'group' in defaults:
            group = defaults['group']

        if callable(points) and not isinstance(points, type):
            raise TypeError(
                "Polygon points= takes a list — the vertex count is fixed. "
                "Link single vertices: "
                "Polygon(points=[lambda: a, (0, 0), (5, 0)])."
            )
        if points is None:
            # Polygon() — irregular quad at design center (centroid = center; uneven sides).
            (cx, cy), unit = _default_pose()
            # Offsets sum to zero so the vertex-average centroid sits on (cx, cy).
            # CCW in y-up; unequal radii / angles → not regular.
            points = [
                (cx + 1.2 * unit, cy + 0.8 * unit),
                (cx - 0.7 * unit, cy + 0.9 * unit),
                (cx - 1.4 * unit, cy - 0.6 * unit),
                (cx + 0.9 * unit, cy - 1.1 * unit),
            ]
        else:
            if not isinstance(points, (list, tuple)):
                # A generator / range of points is read once (it leaked "has no
                # len()"); a string or a mapping is not a list of points (SC9).
                # One Point / Vec2 / mouse iterates as its (x, y): not a list.
                if (isinstance(points, (str, bytes, dict)) or not hasattr(points, "__iter__")
                        or getattr(type(points), "_scena_point_value", False)):
                    raise TypeError(f"Polygon points= takes a list of points, got "
                                    f"{type(points).__name__}")
                points = list(points)
            if len(points) < 3:
                raise ValueError(f"Polygon requires at least 3 points, got {len(points)}")

        super().__init__(
            layer=layer, group=group, visual=visual, color=color,
            line_width=line_width,
        )

        # Create all vertices (and register them as parts) *before* wiring any values, so
        # the batch_update below covers the whole subtree from the start -- otherwise the
        # first assign_formula would trigger a premature _update_impl with a partial
        # (or empty) vertex list.
        self._vertices: List[Point] = []
        for i in range(len(points)):
            vertex = Point.__new__(Point)
            Point._construct(vertex, attr_name=f"v{i}", owner=self)
            vertex._field_type = FieldType.Defining
            self._vertices.append(vertex)

        with self._batch_update():
            for vertex, p in zip(self._vertices, points):
                _init_composite(vertex, p)

    @property
    def points(self) -> Tuple[Point, ...]:
        """The polygon's vertex Points, in order (read-only view; count is fixed).

        A ``_VertexTuple``: ``poly.points[i] @= f`` links that vertex (Python
        stores the vertex back after ``@=``, which the view accepts)."""
        return _VertexTuple(self._vertices)

    @property
    def center(self) -> Point:
        """Alias for centroid (uniform pivot API with Point/Rect/Circle/Ellipse)."""
        return self.centroid

    def _center_xy(self) -> Tuple[float, float]:
        """Vertex-average centroid from the Defining vertices — never wakes the
        Derivate ``centroid`` (engine readers stay cold; D3 in Testing Design)."""
        verts = self._vertices
        n = len(verts)
        if not n:
            return get_xy(self.centroid, bare=True)
        sx = sy = 0.0
        for v in verts:
            sx += _bare_num(v.x)
            sy += _bare_num(v.y)
        return (sx / n, sy / n)

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """Centroid-relative verts so a vertex drag rebuilds the collision hull.

        Pose keys are ``(epoch, cx, cy, *extra)``. Extra must stay identical under
        rigid ``move_by`` (translate the cached hull) and change when layout
        deforms — otherwise the translate fast-path slides a stale polygon.
        World-space verts would break that path; offsets from the vertex-average
        centroid do not. Read ``_vertices`` with ``_bare_num`` (not ``.points``).
        """
        verts = self._vertices
        n = len(verts)
        rot = float(self._rotation)
        scale = float(self._scale)
        if n == 0:
            return (rot, scale)
        xs = [_bare_num(v.x) for v in verts]
        ys = [_bare_num(v.y) for v in verts]
        inv_n = 1.0 / n
        cx = sum(xs) * inv_n
        cy = sum(ys) * inv_n
        extra = [rot, scale]
        extra.extend(c for x, y in zip(xs, ys) for c in (x - cx, y - cy))
        return tuple(extra)

    @batch_update_attrs('centroid', 'signed_area', 'perimeter_length')
    def _update_impl(self) -> None:
        """Recompute centroid (vertex average), signed_area (shoelace), perimeter_length."""
        n = len(self._vertices)
        xs = [_bare_num(v.x) for v in self._vertices]
        ys = [_bare_num(v.y) for v in self._vertices]

        cx = sum(xs) / n
        cy = sum(ys) / n

        area2 = 0.0
        perimeter = 0.0
        for i in range(n):
            x1, y1 = xs[i], ys[i]
            x2, y2 = xs[(i + 1) % n], ys[(i + 1) % n]
            area2 += x1 * y2 - x2 * y1
            perimeter += math.hypot(x2 - x1, y2 - y1)

        self.centroid._takein((cx, cy))
        self.signed_area = area2 / 2.0
        self.perimeter_length = perimeter

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill centroid / area / perimeter on first access."""
        if name not in ('centroid', 'signed_area', 'perimeter_length'):
            return
        with self._no_update():
            self._update_impl()

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw in centroid-local CTM so Gradient/Texture shaders rotate with the polygon."""
        verts = [get_xy(v, bare=True) for v in self._vertices]
        if not verts:
            return
        cx = sum(p[0] for p in verts) / len(verts)
        cy = sum(p[1] for p in verts) / len(verts)
        rot = float(self._rotation)
        cos_a = math.cos(_rad(-rot)) if rot else 1.0
        sin_a = math.sin(_rad(-rot)) if rot else 0.0

        offsets = []
        for wx, wy in verts:
            dx, dy = wx - cx, wy - cy
            if rot:
                lx = dx * cos_a - dy * sin_a
                ly = dx * sin_a + dy * cos_a
            else:
                lx, ly = dx, dy
            offsets.append((round(lx, 3), round(ly, 3)))
        key = (len(offsets), tuple(offsets))
        if self._geom_path is None or self._geom_path_key != key:
            path = skia.Path()
            for i, (lx, ly) in enumerate(offsets):
                if i == 0:
                    path.moveTo(lx, ly)
                else:
                    path.lineTo(lx, ly)
            path.close()
            _geom_path_cache_set(self, path, key)
        path = self._geom_path

        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if rot:
            skia_canvas.rotate(rot)

        skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        if skia_fill_paint:
            skia_canvas.drawPath(path, skia_fill_paint)

        skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if skia_line_paint:
            skia_canvas.drawPath(path, skia_line_paint)

        skia_canvas.restore()

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Point-in-polygon over world-space vertices (also used by RegularPolygon)."""
        return _point_in_polygon(x, y, self.points)

    def _takein_impl(self, other: 'Polygon') -> None:
        """Copy vertex values (must have the same vertex count -- arity is fixed at construction)."""
        if len(other._vertices) != len(self._vertices):
            raise ValueError(
                f"Cannot take in a Polygon with a different vertex count "
                f"({len(other._vertices)} vs {len(self._vertices)})"
            )
        # The source's vertices as read: a RegularPolygon's are cold Derivates
        # (its ``points`` places them), so ``_vertices`` read (0, 0) (SC2).
        for mine, theirs in zip(self._vertices, other.points):
            mine._takein(theirs)

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        return tuple(self._vertices)

    def _parts_written_by_wheel_rotate(self) -> Tuple:
        # Vertices move; _pose_rotation_add also updates PropertyAnchor rotation.
        return (*self._vertices, self["angle"])

    def _clone_geometry(self, **kwargs) -> 'Polygon':
        pts = [get_xy(v, bare=True) for v in self._vertices]
        return type(self)(points=pts, **kwargs)

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Polygon':
        """Translate every vertex by dx and/or dy.

        Free polygon (nothing pulls from it, nothing read its Derivates):
        bare float writes, as Rect does (graphics review SC10: 20.7 µs
        against Rect's 2.7). A read of ``centroid`` / ``signed_area`` /
        ``perimeter_length`` sets the sticky pull flag, so they never go stale."""
        if _pose_fast_ok(self, force=force):
            _translate_points_float(self._vertices, dx, dy)
            return self
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> 'Polygon':
        for vertex in self._vertices:      # every vertex first, then write (SC4)
            _ensure_writable(vertex, "move_by", force=force)
        for vertex in self._vertices:
            if dx is not None:
                vertex.x += dx
            if dy is not None:
                vertex.y += dy
        return self

    @batch_update_self()
    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Polygon':
        """Move the polygon's centroid to absolute x and/or y coordinates."""
        cx, cy = self._center_xy()
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
            return self
        return self._move_by(dx, dy, force=force)

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Polygon':
        """Set absolute rotation (degrees) about a pivot (default: centroid)."""
        _fresh_pose(self)
        return self.rotate_by(_finite_deg(value, "rotate_to angle") - self._rotation, about=about, force=force)

    @batch_update_self()
    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Polygon':
        """Rotate every vertex about a pivot by angle degrees."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        _gate_pose_anchor(self, "angle", "rotate_by", force)
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)
        for vertex in self._vertices:      # every vertex first, then write (SC4)
            _ensure_writable(vertex, "rotate_by", force=force, pivot=(px, py))
        for vertex in self._vertices:
            x, y = get_xy(vertex, bare=True)
            vertex._takein(_rotate_xy(x, y, px, py, dθ_rad))
        _pose_rotation_add(self, dθ_deg)
        return self

    def _mirror_points(self):
        return list(getattr(self, "_vertices", ()) or ())

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Polygon':
        """Scale every vertex's distance from a pivot by factor."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        px, py = self._pivot_xy(about)
        if force or self._requires_pull_invalidate():   # every vertex first, then write (SC4)
            self._scale_gate(about, force, (px, py))
        for vertex in self._vertices:
            x, y = get_xy(vertex, bare=True)
            vertex._takein(_scale_xy(x, y, px, py, factor))
        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        if pivot is None:
            pivot = self._pivot_xy(about)
        for vertex in self._vertices:
            _ensure_writable(vertex, "scale_by", force=force, pivot=pivot)

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Polygon':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)


def _hide_positional_catchall(cls: type) -> None:
    """``help(cls)`` shows the keyword-only signature; ``*args`` only exists to reject."""
    import inspect
    init = cls.__dict__["__init__"]
    sig = inspect.signature(init)
    params = [p for p in sig.parameters.values() if p.kind is not p.VAR_POSITIONAL]
    init.__signature__ = sig.replace(parameters=params)


_hide_positional_catchall(Polygon)


class RegularPolygonModel(Enum):
    CENTER_RADIUS = "center_radius"
    CENTER_SIDE = "center_side"
    VERTEX_SIDE = "vertex_side"


class _LazyRegularPolygonPoints(Sequence):
    """Read-only vertex view that materializes only indexed/iterated verts."""

    __slots__ = ('_poly',)

    def __init__(self, poly: 'RegularPolygon'):
        self._poly = poly

    def __len__(self) -> int:
        return self._poly._n

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self[i] for i in range(*index.indices(len(self))))
        if type(index) is not int:
            if isinstance(index, bool) or not isinstance(index, int):
                # rp.points['a'] leaked "'<' not supported" (graphics review SC9)
                raise TypeError(f"{self._poly._KIND_LABEL}.points takes a whole-number index or a slice, "
                                f"got {type(index).__name__} {index!r:.20}")
            index = int(index)
        self._poly._ensure_vertex_live(index)
        return self._poly._vertices[index]

    def __setitem__(self, index, value) -> None:
        # ``rp.points[i] @= f`` refuses in the ``@=`` (a computed vertex);
        # a plain store gets the reason, not "does not support item assignment".
        poly = self._poly
        raise TypeError(
            f"{poly._KIND_LABEL}.points[{index!r:.20}] = …: the vertices are computed "
            f"from its {poly._computed_from}. Move or turn the polygon "
            f"(move_to, rotate_to), or link its center: poly.center @= lambda: ….")


class _RadialPolygon(Polygon):
    """Shared machinery of ``RegularPolygon`` and ``Triangle``: a Polygon whose
    vertices are always Derivate, placed in closed form from ``center`` /
    ``vertex``, ``radius`` / ``side`` and ``angle`` (the heading of vertex[0]).

    Models (``RegularPolygonModel``): CENTER_RADIUS, CENTER_SIDE, VERTEX_SIDE.
    ``radius`` is the center-to-vertex[0] distance. The defaults below are the
    regular n-gon; ``Triangle`` overrides the shape hooks
    (``_placement_params`` / ``_side_from_radius`` / ``_vertex_xy`` /
    ``_world_verts`` / ``_local_verts`` / ``_reach_factor`` / the hit test and
    the pose extra) and adds ``base_ratio``; the regular formulas stay inline
    here, so a RegularPolygon pays no hook. Private: never instantiated directly.
    """

    _KIND_LABEL = "RegularPolygon"
    _computed_from = "center, radius and angle"     # refusal text (points[i] =, poly["points"])

    # Model inputs (center / vertex, radius / side, angle), not free points.
    _derived_from = None

    center = ContainerSlot(Point)
    radius = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="RegularPolygon.radius")
    side = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="RegularPolygon.side")
    angle = ScalarSlot()
    vertex = ContainerSlot(Point, FieldType.Derivate)

    # Shadow Polygon's vertex-layout extra. Pose-key lookup is
    # ``getattr(cls, "_collision_pose_extra", None)``. A small callable packs
    # Defining slots (angle / radius / side) and never walks Derivate verts.
    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, angle, radius, side)`` — no vertex walk.

        Defining slot assigns often skip ``_collision_epoch``. Extra must
        change when angle / radius / side change so the translate fast-path
        does not slide a stale hull. Do not inherit ``Polygon``'s
        centroid-relative verts: those are Derivate outputs here.
        """
        try:
            rot = float(self._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(self._scale)
        except Exception:
            scale = 1.0
        _slot = self._fresh_scalar
        return (
            rot,
            scale,
            _slot("angle"),
            _slot("radius"),
            _slot("side"),
        )

    def _fresh_scalar(self, name: str) -> float:
        """A Defining scalar's current value, refreshing a link first."""
        d = self.__dict__
        anchors = d.get("_field_anchors")
        if anchors:
            anchor = anchors.get(name)
            if anchor is not None:
                anchor._ensure_fresh()
        else:
            bare_ok = d.get("_scalar_bare_ok")
            if bare_ok is not None and bare_ok.get(name) is False:
                self._refresh_scalar(name)
        val = d.get(name, 0.0)
        return 0.0 if val is None else float(val)

    # Home model = CENTER_RADIUS (same as RegularPolygon() / Triangle()).
    _HOME_KEYS = frozenset({"center", "radius"})
    _HOME_OPTIONAL_KEYS = frozenset({"angle"})

    _CONSTRUCTOR_SIGNATURES = [
        ("center_radius",       {"center", "radius"}),
        ("center_radius_angle", {"center", "radius", "angle"}),
        ("center_side",         {"center", "side"}),
        ("center_side_angle",   {"center", "side", "angle"}),
        ("vertex_side",         {"vertex", "side"}),
        ("vertex_side_angle",   {"vertex", "side", "angle"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        (cx, cy), unit = _default_pose()
        return {"center": (cx, cy), "radius": unit}

    def _init_radial(self, n: int, kwargs: Dict[str, Any]) -> None:
        """Build the model from ``kwargs`` once the subclass resolved ``n``."""
        self._n = n

        from .box import apply_box_to_shape_kwargs
        apply_box_to_shape_kwargs(
            type(self).__name__, kwargs, family="inscribe",
            size_keys=("radius", "side"), heading=True,
        )
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs,
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )
        # Bypass Polygon.__init__ (points=[...]) entirely -- RegularPolygon has its own
        # Defining/Derivate model instead of taking explicit vertex positions.
        Shape.__init__(self, **base_params)

        # Derivate vertex Points, owned directly (dynamic arity, like Polygon's) but always
        # computed -- never Defining -- for a regular polygon.
        # Structural shape↔vertex edges are deferred until a vertex becomes live
        # (points[i], centroid/stats, external formula). Wiring all n vertices
        # eagerly made every move/rotate/scale O(n) via mark_dirty + batch walks,
        # even when draw uses only Defining center/radius/angle via Skia CTM.
        self._vertices: List[Point] = []
        self._wired_vertices: Set[int] = set()
        for i in range(n):
            vtx = Point.__new__(Point)
            Point._construct(vtx, attr_name=f"v{i}", owner=self)
            vtx._field_type = FieldType.Derivate
            # Clear the ownership edge add_parts installed (field_type was still
            # Defining at owner-set time). Wire lazily in _wire_vertex.
            self._clear_structural_edge(vtx)
            self._vertices.append(vtx)

        match signature:
            case "center_radius" | "center_radius_angle":
                self.model = RegularPolygonModel.CENTER_RADIUS
                self._set_defining_parts('center', 'radius', 'angle')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _reject_non_finite(kwargs['radius'], what=f"{self._KIND_LABEL}.radius")
                    _init_scalar(self, 'radius', kwargs['radius'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))
                    self._init_shape_inputs(kwargs)

            case "center_side" | "center_side_angle":
                self.model = RegularPolygonModel.CENTER_SIDE
                self._set_defining_parts('center', 'side', 'angle')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _reject_non_finite(kwargs['side'], what=f"{self._KIND_LABEL}.side")
                    _init_scalar(self, 'side', kwargs['side'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))
                    self._init_shape_inputs(kwargs)

            case "vertex_side" | "vertex_side_angle":
                self.model = RegularPolygonModel.VERTEX_SIDE
                self._set_defining_parts('vertex', 'side', 'angle')
                with self._batch_update():
                    _init_composite(self.vertex, kwargs['vertex'])
                    _reject_non_finite(kwargs['side'], what=f"{self._KIND_LABEL}.side")
                    _init_scalar(self, 'side', kwargs['side'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))
                    self._init_shape_inputs(kwargs)

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        _pose_rotation_set(self, _bare_num(self.angle))

    def _init_shape_inputs(self, kwargs: Dict[str, Any]) -> None:
        """Hook inside the construction batch (Triangle sets ``base_ratio``)."""

    _PART_NAMES = ('center', 'radius', 'side', 'angle', 'vertex')

    @property
    def is_collapsed(self) -> bool:
        """True when circumradius is ``0``."""
        return float(self._scale) == 0.0 or self._placement_params()[2] == 0.0

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Point-in-polygon over closed-form vertices: ``points`` would build a
        Point per vertex and wake them (SC6 / SB8: one hover cost 2.8 → 58 µs
        per later move + rotate)."""
        cx, cy, r, phi0 = self._placement_params()
        step = self._winding() * 2.0 * math.pi / self._n
        a0 = _rad(phi0)
        verts = [(cx + r * math.cos(a0 + i * step), cy + r * math.sin(a0 + i * step))
                 for i in range(self._n)]
        return _point_in_polygon(x, y, verts)

    def _world_verts(self, cx: float, cy: float, r: float, phi0: float,
                     winding: int = 1) -> List[Tuple[float, float]]:
        """Closed-form world vertices (``winding=1``: counter-clockwise from vertex[0]).

        Every consumer that needs the outline (hit test, collision hull,
        ``geom``, ``Track(shape)``) reads it here, never a regular-n-gon formula
        of its own: a ``Triangle`` with ``base_ratio != 1`` is not regular.
        """
        step = winding * 2.0 * math.pi / self._n
        a0 = _rad(phi0)
        return [(cx + r * math.cos(a0 + i * step), cy + r * math.sin(a0 + i * step))
                for i in range(self._n)]

    def _closed_form_verts(self) -> List[Tuple[float, float]]:
        """Counter-clockwise world vertices from the Defining inputs."""
        cx, cy, r, phi0 = self._placement_params()
        return self._world_verts(cx, cy, r, phi0)

    # Bounds (culling, broad-phase) are a circle of ``radius`` about the
    # center. A kind whose vertices reach past ``radius`` (Triangle with
    # base_ratio > 1) defines ``_reach_factor()`` → bounds radius / radius;
    # None here keeps the regular path one attribute read.
    _reach_factor = None

    def _side_from_radius(self, r: float) -> float:
        return 2.0 * r * math.sin(math.pi / self._n)

    def _vertex_xy(self, idx: int, cx: float, cy: float, r: float, phi0: float) -> Tuple[float, float]:
        """World position of ``vertex[idx]`` in the current numbering."""
        a = _rad(phi0) + idx * self._winding() * (2.0 * math.pi / self._n)
        return (cx + r * math.cos(a), cy + r * math.sin(a))

    def _include_point_slot_in_debug(self, name: str) -> bool:
        """Skip inactive alternate-model inputs and centroid (duplicates center)."""
        if name == 'centroid':
            # Numerically identical to ``center`` for a regular n-gon.
            return False
        if name == 'vertex' and self.model != RegularPolygonModel.VERTEX_SIDE:
            return False
        if name == 'center' and self.model == RegularPolygonModel.VERTEX_SIDE:
            # Derivate center — still useful to show.
            return True
        return True

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark Defining parts for this model; cold Derivates stay unregistered."""
        self._mark_defining_parts(*defining, catalog=self._PART_NAMES)
        # Full rewire above would install shape↔vertex edges for every v{i}.
        # Keep cold Derivate vertices out of the dependents cone until live.
        wired = getattr(self, '_wired_vertices', None)
        if wired is not None:
            for i, vtx in enumerate(self._vertices):
                if i not in wired:
                    self._clear_structural_edge(vtx)

    def _wire_vertex(self, idx: int) -> None:
        """Install shape↔vertex structural edges the first time a vertex goes live."""
        if idx in self._wired_vertices:
            return
        vtx = self._vertices[idx]
        self._set_structural_edge(vtx, upward=True)
        vtx._rewire_subtree_structural_edges(upward=True)
        self._wired_vertices.add(idx)

    def _takein_impl(self, other: 'RegularPolygon') -> None:
        """Copy only the defining attributes for the current model (n must match)."""
        if self._n != other._n:
            raise ValueError(
                f"Cannot take in a {other._KIND_LABEL} with a different n ({other._n} vs {self._n})"
            )
        self._adopt_model_of(other)
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS:
                self.center._takein(other.center)
                _init_scalar(self, 'radius', other.radius)
            case RegularPolygonModel.CENTER_SIDE:
                self.center._takein(other.center)
                _init_scalar(self, 'side', other.side)
            case RegularPolygonModel.VERTEX_SIDE:
                self.vertex._takein(other.vertex)
                _init_scalar(self, 'side', other.side)
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")
        _init_scalar(self, 'angle', other.angle)
        self._takein_shape_inputs(other)
        self.__dict__['_vertex_winding'] = other._winding()

    def _takein_shape_inputs(self, other) -> None:
        """Hook: copy shape inputs past the model's (Triangle: ``base_ratio``)."""

    def _winding(self) -> int:
        """``+1``: ``vertex[k]`` runs counter-clockwise from vertex[0]; ``-1`` after an odd
        number of flips. Vertices follow their points (Shapes Design — Named points)."""
        return self.__dict__.get('_vertex_winding', 1)

    def _adopt_winding(self, clone: 'RegularPolygon') -> 'RegularPolygon':
        """Give a clone this polygon's vertex numbering."""
        if self._winding() != clone._winding():
            clone.__dict__['_vertex_winding'] = self._winding()
            clone.update()
        return clone

    def _geometric_angle(self) -> float:
        """Direction center→vertex[0] in degrees (0 = +x). Subclasses may offset."""
        return _bare_num(self.angle)

    def _mirror_geometry(self, axis: str, *, force: bool = False) -> None:
        """Mirror about ``center``: the polygon keeps its place and becomes its mirror.

        Mirrors the heading of vertex[0] (``_geometric_angle``). A subclass
        may offset it from ``angle``; mirroring the raw ``angle`` then
        draws a different polygon (G6). ``vertex=`` models also mirror their
        Defining vertex — left in place, the polygon swung about it. With no
        offset this is the flip convention (``flip_x``: ``180 − θ``,
        ``flip_y``: ``−θ``). A mirror reverses the winding, so ``vertex[k]``
        lands on the mirror of the old ``vertex[k]`` (the list turns clockwise).
        """
        _ensure_writable(self["angle"], "flip", force=force)
        on_vertex = self.model == RegularPolygonModel.VERTEX_SIDE
        if on_vertex:
            _ensure_writable(self.vertex, "flip", force=force)
        cx, cy, _r, phi = self._placement_params()
        mirrored = (180.0 - phi) if axis == "x" else -phi
        new_rotation = _bare_num(self.angle) + (mirrored - phi)
        with self._batch_update():
            if on_vertex:
                vx, vy = get_xy(self.vertex, bare=True)
                self.vertex._takein((2.0 * cx - vx, vy) if axis == "x" else (vx, 2.0 * cy - vy))
            self.angle = new_rotation
            self.__dict__['_vertex_winding'] = -self._winding()
        _pose_rotation_set(self, new_rotation)

    def _placement_params(self) -> Tuple[float, float, float, float]:
        """Return (cx, cy, r, phi0) from the active model's Defining inputs."""
        phi0 = self._geometric_angle()
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS:
                cx, cy = get_xy(self.center, bare=True)
                r = abs(_bare_num(self.radius))
            case RegularPolygonModel.CENTER_SIDE:
                cx, cy = get_xy(self.center, bare=True)
                s = _bare_num(self.side)
                r = abs(s) / (2.0 * math.sin(math.pi / self._n))
            case RegularPolygonModel.VERTEX_SIDE:
                vx, vy = get_xy(self.vertex, bare=True)
                s = _bare_num(self.side)
                # abs before the center offset: a negative side is the same
                # polygon, not a center flipped through the vertex.
                r = abs(s) / (2.0 * math.sin(math.pi / self._n))
                cx = vx - r * math.cos(_rad(phi0))
                cy = vy - r * math.sin(_rad(phi0))
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")
        return cx, cy, r, phi0

    def _center_xy(self) -> Tuple[float, float]:
        """Pose center from Defining inputs — VERTEX_SIDE must not wake Derivate ``center``."""
        cx, cy, _r, _phi = self._placement_params()
        return (cx, cy)

    def _place_vertices(self, cx: float, cy: float, r: float, phi0: float) -> None:
        """Write live Derivate vertices (and all verts when polygon stats are live)."""
        delta = self._winding() * 2.0 * math.pi / self._n
        phi0_rad = _rad(phi0)
        place_all = self._stats_live()
        for i, vtx in enumerate(self._vertices):
            if not place_all and not vtx._is_derivate_live():
                continue
            a = phi0_rad + i * delta
            vtx._takein((cx + r * math.cos(a), cy + r * math.sin(a)))

    def _ensure_vertex_live(self, idx: int) -> None:
        """Mark vertex idx live and refresh its world position immediately."""
        if idx < 0:
            idx += self._n
        if idx < 0 or idx >= self._n:
            raise IndexError(f"{self._KIND_LABEL} vertex index {idx} out of range: it has {self._n} "
                             f"vertices (0 … {self._n - 1})")
        self._wire_vertex(idx)
        vtx = self._vertices[idx]
        vtx._derivate_live = True
        vtx._flag_pull_consumers()
        cx, cy, r, phi0 = self._placement_params()
        with self._no_update():
            vtx._takein(self._vertex_xy(idx, cx, cy, r, phi0))

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill a Derivate part on first access / link (named slot or v{i})."""
        if name.startswith('v') and name[1:].isdigit():
            self._ensure_vertex_live(int(name[1:]))
            return
        if name in ('centroid', 'signed_area', 'perimeter_length'):
            # Stats need every vertex placed; wire + mark live then recompute.
            for i, vtx in enumerate(self._vertices):
                self._wire_vertex(i)
                vtx._derivate_live = True
                vtx._flag_pull_consumers()
            with self._no_update():
                self._update_impl()
                # The stat's slot is still being created, so ``_stats_live()``
                # cannot see it yet: compute the stats here, or the first read
                # stays at the slot default (G8: signed_area read 0).
                Polygon._update_impl(self)
            return
        if name in self._PART_NAMES:
            with self._no_update():
                self._update_impl()
            return

    @property
    def points(self):
        """Vertex Points; indexing/iteration materializes only the verts touched."""
        return _LazyRegularPolygonPoints(self)

    def _stats_live(self) -> bool:
        # A stat read for the first time is registered in ``_derivate_state``
        # before it has a value: count it, or a first read on a dirty polygon
        # skips the stats and returns the slot default (G8 read-order case).
        registered = self.__dict__.get('_derivate_state') or ()
        for name in ('centroid', 'signed_area', 'perimeter_length'):
            part = self.__dict__.get(name)
            if isinstance(part, Container):
                if part._is_derivate_live():
                    return True
            elif part is not None or name in registered:
                return True
        return False

    def _refresh_live_vertex(self, cx: float, cy: float, r: float, phi0: float) -> None:
        """Derivate ``vertex`` (= vertex[0]) in the center models, when live."""
        a = _rad(phi0)
        self._takein_live_derivate('vertex', (cx + r * math.cos(a), cy + r * math.sin(a)))

    def _update_impl(self) -> None:
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS:
                self._update_impl_center_radius()
            case RegularPolygonModel.CENTER_SIDE:
                self._update_impl_center_side()
            case RegularPolygonModel.VERTEX_SIDE:
                self._update_impl_vertex_side()
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")

    @batch_update_self()
    def _update_impl_center_radius(self) -> None:
        """center, radius, angle define the polygon; side is the derived chord length."""
        cx, cy, r, phi0 = self._placement_params()
        self._place_vertices(cx, cy, r, phi0)
        self._refresh_live_vertex(cx, cy, r, phi0)
        if self._field_is_derivate('side'):
            self.side = self._side_from_radius(r)
        if self._stats_live():
            super()._update_impl()

    @batch_update_self()
    def _update_impl_center_side(self) -> None:
        """center, side, angle define the polygon; radius is the derived circumradius."""
        cx, cy, r, phi0 = self._placement_params()
        if self._field_is_derivate('radius'):
            self.radius = r
        self._place_vertices(cx, cy, r, phi0)
        self._refresh_live_vertex(cx, cy, r, phi0)
        if self._stats_live():
            super()._update_impl()

    @batch_update_attrs('center', 'radius')
    def _update_impl_vertex_side(self) -> None:
        """vertex, side, angle define the polygon; center/radius are derived."""
        cx, cy, r, phi0 = self._placement_params()
        center = self.__dict__.get('center')
        if center is not None and (
            center._field_type == FieldType.Defining or center._is_derivate_live()
        ):
            self.center._takein((cx, cy))
        radius = self.__dict__.get('radius')
        if self._field_is_derivate('radius'):
            self.radius = r
        elif isinstance(radius, Container) and (
            radius._field_type == FieldType.Defining or radius._is_derivate_live()
        ):
            self.radius = r
        self._place_vertices(cx, cy, r, phi0)
        if self._stats_live():
            super()._update_impl()

    def _local_path_key(self, r: float):
        """Cache key of the local-frame path: everything but the pose."""
        return (self._n, round(float(r), 4))

    def _local_verts(self, r: float) -> List[Tuple[float, float]]:
        """Counter-clockwise vertices in the local frame (vertex[0] on +x)."""
        delta = 2.0 * math.pi / self._n
        return [(r * math.cos(i * delta), r * math.sin(i * delta)) for i in range(self._n)]

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw via local-frame CTM; path is cached by ``_local_path_key``."""
        cx, cy, r, phi0 = self._placement_params()

        key = self._local_path_key(r)
        if self._geom_path is None or self._geom_path_key != key:
            path = skia.Path()
            for i, (px, py) in enumerate(self._local_verts(r)):
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            path.close()
            _geom_path_cache_set(self, path, key)
        path = self._geom_path

        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if phi0:
            skia_canvas.rotate(phi0)

        skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
        if skia_fill_paint:
            skia_canvas.drawPath(path, skia_fill_paint)
        skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
        if skia_line_paint:
            skia_canvas.drawPath(path, skia_line_paint)
        skia_canvas.restore()

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS | RegularPolygonModel.CENTER_SIDE:
                return (self.center,)
            case RegularPolygonModel.VERTEX_SIDE:
                return (self.vertex,)
            case _:
                return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple[Container, ...]:
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS | RegularPolygonModel.CENTER_SIDE:
                return (self["angle"],)
            case RegularPolygonModel.VERTEX_SIDE:
                return (self.vertex, self["angle"])
            case _:
                return ()

    def _clone_geometry(self, **kwargs) -> 'RegularPolygon':
        # Same model and pose, same vertex numbering (a flipped polygon's clone too).
        return self._adopt_winding(self._clone_geometry_same_model(**kwargs))

    def _clone_shape_kwargs(self) -> Dict[str, Any]:
        """Keywords a same-model clone passes besides the model's inputs."""
        return {"n": self._n}

    def _clone_geometry_same_model(self, **kwargs) -> 'RegularPolygon':
        kwargs = {**self._clone_shape_kwargs(), **kwargs}
        cls = type(self)
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS:
                return cls(
                    center=get_xy(self.center, bare=True),
                    radius=_bare_num(self.radius),
                    angle=_bare_num(self.angle),
                    **kwargs,
                )
            case RegularPolygonModel.CENTER_SIDE:
                return cls(
                    center=get_xy(self.center, bare=True),
                    side=_bare_num(self.side),
                    angle=_bare_num(self.angle),
                    **kwargs,
                )
            case RegularPolygonModel.VERTEX_SIDE:
                return cls(
                    vertex=get_xy(self.vertex, bare=True),
                    side=_bare_num(self.side),
                    angle=_bare_num(self.angle),
                    **kwargs,
                )
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'RegularPolygon':
        """Translate the Defining position part (center, or vertex for VERTEX_SIDE)."""
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS | RegularPolygonModel.CENTER_SIDE:
                if _pose_fast_ok(self, force=force):
                    _translate_point_float(self.center, dx, dy)
                    return self
                return self._move_by_center(dx, dy, force=force)
            case RegularPolygonModel.VERTEX_SIDE:
                if _pose_fast_ok(self, force=force):
                    _translate_point_float(self.vertex, dx, dy)
                    return self
                return self._move_by_vertex(dx, dy, force=force)
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'RegularPolygon':
        """Move the geometric center to absolute coords — not Polygon.centroid.

        Irregular ``Polygon._move_to`` reads Derivate ``centroid``, which would
        materialize pull consumers and defeat A2. Regular polygons use Defining
        ``center``, or a center-relative vertex delta on VERTEX_SIDE.
        """
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS | RegularPolygonModel.CENTER_SIDE:
                if _pose_fast_ok(self, force=force):
                    cx = _bare_attr(self.center.x)
                    cy = _bare_attr(self.center.y)
                    nx = cx if x is None else float(x)
                    ny = cy if y is None else float(y)
                    if nx != cx:
                        _takein_xy_float(self.center, x=nx)
                    if ny != cy:
                        _takein_xy_float(self.center, y=ny)
                    return self
                return self._move_to_center(x, y, force=force)
            case RegularPolygonModel.VERTEX_SIDE:
                cx, cy = self._center_xy()
                dx = None if x is None else float(x) - cx
                dy = None if y is None else float(y) - cy
                if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
                    return self
                return self._move_by(dx, dy, force=force)
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")

    @batch_update_attrs('center')
    def _move_by_center(self, dx: float, dy: float, *, force: bool = False) -> 'RegularPolygon':
        _ensure_writable(self.center, "move_by", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        if dx is not None:
            cx = cx + float(dx)
        if dy is not None:
            cy = cy + float(dy)
        self.center._takein((cx, cy))
        return self

    @batch_update_attrs('center')
    def _move_to_center(self, x: float, y: float, *, force: bool = False) -> 'RegularPolygon':
        _ensure_writable(self.center, "move_to", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if nx != cx or ny != cy:
            self.center._takein((nx, ny))
        return self

    @batch_update_attrs('vertex')
    def _move_by_vertex(self, dx: float, dy: float, *, force: bool = False) -> 'RegularPolygon':
        _ensure_writable(self.vertex, "move_by", force=force)
        if dx is not None:
            self.vertex.x += dx
        if dy is not None:
            self.vertex.y += dy
        return self

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        """Set absolute rotation (direction to vertex[0], degrees) about a pivot (default: center)."""
        current = _bare_num(self.angle)
        return self.rotate_by(_finite_deg(value, "rotate_to angle") - current, about=about, force=force)

    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        """Rotate about a pivot by angle degrees; updates Defining parts + angle."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS | RegularPolygonModel.CENTER_SIDE:
                # Default pivot is center — skip ``_pivot_xy`` / ``get_xy``.
                # Linked angle / live verts still take the structural path (A2).
                about_center = about is None
                if not about_center:
                    px, py = self._pivot_xy(about)
                    cx, cy = get_xy(self.center, bare=True)
                    about_center = _near_pivot(px, py, cx, cy)
                if about_center and not force and not self._requires_pull_invalidate():
                    new_angle = _bare_num(self.angle) + dθ_deg
                    self.__dict__["angle"] = new_angle
                    _pose_rotation_set(self, new_angle)
                    return self
                return self._rotate_by_center(dθ_deg, about=about, force=force)
            case RegularPolygonModel.VERTEX_SIDE:
                return self._rotate_by_vertex(dθ_deg, about=about, force=force)
            case _:
                raise ValueError(f"Unknown regular polygon model: {self.model}")

    @batch_update_attrs('center', 'angle')
    def _rotate_by_center(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)
        cx, cy = get_xy(self.center, bare=True)
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )
        _ensure_writable(self["angle"], "rotate_by", force=force)
        new_angle = _bare_num(self.angle) + dθ_deg
        if about_center:
            self.angle = new_angle
        else:
            _ensure_writable(self.center, "rotate_by", force=force, pivot=(px, py))
            ncx, ncy = _rotate_xy(cx, cy, px, py, dθ_rad)
            self.center._takein((ncx, ncy))
            self.angle = new_angle
        _pose_rotation_set(self, new_angle)
        return self

    @batch_update_attrs('vertex', 'angle')
    def _rotate_by_vertex(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)
        _ensure_writable(self["angle"], "rotate_by", force=force)
        _ensure_writable(self.vertex, "rotate_by", force=force, pivot=(px, py))
        new_angle = _bare_num(self.angle) + dθ_deg
        vx, vy = get_xy(self.vertex, bare=True)
        self.vertex._takein(_rotate_xy(vx, vy, px, py, dθ_rad))
        self.angle = new_angle
        _pose_rotation_set(self, new_angle)
        return self

    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        """Uniformly scale Defining geometry about a pivot."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        own = "_pending_scale_store" not in self.__dict__
        if own:
            self.__dict__["_pending_scale_store"] = store
        try:
            if force or self._requires_pull_invalidate():   # every check before any write (SC5)
                self._scale_gate(about, force)
            match self.model:
                case RegularPolygonModel.CENTER_RADIUS:
                    return self._scale_by_center_radius(factor, about=about, force=force)
                case RegularPolygonModel.CENTER_SIDE:
                    return self._scale_by_center_side(factor, about=about, force=force)
                case RegularPolygonModel.VERTEX_SIDE:
                    return self._scale_by_vertex_side(factor, about=about, force=force)
                case _:
                    raise ValueError(f"Unknown regular polygon model: {self.model}")
        finally:
            if own:
                self.__dict__.pop("_pending_scale_store", None)

    @batch_update_attrs('center', 'radius')
    def _scale_by_center_radius(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        store = self.__dict__["_pending_scale_store"]
        px, py = self._pivot_xy(about)
        cx, cy = get_xy(self.center, bare=True)
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )
        self.radius = _bare_num(self.radius) * factor
        if not about_center:
            self.center._takein(_scale_xy(cx, cy, px, py, factor))
        _pose_scale_set(self, store)
        return self

    @batch_update_attrs('center', 'side')
    def _scale_by_center_side(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        store = self.__dict__["_pending_scale_store"]
        px, py = self._pivot_xy(about)
        cx, cy = get_xy(self.center, bare=True)
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )
        self.side = _bare_num(self.side) * factor
        if not about_center:
            self.center._takein(_scale_xy(cx, cy, px, py, factor))
        _pose_scale_set(self, store)
        return self

    @batch_update_attrs('vertex', 'side')
    def _scale_by_vertex_side(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        store = self.__dict__["_pending_scale_store"]
        px, py = self._pivot_xy(about)
        vx, vy = get_xy(self.vertex, bare=True)
        self.vertex._takein(_scale_xy(vx, vy, px, py, factor))
        self.side = _bare_num(self.side) * factor
        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        if self.model is RegularPolygonModel.VERTEX_SIDE:
            _ensure_writable(self.vertex, "scale_by", force=force,
                             pivot=self._pivot_xy(about) if pivot is None else pivot)
            _ensure_writable(self["side"], "scale_by", force=force)
            return
        size = "radius" if self.model is RegularPolygonModel.CENTER_RADIUS else "side"
        _ensure_writable(self[size], "scale_by", force=force)
        if about is not None:
            px, py = self._pivot_xy(about) if pivot is None else pivot
            cx, cy = get_xy(self.center, bare=True)
            if not (_near_pivot(px, py, cx, cy)):
                _ensure_writable(self.center, "scale_by", force=force, pivot=(px, py))

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'RegularPolygon':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)


class RegularPolygon(_RadialPolygon):
    """
    Regular (equilateral, equiangular) n-gon: a Polygon subclass whose N vertices are always
    Derivate, computed from center/radius-or-side/angle + a fixed vertex count `n`.

    `angle` is always the direction from center to vertex[0] (degrees, 0 = +x axis); vertices
    proceed counter-clockwise from there (vertex[i] at angle + i * 360/n), matching Polygon's
    positive-signed_area convention. `radius` is the circumradius (center-to-vertex distance,
    per project convention).

    Models:
      - CENTER_RADIUS: center, radius, angle are Defining. Derivate: side (chord length).
      - CENTER_SIDE: center, side, angle are Defining. Derivate: radius.
      - VERTEX_SIDE: vertex (= vertex[0]'s world position), side, angle are Defining.
        Derivate: center (= vertex - radius * (cos(angle), sin(angle))), radius.

    `n` (vertex count, >= 3) is a fixed, non-reactive constructor argument -- like Polygon's
    vertex count, it never changes over the shape's life. ``RegularPolygon()`` defaults to
    ``n=6`` with a visible hexagon at the design center; ``RegularPolygon(n=k)`` uses the
    same pose with that vertex count. Geometry signatures still require an explicit ``n``.

    Reuses Polygon's centroid/signed_area/perimeter_length/points/draw/_move_to unchanged
    (they only read self._vertices / self.centroid); center shadows Polygon's centroid-alias
    property with a real Defining/Derivate ContainerSlot (numerically identical for a regular
    polygon, by symmetry). _move_by/rotate_by/scale_by are overridden to update
    center/radius/side/angle/vertex directly instead of per-vertex, since vertices here are
    always computed outputs.

    Args:
        n: Number of sides (default 6).
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        radius: Center-to-vertex distance.
        angle: Heading in degrees (counter-clockwise). Setting it keeps the point
            the shape was placed by; ``rotate_to`` turns it about its center.
        side: Side length (instead of ``radius``).
        vertex: Position of vertex 0 (with ``side``).
    """

    _CTOR_EXTRA_KEYS = frozenset({"n"})
    _HOME_SIZE_KEYS = frozenset({"radius", "angle", "n"})

    @overload
    def __new__(cls, *, n: int = 6, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'RegularPolygon': ...

    @overload
    def __new__(cls, *, n: int, center: GeneralPoint, radius: float, angle: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'RegularPolygon': ...

    @overload
    def __new__(cls, *, n: int, center: GeneralPoint, side: float, angle: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'RegularPolygon': ...

    @overload
    def __new__(cls, *, n: int, vertex: GeneralPoint, side: float, angle: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'RegularPolygon': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        defaults = getattr(type(self), '_shape_defaults', None) or {}
        if 'n' not in kwargs and 'n' in defaults:
            kwargs['n'] = defaults['n']
        if 'n' not in kwargs:
            kwargs['n'] = 6  # RegularPolygon() / (center=…) → hexagon
        n_raw = kwargs['n']
        # Strict int: int(5.9) used to truncate to 5. bool is an int subclass.
        if isinstance(n_raw, bool) or not isinstance(n_raw, int):
            raise TypeError(f"RegularPolygon n must be an int >= 3, got {n_raw!r}")
        n = n_raw
        if n < 3:
            raise ValueError(f"RegularPolygon requires n >= 3, got {n}")
        self._init_radial(n, kwargs)


class RectModel(Enum):
    CORNER_CORNER = "corner_corner"
    TOP_LEFT_WH = "top_left_wh"
    CENTER_WH = "center_wh"
    POINT_VEC = "point_vec"
    SPINE = "spine"


_RECT_SPINE_ANCHORS = frozenset({"cap", "square", "side_left", "side_right"})

# Each Rect / Box model's Defining inputs (the constructor's sets). A copy
# adopts the source's model; the target names its own inputs for it, so a Rect
# that takes in a Square uses width / height, not the Square's length (D21).
_RECT_MODEL_DEFINING = {
    "corner_corner": ("p1", "p2", "angle"),
    "top_left_wh": ("top_left", "width", "height", "angle"),
    "center_wh": ("center", "width", "height", "angle"),
    "point_vec": ("p1", "vec", "angle"),
    "spine": ("p1", "p2", "height"),
}
_SQUARE_MODEL_DEFINING = {
    "center_wh": ("center", "length", "angle"),
    "top_left_wh": ("top_left", "length", "angle"),
}


# Named points of Rect / Box (Shapes Design — Rect, Named points). Their local
# offsets come from the name half-extents ``a, b``, not from the drawn size.
_RECT_NAMED_POINTS = (
    'top_left', 'top_right', 'bottom_left', 'bottom_right',
    'top_center', 'bottom_center', 'left_center', 'right_center',
    'left_square_center', 'right_square_center',
)


def _rect_name_signs(lx: float, ly: float) -> Tuple[int, int]:
    """Signs that make both name half-extents non-negative now (zero → +1)."""
    return (1 if lx >= 0.0 else -1, 1 if ly >= 0.0 else -1)


def _rect_named_offsets(a: float, b: float) -> Dict[str, Tuple[float, float]]:
    """Local offset of every named point, and of Derivate ``p1`` / ``p2``.

    ``a`` / ``b`` are the signed name half-extents: ``top_right`` is ``(a, b)``
    whatever their signs, so a name stays with its point when the box mirrors.
    End-square centres sit ``|b|`` in from the short walls.
    """
    inset = math.copysign(abs(b), a)
    return {
        'top_left': (-a, b),
        'top_right': (a, b),
        'bottom_left': (-a, -b),
        'bottom_right': (a, -b),
        'top_center': (0.0, b),
        'bottom_center': (0.0, -b),
        'left_center': (-a, 0.0),
        'right_center': (a, 0.0),
        'left_square_center': (-a + inset, 0.0),
        'right_square_center': (a - inset, 0.0),
        'p1': (-a, -b),
        'p2': (a, b),
    }


class _RectNames:
    """Named points shared by ``Rect`` and ``box.Box`` (Shapes Design — Rect, Named points).

    A rect names its corners the first time one is used: the signs that make
    the name half-extents ``a, b`` non-negative *then* are stored in
    ``_name_signs``. p1/p2 and p1+vec rects wait for that first use; the
    size-defined models can never cross, so their signs are ``(1, 1)`` until a
    flip mirrors them. After that, ``top_right`` is the local offset ``(a, b)``
    whatever the signs — each name stays with its point.

    ``_oriented_frame`` stays the drawn box (non-negative extents: paint, hit
    test, collision). The host sets ``_ANGLE_FIELD`` (``angle`` / ``angle``).
    """

    _ANGLE_FIELD = 'angle'

    @staticmethod
    def _oriented_xy(cx: float, cy: float, lx: float, ly: float, ang: float) -> Tuple[float, float]:
        """World point from local (lx, ly) offset about (cx, cy) with rotation degrees."""
        cos_a = math.cos(_rad(ang))
        sin_a = math.sin(_rad(ang))
        return (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)

    def _corner_local(self) -> Tuple[float, float]:
        """CORNER_CORNER: ``p2 − p1`` in the rect's rotated frame (signed)."""
        x1, y1 = get_xy(self.p1, bare=True)
        x2, y2 = get_xy(self.p2, bare=True)
        ang = _bare_num(getattr(self, self._ANGLE_FIELD))
        dx, dy = x2 - x1, y2 - y1
        cos_a = math.cos(_rad(-ang))
        sin_a = math.sin(_rad(-ang))
        return (dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a)

    def _signed_extent(self, w: float, h: float) -> Tuple[float, float]:
        """Signed local extent: ``p2 − p1`` in the frame for p1/p2 and p1+vec,
        else the drawn ``(w, h)`` from ``_oriented_frame``."""
        match self.model:
            case RectModel.CORNER_CORNER:
                return self._corner_local()
            case RectModel.POINT_VEC:
                return (_bare_num(self.vec.x), _bare_num(self.vec.y))
            case _:
                return (w, h)

    def _name_signs_now(self, w: float, h: float) -> Tuple[int, int]:
        """The name signs. The first call names the corners (first use).

        Bare reads of Defining parts only — naming must not warm a cold Derivate.
        """
        signs = self.__dict__.get('_name_signs')
        if signs is None:
            signs = _rect_name_signs(*self._signed_extent(w, h))
            self.__dict__['_name_signs'] = signs
        return signs

    def _freeze_names(self) -> Tuple[int, int]:
        """Name the corners now if nothing has yet; return the name signs."""
        signs = self.__dict__.get('_name_signs')
        if signs is not None:
            return signs
        _cx, _cy, w, h, _ang = self._oriented_frame()
        return self._name_signs_now(w, h)

    def _name_half_extents(self, w: float, h: float) -> Tuple[float, float]:
        """Signed name half-extents ``(a, b)``: ``top_right`` is ``(a, b)`` locally."""
        sx, sy = self._name_signs_now(w, h)
        lx, ly = self._signed_extent(w, h)
        return (sx * lx / 2.0, sy * ly / 2.0)

    def _name_frame(self) -> Tuple[float, float, float, float, float]:
        """``(cx, cy, a, b, ang)``: the drawn centre and angle with the name half-extents."""
        cx, cy, w, h, ang = self._oriented_frame()
        a, b = self._name_half_extents(w, h)
        return (cx, cy, a, b, ang)

    def _effective_name_signs(self) -> Tuple[int, int]:
        """Signs of ``(a, b)``: which way the named right / top point in the drawn frame.

        A copy built from the drawn (non-negative) extents takes these as its
        own name signs, so every named point of the copy sits where ours does.
        """
        _cx, _cy, a, b, _ang = self._name_frame()
        return (-1 if a < 0.0 else 1, -1 if b < 0.0 else 1)

    def _derivate_vec(self, w: float, h: float) -> Tuple[float, float]:
        """Derivate ``vec``: ``p2 − p1`` in the rect's frame, so
        ``p2 == p1 + R(angle) @ vec`` holds on every model (SPINE: the signed
        name extent — its p1/p2 are axis points, not corners)."""
        if self.model == RectModel.CORNER_CORNER:
            return self._corner_local()
        a, b = self._name_half_extents(w, h)
        return (2.0 * a, 2.0 * b)

    def _refresh_live_vec(self) -> None:
        """Rewrite a live Derivate ``vec`` (every ``_update_impl`` calls this)."""
        part = self.__dict__.get('vec')
        if part is None or part._field_type == FieldType.Defining:
            return
        if not part._is_derivate_live():
            return
        _cx, _cy, w, h, _ang = self._oriented_frame()
        part._takein(self._derivate_vec(w, h))

    def _derivate_point_value(self, name: str):
        """Value of the Derivate point / ``vec`` part ``name``, or ``None``.

        A named point here is a use: it names the corners if nothing has yet.
        """
        cx, cy, w, h, ang = self._oriented_frame()
        if name == 'vec':
            return self._derivate_vec(w, h)
        if name == 'p2' and self.model == RectModel.POINT_VEC:
            x1, y1 = get_xy(self.p1, bare=True)
            vx, vy = _bare_num(self.vec.x), _bare_num(self.vec.y)
            return self._oriented_xy(x1, y1, vx, vy, ang)
        if name == 'center':
            return (cx, cy)
        if name in _RECT_NAMED_POINTS or name in ('p1', 'p2'):
            lx, ly = _rect_named_offsets(*self._name_half_extents(w, h))[name]
            return self._oriented_xy(cx, cy, lx, ly, ang)
        return None

    def _apply_oriented_corners(self, cx: float, cy: float, w: float, h: float, ang: float) -> None:
        """Write live Derivate named points, Derivate ``p1``/``p2`` and ``vec``.

        Derivate ``p1``/``p2`` are the named ``bottom_left`` / ``top_right``.
        Skips Defining parts, unregistered slots, and cold Derivates — and names
        nothing unless a named point is live (naming happens at first use, not
        at the first update).
        """
        offsets = None
        for name in _RECT_NAMED_POINTS + ('p1', 'p2'):
            if name == 'p2' and self.model == RectModel.POINT_VEC:
                # Already written as p1 + oriented vec (signed components).
                continue
            part = self.__dict__.get(name)
            if part is None or part._field_type == FieldType.Defining:
                continue
            if not part._is_derivate_live():
                continue
            if offsets is None:
                offsets = _rect_named_offsets(*self._name_half_extents(w, h))
            lx, ly = offsets[name]
            part._takein(self._oriented_xy(cx, cy, lx, ly, ang))
        self._refresh_live_vec()


class _RectFrame:
    """The oriented-frame model shared by ``Rect`` (a Shape) and ``Box`` (a
    measuring Container): construction models, ``_oriented_frame``, Derivate
    materialization and the per-model ``_update_impl_*``. Box used to carry a
    near-copy of all of it, and the copies drifted (Box's ``top_left`` model
    ignored the corner names). Hooks: ``_publish_heading`` (Rect writes its
    pose store; Box has none) and ``_pull_heading`` (Rect's derived-heading
    link; nothing on Box). Uses only ``__dict__`` / ``getattr`` patterns that
    work on a slotted Shape and on a closed surface alike.
    """

    __slots__ = ()

    def _publish_heading(self, ang: float) -> None:
        """After an update: Rect keeps its pose store in step (it overrides)."""

    def _pull_heading(self) -> None:
        """A pending derived-heading link (Rect, via _DerivedRotationRoute)."""

    def _wh_signed(self) -> Tuple[float, float]:
        """Signed Defining ``(width, height)``. On a Square ``length`` is Defining
        and ``width`` / ``height`` are Derivate mirrors — read ``length`` (D3)."""
        defining = getattr(self, '_defining_part_names', None)
        if defining is not None and 'length' in defining and 'width' not in defining:
            s = _bare_num(self.length)
            return s, s
        return _bare_num(self.width), _bare_num(self.height)

    def _take_frame_parts(self, other) -> None:
        """``<<`` / ``@=`` after ``_adopt_model_of``: the source's Defining
        inputs for the model, one body for Rect and Box (they were copies)."""
        match self.model:
            case RectModel.CORNER_CORNER:
                self.p1._takein(other.p1)
                self.p2._takein(other.p2)
                _init_scalar(self, 'angle', other.angle)
            case RectModel.TOP_LEFT_WH:
                self.top_left._takein(other.top_left)
                _init_scalar(self, 'width', other.width)
                _init_scalar(self, 'height', other.height)
                _init_scalar(self, 'angle', other.angle)
            case RectModel.CENTER_WH:
                self.center._takein(other.center)
                _init_scalar(self, 'width', other.width)
                _init_scalar(self, 'height', other.height)
                _init_scalar(self, 'angle', other.angle)
            case RectModel.POINT_VEC:
                self.p1._takein(other.p1)
                self.vec._takein(other.vec)
                _init_scalar(self, 'angle', other.angle)
            case RectModel.SPINE:
                self.p1._takein(other.p1)
                self.p2._takein(other.p2)
                _init_scalar(self, 'height', other.height)
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")

    def _rotate_frame(self, dθ_deg: float, *, about, force: bool) -> float:
        """The one ``rotate_by`` body of Rect and Box: every model's Defining
        parts turned about the pivot, each gated with ``pivot=`` (a linked part
        on the pivot is not written, so it may stay linked). Returns the new
        heading. Box kept a copy that drifted (no ``pivot=``, so a linked
        corner on the pivot was refused on Box and allowed on Rect: review
        2026-10-09 S7-3)."""
        dθ_rad = _rad(dθ_deg)
        px, py = self._pivot_xy(about)
        cx, cy = self._center_xy()
        # The heading from Defining inputs (never wakes a Derivate ``angle``).
        new_angle = float(self._oriented_frame()[4]) + dθ_deg
        about_center = (about is None) or _near_pivot(px, py, cx, cy)
        pivot = (px, py)

        match self.model:
            case RectModel.CORNER_CORNER:
                _ensure_writable(self["angle"], "rotate_by", force=force)
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "rotate_by", force=force, pivot=pivot)
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_rotate_xy(x1, y1, px, py, dθ_rad))
                self.p2._takein(_rotate_xy(x2, y2, px, py, dθ_rad))
                self.angle = new_angle
            case RectModel.TOP_LEFT_WH:
                _ensure_writable(self["angle"], "rotate_by", force=force)
                _ensure_writable(self.top_left, "rotate_by", force=force, pivot=pivot)
                # The named top_left (a flip or a copy can mirror the names).
                tl = self._top_left_offset(*self._wh_signed())
                if not about_center:
                    cx, cy = _rotate_xy(cx, cy, px, py, dθ_rad)
                self.top_left._takein(self._oriented_xy(cx, cy, *tl, new_angle))
                self.angle = new_angle
            case RectModel.CENTER_WH:
                _ensure_writable(self["angle"], "rotate_by", force=force)
                if not about_center:
                    _ensure_writable(self.center, "rotate_by", force=force, pivot=pivot)
                    self.center._takein(_rotate_xy(cx, cy, px, py, dθ_rad))
                self.angle = new_angle
            case RectModel.POINT_VEC:
                _ensure_writable(self["angle"], "rotate_by", force=force)
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=pivot)
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_rotate_xy(x1, y1, px, py, dθ_rad))
                self.angle = new_angle
            case RectModel.SPINE:
                # angle is Derivate (from p1->p2): turning p1 / p2 turns it.
                _ensure_writable(self.p1, "rotate_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "rotate_by", force=force, pivot=pivot)
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_rotate_xy(x1, y1, px, py, dθ_rad))
                self.p2._takein(_rotate_xy(x2, y2, px, py, dθ_rad))
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")
        return new_angle

    def _init_model(self, signature: str, kwargs: Dict[str, Any]) -> None:
        """The construction models (Rect and Box share them)."""
        match signature:
            case "corner_corner" | "corner_corner_angle":
                self.model = RectModel.CORNER_CORNER
                self._set_defining_parts('p1', 'p2', 'angle')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    _init_composite(self.p2, kwargs['p2'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "top_left_wh" | "top_left_wh_angle":
                self.model = RectModel.TOP_LEFT_WH
                self._set_defining_parts('top_left', 'width', 'height', 'angle')
                with self._batch_update():
                    _init_composite(self.top_left, kwargs['top_left'])
                    _init_scalar(self, 'width', kwargs['width'])
                    _init_scalar(self, 'height', kwargs['height'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "center_wh" | "center_wh_angle":
                self.model = RectModel.CENTER_WH
                self._set_defining_parts('center', 'width', 'height', 'angle')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _init_scalar(self, 'width', kwargs['width'])
                    _init_scalar(self, 'height', kwargs['height'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "point_vec" | "point_vec_angle":
                self.model = RectModel.POINT_VEC
                self._set_defining_parts('p1', 'vec', 'angle')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    _init_composite(self.vec, kwargs['vec'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "spine":
                anchor = kwargs['anchor']
                if anchor not in _RECT_SPINE_ANCHORS:
                    raise ValueError(
                        f"anchor must be one of {sorted(_RECT_SPINE_ANCHORS)}, got {anchor!r}"
                    )
                # height is a magnitude slot: _init_scalar raises on a bad
                # number and links a formula. Do not float() it first.
                self._anchor = anchor
                self.model = RectModel.SPINE
                self._set_defining_parts('p1', 'p2', 'height')
                with self._batch_update():
                    _init_composite(self.p1, kwargs['p1'])
                    _init_composite(self.p2, kwargs['p2'])
                    _init_scalar(self, 'height', kwargs['height'])

            case _:
                raise ValueError(f"Unknown signature: {signature}")

    def _defining_names_for(self, model) -> Optional[Tuple[str, ...]]:
        return _RECT_MODEL_DEFINING.get(model.value)

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark which parts are Defining for this model; all others are Derivate.

        Only touches already-materialized slots — cold Derivates stay unregistered
        until first access or link (lazy ContainerSlot).
        """
        self._mark_defining_parts(*defining, catalog=self._PART_NAMES)

    def _top_left_offset(self, w: float, h: float) -> Tuple[float, float]:
        """Local offset of the named ``top_left`` for a size-defined model.

        ``(-w/2, +h/2)`` until a flip mirrors the names. Width and height are
        magnitudes here, so the signs never need first-use naming.
        """
        sx, sy = self.__dict__.get('_name_signs') or (1, 1)
        return (-sx * w / 2.0, sy * h / 2.0)

    def _oriented_frame(self) -> Tuple[float, float, float, float, float]:
        """Return (cx, cy, w, h, ang) from Defining inputs for the active model.

        ``w`` / ``h`` are the drawn (non-negative) extents: paint, hit test and
        collision read this. Named points read ``_name_half_extents`` instead.
        """
        match self.model:
            case RectModel.CORNER_CORNER:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                ang = _bare_num(self.angle)
                lx, ly = self._corner_local()
                return (cx, cy, abs(lx), abs(ly), ang)
            case RectModel.TOP_LEFT_WH:
                ang = _bare_num(self.angle)
                defining = getattr(self, '_defining_part_names', None)
                if defining is not None and 'length' in defining and 'width' not in defining:
                    w = h = _bare_num(self.length)
                else:
                    w = _bare_num(self.width)
                    h = _bare_num(self.height)
                tlx, tly = get_xy(self.top_left, bare=True)
                # center = top_left - R(angle) @ (named top_left offset)
                ox, oy = self._oriented_xy(0.0, 0.0, *self._top_left_offset(w, h), ang)
                # Draw / hit use positive extents (scale_by(-1) must stay visible).
                return (tlx - ox, tly - oy, abs(w), abs(h), ang)
            case RectModel.CENTER_WH:
                cx, cy = get_xy(self.center, bare=True)
                ang = _bare_num(self.angle)
                # Square: length is Defining; width/height are Derivate mirrors.
                defining = getattr(self, '_defining_part_names', None)
                if defining is not None and 'length' in defining and 'width' not in defining:
                    L = abs(_bare_num(self.length))
                    return (cx, cy, L, L, ang)
                return (
                    cx, cy,
                    abs(_bare_num(self.width)),
                    abs(_bare_num(self.height)),
                    ang,
                )
            case RectModel.POINT_VEC:
                x1, y1 = get_xy(self.p1, bare=True)
                vx, vy = _bare_num(self.vec.x), _bare_num(self.vec.y)
                ang = _bare_num(self.angle)
                # p1 is oriented local-BL; vec is local (width, height) extent.
                cx, cy = self._oriented_xy(x1, y1, vx / 2.0, vy / 2.0, ang)
                return (cx, cy, abs(vx), abs(vy), ang)
            case RectModel.SPINE:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                h = abs(_bare_num(self.height))
                vx, vy = x2 - x1, y2 - y1
                d = math.hypot(vx, vy)
                # The heading keeps full turns: unwrapped to the pose store (like Line).
                acc = float(getattr(self, '_rotation', 0.0) or 0.0)
                ang = _unwrap_deg(_deg(math.atan2(vy, vx)), acc) if d > 0 else acc
                mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                if d > 0:
                    nx, ny = -vy / d, vx / d  # left-normal of p1→p2
                else:
                    nx, ny = 0.0, 0.0
                anchor = self._anchor
                if anchor == "cap":
                    cx, cy = mx, my
                    w = d
                elif anchor == "square":
                    cx, cy = mx, my
                    w = d + h
                elif anchor == "side_left":
                    cx = mx + nx * h / 2.0
                    cy = my + ny * h / 2.0
                    w = d
                elif anchor == "side_right":
                    cx = mx - nx * h / 2.0
                    cy = my - ny * h / 2.0
                    w = d
                else:
                    raise ValueError(f"Unknown spine anchor: {anchor!r}")
                return (cx, cy, w, h, ang)
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")

    def _materialize_derivate_part(self, name: str) -> None:
        """Compute and write one Derivate part (called on first access / link)."""
        self._pull_heading()
        slot = self._field_slots().get(name)
        if isinstance(slot, ScalarSlot):
            if not self._field_is_derivate(name, slot):
                return
            cx, cy, w, h, ang = self._oriented_frame()
            with self._no_update():
                if name == 'width':
                    self.width = w
                elif name == 'height':
                    self.height = h
                elif name == 'angle':
                    self.angle = ang
            return
        part = self.__dict__.get(name)
        if part is None or part._field_type == FieldType.Defining:
            return
        value = self._derivate_point_value(name)
        if value is None:
            return
        with self._no_update():
            part._takein(value)

    def _update_impl(self) -> None:
        match self.model:
            case RectModel.CORNER_CORNER:
                self._update_impl_corner_corner()
            case RectModel.TOP_LEFT_WH:
                self._update_impl_top_left_wh()
            case RectModel.CENTER_WH:
                self._update_impl_center_wh()
            case RectModel.POINT_VEC:
                self._update_impl_point_vec()
            case RectModel.SPINE:
                self._update_impl_spine()
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")

    @batch_update_attrs(
        'width', 'height', 'center', 'vec',
        'top_left', 'top_right', 'bottom_left', 'bottom_right',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )
    def _update_impl_corner_corner(self) -> None:
        """p1/p2 are oriented opposite corners; angle orients the local frame."""
        cx, cy, w, h, ang = self._oriented_frame()
        self._takein_live_derivate('width', w)
        self._takein_live_derivate('height', h)
        self._takein_live_derivate('center', (cx, cy))
        self._apply_oriented_corners(cx, cy, w, h, ang)
        self._publish_heading(ang)

    @batch_update_attrs(
        'p1', 'p2', 'center', 'vec',
        'top_right', 'bottom_left', 'bottom_right',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )
    def _update_impl_top_left_wh(self) -> None:
        """top_left (world TL), width, height, angle → center and all corners."""
        cx, cy, w, h, ang = self._oriented_frame()
        self._takein_live_derivate('center', (cx, cy))
        self._apply_oriented_corners(cx, cy, w, h, ang)
        self._publish_heading(ang)

    @batch_update_attrs(
        'p1', 'p2', 'vec',
        'top_left', 'top_right', 'bottom_left', 'bottom_right',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )
    def _update_impl_center_wh(self) -> None:
        """center, width, height, angle → oriented corners (incl. Derivate p1/p2)."""
        cx, cy, w, h, ang = self._oriented_frame()
        self._apply_oriented_corners(cx, cy, w, h, ang)
        self._publish_heading(ang)

    @batch_update_attrs(
        'p2', 'width', 'height', 'center',
        'top_left', 'top_right', 'bottom_left', 'bottom_right',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )
    def _update_impl_point_vec(self) -> None:
        """p1 + local vec + angle define the rect; p2 is the oriented opposite corner."""
        x1, y1 = get_xy(self.p1, bare=True)
        vx, vy = _bare_num(self.vec.x), _bare_num(self.vec.y)
        ang = _bare_num(self.angle)
        self._takein_live_derivate('p2', self._oriented_xy(x1, y1, vx, vy, ang))

        cx, cy, w, h, ang = self._oriented_frame()
        self._takein_live_derivate('width', w)
        self._takein_live_derivate('height', h)
        self._takein_live_derivate('center', (cx, cy))
        self._apply_oriented_corners(cx, cy, w, h, ang)
        self._publish_heading(ang)

    @batch_update_attrs(
        'angle', 'width', 'center', 'vec',
        'top_left', 'top_right', 'bottom_left', 'bottom_right',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )
    def _update_impl_spine(self) -> None:
        """p1, p2, height (+ plain ``anchor``) define an oriented rectangle.

        anchor="cap": p1, p2 are midpoints of the short walls.
        anchor="square": p1, p2 are centers of the height×height end squares
        (Derivate left_square_center / right_square_center).
        anchor="side_left"/"side_right": p1, p2 are corners of one long edge;
        the box extends left/right of p1→p2. Derivate width is the along-axis
        extent; Defining height is the cross-axis magnitude.

        No ``_publish_heading``: the pose store is the turn reference the
        heading unwraps to, and only verbs move it (as on a p1/p2 Line).
        Written back here, it counted turns only across the updates that ran,
        so the same writes read 204.78 warm and -155.22 cold.
        """
        cx, cy, w, h, ang = self._oriented_frame()
        self._takein_live_derivate('angle', ang)
        self._takein_live_derivate('width', w)
        self._takein_live_derivate('center', (cx, cy))
        self._apply_oriented_corners(cx, cy, w, h, ang)


def _mirror_rotation_store(obj, axis: str) -> None:
    """The flip convention on the raw pose store (no notify: the caller's
    batch publishes the heading it derives)."""
    r = float(obj._rotation)
    object.__setattr__(obj, '_rotation', (180.0 - r) if axis == "x" else -r)


class Rect(_DerivedRotationRoute, _RectFrame, _RectNames, Shape):
    """
    Oriented rectangle with multi-model constructors (Line-style).

    Models:
      - CORNER_CORNER: p1, p2 are opposite corners, exactly where the author put them
        (a value or a link). angle is the direction of the width side; width and
        height follow from those three and read 0 when the diagonal lies along a side
        (a legal collapsed box). rotate_by / rotate_to turn the box with its corners;
        writing or linking angle keeps the corners and changes the size.
      - TOP_LEFT_WH: top_left is the world position of the local top-left corner (-w/2, +h/2);
        width, height are local edge lengths; angle is orientation about center.
      - CENTER_WH: center, width, height are Defining; angle orients about center (mirrors
        TOP_LEFT_WH's Derivate set, using center instead of top_left as the position anchor).
        Derivate p1/p2 track oriented opposite corners (same loci as bottom_left / top_right).
      - POINT_VEC: p1, vec, angle are Defining. p1 stays where the author put it;
        vec is the signed local (width, height) extent along the rotated sides
        (not a world-axis delta — that is Line(p1=, vec=)). p2 = p1 + R(angle) @ vec.
        The drawn frame uses abs of each component.
      - SPINE: p1, p2, height are Defining (no separate angle -- orientation comes from
        p1->p2). Required plain ``anchor`` selects how p1/p2 sit on the rectangle:
          * "cap": p1, p2 are midpoints of the short walls (caps).
          * "square": p1, p2 are centers of the height×height end squares
            (same loci as Derivate left_square_center / right_square_center).
          * "side_left": p1, p2 are corners of one long edge; box extends left of p1→p2.
          * "side_right": same, box extends right of p1→p2.
        height is a non-negative cross-axis magnitude. Derivate width is the along-axis
        extent (d for cap/side_*; d+height for square). Matches the width=local-x /
        height=local-y rule of the frame-anchored models.

    Named points (top_left, top_right, …, top_center, …): a rect names its
    corners the first time one is used, as they look then (in its own rotated
    frame). From then on each name stays with its point through drags, link
    updates, rotations, scales and flips — p1 keeps being bottom_left even when
    it is dragged past p2. Only p1/p2 and p1+vec rects can cross; the other
    models start visual and change names only when a flip mirrors them.

    Optional angle defaults to 0 when omitted from the constructor.
    Plain (non-reactive) ``corner_radius`` (default 0) rounds paint and the
    pointer fill via ``drawRRect``. Collision and linked corners stay the
    sharp box.


    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        p1: One corner (with ``p2``; or a spine end with ``p2`` + ``height`` +
            ``anchor``).
        p2: The opposite corner.
        angle: Heading in degrees (counter-clockwise). Setting it keeps the point
            the shape was placed by; ``rotate_to`` turns it about its center.
        corner_radius: Rounded corners (0 = sharp).
        top_left: Top-left corner (with ``width`` / ``height``).
        width: Width in design units.
        height: Height in design units.
        vec: From ``p1``: the diagonal as a vector.
        anchor: With ``p1`` + ``p2`` + ``height``: how the ends sit — ``"cap"`` ·
            ``"square"`` · ``"side_left"`` · ``"side_right"``.
    """

    p1 = ContainerSlot(Point)
    p2 = ContainerSlot(Point)
    top_left = ContainerSlot(Point)
    top_right = ContainerSlot(Point, FieldType.Derivate)
    bottom_left = ContainerSlot(Point, FieldType.Derivate)
    bottom_right = ContainerSlot(Point, FieldType.Derivate)
    vec = ContainerSlot(Vec2, FieldType.Derivate)
    width = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    height = ScalarSlot(magnitude=True, hint=HINT_EXTENT)
    angle = ScalarSlot()
    center = ContainerSlot(Point, FieldType.Derivate)
    top_center = ContainerSlot(Point, FieldType.Derivate)
    bottom_center = ContainerSlot(Point, FieldType.Derivate)
    left_center = ContainerSlot(Point, FieldType.Derivate)
    right_center = ContainerSlot(Point, FieldType.Derivate)
    left_square_center = ContainerSlot(Point, FieldType.Derivate)
    right_square_center = ContainerSlot(Point, FieldType.Derivate)

    _CTOR_EXTRA_KEYS = frozenset({"corner_radius"})

    # Home model = CENTER_WH (same as Rect()).
    _HOME_KEYS = frozenset({"center", "width", "height"})
    _HOME_OPTIONAL_KEYS = frozenset({"angle"})
    _HOME_SIZE_KEYS = frozenset({"width", "height", "angle"})

    _CONSTRUCTOR_SIGNATURES = [
        ("corner_corner",        {"p1", "p2"}),
        ("corner_corner_angle",  {"p1", "p2", "angle"}),
        ("top_left_wh",          {"top_left", "width", "height"}),
        ("top_left_wh_angle",    {"top_left", "width", "height", "angle"}),
        ("center_wh",            {"center", "width", "height"}),
        ("center_wh_angle",      {"center", "width", "height", "angle"}),
        ("point_vec",            {"p1", "vec"}),
        ("point_vec_angle",      {"p1", "vec", "angle"}),
        ("spine",                {"p1", "p2", "height", "anchor"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        (cx, cy), unit = _default_pose()
        return {
            "center": (cx, cy),
            "width": 2.0 * unit,
            "height": 1.25 * unit,
        }

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, p2: GeneralPoint, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    @overload
    def __new__(cls, *, top_left: GeneralPoint, width: float, height: float, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, width: float, height: float, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, vec: Vec2, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    @overload
    def __new__(cls, *, p1: GeneralPoint, p2: GeneralPoint, height: float, anchor: str, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Rect': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        from .box import apply_box_to_shape_kwargs
        box_names = apply_box_to_shape_kwargs("Rect", kwargs, family="fill")
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs,
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )
        super().__init__(**base_params)

        self._anchor = None  # set only for SPINE
        self._init_corner_radius(kwargs)

        self._init_model(signature, kwargs)

        if box_names is not None:
            # box= places the rect into a region *and* takes its names.
            self.__dict__['_name_signs'] = box_names

        if self.model == RectModel.SPINE:
            # Angle is Derivate — compute from Defining p1→p2 (A4 / cold-Derivate).
            x1, y1 = get_xy(self.p1, bare=True)
            x2, y2 = get_xy(self.p2, bare=True)
            _pose_rotation_set(
                self,
                _deg(math.atan2(y2 - y1, x2 - x1)) if (x1 != x2 or y1 != y2) else 0.0,
            )
        else:
            _pose_rotation_set(self, _bare_num(self.angle))

    _PART_NAMES = (
        'p1', 'p2', 'top_left', 'top_right', 'bottom_left', 'bottom_right', 'vec',
        'width', 'height', 'angle', 'center',
        'top_center', 'bottom_center', 'left_center', 'right_center',
        'left_square_center', 'right_square_center',
    )

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """``(rot, scale, ang, w, h)`` from Defining ``_oriented_frame`` (cold-safe).

        SPINE / TOP_LEFT keep Derivate ``angle`` / ``width`` cold until accessed.
        Pose keys must not read those slots' defaults (0) or scale/rotate leaves
        a stale collision key vs a peer that materialized Derivates via ``@=``.
        """
        try:
            rot = float(self._rotation)
        except Exception:
            rot = 0.0
        try:
            scale = float(self._scale)
        except Exception:
            scale = 1.0
        _cx, _cy, w, h, ang = self._oriented_frame()
        return (rot, scale, float(ang), float(w), float(h))

    def _heading_driven_parts(self) -> Tuple:
        # What rotate_by writes where ``angle`` is derived (the spine's ends).
        if self.model == RectModel.SPINE:
            return (self.p1, self.p2)
        return ()

    def _init_corner_radius(self, kwargs: Dict[str, Any]) -> None:
        """Paint-only radius; Square must call this (it skips Rect.__init__)."""
        self.corner_radius = kwargs.get('corner_radius', 0.0)

    @property
    def corner_radius(self) -> float:
        """Rounded-corner radius in design units (0 = sharp). A plain number (no ``@=`` link)."""
        return self._corner_radius

    @corner_radius.setter
    def corner_radius(self, value: float) -> None:
        # Paint only — a lambda must not be stored (it used to crash at draw).
        if callable(value) and not isinstance(value, type):
            raise CallableAssignError(
                _ink_link_forbidden_message(self, "corner_radius")
            )
        self._corner_radius = fixed_magnitude(value, "corner_radius")

    def _takein_impl(self, other: 'Rect') -> None:
        """Copy only the defining attributes for the current model.

        The names travel too (a copy is a use): every named point of the copy
        sits where the source's does.
        """
        # Read the source before the first write (SC1: a Box has no corner
        # radius, and the raise came after the model switch: a 0 × 0 rect).
        # The raw name-sign store below is that first write: a destroyed
        # rect refuses before it (sentinel I-atomic: the dead rect took the
        # source's signs, then raised).
        _refuse_if_destroyed(self, "set")
        signs = other._freeze_names()
        anchor = getattr(other, "_anchor", None)          # SPINE only (None elsewhere)
        corner = getattr(other, "_corner_radius", self._corner_radius)   # a Box keeps ours
        self.__dict__['_name_signs'] = signs
        self._adopt_model_of(other)
        self._anchor = anchor
        self._corner_radius = corner
        self._take_frame_parts(other)

    # The pose store follows every update. Bound directly (no extra frame on a
    # per-update path): self._publish_heading(ang) is _pose_rotation_publish(self, ang),
    # which skips the linked-pose refusal (the update is the link's own echo).
    _publish_heading = _pose_rotation_publish

    @property
    def corners(self) -> List['Point']:
        """The four corners ``[top_left, top_right, bottom_left, bottom_right]`` as Points.

        A use: names the corners if nothing has yet (see Named points).
        """
        return [self.top_left, self.top_right, self.bottom_left, self.bottom_right]

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT):
        """Draw via local-frame CTM (Defining pose); world Derivate corners stay lazy."""
        cx, cy, w, h, ang = self._oriented_frame()
        skia_canvas.save()
        skia_canvas.translate(cx, cy)
        if ang:
            skia_canvas.rotate(ang)
        rect = skia.Rect.MakeLTRB(-w / 2.0, -h / 2.0, w / 2.0, h / 2.0)
        r = self._corner_radius
        if r > 0.0:
            rx = min(r, w * 0.5, h * 0.5)
            rrect = skia.RRect.MakeRectXY(rect, rx, rx)
            skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
            if skia_fill_paint:
                skia_canvas.drawRRect(rrect, skia_fill_paint)
            skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
            if skia_line_paint:
                skia_canvas.drawRRect(rrect, skia_line_paint)
        else:
            skia_fill_paint = self._to_skia_fill_paint() if fill_paint is _STYLE_PAINT else fill_paint
            if skia_fill_paint:
                skia_canvas.drawRect(rect, skia_fill_paint)
            skia_line_paint = self._to_skia_line_paint() if stroke_paint is _STYLE_PAINT else stroke_paint
            if skia_line_paint:
                skia_canvas.drawRect(rect, skia_line_paint)

        skia_canvas.restore()

    def _hit_test_xy(self, x: float, y: float) -> bool:
        """Hit-test the oriented box, or the rounded fill when ``corner_radius`` > 0."""
        cx, cy, w, h, ang = self._oriented_frame()
        if w == 0.0 or h == 0.0:
            return False
        dx = x - cx
        dy = y - cy
        if ang:
            cos_a = math.cos(_rad(-ang))
            sin_a = math.sin(_rad(-ang))
            lx = dx * cos_a - dy * sin_a
            ly = dx * sin_a + dy * cos_a
        else:
            lx, ly = dx, dy
        # Rotated corners land ~1 ulp outside the exact half-extent.
        slack = 1e-6
        hw, hh = w * 0.5, h * 0.5
        ax, ay = abs(lx), abs(ly)
        r = self._corner_radius
        if r <= 0.0:
            return ax <= hw + slack and ay <= hh + slack
        # Same clamp as drawRRect. The cut corner is a pointer miss;
        # collision stays this oriented box.
        rx = min(r, hw, hh)
        ix, iy = hw - rx, hh - rx
        if ax <= ix + slack and ay <= hh + slack:
            return True
        if ay <= iy + slack and ax <= hw + slack:
            return True
        dx, dy = ax - ix, ay - iy
        limit = rx + slack
        return dx * dx + dy * dy <= limit * limit

    def _parts_written_by_drag(self) -> Tuple[Container, ...]:
        match self.model:
            case RectModel.CORNER_CORNER | RectModel.SPINE:
                return (self.p1, self.p2)
            case RectModel.TOP_LEFT_WH:
                return (self.top_left,)
            case RectModel.CENTER_WH:
                return (self.center,)
            case RectModel.POINT_VEC:
                return (self.p1,)
            case _:
                return ()

    def _parts_written_by_wheel_rotate(self) -> Tuple[Container, ...]:
        # Matches rotate_by(..., about=None) — center pivot.
        match self.model:
            case RectModel.CORNER_CORNER:
                return (self.p1, self.p2, self["angle"])
            case RectModel.CENTER_WH:
                return (self["angle"],)
            case RectModel.POINT_VEC:
                return (self.p1, self["angle"])
            case RectModel.TOP_LEFT_WH:
                return (self.top_left, self["angle"])
            case RectModel.SPINE:
                return (self.p1, self.p2)
            case _:
                return ()

    def _clone_geometry(self, **kwargs) -> 'Rect':
        # Same model, same Defining values: every part keeps its identity
        # (a CENTER_WH rebuild made p1 / p2 Derivates on other corners).
        cls = type(self)
        rot = _bare_num(self.angle)
        match self.model:
            case RectModel.SPINE:
                geometry = dict(p1=get_xy(self.p1, bare=True), p2=get_xy(self.p2, bare=True),
                                height=_bare_num(self.height), anchor=self._anchor)
            case RectModel.CORNER_CORNER:
                geometry = dict(p1=get_xy(self.p1, bare=True), p2=get_xy(self.p2, bare=True),
                                angle=rot)
            case RectModel.POINT_VEC:
                geometry = dict(p1=get_xy(self.p1, bare=True), vec=get_xy(self.vec, bare=True),
                                angle=rot)
            case RectModel.TOP_LEFT_WH:
                geometry = dict(top_left=get_xy(self.top_left, bare=True),
                                width=_bare_num(self.width), height=_bare_num(self.height),
                                angle=rot)
            case _:
                cx, cy, w, h, ang = self._oriented_frame()
                geometry = dict(center=(cx, cy), width=w, height=h, angle=ang)
        clone = cls(corner_radius=self._corner_radius, **geometry, **kwargs)
        # The clone's extents may be magnitudes: carry the names as signs.
        signs = (self._effective_name_signs() if self.model == RectModel.CENTER_WH
                 else self._freeze_names())
        clone._adopt_names(signs)
        return clone

    def _adopt_names(self, signs: Tuple[int, int]) -> None:
        """Take another rect's names (clone / copy). Refreshes live parts."""
        if self.__dict__.get('_name_signs') == signs:
            return
        self.__dict__['_name_signs'] = signs
        self.update()

    def _mirror_geometry(self, axis: str, *, force: bool = False) -> None:
        """Mirror about ``center``: every named point lands on its mirror image.

        ``angle`` keeps the flip convention (x: ``180 − θ``, y: ``−θ``). Under
        it a true mirror keeps the name half-extent ``a`` and negates ``b``:
        p1/p2 do that by moving, p1+vec by negating ``vec.y`` (both axes), and
        the size-defined models by flipping the stored name sign. A SPINE's
        side anchor swaps: a mirror changes handedness.
        """
        cx, cy = self._center_xy()

        def mirrored(pt) -> Tuple[float, float]:
            x, y = get_xy(pt, bare=True)
            return (2.0 * cx - x, y) if axis == "x" else (x, 2.0 * cy - y)

        def turned(ang: float) -> float:
            return (180.0 - ang) if axis == "x" else -ang

        model = self.model
        # Defining points only — reading a Derivate one would warm it (D3).
        match model:
            case RectModel.CORNER_CORNER | RectModel.SPINE:
                points = (self.p1, self.p2)
            case RectModel.POINT_VEC:
                points = (self.p1,)
            case RectModel.TOP_LEFT_WH:
                points = (self.top_left,)
            case _:
                points = ()
        spine = model is RectModel.SPINE
        point_vec = model is RectModel.POINT_VEC
        for pt in points:
            _ensure_writable(pt, "flip", force=force, pivot=(cx, cy))
        if not spine:
            _ensure_writable(self["angle"], "flip", force=force)
        if point_vec:
            _ensure_writable(self.vec, "flip", force=force)
        self._freeze_names()            # a write: after every check (SB2a)
        if spine:
            # The spine's heading is unwrapped toward the pose store: give it
            # the mirrored full turn first, so 400 flips to -220, not 500
            # (Q1: the convention applies to the unwrapped value).
            _mirror_rotation_store(self, axis)

        with self._batch_update():
            for pt in points:
                pt._takein(mirrored(pt))
            if not spine:
                self.angle = turned(_bare_num(self.angle))
            if point_vec:
                self.vec.y = -_bare_num(self.vec.y)
            elif spine or model is RectModel.CENTER_WH or model is RectModel.TOP_LEFT_WH:
                sx, sy = self.__dict__['_name_signs']
                self.__dict__['_name_signs'] = (sx, -sy)
            if spine and self._anchor in ("side_left", "side_right"):
                self._anchor = "side_right" if self._anchor == "side_left" else "side_left"
        _pose_rotation_set(self, self._rotation_value())

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Rect':
        """Translate Defining position parts only."""
        if _pose_fast_ok(self, force=force):
            match self.model:
                case RectModel.CENTER_WH:
                    _translate_point_float(self.center, dx, dy)
                    return self
                case RectModel.CORNER_CORNER | RectModel.SPINE:
                    _translate_points_float((self.p1, self.p2), dx, dy)
                    return self
                case RectModel.TOP_LEFT_WH:
                    _translate_point_float(self.top_left, dx, dy)
                    return self
                case RectModel.POINT_VEC:
                    _translate_point_float(self.p1, dx, dy)
                    return self
                case _:
                    raise ValueError(f"Unknown rect model: {self.model}")
        return self._move_by_batched(dx, dy, force=force)

    @batch_update_self()
    def _move_by_batched(self, dx: float, dy: float, *, force: bool = False) -> 'Rect':
        match self.model:
            case RectModel.CORNER_CORNER:
                _ensure_writable(self.p1, "move_by", force=force)
                _ensure_writable(self.p2, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                    self.p2.x += dx
                if dy is not None:
                    self.p1.y += dy
                    self.p2.y += dy
            case RectModel.TOP_LEFT_WH:
                _ensure_writable(self.top_left, "move_by", force=force)
                if dx is not None:
                    self.top_left.x += dx
                if dy is not None:
                    self.top_left.y += dy
            case RectModel.CENTER_WH:
                _ensure_writable(self.center, "move_by", force=force)
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                if dx is not None:
                    cx = cx + float(dx)
                if dy is not None:
                    cy = cy + float(dy)
                self.center._takein((cx, cy))
            case RectModel.POINT_VEC:
                _ensure_writable(self.p1, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                if dy is not None:
                    self.p1.y += dy
            case RectModel.SPINE:
                _ensure_writable(self.p1, "move_by", force=force)
                _ensure_writable(self.p2, "move_by", force=force)
                if dx is not None:
                    self.p1.x += dx
                    self.p2.x += dx
                if dy is not None:
                    self.p1.y += dy
                    self.p2.y += dy
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Rect':
        """Move the rectangle's center to absolute x and/or y.

        CENTER_WH writes the center absolutely (A1). When the shape has no
        pull consumers, skips ``batch_update`` / link scans entirely.
        Non-canonical models translate Defining points in one combined step.
        """
        if self.model == RectModel.CENTER_WH:
            if _pose_fast_ok(self, force=force):
                cx = _bare_attr(self.center.x)
                cy = _bare_attr(self.center.y)
                nx = cx if x is None else float(x)
                ny = cy if y is None else float(y)
                if nx != cx:
                    _takein_xy_float(self.center, x=nx)
                if ny != cy:
                    _takein_xy_float(self.center, y=ny)
                return self
            return self._move_to_center_wh(x, y, force=force)
        cx, cy = self._center_xy()
        dx = None if x is None else float(x) - cx
        dy = None if y is None else float(y) - cy
        if (dx is None or dx == 0.0) and (dy is None or dy == 0.0):
            return self
        return self._move_by(dx, dy, force=force)

    @batch_update_self()
    def _move_to_center_wh(self, x: float, y: float, *, force: bool = False) -> 'Rect':
        _ensure_writable(self.center, "move_to", force=force)
        cx = _bare_attr(self.center.x)
        cy = _bare_attr(self.center.y)
        nx = cx if x is None else float(x)
        ny = cy if y is None else float(y)
        if nx != cx or ny != cy:
            self.center._takein((nx, ny))
        return self

    def rotate_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Rect':
        """Set geometric rotation (degrees) about a pivot (default: center)."""
        target = _finite_deg(value, "rotate_to angle")
        current = self._rotation_value()
        return self.rotate_by(target - current, about=about, force=force)

    def rotate_by(self, angle: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Rect':
        """Rotate about a pivot by angle degrees; updates Defining parts + angle."""
        _refuse_if_destroyed(self, "rotate_by")
        dθ_deg = _finite_deg(angle, "rotate_by angle")
        if dθ_deg == 0.0:
            return self
        if (
            self.model == RectModel.CENTER_WH
            and not force
            and not self._requires_pull_invalidate()
        ):
            px, py = self._pivot_xy(about)
            cx, cy = _bare_attr(self.center.x), _bare_attr(self.center.y)
            about_center = (about is None) or (
                _near_pivot(px, py, cx, cy)
            )
            if about_center:
                new_angle = _bare_num(self.angle) + dθ_deg
                self.angle = new_angle
                _pose_rotation_set(self, new_angle)
                return self
        return self._rotate_by_batched(dθ_deg, about=about, force=force)

    @batch_update_self()
    def _rotate_by_batched(self, dθ_deg: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Rect':
        new_angle = self._rotate_frame(dθ_deg, about=about, force=force)
        _pose_rotation_set(self, new_angle)
        return self

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Rect':
        """Uniformly scale Defining geometry about a pivot."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom

        px, py = self._pivot_xy(about)
        cx, cy = self._center_xy()
        about_center = (about is None) or (
            _near_pivot(px, py, cx, cy)
        )

        if force or self._requires_pull_invalidate():   # nothing linked: nothing refuses
            self._scale_gate(about, force, (px, py))     # every check before any write
        match self.model:
            case RectModel.CORNER_CORNER:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.p2._takein(_scale_xy(x2, y2, px, py, factor))
            case RectModel.TOP_LEFT_WH:
                w0, h0 = self._wh_signed()
                self.width = w0 * factor
                self.height = h0 * factor
                ang = _bare_num(self.angle)
                if about_center:
                    ncx, ncy = cx, cy
                else:
                    ncx, ncy = _scale_xy(cx, cy, px, py, factor)
                # The new size, not a re-read: a Square scales ``length`` only after
                # this call, so ``_wh_signed()`` would still be the old side.
                tl = self._top_left_offset(w0 * factor, h0 * factor)
                self.top_left._takein(self._oriented_xy(ncx, ncy, *tl, ang))
            case RectModel.CENTER_WH:
                w0, h0 = self._wh_signed()
                self.width = w0 * factor
                self.height = h0 * factor
                if about_center:
                    ncx, ncy = cx, cy
                else:
                    ncx, ncy = _scale_xy(cx, cy, px, py, factor)
                self.center._takein((ncx, ncy))
            case RectModel.POINT_VEC:
                x1, y1 = get_xy(self.p1, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.vec.x = _bare_num(self.vec.x) * factor
                self.vec.y = _bare_num(self.vec.y) * factor
            case RectModel.SPINE:
                x1, y1 = get_xy(self.p1, bare=True)
                x2, y2 = get_xy(self.p2, bare=True)
                self.p1._takein(_scale_xy(x1, y1, px, py, factor))
                self.p2._takein(_scale_xy(x2, y2, px, py, factor))
                self.height = _bare_num(self.height) * factor
            case _:
                raise ValueError(f"Unknown rect model: {self.model}")

        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        if pivot is None:
            pivot = self._pivot_xy(about)
        match self.model:
            case RectModel.CORNER_CORNER:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "scale_by", force=force, pivot=pivot)
            case RectModel.TOP_LEFT_WH:
                _ensure_writable(self.top_left, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["width"], "scale_by", force=force)
                _ensure_writable(self["height"], "scale_by", force=force)
            case RectModel.CENTER_WH:
                _ensure_writable(self.center, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["width"], "scale_by", force=force)
                _ensure_writable(self["height"], "scale_by", force=force)
            case RectModel.POINT_VEC:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.vec, "scale_by", force=force)
            case RectModel.SPINE:
                _ensure_writable(self.p1, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self.p2, "scale_by", force=force, pivot=pivot)
                _ensure_writable(self["height"], "scale_by", force=force)

    def scale_to(self, value: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Rect':
        """Set absolute uniform scale about a pivot."""
        return _scale_to_via(self, value, about=about, force=force)


class Square(Rect):
    """
    Square: a Rect subclass constrained to width == height == length.

    Models (each reuses the corner math of the matching Rect model):
      - CENTER_LENGTH: center, length are Defining (built on Rect's CENTER_WH).
      - TOP_LEFT_LENGTH: top_left, length are Defining (built on Rect's TOP_LEFT_WH).

    width/height are always Derivate mirrors of length -- setting them directly raises
    DerivedAttributeError, unlike a plain Rect where they can be Defining. This resolves the
    classic Square-is-not-really-a-Rect (LSP) issue: you cannot independently stretch a
    Square's width or height, only its length.

    move_by/rotate_by/draw are inherited unchanged from Rect (they never touch
    width/height/length). Only scale_by is overridden, to keep length in sync.

    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form.
        length: Side length.
        angle: Heading in degrees (counter-clockwise). Setting it keeps the point
            the shape was placed by; ``rotate_to`` turns it about its center.
        corner_radius: Rounded corners (0 = sharp).
        top_left: Top-left corner (with ``length``).
    """

    length = ScalarSlot(magnitude=True, hint=HINT_EXTENT)

    # Home model = CENTER_LENGTH (same as Square()).
    _HOME_KEYS = frozenset({"center", "length"})
    _HOME_OPTIONAL_KEYS = frozenset({"angle"})
    _HOME_SIZE_KEYS = frozenset({"length", "angle"})

    _CONSTRUCTOR_SIGNATURES = [
        ("center_length",         {"center", "length"}),
        ("center_length_angle",   {"center", "length", "angle"}),
        ("top_left_length",       {"top_left", "length"}),
        ("top_left_length_angle", {"top_left", "length", "angle"}),
    ]

    @classmethod
    def _home_pose_values(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        (cx, cy), unit = _default_pose()
        return {"center": (cx, cy), "length": 1.5 * unit}

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Square': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, length: float, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Square': ...

    @overload
    def __new__(cls, *, top_left: GeneralPoint, length: float, angle: float = 0.0, corner_radius: float = 0.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Square': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        from .box import apply_box_to_shape_kwargs
        box_names = apply_box_to_shape_kwargs(
            "Square", kwargs, family="inscribe", size_keys=("length",),
        )
        base_params, signature = self._extract_common_params_and_signature(
            kwargs=kwargs,
            valid_signatures=self._CONSTRUCTOR_SIGNATURES
        )
        # Bypass Rect.__init__'s own signature dispatch -- Square has its own signatures.
        # Everything else Rect.__init__ sets must be set here too
        # (test_shapes.TestSquare.test_init_sets_what_rect_init_sets).
        Shape.__init__(self, **base_params)
        self._anchor = None  # SPINE only; a Square never is one
        self._init_corner_radius(kwargs)

        match signature:
            case "center_length" | "center_length_angle":
                self.model = RectModel.CENTER_WH
                self._set_defining_parts('center', 'length', 'angle')
                with self._batch_update():
                    _init_composite(self.center, kwargs['center'])
                    _init_scalar(self, 'length', kwargs['length'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case "top_left_length" | "top_left_length_angle":
                self.model = RectModel.TOP_LEFT_WH
                self._set_defining_parts('top_left', 'length', 'angle')
                with self._batch_update():
                    _init_composite(self.top_left, kwargs['top_left'])
                    _init_scalar(self, 'length', kwargs['length'])
                    _init_scalar(self, 'angle', kwargs.get('angle', 0.0))

            case _:
                raise ValueError(f"Unknown signature: {signature}")

        if box_names is not None:
            # box= places the square into a region *and* takes its names.
            self.__dict__['_name_signs'] = box_names

        _pose_rotation_set(self, _bare_num(self.angle))

    def _materialize_derivate_part(self, name: str) -> None:
        """Fill width/height from length (Square), then Rect corner materialize."""
        if name in ('width', 'height'):
            with self._no_update():
                self._update_impl()
            return
        super()._materialize_derivate_part(name)

    def _defining_names_for(self, model) -> Optional[Tuple[str, ...]]:
        return _SQUARE_MODEL_DEFINING.get(model.value)

    def _set_defining_parts(self, *defining: str) -> None:
        """Mark Defining parts; length is Defining, width/height always Derivate.

        Must keep ``length`` in ``_defining_part_names`` so Square depends on it.
        """
        defining = set(defining)
        defining.discard('width')
        defining.discard('height')
        self._mark_defining_parts(
            *defining,
            catalog=self._PART_NAMES + ('length',),
        )

    def _takein_impl(self, other: 'Square') -> None:
        """Copy the Defining parts (anchor point, length, angle).

        Not Rect's copy: width / height are Derivate here. (It once called
        ``super()._takein`` — the dispatcher, not the hook — and recursed
        forever; A7 in Testing Design.) The names travel too (a mirrored
        top_left must place the centre the same way). Only a Square: a Rect's
        sides can differ, and it raised AttributeError on ``other.length``."""
        if not isinstance(other, Square):
            raise TypeError(
                f"Square << expected a Square, got {type(other).__name__}: its sides "
                "can differ. Build the Square from the side you want, e.g. "
                "Square(center=rect.center, length=rect.width, angle=rect.angle)."
            )
        self.__dict__['_name_signs'] = other._freeze_names()
        self._adopt_model_of(other)
        self._corner_radius = other._corner_radius
        match self.model:
            case RectModel.CENTER_WH:
                self.center._takein(other.center)
            case RectModel.TOP_LEFT_WH:
                self.top_left._takein(other.top_left)
            case _:
                raise ValueError(f"Unknown square model: {self.model}")
        _init_scalar(self, 'length', other.length)
        _init_scalar(self, 'angle', other.angle)

    def _clone_geometry(self, **kwargs) -> 'Square':
        cls = type(self)
        if self.model == RectModel.TOP_LEFT_WH:
            clone = cls(
                top_left=get_xy(self.top_left, bare=True),
                length=_bare_num(self.length),
                angle=_bare_num(self.angle),
                corner_radius=self._corner_radius,
                **kwargs,
            )
        else:
            clone = cls(
                center=get_xy(self.center, bare=True),
                length=_bare_num(self.length),
                angle=_bare_num(self.angle),
                corner_radius=self._corner_radius,
                **kwargs,
            )
        # Same model, same magnitudes: the names copy as they are. On a
        # TOP_LEFT clone the signs also place the centre from top_left.
        clone._adopt_names(self._freeze_names())
        return clone

    @batch_update_self()
    def _update_impl(self) -> None:
        """Mirror length into width/height, then reuse Rect's corner math unchanged."""
        length_val = _bare_num(self.length)
        self.width = length_val
        self.height = length_val
        super()._update_impl()

    @batch_update_self()
    def scale_by(self, factor: float, *, about: Optional[GeneralPoint] = None, force: bool = False) -> 'Square':
        """Uniformly scale length (and position); reuses Rect's scale_by for the geometry,
        then re-syncs length from the resulting width so it never goes stale."""
        _refuse_if_destroyed(self, "scale_by")
        geom, store = _resolve_scale_apply(self, factor, force=force)
        if geom == 1.0 and store == float(self._scale):
            return self
        factor = geom
        own = "_pending_scale_store" not in self.__dict__
        if own:
            self.__dict__["_pending_scale_store"] = store
        try:
            if force or self._requires_pull_invalidate():   # nothing linked: nothing refuses
                self._scale_gate(about, force)
            super().scale_by(factor, about=about, force=force)
            # Scale the Defining input. Do not re-read Derivate width — a dirty
            # pull would rematerialize it from the still-unscaled length.
            self.length = _bare_num(self.length) * factor
            return self
        finally:
            if own:
                self.__dict__.pop("_pending_scale_store", None)

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        _ensure_writable(self["length"], "scale_by", force=force)
        super()._scale_gate(about, force, pivot)


_TRIANGLE_RATIO_HINT = (
    "base_ratio is base / side: 1 is equilateral, below 1 sharper, above 1 "
    "wider, always below 2"
)


def _reject_bad_base_ratio(value) -> None:
    """Author ``base_ratio`` is in ``(0, 2)``. A formula passes through.

    The slot enforces the same rule on every later ``=``; this check runs at
    construction so ``box=`` can size the triangle from a valid number. A
    linked or tweened value outside the range is clamped (``maximum_open``).
    """
    if callable(value) and not isinstance(value, type):
        return
    if isinstance(value, Attribute):
        value = value.value
        if callable(value) and not isinstance(value, type):
            return
    from .validate import magnitude
    k = magnitude(value, "Triangle.base_ratio", positive=True, hint=_TRIANGLE_RATIO_HINT)
    if isinstance(k, bool) or not isinstance(k, (int, float)):
        return
    if float(k) >= 2.0:
        raise ValueError(
            f"Triangle.base_ratio must be < 2, got {float(k)}: the base of an "
            f"isosceles triangle is shorter than its two equal sides together"
        )


def _triangle_reach(k: float) -> float:
    """Farthest vertex from the centroid, per unit ``radius`` (1 when ``k <= 1``)."""
    hb = 0.75 * k / math.sqrt(1.0 - 0.25 * k * k)   # half base / radius
    return max(1.0, math.hypot(0.5, hb))


# A linked ``base_ratio`` is clamped below 2 by its slot; placement keeps a
# margin so ``1 - k²/4`` never reaches 0 (the legs would be infinite).
_TRIANGLE_K_TOP = 2.0 - 1e-9


class Triangle(_RadialPolygon):
    """
    Isosceles triangle, equilateral by default. ``side`` is the length of the
    two equal sides; ``base_ratio`` sets the third, the base opposite the
    apex: ``base = base_ratio * side``. ``base_ratio=1`` (the default) is the
    equilateral triangle, below 1 is sharper (a ship, an arrow), above 1 is
    wider, and it is always ``0 < base_ratio < 2``. For three free corners use
    ``Polygon(points=[…])``; for an n-sided regular polygon ``RegularPolygon(n=…)``.

    ``angle`` is where the apex (vertex[0]) points, like every other heading
    in Scena: ``angle=0`` points right (+x), ``angle=90`` is the upright
    pose with a flat base. ``face=True`` motion flies a triangle apex first.
    ``center`` is the centroid; ``radius`` is the center-to-apex distance
    (the circumradius when ``base_ratio=1``).

    Models (changing ``base_ratio`` keeps each model's inputs in place):
      - CENTER_RADIUS: center, radius, angle — the center and the apex stay.
      - CENTER_SIDE: center, side, angle — the center and the equal sides stay.
      - VERTEX_SIDE: vertex (= vertex[0]'s world position, the apex),
        side, angle — the apex and the equal sides stay.

    Example:
        ship = Triangle(center=(400, 300), radius=20, angle=90, base_ratio=0.6)

    Args:
        center: Where the shape sits (a point, or a function that returns one).
            ``center=`` alone gives a default-size shape there.
        layer: Draw layer name or number (default: ``"default"``).
        group: Group tag or list of tags (``group["enemies"]``).
        visual: A look (``Neon()``, ``Glow()``, …), a color, ``Gradient`` or
            ``Texture``.
        color: Solid color (fill on area shapes, stroke on lines).
        line_width: Outline thickness in design units (default 1.5).
        box: Fit into a Box (or a frame-like shape) instead of giving position and size
            — its own form. The triangle keeps its ``base_ratio`` and fits inside.
        radius: Center-to-apex distance.
        angle: Heading of the apex in degrees (counter-clockwise). Setting it keeps
            the point the shape was placed by; ``rotate_to`` turns it about its center.
        side: Length of the two equal sides (instead of ``radius``).
        vertex: Position of the apex (with ``side``).
        base_ratio: Base / side, in ``(0, 2)`` (default 1: equilateral).
    """

    _KIND_LABEL = "Triangle"
    _computed_from = "center, radius, angle and base_ratio"

    radius = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="Triangle.radius")
    side = ScalarSlot(magnitude=True, hint=HINT_EXTENT, label="Triangle.side")
    base_ratio = ScalarSlot(
        default=1.0, magnitude=True, positive=True, maximum=2.0, maximum_open=True,
        hint=_TRIANGLE_RATIO_HINT, label="Triangle.base_ratio",
    )

    _CTOR_EXTRA_KEYS = frozenset({"base_ratio"})
    _HOME_SIZE_KEYS = frozenset({"radius", "angle", "base_ratio"})
    _PART_NAMES = _RadialPolygon._PART_NAMES + ('base_ratio',)

    @overload
    def __new__(cls, *, center: Optional[GeneralPoint] = None, base_ratio: float = 1.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Triangle': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, radius: float, angle: float = 0.0, base_ratio: float = 1.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Triangle': ...

    @overload
    def __new__(cls, *, center: GeneralPoint, side: float, angle: float = 0.0, base_ratio: float = 1.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Triangle': ...

    @overload
    def __new__(cls, *, vertex: GeneralPoint, side: float, angle: float = 0.0, base_ratio: float = 1.0, layer: Any = None, group: Optional[Union[str, Sequence[str]]] = None, visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, line_width: Optional[float] = None, box: Any = None) -> 'Triangle': ...

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        _reject_positional_shape_args(type(self), args)
        if 'n' in kwargs:
            raise TypeError(
                "Triangle always has 3 vertices: drop n=. For a regular polygon "
                "with n sides write RegularPolygon(n=…, center=…, radius=…)."
            )
        free = [k for k in ('p1', 'p2', 'p3', 'points') if k in kwargs]
        if free:
            raise TypeError(
                f"Triangle has no {free[0]}=: it is placed by center / vertex, "
                f"radius / side and angle (base_ratio makes it isosceles). For three "
                f"free corners write Polygon(points=[(x1, y1), (x2, y2), (x3, y3)])."
            )
        defaults = getattr(type(self), '_shape_defaults', None) or {}
        if 'base_ratio' not in kwargs:
            kwargs['base_ratio'] = defaults.get('base_ratio', 1.0)
        k = kwargs['base_ratio']
        _reject_bad_base_ratio(k)
        if 'box' in kwargs and 'radius' not in kwargs and 'side' not in kwargs:
            # Fit inside the box's inscribed circle, as a regular polygon does:
            # past base_ratio 1 the base corners reach farther than the apex.
            from .box import apply_box_to_shape_kwargs
            apply_box_to_shape_kwargs(
                type(self).__name__, kwargs, family="inscribe",
                size_keys=("radius", "side"), heading=True,
            )
            if isinstance(k, (int, float)) and not isinstance(k, bool) and k > 1.0:
                kwargs['radius'] = kwargs['radius'] / _triangle_reach(float(k))
        self._init_radial(3, kwargs)

    def _init_shape_inputs(self, kwargs: Dict[str, Any]) -> None:
        _init_scalar(self, 'base_ratio', kwargs['base_ratio'])

    def _set_defining_parts(self, *defining: str) -> None:
        """``base_ratio`` is an input of every model."""
        names = defining if 'base_ratio' in defining else (*defining, 'base_ratio')
        super()._set_defining_parts(*names)

    def _tri(self) -> Tuple[float, float, float, float, float]:
        """``(k, kp, hb, reach, rps)`` for the current ``base_ratio`` ``k``:
        ``kp`` placed (kept in ``[0, 2)``), ``hb`` half base / radius,
        ``reach`` farthest vertex / radius, ``rps`` radius / side. Cached by
        ``k``: every placement reads it, and a ``base_ratio`` read is the
        slot's (the bare fast path below is ``ScalarSlot.__get__``'s own)."""
        d = self.__dict__
        k = None
        if not d.get('_field_anchors') and d.get('_link') is None:
            ok = d.get('_scalar_bare_ok')
            if ok is not None and ok.get('base_ratio') is True:
                k = d.get('base_ratio', 1.0)
        if k is None:
            k = _bare_num(self.base_ratio)
        c = d.get('_tri_consts')
        if c is not None and c[0] == k:
            return c
        kp = 0.0 if k <= 0.0 else (k if k < _TRIANGLE_K_TOP else _TRIANGLE_K_TOP)
        q = math.sqrt(1.0 - 0.25 * kp * kp)       # height / side
        hb = 0.75 * kp / q
        c = (k, kp, hb, max(1.0, math.hypot(0.5, hb)), (2.0 / 3.0) * q)
        d['_tri_consts'] = c
        return c

    # --- shape hooks (the regular n-gon formulas stay inline on _RadialPolygon) ---

    def _placement_params(self) -> Tuple[float, float, float, float]:
        """``(cx, cy, r, phi0)``: ``r`` is centroid → apex; ``radius = 2/3`` of
        the height, height = ``side * sqrt(1 - k²/4)``."""
        phi0 = _bare_num(self.angle)
        match self.model:
            case RegularPolygonModel.CENTER_RADIUS:
                cx, cy = get_xy(self.center, bare=True)
                r = abs(_bare_num(self.radius))
            case RegularPolygonModel.CENTER_SIDE:
                cx, cy = get_xy(self.center, bare=True)
                r = abs(_bare_num(self.side)) * self._tri()[4]
            case RegularPolygonModel.VERTEX_SIDE:
                vx, vy = get_xy(self.vertex, bare=True)
                r = abs(_bare_num(self.side)) * self._tri()[4]
                cx = vx - r * math.cos(_rad(phi0))
                cy = vy - r * math.sin(_rad(phi0))
            case _:
                raise ValueError(f"Unknown triangle model: {self.model}")
        return cx, cy, r, phi0

    def _side_from_radius(self, r: float) -> float:
        return r / self._tri()[4]

    def _local_verts(self, r: float) -> List[Tuple[float, float]]:
        """Apex on +x, base at x = -r/2 (the centroid sits 1/3 of the height up)."""
        hb = self._tri()[2] * r
        return [(r, 0.0), (-0.5 * r, hb), (-0.5 * r, -hb)]

    def _world_verts(self, cx: float, cy: float, r: float, phi0: float,
                     winding: int = 1) -> List[Tuple[float, float]]:
        a = _rad(phi0)
        co, si = math.cos(a), math.sin(a)
        hb = winding * self._tri()[2] * r
        bx, by = cx - 0.5 * r * co, cy - 0.5 * r * si    # the base's midpoint
        return [(cx + r * co, cy + r * si),
                (bx - hb * si, by + hb * co),
                (bx + hb * si, by - hb * co)]

    def _vertex_xy(self, idx: int, cx: float, cy: float, r: float, phi0: float) -> Tuple[float, float]:
        return self._world_verts(cx, cy, r, phi0, self._winding())[idx]

    def _place_vertices(self, cx: float, cy: float, r: float, phi0: float) -> None:
        verts = self._world_verts(cx, cy, r, phi0, self._winding())
        place_all = self._stats_live()
        for vtx, xy in zip(self._vertices, verts):
            if place_all or vtx._is_derivate_live():
                vtx._takein(xy)

    def _hit_test_xy(self, x: float, y: float) -> bool:
        cx, cy, r, phi0 = self._placement_params()
        return _point_in_polygon(x, y, self._world_verts(cx, cy, r, phi0))

    def _reach_factor(self) -> float:
        return self._tri()[3]

    def _local_path_key(self, r: float):
        return (3, round(float(r), 4), self._tri()[1])

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """The radial extra plus ``base_ratio``: a ratio write alone must change
        the key, or the translate fast path slides a stale hull."""
        extra = _RadialPolygon._collision_pose_extra(self)
        d = self.__dict__
        if not d.get('_field_anchors'):
            ok = d.get('_scalar_bare_ok')
            if ok is None or ok.get('base_ratio') is not False:
                return extra + (float(d.get('base_ratio', 1.0)),)
        return extra + (self._fresh_scalar('base_ratio'),)

    def _clone_shape_kwargs(self) -> Dict[str, Any]:
        return {"base_ratio": _bare_num(self.base_ratio)}

    def _takein_shape_inputs(self, other) -> None:
        k = other.base_ratio if isinstance(other, Triangle) else 1.0
        _init_scalar(self, 'base_ratio', k)


# ---------------------------------------------------------------------------
# Retired name (0.9.0): EquilateralTriangle → Triangle
# ---------------------------------------------------------------------------
#
# Loud, never silent (Scena Design, "Compatibility and versions"). ``scena/
# __init__.py`` answers ``scena.EquilateralTriangle`` / ``from scena import
# EquilateralTriangle`` with this stub (module ``__getattr__``). Not in
# ``__all__`` nor in builtins: a star import gives a plain ``NameError``.
# Keep it at least until 1.0.

def _retired_equilateral_triangle_message(name: Optional[str] = None) -> str:
    fix = (f"Write class {name}(Triangle)" if name
           else "Write Triangle(center=…, radius=…)")
    return (
        f"EquilateralTriangle was renamed to Triangle in 0.9.0 (equilateral by "
        f"default; base_ratio= makes it isosceles). {fix}."
    )


class _RetiredEquilateralTriangle:
    """``EquilateralTriangle`` was renamed ``Triangle`` in 0.9.0; using it raises with the fix."""

    def __init_subclass__(cls, **kwargs):
        raise TypeError(_retired_equilateral_triangle_message(cls.__name__))

    def __new__(cls, *args, **kwargs):
        raise TypeError(_retired_equilateral_triangle_message())


_RetiredEquilateralTriangle.__name__ = _RetiredEquilateralTriangle.__qualname__ = "EquilateralTriangle"

RETIRED_NAMES: Dict[str, Any] = {
    "EquilateralTriangle": _RetiredEquilateralTriangle,
}


def _refuse_anchor_off(anchor, name: str) -> None:
    """``anchor.draggable = False`` / ``handle = False`` (decided 2026-10-10:
    raise; it was accepted and ignored)."""
    from .entity import entity_label
    raise TypeError(
        f"{name} = False on {entity_label(anchor)}: an Anchor is always a "
        f"draggable handle. For a point the pointer cannot move, use "
        f"Point(x, y, visible=True)."
    )


class Anchor(Point):
    """Sugar for a free, always-handled Point (visible + draggable on ``top``).

    Same glyph as a visible Point; construction forces ``handle=True``.
    ``color=`` forwards to Point (author tint; opts out of auto role paint).
    Pose stays free: inbound links raise ``LinkedAttributeError``.
    Outbound links *to* the Anchor are fine, and need a lambda:
    ``Line(p1=lambda: a.center, …)`` follows the drag. A bare ``a.center``
    (or ``a``) is copied once at construction and does not follow.

    Example:
        a = Anchor(100, 100)           # default red (role auto)
        b = Anchor(200, 150, color="cyan")
        Line(p1=lambda: a.center, p2=lambda: b.center)   # follows a and b

    Args:
        x: x coordinate (or a point as the only value).
        y: y coordinate.
        color: Handle color.
        group: Group tag(s).
    """

    def __init__(
        self,
        x: Any = _POINT_UNSET,
        y: Any = _POINT_UNSET,
        *,
        color: Any = _POINT_UNSET,
        group: Optional[Union[str, Sequence[str]]] = None,
    ):
        # Pose must stay free: no Attribute leaves, no whole-point formula.
        if isinstance(x, Attribute) or isinstance(y, Attribute):
            raise LinkedAttributeError(
                "Cannot construct Anchor from linked Attributes: "
                "Anchor pose must stay free (Anchors are always handles)."
            )
        if y is _POINT_UNSET and callable(x) and not isinstance(x, type):
            raise LinkedAttributeError(
                "Cannot construct Anchor from a formula: "
                "Anchor pose must stay free (Anchors are always handles)."
            )
        if (
            y is _POINT_UNSET
            and isinstance(x, tuple)
            and len(x) == 2
            and any(callable(c) and not isinstance(c, type) for c in x)
        ):
            raise LinkedAttributeError(
                "Cannot construct Anchor from linked tuple components: "
                "Anchor pose must stay free (Anchors are always handles)."
            )
        # Forward color= to Point when given; omit → keep role auto after handle=.
        fwd: Dict[str, Any] = {'layer': None, 'group': group}
        if color is not _POINT_UNSET:
            fwd['color'] = color
        # Forward omitted y so Anchor(pt) uses Point's point-like path.
        if y is _POINT_UNSET:
            super().__init__(x, **fwd)
        else:
            super().__init__(x, y, **fwd)
        self.handle = True
        self.set_alpha(self.HANDLE_ALPHA)

    @property
    def handle(self) -> bool:
        """Always ``True``: an Anchor is a visible, draggable handle."""
        return True

    @handle.setter
    def handle(self, value: bool) -> None:
        # Anchors are always handles; keep visible + draggable in sync. The
        # value is still checked: "no" is not a flag (A12).
        if not expect_bool(value, "Anchor.handle"):
            _refuse_anchor_off(self, "handle")
        self.visible = True
        if not self._draggable:
            self._draggable = True
            self._sync_interactive_registry()
        self._apply_role_marker_style()

    @property
    def draggable(self) -> bool:
        """Always ``True`` (an Anchor is a handle); ``False`` raises."""
        return True

    @draggable.setter
    def draggable(self, value: bool) -> None:
        if not expect_bool(value, "Anchor.draggable"):
            _refuse_anchor_off(self, "draggable")
        self.handle = True

    def _draggable_from_callbacks(self, on: bool) -> None:
        pass        # always draggable: clearing a drag callback keeps the handle

    def _ensure_can_link_attribute(self, target: Container) -> None:
        """No inbound links: the pointer drags an Anchor (Guia: "Sem ligação de
        entrada"). The generic refusal said "set draggable = False first",
        which an Anchor cannot do."""
        from .entity import entity_label
        label = entity_label(self)
        raise LinkedAttributeError(
            f"{label[:1].upper()}{label[1:]} takes no links (@=): an Anchor is always a "
            f"handle the pointer drags. For a marker that follows a formula, use a "
            f"Point: Point(lambda: ...), or keep the value in a field of another object."
        )

    def _clone_geometry(self, **kwargs) -> 'Anchor':
        cx, cy = get_xy(self, bare=True)
        kwargs.pop('layer', None)
        color = self.fill
        return type(self)(cx, cy, color=color, **kwargs)


class Blank(Shape):
    """A Shape that ignores all modifications but accepts all Shape operations."""
    
    def __init__(self):
        super().__init__(layer=None)
        self.visible = False
        self._center = Point(0, 0, layer=None)

    @property
    def center(self) -> Point:
        return self._center

    def _clone_geometry(self, **kwargs) -> 'Blank':
        return type(self)()

    def _update_impl(self):
        pass

    def _geometry_draw(self, skia_canvas, fill_paint=_STYLE_PAINT, stroke_paint=_STYLE_PAINT) -> None:
        """Do nothing when drawing."""
        pass
        
    def _takein_impl(self, other: 'Shape') -> None:
        """Do nothing when copying."""
        pass

    def _move_by(self, dx: float, dy: float, *, force: bool = False) -> 'Blank':
        """Ignore movement."""
        return self

    def _move_to(self, x: float, y: float, *, force: bool = False) -> 'Blank':
        """Ignore movement."""
        return self

    def rotate_to(self, value: float, *, about=None, force: bool = False) -> 'Blank':
        _refuse_if_destroyed(self, "rotate_to")
        _finite_deg(value, "rotate_to angle")
        return self

    def rotate_by(self, angle: float, *, about=None, force: bool = False) -> 'Blank':
        _refuse_if_destroyed(self, "rotate_by")
        _finite_deg(angle, "rotate_by angle")
        return self

    def scale_to(self, value: float, *, about=None, force: bool = False) -> 'Blank':
        _refuse_if_destroyed(self, "scale_to")
        return _scale_to_via(self, value, about=about, force=force)

    def scale_by(self, factor: float, *, about=None, force: bool = False) -> 'Blank':
        _refuse_if_destroyed(self, "scale_by")
        _geom, store = _resolve_scale_apply(self, factor, force=force)
        _pose_scale_set(self, store)
        return self

    def _scale_gate(self, about, force: bool, pivot=None) -> None:
        pass                                # nothing but the pose store


_SHAPE_STYLE_SIGNATURE = (
    "layer: Any = None, "
    "group: Optional[Union[str, Sequence[str]]] = None, "
    "visual: Optional[LookLike] = None, color: Optional[ColorLike] = None, "
    "line_width: Optional[float] = None, box: Any = None"
)


def _publish_shape_signature(cls: type) -> None:
    """``help(cls)`` shows the union of model keywords plus shared style keywords.

    The implementation stays ``*args, **kwargs`` so a positional value can raise
    with a keyword example. ``*args`` is not part of the published signature.
    """
    import inspect
    from typing import get_overloads

    init = cls.__dict__.get("__init__")
    if init is None:
        return
    collected: Dict[str, inspect.Parameter] = {}
    new = cls.__dict__.get("__new__")
    if new is not None:
        for ov in get_overloads(new):
            for name, param in inspect.signature(ov).parameters.items():
                if name in ("self", "cls"):
                    continue
                if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                    continue
                prev = collected.get(name)
                if prev is None or (
                    prev.default is inspect.Parameter.empty
                    and param.default is not inspect.Parameter.empty
                ):
                    collected[name] = param.replace(kind=inspect.Parameter.KEYWORD_ONLY)
    for _sig_name, keys in getattr(cls, "_CONSTRUCTOR_SIGNATURES", ()) or ():
        for name in keys:
            collected.setdefault(
                name,
                inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None),
            )
    for name in getattr(cls, "_CTOR_EXTRA_KEYS", ()) or ():
        collected.setdefault(
            name,
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None),
        )
    for name in ("layer", "group", "visual", "color", "line_width", "box"):
        collected.setdefault(
            name,
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=None),
        )
    if "n" in collected and collected["n"].default is inspect.Parameter.empty:
        if cls.__name__ == "RegularPolygon":
            collected["n"] = collected["n"].replace(default=6)
    # One flat signature cannot say "radius= needs center=": every model
    # keyword is optional here (``Circle()`` / ``Circle(center=…)`` work), and
    # the per-model forms are the ``@overload`` stubs editors show.
    point_like = (GeneralPoint, Optional[GeneralPoint])
    for name, param in list(collected.items()):
        if param.default is inspect.Parameter.empty:
            param = param.replace(default=None)
        if param.annotation in point_like:
            # ``Union[ForwardRef('Point'), …]`` read badly in help().
            param = param.replace(annotation="Point | (x, y) | Shape | Vec2")
        collected[name] = param
    published = inspect.Signature(
        [inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD), *collected.values()]
    )
    init.__signature__ = published
    # ``inspect.signature(cls)`` follows ``__wrapped__`` on the actor-init
    # wrapper. The class attribute is what ``help(Circle)`` reads.
    cls.__signature__ = published.replace(
        parameters=[p for p in published.parameters.values() if p.name != "self"]
    )


for _shape_cls in (Line, Circle, Ellipse, RegularPolygon, Rect, Square, Triangle):
    _publish_shape_signature(_shape_cls)


def _publish_point_signature() -> None:
    """Hide the engine ``attr_name`` / ``owner`` path slots use to build a Point."""
    import inspect
    init = Point.__init__
    sig = inspect.signature(init)
    kept = [p for p in sig.parameters.values() if p.name != "_engine" and not p.name.startswith("_")]
    init.__signature__ = sig.replace(parameters=kept)


_publish_point_signature()


def _refuse_retired_burn_kwargs(retired: dict) -> None:
    """``burn_out(fidelity=)`` was removed in 0.6.0: it never changed the drawing."""
    if "fidelity" in retired:
        raise TypeError(
            "burn_out(fidelity=) was removed in 0.6.0: it never changed the "
            "drawing (every value drew the same burn). Delete it: "
            "ship.burn_out(0.55) or ship.burn_out(0.55, intensity=1.2)."
        )
    name = next(iter(retired))
    raise TypeError(
        f"burn_out() got an unexpected keyword argument {name!r}. "
        "Valid: duration, intensity=, on_done=."
    )

