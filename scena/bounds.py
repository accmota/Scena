"""Playfield leave-area: opt-in ``@leave_playfield`` + ``canvas.playfield``.

World-fixed AABB (default 1.5× design rect). Center-vs-box after collision;
handlers fire once per inside→outside edge (with *seen inside* hysteresis.
"""
from __future__ import annotations

import functools
import math
import weakref
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple

import skia

from .validate import call_truncated, expect_callable
from .closed import ClosedSurface

__all__ = [
    "leave_playfield",
    "get_bounds_system",
    "reset_bounds_system",
    "BoundsPlayfield",
]


def _item_center_xy(item) -> Optional[Tuple[float, float]]:
    """World center of ``item``, or ``None`` when it has no pose (bare Entity).

    A center that is not a point / ``(x, y)``, or is non-finite, raises
    naming the item — it would otherwise silently never (or wrongly) leave.
    """
    center = getattr(item, "center", None)
    if center is None:
        return None
    try:
        if hasattr(center, "x"):
            x, y = float(center.x), float(center.y)
        else:
            x, y = center
            x, y = float(x), float(y)
    except (AttributeError, TypeError, ValueError):
        raise TypeError(
            f"@leave_playfield: {item!r} center must be a point or (x, y) "
            f"numbers, got {center!r}"
        ) from None
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(
            f"@leave_playfield: {item!r} has a non-finite center ({x}, {y})"
        )
    return x, y


def _finite_edge(value, name: str) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"canvas.playfield.{name} must be finite, got {value!r}")
    return v


def _center_inside(x: float, y: float, left: float, bottom: float, right: float, top: float) -> bool:
    return left <= x <= right and bottom <= y <= top


class XY(NamedTuple):
    x: float
    y: float


