"""Registry, layer stack, and author facades for groups / layers.

Internal (Scena modules):
  - :class:`LayerStack` — draw layers (str name or int position), z-order, enable flags
  - :class:`Registry` — live roster + group maps, register / soft-remove / destroy

Author-facing:
  - :class:`LayersFacade` — ``canvas.layers``
  - :func:`above` / :func:`below` — adjacent layer numbers for ``layer=``
  - :class:`GroupOperator` — global ``group`` (``group["name"]`` live named groups,
    formula groups via ``@=``, snapshot algebra; count / empty / first / last /
    queries / bulk verbs — not a process owner)

Soft vs hard:
  - ``unregister_draw`` / ``Shape.undraw`` — stop painting; keep graph
  - ``destroy`` / ``Shape.destroy`` — cancel shape transients (no pending ``on_done``),
    mark ``is_alive`` False and ``active`` False, drop draw + roster/groups + ``clean_up()``

There are no author ids: the Python variable is the handle, ``group["tag"]``
is the lookup by name. The roster (``live``) is keyed by an internal serial
that is never reused, so a stale second ``destroy()`` cannot drop a newer actor.
"""

from __future__ import annotations

import sys

import math
from contextlib import contextmanager
from dataclasses import dataclass, field, fields
import warnings
import weakref
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)
from weakref import WeakValueDictionary

from .camera_response import CameraResponse, ScrollState
from .entity import GroupTags
from .state import DestroyedError
from .shapes import Shape, Blank, nearest as _nearest_item
from .validate import refuse_async as _refuse_async

# Registered drawables: Shape or SpatialFx via Entity.
RegistryObject = Any


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


# ``@click(group[tag])`` and the other pointer decorators follow the tag:
# ``interaction._tag_hook`` once a tag rule exists, else None (one global read
# per tag / untag).
_POINTER_TAG_HOOK = None

class ParallaxLayerError(ValueError):
    """Raised when interactive / collidable geometry is used on a parallax layer.

    Permanent invariant (not a v1 gap): non-neutral layers never participate in
    hit-testing or collision. Catchable as ``ValueError`` for convenience.
    """


class UiLayerError(ValueError):
    """Raised when world-only features are used on the reserved ``ui`` layer.

    ``ui`` is view-space (camera-immune, drawn with widgets). Collision and
    SpatialFx are forbidden there. Interactive Graphics are allowed.
    Catchable as ``ValueError`` for convenience.
    """


# ---------------------------------------------------------------------------
# Layer name normalization
# ---------------------------------------------------------------------------

BUILT_IN_LAYERS = frozenset({'top', 'default', 'ui'})

# ``top`` is reserved as the uppermost *world* layer. Author layers may use
# any z strictly below ``TOP_Z`` (i.e. at most ``MAX_LAYER_Z`` == 100).
# ``ui`` is a separate *view* pass (not part of the camera walk); its z is
# reserved and never competes with author / top paint order.
TOP_LAYER = 'top'
TOP_Z = 101
MAX_LAYER_Z = TOP_Z - 1  # 100 — easy-to-remember author ceiling
UI_LAYER = 'ui'
UI_Z = 102  # reserved; excluded from camera / world hit iterators


LayerKey = Union[str, int]


def normalize_layer_name(name: Optional[LayerKey]) -> Optional[LayerKey]:
    """Map ``None`` / blank → ``None`` (undrawn). Pass ints through; strip strings.

    ``None`` means not on any draw list. There is no ``'none'`` / ``'no_draw'``
    sentinel — use ``None`` for undrawn, or a real layer name / number to draw.

    Numeric layers (``int``, not ``bool``) are a separate namespace from string
    names: ``10`` and ``"10"`` never collide. ``bool`` is rejected (``True``
    must not silently become layer ``1``).
    """
    if name is None:
        return None
    if isinstance(name, bool):
        raise TypeError(
            "layer cannot be a bool; use an int (position) or str (name)"
        )
    if isinstance(name, int):
        return name
    if not isinstance(name, str):
        hint = (
            f" Write layer={int(name)}." if isinstance(name, float) and name.is_integer()
            else ""
        )
        raise TypeError(
            f"layer expected a layer name (str) or a whole number (int), got "
            f"{type(name).__name__} {name!r}.{hint}"
        )
    s = name.strip()
    if not s:
        return None
    return s


def layer_is_parallax(stack: "LayerStack", layer_name: Optional[LayerKey]) -> bool:
    """True if ``layer_name`` exists and has a non-neutral camera response."""
    if layer_name is None:
        return False
    layer = stack.get(layer_name)
    return layer is not None and not layer._is_neutral_response


def layer_is_ui(layer_name: Optional[LayerKey]) -> bool:
    """True if ``layer_name`` is the reserved view-space ``ui`` layer."""
    return normalize_layer_name(layer_name) == UI_LAYER


# ---------------------------------------------------------------------------
# Layer + LayerStack (internal)
# ---------------------------------------------------------------------------

@dataclass
class Layer:
    """One draw list (string name or numeric position). Higher ``z`` paints later.

    ``response`` (frozen :class:`CameraResponse`) is set at creation only.
    Non-neutral response → parallax layer: no hit-test, no collision enrollment
    (enforced at shape/collider entry points; hit/collision systems need no
    special paths because forbidden members never register).

    Numeric layers (``name`` is an ``int``) have frozen ``z`` equal to their
    identity — use a different number, ``above()`` / ``below()``, or a named
    layer instead of mutating ``.z``.

    Author-facing per-layer ops: ``visible``, ``z``, ``post_fx``, ``scroll``
    (live rate on non-neutral layers), ``view`` (read-only window), ``delete()``,
    ``clear()`` — via ``canvas.layers[name]`` or the handle returned by
    ``canvas.layers.create(...)``. ``name`` is read-only: it is the registry
    key *and* the key every member shape caches in ``_layer``, so there is no
    rename (a write raises ``AttributeError`` naming the create-and-move fix).
    Any other public write raises ``AttributeError`` (did-you-mean, or the
    ``create(...)`` hint for a camera-response knob) — see ``__setattr__``.
    """

    _name: LayerKey
    _z: int
    _objects: List[RegistryObject] = field(default_factory=list)
    _interactive: List[RegistryObject] = field(default_factory=list)
    visible: bool = True
    # Only meaningful for the reserved ``top`` layer: when True, shapes on
    # ``top`` are drawn after canvas post-FX (HUD stays sharp). Other layers
    # must never set this — use ``canvas.layers['top'].post_fx = False``.
    _exempt_from_post: bool = False
    _response: CameraResponse = field(default_factory=CameraResponse)
    # Private scroll integrator — not part of equality/repr.
    _scroll_state: ScrollState = field(default=None, repr=False, compare=False)  # type: ignore[assignment]
    _tombstones: int = field(default=0, repr=False, compare=False)
    _stack: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._scroll_state is None:
            rate = self._response.scroll if self._response is not None else (0.0, 0.0)
            state = ScrollState(rate)
            # Scroll counts from the layer's birth: the first frame's dt was
            # lost (a 0.25 s first frame scrolled 75 of 100: review 2026-10-09
            # W-T7). No clock yet (import time): the first advance seeds it.
            try:
                from .process import _clock
                clk = _clock()
                if clk is not None:
                    state._last_t = float(clk.time)
            except Exception:
                pass
            object.__setattr__(self, '_scroll_state', state)

    def __setattr__(self, attr: str, value: Any) -> None:
        # Closed surface: dataclass fields (incl. the private ones the
        # stack and the draw walk write) and properties pass; ``name`` /
        # ``z`` / ``post_fx`` setters run their own checks. Anything else
        # used to land in a dead attribute (``layer.visable = False``,
        # ``layer.scroll = (0, 0)``). See Canvas Design, Registry and layers.
        if attr == "visible":
            # A flag, like a shape's: ``layer.visible = "no"`` is truthy and
            # kept the layer drawing (review 2026-10-09 S9-9).
            from .validate import expect_bool
            value = expect_bool(value, "layer.visible")
        if attr in _LAYER_FIELDS or isinstance(getattr(Layer, attr, None), property):
            object.__setattr__(self, attr, value)
            return
        raise AttributeError(_layer_unknown_attr_message(self._name, attr))

    @property
    def name(self) -> LayerKey:
        """Registry key (``str`` name or ``int`` position). Read-only."""
        return self._name

    @name.setter
    def name(self, value) -> None:
        # Silently accepting the write used to desync the handle from the
        # registry (``canvas.layers`` kept the old key) and from every member
        # shape's cached ``_layer`` key. See Canvas Design, Registry and layers.
        raise AttributeError(
            f"layer.name is read-only (it is the canvas.layers key {self._name!r}). "
            f"Write canvas.layers.create({value!r}, ...) and move shapes with "
            f"shape.layer = {value!r}."
        )

    @property
    def z(self) -> int:
        """Draw order: higher paints later. Writable on named layers (not ``top`` / ``ui`` / numeric)."""
        return self._z

    @z.setter
    def z(self, value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"layer z must be a number, got {type(value).__name__}"
            )
        if isinstance(self.name, int):
            raise ValueError(
                f"Cannot change z of numeric layer {self.name}: "
                f"the number is its position (frozen). Use a different "
                f"number, above()/below(), or a named layer"
            )
        if self.name == TOP_LAYER:
            raise ValueError(
                f"Cannot change z of reserved layer '{TOP_LAYER}' "
                f"(fixed at z={TOP_Z})"
            )
        if self.name == UI_LAYER:
            raise ValueError(
                f"Cannot change z of reserved layer '{UI_LAYER}' "
                f"(fixed at z={UI_Z})"
            )
        self._z = self._stack._validate_z(self.name, value)
        self._stack._sort()

    @property
    def post_fx(self) -> bool:
        """When False on ``top``, shapes stay sharp above canvas post FX."""
        return not self._exempt_from_post

    @post_fx.setter
    def post_fx(self, value: bool) -> None:
        if self.name != TOP_LAYER:
            raise ValueError(
                f"Only reserved layer '{TOP_LAYER}' can opt out of post FX; "
                f"got {self.name!r}"
            )
        self._exempt_from_post = not bool(value)

    @property
    def view(self):
        """The view window in this layer's coordinates, as a fresh ``Box``. Read-only.

        Gameplay (neutral) layers see ``canvas.game_view``; ``ui`` sees
        ``canvas.ui_view``; a parallax / scroll layer sees the rectangle its
        camera response and scroll offset show (place scenery at
        ``layer.view.right + 200`` to have it enter from the right). A
        snapshot: read it again each frame. Rotated camera → AABB of the four
        view corners (over-inclusive).
        """
        from .canvas import ScenaCanvas
        return ScenaCanvas.get_current().layer_view(self)

    @view.setter
    def view(self, value) -> None:
        raise AttributeError(
            f"layer.view is read-only (the window the camera shows on layer "
            f"{self._name!r}). Move the camera instead: canvas.pan_to(...)."
        )

    @property
    def scroll(self) -> Tuple[float, float]:
        """Scroll rate ``(x, y)`` in design units/sec (y-up), on world ``clock.time``.

        Live on layers created with camera response (``pan_response=`` /
        ``zoom_response=`` / ``rotation_response=`` / ``scroll=``): a write
        changes the speed from now on, without a jump (``(0, 0)`` stops,
        ``chase(layer.scroll, (0, 0), 3)`` eases). A layer created neutral
        raises: it may hold collidable bodies and never becomes decoration.
        """
        return self._scroll_state.rate

    @scroll.setter
    def scroll(self, value) -> None:
        if self._is_neutral_response:
            name = self._name
            if isinstance(name, int):
                raise ValueError(
                    f"layer {name} has no scroll: numeric layers have no camera "
                    f"response. Create a named layer with "
                    f"canvas.layers.create('name', scroll=...) and move shapes "
                    f"with shape.layer = 'name'."
                )
            raise ValueError(
                f"layer {name!r} was created without camera response, so it cannot "
                f"scroll (it may hold collidable bodies). Create a scrolling "
                f"decoration layer with canvas.layers.create({name!r}, scroll=(0, -40)); "
                f"to start it stopped, create it at speed and write layer.scroll = (0, 0)."
            )
        from .validate import scroll_rate
        self._scroll_state.rate = scroll_rate(value, "layer.scroll")

    @property
    def _is_neutral_response(self) -> bool:
        return self._response.is_neutral

    def delete(self, *, destroy_shapes: bool = True) -> None:
        """Delete this custom layer (built-ins cannot be deleted).

        If ``destroy_shapes`` is True (default), shapes on the layer are
        fully destroyed first. If False, shapes are only soft-removed from
        the draw list (roster/groups/graph kept) before the layer is deleted.
        """
        registry = self._stack._registry
        if destroy_shapes:
            registry.destroy_all(self.name)
        else:
            registry.clear_draw_list(self.name)
        self._stack.delete(self.name)

    def clear(self, *, hard: bool = False) -> None:
        """Clear objects from this layer.

        ``hard=False`` (default): soft — unregister_draw only.
        ``hard=True``: destroy (full teardown) each object.
        """
        registry = self._stack._registry
        if hard:
            registry.destroy_all(self.name)
        else:
            registry.clear_draw_list(self.name)

    @property
    def _live_count(self) -> int:
        """Objects on this layer, not counting removal holes (O(1)).

        ``objects`` keeps a ``None`` hole per removal until ``compact()``;
        never report ``len(objects)`` as a count.
        """
        return len(self._objects) - self._tombstones

    def _append_object(self, obj: RegistryObject) -> None:
        object.__setattr__(obj, "_draw_index", len(self._objects))
        self._objects.append(obj)

    def _tombstone_object(self, obj: RegistryObject) -> bool:
        """O(1) remove: leave a hole; compact() restores painter order later."""
        idx = getattr(obj, "_draw_index", -1)
        objs = self._objects
        if idx < 0 or idx >= len(objs) or objs[idx] is not obj:
            try:
                idx = objs.index(obj)
            except ValueError:
                return False
        objs[idx] = None
        self._tombstones += 1
        try:
            object.__setattr__(obj, "_draw_index", -1)
        except Exception:
            pass
        return True

    def _compact(self) -> None:
        if not self._tombstones:
            return
        live = []
        for o in self._objects:
            if o is None:
                continue
            object.__setattr__(o, "_draw_index", len(live))
            live.append(o)
        # Mutate in place so callers holding ``layer._objects`` stay current.
        self._objects[:] = live
        self._tombstones = 0


