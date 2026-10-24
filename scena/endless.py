"""Endless: fill the part of a layer the camera sees, slot by slot.

The axis (or a grid) is cut into **slots**. For each slot near the layer's
view, ``Endless`` builds what goes there ahead of the view and destroys it
once the slot falls far behind. The tool owns *when* and *where*; the author
owns *what* (image paths, or a builder ``fn(slot)``). Canvas Design, "Endless
fill".
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from ._weakset import OrderedWeakSet
from .entity import Entity, Graphic

# Live Endless instances, for the fill after the process tick.
_LIVE_ENDLESS = OrderedWeakSet()    # filled in creation order (RA3)


def refill_after_tick() -> None:
    """Frame body, right after the process tick: an Endless whose view moved
    after its own ``on_update`` filled (a camera moved by a later actor or a
    timer) fills again, so a frame with a long ``dt`` never paints an empty
    strip at the leading edge (review 2026-10-09 W-T6). One view read when the
    view did not move."""
    if not _LIVE_ENDLESS:
        return
    for e in list(_LIVE_ENDLESS):
        if not e.is_alive:
            _LIVE_ENDLESS.discard(e)
            continue
        if not e.active:
            continue
        v = e._view()
        if (v.left, v.right, v.bottom, v.top) != getattr(e, "_filled_view", None):
            e._fill(v)
from .registry import BUILT_IN_LAYERS, normalize_layer_name

__all__ = ["Endless", "Slot"]

# Live slots (cells for ``"xy"``) one Endless keeps at most. Extreme zoom-out
# over small slots stops filling here and warns once instead of building
# hundreds of pieces per frame.
_SLOT_CAP = 256

# Fill margins, as fractions of the view's extent along each axis. ``ahead``
# < ``behind``: the band between them is the spatial hysteresis that keeps a
# camera hovering at a boundary from rebuilding the same slot every frame.
_AHEAD = 0.5
_BEHIND = 1.0

_M64 = (1 << 64) - 1


def _splitmix64(z: int) -> int:
    z = (z + 0x9E3779B97F4A7C15) & _M64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
    return z ^ (z >> 31)


def _mix(*parts: int) -> int:
    """One 64-bit seed from ints (negative ones too). Not ``hash(tuple)``:
    tuples are not valid ``random`` seeds, and integer arithmetic gives the
    same stream on every Python version."""
    h = 0x6A09E667F3BCC909
    for p in parts:
        h = _splitmix64(h ^ (int(p) & _M64))
    return h


class Slot:
    """The place a builder fills: index, absolute edges, and its own random stream.

    ``i`` (and ``j`` for ``axis="xy"``): slot index, 0 at ``start``, negative
    behind it. Edges along the endless axes are **absolute** world coordinates
    (layer coordinates on a parallax layer): ``left`` / ``right`` for
    ``axis="x"``, ``bottom`` / ``top`` for ``axis="y"``, all four plus ``box``
    for ``"xy"``. ``rng`` is a ``random.Random`` seeded by the run seed and the
    index: the same slot always draws the same numbers (swap ``random.`` for
    ``slot.rng.``). ``chance(p)`` draws from the same stream.
    """

    __slots__ = ("_i", "_j", "_left", "_right", "_bottom", "_top", "_rng", "_axis")

    def __init__(self, axis, i, j, left, right, bottom, top, rng):
        self._axis = axis
        self._i = i
        self._j = j
        self._left = left
        self._right = right
        self._bottom = bottom
        self._top = top
        self._rng = rng

    def _edge(self, name, value, axis_needed):
        if value is None:
            raise AttributeError(
                f"slot.{name}: an axis={self._axis!r} slot has no {name} edge "
                f"(it is endless along {axis_needed!r} only). Place the other "
                f"axis yourself, e.g. a fixed y for a side-scroller."
            )
        return value

    @property
    def i(self) -> int:
        """Slot index along the endless axis (column for ``"xy"``)."""
        return self._i

    @property
    def j(self) -> int:
        """Row index (``axis="xy"`` only)."""
        if self._j is None:
            raise AttributeError(
                f"slot.j exists only with axis='xy'; this slot is axis={self._axis!r} (use slot.i)."
            )
        return self._j

    @property
    def left(self) -> float:
        """Left edge (world x), axis ``"x"`` / ``"xy"``."""
        return self._edge("left", self._left, "y")

    @property
    def right(self) -> float:
        """Right edge (world x), axis ``"x"`` / ``"xy"``."""
        return self._edge("right", self._right, "y")

    @property
    def bottom(self) -> float:
        """Bottom edge (world y), axis ``"y"`` / ``"xy"``."""
        return self._edge("bottom", self._bottom, "x")

    @property
    def top(self) -> float:
        """Top edge (world y), axis ``"y"`` / ``"xy"``."""
        return self._edge("top", self._top, "x")

    @property
    def box(self):
        """The cell as a ``Box`` (``axis="xy"`` only)."""
        if self._j is None:
            raise AttributeError(
                f"slot.box exists only with axis='xy' (a 1D slot has no cross-axis "
                f"extent). Use slot.{'left / slot.right' if self._axis == 'x' else 'bottom / slot.top'}."
            )
        from .box import Box
        return Box._from_aabb(self._left, self._bottom, self._right, self._top)

    @property
    def rng(self) -> random.Random:
        """This slot's ``random.Random``: same slot, same numbers."""
        return self._rng

    def chance(self, p) -> bool:
        """``True`` with probability ``p`` (0..1), drawn from this slot's stream."""
        from .scenamath import _chance_probability
        return self._rng.random() < _chance_probability(p, "slot.chance")

    def __repr__(self) -> str:
        if self._axis == "xy":
            return (f"Slot(i={self._i}, j={self._j}, left={self._left:g}, "
                    f"bottom={self._bottom:g}, right={self._right:g}, top={self._top:g})")
        if self._axis == "x":
            return f"Slot(i={self._i}, left={self._left:g}, right={self._right:g})"
        return f"Slot(i={self._i}, bottom={self._bottom:g}, top={self._top:g})"