class BoundsPlayfield(ClosedSurface):
    """Author-facing playfield rect behind ``canvas.playfield``.

    Default: design rect with ``pad=0.25`` on each side (1.5×, centered).
    World-fixed — does not follow the camera. Not a ``Box``; ``inset`` /
    ``outset`` / ``grid`` return ``Box`` copies and never write ``.pad``.
    Negative ``pad`` shrinks inside the design rect; ``pad <= -0.5`` collapses
    to a point at the design center (remainder — does not invert edges).
    """

    _closed_who = "canvas.playfield"

    def __init__(self, engine: "ScenaCanvas") -> None:
        self._engine = engine
        self._pad = 0.25
        self._explicit: Optional[Tuple[float, float, float, float]] = None

    def _design_size(self) -> Tuple[float, float]:
        return float(self._engine.width), float(self._engine.height)

    def _pad_rect(self) -> Tuple[float, float, float, float]:
        w, h = self._design_size()
        p = self._pad
        # size * (1 + 2p); clamp to >= 0 so negative pad never inverts edges.
        ew = max(0.0, w * (1.0 + 2.0 * p))
        eh = max(0.0, h * (1.0 + 2.0 * p))
        cx, cy = w * 0.5, h * 0.5
        return (cx - ew * 0.5, cy - eh * 0.5, cx + ew * 0.5, cy + eh * 0.5)

    def _rect(self) -> Tuple[float, float, float, float]:
        if self._explicit is not None:
            return self._explicit
        return self._pad_rect()

    @property
    def pad(self) -> Optional[float]:
        """Pad fraction when pad-relative; ``None`` when explicit edges are set."""
        return None if self._explicit is not None else self._pad

    @pad.setter
    def pad(self, value: float) -> None:
        self._pad = _finite_edge(value, "pad")
        self._explicit = None

    @property
    def left(self) -> float:
        """Left edge x of the playfield (world-fixed). Writable."""
        return self._rect()[0]

    @left.setter
    def left(self, value: float) -> None:
        self._snapshot_explicit()
        l, b, r, t = self._explicit  # type: ignore[misc]
        self._explicit = (_finite_edge(value, 'left'), b, r, t)

    @property
    def bottom(self) -> float:
        """Bottom edge y (y-up). Writable."""
        return self._rect()[1]

    @bottom.setter
    def bottom(self, value: float) -> None:
        self._snapshot_explicit()
        l, b, r, t = self._explicit  # type: ignore[misc]
        self._explicit = (l, _finite_edge(value, 'bottom'), r, t)

    @property
    def right(self) -> float:
        """Right edge x. Writable."""
        return self._rect()[2]

    @right.setter
    def right(self, value: float) -> None:
        self._snapshot_explicit()
        l, b, r, t = self._explicit  # type: ignore[misc]
        self._explicit = (l, b, _finite_edge(value, 'right'), t)

    @property
    def top(self) -> float:
        """Top edge y. Writable."""
        return self._rect()[3]

    @top.setter
    def top(self, value: float) -> None:
        self._snapshot_explicit()
        l, b, r, t = self._explicit  # type: ignore[misc]
        self._explicit = (l, b, r, _finite_edge(value, 'top'))

    @property
    def width(self) -> float:
        """right − left. Read-only."""
        l, _, r, _ = self._rect()
        return r - l

    @property
    def height(self) -> float:
        """top − bottom. Read-only."""
        _, b, _, t = self._rect()
        return t - b

    @property
    def center(self) -> XY:
        """Middle point ``(x, y)``. Read-only."""
        l, b, r, t = self._rect()
        return XY((l + r) * 0.5, (b + t) * 0.5)

    @property
    def top_left(self) -> XY:
        """Corner ``(left, top)``. Read-only."""
        return XY(self.left, self.top)

    @property
    def top_right(self) -> XY:
        """Corner ``(right, top)``. Read-only."""
        return XY(self.right, self.top)

    @property
    def bottom_left(self) -> XY:
        """Corner ``(left, bottom)``. Read-only."""
        return XY(self.left, self.bottom)

    @property
    def bottom_right(self) -> XY:
        """Corner ``(right, bottom)``. Read-only."""
        return XY(self.right, self.bottom)

    def set(
        self,
        box=None,
        /,
        *,
        left: float = None,
        bottom: float = None,
        right: float = None,
        top: float = None,
    ) -> "BoundsPlayfield":
        """Explicit world AABB: one ``Box``, or all four edges by keyword.

        ``box``: a ``Box`` (``canvas.game_view.outset(300)``,
        ``canvas.playfield.outset(m)``); its edges are read once (a snapshot).
        ``left`` / ``bottom`` / ``right`` / ``top``: the four edges, all required
        when no Box is given. Mixing a Box with keywords raises ``TypeError``.
        """
        edges = {"left": left, "bottom": bottom, "right": right, "top": top}
        if box is not None:
            from .box import Box
            if not isinstance(box, Box):
                raise TypeError(
                    f"playfield.set takes a Box (canvas.game_view.outset(300)) or the "
                    f"four keywords set(left=..., bottom=..., right=..., top=...), "
                    f"got {type(box).__name__}"
                )
            given = [k for k, v in edges.items() if v is not None]
            if given:
                raise TypeError(
                    f"playfield.set: pass a Box or the four keywords, not both "
                    f"(got a Box and {', '.join(given)}=)"
                )
            left, bottom, right, top = box.left, box.bottom, box.right, box.top
        else:
            missing = [k for k, v in edges.items() if v is None]
            if missing:
                raise TypeError(
                    f"playfield.set needs a Box or all four keywords "
                    f"left, bottom, right, top (missing: {', '.join(missing)})"
                )
        left = _finite_edge(left, "set(left=...)")
        bottom = _finite_edge(bottom, "set(bottom=...)")
        right = _finite_edge(right, "set(right=...)")
        top = _finite_edge(top, "set(top=...)")
        if left >= right:
            raise ValueError(f"playfield.set: left ({left}) must be < right ({right})")
        if bottom >= top:
            raise ValueError(f"playfield.set: bottom ({bottom}) must be < top ({top})")
        self._explicit = (left, bottom, right, top)
        return self

    def _as_box(self):
        from .box import Box
        l, b, r, t = self._rect()
        return Box._from_aabb(l, b, r, t)

    def inset(self, margin: float):
        """Layout copy as a ``Box``. Does not change ``.pad``."""
        return self._as_box().inset(margin)

    def outset(self, margin: float):
        """Larger layout copy as a ``Box``. Does not change ``.pad``."""
        return self._as_box().outset(margin)

    def grid(self, cols: int, rows: int, gap=0):
        """Divide the playfield AABB into a ``Grid`` of ``Box`` cells."""
        return self._as_box().grid(cols, rows, gap=gap)

    def beside(self, side: str, *, width=None, height=None, gap: float = 0):
        """Outside-neighbor layout copy as a ``Box``. Does not change ``.pad``."""
        return self._as_box().beside(side, width=width, height=height, gap=gap)

    def strip(self, side: str, thickness: float):
        """Inside edge-band layout copy as a ``Box``. Does not change ``.pad``."""
        return self._as_box().strip(side, thickness)

    def _snapshot_explicit(self) -> None:
        if self._explicit is None:
            self._explicit = self._pad_rect()