_LAYER_FIELDS = frozenset(f.name for f in fields(Layer))
_LAYER_WRITABLE = ("visible", "z", "post_fx", "scroll")
# ``response`` is the frozen ``CameraResponse`` the docstring names. ``scroll``
# is not here: its rate is live (``Layer.scroll``); the classification
# (neutral or not) stays frozen.
_LAYER_FROZEN = ("pan_response", "zoom_response", "rotation_response", "response")


def _layer_unknown_attr_message(layer_name: LayerKey, attr: str) -> str:
    """``AttributeError`` text for a write ``Layer`` does not accept.

    ``Layer`` keeps its own allow-list (dataclass fields + properties) and the
    camera-response hints; the generic sentence comes from
    :func:`scena.closed.unknown_name_message`, as on every closed surface.
    """
    writable = "Writable on a layer: " + ", ".join(_LAYER_WRITABLE) + "."
    if attr in _LAYER_FROZEN:
        if isinstance(layer_name, int):
            return (
                f"layer {layer_name} has no {attr!r}: numeric layers have no "
                f"camera response. Create a named layer with "
                f"canvas.layers.create('name', {attr}=...) and move shapes with "
                f"shape.layer = 'name'."
            )
        knob = "pan_response=..." if attr == "response" else f"{attr}=..."
        return (
            f"layer.{attr} cannot be changed: camera-response knobs are set only "
            f"in canvas.layers.create({layer_name!r}, {knob}) and are frozen for "
            f"the life of the layer. Create another layer and move shapes with "
            f"shape.layer = ..."
        )
    if callable(getattr(Layer, attr, None)):
        return f"layer.{attr} is a method; call it, do not assign it. {writable}"
    from .closed import unknown_name_message
    from .validate import did_you_mean
    hint = did_you_mean(attr, _LAYER_WRITABLE + ("name",) + _LAYER_FROZEN[:-1], n=1)
    if any(repr(k) in hint for k in _LAYER_FROZEN):
        hint += " It is set only in canvas.layers.create(...)."
    return unknown_name_message(
        f"layer {layer_name!r}", attr, _LAYER_WRITABLE, noun="a layer", hint=hint,
    )


class LayerStack:
    """Ordered stack of draw layers. Higher ``z`` → on top.

    Built-ins created on init / :meth:`reset_builtins`:
      - ``default`` (z=0, always neutral response) — world
      - ``top`` (z=101, reserved uppermost *world*; author z ≤ 100; always neutral)
      - ``ui`` (z=102, reserved *view* pass; excluded from camera walk / world hit)

    ``has_parallax_layers`` is a cached flag (recomputed on create/delete only)
    used by the draw loop for a zero-cost fast path when no parallax layers
    exist.
    """

    DEFAULT_Z = {
        'default': 0,
        'top': TOP_Z,
        'ui': UI_Z,
    }

    def __init__(self, registry: "Registry") -> None:
        self._registry = registry
        self._layers: Dict[LayerKey, Layer] = {}
        self._default_name = 'default'
        self._has_parallax_layers = False
        self.reset_builtins()

    def reset_builtins(self) -> None:
        """Replace all layers with the built-ins (draw lists emptied)."""
        self._layers.clear()
        # Built-ins are always neutral — never created via author create() with
        # response kwargs; pass explicit neutral response defensively.
        self.create(
            'default',
            z=self.DEFAULT_Z['default'],
            visible=True,
            response=CameraResponse(),
        )
        self.create(
            'top',
            z=self.DEFAULT_Z['top'],
            visible=True,
            response=CameraResponse(),
        )
        self.create(
            UI_LAYER,
            z=self.DEFAULT_Z['ui'],
            visible=True,
            response=CameraResponse(),
        )
        self._default_name = 'default'
        self._recompute_has_parallax()

    def _recompute_has_parallax(self) -> None:
        self._has_parallax_layers = any(
            not layer._is_neutral_response for layer in self._layers.values()
            if layer.name != UI_LAYER
        )

    @property
    def has_parallax_layers(self) -> bool:
        """True if any non-neutral camera-response layer exists."""
        return self._has_parallax_layers

    def _sort(self) -> None:
        self._layers = dict(sorted(self._layers.items(), key=lambda item: item[1].z))

    def _validate_z(self, name: LayerKey, z: int) -> int:
        """Return validated z, or raise if it would sit at/above ``top``."""
        if isinstance(z, bool) or not isinstance(z, (int, float)):
            raise TypeError(
                f"layer z must be a number, got {type(z).__name__}"
            )
        if isinstance(z, float) and not z.is_integer():
            # ``int(5.5)`` silently drew the layer at 5 (S9-9).
            raise ValueError(f"layer z must be a whole number, got {z!r}")
        z = int(z)
        if name == TOP_LAYER:
            if z != TOP_Z:
                raise ValueError(
                    f"Reserved layer '{TOP_LAYER}' is fixed at z={TOP_Z}"
                )
            return z
        if name == UI_LAYER:
            if z != UI_Z:
                raise ValueError(
                    f"Reserved layer '{UI_LAYER}' is fixed at z={UI_Z}"
                )
            return z
        if z >= TOP_Z:
            raise ValueError(
                f"Layer z must be <= {MAX_LAYER_Z} "
                f"(below reserved '{TOP_LAYER}' at z={TOP_Z}); got {z}"
            )
        return z

    @property
    def default(self) -> str:
        return self._default_name

    @default.setter
    def default(self, name: str) -> None:
        if name not in self._layers:
            raise self._missing(name)
        self._default_name = name

    def create(
        self,
        name: LayerKey,
        *,
        z: int = 0,
        visible: bool = True,
        response: Optional[CameraResponse] = None,
    ) -> Layer:
        if isinstance(name, bool):
            raise TypeError(
                "layer cannot be a bool; use an int (position) or str (name)"
            )
        if name in self._layers:
            raise ValueError(f"Layer '{name}' already exists")
        z = self._validate_z(name, z)
        resp = response if response is not None else CameraResponse()
        layer = Layer(_name=name, _z=z, visible=bool(visible), _response=resp)
        object.__setattr__(layer, '_stack', self)
        self._layers[name] = layer
        self._sort()
        self._recompute_has_parallax()
        return layer

    def delete(self, name: LayerKey) -> None:
        if name not in self._layers:
            raise self._missing(name)
        if name in BUILT_IN_LAYERS:
            raise ValueError(f"Cannot delete built-in layer '{name}'")
        layer = self._layers[name]
        layer._compact()
        if layer._objects:
            raise ValueError(
                f"Layer '{name}' still has objects; clear or destroy them first"
            )
        del self._layers[name]
        if self._default_name == name:
            self._default_name = 'default'
        self._recompute_has_parallax()

    def get(self, name: LayerKey) -> Optional[Layer]:
        return self._layers.get(name)

    def _missing(self, name) -> ValueError:
        """``Layer 'x' not found`` with the names that exist and the create fix."""
        from .validate import did_you_mean
        names = [n for n in self._layers if isinstance(n, str)]
        return ValueError(
            f"Layer {name!r} not found.{did_you_mean(name, names)} "
            f"Existing layers: {', '.join(names)}. Create it first with "
            f"canvas.layers.create({name!r})."
        )

    def require(self, name: LayerKey) -> Layer:
        if not isinstance(name, (str, int)) or isinstance(name, bool):
            normalize_layer_name(name)  # raises TypeError naming the fix
        layer = self._layers.get(name)
        if layer is None:
            raise self._missing(name)
        return layer

    def __contains__(self, name: object) -> bool:
        # Accept str or int (not bool — bool is a subclass of int).
        if isinstance(name, bool):
            return False
        return isinstance(name, (str, int)) and name in self._layers

    def __getitem__(self, name: LayerKey) -> Layer:
        return self.require(name)

    def __iter__(self) -> Iterator[LayerKey]:
        return iter(self._layers)

    def values(self) -> Iterator[Layer]:
        return iter(self._layers.values())

    def list_info(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': layer.name,
                'z': layer.z,
                'visible': layer.visible,
                'object_count': layer._live_count,
            }
            for layer in self._layers.values()
        ]

    def iter_draw_order(self) -> Iterator[Layer]:
        """Yield visible *world* layers bottom→top (low z first).

        Skips the reserved ``ui`` view pass (drawn after post with widgets).
        """
        for layer in self._layers.values():
            if layer.visible and layer.name != UI_LAYER:
                yield layer

    def iter_hit_order(self) -> Iterator[Layer]:
        """Yield visible *world* layers top→bottom (high z first).

        Skips ``ui`` (hit-tested in view space before world Graphics).
        """
        for layer in reversed(list(self._layers.values())):
            if layer.visible and layer.name != UI_LAYER:
                yield layer

    def get_ui_layer(self) -> Optional[Layer]:
        """Return the reserved ``ui`` layer, or None if missing."""
        return self._layers.get(UI_LAYER)