def _positive(value, what: str) -> float:
    from .validate import number
    v = number(value, what)
    if v <= 0.0:
        raise ValueError(f"{what} must be > 0, got {value!r}")
    return v


class Endless(Entity):
    """Fill the part of a layer the camera sees with pieces, slot by slot, forever.

    Each frame ``Endless`` reads ``layer.view`` and builds the slots that come
    near it (a little ahead of the view) and destroys the slots that fell far
    behind. Walking back rebuilds the **same** piece: each slot draws from its
    own seeded stream. It never moves the camera and never moves its pieces.

    Args:
        layer: A layer of its own (name or number), made with
            ``canvas.layers.create(...)``. ``default`` / ``top`` / ``ui`` raise:
            pieces made during play would paint over the player.
        pieces: An image path, a list of image paths (one picked per slot), or
            a builder ``fn(slot)`` returning a Graphic, a list of Graphics, or
            ``[]`` for an empty slot, built at the absolute ``slot``
            coordinates.
        axis: ``"x"`` (side-scroller), ``"y"`` (vertical) or ``"xy"`` (grid).
        step: Slot size along the axis: a number; a pair ``(w, h)`` for
            ``"xy"`` (required there); or a function ``step(slot) -> width``
            for widths that vary. Required with a builder. Omitted with images:
            each image's size along the axis plus ``gap``.
        gap: Space after each image (a number, or ``(lo, hi)`` drawn per
            slot). Measured image pieces only.
        start: Axis coordinate of slot 0's leading edge (a pair for ``"xy"``).
            Default: the view's near edge when ``Endless`` is created.
        seed: ``None`` → a new world each run; an int → the same world every
            run. Read the one in use from ``.seed``.
        bottom: Image pieces with ``axis="x"``: y of their bottom edge
            (default: the view's bottom at creation).
        left: Image pieces with ``axis="y"``: x of their left edge (default:
            the view's left at creation).
        group: Group tag(s) for image pieces (builders set their own).
        height / width / size: Image pieces: the size of each piece, as in
            ``Sprite(path, height=...)`` (a bare ``Sprite(path)`` is 48 units on
            its longer side). A band of background art usually wants
            ``height=`` of the screen. Builders size their own pieces.
    """

    def __init__(
        self,
        layer,
        pieces,
        *,
        axis: str = "x",
        step=None,
        gap=0,
        start=None,
        seed=None,
        bottom=None,
        left=None,
        group=None,
        height=None,
        width=None,
        size=None,
    ):
        from .canvas import ScenaCanvas
        engine = ScenaCanvas.get_current()
        layer_key = self._check_layer(engine, layer)
        axis = self._check_axis(axis)
        kind, source = self._check_pieces(pieces)
        step_kind, step_val = self._check_step(axis, kind, step)
        gap_val = self._check_gap(axis, kind, step, gap)
        cross = self._check_cross(axis, kind, bottom, left)
        if group is not None and kind == "builder":
            raise TypeError(
                "Endless group= is for image pieces; a builder gives its pieces "
                "their own group (Rect(..., group='parede'))."
            )
        sizing = self._check_sizing(kind, height=height, width=width, size=size)
        seed_val = self._check_seed(seed)

        self._construct(layer=None)
        self._layer_key = layer_key
        self._axis = axis
        self._kind = kind
        self._source = source
        self._step_kind = step_kind
        self._step = step_val
        self._gap = gap_val
        self._group = group
        self._sizing = sizing
        self._seed = seed_val
        self._extent_cache: Dict[str, Tuple[float, float]] = {}
        # 1D variable widths: index → (near, far). Fixed steps need no cache.
        self._edges: Dict[int, Tuple[float, float]] = {}
        self._hint = 0
        # Live slots: key (i, or (i, j)) → owned pieces. A key stays while its
        # slot is inside the keep window, even when its pieces are gone (a
        # piece the author destroyed is consumed until the slot comes back).
        self._live: Dict[Any, List[Graphic]] = {}
        self._warned_cap = False
        self._warned_drift = False

        v = self._view()
        if axis == "xy":
            if start is None:
                self._start = (v.left, v.bottom)
            else:
                from .validate import pair
                self._start = pair(start, "Endless start")
        else:
            if start is None:
                self._start = v.left if axis == "x" else v.bottom
            else:
                from .validate import number
                self._start = number(start, "Endless start")
        if kind == "images" and axis != "xy":
            if cross is None:
                cross = v.bottom if axis == "x" else v.left
        self._cross = cross
        if self._layer_obj()._is_neutral_response:
            self._view0 = (v.left, v.bottom, v.right, v.top)
        else:
            self._view0 = None
        if axis != "xy" and step_kind != "fixed":
            self._edges[0] = self._measure_from(0, self._start, forward=True)
        try:
            self._fill()                # the first frame is already full
        except BaseException:
            for key in list(self._live):
                self._release(key)
            raise
        # Strong: a one-line ``Endless("pista", ...)`` has no variable and no
        # draw slot, and the roster is weak (Actors Design, roster).
        self._scenacanvas.registry.hold(self)
        self.on_update = Endless._tick
        _LIVE_ENDLESS.add(self)

    # --- construction checks ------------------------------------------------

    @staticmethod
    def _check_layer(engine, layer):
        key = normalize_layer_name(layer)
        if key is None:
            raise TypeError(
                "Endless needs a layer name, e.g. "
                "canvas.layers.create('pista', below='default'); Endless('pista', ...)."
            )
        if key in BUILT_IN_LAYERS:
            raise ValueError(
                f"Endless needs a layer of its own, not {key!r}: pieces made during "
                f"play would paint over everything already on it (the player "
                f"included). Create one: canvas.layers.create('pista', "
                f"below='default'), then Endless('pista', ...)."
            )
        engine.registry.layers.require(key)
        return key

    @staticmethod
    def _check_axis(axis):
        if axis not in ("x", "y", "xy"):
            raise ValueError(f"Endless axis must be 'x', 'y' or 'xy', got {axis!r}")
        return axis

    @staticmethod
    def _check_pieces(pieces):
        if isinstance(pieces, str):
            return "images", (pieces,)
        if isinstance(pieces, (list, tuple)):
            if not pieces:
                raise ValueError(
                    "Endless pieces is an empty list; pass image paths or a builder fn(slot)."
                )
            if not all(isinstance(p, str) for p in pieces):
                raise TypeError(
                    "Endless pieces: a list holds image paths only. For variety "
                    "inside a slot, write a builder and pick with slot.rng.choice([...])."
                )
            return "images", tuple(pieces)
        if callable(pieces) and not isinstance(pieces, type):
            return "builder", pieces
        raise TypeError(
            f"Endless pieces must be an image path, a list of image paths, or a "
            f"builder fn(slot); got {type(pieces).__name__}"
        )

    @staticmethod
    def _check_step(axis, kind, step):
        if axis == "xy":
            if step is None or isinstance(step, (int, float)) or callable(step):
                raise TypeError(
                    "Endless axis='xy' needs a fixed cell size step=(w, h), "
                    "e.g. step=(400, 400)."
                )
            from .validate import pair
            w, h = pair(step, "Endless step")
            return "fixed", (_positive(w, "Endless step width"), _positive(h, "Endless step height"))
        if step is None:
            if kind == "builder":
                raise TypeError(
                    "a builder needs step= (a number, or a function of slot for "
                    "variable widths): Endless('pista', trecho, step=400)."
                )
            return "measured", None
        if callable(step) and not isinstance(step, type):
            return "function", step
        if isinstance(step, (tuple, list)):
            raise TypeError(
                f"Endless step=(w, h) is for axis='xy'; axis={axis!r} takes one number."
            )
        return "fixed", _positive(step, "Endless step")

    @staticmethod
    def _check_gap(axis, kind, step, gap):
        given = not (isinstance(gap, (int, float)) and not isinstance(gap, bool) and gap == 0)
        if not given:
            return 0.0
        if axis == "xy":
            raise TypeError("Endless axis='xy' has no gap= (the cells are step=(w, h)).")
        if step is not None:
            raise TypeError(
                "Endless takes step= or gap=, not both: gap= spaces measured "
                "images; with step= the slot size is the step."
            )
        from .validate import number, pair
        if isinstance(gap, (tuple, list)):
            lo, hi = pair(gap, "Endless gap")
            if lo > hi:
                raise ValueError(f"Endless gap=(lo, hi) needs lo <= hi, got {gap!r}")
            return (lo, hi)
        return number(gap, "Endless gap")

    @staticmethod
    def _check_cross(axis, kind, bottom, left):
        if axis == "x" and left is not None:
            raise TypeError("Endless axis='x' places images with bottom=, not left=.")
        if axis == "y" and bottom is not None:
            raise TypeError("Endless axis='y' places images with left=, not bottom=.")
        if axis == "xy" and (bottom is not None or left is not None):
            raise TypeError("Endless axis='xy' centers images in their cells; drop bottom= / left=.")
        value = bottom if axis == "x" else left
        if value is None:
            return None
        if kind == "builder":
            name = "bottom" if axis == "x" else "left"
            raise TypeError(
                f"Endless {name}= is for image pieces; a builder places the other "
                f"axis itself."
            )
        from .validate import number
        return number(value, "Endless bottom" if axis == "x" else "Endless left")

    @staticmethod
    def _check_sizing(kind, **given):
        sizing = {k: v for k, v in given.items() if v is not None}
        if sizing and kind == "builder":
            name = next(iter(sizing))
            raise TypeError(
                f"Endless {name}= is for image pieces; a builder sizes its own "
                f"pieces (Sprite(..., {name}=...) inside the builder)."
            )
        return sizing

    @staticmethod
    def _check_seed(seed):
        if seed is None:
            return random.getrandbits(32)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"Endless seed must be an int or None, got {type(seed).__name__}")
        return int(seed)

    # --- reads ----------------------------------------------------------------

    @property
    def seed(self) -> int:
        """The seed in use (pass it as ``seed=`` to replay the same world). Read-only."""
        return self._seed

    @property
    def pieces(self) -> list:
        """Live pieces this Endless built, in axis order (a fresh list). Read-only."""
        out = []
        for key in sorted(self._live):
            out.extend(p for p in self._live[key] if p.is_alive)
        return out

    def index_at(self, where):
        """Slot index holding world coordinate ``where`` (``(i, j)`` from ``(x, y)`` for ``"xy"``)."""
        from .validate import number, pair
        if self._axis == "xy":
            x, y = pair(where, "Endless.index_at")
            (x0, y0), (w, h) = self._start, self._step
            return (math.floor((x - x0) / w), math.floor((y - y0) / h))
        if isinstance(where, (tuple, list)):
            raise TypeError(
                f"Endless.index_at takes one coordinate along axis={self._axis!r}; "
                f"pass {'x' if self._axis == 'x' else 'y'} only."
            )
        return self._index_at(number(where, "Endless.index_at"))

    # --- slot geometry (1D) -----------------------------------------------------

    def _stream(self, i, j=None) -> random.Random:
        parts = (self._seed, i) if j is None else (self._seed, i, j)
        return random.Random(_mix(*parts))

    def _engine_draws(self, i, rng, slot):
        """The draws the engine makes from slot ``i``'s stream before the
        builder runs: the image pick and the gap, or the ``step(slot)`` width.
        Returns ``(extent_or_width, path, gap)``."""
        if self._kind == "images":
            path = rng.choice(self._source)
        else:
            path = None
        if self._step_kind == "function":
            width = self._step(slot)
            try:
                width = float(width)
            except (TypeError, ValueError):
                raise TypeError(
                    f"Endless step(slot) must return a number, got "
                    f"{type(width).__name__} for slot i={i}"
                ) from None
            if not math.isfinite(width) or width <= 0.0:
                raise ValueError(
                    f"Endless step(slot) returned {width!r} for slot i={i}; a width "
                    f"must be a finite number > 0."
                )
            return width, path, 0.0
        if self._step_kind == "measured":
            gap = self._gap
            if isinstance(gap, tuple):
                gap = rng.uniform(gap[0], gap[1])
            extent = self._measure_image(path)
            width = extent + gap
            if not math.isfinite(width) or width <= 0.0:
                raise ValueError(
                    f"Endless slot i={i}: image {path!r} is {extent:g} wide plus gap "
                    f"{gap:g} = {width:g}; a slot must be wider than 0. Pass step=."
                )
            return width, path, gap
        return self._step, path, 0.0

    def _measure_image(self, path) -> float:
        """Size of ``Sprite(path)`` along the axis, measured once per path from a
        throwaway Sprite so it always matches the pieces actually built."""
        size = self._extent_cache.get(path)
        if size is None:
            from .sprite import Sprite
            probe = Sprite(path, layer=None, **self._sizing)
            try:
                size = (float(probe.width), float(probe.height))
            finally:
                probe.destroy()
            self._extent_cache[path] = size
        return size[0] if self._axis == "x" else size[1]

    def _width_of(self, i) -> float:
        rng = self._stream(i)
        slot = self._slot_1d(i, None, None, rng)
        return self._engine_draws(i, rng, slot)[0]

    def _measure_from(self, i, edge, *, forward):
        w = self._width_of(i)
        return (edge, edge + w) if forward else (edge - w, edge)

    def _bounds(self, i) -> Tuple[float, float]:
        """``(near, far)`` of slot ``i`` along the axis (cached for variable widths)."""
        if self._step_kind == "fixed":
            near = self._start + i * self._step
            return near, near + self._step
        edges = self._edges
        got = edges.get(i)
        if got is not None:
            return got
        if i > 0:
            k = max(k for k in edges if k < i)
            while k < i:
                k += 1
                edges[k] = self._measure_from(k, edges[k - 1][1], forward=True)
        else:
            k = min(k for k in edges if k > i)
            while k > i:
                k -= 1
                edges[k] = self._measure_from(k, edges[k + 1][0], forward=False)
        return edges[i]

    def _index_at(self, x: float) -> int:
        if self._step_kind == "fixed":
            return math.floor((x - self._start) / self._step)
        # Walk from the last answer: per frame the view moves a slot or two,
        # so this is O(distance), not O(slots ever visited).
        i = self._hint
        near, far = self._bounds(i)
        while x >= far:
            i += 1
            near, far = self._bounds(i)
        while x < near:
            i -= 1
            near, far = self._bounds(i)
        self._hint = i
        return i

    def _slot_1d(self, i, near, far, rng) -> Slot:
        if self._axis == "x":
            return Slot("x", i, None, near, far, None, None, rng)
        return Slot("y", i, None, None, None, near, far, rng)

    # --- per-frame fill -------------------------------------------------------

    def _layer_obj(self):
        return self._scenacanvas.registry.layers.require(self._layer_key)

    def _view(self):
        return self._layer_obj().view

    def _tick(self, dt) -> None:
        self._fill()

    def _fill(self, v=None) -> None:
        if not self.is_alive:
            return
        if v is None:
            v = self._view()
        self._filled_view = (v.left, v.right, v.bottom, v.top)
        if self._axis == "xy":
            self._fill_xy(v)
        else:
            self._fill_1d(v)
        if self._view0 is not None and not self._warned_drift:
            self._check_drift(v)

    def _fill_1d(self, v) -> None:
        lo, hi = (v.left, v.right) if self._axis == "x" else (v.bottom, v.top)
        extent = max(hi - lo, 1e-9)
        keep_lo, keep_hi = lo - _BEHIND * extent, hi + _BEHIND * extent
        for key in list(self._live):
            near, far = self._bounds(key)
            if far < keep_lo or near > keep_hi:
                self._release(key)
        i0 = self._index_at(lo - _AHEAD * extent)
        i1 = self._index_at(hi + _AHEAD * extent)
        mid = self._index_at(0.5 * (lo + hi))
        # Nearest the view first, so a capped fill keeps what is on screen.
        order = sorted(range(i0, i1 + 1), key=lambda k: abs(k - mid))
        for i in order:
            if i in self._live:
                continue
            if len(self._live) >= _SLOT_CAP:
                self._warn_cap()
                break
            self._build_1d(i)

    def _fill_xy(self, v) -> None:
        (x0, y0), (w, h) = self._start, self._step
        ex, ey = max(v.width, 1e-9), max(v.height, 1e-9)
        kl, kr = v.left - _BEHIND * ex, v.right + _BEHIND * ex
        kb, kt = v.bottom - _BEHIND * ey, v.top + _BEHIND * ey
        for key in list(self._live):
            i, j = key
            cl, cb = x0 + i * w, y0 + j * h
            if cl + w < kl or cl > kr or cb + h < kb or cb > kt:
                self._release(key)
        i0 = math.floor((v.left - _AHEAD * ex - x0) / w)
        i1 = math.floor((v.right + _AHEAD * ex - x0) / w)
        j0 = math.floor((v.bottom - _AHEAD * ey - y0) / h)
        j1 = math.floor((v.top + _AHEAD * ey - y0) / h)
        mi = math.floor((0.5 * (v.left + v.right) - x0) / w)
        mj = math.floor((0.5 * (v.bottom + v.top) - y0) / h)
        cells = [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
        cells.sort(key=lambda c: max(abs(c[0] - mi), abs(c[1] - mj)))
        for key in cells:
            if key in self._live:
                continue
            if len(self._live) >= _SLOT_CAP:
                self._warn_cap()
                break
            self._build_xy(*key)

    def _build_1d(self, i) -> None:
        near, far = self._bounds(i)
        rng = self._stream(i)
        slot = self._slot_1d(i, near, far, rng)
        _w, path, _gap = self._engine_draws(i, rng, slot)
        if self._kind == "images":
            built = [self._image_piece(path, near)]
        else:
            built = self._run_builder(slot, i)
        self._live[i] = built

    def _build_xy(self, i, j) -> None:
        (x0, y0), (w, h) = self._start, self._step
        left, bottom = x0 + i * w, y0 + j * h
        rng = self._stream(i, j)
        slot = Slot("xy", i, j, left, left + w, bottom, bottom + h, rng)
        if self._kind == "images":
            from .sprite import Sprite
            path = rng.choice(self._source)
            built = [self._sprite(Sprite, path, (left + w / 2, bottom + h / 2))]
        else:
            built = self._run_builder(slot, (i, j))
        self._live[(i, j)] = built

    def _sprite(self, Sprite, path, center):
        if self._group is None:
            return Sprite(path, center=center, layer=self._layer_key, **self._sizing)
        return Sprite(path, center=center, layer=self._layer_key, group=self._group,
                      **self._sizing)

    def _image_piece(self, path, near):
        from .sprite import Sprite
        self._measure_image(path)
        w, h = self._extent_cache[path]
        if self._axis == "x":
            center = (near + w / 2, self._cross + h / 2)
        else:
            center = (self._cross + w / 2, near + h / 2)
        return self._sprite(Sprite, path, center)

    def _run_builder(self, slot, key) -> List[Graphic]:
        from .canvas import ScenaCanvas
        layers = ScenaCanvas.get_current().registry.layers
        prev = layers.default
        layers.default = self._layer_key
        try:
            result = self._source(slot)
        finally:
            layers.default = prev
        label = f"i={key}" if not isinstance(key, tuple) else f"(i, j)={key}"
        if isinstance(result, Graphic):
            built = [result]
        elif isinstance(result, (list, tuple)):
            built = list(result)
            for item in built:
                if not isinstance(item, Graphic):
                    raise TypeError(
                        f"Endless builder for slot {label} returned a list holding "
                        f"{type(item).__name__}; return Graphics (Rect, Sprite, …) "
                        f"or [] for an empty slot."
                    )
        else:
            raise TypeError(
                f"Endless builder for slot {label} returned "
                f"{'None' if result is None else type(result).__name__}; return a "
                f"Graphic, a list of Graphics, or [] for an empty slot."
            )
        for item in built:
            if item.is_alive and item.layer != self._layer_key:
                item.layer = self._layer_key
        return built

    def _release(self, key) -> None:
        for piece in self._live.pop(key, ()):
            if piece.is_alive:
                piece.destroy()

    def _warn_cap(self) -> None:
        if self._warned_cap:
            return
        self._warned_cap = True
        from .process import report_author_warning
        report_author_warning(
            "Endless",
            f"Endless on layer {self._layer_key!r}: the view covers more than "
            f"{_SLOT_CAP} slots, so filling stopped there. Use a larger step= "
            f"(or zoom out less).",
        )

    def _check_drift(self, v) -> None:
        """Treadmill sign on a gameplay layer: the camera never moved, but owned
        pieces were moved far from their slots (the screen empties, no error)."""
        if (v.left, v.bottom, v.right, v.top) != self._view0:
            self._view0 = None          # the camera moves: never warn
            return
        ex, ey = max(v.width, 1e-9), max(v.height, 1e-9)
        for key, built in self._live.items():
            if self._axis == "xy":
                (x0, y0), (w, h) = self._start, self._step
                cx, cy = x0 + (key[0] + 0.5) * w, y0 + (key[1] + 0.5) * h
            else:
                near, far = self._bounds(key)
                mid = 0.5 * (near + far)
            for piece in built:
                if not piece.is_alive:
                    continue
                c = piece.center
                if self._axis == "xy":
                    far_off = abs(c.x - cx) > ex or abs(c.y - cy) > ey
                elif self._axis == "x":
                    far_off = abs(c.x - mid) > ex
                else:
                    far_off = abs(c.y - mid) > ey
                if far_off:
                    self._warned_drift = True
                    from .process import report_author_warning
                    report_author_warning(
                        "Endless",
                        f"Endless on layer {self._layer_key!r}: pieces are being "
                        f"moved away from their slots. Endless fills what the "
                        f"camera sees; with a fixed camera, move the camera instead "
                        f"of the pieces (see Guia, Mundo sem fim).",
                    )
                    return

    # --- teardown -------------------------------------------------------------

    def _clean_up(self) -> None:
        live = getattr(self, "_live", None)
        if live:
            for key in list(live):
                self._release(key)
        self._scenacanvas.registry.release(self)
        super()._clean_up()

    def __repr__(self) -> str:
        return (f"Endless({self._layer_key!r}, axis={self._axis!r}, "
                f"live_slots={len(getattr(self, '_live', ()))})")