class BoundsSystem:
    """Global leave-bounds registry and per-frame step."""

    def __init__(self) -> None:
        # Tag -> every top-level handler on it, in registration order (all run,
        # like ``@collide`` and the class form). An act's handlers are dropped at
        # the act change (the act manager restores the sealed copy).
        self._group_handlers: Dict[str, Tuple[Callable, ...]] = {}
        # item → the class's plain ``@leave_playfield`` functions (called as
        # ``fn(item)``). Never a bound method: the value would hold its own
        # weak key strongly and the actor could never be collected.
        self._instance_handlers: "weakref.WeakKeyDictionary[Any, Tuple[Callable, ...]]" = (
            weakref.WeakKeyDictionary()
        )
        self._seen_inside: "weakref.WeakKeyDictionary[Any, bool]" = (
            weakref.WeakKeyDictionary()
        )
        self._playfield: Optional[BoundsPlayfield] = None

    def bind_playfield(self, playfield: BoundsPlayfield) -> None:
        self._playfield = playfield

    @property
    def enrolled(self) -> bool:
        return bool(self._group_handlers or self._instance_handlers)

    def add_group_handler(self, group_name: str, handler: Callable) -> None:
        expect_callable(handler, what="leave_playfield handler")
        tag = str(group_name)
        prev = self._group_handlers.get(tag, ())
        if handler not in prev:
            # A new tuple, never an in-place change: the act seal keeps a copy.
            self._group_handlers[tag] = prev + (handler,)

    def add_instance_handler(self, item, fn: Callable) -> None:
        """Enroll a class ``@leave_playfield`` function for ``item``.

        ``fn`` is the plain function (``fn(item)``), not a bound method — see
        ``_instance_handlers``. Several methods on one class all run.
        """
        expect_callable(fn, what="leave_playfield handler")
        prev = self._instance_handlers.get(item, ())
        if fn not in prev:
            self._instance_handlers[item] = prev + (fn,)

    def forget_item(self, item) -> None:
        """Drop ``item``'s instance handlers and edge memory (``destroy()``)."""
        self._instance_handlers.pop(item, None)
        self._seen_inside.pop(item, None)

    def _playfield_rect(self) -> Optional[Tuple[float, float, float, float]]:
        if self._playfield is None:
            return None
        rect = self._playfield._rect()
        left, bottom, right, top = rect
        # Checked at use, not per edge: edges are set one at a time, so a
        # half-moved rect is legal between two assignments.
        if not (left <= right and bottom <= top):
            raise ValueError(
                f"canvas.playfield is inverted (left={left:g}, right={right:g}, "
                f"bottom={bottom:g}, top={top:g}): need left <= right and "
                f"bottom <= top, or nothing can ever be inside it"
            )
        return rect

    def _should_skip_item(self, item, stack: "LayerStack") -> bool:
        if not getattr(item, "is_alive", True):
            return True
        if not getattr(item, "active", True):
            return True
        if _item_center_xy(item) is None:
            return True
        layer_name = getattr(item, "layer", None)
        from .registry import layer_is_parallax
        if layer_is_parallax(stack, layer_name):
            return True
        return False

    def _handlers_for_item(self, item) -> List[Callable]:
        out: List[Callable] = []
        seen_ids: Set[int] = set()
        for fn in self._instance_handlers.get(item, ()):
            # Same arity rule as a bound method: ``self`` then the item.
            out.append(functools.partial(call_truncated, fn, item, item))
            seen_ids.add(id(fn))
        for tag in getattr(item, "group", ()) or ():
            for handler in self._group_handlers.get(tag, ()):
                if id(handler) not in seen_ids:
                    out.append(handler)
                    seen_ids.add(id(handler))
        return out

    def _dispatch_leave(self, item, handlers: List[Callable]) -> None:
        for handler in handlers:
            if not getattr(item, "is_alive", True):
                return
            if isinstance(handler, functools.partial):
                handler()  # class method, already given its instance
            else:
                # An earlier handler may have changed act: an act's handler
                # dropped by that change does not run (review S4-1).
                tags = getattr(item, "group", ()) or ()
                if not any(handler in self._group_handlers.get(t, ()) for t in tags):
                    continue
                call_truncated(handler, item)

    def step(self) -> None:
        if not self.enrolled:
            return
        rect = self._playfield_rect()
        if rect is None:
            return
        left, bottom, right, top = rect

        from .canvas import ScenaCanvas
        try:
            engine = ScenaCanvas.get_current()
        except RuntimeError:
            return
        registry = engine.registry
        stack = registry.layers

        candidates: List[Any] = []
        seen_items: Set[int] = set()

        for tag in self._group_handlers:
            for item in list(registry.list_by_groupid(tag)):
                oid = id(item)
                if oid not in seen_items:
                    seen_items.add(oid)
                    candidates.append(item)

        for item in list(self._instance_handlers.keys()):
            oid = id(item)
            if oid not in seen_items:
                seen_items.add(oid)
                candidates.append(item)

        for item in candidates:
            if self._should_skip_item(item, stack):
                continue
            xy = _item_center_xy(item)
            if xy is None:
                continue
            x, y = xy
            inside = _center_inside(x, y, left, bottom, right, top)
            was_seen = self._seen_inside.get(item, False)
            if inside:
                self._seen_inside[item] = True
                continue
            if not was_seen:
                continue
            handlers = self._handlers_for_item(item)
            if not handlers:
                continue
            # Consume the edge before handlers run (a raising handler must
            # not refire next step). Re-fires after the item re-enters.
            del self._seen_inside[item]
            self._dispatch_leave(item, handlers)

    def debug_stroke(self, skia_canvas) -> None:
        """Immediate-mode playfield outline (inspect overlay)."""
        if not self.enrolled or skia_canvas is None:
            return
        rect = self._playfield_rect()
        if rect is None:
            return
        left, bottom, right, top = rect
        paint = skia.Paint()
        paint.setStyle(skia.Paint.kStroke_Style)
        paint.setStrokeWidth(1.5)
        paint.setAntiAlias(True)
        paint.setColor4f(skia.Color4f(0.2, 0.85, 0.95, 0.85))
        path = skia.Path()
        path.moveTo(left, bottom)
        path.lineTo(right, bottom)
        path.lineTo(right, top)
        path.lineTo(left, top)
        path.close()
        skia_canvas.drawPath(path, paint)