# ---------------------------------------------------------------------------
# Ordered weak group membership (join-order stable)
# ---------------------------------------------------------------------------

class _OrderedWeakGroup:
    """Insertion-ordered weak membership for one named tag.

    Members appear in the order they joined. Re-add of a current member is a
    no-op (does not move to end). Untag + tag again appends. Dead refs are
    dropped by the weakref callback; walks skip any that remain.
    """

    __slots__ = ('_order',)

    def __init__(self) -> None:
        self._order: Dict[int, weakref.ref] = {}

    def add(self, obj) -> bool:
        key = id(obj)
        existing = self._order.get(key)
        if existing is not None:
            live = existing()
            if live is obj:
                return False
            del self._order[key]

        def _on_die(ref, k=key, order=self._order):
            if order.get(k) is ref:
                order.pop(k, None)

        self._order[key] = weakref.ref(obj, _on_die)
        return True

    def discard(self, obj) -> bool:
        key = id(obj)
        existing = self._order.get(key)
        if existing is None:
            return False
        live = existing()
        del self._order[key]
        return live is obj

    def __contains__(self, obj) -> bool:
        ref = self._order.get(id(obj))
        return ref is not None and ref() is obj

    def __len__(self) -> int:
        return len(self._order)

    def __bool__(self) -> bool:
        return len(self._order) > 0

    def __iter__(self) -> Iterator:
        for key, ref in list(self._order.items()):
            obj = ref()
            if obj is None:
                self._order.pop(key, None)
                continue
            yield obj

    def live_list(self) -> List:
        return list(self)


# ---------------------------------------------------------------------------
# Registry (internal)
# ---------------------------------------------------------------------------

