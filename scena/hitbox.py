"""Hitboxes: every collider a Graphic answers with is a :class:`Hitbox`.

``graphic.hitbox`` is the **main** hitbox (``_MainHitbox``): the one that
stands, meets walls and is pushed by ``resolve()``. It is a view: its knobs
forward to the host's own bake state. ``sprite.add_hitbox(group=…)`` adds
**parts** — detection-only extras. Every hitbox reads ``shape`` / ``source``
/ ``anchor`` / ``scale`` / ``active`` / ``box``. A part:

- bakes with the same four knobs and the same pipeline as the main hitbox
  (``_HitboxBakeMixin``), defaulting to ``source="each"``;
- follows the **paint** — pose, flips, current cell, and ``tilt`` (seat too);
- answers for the groups it **claims**: the host joins those groups as usual,
  and ``@collide`` lists the part's collider under them instead of the body's;
- never resolves: ``resolve(part, …)`` refuses it, and manual ``info.resolve()``
  on a part contact raises. A ``resolve()`` on a group the part claims moves
  the host's **body** (``CollisionSystem._claimed_bodies``);
- lives and dies with the host (destroy, park, ``collidable = False``).

An empty bake (transparent cell, ``"each"`` frame without art) means no
collider on that frame — there is no design-box fallback for parts.
"""

from __future__ import annotations

import inspect
import math
import weakref
from collections.abc import Sequence
from typing import List, Optional, Tuple

from .atlas import boxes_to_local, circle_to_local
from .entity import _author_site, _bump_collision_epoch
from .state import (
    CallableAssignError,
    LinkedAttributeError,
    as_payload,
    callable_assign_message,
)
from .validate import expect_bool as _expect_flag
from .validate import fixed_magnitude as _fixed_magnitude
from .validate import number as _number
from .sprite import (
    _ADD_HITBOX_UNSET,
    _HitboxBakeMixin,
    _emit_baked_specs,
    _parse_hitbox,
    _parse_hitbox_anchor,
    _parse_hitbox_from,
    _parse_hitbox_scale,
)


# Every Hitbox ever made (weak). Audit registry: the system tests' "parts die
# with their host" invariant and the leak census read it (tests/*_support.py).
_LIVE_PARTS: "weakref.WeakSet[Hitbox]" = weakref.WeakSet()

# Parts whose ``active`` is linked (``hb["active"] @= fn``). Module-level so a
# ``reset_collision_system()`` does not drop the links; ``step()`` refreshes
# every entry before its proxies (``_refresh_linked_parts``).
_LINKED_PARTS: "weakref.WeakSet[Hitbox]" = weakref.WeakSet()

# ``add_hitbox`` art-knob default: tells "left out" from "passed", so a px
# shape can refuse an explicit ``hitbox_from="each"`` too.
_UNSET = _ADD_HITBOX_UNSET

_ART_DEFAULTS = (
    ("shape", "auto"),
    ("source", "each"),
    ("anchor", "center"),
    ("scale", 1.0),
)

# Names a Hitbox dropped when every hitbox became one type: the knob lost its
# ``hitbox`` prefix (it is on a hitbox already). Reads and writes raise with
# the new spelling instead of an AttributeError about ``__slots__``.
_RETIRED_KNOBS = {
    "hitbox": "shape",
    "hitbox_from": "source",
    "hitbox_anchor": "anchor",
    "hitbox_scale": "scale",
    "width": "box.width",
    "height": "box.height",
}


def _retired_knob_message(name: str) -> str:
    new = _RETIRED_KNOBS[name]
    if name in ("width", "height"):
        return (
            f"a Hitbox has no .{name}; measure it: hb.{new} "
            "(a Box of the hitbox as it is now)."
        )
    return f"Hitbox.{name} is now hb.{new} (add_hitbox({new}=…) when adding one)."


class _RetiredKnob:
    """A retired name, read or written, raises with its new spelling. A class
    descriptor costs nothing elsewhere; a ``__setattr__`` that checked the
    name cost about 100 ns on every private write (graphics review HP14:
    about 2 µs per animated part per step)."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        raise AttributeError(_retired_knob_message(self._name))

    def __set__(self, obj, value) -> None:
        raise AttributeError(_retired_knob_message(self._name))


def _box_of_prims(prims):
    """Screen-aligned Box around ``prims``, or ``None`` when there are none."""
    if not prims:
        return None
    from .box import Box
    minx = min(p.aabb[0] for p in prims)
    miny = min(p.aabb[1] for p in prims)
    maxx = max(p.aabb[2] for p in prims)
    maxy = max(p.aabb[3] for p in prims)
    return Box._snapshot(
        0.5 * (minx + maxx), 0.5 * (miny + maxy), maxx - minx, maxy - miny, 0.0,
    )


def _dead_hitbox_error(hb, what: str):
    """``DestroyedError`` for a write on a hitbox that is out of play.

    Same contract as a dead Entity: reads keep answering, a change raises and
    names why (removed, or its Graphic destroyed — with the destroy site) and
    the guard to write.
    """
    from .state import DestroyedError
    from .entity import _destroyed_access_message, _refuse_if_destroyed
    host = hb._host_ref()
    main = type(hb)._is_main
    if what.startswith("["):                     # the ``hb["active"] @=`` link
        label = f"hitbox{what}" if main else f"hb{what}"
    else:
        label = f"hitbox.{what}" if main else f"Hitbox.{what}"
    if hb._removed:
        return DestroyedError(
            f"{label} cannot change a removed hitbox (sprite.remove_hitbox took it "
            f"off {host!r}). Guard the call: if hb.is_alive:"
        )
    if host is None:
        return DestroyedError(
            f"{label} cannot change a hitbox whose Graphic is gone. "
            "Guard the call: if hb.is_alive:"
        )
    if main:
        try:
            _refuse_if_destroyed(host, f"hitbox.{what}")
        except DestroyedError as e:
            return e
    base = (
        f"{label} cannot change a hitbox whose {type(host).__name__} was destroyed. "
        "Guard the call: if hb.is_alive:"
    )
    return DestroyedError(_destroyed_access_message(host, base))


def _read_only(message: str):
    """A property setter that refuses with a Scena sentence (not Python's
    "property … has no setter")."""
    def refuse(self, value) -> None:
        raise AttributeError(message)
    refuse._scena_read_only = True     # tests tell refusers from real setters
    return refuse


def _px_numbers(value, what: str, n: int, form: str) -> Tuple[float, ...]:
    value = as_payload(value)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(
            f"{what} expected {form} in the frame's pixels; got {type(value).__name__}."
        )
    if len(value) != n:
        raise TypeError(
            f"{what} expected {form} ({n} numbers) in the frame's pixels; "
            f"got {len(value)}."
        )
    return tuple(_number(as_payload(v), what) for v in value)


def _parse_px_rect(value) -> Tuple[float, float, float, float]:
    """``(x, y, w, h)``: top-left corner and size, in the frame's pixels (y down)."""
    x, y, w, h = _px_numbers(value, "px_rect", 4, "(x, y, w, h)")
    return (x, y, _fixed_magnitude(w, "px_rect width"), _fixed_magnitude(h, "px_rect height"))