_bounds_system: Optional[BoundsSystem] = None


def get_bounds_system() -> BoundsSystem:
    global _bounds_system
    if _bounds_system is None:
        _bounds_system = BoundsSystem()
    return _bounds_system


def reset_bounds_system() -> None:
    """Test helper: clear the global system."""
    global _bounds_system
    _bounds_system = BoundsSystem()
    try:
        eng = ScenaCanvas.get_current()
        if hasattr(eng, "bounds"):
            _bounds_system.bind_playfield(eng.bounds)
    except RuntimeError:
        pass


def _in_class_body_for_bounds() -> bool:
    """True when decorating inside a class body (module or nested)."""
    from .process import _in_executing_class_body
    for depth in range(2, 8):
        if _in_executing_class_body(depth):
            return True
    return False


def _register_leave_playfield(func: Callable, tags: Tuple[str, ...]) -> Callable:
    from .process import _claim_decorator_role

    in_class = _in_class_body_for_bounds()

    if in_class:
        if tags:
            raise TypeError(
                "@leave_playfield on a class method takes no group names — "
                "use @leave_playfield at script level for group['bolt'] enrollment."
            )
        _claim_decorator_role(func, "leave_playfield")
        func._leave_playfield_method = True
        return func

    if not tags:
        raise TypeError(
            "@leave_playfield requires at least one group name at script level "
            "(e.g. @leave_playfield('bolt', 'sting'))."
        )

    for tag in tags:
        if not isinstance(tag, str):
            raise TypeError(
                "@leave_playfield group names must be strings — "
                f"got {type(tag).__name__}. Use @leave_playfield('bolt'), not group['bolt']."
            )

    _claim_decorator_role(func, "leave_playfield")
    from .registry import declare_group_names
    declare_group_names(tags)
    sys = get_bounds_system()
    for tag in tags:
        sys.add_group_handler(tag, func)
    return func


def leave_playfield(*group_names):
    """Decorator: fire when an enrolled actor's center leaves ``canvas.playfield``.

    Script level::

        @leave_playfield("bolt", "sting")
        def leftover(shot):
            shot.destroy()

    Class method (this instance only)::

        class Bolt(Sprite):
            @leave_playfield
            def leftover(self):
                self.destroy()
    """
    bare = (
        len(group_names) == 1
        and callable(group_names[0])
        and not isinstance(group_names[0], str)
    )
    tags = () if bare else group_names

    def decorator(func: Callable) -> Callable:
        return _register_leave_playfield(func, tags)

    if bare:
        return decorator(group_names[0])
    return decorator


# Late import for type hints only
from .canvas import ScenaCanvas  # noqa: E402
from .registry import LayerStack  # noqa: E402