class Registry:
    """Live roster, groups, and draw-list membership for shapes.

    Scena modules call this; authors use Shape methods, ``group``, and
    ``canvas.layers``.
    """

    def __init__(self) -> None:
        self.layers = LayerStack(registry=self)
        # Every registered, not-yet-destroyed item, in registration order.
        # Keyed by ``obj._reg_key`` (a serial, never reused); weak like the
        # rest of the registry — the draw list / scheduler keep actors alive.
        self.live: WeakValueDictionary = WeakValueDictionary()
        self._next_key = 0
        self.group_map: Dict[str, _OrderedWeakGroup] = {}
        self._group_gen: Dict[str, int] = {}
        # Bumped by every destroy: a broadcast re-checks liveness only when
        # it moved during the broadcast (S9-3), at no per-member cost.
        self._destroy_gen = 0
        # Group names a rule declared (@collide family, collide_with, resolve,
        # @leave_playfield). With ``_group_gen`` (every name that ever had a
        # member) these are the names ``group[...]`` may read while empty
        # without the near-miss typo warning (Actors Design, Group names).
        self._declared_groups: Set[str] = set()
        self._group_formulas: Dict[str, Callable] = {}
        self._group_formula_stack: List[str] = []
        # Bumped whenever the set or order of pointer targets may have changed
        # (interactive list edits, flag flips, z-order). The hover resolver
        # re-runs a full hit test when it moves (Shapes Design, Hover).
        self._pointer_epoch = 0
        # Undrawn actors the world keeps alive with no author variable
        # (``Endless("pista", ...)`` on one line must keep filling; an author
        # ``Wasp()`` with an ``on_update``: Laws L1). Strong; an actor leaves
        # it in its teardown (``remove_live``; Endless in its ``_clean_up``).
        self._held: Set[Any] = set()

    def hold(self, obj) -> None:
        """Keep ``obj`` alive until its teardown calls :meth:`release`."""
        self._held.add(obj)

    def release(self, obj) -> None:
        self._held.discard(obj)

    # --- registration lifecycle ------------------------------------------------

    def _require_or_create_layer(self, target: LayerKey) -> Layer:
        """Return an existing layer, or auto-create a numeric one (``z == name``).

        String names must already exist (typo guard). Int keys auto-vivify with
        frozen ``z`` equal to the number — separate namespace from ``"10"``.
        """
        if target not in self.layers:
            if isinstance(target, int):
                return self.layers.create(target, z=target)
            from .validate import did_you_mean
            names = [n for n in self.layers if isinstance(n, str)]
            raise ValueError(
                f"Layer '{target}' not found.{did_you_mean(target, names)} "
                f"Existing layers: {', '.join(names)}. Create it first: "
                f"canvas.layers.create({target!r}, above=\"default\") draws it in front "
                f"of the game, below=\"default\" behind it; or use an int layer "
                f"(auto-created, a higher number in front)."
            )
        return self.layers[target]

    def register(
        self, obj: RegistryObject, layer: Optional[LayerKey] = None
    ) -> RegistryObject:
        """Register ``obj`` in the roster/groups; optionally append to a draw layer.

        ``layer=None`` → roster/groups only (undrawn). A string layer must exist;
        an ``int`` layer is auto-created at that z. Callers supply the layer:
        Shape / SpatialFx default to ``\"default\"``; Point to ``None`` (undrawn).
        """
        if _SOLVER_READING:
            refuse_if_solver_reading(f"creating a {type(obj).__name__}")
        # Resolve the layer before claiming anything, so a bad layer leaves
        # no roster / group / draw entry behind.
        target = normalize_layer_name(layer)
        draw_layer = None if target is None else self._require_or_create_layer(target)
        self.add_live(obj)

        for group_id in list(obj.group):
            self.add_to_group(obj, group_id)

        if draw_layer is None:
            obj._layer = None
            if getattr(type(obj), "_scena_holds_undrawn", False):
                self._held.add(obj)         # until remove_live (Laws L1)
            return obj

        draw_layer._append_object(obj)
        obj._layer = target
        return obj

    def unregister_draw(self, obj: RegistryObject) -> bool:
        """Soft remove: drop from draw + interactive lists; keep roster/groups/graph.

        Returns True if the object was on a draw layer.
        """
        layer_name = normalize_layer_name(getattr(obj, '_layer', None))
        if layer_name is None:
            obj._layer = None
            return False

        if layer_name not in self.layers:
            raise ValueError(
                f"Internal inconsistency: Layer '{layer_name}' on {obj} not found"
            )

        layer = self.layers[layer_name]
        if not layer._tombstone_object(obj):
            raise ValueError(
                f"Internal inconsistency: {obj} not found in layer {layer_name}"
            )
        if obj in layer._interactive:
            layer._interactive.remove(obj)
            self._pointer_epoch += 1
        obj._layer = None
        return True

    def destroy(self, obj: RegistryObject) -> None:
        """Hard remove: cancel transients, mark dead, unregister_draw, clean_up.

        Pending shape-transient ``on_done`` callbacks are **not** run.
        ``on_destroy`` (if set) runs first, while the item is still fully alive.
        Marks ``is_alive`` and ``active`` False (direct flags, not the park setter).
        Author errors (``on_destroy``, a partner's ``on_collide_exit``)
        propagate after teardown completes.
        """
        from .entity import _fire_on_destroy
        if getattr(obj, "_dying", False):
            return          # a hook of this teardown called destroy() again
        try:
            _fire_on_destroy(obj)
        finally:
            self._destroy_teardown(obj)

    def _destroy_teardown(self, obj: RegistryObject) -> None:
        # Dying: alive (its own exit hooks run on a live object), but a second
        # destroy() from one of those hooks is a no-op (review X-life-5).
        self._destroy_gen += 1
        try:
            object.__setattr__(obj, "_dying", True)
        except Exception:
            pass
        # Pull outside @= dependents while obj still reads as alive: auto-unlink
        # later keeps their value, which must be the source's final one (D8).
        # A formula error re-raises after teardown (same rule as on_destroy).
        pull_error = None
        pull = getattr(obj, "_pull_external_dependents", None)
        if pull is not None:
            try:
                pull()
            except (ReferenceError, AttributeError):
                pass  # includes DestroyedError: a source already gone
            except Exception as exc:  # noqa: BLE001 — author formula error
                pull_error = exc
        try:
            self._destroy_teardown_body(obj)
        finally:
            if pull_error is not None:
                raise pull_error

    def _destroy_teardown_body(self, obj: RegistryObject) -> None:
        # Entity parts (a Circle's ``center``, a Line's ``p1`` / ``p2``) are
        # registered like actors. Collect them now: ``_clean_up`` below cuts
        # the owner edges that let us find them.
        parts = entity_parts(obj)
        try:
            from .transients import clear_transients
            clear_transients(obj, silent=True)
        except Exception:
            pass
        try:
            from .spatial_fx import unregister_spatial
            unregister_spatial(obj)
        except Exception:
            pass
        try:
            from .orchestration import forget_hud_column_item, unregister_widget
            forget_hud_column_item(obj)
            unregister_widget(obj)
        except Exception:
            pass
        try:
            from .entity import _record_destroy_site
            _record_destroy_site(obj)
        except Exception:
            pass
        # Out of its groups for every reader before any author exit runs: a
        # survivor's ``on_collide_exit`` counting ``group["enemy"]`` sees the
        # last enemy gone (review S9-2). Its tags stay until the registry
        # teardown; collision keeps its own tag index for the exits below.
        if obj.group:
            self._leave_group_buckets(obj)
        # The exits that are author code run while ``obj`` still exists
        # (Shapes Design "Hover", Collision Design: "the dying body, while it
        # still exists"): the dying object's own hover / collide exit may
        # write to it (the taught un-highlight). Before, they ran after
        # ``_destroyed`` and raised DestroyedError out of destroy() and
        # change_act (review X-life-5). An error re-raises after teardown.
        exit_error: Optional[BaseException] = None
        from .collision import get_collision_system
        try:
            # Fires the survivor's and the dying body's on_collide_exit.
            get_collision_system().forget_destroyed_item(obj)
        except BaseException as exc:  # noqa: BLE001 — finish the teardown first
            exit_error = exc
        for manager in list(getattr(self, "_pointer_managers", ()) or ()):
            try:
                # Fires on_hover_exit while obj still exists.
                manager.forget_destroyed(obj)
            except BaseException as exc:  # noqa: BLE001
                if exit_error is None:
                    exit_error = exc
        try:
            obj._destroyed = True
            from .entity import _mark_routes_dead
            _mark_routes_dead(obj)
        except Exception:
            pass
        try:
            # Parts outlive the teardown as readable values (the author may
            # still hold ``dead.center``) with their owner edge cut: mark them
            # so a later ``@=`` on one refuses like the actor itself (W2).
            # A part that is not an Entity (``ship.vel``, a Vec2) is dead too:
            # ``ScalarSlot.__set__`` refuses its axis writes as it does a
            # retired Point's (``retire_part`` below marks the Entity parts).
            # Its refusal builds the breadcrumb from ``_destroyed_with_host``
            # (``_destroyed_access_message``): no label string per destroy.
            for node in obj._iter_subtree():
                if node is not obj:
                    nd = node.__dict__
                    nd["_host_destroyed"] = True
                    if not getattr(type(node), "_scena_is_entity", False):
                        nd["_destroyed"] = True
                        nd["_destroyed_with_host"] = obj
        except Exception:
            pass
        try:
            # Report inactive without the park setter (no stash / restore).
            object.__setattr__(obj, "_active", False)
            object.__setattr__(obj, "_active_saved_visible", None)
            object.__setattr__(obj, "_active_saved_collidable", None)
        except Exception:
            pass
        try:
            # End a pointer hold on this actor: held Handles must tick again so
            # their dead-target check cancels them (a held Handle never reaches
            # it). See Shapes Design — Persistent drivers (hold).
            from .process import release_hold
            release_hold(obj)
        except Exception:
            pass
        try:
            from .process import get_scheduler
            sched = get_scheduler()
            # Implicit ending: a sound that ends by itself rings out.
            sched.cancel_owner(obj, release=True)
            # Parts outlive the teardown as readable values, not as running
            # work: a part's timers / tweens / mode script end with the host,
            # by the same rule (a loop on ``line.p1`` must not play forever).
            for node in obj._iter_subtree():
                if node is obj:
                    continue
                if id(node) in sched._by_owner:
                    sched.cancel_owner(node, release=True)
        except Exception:
            pass
        try:
            from .events import get_global_event_system
            es = get_global_event_system()
            es.drop_owner(obj)
            if es._classless:
                es.drop_reading(obj)  # classless watches on a dead source (S2-8)
        except Exception:
            pass
        try:
            from .bounds import get_bounds_system
            get_bounds_system().forget_item(obj)
        except Exception:
            pass
        # A part leaves with its owner: off every draw / pointer list,
        # group and the roster, and dead (writes raise, reads stay).
        for part in parts:
            self.retire_part(part, obj)
        self.unregister_draw(obj)
        self._teardown_registry_and_graph(obj)
        if exit_error is not None:
            raise exit_error

    def _leave_group_buckets(self, obj: RegistryObject) -> None:
        """Take a dying object out of every group bucket (reads, counts,
        broadcasts, formula groups) without the collision notify; its tags
        and the collision tag index go in the normal teardown."""
        for groupid in list(getattr(obj, "group", ()) or ()):
            bucket = self.group_map.get(groupid)
            if bucket is not None and bucket.discard(obj):
                self._group_gen[groupid] = self._group_gen.get(groupid, 0) + 1

    def retire_part(self, part: RegistryObject, host: RegistryObject) -> None:
        """Take one Entity part of ``host`` out of Scena (host destroy / rollback).

        Same registry exit as ``destroy()`` minus the actor-only steps: no
        ``on_destroy`` (a part is not an actor) and no graph cleanup (the
        host's ``_clean_up`` walks the part subtree). Reads stay, like any
        destroyed actor; writes raise ``DestroyedError`` naming the host.
        """
        if getattr(part, "_destroyed", False):
            return
        from .bounds import get_bounds_system
        from .collision import get_collision_system
        from .events import get_global_event_system
        from .process import release_hold
        from .transients import clear_transients
        for step in (
            lambda: clear_transients(part, silent=True),
            lambda: release_hold(part),
            lambda: get_global_event_system().drop_owner(part),
            lambda: get_bounds_system().forget_item(part),
            lambda: get_collision_system().forget_destroyed_item(part),
        ):
            try:
                step()
            except Exception:
                pass
        self.unregister_draw(part)
        self.remove_live(part)
        for group_id in list(getattr(part, "group", ()) or ()):
            self.remove_from_group(part, group_id)
        d = part.__dict__
        d["_destroyed"] = True
        from .entity import _mark_routes_dead
        _mark_routes_dead(part)
        d["_destroyed_by"] = _part_destroyed_note(host)
        # Slots on a Shape part: a ``d[...]`` write never reached them, so a
        # retired Point read ``active`` True (review 2026-10-09 S5-4 class).
        object.__setattr__(part, "_active", False)
        object.__setattr__(part, "_active_saved_visible", None)
        object.__setattr__(part, "_active_saved_collidable", None)

    def change_layer(self, obj: RegistryObject, new_layer: Optional[LayerKey]) -> None:
        """Move ``obj`` to ``new_layer``, or undrawn if ``None``.

        An ``int`` target auto-creates that numeric layer if missing.
        """
        target = normalize_layer_name(new_layer)
        # Resolve first so a rejected name leaves the object on its old layer.
        layer = None if target is None else self._require_or_create_layer(target)
        self.unregister_draw(obj)
        if target is None:
            obj._layer = None
            return

        layer._append_object(obj)
        obj._layer = target
        sync = getattr(obj, '_sync_interactive_registry', None)
        if sync is not None:
            sync()

    def _teardown_registry_and_graph(self, obj: RegistryObject) -> None:
        self.remove_live(obj)
        for group_id in list(obj.group):
            self.remove_from_group(obj, group_id)
        obj._clean_up()

    def clear_draw_list(self, layer_name: Optional[LayerKey] = None) -> None:
        """Soft-clear: unregister_draw every object on one layer or all layers."""
        if layer_name is not None:
            layer = self.layers.require(layer_name)
            layer._compact()
            for obj in list(layer._objects):
                self.unregister_draw(obj)
            return
        for layer in list(self.layers.values()):
            layer._compact()
            for obj in list(layer._objects):
                self.unregister_draw(obj)

    def destroy_all(self, layer_name: Optional[LayerKey] = None) -> None:
        """Hard-clear: destroy every object on one layer or all layers.

        Runs each layer to a fixed point: an ``on_destroy`` handler that
        spawns a new object onto a layer already being drained is destroyed
        too, in a follow-up pass, instead of surviving the sweep. Without
        this, ``Layer.delete()`` (which calls this then requires the layer
        empty) would raise "still has objects" on the very spawn its own
        cleanup caused, and ``reset_layers()`` would silently orphan the
        spawn — alive and registered, but on a layer ``reset_builtins()``
        is about to drop, so never drawn or hit-tested again.
        """
        if layer_name is not None:
            self._drain_layer(self.layers.require(layer_name))
            return
        for layer in list(self.layers.values()):
            self._drain_layer(layer)

    _DESTROY_ALL_MAX_PASSES = 10_000

    def _drain_layer(self, layer: "Layer") -> None:
        """Destroy a layer's objects to a fixed point (see :meth:`destroy_all`)."""
        layer._compact()
        passes = 0
        while layer._objects:
            passes += 1
            if passes > self._DESTROY_ALL_MAX_PASSES:
                raise RuntimeError(
                    f"destroy_all() did not settle after "
                    f"{self._DESTROY_ALL_MAX_PASSES} passes on layer "
                    f"{layer.name!r}: an on_destroy handler is likely "
                    f"spawning new objects onto this layer forever"
                )
            from .entity import is_part
            for obj in list(layer._objects):
                if is_part(obj):
                    # A shown handle is a view of its owner's point, not an
                    # actor on this layer: undraw it (it leaves with the owner).
                    self.unregister_draw(obj)
                    obj._layer = None
                else:
                    self.destroy(obj)
            layer._compact()

    def reset_layers(self) -> None:
        """Destroy every drawn object and recreate built-in layers."""
        self.destroy_all()
        # Objects that were registered but never drawn (e.g. Points) remain.
        self.layers.reset_builtins()

    # --- z-order within a layer ------------------------------------------------

    def move_to_front(self, obj: Shape) -> None:
        layer_name = normalize_layer_name(getattr(obj, '_layer', None))
        if layer_name is None or layer_name not in self.layers:
            return
        layer = self.layers[layer_name]
        layer._compact()
        if obj not in layer._objects:
            return
        layer._objects.remove(obj)
        for i, o in enumerate(layer._objects):
            object.__setattr__(o, "_draw_index", i)
        layer._append_object(obj)
        self._pointer_epoch += 1

    def move_to_back(self, obj: Shape) -> None:
        layer_name = normalize_layer_name(getattr(obj, '_layer', None))
        if layer_name is None or layer_name not in self.layers:
            return
        layer = self.layers[layer_name]
        layer._compact()
        if obj not in layer._objects:
            return
        layer._objects.remove(obj)
        layer._objects.insert(0, obj)
        for i, o in enumerate(layer._objects):
            object.__setattr__(o, "_draw_index", i)
        self._pointer_epoch += 1

    # --- interactive hit-testing -----------------------------------------------

    def set_interactive(self, obj: Shape, active: bool) -> None:
        """Add or remove ``obj`` from its layer's interactive hit-test list.

        Always bumps ``_pointer_epoch``: callers (``_sync_interactive_registry``)
        run on every pointer-flag change, including flips that keep the
        membership (``clickable`` off while ``draggable`` stays on).
        """
        self._pointer_epoch += 1
        layer_name = normalize_layer_name(getattr(obj, '_layer', None))
        if layer_name is None or layer_name not in self.layers:
            return
        interactive = self.layers[layer_name]._interactive
        if active:
            if obj not in interactive:
                interactive.append(obj)
        else:
            if obj in interactive:
                interactive.remove(obj)

    @staticmethod
    def _interactive_topmost_first(layer: Layer) -> List[Shape]:
        """``layer._interactive`` in reverse paint order.

        Sorts the k interactive members by ``_draw_index`` (kept valid across
        tombstones; rewritten by ``_compact`` / ``move_to_front`` /
        ``move_to_back``) instead of walking every object on the layer.
        """
        return sorted(
            layer._interactive,
            key=lambda o: getattr(o, "_draw_index", -1),
            reverse=True,
        )

    def iter_interactive_hit_order(self) -> Iterator[Shape]:
        """Yield interactive *world* shapes topmost-first (matches paint order).

        Skips ``ui`` (use :meth:`iter_ui_interactive_hit_order` for view space).
        """
        for layer in self.layers.iter_hit_order():
            if layer._interactive:
                yield from self._interactive_topmost_first(layer)

    def iter_ui_interactive_hit_order(self) -> Iterator[Shape]:
        """Yield interactive shapes on the reserved ``ui`` layer (topmost first)."""
        layer = self.layers.get_ui_layer()
        if layer is None or not layer.visible or not layer._interactive:
            return
        yield from self._interactive_topmost_first(layer)

    def pointer_layers_signature(self) -> tuple:
        """Layer order + visibility, compared frame to frame by the hover resolver.

        Layer ``visible`` is a plain field and ``z`` reorders the stack; both
        change which target is topmost without touching any interactive list.
        O(number of layers).
        """
        return tuple((layer.name, layer.visible) for layer in self.layers.values())

    def objects_on_layer(self, layer_name: str) -> List[RegistryObject]:
        layer = self.layers.require(layer_name)
        layer._compact()
        return list(layer._objects)

    # --- live roster -----------------------------------------------------------

    def add_live(self, obj: RegistryObject) -> None:
        self._next_key += 1
        obj._reg_key = self._next_key
        self.live[self._next_key] = obj

    def remove_live(self, obj: RegistryObject) -> None:
        key = getattr(obj, "_reg_key", None)
        if key is not None and self.live.get(key) is obj:
            del self.live[key]
        self._held.discard(obj)

    def is_live(self, obj: RegistryObject) -> bool:
        """``obj`` is registered here and not yet destroyed."""
        key = getattr(obj, "_reg_key", None)
        return key is not None and self.live.get(key) is obj

    def live_objects(self) -> List[RegistryObject]:
        """Registered, not-yet-destroyed items in registration order."""
        return list(self.live.values())

    # --- groups ----------------------------------------------------------------

    def list_by_groupid(self, group_id: str) -> List[RegistryObject]:
        bucket = self.group_map.get(group_id)
        if bucket is None:
            return []
        members = bucket.live_list()
        if not members:
            del self.group_map[group_id]
        return members

    def group_live_count(self, group_id: str) -> int:
        """O(1) live member count (no list materialization)."""
        bucket = self.group_map.get(group_id)
        if bucket is None:
            return 0
        n = len(bucket)
        if n == 0:
            del self.group_map[group_id]
            return 0
        return n

    def add_to_group(self, obj: Shape, groupid: str) -> None:
        # Before any change: the collision notify below swallows exceptions.
        if _SOLVER_READING:
            refuse_if_solver_reading("a group change (tag / add_to_group)")
        if groupid in self._group_formulas:
            raise TypeError(
                f"group[{groupid!r}] is a formula group; cannot tag members onto it. "
                f"Untag sources, or unlink the formula first."
            )
        hook = _POINTER_TAG_HOOK
        built = getattr(obj, "_actor_constructed", False)
        if hook is not None and built:
            hook(obj, groupid, "check")     # a refused joiner raises, nothing changed
        tags = obj.group
        if groupid not in tags:
            # Snapshot swap, never in-place: ``shape.group`` is read-only
            # (GroupTags) so authors cannot desync it from ``group_map``.
            object.__setattr__(obj, "group", GroupTags(tags | {groupid}))
        if groupid not in self.group_map:
            self.group_map[groupid] = _OrderedWeakGroup()
        already = obj in self.group_map[groupid]
        self.group_map[groupid].add(obj)
        if not already:
            self._group_gen[groupid] = self._group_gen.get(groupid, 0) + 1
        if built:
            try:
                from .collision import notify_group_add
                notify_group_add(obj, groupid)
            except Exception:
                pass
            if hook is not None and not already:
                hook(obj, groupid, "join")

    def remove_from_group(self, obj: Shape, groupid: str) -> None:
        if _SOLVER_READING:
            refuse_if_solver_reading("a group change (untag / remove_from_group)")
        tags = obj.group
        if groupid in tags:
            object.__setattr__(obj, "group", GroupTags(tags - {groupid}))
        if groupid in self.group_map:
            was_member = obj in self.group_map[groupid]
            self.group_map[groupid].discard(obj)
            if was_member:
                self._group_gen[groupid] = self._group_gen.get(groupid, 0) + 1
                try:
                    from .collision import notify_group_remove
                    notify_group_remove(obj, groupid)
                except Exception:
                    pass
                hook = _POINTER_TAG_HOOK
                if hook is not None and getattr(obj, "_actor_constructed", False):
                    hook(obj, groupid, "leave")
            # The notify above can reach a formula group's refresh, which may
            # already have dropped the emptied entry (untag of a last member).
            if not self.group_map.get(groupid):
                self.group_map.pop(groupid, None)

    def clear_group(self, groupid: str) -> None:
        """Remove group membership from all members (shapes stay on canvas)."""
        if groupid not in self.group_map:
            return
        for obj in list(self.group_map[groupid]):
            self.remove_from_group(obj, groupid)

    def group_generation(self, groupid: str) -> int:
        """Membership generation for ``groupid`` (add/remove bumps)."""
        return self._group_gen.get(groupid, 0)

    def has_group_formula(self, name: str) -> bool:
        return name in self._group_formulas

    def declare_group_name(self, name: str) -> None:
        """A rule names this group: an empty lookup of it is not a typo."""
        self._declared_groups.add(name)

    def group_name_known(self, name: str) -> bool:
        """Live now, ever had a member, declared by a rule, a formula group, or
        a class keyword's ``group=`` (``class Inimigo(Rect, group="inimigos")``
        before the first one exists: persona probes R3-6). The class scan runs
        only for a name not known otherwise (a near-miss check, rare)."""
        if (name in self.group_map or name in self._group_gen
                or name in self._declared_groups or name in self._group_formulas):
            return True
        if _class_keyword_groups_include(name):
            self._declared_groups.add(name)
            return True
        return False

    def known_group_names(self) -> List[str]:
        """Every known name (see ``group_name_known``), for did-you-mean hints."""
        return sorted(set(self.group_map) | set(self._group_gen)
                      | self._declared_groups | set(self._group_formulas))

    def set_group_formula(self, name: str, fn: Callable) -> None:
        n = self.group_live_count(name)
        if n > 0:
            raise TypeError(
                f"group[{name!r}] already has tagged members; "
                f"cannot bind a formula. Untag them first, or pick another name."
            )
        if name in self._group_formulas:
            warnings.warn(
                f"group[{name!r}] received a formula that overrides its previous link",
                RuntimeWarning,
                stacklevel=4,
            )
        self._group_formulas[name] = fn

    def unlink_group_formula(self, name: str) -> None:
        self._group_formulas.pop(name, None)

    def clear_group_formulas(self) -> None:
        self._group_formulas.clear()
        self._group_formula_stack.clear()

    def eval_group_formula(self, name: str) -> List[Shape]:
        if name not in self._group_formulas:
            return []
        if name in self._group_formula_stack:
            chain = " → ".join(self._group_formula_stack + [name])
            raise RuntimeError(f"group formula cycle: {chain}")
        self._group_formula_stack.append(name)
        try:
            return _formula_result_members(self, self._group_formulas[name]())
        finally:
            self._group_formula_stack.pop()