def _parse_px_circle(value) -> Tuple[float, float, float]:
    """``(x, y, r)``: centre and radius, in the frame's pixels (y down)."""
    x, y, r = _px_numbers(value, "px_circle", 3, "(x, y, r)")
    return (x, y, _fixed_magnitude(r, "px_circle radius"))


def _site_text(site) -> str:
    if not site:
        return "an unknown line"
    import os
    return f"{os.path.basename(site[0])}:{site[1]}"


class _ActiveRef:
    """``hb["active"]``: the link point for ``@=`` and ``unlink()``."""

    __slots__ = ("_part",)

    def __init__(self, part: "Hitbox") -> None:
        self._part = part

    def __imatmul__(self, source) -> "_ActiveRef":
        self._part._link_active(source, _author_site())
        return self

    def unlink(self) -> "Hitbox":
        """Drop the formula; ``active`` keeps its last value."""
        self._part._unlink_active()
        return self._part

    @property
    def linked(self) -> bool:
        return self._part._active_link is not None

    def __repr__(self) -> str:
        state = "linked" if self.linked else "plain"
        return f"<hitbox['active'] {state}: {self._part._active_raw()}>"


def _parse_part_groups(group) -> Tuple[str, ...]:
    """Same rule as ``Entity(group=…)``: a string, a sequence of strings, or None."""
    if group is None:
        return ()
    if isinstance(group, str):
        names = (group,)
    elif isinstance(group, Sequence) and all(isinstance(x, str) for x in group):
        names = tuple(group)
    else:
        raise TypeError("group must be either a string, a sequence of strings, or None")
    for n in names:
        if not n:
            raise TypeError("group names must be non-empty strings")
    return tuple(dict.fromkeys(names))