# ---------------------------------------------------------------------------
# Author facades: LayersFacade, group
# ---------------------------------------------------------------------------

class LayersFacade:
    """Author-facing ``canvas.layers`` API."""

    __slots__ = ('_registry',)

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def create(
        self,
        name: str,
        *,
        z: Optional[int] = None,
        above: Optional[LayerKey] = None,
        below: Optional[LayerKey] = None,
        visible: bool = True,
        pan_response: float = 1.0,
        zoom_response: float = 1.0,
        rotation_response: float = 1.0,
        scroll: Tuple[float, float] = (0.0, 0.0),
    ) -> Layer:
        """Create a custom **named** layer (string only).

        Numeric layers (``layer=10`` on a drawable) are a separate path —
        ``create(10)`` raises ``TypeError``. Specify exactly one of ``z``,
        ``above=``, or ``below=`` (or omit all for ``z=0``). Author ``z`` must
        be ≤ ``MAX_LAYER_Z`` (100); ``top`` is reserved at 101. ``above='top'``
        is rejected; ``below='top'`` is OK.

        Camera-response knobs (``pan_response``, ``zoom_response``,
        ``rotation_response``, ``scroll``) are **constructor-only** — frozen
        for the life of the layer. Defaults ``(1, 1, 1, (0, 0))`` match the
        full camera (neutral). Non-neutral layers are for decoration only:
        interactive / collidable shapes cannot live there
        (:class:`ParallaxLayerError`).
        """
        if not isinstance(name, str):
            raise TypeError(
                "canvas.layers.create() takes a string name; "
                "numeric layers come from layer=<int> on a drawable "
                f"(got {type(name).__name__})"
            )
        # A drawable's `layer=` write normalizes via ``normalize_layer_name``
        # (strips whitespace; blank -> None/undrawn). Store the same
        # stripped name here so `create(" hud ")` and later `layer="hud"` /
        # `layer=" hud "` all resolve to the same layer — otherwise the
        # padded name is created but can never be targeted, and an empty /
        # whitespace-only name creates a layer nothing can ever draw to.
        stripped_name = name.strip()
        if not stripped_name:
            raise ValueError(
                f"canvas.layers.create() name must not be blank, got {name!r}"
            )
        name = stripped_name
        stack = self._registry.layers
        specified = sum(x is not None for x in (z, above, below))
        if specified > 1:
            raise ValueError("Specify at most one of z=, above=, below=")
        if above is not None:
            if above == TOP_LAYER:
                raise ValueError(
                    f"Cannot create a layer above reserved '{TOP_LAYER}'"
                )
            if above == UI_LAYER:
                raise ValueError(
                    f"Cannot create a layer above reserved '{UI_LAYER}'"
                )
            z_val = stack.require(above).z + 1
        elif below is not None:
            z_val = stack.require(below).z - 1
        elif z is not None:
            if isinstance(z, bool) or not isinstance(z, (int, float)):
                raise TypeError(
                    f"z= must be a number, got {type(z).__name__}"
                )
            z_val = int(z)
        else:
            z_val = 0
        if scroll is None:
            scroll_t: Tuple[float, float] = (0.0, 0.0)
        else:
            from .validate import scroll_rate
            scroll_t = scroll_rate(scroll, "scroll")
        pan_response = float(pan_response)
        zoom_response = float(zoom_response)
        rotation_response = float(rotation_response)
        for resp_name, resp_val in (
            ("pan_response", pan_response),
            ("zoom_response", zoom_response),
            ("rotation_response", rotation_response),
        ):
            if not math.isfinite(resp_val):
                raise ValueError(f"{resp_name} must be finite, got {resp_val}")
        response = CameraResponse(
            pan_response=pan_response,
            zoom_response=zoom_response,
            rotation_response=rotation_response,
            scroll=scroll_t,
        )
        return stack.create(name, z=z_val, visible=visible, response=response)

    def __getitem__(self, name: LayerKey) -> Layer:
        """Return the named or numeric layer (same handle as ``create`` returns)."""
        return self._registry.layers.require(name)

    @property
    def default(self) -> str:
        """Layer name used as construction default when ``layer`` is omitted
        on non-Point shapes (Shape default is ``\"default\"``)."""
        return self._registry.layers.default

    @default.setter
    def default(self, name: str) -> None:
        self._registry.layers.default = name

    @contextmanager
    def using(self, name: str):
        """Temporarily set the construction default layer."""
        stack = self._registry.layers
        prev = stack.default
        stack.default = name
        try:
            yield
        finally:
            stack.default = prev

    def list(self) -> List[Dict[str, Any]]:
        """One dict per layer, in draw order: ``name``, ``z``, ``visible``, ``object_count``."""
        return self._registry.layers.list_info()

    def clear(self, *, hard: bool = False) -> None:
        """Clear objects from every layer.

        ``hard=False`` (default): soft — unregister_draw only.
        ``hard=True``: destroy (full teardown) each object.
        """
        if hard:
            self._registry.destroy_all()
        else:
            self._registry.clear_draw_list()

    def __contains__(self, name: object) -> bool:
        return name in self._registry.layers

    def __iter__(self) -> Iterator[LayerKey]:
        return iter(self._registry.layers)