class Hitbox(_HitboxBakeMixin):
    """A collider a Graphic answers with. ``graphic.hitbox`` is the main one;
    ``sprite.add_hitbox`` adds detection-only parts.

    Not an Entity: no pose, no draw, no processes, no ink. Handlers receive
    the host Sprite; ``info.a_hitbox`` / ``info.b_hitbox`` name the part.

    Args:
        group: Group tag(s) this part answers for (``@collide("weak_spot", …)``).
        shape: ``"auto"`` · ``"rect"`` · ``"ellipse"`` · ``"circle"`` · ``"hull"``.
        source: Which art the part is measured on (default ``"each"``).
        anchor: Point that stays put when scaled.
        scale: Shrink / stretch: a number or ``(sx, sy)``.
        active: Detects while ``True``.
        px_rect: Place by hand: ``(x, y, w, h)`` in frame pixels (top-left + size).
        px_circle: Place by hand: ``(x, y, r)`` in frame pixels.
    """

    # Duck-typed marker for the collision engine (no import cycle).
    _is_hitbox_part = True
    # The main hitbox view (``_MainHitbox``) says True.
    _is_main = False

    __slots__ = (
        "_host_ref",
        "_claims",
        "_added",
        "_active",
        "_removed",
        "_part_epoch",
        "_collider",
        "_collidable",
        # Bake state (same names as the Sprite body; see ``_HitboxBakeMixin``).
        "_hitbox_kind",
        "_hitbox_from",
        "_hitbox_anchor",
        "_hitbox_scale",
        "_hitbox_boxes",
        "_hitbox_circle",
        "_hitbox_circles",
        "_hitbox_ellipse",
        "_hitbox_ellipses",
        "_hitbox_poly",
        "_hitbox_base_boxes",
        "_hitbox_base_circle",
        "_hitbox_base_circles",
        "_hitbox_base_ellipse",
        "_hitbox_base_ellipses",
        "_hitbox_base_poly",
        "_hitbox_local_radius",
        "_hitbox_extent_x",
        "_hitbox_extent_y",
        "_hitbox_extent_pose",
        "_hitbox_frame",
        "_hitbox_locked_kind",
        "_hitbox_baked_key",
        "_hitbox_ref_src_w",
        "_hitbox_ref_src_h",
        "_auto_baked",
        # Round 2: hand-placed pixel shape, linked ``active``, author sites.
        "_px",
        "_site",
        "_active_link",
        "_link_site",
        "_link_busy",
        "__weakref__",
    )

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError(
            "Hitbox is not constructed directly. "
            "Use sprite.add_hitbox(group=..., shape=..., source=...) for an "
            "extra one; the main one is sprite.hitbox."
        )

    __init__.__signature__ = inspect.Signature([
        inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD),
        inspect.Parameter("group", inspect.Parameter.KEYWORD_ONLY, default=None),
        inspect.Parameter("shape", inspect.Parameter.KEYWORD_ONLY, default="auto"),
        inspect.Parameter("source", inspect.Parameter.KEYWORD_ONLY, default="each"),
        inspect.Parameter("anchor", inspect.Parameter.KEYWORD_ONLY, default="center"),
        inspect.Parameter("scale", inspect.Parameter.KEYWORD_ONLY, default=1.0),
        inspect.Parameter("active", inspect.Parameter.KEYWORD_ONLY, default=True),
        inspect.Parameter("px_rect", inspect.Parameter.KEYWORD_ONLY, default=None),
        inspect.Parameter("px_circle", inspect.Parameter.KEYWORD_ONLY, default=None),
    ])

    @classmethod
    def _make(
        cls,
        host,
        *,
        group=None,
        shape=_UNSET,
        source=_UNSET,
        anchor=_UNSET,
        scale=_UNSET,
        active=True,
        px_rect=None,
        px_circle=None,
        site=None,
    ) -> "Hitbox":
        groups = _parse_part_groups(group)
        if callable(as_payload(active)):
            raise TypeError(
                "add_hitbox(active=) takes True / False. To follow the animation, "
                "link it after: hb = sprite.add_hitbox(...); "
                "hb[\"active\"] @= lambda: sprite.showing(...)"
            )
        active = _expect_flag(active, "active")
        px = cls._parse_px_kwargs(px_rect, px_circle)
        given = dict(shape=shape, source=source, anchor=anchor, scale=scale)
        if px is not None:
            from .sprite import Svg
            if isinstance(host, Svg):
                raise TypeError(
                    f"{px[0] == 'rect' and 'px_rect' or 'px_circle'}= needs a sprite sheet; "
                    "an Svg has no pixels. Use the art knobs (shape=, scale=)."
                )
            passed = [k for k, v in given.items() if v is not _UNSET]
            if passed:
                name = "px_rect" if px[0] == "rect" else "px_circle"
                raise TypeError(
                    f"a px shape is placed by hand; drop {passed[0]}= "
                    f"({name}= and the art knobs shape= / source= / "
                    "anchor= / scale= do not mix)."
                )
        for k, default in _ART_DEFAULTS:
            if given[k] is _UNSET:
                given[k] = default
        kind = _parse_hitbox(given["shape"], what="shape")
        spec = _parse_hitbox_from(
            given["source"], host._sheet, construct_frame=int(host._construct_frame),
            what="source",
        )
        anchor = _parse_hitbox_anchor(given["anchor"], what="anchor")
        scale = _parse_hitbox_scale(given["scale"], what="scale")
        claims = host._hitbox_claims or {}
        for g in groups:
            if g in claims:
                raise TypeError(
                    f"group {g!r} is already claimed by another hitbox on this sprite; "
                    f"one hitbox answers for each group."
                )
        self = object.__new__(cls)
        self._host_ref = weakref.ref(host)
        self._claims = set()
        self._added = set()         # claims that put the host in the group (HP13)
        self._active = bool(active)
        self._removed = False
        self._part_epoch = 0
        self._collider = None
        self._collidable = False
        self._hitbox_kind = kind
        self._hitbox_from = spec
        self._hitbox_anchor = anchor
        self._hitbox_scale = scale
        self._hitbox_frame = 0
        self._hitbox_locked_kind = None
        self._hitbox_baked_key = None
        self._hitbox_ref_src_w = 1.0
        self._hitbox_ref_src_h = 1.0
        self._auto_baked = False
        self._px = px
        self._site = site
        self._active_link = None
        self._link_site = None
        self._link_busy = False
        self._clear_auto_hitbox()
        _LIVE_PARTS.add(self)
        host._hitbox_parts = host._hitbox_parts + (self,)
        for g in groups:
            self._claim(g)
        return self

    @staticmethod
    def _parse_px_kwargs(px_rect, px_circle):
        if px_rect is not None and px_circle is not None:
            raise TypeError(
                "one px shape per hitbox: pass px_rect= or px_circle=, not both "
                "(another shape is another add_hitbox)."
            )
        if px_rect is not None:
            return ("rect", _parse_px_rect(px_rect))
        if px_circle is not None:
            return ("circle", _parse_px_circle(px_circle))
        return None

    def __repr__(self) -> str:
        host = self._host_ref()
        state = "removed" if not self.is_alive else ("on" if self._active else "off")
        if self._active_link is not None:
            state += ", linked"
        groups = ", ".join(sorted(self._claims)) or "-"
        if self._px is not None:
            shape = f"px_{self._px[0]}={self._px[1]!r}"
        else:
            shape = f"{self._hitbox_kind}/{self._hitbox_from!r}"
        return f"<Hitbox {shape} [{groups}] of {host!r} {state}>"

    def _active_raw(self) -> bool:
        """The stored on / off, without running a link (repr)."""
        return self._active

    # --- author surface ------------------------------------------------------

    @property
    def host(self):
        """The Sprite that owns this hitbox (``None`` after it is removed or destroyed)."""
        host = self._host_ref()
        if host is None or self._removed or not getattr(host, "is_alive", False):
            return None
        return host

    host = host.setter(_read_only(
        "hb.host is the sprite that owns this hitbox; a hitbox does not move to "
        "another sprite. Add one there: other.add_hitbox(...)."
    ))

    @property
    def is_alive(self) -> bool:
        """True until ``remove_hitbox`` or the host's ``destroy()``."""
        if self._removed:
            return False
        host = self._host_ref()
        return host is not None and bool(getattr(host, "is_alive", False))

    is_alive = is_alive.setter(_read_only(
        "hb.is_alive is read-only. Remove an extra hitbox with "
        "sprite.remove_hitbox(hb); switch any hitbox off with hb.active = False."
    ))

    def _refuse_dead(self, what: str) -> None:
        """Every write on a hitbox out of play raises ``DestroyedError``."""
        if not self.is_alive:
            raise _dead_hitbox_error(self, what)

    @property
    def active(self) -> bool:
        """Author switch for this part (default True). ``False`` leaves collision.

        Linked (``hb["active"] @= fn``): each read calls ``fn`` and applies it.
        """
        if self._active_link is not None:
            if self._link_busy:
                raise ValueError(
                    "the formula linked to this hitbox's active reads itself "
                    f"(hb.active inside hb['active'] @= …, linked at "
                    f"{_site_text(self._link_site)})."
                )
            self._refresh_link()
        return self._active

    @active.setter
    def active(self, value) -> None:
        self._refuse_dead("active")
        if callable(as_payload(value)):
            raise CallableAssignError(callable_assign_message("hitbox", "active"))
        if self._active_link is not None:
            raise LinkedAttributeError(
                "this hitbox's active is linked (hb['active'] @= …, at "
                f"{_site_text(self._link_site)}); call hb['active'].unlink() "
                "before writing it."
            )
        self._apply_active(_expect_flag(value, 'active'))

    def _apply_active(self, want: bool) -> None:
        """Switch on / off: enroll the claims, or leave collision (exits fire)."""
        if want == self._active:
            return
        self._active = want
        if not self.is_alive:
            return
        if want:
            self._enroll_claims()
        else:
            self._retire_collider()

    # --- linked active (``hb["active"] @= fn``) --------------------------------

    def __getitem__(self, key):
        if key == "active":
            return _ActiveRef(self)
        raise TypeError(
            f"hitbox[{key!r}]: only 'active' links on a Hitbox "
            "(hb['active'] @= lambda: …). Set the other knobs with =."
        )

    def __setitem__(self, key, value) -> None:
        # ``hb["active"] @= fn`` writes the ref back after ``__imatmul__``.
        if key == "active" and isinstance(value, _ActiveRef) and value._part is self:
            return
        raise TypeError(
            f"hitbox[{key!r}] = … is not a write. Use hb.active = True / False, "
            "or link it: hb['active'] @= lambda: …"
        )

    def _link_active(self, source, site) -> None:
        if not callable(source):
            raise TypeError(
                "hb['active'] @= expects a function (lambda: …) that returns "
                f"True / False; got {type(source).__name__}. "
                "For a fixed value write hb.active = True / False."
            )
        self._require_alive("['active'] @=")
        old_fn, old_site = self._active_link, self._link_site
        self._active_link = source
        self._link_site = site
        try:
            self._refresh_link(force=True)
        except BaseException:
            self._active_link, self._link_site = old_fn, old_site
            if old_fn is None:
                _LINKED_PARTS.discard(self)
            raise
        _LINKED_PARTS.add(self)

    def _unlink_active(self) -> None:
        self._active_link = None
        self._link_site = None
        _LINKED_PARTS.discard(self)

    def _refresh_link(self, *, force: bool = False) -> None:
        """Call the linked function and apply its flag (enter / exit as a write).

        Skipped while the part cannot be in play (removed, host dead, parked,
        or ``collidable = False``); resume re-enrolls and the next refresh
        sets the value. ``force`` evaluates anyway (the ``@=`` line itself).
        """
        fn = self._active_link
        if fn is None or self._link_busy:
            return
        if not force:
            if not self.is_alive:
                return
            host = self._host_ref()
            if getattr(host, "_collision_opt_out", False) or not getattr(host, "active", True):
                return
        self._link_busy = True
        try:
            try:
                raw = fn()
            except Exception as e:
                self._note_link_error(e)
                raise
            try:
                want = _expect_flag(raw, "hb['active'] formula")
            except (TypeError, ValueError) as e:
                self._note_link_error(e)
                raise
        finally:
            self._link_busy = False
        if self.is_alive:
            self._apply_active(want)
        else:
            self._active = want

    def _note_link_error(self, e: BaseException) -> None:
        add = getattr(e, "add_note", None)
        if add is not None:
            add(
                f"in the formula linked to hitbox.active at {_site_text(self._link_site)} "
                f"(hitbox made at {_site_text(self._site)})"
            )

    @property
    def group(self) -> frozenset:
        """Groups this hitbox answers for (read-only; use ``add_to_group``)."""
        return frozenset(self._claims)

    group = group.setter(_read_only(
        "hb.group is a snapshot of the groups this hitbox claims; change it with "
        "hb.tag(...) / hb.untag(...)."
    ))

    def add_to_group(self, groupid: str) -> "Hitbox":
        """Answer for ``groupid``: the host joins it; collision uses this hitbox."""
        from .entity import _require_group_name
        name = _require_group_name(groupid, "add_to_group")
        self._require_alive("add_to_group")
        if name in self._claims:
            return self
        other = (self._host_ref()._hitbox_claims or {}).get(name)
        if other is not None and other is not self:
            raise TypeError(
                f"group {name!r} is already claimed by another hitbox on this sprite; "
                f"one hitbox answers for each group."
            )
        self._claim(name)
        return self

    def remove_from_group(self, groupid: str) -> "Hitbox":
        """Stop answering for ``groupid``. The host leaves the group when this
        hitbox put it there; a group the host was in on its own stays."""
        from .entity import _require_group_name
        groupid = _require_group_name(groupid, "remove_from_group")
        self._refuse_dead("remove_from_group")
        if groupid not in self._claims:
            return self
        host = self._host_ref()
        if self._unclaim(groupid) and host is not None and getattr(host, "is_alive", False) \
                and groupid in host.group:
            host.remove_from_group(groupid)
        return self

    def tag(self, *names: str) -> "Hitbox":
        """Add this hitbox to named groups (tag sugar)."""
        self._refuse_dead("tag")
        from .entity import _tag_names
        for n in _tag_names(names, "tag"):
            self.add_to_group(n)
        return self

    def untag(self, *names: str) -> "Hitbox":
        """Remove this hitbox from named groups (tag sugar)."""
        self._refuse_dead("untag")
        from .entity import _tag_names
        for n in _tag_names(names, "untag"):
            self.remove_from_group(n)
        return self

    def tagged(self, name: str) -> bool:
        """True if this hitbox answers for the named group."""
        from .entity import _require_group_name
        return _require_group_name(name, "tagged") in self._claims     # HP6: a list hashed raw

    @property
    def shape(self) -> str:
        """``"auto"`` / ``"rect"`` / ``"ellipse"`` / ``"circle"`` / ``"hull"``."""
        return self._hitbox_kind

    @shape.setter
    def shape(self, value) -> None:
        self._refuse_dead("shape")
        self._refuse_art_write("shape")
        self._hitbox_kind = _parse_hitbox(value, what="shape")
        self._invalidate_auto_bake()

    @property
    def source(self):
        """Which art defines this hitbox (default ``"each"``: the current cell)."""
        return self._hitbox_from

    @source.setter
    def source(self, value) -> None:
        self._refuse_dead("source")
        self._refuse_art_write("source")
        host = self._require_alive("source")
        spec = _parse_hitbox_from(
            value, host._sheet, construct_frame=int(host._construct_frame),
            what="source",
        )
        if spec == self._hitbox_from:
            return
        self._hitbox_from = spec
        self._invalidate_auto_bake()

    @property
    def anchor(self):
        """Fixed point for ``scale`` (same presets as the main hitbox)."""
        return self._hitbox_anchor

    @anchor.setter
    def anchor(self, value) -> None:
        self._refuse_dead("anchor")
        self._refuse_art_write("anchor")
        key = _parse_hitbox_anchor(value, what="anchor")
        if key == self._hitbox_anchor:
            return
        self._hitbox_anchor = key
        if self._auto_baked:
            self._apply_hitbox_shaping()
        _bump_collision_epoch(self)

    @property
    def scale(self) -> Tuple[float, float]:
        """Margin ``(sx, sy)``. Write a scalar or a pair; read is always a pair."""
        sx, sy = self._hitbox_scale
        return (float(sx), float(sy))

    @scale.setter
    def scale(self, value) -> None:
        self._refuse_dead("scale")
        self._refuse_art_write("scale")
        pair = _parse_hitbox_scale(value, what="scale")
        if pair == self._hitbox_scale:
            return
        self._hitbox_scale = pair
        if self._auto_baked:
            self._apply_hitbox_shaping()
        _bump_collision_epoch(self)

    @property
    def box(self):
        """A Box around this hitbox as it is now (current cell, pose), or ``None``.

        Screen-aligned: ``hb.box.width`` / ``left`` / ``bottom`` / … are the
        collider's bounds. ``None`` when there is no collider on this frame
        (an empty bake). Measured whether or not the hitbox is ``active``.
        """
        if self._host_ref() is None or self._removed:
            return None
        from .collision import _prims_from_collision_specs
        return _box_of_prims(_prims_from_collision_specs(self._collision_specs()))

    box = box.setter(_read_only(
        "hb.box is a measurement (a new Box each read). Change the hitbox itself: "
        "hb.shape / hb.scale / hb.anchor."
    ))

    def __getattr__(self, name: str):
        if name in _RETIRED_KNOBS:
            raise AttributeError(_retired_knob_message(name))
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    def _refuse_art_write(self, knob: str) -> None:
        if self._px is not None:
            name = "px_rect" if self._px[0] == "rect" else "px_circle"
            raise TypeError(
                f"this hitbox has a hand-placed {name}; {knob} does not apply. "
                f"Write hb.{name} = None first to go back to the art."
            )

    @property
    def px_rect(self):
        """``(x, y, w, h)`` in the frame's pixels (top-left corner, y down), or ``None``."""
        return self._px[1] if self._px is not None and self._px[0] == "rect" else None

    @px_rect.setter
    def px_rect(self, value) -> None:
        self._set_px("rect", value)

    @property
    def px_circle(self):
        """``(x, y, r)`` in the frame's pixels (centre, y down), or ``None``."""
        return self._px[1] if self._px is not None and self._px[0] == "circle" else None

    @px_circle.setter
    def px_circle(self, value) -> None:
        self._set_px("circle", value)

    def _set_px(self, which: str, value) -> None:
        self._require_alive(f"px_{which}")
        if as_payload(value) is None:
            if self._px is None or self._px[0] != which:
                return
            new = None
        else:
            from .sprite import Svg
            if isinstance(self._host_ref(), Svg):
                raise TypeError(
                    f"px_{which}= needs a sprite sheet; an Svg has no pixels."
                )
            parse = _parse_px_rect if which == "rect" else _parse_px_circle
            new = (which, parse(value))
            if new == self._px:
                return
        self._px = new
        # A px shape leaves the art knobs at their defaults; ``None`` returns
        # the part to the default art bake (``"auto"`` / ``"each"``).
        self._hitbox_kind = "auto"
        self._hitbox_from = "each"
        self._hitbox_anchor = "center"
        self._hitbox_scale = (1.0, 1.0)
        self._invalidate_auto_bake()

    # --- claims and enrollment -------------------------------------------------

    def _require_alive(self, what: str):
        """The host for a write; ``DestroyedError`` when out of play."""
        self._refuse_dead(what)
        return self.host

    def _claim(self, name: str) -> None:
        host = self._host_ref()
        claims = host._hitbox_claims
        if claims is None:
            claims = {}
            host._hitbox_claims = claims
        claims[name] = self
        self._claims.add(name)
        from .collision import _collision_system
        sys = _collision_system
        body = getattr(host, "_collider", None)
        if sys is not None and body is not None:
            # The body stops answering for this group.
            sys._tag_remove(name, body)
        if name in host.group:
            if sys is not None and name in sys._pair_tags:
                sys._try_enroll_item(host, tag=name)
        else:
            host.add_to_group(name)
            self._added.add(name)

    def _unclaim(self, name: str) -> bool:
        """Stop answering for ``name``. True when this claim had put the host
        in the group, so the host leaves it too; a group the host was in on
        its own stays (graphics review HP13: removing a weak spot took the
        boss out of ``"enemy"``)."""
        host = self._host_ref()
        self._claims.discard(name)
        added = name in self._added
        self._added.discard(name)
        claims = host._hitbox_claims if host is not None else None
        if claims is not None and claims.get(name) is self:
            del claims[name]
        from .collision import _collision_system
        sys = _collision_system
        if sys is not None and self._collider is not None:
            sys._tag_remove(name, self._collider)
        return added

    def _enroll_claims(self) -> None:
        """Enroll under every claimed group the host is currently in."""
        host = self.host
        if host is None:
            return
        from .collision import _collision_system
        sys = _collision_system
        if sys is None:
            return
        for name in list(self._claims):
            if name in host.group and name in sys._pair_tags:
                sys._try_enroll_item(host, tag=name)

    def _retire_collider(self) -> None:
        """Leave collision now (fires ``@collide_exit`` for open contacts)."""
        col = self._collider
        self._collider = None
        self._collidable = False
        if col is not None:
            col._unregister()

    def _detach(self) -> None:
        """``remove_hitbox`` / host teardown: drop claims, leave collision."""
        if self._removed:
            return
        host = self._host_ref()
        for name in list(self._claims):
            if self._unclaim(name) and host is not None and getattr(host, "is_alive", False) \
                    and name in host.group:
                host.remove_from_group(name)
        self._retire_collider()
        self._removed = True
        _LIVE_PARTS.discard(self)
        _LINKED_PARTS.discard(self)

    # --- collision-shape protocol (read by ``collision.py``) ---------------------

    @property
    def _node_id(self):
        """Host graph node id while alive; ``None`` lets ``Collider.shapes`` prune it."""
        host = self._host_ref()
        if host is None or self._removed:
            return None
        return getattr(host, "_node_id", None)

    @property
    def layer(self):
        """The host Sprite's layer (a part follows its Sprite). Read-only."""
        host = self._host_ref()
        return getattr(host, "layer", None) if host is not None else None

    layer = layer.setter(_read_only(
        "hb.layer is its sprite's layer; move the sprite: sprite.layer = ..."
    ))

    @property
    def _collision_opt_out(self) -> bool:
        """In play only while the part is on and its host is collidable and active."""
        if not self._active:
            return True
        host = self._host_ref()
        if host is None:
            return True
        if getattr(host, "_collision_opt_out", False):
            return True
        return not getattr(host, "active", True)

    @property
    def _collision_epoch(self) -> int:
        """Host epoch + own epoch: either bump invalidates the part snapshot."""
        host = self._host_ref()
        base = int(getattr(host, "_collision_epoch", 0) or 0) if host is not None else 0
        return base + self._part_epoch

    @_collision_epoch.setter
    def _collision_epoch(self, value) -> None:
        # ``_bump_collision_epoch`` writes ``epoch + 1``; keep only our share.
        host = self._host_ref()
        base = int(getattr(host, "_collision_epoch", 0) or 0) if host is not None else 0
        self._part_epoch = int(value) - base

    def _pull_property_anchors(self) -> None:
        host = self._host_ref()
        if host is None:
            return
        pull = getattr(type(host), "_pull_property_anchors", None)
        if pull is not None:
            pull(host)

    def _collision_pose_anchor(self) -> Tuple[float, float]:
        host = self._host_ref()
        if host is None:
            return (0.0, 0.0)
        from .shapes import get_xy
        return get_xy(host.center, bare=True)

    def _collision_pose_extra(self) -> Tuple[float, ...]:
        """Paint pose (heading, tilt, seat, flips, size) for the snapshot cache."""
        key = self._pose_key()
        return key[3:] if key else ()

    def _pose_key(self) -> tuple:
        """Whole snapshot key ``(epoch, x, y, *paint pose)`` in one pass.

        ``_collision_pose_key`` calls this for parts (one host anchor read;
        no seat work while ``tilt`` is a bare angle). Keep the tuple shape
        stable: the translate fast path compares ``key[3:]``.
        """
        host = self._host_ref()
        if host is None:
            return ()
        pull = getattr(type(host), "_pull_property_anchors", None)
        if pull is not None:
            pull(host)
        cx, cy = self._collision_pose_anchor()
        if getattr(host, "_tilt_mode", "angle") == "angle":
            tilt = float(host._tilt)
            seat_x = seat_y = 0.0
        else:
            tilt = float(host._tilt_angle_for_paint())
            seat_x, seat_y = host._tilt_seat_local(cx, cy)
        w, h = self._hitbox_pose_wh()
        return (
            int(self._collision_epoch),
            float(cx),
            float(cy),
            float(host._draw_angle()),
            tilt,
            float(seat_x),
            float(seat_y),
            float(host._scale),
            float(w),
            float(h),
            1.0 if host._flip_x else 0.0,
            1.0 if host._flip_y else 0.0,
            float(host._offset_x),
            float(host._offset_y),
        )

    def _has_locals(self) -> bool:
        return bool(
            self._hitbox_circle is not None
            or self._hitbox_circles
            or self._hitbox_ellipse is not None
            or self._hitbox_ellipses
            or self._hitbox_poly
            or self._hitbox_boxes
        )

    def _paint_placement(self, host) -> Tuple[float, float, float, float, float]:
        """``(tx, ty, ang, ox, oy)``: where paint puts the cell origin.

        Paint: flip the cell, tilt it about the pivot, add the seat, turn by
        the heading. That is a rotation by ``ang = draw + tilt`` about
        ``(tx, ty)``; ``(ox, oy)`` is the flipped offset, turned by ``ang``.
        """
        cx, cy = self._collision_pose_anchor()
        draw = math.radians(float(host._draw_angle()))
        tilt_deg = float(host._tilt_angle_for_paint())
        seat_x, seat_y = host._tilt_seat_local(cx, cy)
        # Translation from pivot tilt + seat, in post-heading space.
        qx, qy = float(seat_x), float(seat_y)
        tilt = 0.0
        if abs(tilt_deg) > 1e-12:
            tilt = math.radians(tilt_deg)
            px, py = host._tilt_pivot_local()
            ct, st = math.cos(tilt), math.sin(tilt)
            qx += px - (ct * px - st * py)
            qy += py - (st * px + ct * py)
        cd, sd = math.cos(draw), math.sin(draw)
        tx = cx + cd * qx - sd * qy
        ty = cy + sd * qx + cd * qy
        ox, oy = host._apply_local_flip(float(host._offset_x), float(host._offset_y))
        return tx, ty, draw + tilt, ox, oy

    def _collision_specs(self) -> List[Tuple]:
        """World prims of this part, placed the way the host is painted.

        The paint placement is a rigid turn plus a translation, so the body's
        emitter places the locals once that translation is known.
        Empty bake → ``[]`` (no design-box fallback).
        """
        host = self._host_ref()
        if host is None or self._removed:
            return []
        self._ensure_auto_baked()
        if not self._has_locals():
            return []
        w, h = self._hitbox_pose_wh()
        w, h = abs(float(w)), abs(float(h))
        tx, ty, ang, ox, oy = self._paint_placement(host)
        c, sn = math.cos(ang), math.sin(ang)
        pcx = tx + ox * c - oy * sn
        pcy = ty + ox * sn + oy * c
        return _emit_baked_specs(self, host, pcx, pcy, ang, w, h)

    def _proxy_aabb(self) -> Optional[Tuple[float, float, float, float]]:
        """Cheap broad-phase bound (no prims): the body's extent box, placed by paint.

        Every baked prim (and its own AABB) sits in ``|lx| <= ex*w, |ly| <= ey*h``
        about the flipped-offset origin; the AABB of that box turned by ``ang``
        holds them all (same bound as the Sprite body). The offset is rotation-
        free, so it pads by ``hypot(offset)``. ``None`` for an empty bake (the
        caller then finds no prims and leaves the proxy invalid).
        """
        host = self._host_ref()
        if host is None or self._removed:
            return None
        self._ensure_auto_baked()
        if not self._has_locals():
            return None
        w, h = self._hitbox_pose_wh()
        w, h = abs(float(w)), abs(float(h))
        ex, ey = self._hitbox_extents_for_pose(w, h)
        tx, ty, ang, ox, oy = self._paint_placement(host)
        exw, eyh = ex * w, ey * h
        c, sn = abs(math.cos(ang)), abs(math.sin(ang))
        hx = c * exw + sn * eyh
        hy = sn * exw + c * eyh
        if ox or oy:
            pad = math.hypot(ox, oy)
            hx += pad
            hy += pad
        return (tx - hx, ty - hy, tx + hx, ty + hy)

    # --- px shape bake ------------------------------------------------------------

    def _px_geometry_key(self, idx: int):
        """What a px bake depends on: the cell's source size and its pivot.

        ``_frame_at`` hands back the pivot-applied cell (``Sheet(anchor=)``,
        atlas pivot, ``clip(offset=)``), so cells that share this key convert
        the same numbers to the same locals.
        """
        fr = self._sheet._frame_at(int(idx))
        return (float(fr.src_w), float(fr.src_h), float(fr.pivot_x), float(fr.pivot_y))

    def _ensure_auto_baked(self) -> None:
        if self._px is None:
            return super()._ensure_auto_baked()
        idx = int(self._still_hitbox_index())
        key = self._px_geometry_key(idx)
        if self._auto_baked and self._hitbox_baked_key == key:
            self._hitbox_frame = idx
            return
        self._clear_auto_hitbox()
        fr = self._sheet._frame_at(idx)
        self._hitbox_ref_src_w = float(fr.src_w)
        self._hitbox_ref_src_h = float(fr.src_h)
        which, nums = self._px
        if which == "rect":
            self._hitbox_boxes = boxes_to_local((nums,), fr)
        else:
            c = circle_to_local(nums[0], nums[1], nums[2], fr)
            self._hitbox_circle = c
            self._hitbox_circles = (c,)
        self._hitbox_frame = idx
        self._hitbox_baked_key = key
        self._commit_hitbox_base()

    def _sync_auto_hitbox_frame(self) -> None:
        """Playhead tick. A px shape rebakes only when the cell geometry changes."""
        if self._px is None:
            return super()._sync_auto_hitbox_frame()
        if not self._play_frames:
            return
        idx = int(self._still_hitbox_index())
        if int(self._hitbox_frame) == idx:
            return
        if self._auto_baked and self._hitbox_baked_key == self._px_geometry_key(idx):
            # Same size and pivot: same locals; keep the pose cache warm.
            self._hitbox_frame = idx
            return
        _bump_collision_epoch(self)
        self._ensure_auto_baked()

    # --- bake host protocol (see ``_HitboxBakeMixin``) --------------------------

    @property
    def _sheet(self):
        return self._host_ref()._sheet

    @property
    def _play_frames(self):
        return self._host_ref()._play_frames

    @property
    def _play_name(self):
        return self._host_ref()._play_name

    @property
    def _frame(self):
        return self._host_ref()._frame

    @property
    def _construct_frame(self):
        return self._host_ref()._construct_frame

    def _current_frame_index(self) -> int:
        return self._host_ref()._current_frame_index()

    @property
    def _size_intent(self):
        return getattr(self._host_ref(), "_size_intent", "default")

    @property
    def _size_intent_value(self):
        return getattr(self._host_ref(), "_size_intent_value", None)

    @property
    def _scale(self):
        return self._host_ref()._scale

    def _du_per_px(self):
        return self._host_ref()._du_per_px()


for _name in _RETIRED_KNOBS:
    setattr(Hitbox, _name, _RetiredKnob(_name))
del _name


class _MainHitbox(Hitbox):
    """``graphic.hitbox``: the collider the Graphic itself answers with.

    A view, made once per Graphic and cached: every knob forwards to the
    host's own state (``_hitbox_kind`` / ``_hitbox_from`` / … on a Sprite;
    a Shape's geometry *is* its hitbox, so a Shape's knobs refuse). It stands
    and is pushed by ``resolve()``; ``@collide`` naming the Graphic means it.
    It is not a part: no group claims, no px shape, not removable. ``active``
    switches it alone (parts keep detecting); ``collidable`` switches every
    hitbox of the Graphic.
    """

    _is_hitbox_part = False
    _is_main = True
    __slots__ = ()

    @classmethod
    def _for(cls, host) -> "_MainHitbox":
        view = object.__new__(cls)
        object.__setattr__(view, "_host_ref", weakref.ref(host))
        object.__setattr__(view, "_removed", False)
        object.__setattr__(view, "_px", None)
        object.__setattr__(view, "_claims", frozenset())
        object.__setattr__(view, "_site", None)
        object.__setattr__(view, "_active_link", None)
        object.__setattr__(view, "_link_site", None)
        object.__setattr__(view, "_link_busy", False)
        return view

    # --- which host ------------------------------------------------------------

    def _sprite_host(self, knob: str, *, write: bool = False):
        """The host when it is a Sprite (knobs apply); a Shape refuses.

        Reads keep answering after ``destroy()`` (like a dead actor's pose);
        a write raises ``DestroyedError``.
        """
        host = self._host_ref()
        if host is None:
            raise _dead_hitbox_error(self, knob)
        if write:
            self._refuse_dead(knob)
        from .sprite import Sprite
        if isinstance(host, Sprite):
            return host
        kind = type(host).__name__
        raise TypeError(
            f"a {kind}'s hitbox is its own geometry; {knob} does not apply. "
            f"Change the {kind} itself (its size, points, rotation)."
        )

    def __repr__(self) -> str:
        host = self._host_ref()
        # The stored state: a repr does not run the active link (HP8).
        state = "removed" if not self.is_alive else ("on" if self._active_raw() else "off")
        from .sprite import Sprite
        if isinstance(host, Sprite):
            shape = f"{host._hitbox_kind}/{host._hitbox_from!r}"
        else:
            shape = type(host).__name__.lower()
        return f"<Hitbox main {shape} of {host!r} {state}>"

    @property
    def is_alive(self) -> bool:
        host = self._host_ref()
        return host is not None and bool(getattr(host, "is_alive", False))

    is_alive = is_alive.setter(_read_only(
        "hitbox.is_alive follows its Graphic. The main hitbox is not removed: "
        "switch it off with g.hitbox.active = False."
    ))

    @property
    def host(self):
        """The Graphic this hitbox belongs to (``None`` after it is destroyed)."""
        host = self._host_ref()
        if host is None or not getattr(host, "is_alive", False):
            return None
        return host

    host = host.setter(_read_only(
        "g.hitbox.host is the Graphic itself; the main hitbox does not move."
    ))

    # --- the four knobs --------------------------------------------------------

    @property
    def shape(self) -> str:
        """Sprite: ``"auto"`` / ``"rect"`` / … (``Sprite(hitbox_shape=)``).
        Shape: its kind (``"rect"``, ``"circle"``, …), read-only."""
        host = self._host_ref()
        if host is None:
            raise _dead_hitbox_error(self, "shape")
        from .sprite import Sprite
        if isinstance(host, Sprite):
            return host._hitbox_kind
        return type(host).__name__.lower()

    @shape.setter
    def shape(self, value) -> None:
        self._sprite_host("shape", write=True)._set_hitbox(value)

    @property
    def source(self):
        """Which art defines the main hitbox (``Sprite(hitbox_source=)``)."""
        return self._sprite_host("source")._hitbox_from

    @source.setter
    def source(self, value) -> None:
        self._sprite_host("source", write=True)._set_hitbox_source(value)

    @property
    def anchor(self):
        """Fixed point for ``scale``, replacement, and ``.tilt``."""
        return self._sprite_host("anchor")._hitbox_anchor

    @anchor.setter
    def anchor(self, value) -> None:
        self._sprite_host("anchor", write=True)._set_hitbox_anchor(value)

    @property
    def scale(self) -> Tuple[float, float]:
        """Margin ``(sx, sy)``. Write a scalar or a pair; read is always a pair."""
        sx, sy = self._sprite_host("scale")._hitbox_scale
        return (float(sx), float(sy))

    @scale.setter
    def scale(self, value) -> None:
        self._sprite_host("scale", write=True)._set_hitbox_scale(value)

    # --- on / off --------------------------------------------------------------

    @property
    def active(self) -> bool:
        """``False`` switches the main hitbox off; parts keep detecting.

        Off: no ``resolve()``, ``touching_*`` clears, ``@collide`` naming the
        Graphic goes quiet (exits fire), unnamed queries skip it. Linked
        (``g.hitbox["active"] @= fn``): each read calls ``fn`` and applies it.
        """
        if self._active_link is not None:
            if self._link_busy:
                raise ValueError(
                    "the formula linked to this hitbox's active reads itself "
                    f"(hitbox.active inside hitbox['active'] @= …, linked at "
                    f"{_site_text(self._link_site)})."
                )
            self._refresh_link()
        host = self._host_ref()
        return host is not None and not host.__dict__.get("_main_hitbox_off", False)

    @active.setter
    def active(self, value) -> None:
        self._refuse_dead("active")
        if callable(as_payload(value)):
            raise CallableAssignError(callable_assign_message("hitbox", "active"))
        if self._active_link is not None:
            raise LinkedAttributeError(
                "this hitbox's active is linked (hitbox['active'] @= …, at "
                f"{_site_text(self._link_site)}); call hitbox['active'].unlink() "
                "before writing it."
            )
        self._apply_active(_expect_flag(value, 'active'))

    def _active_raw(self) -> bool:
        """The stored on / off, without running a link (repr)."""
        host = self._host_ref()
        return host is not None and not host.__dict__.get("_main_hitbox_off", False)

    def _apply_active(self, want: bool) -> None:
        host = self._host_ref()
        if host is None:
            return
        off = not want
        if bool(host.__dict__.get("_main_hitbox_off", False)) == off:
            return
        host._main_hitbox_off = off
        _bump_collision_epoch(host)

    # --- measure ---------------------------------------------------------------

    @property
    def box(self):
        """A Box around the main hitbox as it is now, or ``None`` (no collider).

        Screen-aligned bounds of the collider the engine uses — for a Sprite
        the baked hitbox (``source`` decides which art), not the drawn cell
        (``sprite.box``). Measured whether or not it is ``active``.
        """
        host = self._host_ref()
        if host is None or not getattr(host, "is_alive", False):
            return None
        from .collision import _snapshot_shape_uncached
        return _box_of_prims(_snapshot_shape_uncached(host, include_off=True))

    box = box.setter(_read_only(
        "g.hitbox.box is a measurement (a new Box each read). Change the hitbox "
        "itself: sprite.hitbox.shape / .scale / .anchor (a Shape: the Shape)."
    ))

    # --- what a part has and the main hitbox does not --------------------------

    def _not_a_part(self, what: str):
        raise TypeError(
            f"hitbox.{what}: the main hitbox answers for the sprite's own groups "
            "(sprite.tag(...), sprite.untag(...)). Group claims belong to extra "
            "hitboxes: sprite.add_hitbox(group=...)."
        )

    @property
    def group(self) -> frozenset:
        """The groups the main hitbox answers for: the Graphic's groups minus
        those an extra hitbox claims (that one answers instead). Read-only;
        change them on the Graphic (``sprite.tag`` / ``untag``)."""
        host = self._host_ref()
        if host is None:
            return frozenset()
        claims = getattr(host, "_hitbox_claims", None) or {}
        return frozenset(g for g in host.group if g not in claims)

    group = group.setter(_read_only(
        "g.hitbox.group is the Graphic's groups minus those an extra hitbox "
        "claims; change them with sprite.tag(...) / sprite.untag(...)."
    ))

    def add_to_group(self, groupid: str):
        self._not_a_part("add_to_group")

    def remove_from_group(self, groupid: str):
        self._not_a_part("remove_from_group")

    def tag(self, *names: str):
        self._not_a_part("tag")

    def untag(self, *names: str):
        self._not_a_part("untag")

    def tagged(self, name: str) -> bool:
        """True when the main hitbox answers for ``name`` (see ``group``)."""
        from .entity import _require_group_name
        return _require_group_name(name, "tagged") in self.group

    @property
    def px_rect(self):
        return None

    @px_rect.setter
    def px_rect(self, value) -> None:
        self._refuse_px("px_rect")

    @property
    def px_circle(self):
        return None

    @px_circle.setter
    def px_circle(self, value) -> None:
        self._refuse_px("px_circle")

    def _refuse_px(self, which: str) -> None:
        raise TypeError(
            f"{which}= places an extra hitbox by hand; the main hitbox is shaped "
            "by shape / source / anchor / scale. For a hand-placed box, "
            f"add one: sprite.add_hitbox({which}=...)."
        )


def _main_hitbox_of(host) -> _MainHitbox:
    """``graphic.hitbox``: the cached main view (one per Graphic)."""
    view = host.__dict__.get("_main_hitbox_view")
    if view is None:
        view = _MainHitbox._for(host)
        host.__dict__["_main_hitbox_view"] = view
    return view


def _refresh_linked_parts() -> None:
    """``step()`` preamble: apply every linked ``active`` before the proxies."""
    if not _LINKED_PARTS:
        return
    for part in list(_LINKED_PARTS):
        if not part.is_alive:
            _LINKED_PARTS.discard(part)     # host destroyed: no _detach ran
            continue
        part._refresh_link()