def _class_keyword_groups_include(name: str) -> bool:
    """Some author class names ``name`` in its class keyword ``group=``."""
    from .entity import Entity
    stack = list(Entity.__subclasses__())
    seen = set()
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        stack.extend(cls.__subclasses__())
        for attr in ("_shape_defaults", "_class_defaults", "_sprite_defaults"):
            defs = cls.__dict__.get(attr)
            if not defs:
                continue
            g = defs.get("group")
            if g == name or (isinstance(g, (list, tuple, set, frozenset)) and name in g):
                return True
    return False


def declare_group_names(atoms) -> None:
    """Record the group names among a rule's sides on the current registry.

    ``atoms`` are side atoms (tag strings, ``group["tag"]``, actors, ...);
    only names are kept. Called by ``@collide`` / ``collide_with`` /
    ``resolve`` / ``@leave_playfield`` at registration.
    """
    try:
        from .canvas import ScenaCanvas
        registry = ScenaCanvas.get_current().registry
    except RuntimeError:
        return
    for atom in atoms:
        if isinstance(atom, str):
            registry.declare_group_name(atom)
        elif isinstance(atom, GroupOperator) and atom._group_id is not None:
            registry.declare_group_name(atom._group_id)


def above(name: LayerKey) -> int:
    """Return the layer number one step above ``name`` (``z + 1``).

    ``name`` may be a string or a number and must already exist. Does not
    invent the anchor. Results that would sit on or above reserved ``top``
    raise ``ValueError`` here.
    """
    ref = normalize_layer_name(name)
    if ref is None:
        raise TypeError("above() needs a layer name or number, not None")
    from .canvas import ScenaCanvas
    z = ScenaCanvas.get_current().registry.layers.require(ref).z + 1
    if z >= TOP_Z:
        raise ValueError(
            f"above({name!r}) is z={z}, above the author ceiling {MAX_LAYER_Z} "
            f"(reserved {TOP_LAYER!r} stays at {TOP_Z})"
        )
    return z


def below(name: LayerKey) -> int:
    """Return the layer number one step below ``name`` (``z - 1``).

    ``name`` may be a string or a number and must already exist. Does not
    invent the anchor. Does not check floors — the result is a plain int
    for use as ``layer=``.
    """
    ref = normalize_layer_name(name)
    if ref is None:
        raise TypeError("below() needs a layer name or number, not None")
    from .canvas import ScenaCanvas
    return ScenaCanvas.get_current().registry.layers.require(ref).z - 1


def _as_xy(point) -> Tuple[float, float]:
    """``(x, y)`` from a point-like: the one reading (``shapes._xy_of``)."""
    from .shapes import _xy_of
    try:
        return _xy_of(point, required=True)
    except TypeError:
        raise TypeError(
            "point must be (x, y) or have .x and .y, "
            f"got {type(point).__name__}"
        ) from None


def _member_xy(obj) -> Optional[Tuple[float, float]]:
    center = getattr(obj, "center", None)
    if center is not None:
        try:
            return _as_xy(center)
        except TypeError:
            pass
    try:
        return float(obj.x), float(obj.y)
    except (AttributeError, TypeError, ValueError):
        return None


def _member_aabb(obj) -> Optional[Tuple[float, float, float, float]]:
    """World AABB for group measurement (``group.box`` / ``nearest`` / centroid).

    Delegates to ``canvas._approx_draw_aabb`` — the same geometry draw/cull
    use — instead of a second, independently-maintained implementation.
    That function already prefers Defining parts (cold-safe: reading
    ``center`` on a ``Line`` or a TOP_LEFT_WH ``Rect`` first would wake a
    Derivate that then permanently loses the A1-A4 pose fast path — see
    Reactive Design "Hazard #1"), and already accounts for Sprite
    scale/rotation, Polygon vertices, and Text/SpatialFx ``_domain_aabb``.
    A second implementation had drifted: it ignored Sprite scale entirely
    and collapsed Polygon/Text to a single point (the center), which made
    ``canvas.frame_to(group.box)`` crop a scaled sprite and zoom in to
    ~1e-6 on a framed Polygon/Text group.
    """
    from .canvas import _approx_draw_aabb

    box = _approx_draw_aabb(obj)
    if box is not None:
        return box
    # Fall back to a degenerate point box for a center/x,y-only member with
    # no known extent (draw cull instead fails open — "keep drawing" — but
    # a group measurement should still count the member at its position).
    xy = _member_xy(obj)
    if xy is None:
        return None
    cx, cy = xy
    return (cx, cy, cx, cy)


def _require_pred(pred, *, what: str) -> None:
    if pred is None or not callable(pred):
        raise TypeError(
            f"{what} expected a function, got "
            f"{'None' if pred is None else type(pred).__name__}."
        )
    # An async predicate returns a coroutine, which is truthy: every member
    # would match and Python would only print "never awaited".
    _refuse_async(pred, what=what)


def _formula_result_members(registry: Registry, result) -> List[Shape]:
    if result is None:
        return []
    if isinstance(result, GroupOperator):
        return result._members()
    if isinstance(result, str):
        if registry.has_group_formula(result):
            return registry.eval_group_formula(result)
        return registry.list_by_groupid(result)
    if isinstance(result, (list, tuple)):
        return list(result)
    raise TypeError(
        "group formula must return a group, a tag name, or a list of members, "
        f"got {type(result).__name__}."
    )


def _normalize_group_formula_source(source, registry: Registry) -> Callable:
    """Callable stored for recompute-on-read. Rejects a frozen snapshot RHS."""
    if isinstance(source, str):
        name = source
        return lambda: GroupOperator(registry, group_id=name)
    if isinstance(source, GroupOperator):
        if not source.is_live:
            raise TypeError(
                "group['name'] @= already received a frozen snapshot "
                "(e.g. group['a'] | group['b']). Wrap the expression in "
                "lambda: … so it re-runs on each read."
            )
        fname = source._formula_name
        gid = source._group_id
        if fname:
            return lambda: GroupOperator(registry, formula_name=fname)
        return lambda: GroupOperator(registry, group_id=gid)
    if callable(source):
        return source
    raise TypeError(
        "group['name'] @= expected a lambda, a live group, or a tag name, "
        f"got {type(source).__name__}."
    )


def _part_destroyed_note(host) -> str:
    """The breadcrumb a dead part's refusal carries (``_destroyed_by``):
    ``a part of the Circle made at app.py:3, which was destroyed at …``."""
    from .entity import entity_label
    try:
        host_label = entity_label(host)
    except Exception:
        host_label = f"its {type(host).__name__}"
    host_note = getattr(host, "__dict__", {}).get("_destroyed_by")
    return f"a part of {host_label}, which was " + (host_note or "destroyed")


def entity_parts(obj) -> List[RegistryObject]:
    """``obj``'s Entity parts (its owned Points), deepest first; ``obj`` excluded."""
    try:
        nodes = list(obj._iter_subtree())
    except Exception:
        return []
    return [n for n in reversed(nodes)
            if n is not obj and getattr(type(n), "_scena_is_entity", False)]


def _member_not_name(verb: str, item: str, where: str) -> str:
    """``"heroi" in group["wasp"]`` — a string is a tag, never a member."""
    use = f"ship in {where}" if verb == "in" else f"{where}.index(ship)"
    return (
        f"{where} holds objects, not names: got {item!r}. Scena has no ids — "
        f"pass the object itself ({use}), or test a tag with ship.tagged({item!r})."
    )


_MISSING = object()
# Names a Blank accepted as an ink field (an empty group's write of a plain
# value to one of them is a no-op; see ``GroupOperator.__setattr__``).
_EMPTY_GROUP_FIELDS_OK: set = set()


def _blank_class_attr(name: str):
    """``name`` as defined on the Blank class (method / property / slot), or _MISSING."""
    import inspect
    return inspect.getattr_static(Blank, name, _MISSING)


def _empty_group_attr(name: str, label: str):
    """``group["x"].<name>`` on an empty group (Guia, Agir em massa).

    A method does nothing and returns None (neither the group nor a list); with
    ``time=`` it returns a Handle (a timed verb on a stand-in target). Built
    without constructing a Shape: a full ``Blank()`` per call cost ~0.3 ms, paid
    every frame by ``group["tiros"].move_by(...)`` while no shot is alive, and its
    roster entry made a run depend on GC timing (bug PM7).

    A field read raises: there is no member to read it from. It used to read
    a Blank built for the purpose, so ``group["boss"].center`` answered an
    invented (0, 0) once the boss was gone, built and registered a Blank per
    read (~0.1 ms), and ``.hp`` raised naming ``Blank`` (graphics review SC12).
    """
    attr = _blank_class_attr(name)
    on_blank = callable(attr) and not isinstance(attr, type)
    if not name.startswith("_") and (on_blank or name in _entity_method_names()):
        # Any member kind's method, not only a Shape's: group["inimigos"].play(...)
        # with no enemy left did raise AttributeError (the stand-in is a Shape;
        # found by test_noop_cost). A typo still raises below.
        def _noop(*args, **kwargs):
            if on_blank and (kwargs.get("time") is not None or kwargs.get("speed") is not None):
                from .process import _empty_group_timed
                handle = _empty_group_timed(kwargs)
                if handle is not None:
                    return handle
                return getattr(Blank(), name)(*args, **kwargs)
            return None
        return _noop
    raise AttributeError(
        f"{label} is empty: there is no member to read .{name} from. "
        f"Check {label}.empty first, or read {label}.centroid / {label}.box "
        f"(None when empty).",
        name=name, obj=None,
    )


_ENTITY_METHODS: Optional[frozenset] = None


def _entity_method_names() -> frozenset:
    """Public method names of every Entity kind (Shape, Sprite, Text, Track,
    widgets …): what a group member could answer to."""
    global _ENTITY_METHODS
    if _ENTITY_METHODS is None:
        import inspect
        from .entity import Entity
        names, stack, seen = set(), [Entity], set()
        while stack:
            cls = stack.pop()
            if cls in seen:
                continue
            seen.add(cls)
            stack.extend(cls.__subclasses__())
            if not cls.__module__.startswith("scena."):
                continue
            for n, v in vars(cls).items():
                if not n.startswith("_") and inspect.isfunction(v):
                    names.add(n)
        _ENTITY_METHODS = frozenset(names)
    return _ENTITY_METHODS


def _declares_group_formula(frame) -> bool:
    """Is the caller's ``group[name]`` the left side of ``group[name] @= …``?

    Python reads ``group[name]`` before the ``@=`` runs, so the near-miss
    guard saw the declaration of a new formula group as a read of an unknown
    name (AC9). Only consulted when a hint would be shown (an unknown name
    near a known one): the caller's bytecode after its subscript has the
    in-place ``@=`` right before the store back into the same subscript."""
    try:
        import dis
        code, at = frame.f_code, frame.f_lasti
        seen = False
        for ins in dis.get_instructions(code):
            if ins.offset <= at:
                continue
            if ins.opname == "BINARY_OP" and ins.argrepr == "@=":
                seen = True
            elif ins.opname == "STORE_SUBSCR":
                return seen
            elif ins.opname in ("POP_TOP", "RETURN_VALUE", "RETURN_CONST", "STORE_NAME",
                                "STORE_FAST", "STORE_GLOBAL", "STORE_ATTR"):
                return False
    except Exception:
        return False
    return False


class GroupOperator:
    """Global ``group["name"]`` — live named group, formula group, or snapshot.

    Author contract:
      - ``group['rects']`` — live view of ``group_map['rects']``
      - ``group['enemies'] @= lambda: group['a'] | group['b']`` — named live
        formula (recompute-on-read)
      - Walk order on a named tag is **join order** (not spatial)
      - Every walk that yields members copies at enter (``for``, ``any`` /
        ``all`` / ``count_where`` / ``filter`` / ``nearest`` / ``centroid`` /
        ``box``, ``index``, ``first`` / ``last`` / ``[i]``, bulk ``destroy`` /
        ``tag`` / ``untag``). Destroy / tag / spawn during that walk is safe;
        the next call sees joiners.
      - ``count`` / ``empty`` / ``len`` stay O(1) on a live tag; formula
        groups are O(n) (recompute)
      - ``group['a'] | group['b']`` — snapshot (fixed member list)
      - ``group['a'].filter(pred)`` — snapshot of members matching ``pred``
      - Membership changes only via ``shape.add_to_group`` / ``remove_from_group``
      - ``@click(group['x'])`` follows the tag (members joining later get the
        handler, leavers lose it); a snapshot wires its members of the moment
      - Groups are **not** a process owner (no ``group.every`` / ``group.on_update``)
    """

    __slots__ = ('_registry', '_group_id', '_snapshot', '_formula_name', '__weakref__')

    def __init__(
        self,
        registry: Registry,
        *,
        group_id: Optional[str] = None,
        snapshot: Optional[List[Shape]] = None,
        formula_name: Optional[str] = None,
    ) -> None:
        self._registry = registry
        self._group_id = group_id
        self._snapshot = None if snapshot is None else list(snapshot)
        self._formula_name = formula_name

    def _is_root(self) -> bool:
        return (
            self._group_id is None
            and self._snapshot is None
            and self._formula_name is None
        )

    def _named(self) -> Optional[str]:
        return self._formula_name or self._group_id

    def __call__(self, group_id: str = "name", *args, **kwargs) -> 'GroupOperator':
        shown = group_id if isinstance(group_id, str) else "name"
        raise TypeError(
            f"group({shown!r}) is not used anymore; write group[{shown!r}] "
            f"(brackets, like a dict lookup)."
        )

    def _members(self) -> List[Shape]:
        if self._formula_name is not None:
            return self._registry.eval_group_formula(self._formula_name)
        if self._group_id is not None:
            return self._registry.list_by_groupid(self._group_id)
        return list(self._snapshot or [])

    def _iter_members(self) -> Iterator[Shape]:
        # Copy at enter. Walking the live membership store while it mutates
        # (destroy / tag / spawn / GC) is unsafe; count / empty on a tag stay
        # O(1) and do not copy.
        return iter(self._members())

    @property
    def is_live(self) -> bool:
        """True for ``group['tag']`` (follows the tag); False for a snapshot (``.filter()``, ``|`` …)."""
        return self._group_id is not None or self._formula_name is not None

    @property
    def is_linked(self) -> bool:
        """True if this group is defined by a formula (``group['x'] @= lambda: …``)."""
        name = self._named()
        if name is None:
            return False
        return self._registry.has_group_formula(name)

    def unlink(self) -> 'GroupOperator':
        """Drop a formula; this name becomes an empty tag view."""
        name = self._named()
        if name is None:
            if self._is_root():
                raise TypeError(
                    "cannot unlink the root group; bind a name: "
                    "group['enemies'] @= lambda: …"
                )
            raise TypeError(
                "cannot unlink a snapshot group "
                "(e.g. group['a'] | group['b'])."
            )
        self._registry.unlink_group_formula(name)
        self._formula_name = None
        self._group_id = name
        return self

    def __imatmul__(self, source) -> 'GroupOperator':
        name = self._named()
        if name is None:
            raise TypeError(
                "cannot @= on a snapshot group (e.g. group['a'] | group['b']). "
                "Bind a name: group['enemies'] @= lambda: ..."
            )
        fn = _normalize_group_formula_source(source, self._registry)
        self._registry.set_group_formula(name, fn)
        self._formula_name = name
        self._group_id = None
        return self

    def __setitem__(self, key, value) -> None:
        if not self._is_root():
            raise TypeError(
                f"group[{key!r}] does not support plain assignment; "
                f"use group[{key!r}] @= lambda: ... to bind a live formula"
                if isinstance(key, str)
                else "cannot assign into a group by index."
            )
        if (
            isinstance(key, str)
            and isinstance(value, GroupOperator)
            and (value._group_id == key or value._formula_name == key)
        ):
            return
        raise TypeError(
            f"group[{key!r}] does not support plain assignment; "
            f"use group[{key!r}] @= lambda: ... to bind a live formula"
        )

    @property
    def count(self) -> int:
        """Live member count. O(1) for named tags; O(n) for formula groups."""
        if self._formula_name is not None:
            return len(self._members())
        if self._group_id is not None:
            return self._registry.group_live_count(self._group_id)
        return len(self._snapshot or [])

    @property
    def empty(self) -> bool:
        """True iff ``count == 0``. A sync read — not a predicate for ``until()``."""
        return self.count == 0

    def __iter__(self) -> Iterator[Shape]:
        return self._iter_members()

    def __len__(self) -> int:
        return self.count

    def __bool__(self) -> bool:
        return self.count > 0

    def __getitem__(self, key: Union[int, slice, str]) -> Union[Shape, List[Shape], 'GroupOperator']:
        if isinstance(key, str):
            if not self._is_root():
                label = self._named()
                hint = (
                    f"group[{label!r}][0]"
                    if label is not None
                    else "an integer index on this group"
                )
                raise TypeError(
                    f"group[{key!r}] looks up a named group on the root `group` only. "
                    f"To index members use an integer: {hint}."
                )
            if self._registry.has_group_formula(key):
                return GroupOperator(self._registry, formula_name=key)
            # Near-miss guard for typos. An empty group is not a typo when the
            # name ever had a member (the bucket was dropped) or a rule names
            # it (nothing joined yet): Actors Design, Group names.
            if not self._registry.group_name_known(key):
                from .validate import did_you_mean
                hint = did_you_mean(key, self._registry.known_group_names())
                if hint and not _declares_group_formula(sys._getframe(1)):
                    import warnings
                    warnings.warn(
                        f"No group {key!r}.{hint} A new name is an empty view.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
            return GroupOperator(self._registry, group_id=key)
        if self._is_root():
            raise TypeError(
                "cannot index the root group; bind a name: "
                "group['wasp'][0]"
            )
        members = self._members()
        if isinstance(key, slice):
            return members[key]
        try:
            return members[key]
        except IndexError:
            n = len(members)
            where = self._where_label()
            if n == 0:
                raise IndexError(f"{where} is empty.") from None
            raise IndexError(
                f"index {key} out of range for {where} "
                f"({n} member{'s' if n != 1 else ''})."
            ) from None

    def __contains__(self, item: Shape) -> bool:
        if isinstance(item, str):
            raise TypeError(_member_not_name("in", item, self._where_label()))
        return item in self._members()

    def _where_label(self) -> str:
        name = self._named()
        if name is not None:
            return f"group[{name!r}]"
        return "this group"

    def index(self, item: Shape) -> int:
        """0-based join-order rank of ``item``.

        Inverse of ``group['wasp'][i]``. ``item`` is the actor itself (a
        string raises ``TypeError``: there are no ids). Missing member raises ``ValueError``
        (not ``-1`` / ``None``). Rank is live: an earlier leave closes the
        gap. Not a sticky formation slot — stamp ink at birth for a number
        that must not move. Root ``group.index(...)`` raises ``TypeError``.
        """
        if self._is_root():
            raise TypeError(
                "cannot .index() the root group; bind a name: "
                "group['wasp'].index(obj)"
            )
        if isinstance(item, str):
            raise TypeError(_member_not_name("index", item, self._where_label()))
        for i, obj in enumerate(self._members()):
            if obj is item:
                return i
        from .entity import entity_label
        where = self._where_label()
        shown = entity_label(item) if getattr(type(item), "_scena_is_entity", False) else repr(item)
        raise ValueError(
            f"{shown} is not in {where}. "
            f"Check membership with: item in {where}"
        )

    def _end_member(self, which: str) -> Shape:
        if self._is_root():
            raise TypeError(
                f"cannot .{which} the root group; bind a name: "
                f"group['wasp'].{which}"
            )
        members = self._members()
        if not members:
            raise IndexError(f"{self._where_label()} is empty.")
        return members[0] if which == "first" else members[-1]

    @property
    def first(self) -> Shape:
        """Join-order first member. Same as ``group['wasp'][0]``.

        Live: the oldest current member. Empty raises ``IndexError`` (not
        ``None``). Root ``group.first`` raises ``TypeError``.
        """
        return self._end_member("first")

    @property
    def last(self) -> Shape:
        """Join-order last member. Same as ``group['wasp'][-1]``.

        Live: who is at the end now (re-tag after untag appends). Empty
        raises ``IndexError`` (not ``None``). Root ``group.last`` raises
        ``TypeError``.
        """
        return self._end_member("last")

    def _author_label(self) -> str:
        """How the author wrote this group, for a message."""
        if self._group_id is not None:
            return f"group[{self._group_id!r}]"
        if self._formula_name is not None:
            return f"group[{self._formula_name!r}]"
        return "this group (a snapshot)"

    def __getattr__(self, name: str):
        # Groups may mix Shape and SpatialFx (both Entity). Attribute/method
        # forwarding applies to every current member — if a Shape-only API
        # (handles, set_color, contains_point, …) is called on a mixed group,
        # members that lack the attribute raise AttributeError (honest failure;
        # do not silently skip). Prefer Shape-only groups for those APIs, or
        # iterate members and filter yourself.
        members = self._members()
        if not members:
            return _empty_group_attr(name, self._author_label())

        first_attr = getattr(members[0], name)
        if callable(first_attr):
            def wrapper(*args, **kwargs):
                current = self._members()
                reg = self._registry
                gen = reg._destroy_gen
                results = []
                append = results.append
                skipped = None
                for obj in current:
                    try:
                        append(getattr(obj, name)(*args, **kwargs))
                    except DestroyedError:
                        # A member an earlier member's call destroyed (a chain
                        # reaction) is skipped: the author cannot guard inside
                        # a broadcast (review 2026-10-09 S9-3). A member dead
                        # before the broadcast still raises.
                        if reg._destroy_gen == gen or not getattr(obj, "_destroyed", False):
                            raise
                        if skipped is None:
                            skipped = set()
                        skipped.add(id(obj))
                called = current if skipped is None else [
                    o for o in current if id(o) not in skipped]
                if results and all(r is obj for r, obj in zip(results, called)):
                    return self
                return results
            return wrapper

        if len(members) == 1:
            return first_attr
        return [getattr(obj, name) for obj in members]

    def __setattr__(self, name: str, value) -> None:
        # Same mixed-membership caveat as ``__getattr__``: setattr on a name
        # that only some members define can raise AttributeError.
        if name.startswith('_'):
            object.__setattr__(self, name, value)
            return
        members = self._members()
        if not members:
            # A known field: nothing to write (no member). Anything else goes
            # through a Blank, which keeps the error an unknown name gives.
            if _blank_class_attr(name) is _MISSING:
                # A Blank decides what an unknown name means (a new field, a
                # typo, a callable …). Once a name was accepted as a field,
                # writing a plain value to it again builds nothing: a Blank
                # per write cost ~0.3 ms and two roster entries (S9-8).
                plain = not (callable(value) and not isinstance(value, type))
                if plain and name in _EMPTY_GROUP_FIELDS_OK:
                    return
                setattr(Blank(), name, value)
                if plain:
                    _EMPTY_GROUP_FIELDS_OK.add(name)
            return
        reg = self._registry
        gen = reg._destroy_gen
        for obj in members:
            if reg._destroy_gen != gen and getattr(obj, "_destroyed", False):
                continue    # destroyed by an earlier member's setter (S9-3)
            setattr(obj, name, value)

    def _resolve_other(self, other: Union[str, 'GroupOperator']) -> List[Shape]:
        if isinstance(other, str):
            if self._registry.has_group_formula(other):
                return _formula_result_members(
                    self._registry, self._registry.eval_group_formula(other)
                )
            return self._registry.list_by_groupid(other)
        if isinstance(other, GroupOperator):
            return other._members()
        raise TypeError("other must be a group_id string or GroupOperator")

    def _snapshot_from(self, objects: List[Shape]) -> 'GroupOperator':
        return GroupOperator(self._registry, snapshot=list(objects))

    def union(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        """Members of either group, no duplicates, this group first — a snapshot."""
        seen: Set[int] = set()
        out: List[Shape] = []
        for obj in self._members():
            key = id(obj)
            if key not in seen:
                seen.add(key)
                out.append(obj)
        for obj in self._resolve_other(other):
            key = id(obj)
            if key not in seen:
                seen.add(key)
                out.append(obj)
        return self._snapshot_from(out)

    def intersection(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        """Members in both this group and ``other`` (a group or a tag name) — a snapshot."""
        right = {id(obj) for obj in self._resolve_other(other)}
        return self._snapshot_from(
            [obj for obj in self._members() if id(obj) in right]
        )

    def difference(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        """Members of this group that are not in ``other`` (a group or a tag name) — a snapshot."""
        right = {id(obj) for obj in self._resolve_other(other)}
        return self._snapshot_from(
            [obj for obj in self._members() if id(obj) not in right]
        )

    def symmetric_difference(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        """Members in exactly one of the two groups — a snapshot."""
        a = self._members()
        b = self._resolve_other(other)
        bset = {id(obj) for obj in b}
        aset = {id(obj) for obj in a}
        out = [obj for obj in a if id(obj) not in bset]
        out.extend(obj for obj in b if id(obj) not in aset)
        return self._snapshot_from(out)

    def as_set(self) -> Set[Shape]:
        """The current members as a plain Python ``set``."""
        return set(self._members())

    def destroy(self) -> 'GroupOperator':
        """Bulk teardown of current members (wave clear, restart)."""
        for obj in self._iter_members():
            obj.destroy()
        return self

    def tag(self, *names: str) -> 'GroupOperator':
        """Add every current member to each named group."""
        for obj in self._iter_members():
            obj.tag(*names)
        return self

    def untag(self, *names: str) -> 'GroupOperator':
        """Remove every current member from each named group."""
        for obj in self._iter_members():
            obj.untag(*names)
        return self

    def filter(self, pred: Callable) -> 'GroupOperator':
        """Snapshot of members for which ``pred(member)`` is true.

        Fixed membership at call time (same kind as ``group['a'] | group['b']``).
        Join order of the source is kept.
        """
        _require_pred(pred, what="filter()")
        return self._snapshot_from(
            [obj for obj in self._iter_members() if pred(obj)]
        )

    def any(self, pred: Callable) -> bool:
        """True if ``pred(member)`` holds for any current member (short-circuit)."""
        _require_pred(pred, what="any()")
        for obj in self._iter_members():
            if pred(obj):
                return True
        return False

    def all(self, pred: Callable) -> bool:
        """True if ``pred(member)`` holds for every current member (short-circuit).

        Vacuous on an empty group (same as Python ``all([])``).
        """
        _require_pred(pred, what="all()")
        for obj in self._iter_members():
            if not pred(obj):
                return False
        return True

    def count_where(self, pred: Callable) -> int:
        """Count members matching ``pred`` without building a match list."""
        _require_pred(pred, what="count_where()")
        n = 0
        for obj in self._iter_members():
            if pred(obj):
                n += 1
        return n

    def nearest(
        self,
        point,
        where: Optional[Callable] = None,
        *,
        within: Optional[float] = None,
    ):
        """Closest member to ``point`` (world units), or ``None`` if none match.

        ``point`` is any point-like: ``(x, y)``, Point, Vec2, a Graphic
        (its ``.center``), or ``mouse``. Optional
        ``where=`` restricts candidates (``pred(member) -> bool``). Optional
        ``within=`` caps Euclidean distance (inclusive). Same metric as the
        standalone ``nearest(origin, items)`` helper.
        """
        return _nearest_item(point, self, where=where, within=within)

    @property
    def centroid(self) -> Optional[Tuple[float, float]]:
        """Average position of members with a known center, or ``None`` if empty."""
        sx = sy = 0.0
        n = 0
        for obj in self._iter_members():
            xy = _member_xy(obj)
            if xy is None:
                continue
            sx += xy[0]
            sy += xy[1]
            n += 1
        if n == 0:
            return None
        return (sx / n, sy / n)

    def _aabb(self) -> Optional[Tuple[float, float, float, float]]:
        """AABB ``(minx, miny, maxx, maxy)`` of live members, or ``None`` if empty."""
        box = None
        for obj in self._iter_members():
            aabb = _member_aabb(obj)
            if aabb is None:
                continue
            if box is None:
                box = [aabb[0], aabb[1], aabb[2], aabb[3]]
            else:
                if aabb[0] < box[0]:
                    box[0] = aabb[0]
                if aabb[1] < box[1]:
                    box[1] = aabb[1]
                if aabb[2] > box[2]:
                    box[2] = aabb[2]
                if aabb[3] > box[3]:
                    box[3] = aabb[3]
        if box is None:
            return None
        return (box[0], box[1], box[2], box[3])

    @property
    def box(self) -> Optional["Box"]:
        """Fresh measuring Box over live members' AABB, or None if empty.

        None when the group has no members, or none of its members expose
        measurable geometry (``.radius``, ``.width``+``.height``, ``p1``/``p2``,
        or ``.x``+``.y``) — same emptiness rule as ``.centroid``. Rotated
        members contribute their axis-aligned bounds; the Box angle is always
        0. A single-member or fully-coincident group is a legal *collapsed*
        Box (width=0 and/or height=0 at that point).
        """
        aabb = self._aabb()
        if aabb is None:
            return None
        from .box import Box
        return Box._from_aabb(*aabb)

    def __or__(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        return self.union(other)

    def __and__(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        return self.intersection(other)

    def __sub__(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        return self.difference(other)

    def __xor__(self, other: Union[str, 'GroupOperator']) -> 'GroupOperator':
        return self.symmetric_difference(other)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GroupOperator):
            return set(self._members()) == set(other._members())
        if isinstance(other, str):
            return set(self._members()) == set(self._resolve_other(other))
        return NotImplemented

    def issubset(self, other: Union[str, 'GroupOperator']) -> bool:
        """True if every member here is also in ``other``."""
        return set(self._members()).issubset(set(self._resolve_other(other)))

    def issuperset(self, other: Union[str, 'GroupOperator']) -> bool:
        """True if every member of ``other`` is also here."""
        return set(self._members()).issuperset(set(self._resolve_other(other)))

    def __le__(self, other: Union[str, 'GroupOperator']) -> bool:
        return self.issubset(other)

    def __ge__(self, other: Union[str, 'GroupOperator']) -> bool:
        return self.issuperset(other)

    def __copy__(self) -> 'GroupOperator':
        if self._formula_name is not None:
            return GroupOperator(self._registry, formula_name=self._formula_name)
        if self._group_id is not None:
            return GroupOperator(self._registry, group_id=self._group_id)
        return GroupOperator(self._registry, snapshot=list(self._snapshot or []))

    def __deepcopy__(self, memo) -> 'GroupOperator':
        # Shapes are shared; only the operator shell is copied.
        return self.__copy__()

    def __str__(self) -> str:
        if self._formula_name is not None:
            label = f"Group '{self._formula_name}' (formula"
        elif self._group_id is not None:
            label = f"Group '{self._group_id}' (live"
        else:
            label = "Group (snapshot"
        members = self._members()
        lines = [f"{label}, {len(members)} objects)"]
        for obj in members:
            lines.append(f"  - {obj}")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return self.__str__()
