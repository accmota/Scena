from typing import Any, Callable, Dict, List, Optional, Union, TypeVar, Set, Tuple
from enum import Enum
from functools import wraps
import inspect
import math
import warnings
import weakref

from contextlib import contextmanager
from contextvars import ContextVar
from abc import abstractmethod
from collections import defaultdict, deque


_check_circular_reference = True

# When True, unowned Containers skip dependency-graph registration until they
# become an owned part or a formula source/target (via add_dependency). Prevents
# bare Vec2/Point scratch values from leaking strong refs into the graph.
_lazy_container_registration = True


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


def set_lazy_container_registration(enabled: bool) -> None:
    """Test/debug escape hatch for eager vs lazy Container graph registration."""
    global _lazy_container_registration
    _lazy_container_registration = bool(enabled)


# When True, DependencyGraph.nodes holds weak refs and a weakref.finalize per
# registered container purges edge maps when Python collects the object.
# Default on (leak-class backstop). Escape hatch mirrors
# set_lazy_container_registration; call init_scena_system() after toggling so
# the live graph picks up the matching nodes storage.
_graph_gc_backstop = True


def set_graph_gc_backstop(enabled: bool) -> None:
    """Test/debug escape hatch for GC-backed DependencyGraph eviction."""
    global _graph_gc_backstop
    _graph_gc_backstop = bool(enabled)


def graph_gc_backstop_enabled() -> bool:
    return _graph_gc_backstop


# When True, newly constructed Containers skip dependency-graph registration.
# Used for temporary Point/Vec2 results from arithmetic so formula evaluation
# does not leak nodes into the graph every frame.
_ephemeral_creation: ContextVar[bool] = ContextVar('_ephemeral_creation', default=False)


@contextmanager
def ephemeral_creation():
    """Create Containers that are not registered in the dependency graph."""
    token = _ephemeral_creation.set(True)
    try:
        yield
    finally:
        _ephemeral_creation.reset(token)


# Parts materialized under a deferred tree (a measured Box, see
# ``Container._in_deferred_graph_tree``) are built with registration off:
# the tree joins the graph as a whole, on its first link.
_registration_deferred: ContextVar[bool] = ContextVar('_registration_deferred', default=False)


@contextmanager
def _deferred_registration():
    token = _registration_deferred.set(True)
    try:
        yield
    finally:
        _registration_deferred.reset(token)


def is_ephemeral_creation() -> bool:
    return _ephemeral_creation.get()

from .easing import MappingFunctions, remap, lerp
from .closed import ClosedSurface, make_closed_setattr

T = TypeVar('T')  # Generic type for values
Number = Union[int, float]  # Type alias for numeric types

# ``entity._placement_write``: an author ``<<`` on an actor or its part is a
# collision placement (set by entity at import; state does not import entity).
_PLACEMENT_HOOK = None

class ContainerSet:
    """
    A set-like class that uses object identity (id()) for comparison instead of __eq__.
    This is useful for Container objects that have value-based __eq__ but need
    identity-based set operations.
    """

    # Closed surface at no cost (reachable as ``obj.parts``): no ``__dict__``.
    __slots__ = ("_dict",)
    
    def __init__(self, iterable=None):
        self._dict = {}
        if iterable is not None:
            for item in iterable:
                self.add(item)
    
    def add(self, item):
        """Add an item to the set."""
        self._dict[id(item)] = item
    
    def remove(self, item):
        """Remove an item from the set."""
        item_id = id(item)
        if item_id in self._dict:
            del self._dict[item_id]
        else:
            raise KeyError(item)
    
    def discard(self, item):
        """Remove an item from the set if present."""
        self._dict.pop(id(item), None)
    
    def clear(self):
        """Remove all items from the set."""
        self._dict.clear()
    
    def __contains__(self, item):
        """Check if an item is in the set."""
        return id(item) in self._dict
    
    def __iter__(self):
        """Iterate over the items in the set."""
        return iter(self._dict.values())
    
    def __len__(self):
        """Get the number of items in the set."""
        return len(self._dict)
    
    def __repr__(self):
        """String representation of the set."""
        return f"ContainerSet({list(self._dict.values())})"
    
    def copy(self):
        """Create a copy of the set."""
        return ContainerSet(self._dict.values())
    
    def update(self, iterable):
        """Add all items from iterable to the set."""
        for item in iterable:
            self.add(item)
    
    def union(self, other):
        """Return the union of this set and another."""
        result = self.copy()
        result.update(other)
        return result
    
    def intersection(self, other):
        """Return the intersection of this set and another."""
        result = ContainerSet()
        for item in other:
            if item in self:
                result.add(item)
        return result
    
    def difference(self, other):
        """Return the difference of this set and another."""
        result = ContainerSet()
        for item in self:
            if item not in other:
                result.add(item)
        return result
    
    def symmetric_difference(self, other):
        """Return the symmetric difference of this set and another."""
        result = ContainerSet()
        for item in self:
            if item not in other:
                result.add(item)
        for item in other:
            if item not in self:
                result.add(item)
        return result
    
    def issubset(self, other):
        """Check if this set is a subset of another."""
        for item in self:
            if item not in other:
                return False
        return True
    
    def issuperset(self, other):
        """Check if this set is a superset of another."""
        for item in other:
            if item not in self:
                return False
        return True
    
    def __eq__(self, other):
        """Check if this set equals another set."""
        if not isinstance(other, (ContainerSet, set)):
            return False
        if len(self) != len(other):
            return False
        for item in self:
            if item not in other:
                return False
        return True
    
    def __ne__(self, other):
        """Check if this set is not equal to another set."""
        return not self.__eq__(other)


def get_owner_chain(obj: 'Container') -> List['Container']:
    """Get the chain of owners for a Container, excluding itself."""
    chain = []
    current = obj
    while current.owner is not None:
        current = current.owner
        chain.append(current)
    return chain


# Dot/create names that would shadow State methods. ``name`` is rejected
# separately (read-only diagnostic label).
_STATE_RESERVED_CELLS = frozenset({"keys", "exists", "create", "remove"})


def _state_key(key, verb: str) -> None:
    """A State variable name is a string, checked before any dict lookup (a
    list leaked "unhashable type": A1 class, found again by the gate's
    surface fuzz once ``unhashable type`` counted as a leak)."""
    if type(key) is not str:
        raise TypeError(f"State.{verb}() takes a variable name (str), got "
                        f"{type(key).__name__} {key!r:.30}")


class State:
    """Named bag of Attribute cells.

    Dot access reads the cell's **value** (``st.mic is None``, ``type(st.n)``,
    ``best = st.score`` copies), the same as an Entity field. Bracket access
    returns a FieldRef: the handle that links (``st["k"] @= …``) and binds
    (``Slider(st["volume"])``, ``Text(st["score"])``, ``@on_change(st["wave"])``)
    — the same spelling as Shape/Entity fields. Before 0.8.0 the dot read
    returned the cell itself, so ``st.mic is None`` was always False.

    ``name`` is a diagnostic label for FieldRef / LinkedAttributeError
    messages (same role as Container.name). The builtin bag is constructed
    as ``State(name="st")``. Unlabeled ``State()`` uses ``"State"`` so a
    second bag does not pretend to be the global.
    """

    def __init__(self, name: str = "State") -> None:
        if not isinstance(name, str):
            raise TypeError(f"State name must be a str, got {type(name).__name__}")
        if not name:
            raise ValueError("State name must be a non-empty str")
        self._name = name
        self._data = {}  # Store Attribute objects
        self._watchers = {}

    @property
    def name(self) -> str:
        """Diagnostic label for FieldRef / LinkedAttributeError messages."""
        return self._name

    def __str__(self) -> str:
        """Return a readable string representation of the state"""
        items = []
        for k, v in self._data.items():
            items.append(f'{k}={v.value}')
        body = ', '.join(items)
        if body:
            return f"State({self._name!r}, {body})"
        return f"State({self._name!r})"

    def __repr__(self) -> str:
        """Return a detailed string representation"""
        items = []
        for k, v in self._data.items():
            items.append(f'{k}={v.value}')
        return f"State(name={self._name!r}, data={{{', '.join(items)}}})"

    def _new_cell(self, key: str, initial: Any) -> 'Attribute':
        """Create a boxed cell whose diagnostic path includes this bag's label."""
        attr = Attribute(initial, attr_name=key)
        attr._name = f"{self._name}.{key}"
        attr._state_bag = weakref.ref(self)
        return attr

    def __getattr__(self, key: str) -> Any:
        """``st.key`` reads the cell's value (pull-resolves a linked cell).

        Hot path: an unlinked cached leaf returns ``_raw_value`` without the
        ``Attribute.value`` property call (same test as that property).
        """
        try:
            cell = self._data[key]
        except KeyError:
            raise AttributeError(self._missing_cell_message(key)) from None
        d = cell.__dict__
        if d.get('_bare_ok') is True and d['_link'] is None:
            return d['_raw_value']
        return cell.value

    def _missing_cell_message(self, key: str) -> str:
        from .validate import did_you_mean
        who = self._name
        return (
            f"{who} has no cell {key!r}. Create it first: {who}.{key} = 0 "
            f"(any starting value), then read {who}.{key} or link {who}['{key}'] @= …."
            f"{did_you_mean(key, self._data)}"
        )

    def __setattr__(self, key: str, value: Any) -> None:
        """Allow setting values using dot notation: state.key = value"""
        if key.startswith('_'):  # Allow setting private attributes normally
            super().__setattr__(key, value)
            return
        if _SOLVER_READING:
            refuse_if_solver_reading(f"{self._name}.{key} = …")
        if key == 'name' or key in _STATE_RESERVED_CELLS:
            raise AttributeError(
                f"{self._name}.{key} is reserved (part of the state object itself). "
                f"Pick another key, e.g. {self._name}.player_{key} = …"
            )
        if isinstance(value, _PLAIN_FUNCTIONS):
            raise CallableAssignError(callable_assign_message(self._name, key))

        cell = self._data.get(key)
        if cell is None:
            self._data[key] = self._new_cell(key, value)
        elif value is cell._raw_value and type(value) not in _VALUE_TYPES:
            # ``st.pos += v`` / ``st.items += [x]``: ``st.pos`` is the held
            # object, ``+=`` changed it in place and assigns it back. The cell
            # sees the same object, so it would notify nothing (0.8.0). A Vec2
            # already told the cell, from its own ``update()`` (_HeldPayloadUpdate).
            if value.__class__ is not _HELD_BY_VALUE:
                cell._changed_in_place()
        else:
            # What ``cell.value = value`` runs, without the closed-surface
            # ``__setattr__`` and the property hop (pays for the check above).
            cell._assign_value(value)

    def __getitem__(self, key: str) -> 'FieldRef':
        """Link handle. Does not create a cell — ``@=`` does, reads must exist."""
        if not isinstance(key, str):
            raise TypeError(f"field name must be a str, got {type(key).__name__}")
        if key == "name" or key in _STATE_RESERVED_CELLS:
            raise AttributeError(
                f"{self._name}.{key} is reserved (part of the state object itself). "
                f"Pick another key, e.g. {self._name}.player_{key} = …"
            )
        return FieldRef(owner=self, name=key)

    def __setitem__(self, key: str, value) -> None:
        """Write-back target for ``st[key] @= source``. Plain assignment is an error."""
        if isinstance(value, FieldRef) and value.owner is self and value.name == key:
            return
        raise TypeError(
            f"State[...] does not support plain assignment; "
            f"use '{key} = value' for a concrete value or '[...] @= ...' to link"
        )

    def _resolve_cell(self, key: str):
        """Return the Attribute for ``key``, or raise AttributeError."""
        if not isinstance(key, str):
            raise TypeError(f"field name must be a str, got {type(key).__name__}")
        if key not in self._data:
            raise AttributeError(self._missing_cell_message(key))
        return self._data[key]

    def _link_field(self, name: str, source) -> None:
        """Install a formula/direct link on cell ``name`` (bracket ``@=``)."""
        source = _normalize_link_rhs(source)
        if not callable(source) and not isinstance(source, Container):
            raise TypeError(_LINK_RHS_ERROR)
        if name == "name" or name in _STATE_RESERVED_CELLS:
            raise AttributeError(
                f"{self._name}.{name} is reserved (part of the state object itself). "
                f"Pick another key, e.g. {self._name}.player_{name} = …"
            )
        if name not in self._data:
            self._data[name] = self._new_cell(name, 0)
        self._data[name]._assign_formula(source)

    def _linkable_source(self, name: str) -> 'Attribute':
        """Graph node for ``st[name]`` as a DirectLink RHS."""
        return self._resolve_cell(name)

    def _unlink_field(self, name: str) -> None:
        self._resolve_cell(name).unlink()

    def _read_field(self, name: str):
        """Payload of cell ``name`` (FieldRef.value contract)."""
        return self._resolve_cell(name).value

    def _field_is_linked(self, name: str) -> bool:
        return self._resolve_cell(name)._link is not None

    def _write_field(self, name: str, value) -> None:
        """Write a concrete value onto cell ``name``. Raises if the cell is linked."""
        attr = self._resolve_cell(name)
        attr._refuse_author_write()
        attr._takein(value)

    def create(self, key: str, initial: Any = None) -> None:
        """
        Create or update a state variable.

        Args:
            key: The state variable name
            initial: Initial value (default 0)
        """
        _state_key(key, "create")
        if key == 'name':
            raise AttributeError("State.name is read-only")
        if key in _STATE_RESERVED_CELLS:
            raise AttributeError(f"State.{key} is reserved")
        if isinstance(initial, _PLAIN_FUNCTIONS):
            raise CallableAssignError(callable_assign_message(self._name, key))
        if key not in self._data:
            if initial is None:
                initial = 0
            self._data[key] = self._new_cell(key, initial)
        else:
            var_instance = self._data[key]
            if initial is not None:
                var_instance.value = initial

    def exists(self, key: str) -> bool:
        """Check if a key exists in the state"""
        _state_key(key, "exists")
        return key in self._data

    def keys(self) -> Set[str]:
        """Return all state keys"""
        return self._data.keys()

    def remove(self, key: str) -> None:
        """
        Remove a state variable and tear it down from the reactive system.

        Calls ``Attribute._clean_up()`` (auto-unlinks external dependents that
        referenced this variable, unregisters from the DependencyGraph) and
        drops the key from this State. Raises KeyError if the key is absent.
        """
        _state_key(key, "remove")
        if key not in self._data:
            raise KeyError(f"State has no variable {key!r}")
        attr = self._data.pop(key)
        attr._clean_up()


# Auto-unlink notice override. ``scena.act`` installs one: during an act
# change it silences dependents that leave in the same batch and names the
# acts for a game object left reading an act object. Returns True when it
# handled the notice (no generic warning then). ``None`` = generic warning.
_UNLINK_NOTICE_HOOK: Optional[Callable[[Any, Any], bool]] = None

# Set by ``act.ActManager._seal`` in a game with acts: ``FieldRef.__imatmul__``
# calls it with ``(owner, name)`` before linking; it returns a callable to run
# once the link is installed (or None). An act's link on a game object is
# undone at the act change (Act Design, Removed; review 2026-10-14 PA1).
_ACT_LINK_HOOK: Optional[Callable[[Any, str], Optional[Callable[[], None]]]] = None


# ------------------------------------------------------------------------------------------------

def _already_suppressing_updates(container) -> bool:
    """True if leaf writes on container's subtree already skip update().

    Nested batching (batch_update_attrs inside no_update, Point._takein inside
    an outer batch, etc.) would otherwise re-walk the same ownership subtree
    just to set flags that are already True.

    Only checks `_in_batch_update` — not `update_manager.is_updating`. The
    outermost _no_update() in _recalculate_formula runs *after* is_updating is
    set, and must still push flags so Derivate writes inside _update_impl
    pass _ensure_not_derivate and leaf Attribute.update() stays suppressed.
    """
    return bool(getattr(container, '_in_batch_update', False))


def batch_update_attrs(*attr_names):
    """
    Decorator that batches updates for the named attributes and their part subtrees.

    Sets _in_batch_update on each named container and all descendants so leaf
    Attribute writes (e.g. vec.x = ...) do not each start an update cycle.
    After the method, restores flags and calls update() on the named attributes
    in reverse order — skipped when an update cycle is already running (the
    active cycle's dirty cone handles propagation).

    When the owner is already suppressing updates (nested under no_update /
    batch_update, or inside an active update_cycle), the body runs with no
    extra subtree walk — the outer scope already owns suppression and flush.
    
    Args:
        *attr_names: Names of attributes to include in batch update ('self' allowed)
        
    Example:
        @batch_update_attrs('vec', 'center')
        def _update_impl(self):
            self.vec.x = 10
            self.center.y = 20
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Under an outer no_update / batch (e.g. _recalculate_formula), do not
            # getattr named attrs — that would force-create cold Derivate slots.
            # Suppression already covers the ownership subtree; writes to live
            # parts inherit _in_batch_update (new slots copy it on materialize).
            if _already_suppressing_updates(self):
                return func(self, *args, **kwargs)

            # Resolve named attrs (may lazily create Derivate slots) only when
            # this decorator is the outermost suppressor.
            attrs = []
            for name in attr_names:
                if name == 'self':
                    attr = self
                else:
                    attr = getattr(self, name)
                    # Bare ScalarSlot fields are floats — batch the owner instead.
                    if not hasattr(attr, '_in_batch_update') and not hasattr(
                        attr, '_push_batch_update_subtree'
                    ):
                        attr = self
                attrs.append(attr)

            if attrs and all(getattr(a, '_in_batch_update', False) for a in attrs):
                return func(self, *args, **kwargs)

            previous_states: Dict[int, Tuple[Any, bool]] = {}
            for attr in attrs:
                if hasattr(attr, '_push_batch_update_subtree'):
                    attr._push_batch_update_subtree(previous_states)
                elif hasattr(attr, '_in_batch_update'):
                    aid = id(attr)
                    if aid not in previous_states:
                        previous_states[aid] = (attr, attr._in_batch_update)
                    attr._in_batch_update = True

            try:
                result = func(self, *args, **kwargs)
            finally:
                # Restore only the named attrs we pushed (not the whole owner
                # subtree). Push is per-attr; restore must match so large
                # ownership trees (e.g. RegularPolygon vertices) are not walked.
                for attr in attrs:
                    if hasattr(attr, '_restore_batch_update_subtree'):
                        attr._restore_batch_update_subtree(previous_states)
                    elif hasattr(attr, '_in_batch_update'):
                        hit = previous_states.get(id(attr))
                        attr._in_batch_update = hit[1] if hit else False

                # Flush only outside an active cycle; nested cycles are blocked
                # and leaf values are already written for the running pass.
                um = getattr(getattr(self, '_scena_system', None), 'update_manager', None)
                if um is None or not um.is_updating:
                    for attr in reversed(attrs):
                        # Only flush if this named attr was not already batching
                        hit = previous_states.get(id(attr))
                        if hit is not None and hit[1]:
                            continue
                        if hasattr(attr, 'update'):
                            attr.update()

            return result
                
        return wrapper
    return decorator

# Simpler decorator for the case of just 'self' (includes part subtree)
def batch_update_self():
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if _already_suppressing_updates(self):
                return func(self, *args, **kwargs)

            previous_states: Dict[int, Tuple[Any, bool]] = {}
            self._push_batch_update_subtree(previous_states)
            try:
                result = func(self, *args, **kwargs)
            finally:
                self._restore_batch_update_subtree(previous_states)

                um = getattr(getattr(self, '_scena_system', None), 'update_manager', None)
                hit = previous_states.get(id(self))
                was_self_batching = hit[1] if hit else False
                if not was_self_batching and (um is None or not um.is_updating):
                    self.update()

            return result
                
        return wrapper
    return decorator

class LinkedAttributeError(Exception):
    """Raised when attempting to modify a linked attribute directly."""
    pass


class CallableAssignError(TypeError, AttributeError, ValueError):
    """``obj.field = lambda: …`` — ``=`` copies a value; it never links.

    One error for every field kind (ink, geometry slot, pose property, ``st``
    cell). Subclasses ``TypeError`` / ``AttributeError`` / ``ValueError`` so
    code that caught the older per-site types keeps working.
    """


import functools as _functools
import types as _types

# What ``st.x = …`` refuses: a plain function or method (a ``lambda``, a
# ``def``, a bound method, a builtin, a ``partial``). ``=`` copies a value;
# ``st["x"] @= fn`` links. A class and a callable object (a key table, a
# group operator) are values (Q5 of the geometry campaign; a named ``def`` used
# to be stored).
_PLAIN_FUNCTIONS = (_types.FunctionType, _types.MethodType, _types.BuiltinFunctionType,
                    _functools.partial)


def callable_assign_message(owner: Any, field: str) -> str:
    """Shared wording for :class:`CallableAssignError`."""
    if isinstance(owner, str):
        who = owner
    else:
        who = getattr(owner, "name", None) or type(owner).__name__
    return (
        f"{who}.{field} cannot be linked by assigning a callable — `=` copies a value. "
        f"Link with {who}['{field}'] @= lambda: … (or assign the value itself)."
    )


# Revision cells bumped since the collision system last drained them (its
# moved set: ``CollisionSystem._drain_pose_cells``). A cell joins once until
# drained (its flag), so the list is bounded by the roots that moved.
DIRTY_POSE_CELLS: list = []


def _pose_cell_of(node) -> list:
    """``[revision, dirty, weakref(root), trust epoch, moves, draw seen]`` of
    ``node``'s root, cached on ``node``. The trust epoch moves only when a link, anchor or
    pull owner comes or goes (``bump_pose_trust``): trust is cached on it, so a
    move does not re-check it. ``moves`` counts the revisions that were an A1
    write of a center Point the cull marked (``_pose_mover``): a pure
    translation, which the cull box follows by a shift (Canvas Design,
    "Offscreen culling"). ``draw seen`` is ``revision - moves`` at the last
    Sprite blit, or None before the first: the blit plan is stored once it
    holds (Sprite Design, "Blit plan cache").

    Parts are never reparented (``owner`` raises), so the cell a part caches
    stays its root's; ``_invalidate_ownership_root_cache`` drops it anyway.
    """
    d = node.__dict__
    root = d.get('_ownership_root_cache')
    if root is None:
        root = node if d.get('_owner') is None else node._ownership_root()
    rd = root.__dict__
    cell = rd.get('_pose_cell')
    if cell is None:
        try:
            ref = weakref.ref(root)
        except TypeError:
            ref = None
        cell = [0, False, ref, 0, 0, None]
        rd['_pose_cell'] = cell
    d['_pose_cell'] = cell
    return cell


def pose_rev(obj) -> int:
    """``obj``'s current pose revision (0 before the first bump)."""
    cell = obj.__dict__.get('_pose_cell')
    return cell[0] if cell is not None else 0


def bump_pose_rev(node) -> None:
    """A pose input of ``node``'s tree changed: bump its root's revision.

    The revision says "something a collision pose key or a draw box reads may
    have changed since you last looked" (Collision Design, "Pose revision").
    Over-bumping is harmless (a cache recomputes); a missed bump is a stale
    hull, which ``SCENA_VERIFY_POSE_REV=1`` turns into an error.
    """
    d = getattr(node, '__dict__', None)
    if d is None:
        # A slot-only part (a Hitbox): its host's pose key reads it.
        ref = getattr(node, '_host_ref', None)
        host = ref() if callable(ref) else None
        if host is not None:
            bump_pose_rev(host)
        return
    cell = d.get('_pose_cell')
    if cell is None:
        cell = _pose_cell_of(node)
    cell[0] += 1
    if not cell[1]:
        cell[1] = True
        DIRTY_POSE_CELLS.append(cell)


def bump_pose_trust(node) -> None:
    """A link, anchor or pull owner came or went on ``node``'s tree: the
    revision moves and so does the trust epoch (trust is re-checked)."""
    d = getattr(node, '__dict__', None)
    if d is None:
        return
    cell = d.get('_pose_cell')
    if cell is None:
        cell = _pose_cell_of(node)
    cell[3] += 1
    bump_pose_rev(node)


def probe_private(obj, name: str, default=None):
    """``getattr(obj, name, default)`` for a private engine field, without
    ``Entity.__getattr__``: a miss there builds and raises an error message
    only for ``getattr`` to swallow it. Same answer for a private name: it is
    never ink, and every error that path raises is an ``AttributeError``."""
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        return default


class DestroyedError(AttributeError):
    """Read / write of an Entity after ``destroy()``.

    An ``AttributeError`` subclass so ``getattr(e, name, default)`` and
    ``hasattr`` keep working. ``@when`` / ``@on_change`` retire quietly on
    this (the watched source is gone); a plain ``AttributeError`` (typo,
    missing ink) raises.
    """


def driver_conflict_message(
    *,
    new: str,
    subject: str,
    part: str,
    existing: str,
    undo: str,
) -> str:
    """Shared wording for persistent-driver conflicts (only a formula is exclusive).

    ``subject`` is the actor that already owns the part — ``entity_label``
    (``the Sprite made at app.py:151``), never the class name alone.

    - ``new == "link"``: ``Cannot link <part> of <subject>: <existing>. <undo>.``
      where ``existing`` is a clause about the driver in place
      (``move_by(time=2, loops="forever") pushes it``).
    - any other ``new`` (``resolve()``, ``set draggable on``, ``move_to``):
      ``Cannot <new> <subject>: its <part> <existing>. <undo>.``
      (``existing`` = ``has an @= formula``).
    """
    if new == "link":
        head = f"Cannot link {part} of {subject}"
        clause = existing
    else:
        head = f"Cannot {new} {subject}"
        clause = f"its {part} {existing}"
    return f"{head}: {clause}. {undo}."


def motion_conflict_message(handle, *, subject: str, part: str) -> str:
    """``@=`` refused because a motion Handle (tween / timed pose verb) claims the part."""
    label = getattr(handle, "_claim_label", None) or (
        getattr(handle, "_claim_kind", None) or handle.kind
    )
    writes = getattr(handle, "_claim_writes", None) or "drives"
    undo = "Call handle.cancel() first"
    if getattr(handle, "_loops", 1) != -1:
        undo += ", or wait for the motion to finish"
    return driver_conflict_message(
        new="link", subject=subject, part=part,
        existing=f"{label} {writes} it", undo=undo,
    )


class DerivedAttributeError(Exception):
    """Raised when attempting to set or link a Derivate (computed) attribute directly.

    Derivate parts are outputs of their Shape's active model (recomputed by
    _update_impl); they are not valid write targets for user code. See
    Container._ensure_not_derivate().
    """
    pass

class CircularReferenceError(Exception):
    """Raised when an ``@=`` link would make a value depend on itself.

    ``a["radius"] @= lambda: b.radius`` then ``b["radius"] @= lambda: a.radius``:
    the second link closes a loop. The message names both ends.
    """
    pass


def _cycle_label(node) -> str:
    """``radius of the Circle "a"`` / ``the Circle created at game.py:12``."""
    holder = node if getattr(node, "_scena_is_entity", False) else getattr(node, "owner", None)
    name = getattr(node, "name", None)
    if holder is None or not getattr(holder, "_scena_is_entity", False):
        return repr(name) if name else type(node).__name__
    from .entity import entity_label
    label = entity_label(holder)
    if holder is node:
        return label
    field = str(name).rsplit(".", 1)[-1] if name else type(node).__name__
    return f"{field} of {label}"

def _own_size_read_message(owner, source) -> Optional[str]:
    """AC14 (a known limitation, 2026-10-10): a custom field of an object that
    reads the object's own size fields or derived points (``r["d"] @= lambda:
    r.width``, ``r.top_left``, a Polygon's ``center``). Those are computed from
    the whole object, the new field included, so the link would read itself.
    ``None`` for a real cycle (two of the object's formulas reading each other)."""
    from .entity import entity_label
    if not isinstance(owner, ScalarAnchor) or isinstance(source, ScalarAnchor):
        return None
    if getattr(source, "_link", None) is not None:
        return None
    parent = getattr(owner, "_scalar_parent", None)
    if parent is None:
        return None
    try:
        same = source._ownership_root() is parent._ownership_root()
    except Exception:
        return None
    if not same:
        return None
    name = getattr(owner, "_scalar_name", "field")
    what = entity_label(parent)
    return (
        f"{name} of {what} cannot read that object's own size or computed points "
        f"(width, radius, corners, a polygon's center, ...): those are worked out "
        f"from the whole object, and {name} is part of it. This is a known limit. "
        f"Use a property in the class instead (@property def {name}(self): "
        f"return self.width * 2), or set {name} in update(dt). Its own custom "
        f"fields and other objects can be read in a formula."
    )


class FormulaLink():
    """Base class for Direct and Formula attribute links."""

    def __init__(self, expression_fn: Callable[[], Any], always_update=False):
        if not callable(expression_fn):
            raise TypeError("Expression must be callable")

        self.owner = None
        self.expression_fn = expression_fn
        self.always_update = always_update
        # Extract Container sources from the expression (AST + closure).
        # Empty sources would install a dead link (never dirty again) — refuse.
        hops = []
        self.sources = self._extract_sources(expression_fn, hops)
        if not self.sources:
            raise TypeError(_FORMULA_NO_SOURCES_ERROR)
        if hops:
            # The chain reads through a holder (``nave.alvo.radius``,
            # ``st.alvo.radius``): what it follows past the holder is the
            # object held now, re-learned when the holder holds another one.
            # Only such a link checks its holders on evaluation (the class).
            self._hops = hops
            self._source_fn = expression_fn
            if type(self) is FormulaLink:
                self.__class__ = _HolderFormulaLink
        # Store old value for simple value comparison optimization
        self.old_value = None

    def _is_simple_value(self, value) -> bool:
        """Check if a value is a simple type that can be efficiently compared."""
        return isinstance(value, (int, float, bool, str))

    # ``(store, key, held)`` per holder the formula reads through: ``store[key]``
    # held ``held`` when the sources were learned (an ink dict and field name,
    # or a cell's ``__dict__`` and ``'_raw_value'``); ``_A_VALUE`` when it held
    # a value (a Vec2, a number, a string: the chain stops at the holder, and
    # another value changes nothing). None: no holder hop.
    _hops = None

    def evaluate(self) -> Any:
        return self.expression_fn()

    def _follow_holders(self) -> None:
        """A holder on a chain holds another object: follow that one instead.

        Runs after an evaluation (the holder notified, so the formula re-ran).
        Sources are re-learned from the formula, and the edges that changed
        are moved. A chain that no longer resolves (``nave.alvo`` is None now,
        or lacks the attribute) stops at its holder, which is still a source."""
        for store, key, held in self._hops:
            now = store.get(key, _NO_HELD)
            if now is held:
                continue
            if held is _A_VALUE and (now.__class__ is _HELD_BY_VALUE or (
                    now is not None and type(now) in _VALUE_TYPE_SET)):
                continue            # ``nave.desvio = vec_from_angle(…)``: a value again
            break
        else:
            return
        owner = self.owner
        hops = []
        try:
            new_sources = self._extract_sources(self._source_fn, hops, lenient=True,
                                                parts=self._source_parts)
        except Exception:
            # Not readable any more (a helper was rebound, a cell removed):
            # keep the sources, and stop asking until a holder moves again.
            self._hops = [(store, key, store.get(key, _NO_HELD))
                          for store, key, _ in self._hops]
            return
        self._hops = hops or None
        old_sources = self.sources
        if owner is None:
            self.sources = new_sources
            return
        ss = owner._scena_system
        dropped = [s for s in old_sources if s not in new_sources]
        added = [s for s in new_sources if s not in old_sources]
        if not dropped and not added:
            return
        kept = ContainerSet(s for s in old_sources if s in new_sources)
        for source in dropped:
            ss.remove_dependency(owner, source)
        g = ss.dependency_graph
        if getattr(owner, '_node_id', None) is None:
            ss.register_container(owner)
        for source in added:
            if not getattr(source, '_ephemeral', False):
                if getattr(source, '_node_id', None) is None:
                    ss.register_container(source)
                if g.would_create_cycle(owner._node_id, source._node_id):
                    # ``nave.alvo = r`` under ``r.radius = nave.alvo.radius * 2``:
                    # the formula would read the value it defines. It is not
                    # followed (as before re-pointing); say so once.
                    from .process import report_author_warning
                    report_author_warning(
                        "@=",
                        f"{_cycle_label(owner)}'s formula now reads "
                        f"{_cycle_label(source)}, which reads {_cycle_label(owner)}: "
                        "a formula cannot depend on the value it defines, so it does "
                        "not follow that read.",
                    )
                    continue
            ss.add_dependency(owner, source)
            source._note_became_link_source()
            kept.add(source)
        self.sources = kept
        for source in dropped:
            source._refresh_link_source_liveness()

    def evaluate_and_update(self):
        """Evaluate formula and update owner through dependency system"""
        if self.owner is None:
            return
            
        result = self.expression_fn()
        if self._hops is not None:
            self._follow_holders()
        
        # Check if value changed (for optimization)
        if not self.always_update and self._is_simple_value(result):
            if self.old_value == result:
                return  # No change

        # Containers: silent subtree write (raw hook) then one invalidate below.
        # Non-containers (e.g. EventRegistration): takein + mark dirty + flush effects.
        if hasattr(self.owner, '_no_update') and hasattr(self.owner, 'update'):
            with self.owner._no_update():
                self.owner._takein_impl(result)
                if self.owner._parts:
                    self.owner._refresh_after_raw_store()
            self.old_value = result
            self.owner.update()
            # Value already applied — clear own dirty so the next read does not
            # re-evaluate; dependents stay dirty until pulled.
            self.owner._dirty = False
            if hasattr(self.owner, '_clear_subtree_dirty'):
                self.owner._clear_subtree_dirty()
        else:
            self.owner._takein(result)
            self.old_value = result
            um = self.owner._scena_system.update_manager
            um.mark_dirty(self.owner)
            self.owner._dirty = False
            if not um.deferring:
                um.flush()

    def set_owner(self, owner):
        """Set owner and register formula dependencies in dependency system"""
        # If already has an owner, raise error
        if self.owner is not None:
            raise LinkedAttributeError("Cannot set owner of a linked attribute that already has an owner")

        # Cycle check before mutating owner / graph edges
        self.owner = owner
        try:
            self.check_circular_reference()
        except CircularReferenceError:
            self.owner = None
            raise

        # Add formula dependencies (containers are already registered during __init__)
        for source in self.sources:
            owner._scena_system.add_dependency(owner, source)
            source._note_became_link_source()

        # Initial evaluation
        self.evaluate_and_update()

    def clear(self)-> None:
        """Clear owner and clean up dependencies"""
        sources = []
        if self.owner is not None:
            # Clean up dependencies before clearing owner
            sources = list(self.sources)
            for source in sources:
                self.owner._scena_system.remove_dependency(self.owner, source)
        
        self.owner = None
        for source in sources:
            source._refresh_link_source_liveness()

    def check_circular_reference(self) -> None:
        """
        Check whether adding formula edges owner → sources would cycle.

        Uses the DependencyGraph (same structure UpdateManager walks), not a
        parallel DependencyState walk. A cycle exists iff any source can already
        reach the owner along existing dependency edges.
        """
        if not _check_circular_reference:
            return

        owner = self.owner
        if owner is None:
            return

        ss = getattr(owner, '_scena_system', None)
        if ss is None:
            return

        g = ss.dependency_graph
        # Ensure owner is registered (events / late nodes).
        if getattr(owner, '_node_id', None) is None:
            ss.register_container(owner)
        owner_id = owner._node_id
        if owner_id is None:
            return

        for source in self.sources:
            if getattr(source, '_ephemeral', False):
                continue
            if getattr(source, '_node_id', None) is None:
                ss.register_container(source)
            source_id = getattr(source, '_node_id', None)
            if source_id is None:
                continue
            if g.would_create_cycle(owner_id, source_id):
                owner_desc = _cycle_label(owner)
                source_desc = _cycle_label(source)
                own = _own_size_read_message(owner, source)
                if own is not None:
                    raise CircularReferenceError(own)
                raise CircularReferenceError(
                    f"Circular link: {owner_desc} would read {source_desc}, which already "
                    f"reads {owner_desc} (directly or through other formulas). A formula "
                    f"cannot depend on the value it defines. Link one direction only and "
                    f"set the other side with = (or in update(dt))."
                )

    @staticmethod
    def _locate_lambda_node(fn: Callable[[], Any]):
        """``ast.Lambda`` / ``ast.FunctionDef`` for ``fn`` (cached; see ``formula_check``)."""
        from .formula_check import locate_formula_node
        return locate_formula_node(fn)

    # Extract all Container objects that are referenced in a formula
    def _extract_sources(self, fn: Callable[[], Any], hops: Optional[list] = None,
                         lenient: bool = False, parts=None) -> ContainerSet:
        """
        Extract all Container instances a formula reads, from its source.

        A formula is a ``lambda`` or a named function (``def``). Its source is
        located once and cached (``formula_check.locate_formula_node``), then
        checked (``formula_check.check_formula``): shapes whose reads the
        static pass cannot see — loops, comprehensions, writes, nested
        functions, calls into code Scena cannot read, group reads — raise
        ``TypeError``. Plain helper functions from the same file are followed
        and their sources collected too. Names resolve through globals,
        closure, and default-arg captures (``lambda h=host: h.angle``).
        Handles attribute chains, calls, and simple subscripts
        (e.g. ``obj.attr``, ``items[0].radius``).

        A chain that reads through a holder (an Entity ink field or an st
        cell holding an object, ``nave.alvo.radius``) adds the holder and the
        object it holds now, and appends ``(store, key, held)`` to ``hops``
        (``FormulaLink._follow_holders`` re-learns the sources when the holder
        holds another object). ``lenient`` (that re-learning): a chain that
        does not resolve stops at its holder instead of raising, and ``parts``
        are the ones read at link (``_source_parts``): the same names, the
        same helpers, so only what the holders hold is read again.

        Raises:
            TypeError: If the formula hides a read, its source cannot be read
                and has no Container defaults, or no Container sources are found.
        """
        import inspect
        import ast
        from .formula_check import check_formula, formula_context
        from .validate import refuse_async
        if hops is None:
            hops = []

        # An async formula returns a coroutine, never a value.
        refuse_async(fn, what="@= formula")
        lambda_node = parts[0].node if parts else self._locate_lambda_node(fn)
        if lambda_node is None:
            # No source (REPL / ``exec``). Default-arg captures are sources
            # either way — ``def f(b=branch): ...`` is how wide fan-in links
            # are written. Closure / global names are only trusted for
            # lambdas; a named function without source must use defaults.
            is_lambda = getattr(fn, "__name__", None) == "<lambda>"
            defaults = (
                *(fn.__defaults__ or ()),
                *((fn.__kwdefaults__ or {}).values()),
            )
            candidates = list(defaults)
            if is_lambda:
                closure = inspect.getclosurevars(fn)
                candidates.extend(closure.nonlocals.values())
                candidates.extend(closure.globals.values())
            fallback = ContainerSet(
                v for v in candidates if isinstance(v, Container)
            )
            # An audio reader, reached directly or one attribute away from a
            # Scena object (``self.mic.level``): without the hop the object is
            # the only source and the level never notifies.
            for value in candidates:
                off_graph = _formula_source_of(value)
                if off_graph is not None:
                    fallback.add(off_graph)
                elif isinstance(value, Container):
                    for attr in fn.__code__.co_names:
                        # Only a stored value (ink): a class attribute is a
                        # property / slot whose read can materialize a part.
                        if hasattr(type(value), attr):
                            continue
                        try:
                            held = getattr(value, attr)
                        except Exception:
                            continue
                        off_graph = _formula_source_of(held)
                        if off_graph is not None:
                            fallback.add(off_graph)
            # ``lambda h=st: h.score`` — State is not a Container; the cell is.
            # Lambdas without source (REPL / exec) reach ``st`` as a global.
            names = fn.__code__.co_names
            for value in candidates:
                if not isinstance(value, State):
                    continue
                data = getattr(value, "_data", None)
                if not isinstance(data, dict):
                    continue
                for cell_name in names:
                    cell = data.get(cell_name)
                    if isinstance(cell, Container):
                        fallback.add(cell)
            if fallback:
                return fallback
            from .formula_check import source_is_stale
            stale = (" The script file changed on disk since the program started, "
                     "so its source no longer matches the running code: restart the "
                     "program." if source_is_stale(fn) else "")
            if not is_lambda:
                raise TypeError(
                    f"@= formula {getattr(fn, '__name__', fn)}(): Scena cannot read "
                    "this function's source, so it cannot learn what it depends on. "
                    "Define it in the script file, or write a `lambda:`." + stale
                )
            raise TypeError(
                f"@= formula could not be parsed for sources ({fn}); "
                "write a lambda that names a Scena value "
                "(st.x, shape.radius, mouse, clock, keyp, …)" + stale
            )

        # Refuses hidden reads; returns the formula plus the helpers it calls.
        if parts is None:
            parts = check_formula(fn, lambda_node)
        _fname = getattr(getattr(fn, "__func__", fn), "__name__", "")
        fn_label = "lambda" if _fname == "<lambda>" else f"{_fname}()"

        _UNRESOLVED = object()

        # SourceExtractor is an AST visitor that extracts Container objects from lambda functions.
        # It handles both direct variable references (e.g., 'my_var') and attribute chains (e.g., 'my_line.p1.x').
        # The visitor traverses the AST to find all references to objects that could be formula sources.
        class SourceExtractor(ast.NodeVisitor):
            def __init__(self, resolution_context):
                self.resolution_context = resolution_context
                self.sources: ContainerSet = ContainerSet()

            def _index_value(self, slice_node):
                """Resolve a simple subscript key, or ``_UNRESOLVED``."""
                if isinstance(slice_node, ast.Constant):
                    return slice_node.value
                if isinstance(slice_node, ast.UnaryOp) and isinstance(
                    slice_node.op, ast.USub
                ):
                    if isinstance(slice_node.operand, ast.Constant) and isinstance(
                        slice_node.operand.value, (int, float)
                    ):
                        return -slice_node.operand.value
                if isinstance(slice_node, ast.Name):
                    if slice_node.id in self.resolution_context:
                        return self.resolution_context[slice_node.id]
                return _UNRESOLVED

            def _unwind_chain(self, node):
                """Walk Attribute / Call / Subscript down to a Name.

                Returns ``(base_name, steps)`` where each step is
                ``('attr', name)`` or ``('sub', key)``, or ``None`` if the
                chain cannot be resolved statically.
                """
                steps = []
                curr = node
                while True:
                    if isinstance(curr, ast.Attribute):
                        steps.insert(0, ('attr', curr.attr))
                        curr = curr.value
                    elif isinstance(curr, ast.Call):
                        curr = curr.func
                    elif isinstance(curr, ast.Subscript):
                        key = self._index_value(curr.slice)
                        if key is _UNRESOLVED:
                            return None
                        steps.insert(0, ('sub', key))
                        curr = curr.value
                    else:
                        break
                if not isinstance(curr, ast.Name):
                    return None
                return curr.id, steps

            def _collect_from_chain(self, base_name, steps):
                base_obj = self.resolution_context.get(base_name)
                if base_obj is None:
                    return
                last_container = (
                    base_obj if isinstance(base_obj, Container)
                    else _formula_source_of(base_obj)
                )

                target = base_obj
                parent_container = None
                terminal_field = None
                last = len(steps) - 1
                for i, (kind, payload) in enumerate(steps):
                    if kind == 'attr':
                        if isinstance(target, State):
                            # ``st.score`` reads the value; the source is the
                            # cell (a missing one raises "has no cell …").
                            if lenient and payload not in target._data:
                                return
                            cell = target._resolve_cell(payload)
                            target = last_container = cell
                            if i == last:
                                break
                            held = cell.value
                            if (held.__class__ is _HELD_BY_VALUE
                                    or type(held) in _VALUE_TYPE_SET and held is not None):
                                # ``st.pos.x``: the Vec2 is the cell's value, not
                                # a source of its own (a new one replaces it in
                                # the cell; an in-place change tells the cell).
                                hops.append((cell.__dict__, '_raw_value', _A_VALUE))
                                break
                            # The rest of the chain (``st.alvo.radius``) reads the
                            # object held now: the cell is a source, so is what
                            # the chain reads in that object, and a new
                            # ``st.alvo`` re-points them (``_follow_holders``).
                            # A cell that holds None now (``lambda: st.alvo.r
                            # if st.alvo else 0``) stops here until it holds one.
                            hops.append((cell.__dict__, '_raw_value', held))
                            self.sources.add(cell)
                            if held is None:
                                break
                            # An audio reader held in the cell (``st.mic.level``)
                            # is written off the graph: its level is a source
                            # too, or the formula hears only a new ``st.mic``.
                            off_graph = _formula_source_of(held)
                            if off_graph is not None:
                                self.sources.add(off_graph)
                                last_container = None
                                break
                            target = held
                            last_container = held if _is_durable_source(held) else None
                            continue
                        if target is None and i > 0:
                            if lenient:
                                last_container = None
                                break
                            # ``g.mic.level`` while ``g.mic`` is None (a mic
                            # opened later): Python's "'NoneType' object has
                            # no attribute 'level'" named neither the read nor
                            # the fix. Sources are learned at link time.
                            path = base_name + "".join(
                                f".{p}" if k == 'attr' else f"[{p!r}]"
                                for k, p in steps[:i]
                            )
                            raise AttributeError(
                                f"@= formula {fn_label} reads {path}.{payload}, "
                                f"but {path} is None when the formula is linked. "
                                "A formula learns what it follows when it is "
                                f"linked: link it after {path} is set (even "
                                f"with 'if {path} else …' in the formula)."
                            )
                        if not hasattr(target, payload):
                            if lenient:
                                last_container = None
                                break
                            # A read the link cannot follow would leave it
                            # silently stale — refuse instead of warning. The
                            # object's own error (with its hints) comes first.
                            getattr(target, payload)
                            raise TypeError(
                                f"@= formula {fn_label} reads {base_name}…{payload}, "
                                f"but {type(target).__name__} has no {payload!r} "
                                "(yet). Create it before linking, or check the spelling."
                            )
                        next_target = getattr(target, payload)
                        if isinstance(target, Container) and (
                                i < last or isinstance(next_target, Container)):
                            # An ink field holding an object (``nave.desvio``,
                            # ``nave.alvo``): the field is a source, so a new
                            # value re-runs the formula. A Vec2 there is the
                            # field's value, not a source of its own: its
                            # in-place changes notify the field (``_hold_payload``),
                            # as an st cell's do. An object goes on being
                            # followed below: the one held now, re-pointed when
                            # the field holds another (``_follow_holders``).
                            anchor = _ink_field_source(target, payload)
                            if anchor is not None:
                                self.sources.add(anchor)
                                if (next_target.__class__ is _HELD_BY_VALUE
                                        or type(next_target) in _VALUE_TYPE_SET
                                        and (next_target is not None or lenient)):
                                    # A Vec2, a number, a string: the field's
                                    # value. None (re-learning only; at link
                                    # time a read through None is refused
                                    # below): stop here until it holds one.
                                    if i < last:
                                        hops.append((target._ink, payload,
                                                     None if next_target is None
                                                     else _A_VALUE))
                                    last_container = None
                                    break
                                if next_target is not None:
                                    hops.append((target._ink, payload, next_target))
                                    last_container = None
                        if i == last:
                            if isinstance(target, Container) and not isinstance(
                                next_target, Container
                            ):
                                parent_container = target
                                terminal_field = payload
                        target = next_target
                        if _is_durable_source(target):
                            last_container = target
                        else:
                            off_graph = _formula_source_of(target)
                            if off_graph is not None:
                                last_container = off_graph
                        if callable(target) and not isinstance(target, Container):
                            break
                    else:  # 'sub'
                        try:
                            target = target[payload]
                        except Exception:
                            if lenient:
                                last_container = None
                                break
                            raise TypeError(
                                f"@= formula {fn_label} reads {base_name}[…{payload!r}], "
                                "which does not exist when the formula is linked."
                            )
                        if _is_durable_source(target):
                            last_container = target

                # ``st["score"]`` / ``obj["field"]`` yields a FieldRef, not a
                # Container. Depend on that field's graph node.
                if isinstance(target, FieldRef):
                    try:
                        resolved = target.owner._linkable_source(target.name)
                    except Exception:
                        resolved = None
                    if isinstance(resolved, Container):
                        last_container = resolved

                added_scalar = False
                if parent_container is not None and terminal_field is not None:
                    try:
                        slot = parent_container._resolve_field(terminal_field)
                    except AttributeError:
                        slot = None
                    if slot is _INK_SLOT and terminal_field in getattr(
                            type(parent_container), "_scena_target_only", ()):
                        # An appearance field / flag is a link target only:
                        # the formula follows the object, as before.
                        slot = None
                    if slot is _INK_SLOT:
                        anchor = parent_container._ensure_scalar_anchor(
                            terminal_field
                        )
                        self.sources.add(anchor)
                        added_scalar = True
                if not added_scalar and last_container is not None:
                    self.sources.add(last_container)

            def visit_Attribute(self, node: ast.Attribute):
                # Full chain like ``my_line.p1.x`` or ``orbiters[0].radius``.
                # Do not ``generic_visit`` — that would also register intermediate
                # containers and double-fire updates.
                unwound = self._unwind_chain(node)
                if unwound is None:
                    # e.g. complex subscript — still harvest any Name Containers.
                    self.generic_visit(node)
                    return
                self._collect_from_chain(*unwound)

            def visit_Subscript(self, node: ast.Subscript):
                # Bare ``items[0]`` (no trailing attribute).
                unwound = self._unwind_chain(node)
                if unwound is None:
                    self.generic_visit(node)
                    return
                self._collect_from_chain(*unwound)

            def visit_Name(self, node: ast.Name):
                # Standalone variables that are not part of an attribute chain.
                # For example, if the lambda is `lambda: my_line` instead of `lambda: my_line.p1`.
                obj = self.resolution_context.get(node.id)
                if isinstance(obj, Container):
                    self.sources.add(obj)
        
        raw_sources = ContainerSet()
        for part in parts:
            # Locals (assignments, a helper's parameters) are not the globals
            # of the same name; their right-hand sides are visited anyway.
            resolution_context = {
                k: v for k, v in part.context.items() if k not in part.locals
            }
            extractor = SourceExtractor(resolution_context)
            # The body only. A default's expression runs once, when the
            # function is made; the body reads the parameter, which resolves
            # to that default through the context. Visiting the default as a
            # read made ``lambda g=g: g.ganho`` (a loop's own name) depend on
            # the whole of ``g``: a cycle when the link is g's own field, and
            # an over-broad source otherwise (AC8).
            if isinstance(part.node, ast.Lambda):
                extractor.visit(part.node.body)
            else:
                for stmt in part.node.body:
                    extractor.visit(stmt)
            for source in extractor.sources:
                raw_sources.add(source)
        
        # Post-process the sources to keep only the outermost containers.
        # This is necessary for performance. If we have dependencies on both an
        # attribute (e.g., `my_line.p1.x`) and its owner (`my_line`), a single
        # change to the attribute would trigger two updates to this FormulaLink:
        # one directly from the attribute, and another that bubbles up through the
        # owner. By listening only to the outermost container, we get a single,
        # consolidated update.
        final_sources = ContainerSet()
        for source in raw_sources:
            is_descendant = any(owner in raw_sources for owner in get_owner_chain(source))
            if not is_descendant:
                final_sources.add(source)
        if hops:
            self._source_parts = parts
        return final_sources
    
class _HolderFormulaLink(FormulaLink):
    """A formula whose chain reads through a holder (``FormulaLink._hops``).

    Its own class so that only these pay the holder check on a pull; a
    formula that reads no object through a holder evaluates as before."""

    def evaluate(self) -> Any:
        result = self.expression_fn()
        hops = self._hops
        if hops is not None:
            # Inline: the same object in every holder (most pulls) costs one
            # probe per hop; anything else is ``_follow_holders``'s to judge.
            for store, key, held in hops:
                if store.get(key, _NO_HELD) is not held:
                    self._follow_holders()
                    break
        return result


class DirectLink(FormulaLink):
    """A simplified FormulaLink for direct attribute references that bypasses AST parsing."""
    
    def __init__(self, source: 'Container', always_update=False):
        # Attribute / ScalarAnchor sinks need a payload (``.value``). Composite
        # Containers (Point, Shape, …) are taken in as-is — even when they set
        # ``_passthrough_update`` for the dirty walk.
        # Names resolve at call time; both classes are defined later in this module.
        if isinstance(source, Attribute) or isinstance(source, ScalarAnchor):
            expression_fn = lambda s=source: s.value
        else:
            expression_fn = lambda s=source: s
        
        # Don't call parent constructor - we will init by DirectLink own terms
        # Since it is a direct link, we don't need to extract sources from the expression
        self.owner = None
        self.expression_fn = expression_fn
        # Manually set the sources to be just the source attribute
        self.sources = ContainerSet([source])
        # Store old value for simple value comparison optimization
        self.old_value = None
        self.always_update = always_update
        # Note: No more observer pattern - dependencies will be managed by Container._assign_formula()
        
    @property
    def source(self) -> 'Container':
        """Get the single source of this DirectLink."""
        return next(iter(self.sources))


class DependencyState(Enum):
    """
    Derived view of where a container's value currently comes from.

    Not stored — computed from `_link` and the owner chain. Prefer asserting on
    `_link` / graph edges in new code; this enum remains for introspection and
    existing tests.
    """
    DEPENDENT_DOWNWARD = "dependent_downward"  # Driven by parts / local value
    DEPENDENT_UPWARD = "dependent_upward"      # Under a formula-driven ancestor
    LINKED_OUTWARD = "linked_outward"          # Has its own formula link

class FieldType(Enum):
    Defining = "Defining"
    Derivate = "Derivate"


_FIELD_DERIVATE = FieldType.Derivate


_LINK_RHS_ERROR = (
    "@= needs a linkable object, a field (obj['radius'], st['score']), or a "
    "callable — use '=' for a plain value (st.score reads the value; the "
    "cell is st['score'])"
)


def _normalize_link_rhs(source):
    """Turn a FieldRef into its graph node; leave Container / callable unchanged."""
    if isinstance(source, FieldRef):
        return source.owner._linkable_source(source.name)
    if source.__class__ is _HELD_BY_VALUE:
        refuse_held_payload(source, "… @= {cell}")
    return source

def _follows_cell_hint(cell) -> str:
    """`` — it shows st['score']: write st.score …`` when ``cell`` is linked
    straight to a State cell (``Text(st["score"])``), else ``""``. Error path only."""
    link = getattr(cell, "_link", None)
    if not isinstance(link, DirectLink):
        return ""
    bag_ref = getattr(link.source, "_state_bag", None)
    bag = bag_ref() if bag_ref is not None else None
    key = getattr(link.source, "attr_name", None)
    if bag is None or not key:
        return ""
    return (f". It shows {bag.name}[{key!r}] (one way): to change what it "
            f"shows, write {bag.name}.{key} = …")


def _formula_source_of(obj):
    """The graph node of a value that lives off the graph, or None.

    An audio level is written by an audio thread, never through the graph: a
    microphone, the ``audio`` bus and a sound ``Handle`` name a stand-in node
    (``_formula_source``, ``level_source.py``) that the frame dirties when the
    level moves. Asked at link time only.
    """
    hook = getattr(type(obj), "_formula_source", None)
    if hook is None:
        return None
    return hook(obj)


def _ink_field_source(obj, name: str):
    """The graph node of ink field ``name`` on ``obj`` (made on demand), or None
    when ``name`` is not an ink field. Asked at link time only."""
    try:
        slot = obj._resolve_field(name)
    except AttributeError:
        return None
    if slot is not _INK_SLOT or name in getattr(type(obj), "_scena_target_only", ()):
        return None
    ink = getattr(obj, '_ink', None)
    if not isinstance(ink, dict) or name not in ink:
        return None         # a property-backed field (``angle``) reads its own node
    return obj._ensure_scalar_anchor(name)


def _is_durable_source(obj) -> bool:
    """A Container a formula chain may depend on.

    A measured Box (``canvas.game_view``, ``graphic.box``, ``layer.view``) is
    a fresh value built on every read, off the graph until linked: depending
    on it would freeze the formula at the value it was linked with (and join
    the throwaway into the graph on every pull, D11). The source is what it
    was measured from — the Container before it in the chain (``canvas``,
    the graphic), which notifies when the measurement changes.
    """
    if not isinstance(obj, Container):
        return False
    try:
        return not obj._in_deferred_graph_tree()
    except Exception:
        return True


_FORMULA_NO_SOURCES_ERROR = (
    "@= formula has no reactive sources — name a Scena value in the lambda "
    "(st.x, shape.radius, mouse, clock, keyp, …) so the graph can update it; "
    "use '=' to copy a plain Python value once"
)


_INK_SLOT = object()  # sentinel from _resolve_field for dynamic ink names
_NO_HELD = object()   # a holder hop's field is gone (``FormulaLink._follow_holders``)
_A_VALUE = object()   # a holder hop held a value, not an object to follow


class FieldRef:
    """Bracket handle for link management: ``obj["field"] @= source``.

    Stateless except for ``(owner, name)``. Created fresh on every ``[...]``
    access; not itself a dependency-graph node.
    """

    __slots__ = ("owner", "name")

    def __init__(self, owner: Any, name: str):
        # owner is Container or State (duck-typed FieldRef protocol).
        self.owner = owner
        self.name = name

    def __imatmul__(self, source):
        hook = _ACT_LINK_HOOK
        if hook is None:
            self.owner._link_field(self.name, _normalize_link_rhs(source))
            return self
        # An act's link on a game object leaves with the act (PA1): the act
        # manager snapshots what the field had, then records the new link.
        commit = hook(self.owner, self.name)
        self.owner._link_field(self.name, _normalize_link_rhs(source))
        if commit is not None:
            commit()
        return self

    @property
    def value(self):
        return self.owner._read_field(self.name)

    @property
    def is_linked(self) -> bool:
        return self.owner._field_is_linked(self.name)

    def unlink(self) -> None:
        self.owner._unlink_field(self.name)

    def __repr__(self) -> str:
        return f"<field {self.owner!r}[{self.name!r}]>"

    # The handle is not the value. Before, a handle used as a value was silent
    # (``f"{st['score']}"`` showed the repr, ``if st["alive"]:`` was always
    # true, ``@when(lambda: st["score"] == 5)`` never fired) or raised Python's
    # bare "unsupported operand". Each use now raises with the dot spelling.
    # ``__repr__`` stays for debugging, and ``__hash__`` is the identity one.
    # Nothing here is on a hot path: the engine reads a handle with
    # ``isinstance`` and ``.value``.
    def _not_a_value(self, *_args):
        raise TypeError(field_ref_value_message(self))

    __bool__ = __str__ = __format__ = _not_a_value
    __int__ = __float__ = __index__ = __round__ = __iter__ = __len__ = _not_a_value
    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _not_a_value
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _not_a_value
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = _not_a_value
    __mod__ = __rmod__ = __pow__ = __rpow__ = _not_a_value
    __divmod__ = __rdivmod__ = __and__ = __rand__ = __or__ = __ror__ = _not_a_value
    __xor__ = __rxor__ = __lshift__ = __rlshift__ = __rshift__ = __rrshift__ = _not_a_value
    __neg__ = __pos__ = __abs__ = __invert__ = _not_a_value
    __trunc__ = __floor__ = __ceil__ = __contains__ = _not_a_value
    __hash__ = object.__hash__

    def __getitem__(self, key):
        # ``st["pos"]["x"]``: the bracket is on the value (``st.pos["x"]``).
        raise TypeError(field_ref_value_message(self, f"[{key!r}]"))

    def __getattr__(self, attr):
        # Only names the slots and the class lack reach here: ``st["pos"].x``.
        if attr.startswith("_"):
            raise AttributeError(attr)
        raise AttributeError(field_ref_value_message(self, f".{attr}"))


def field_ref_label(ref: 'FieldRef') -> Tuple[str, str]:
    """``("st['score']", "st.score")`` for a handle, in the author's words."""
    owner = ref.owner
    base = getattr(owner, "name", None)
    if not isinstance(base, str) or not base:
        base = type(owner).__name__
    if not isinstance(owner, State):
        base = base[:1].lower() + base[1:]
    name = ref.name
    dot = f"{base}.{name}" if name.isidentifier() else f"{base}[{name!r}].value"
    return f"{base}[{name!r}]", dot


def field_ref_value_message(ref: 'FieldRef', use: str = "") -> str:
    """Refusal for a bracket handle used as its value (bool, ``+``, f-string)."""
    bracket, dot = field_ref_label(ref)
    head = f"{bracket}{use}: " if use else ""
    return (
        f"{head}{bracket} is the field itself (the handle), not its value. To "
        f"read the value write {dot}{use} — inside a lambda too: the lambda "
        f"already keeps it live. {FIELD_REF_USES}"
    )


# Where a bracket handle goes, for the refusals above and in formula_check.
FIELD_REF_USES = (
    "The brackets hand the field, outside any lambda, to what follows or "
    "writes it: Slider(st[\"volume\"]), Text(st[\"score\"]), "
    "@on_change(st[\"wave\"]), tween(st[\"x\"], …), st[\"b\"] @= …, "
    "and a lone right side (c[\"r\"] @= st[\"r\"])."
)



# Private fields ``Container.__init__`` writes. A class whose ``__setattr__``
# is a Python function that passes private names straight through (closed
# surfaces, Entity, Point, Vec2: ``_scena_private_passthrough``) pays ~100 ns
# per field for the call alone; with no slot or descriptor of these names in
# its MRO (Shape slots ``_in_batch_update``) the init writes them in one
# ``__dict__`` update instead. ``graphic.box`` builds a Box per read; every
# vector arithmetic result is a new Vec2. Classes without a Python
# ``__setattr__`` keep plain writes, already the cheapest.
_CONTAINER_INIT_FIELDS = (
    "_node_id", "_ephemeral", "_scena_system", "_owner", "_parts", "_attr_name",
    "_name", "_in_batch_update", "_dirty", "_resolving", "_link", "_field_type",
    "_derivate_live", "_needs_pull_invalidate",
)


def _snake_name(class_name: str) -> str:
    """``RegularPolygon`` → ``regular_polygon`` (a variable name in a message)."""
    out = []
    for i, ch in enumerate(class_name):
        if ch.isupper() and i and not class_name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _field_key_refusal(owner: Any, key: Any) -> str:
    """Why ``owner[key]`` with a non-string key is refused.

    Brackets name a field (``ship["hp"] @= …``). A number reaches here from
    ``ship[0]`` and from Python's old iteration fallback (``x, y = ship``:
    ``iter()`` on a class with ``__getitem__`` and no ``__iter__`` calls
    ``obj[0]``), which used to read "field name must be a str, got int".
    """
    kind = type(owner).__name__
    var = _snake_name(kind)
    msg = (f"{kind}[{key!r}]: a {kind} is not a sequence; brackets take a field "
           f"name, as in {var}['hp'] @= lambda: ….")
    if getattr(type(owner), "_scena_is_graphic", False):
        msg += (f" Its position is {var}.center: x, y = {var}.center "
                f"(or read {var}.center.x / {var}.center.y).")
    return msg


def _point_index_refusal(owner: Any, key: Any) -> str:
    """``p[0]`` on a Point / Vec2 / mouse: the axes have names, not indexes."""
    kind = type(owner).__name__
    var = "mouse" if kind == "Mouse" else ("v" if hasattr(owner, "length") else "p")
    return (f"{kind}[{key!r}]: a {kind.lower() if kind == 'Mouse' else kind} has no "
            f"index. Read {var}.x / {var}.y, or unpack it: x, y = {var} (a snapshot "
            f"of the current value).")


def _join_names(names, word: str) -> str:
    """``a, b and c`` / ``a, b or c``."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {word} " + names[-1]


def _number_text(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return f"{float(value):g}"
        except OverflowError:       # 10**400: the message must not raise itself
            return "x"
    return "x"


def _derived_point_target(var: str, name: str, value: Any, part: Optional[str]):
    """The ``move_to`` arguments that put the computed point ``name`` where the
    author wrote it (``value`` a pair, or one axis when ``part`` is x / y)."""
    if part in ("x", "y"):
        shown = _number_text(value)
        if shown == "x":
            shown = part
        return (shown, f"{var}.{name}.y") if part == "x" else (f"{var}.{name}.x", shown)
    pair = None
    if isinstance(value, (tuple, list)) and len(value) == 2:
        pair = value
    elif hasattr(value, "x") and hasattr(value, "y") and not callable(value):
        try:
            pair = (float(value.x), float(value.y))
        except (TypeError, ValueError):
            pair = None
    if pair is not None:
        xs, ys = _number_text(pair[0]), _number_text(pair[1])
        if xs != "x" and ys != "x":
            return xs, ys
    return "x", "y"


def _container_dict_init(cls: type) -> bool:
    """True when ``Container.__init__`` may fill ``cls``'s fields through ``__dict__``."""
    ok = cls.__dict__.get("_scena_dict_init")
    if ok is None:
        setter = cls.__setattr__
        ok = (
            setter is not object.__setattr__
            and getattr(setter, "_scena_private_passthrough", False)
            and not any(
                hasattr(type(inspect.getattr_static(cls, n, None)), "__set__")
                for n in _CONTAINER_INIT_FIELDS
            )
            # The ownerless skip of the ``owner`` setter assumes Container's.
            and inspect.getattr_static(cls, "owner", None) is Container.__dict__["owner"]
            and cls._refresh_name is Container._refresh_name
        )
        type.__setattr__(cls, "_scena_dict_init", ok)
    return ok


class Container():
    """
    Mixin class that provides container (owner, parts, name, attr_name) functionality.
    """

    # Entity / registry citizens use ``_scena_is_entity`` so they always enter the
    # graph. Bare Vec2 / Attribute stay False and register only on first edge.
    _graph_citizen = False
    # True on ``ScalarAnchor`` (a field's graph node): its structural edge
    # follows its link (``_should_use_upward_edge``).
    _scalar_anchor = False
    # Hook run after a raw store of a Defining field (``_takein_impl``, a
    # per-field link's pull): a class whose computed fields derive from those
    # fields (Vec2 ``length`` / ``angle``) brings them in step. None: nothing to do.
    _sync_computed = None
    # Shape publishes its pose store after an ``angle`` write (None elsewhere).
    _publish_angle_input = None
    # Graph plumbing: never offered in a closed surface's "Writable on …" list.
    _closed_hidden = frozenset({"owner", "parts", "field_type"})

    def __init__(self, owner: Optional['Container'] = None, attr_name: Optional[str] = None):
        ephemeral = is_ephemeral_creation()
        global_scena_system = get_scena_system()
        if global_scena_system is None:
            raise RuntimeError(
                "No scena system is initialized. Call init_scena_system() before creating containers."
            )
        # Name: just the attribute name (e.g. p1); the full path ("line1.p1.x")
        # is built in the owner setter / _refresh_name once the owner is known.
        attr_name = attr_name or self.__class__.__name__
        fast = type(self).__dict__.get("_scena_dict_init")
        if fast is None:
            fast = _container_dict_init(type(self))
        # Internal state BEFORE the owner edge and registration.
        if fast:
            self.__dict__.update(
                _node_id=None, _ephemeral=ephemeral, _scena_system=global_scena_system,
                _owner=None, _parts=ContainerSet(), _attr_name=attr_name, _name=attr_name,
            )
        else:
            self._node_id = None  # Will be set by ScenaSystem when registered
            self._ephemeral = ephemeral
            self._scena_system = global_scena_system
            self._owner = None
            self._parts = ContainerSet()  # read through the ``parts`` property
            self._attr_name = attr_name
            self._name = attr_name

        # Set owner (this will establish owner/part relationships and refresh name).
        # Owned parts register via add_parts → add_dependency (auto-register).
        # On the dict path an ownerless object skips the setter: it would store
        # None over None and rebuild the same name (three Python __setattr__
        # calls, the bulk of a closed Vec2.temp's cost).
        if owner is not None or not fast:
            self.owner = owner

        # Register container AFTER relationships are established.
        # Ephemeral temps (arithmetic results) must not enter the graph.
        # Lazy mode: bare non-citizen Containers (Vec2, Attribute, …) stay
        # off-graph until first ownership/formula edge so discarded scratch
        # values do not leak strong refs into DependencyGraph.nodes.
        # Entity / Graphic / SpatialFx always register (collision + registry).
        if not ephemeral:
            cls = type(self)
            citizen = (
                getattr(cls, '_graph_citizen', False)
                or getattr(cls, '_scena_is_entity', False)
            )
            if (
                (not _lazy_container_registration or owner is not None or citizen)
                and not _registration_deferred.get()
            ):
                global_scena_system.register_container(self)

        # _dirty / _resolving: pull-based reactivity (invalidate on write,
        # recompute on read). _field_type: overridden by ContainerSlot for
        # Derivate parts. _derivate_live: explicit liveness for Derivate roots
        # (cold Derivates are skipped in _update_impl until live).
        # _needs_pull_invalidate: sticky; once any @= / @when / live Derivate
        # consumes this ownership tree, Defining writes must mark_dirty. Stays
        # False for pure pose animation (A2 — pay invalidate only when pull
        # consumers exist).
        if fast:
            self.__dict__.update(
                _in_batch_update=False, _dirty=False, _resolving=False, _link=None,
                _field_type=FieldType.Defining, _derivate_live=False,
                _needs_pull_invalidate=False,
            )
        else:
            self._in_batch_update = False
            self._dirty = False
            self._resolving = False
            self._link = None
            self._field_type = FieldType.Defining
            self._derivate_live = False
            self._needs_pull_invalidate = False

    @property
    def parts(self) -> "ContainerSet":
        """The parts this object owns (``circle.center``, ``line.p1``). Read-only."""
        return self._parts

    @parts.setter
    def parts(self, value) -> None:
        # A rebind (``e.parts = 1.0``) orphaned the real parts and left
        # destroy() unable to walk them. Engine code writes ``_parts``.
        raise TypeError(
            f"{type(self).__name__}.parts is read-only: an object "
            "makes its own parts (circle.center, line.p1). Keep your "
            "own list under another name (self.pieces = [...])."
        )

    @property
    def field_type(self) -> "FieldType":
        """``Defining`` or ``Derivate``: how this part relates to its owner. Read-only."""
        return self._field_type

    @field_type.setter
    def field_type(self, value) -> None:
        # ``ship.field_type = 3`` silently corrupted the part's graph edges.
        # Engine code writes ``_field_type``.
        raise AttributeError(
            f"{type(self).__name__}.field_type is read-only: an engine field "
            "(Defining / Derivate) set when the part is made."
        )

    def _ownership_root(self) -> "Container":
        """Topmost owner in the part tree (Shape / free Point / …).

        Cached: ownership is assigned once at materialize and never reparented
        (``owner`` setter raises if already set). Cleared when owner changes.
        """
        cached = self.__dict__.get('_ownership_root_cache')
        if cached is not None:
            return cached
        root = self
        while root._owner is not None:
            root = root._owner
        self.__dict__['_ownership_root_cache'] = root
        return root

    def _in_deferred_graph_tree(self) -> bool:
        """True while this part tree stays off the dependency graph.

        A measured Box (``Box._snapshot``: ``graphic.box``, layout children,
        grid cells) is a throwaway an author mostly reads. Its Point parts
        would each register a node and a structural edge, and the tree is a
        reference cycle (owner ↔ parts), so those nodes lived until the
        cyclic GC — per-frame ``graphic.box.top_left`` looked like a leak.
        Until something links into it, the tree is off-graph: reads pull
        through ownership, writes recompute eagerly (``update``). The first
        registration of any node in it wires the whole tree
        (``_join_dependency_graph``).
        """
        return self._ownership_root().__dict__.get('_graph_deferred', False)

    def _join_dependency_graph(self) -> None:
        """Wire this deferred tree root and its parts into the graph (once)."""
        if not self.__dict__.pop('_graph_deferred', False):
            return
        self._scena_system.register_container(self)
        self._wire_structural_tree()

    def _wire_structural_tree(self, upward: Optional[bool] = None) -> None:
        """Structural edges as eager materialize would have set them.

        Same choice as ``_add_parts`` per part; under a Derivate part the
        edges are forced upward (``ContainerSlot.__get__`` does that before
        it sets the owner).
        """
        for part in self._parts:
            use_upward = upward if upward is not None else self._should_use_upward_edge(part)
            self._set_structural_edge(part, use_upward)
            below = True if (
                upward or part.__dict__.get('_field_type') == FieldType.Derivate
            ) else None
            part._wire_structural_tree(below)

    def _flag_pull_consumers(self) -> None:
        """Mark ownership root so subsequent Defining writes invalidate."""
        self._ownership_root()._needs_pull_invalidate = True

    def _requires_pull_invalidate(self) -> bool:
        """True if a write here may affect @= / @when / live Derivates."""
        return bool(getattr(self._ownership_root(), "_needs_pull_invalidate", False))

    def _invalidate_bare_reads(self) -> None:
        """Drop cached ``_bare_ok`` on this ownership subtree (after link changes)."""
        for node in self._iter_subtree():
            node.__dict__.pop('_bare_ok', None)
            node.__dict__.pop('_scalar_bare_ok', None)
        bump_pose_trust(self)   # a link came or went: trust is re-checked

    def _invalidate_ownership_root_cache(self) -> None:
        """Clear memoized ownership roots on this subtree (owner graph changed)."""
        for node in self._iter_subtree():
            node.__dict__.pop('_ownership_root_cache', None)
            node.__dict__.pop('_pose_cell', None)

    def _formula_driven_ancestor(self) -> Optional['Container']:
        """Nearest owner (not self) that has a formula link, or None."""
        current = self._owner
        while current is not None:
            if current._link is not None:
                return current
            current = current._owner
        return None

    def _formula_driven_descendant(self) -> Optional['Container']:
        """First descendant (not self) that has a formula link, or None."""
        for part in self._parts:
            if part._link is not None:
                return part
            found = part._formula_driven_descendant()
            if found is not None:
                return found
        return None

    @property
    def _dependency_state(self) -> DependencyState:
        """Derived linked-mode view (see DependencyState). Not a stored cache."""
        if self._link is not None:
            return DependencyState.LINKED_OUTWARD
        if self._formula_driven_ancestor() is not None:
            return DependencyState.DEPENDENT_UPWARD
        return DependencyState.DEPENDENT_DOWNWARD

    def _derivate_source(self) -> Optional['Container']:
        """Nearest node (self or an owner) whose field_type is Derivate, or None.

        FieldType is only ever set explicitly on the top of a Derivate subtree
        (e.g. a Rect's `top_right` Point) — nested leaves (`top_right.x`) keep
        the Container default of Defining. Walking the owner chain finds the
        Derivate root either way, so `rect.top_right.x` is caught too.

        Uses ``__dict__.get`` so Attribute.__getattr__ is not triggered when
        ``field_type`` is not yet assigned (owner set mid-``__init__``).
        """
        node = self
        while node is not None:
            ft = node.__dict__.get('_field_type', FieldType.Defining)
            if ft == FieldType.Derivate:
                return node
            node = node._owner
        return None

    def _should_use_upward_edge(self, owned: 'Container') -> bool:
        """Whether structural edge should be owned -> self (part depends on owner)."""
        if (owned.__class__._scalar_anchor and owned.__dict__.get('_derivate_field')
                and owned.__dict__.get('_link') is None):
            # A source-only anchor on a Derivate scalar (``k["r"] @= line["length"]``)
            # is computed from its owner: it depends on it, so any change of
            # the owner dirties it and its readers (it froze: review
            # 2026-10-09 S5-2). An anchor on a Defining field keeps the
            # downward edge (a part's formula may read its owner's Defining
            # field: PARALLEL_DIST p1 reads dist); its writers notify it
            # (``_notify_source_anchors``).
            return True
        owned_ft = owned.__dict__.get('_field_type', FieldType.Defining)
        if owned_ft == FieldType.Derivate:
            return True
        self_ft = self.__dict__.get('_field_type', FieldType.Defining)
        if self_ft == FieldType.Derivate:
            return True
        # Formula-driven node or anything under one: value flows down the tree.
        if self._link is not None or self._formula_driven_ancestor() is not None:
            return True
        return False

    def _ensure_no_competing_formula(self) -> None:
        """
        At most one formula driver on an ownership ancestor↔descendant chain.
        Call before installing a new link on self (self's own link may be replaced).
        """
        ancestor = self._formula_driven_ancestor()
        if ancestor is not None:
            raise LinkedAttributeError(
                f"Cannot link {self.name}: ancestor {ancestor.name} already has a formula"
            )
        descendant = self._formula_driven_descendant()
        if descendant is not None:
            raise LinkedAttributeError(
                f"Cannot link {self.name}: descendant {descendant.name} already has a formula "
                f"(call unlink_all() first)"
            )

    def _has_external_dependents(self) -> bool:
        """True if any graph dependent lies outside this ownership subtree.

        Used for Derivate liveness (external @= / formula links). Structural
        children (e.g. Point.x) do not count.
        """
        if self._node_id is None or self._scena_system is None:
            return False
        g = self._scena_system.dependency_graph
        subtree_ids = {
            n._node_id for n in self._iter_subtree()
            if getattr(n, '_node_id', None) is not None
        }
        if not subtree_ids:
            return False
        for nid in subtree_ids:
            for dep_id in g.dependents.get(nid, ()):
                if dep_id not in subtree_ids:
                    return True
        return False

    def _is_derivate_live(self) -> bool:
        """Whether this Derivate root should be refreshed by the owner's _update_impl."""
        if getattr(self, '_derivate_live', False):
            return True
        return self._has_external_dependents()

    def _note_became_link_source(self) -> None:
        """Called when a formula/DirectLink begins depending on this container."""
        # Read by writers that skip the graph for speed (Text layout, pose
        # floats): a link reads this node, so they must notify (D25).
        self.__dict__['_link_source'] = True
        owner = self.__dict__.get('_owner')
        hook = getattr(owner, '_part_became_link_source', None) if owner is not None else None
        if hook is not None:
            hook(self)
        self._flag_pull_consumers()
        root = self._derivate_source() or self
        was_live = root._derivate_live
        root._derivate_live = True
        # First time a cold Derivate becomes a link source: materialize now so
        # the link's initial evaluate sees fresh geometry.
        if not was_live and root._owner is not None:
            materialize = getattr(root._owner, '_materialize_derivate_part', None)
            if materialize is not None:
                materialize(root._attr_name)

    def _refresh_link_source_liveness(self) -> None:
        """Recompute _derivate_live after a consumer unlinks."""
        root = self._derivate_source() or self
        root._derivate_live = root._has_external_dependents()
        if '_link_source' in self.__dict__ and not self._has_external_dependents():
            del self.__dict__['_link_source']

    def _ensure_not_derivate(self, operation: str, value: Any = None) -> None:
        """Guard against external writes to a Derivate (computed) attribute.

        Derivate parts are outputs of their Shape's model, recomputed by
        `_update_impl`; only the shape itself may write them. Internal
        recomputation always runs under `no_update()` / `batch_update()` /
        `batch_update_self()` / `batch_update_attrs()`, which set
        `_in_batch_update` on the whole part subtree — so this check is
        skipped for those writes and only rejects ordinary, unbatched calls
        (i.e. user code reaching in directly). Note: manually wrapping an
        external write in `shape._batch_update()` would also bypass this —
        an accepted, narrow gap given how rare that combination is.
        """
        if self._in_batch_update:
            return
        source = self._derivate_source()
        if source is None:
            return
        op = "link" if operation == "link" else "set"
        raise DerivedAttributeError(self._derived_refusal(source, op, value))

    def _clear_structural_edge(self, owned: 'Container') -> None:
        """Remove either direction of the structural owner/part edge."""
        self._scena_system.remove_dependency(self, owned)
        self._scena_system.remove_dependency(owned, self)

    def _set_structural_edge(self, owned: 'Container', upward: bool) -> None:
        """Set structural edge between self and owned (clears any existing first)."""
        if self._in_deferred_graph_tree():
            return  # wired as a whole by _join_dependency_graph
        self._clear_structural_edge(owned)
        if upward:
            # owned depends on self (owner updates first, then part / its dependents)
            self._scena_system.add_dependency(owned, self)
        else:
            # self depends on owned (part updates first, then owner)
            self._scena_system.add_dependency(self, owned)

    def _rewire_subtree_structural_edges(self, upward: Optional[bool] = None) -> None:
        """
        Rewire structural edges for this container's part tree.

        If upward is True/False, force that direction for every edge.
        If upward is None, choose per-part from field_type / dependency state.
        """
        for part in self._parts:
            use_upward = upward if upward is not None else self._should_use_upward_edge(part)
            self._set_structural_edge(part, use_upward)
            # Descendants: if we forced upward (link), keep forcing; else decide locally
            part._rewire_subtree_structural_edges(upward=upward)

    def _add_parts(self, owned: 'Container') -> None:
        """Add an owned object to this shape and establish dependency."""
        self._bust_subtree_cache()
        self._parts.add(owned)

        # Ephemeral trees are value carriers only — no graph edges.
        if getattr(self, '_ephemeral', False) or getattr(owned, '_ephemeral', False):
            return

        # Defining parts: owner depends on part (downward).
        # Derived parts / upward-linked subtrees: part depends on owner (upward).
        self._set_structural_edge(owned, upward=self._should_use_upward_edge(owned))

    def _remove_parts(self, owned: 'Container') -> None:
        """Remove an owned object from this shape and clean up dependency."""
        self._bust_subtree_cache()
        self._parts.discard(owned)
        if getattr(self, '_ephemeral', False) or getattr(owned, '_ephemeral', False):
            return
        self._clear_structural_edge(owned)

    @property
    def name(self) -> str:
        """Get the shape's name."""
        return self._name

    @property
    def attr_name(self) -> Optional[str]:
        """Get the attribute name of this shape."""
        return self._attr_name

    @property
    def owner(self) -> Optional['Container']:
        """Get the owner of this attribute."""
        return self._owner

    @owner.setter
    def owner(self, owner: Optional['Container']) -> None:
        """Set the owner of this attribute and manage part registration.
        
        Args:
            owner: The Container instance that owns this attribute, or None to clear ownership
        """
        # Validate before any mutation: a refused write must leave the object
        # untouched (a junk owner stored before ``_add_parts`` failed made the
        # object read as a part, so ``destroy()`` refused it forever).
        if owner is not None and not isinstance(owner, Container):
            raise TypeError(
                f"{type(self).__name__}.owner takes a Scena object or None, "
                f"not {type(owner).__name__}. Parts get their owner when it "
                "makes them (circle.center, line.p1); a top-level object has none."
            )

        # If we already have an owner, remove ourselves as a part first
        # This will automatically remove the dependency relationship

        if self._owner is not None and owner is not None:
            raise RuntimeError(f"Cannot set owner of {self.name} that already has an owner {self._owner.name}")

        if self._owner is not None and self._owner is owner:
            return

        if self._owner is not None:
            self._owner._remove_parts(self)
            
        # Set the new owner
        self._owner = owner
        
        # If we have a new owner, add ourselves as a part
        # This will automatically add the dependency relationship
        if owner is not None:
            owner._add_parts(self)

        # Ownership root may have changed for this whole subtree.
        self._invalidate_ownership_root_cache()

        # Rebuild informative full path (e.g. "line1.p1.x"), including parts
        # that may have been created before this owner was assigned.
        self._refresh_name()

    def _refresh_name(self) -> None:
        """Rebuild self._name from the owner chain and propagate to parts."""
        if self._owner is not None:
            self._name = self._owner.name + "." + self._attr_name
        else:
            self._name = self._attr_name
        for part in self._parts:
            part._refresh_name()

    def _bust_subtree_cache(self) -> None:
        """Drop flattened-subtree caches on this node and every owner above.

        Tier 1.3: ``_iter_subtree`` memoizes a flat list; part graph changes
        (``add_parts`` / ``remove_parts``, including lazy Derivate materialize)
        must invalidate ancestors that may have cached this node.
        """
        node: Optional[Container] = self
        while node is not None:
            node.__dict__.pop('_subtree_cache', None)
            node = node._owner

    def _subtree_list(self) -> List['Container']:
        """Flattened ownership subtree (self first). Cached until parts change."""
        cached = self.__dict__.get('_subtree_cache')
        if cached is not None:
            return cached
        out: List[Container] = [self]
        for part in self._parts:
            out.extend(part._subtree_list())
        self.__dict__['_subtree_cache'] = out
        return out

    def _iter_subtree(self):
        """Yield self then every descendant part (depth-first).

        Tier 1.3: uses a cached flat list (``_subtree_list``), busted on
        ``add_parts`` / ``remove_parts``.
        """
        return iter(self._subtree_list())

    def _push_batch_update_subtree(self, previous_states: Dict[int, Tuple[Any, bool]]) -> None:
        """
        Set _in_batch_update=True on this container and all parts.
        Records prior flags in previous_states (first write wins for overlaps).
        Keys are ``id(node)`` so unhashable Attributes/Vec2s work as batch targets.
        """
        for node in self._iter_subtree():
            nid = id(node)
            if nid not in previous_states:
                previous_states[nid] = (node, node._in_batch_update)
            node._in_batch_update = True

    def _restore_batch_update_subtree(self, previous_states: Dict[int, Tuple[Any, bool]]) -> None:
        """Restore flags recorded by _push_batch_update_subtree.

        Nodes created during the batch (lazy ContainerSlots) are not in
        previous_states but may have inherited _in_batch_update=True — clear
        them to match this container's restored flag so they do not stay
        stuck suppressing update() forever.
        """
        for node, was_batching in previous_states.values():
            node._in_batch_update = was_batching
        owner_flag = self._in_batch_update
        for node in self._iter_subtree():
            if id(node) not in previous_states:
                node._in_batch_update = owner_flag

    def _local_refresh_root(self) -> Optional['Container']:
        """Nearest ancestor (incl. self) with a structural ``_update_impl``.

        Skips pass-through leaves (Attribute / Point) and formula-driven
        containers — those resolve via ``_resolve_link`` instead.
        """
        node: Optional[Container] = self
        while node is not None:
            if (
                node._link is None
                and not getattr(type(node), '_passthrough_update', False)
            ):
                return node
            node = node._owner
        return None

    def _ensure_fresh(self) -> None:
        """Pull-resolve this node (and ancestors) if dirty before a read.

        Unlinked Defining leaves cache ``_bare_ok`` (A3) so repeated
        ``.value`` / ``float(attr)`` reads skip owner-chain walks. The same
        flag is shared with ``_bare_attr`` / ``get_xy(bare=True)`` and is
        cleared by ``_invalidate_bare_reads`` on link changes.
        """
        if self._link is not None:
            self._resolve_link()
            return

        flag = self.__dict__.get('_bare_ok')
        if flag is True:
            return

        if flag is not False:
            # First touch: classify once. True → bare leaf (no further work).
            # False → formula ancestor or Derivate lineage; fall through.
            if (
                self._formula_driven_ancestor() is None
                and self._derivate_source() is None
                and '_pull_owner' not in self.__dict__
            ):
                self.__dict__['_bare_ok'] = True
                return
            self.__dict__['_bare_ok'] = False

        ancestor = self._formula_driven_ancestor()
        if ancestor is not None:
            ancestor._resolve_link()
            return
        # Prefer __dict__ — Attribute.__getattr__ must not run for field_type
        # during init (owner set before field_type is assigned).
        ft = self.__dict__.get('_field_type', FieldType.Defining)
        if ft == FieldType.Derivate or self._derivate_source() is not None:
            root = self._local_refresh_root()
            if root is not None and root._dirty:
                root._resolve_structural()
            elif root is self and self._owner is not None and self._owner._dirty \
                    and '_heading_anchor' in self._owner.__dict__:
                # A Derivate with its own structure (a Line's ``vec``) is clean
                # while its owner still has a linked heading to pull (D18).
                self._owner._resolve_structural()
        elif '_pull_owner' in self.__dict__:
            self._pull_owner_first()

    def _resolve_link(self) -> None:
        """Recompute a formula / DirectLink target on read (pull, memoized).

        Tier 1.4: leaf sinks (empty ``parts`` — Point / Attribute / ScalarAnchor)
        skip the ``no_update()`` contextmanager and the trailing subtree dirty
        clear; save/restore ``_in_batch_update`` on self only.

        Stores via ``_takein_impl`` (the raw hook), never the ``_takein``
        dispatcher: a pull must not invalidate. The write that made this node
        dirty already walked its cone; the dispatcher (``Point._takein`` →
        ``update()`` / nested ``mark_dirty``) re-walks it on every read —
        O(cone) per pull, ~2× sierpinski draw (Reactive Design, "Pull stores
        raw").
        """
        if not self._dirty or self._resolving:
            return
        if self._link is None:
            self._dirty = False
            return
        self._resolving = True
        try:
            result = self._link.evaluate()
            if not self._parts:
                # Leaf fast path — no ownership children to suppress or clear.
                d = self.__dict__
                # Attribute, not ``d[...]``: a Shape keeps this flag in a slot
                # that a dict write never reaches (review 2026-10-09 S5-4).
                was = getattr(self, '_in_batch_update', False)
                object.__setattr__(self, '_in_batch_update', True)
                try:
                    self._takein_impl(result)
                    if self._link is not None:
                        self._link.old_value = result
                finally:
                    object.__setattr__(self, '_in_batch_update', was)
            else:
                with self._no_update():
                    self._takein_impl(result)
                    self._takein_pose(result)       # a whole link carries the pose (C7)
                    self._refresh_after_raw_store()
            if self._link is not None:
                self._link.old_value = result
        except Exception:
            # Leave ``_dirty`` set so the next read retries. Clearing it here
            # froze the last good value after a transient formula error.
            raise
        else:
            self._dirty = False
            # takein refreshed this ownership subtree; clear stale bits so a
            # later write can re-invalidate correctly.
            if self._parts:
                self._clear_subtree_dirty()
        finally:
            self._resolving = False

    def _resolve_structural(self) -> None:
        """Run ``_update_impl`` for a Shape/Vec2/… when its Derivate is read."""
        if not self._dirty or self._resolving:
            return
        # A Derivate part with its own structure (a shape's Derivate ``vec``:
        # Vec2 derives length / angle) is written by its owner. Bring the
        # owner up to date first, or the read sees the x / y of the last
        # owner update (the stale-vec bug, G5 in Testing Design).
        if self.__dict__.get('_field_type') == FieldType.Derivate and self._owner is not None:
            owner_root = self._owner._local_refresh_root()
            if owner_root is not None and owner_root._dirty:
                owner_root._resolve_structural()
        self._resolving = True
        try:
            with self._no_update():
                self._update_impl()
        except Exception:
            raise
        else:
            self._clear_subtree_dirty()
        finally:
            self._resolving = False

    def _refresh_after_raw_store(self) -> None:
        """After a whole-object pull stored the Defining parts raw (inside
        ``_no_update``), run this node's own ``_update_impl`` so the Derivates
        already live (``rect.top_right`` read before) follow; the caller then
        marks the subtree clean, so skipping this left them stale (D19 in
        Testing Design). Only nodes with parts reach here: a whole-shape link,
        never the leaf sinks (Point / Vec2 / ScalarAnchor)."""
        if type(self)._update_impl is not Container._update_impl:
            self._update_impl()

    def _clear_subtree_dirty(self) -> None:
        """Mark this node and its parts clean after a refresh of the subtree.

        A part with its own link (a ``ScalarAnchor`` of ``ship["hp"] @= …``, a
        part linked on its own) stays dirty: it pulls its link only when
        dirty, and the refresh did not necessarily read it. Clearing it froze
        the old value until the next source change (``r.width`` read before
        ``r.hp`` returned the old hp; Testing Design D13).
        """
        for node in self._iter_subtree():
            if node is self or node._link is None:
                node._dirty = False

    def _pull_owner_first(self) -> None:
        """A Defining part that a linked verb rewrites (``_pull_owner`` is set by
        the shape that owns the link, e.g. a Line's linked ``angle`` -> ``p1`` /
        ``p2``): bring that owner up to date first, or this read sees the points
        from before the source moved (D18 in Testing Design)."""
        owner = self.__dict__.get('_pull_owner')
        if owner is not None and owner._dirty and not owner._in_batch_update:
            owner._resolve_structural()

    def _recalculate_formula(self) -> bool:
        """Pull-resolve if dirty. Kept for effects / ephemeral / tests.

        Returns True if this node was dirty (and thus may have changed).
        """
        was_dirty = self._dirty
        if self._link is not None:
            self._resolve_link()
            return was_dirty
        if getattr(type(self), '_passthrough_update', False):
            self._dirty = False
            return was_dirty
        root = self._local_refresh_root()
        if root is not None:
            root_was = root._dirty
            root._resolve_structural()
            return root_was
        self._dirty = False
        return was_dirty

    def _clear_owner(self) -> None:
        self.owner = None  # just use the property setter logic

    def _external_formula_dependents(self) -> List['Container']:
        """Linked nodes OUTSIDE this subtree whose formula reads a node inside it."""
        ss = self._scena_system
        if ss is None or getattr(self, '_ephemeral', False):
            return []
        subtree_ids = {
            n._node_id for n in self._iter_subtree()
            if getattr(n, '_node_id', None) is not None
        }
        if not subtree_ids:
            return []
        g = ss.dependency_graph
        out = []
        seen = set()
        for nid in subtree_ids:
            for dep_id in g.get_dependents(nid):
                if dep_id in subtree_ids or dep_id in seen:
                    continue
                seen.add(dep_id)
                dep = g.nodes.get(dep_id)
                link = getattr(dep, '_link', None) if dep is not None else None
                if link is not None and any(
                    getattr(src, '_node_id', None) in subtree_ids for src in link.sources
                ):
                    out.append(dep)
        return out

    def _pull_external_dependents(self) -> None:
        """Bring outside dependents up to date while this subtree is still readable.

        ``destroy()`` calls this before the Entity is marked dead: the later
        auto-unlink keeps each dependent's value, and that value must reflect
        the source's final state, not the last time someone read it (D8).
        """
        for dep in self._external_formula_dependents():
            dep._resolve_link()

    def _clean_up(self) -> None:
        """
        Remove this container and its part subtree from the reactive system.

        - Unlinks external dependents whose formulas reference this subtree
        - Recursively cleans parts (unlink, detach owner, unregister)
        - Unlinks self, detaches from owner (structural edges), unregisters node
        """
        if getattr(self, '_ephemeral', False):
            # Temps were never registered; still clear ownership if any.
            if self._owner is not None:
                self._clear_owner()
            return

        ss = self._scena_system
        subtree = list(self._iter_subtree())
        subtree_ids = {
            n._node_id for n in subtree
            if getattr(n, '_node_id', None) is not None
        }

        # Auto-unlink outsiders that formula-depend on nodes we are about to remove.
        if ss is not None and subtree_ids:
            g = ss.dependency_graph
            external_ids = set()
            for nid in subtree_ids:
                for dep_id in g.get_dependents(nid):
                    if dep_id not in subtree_ids:
                        external_ids.add(dep_id)
            for dep_id in external_ids:
                dep = g.nodes.get(dep_id)
                if dep is None:
                    continue
                link = getattr(dep, '_link', None)
                if link is None:
                    continue
                if any(getattr(src, '_node_id', None) in subtree_ids for src in link.sources):
                    hook = _UNLINK_NOTICE_HOOK
                    # A field of the dying object itself (its own ``hp`` or
                    # ``grounded`` reading its pose) goes with its owner:
                    # unlinked quietly, not a lost link (AC11).
                    # (A part's clean-up runs inside its host's: the host is
                    # already dead then, and its fields read the part.)
                    parent = dep._scalar_parent if isinstance(dep, ScalarAnchor) else None
                    own = parent is not None and (
                        getattr(parent, '_node_id', None) in subtree_ids
                        or getattr(parent, 'is_alive', True) is False)
                    if not own and (hook is None or not hook(dep, self)):
                        warnings.warn(
                            f"Attribute {dep.name} was unlinked because a formula source was removed",
                            RuntimeWarning,
                        )
                    dep.unlink()
                    if isinstance(dep, ScalarAnchor):
                        parent = dep._scalar_parent
                        if parent is not None:
                            parent._drop_scalar_anchor(dep._scalar_name)

        # Clean parts first (copy: clear_owner mutates self._parts).
        # destroy() detaches owner before the next snapshot. Stamp Entity parts
        # with the dead host so History.snapshot(part) can still name it.
        from .entity import Entity as _Entity
        host_dead = isinstance(self, _Entity) and not self.is_alive
        for part in list(self._parts):
            if host_dead and isinstance(part, _Entity):
                object.__setattr__(part, "_destroyed_with_host", self)
            part._clean_up()

        self.__dict__.pop('_field_anchors', None)

        if self._link is not None:
            self.unlink()

        if self._owner is not None:
            self._clear_owner()

        if ss is not None and self._node_id is not None:
            ss.unregister_container(self)
            self._node_id = None

    def update(self) -> None:
        """
        Invalidate this node and dependents after an external mutation.

        Pure derived data is recomputed on read (pull). Effects (``@when`` /
        ``@on_change``) are collected and run on ``flush()`` — immediately
        when not frame-batching, once before draw inside ``run()``.

        When the ownership tree has no pull consumers (no ``@=`` / ``@when`` /
        live Derivates), skip ``mark_dirty`` — Defining values are already
        stored synchronously and draw reads them directly (A2).
        """
        if self._in_batch_update:
            return

        # Ephemeral containers are not in the graph; resolve locally if needed.
        if getattr(self, '_ephemeral', False) or self._node_id is None:
            if self._link is not None:
                self._dirty = True
                self._resolve_link()
            else:
                # A destroyed Sprite used to land here on a write and raise
                # NotImplementedError (no ``_update_impl``). Derived reads
                # (Line.center) still need ``_update_impl``. An error already
                # in flight (batch_update's finally) must not be masked.
                dead = _dead_self_or_owner(self)
                if dead is not None:
                    import sys
                    if sys.exc_info()[0] is not None:
                        return
                try:
                    with self._no_update():
                        self._update_impl()
                except NotImplementedError:
                    if dead is not None:
                        from .entity import _refuse_if_destroyed
                        _refuse_if_destroyed(dead, "update")
                    raise
            # A deferred tree has no structural edge to carry a part's write
            # up to its owner (a measured Box's ``center``): recompute the
            # owner here, as the graph walk + pull would have.
            owner = self._owner
            if owner is not None and self._in_deferred_graph_tree():
                owner.update()
            return

        if not self._requires_pull_invalidate():
            return

        self._scena_system.update_manager.mark_dirty(self)

    @batch_update_self()
    def _takein(self, new_value):
        """
        Take in a new value.
        This method is called when a new value is assigned to the attribute.
        It is implemented by subclasses.
        """
        if new_value is self:
            return

        self._takein_impl(new_value)   # Call _takein method of the subclass (specific implementation by subclass)
        self._takein_pose(new_value)
        bump_pose_rev(self)
        # A copy (``<<``, ``absorb``, part ``=``) stores fields raw: dirty the
        # field anchors a FieldRef link reads, on this node and its parts.
        for node in self._iter_subtree():
            if node.__dict__.get('_field_anchors'):
                _notify_source_anchors(node)
        # self.update() will be called automatically at the end by @batch_update_self

    def _taketo(self, other: 'Container') -> None:
        # Just takein in reverse
        other._takein(self)

    @abstractmethod
    def _takein_impl(self, new_value):
        """
        Abstract method for implementing the takein method.
        Should be implemented by subclasses to handle taking in values.
        """
        raise NotImplementedError("Subclasses must implement takein")
    
    def _author_unlink_hint(self) -> str:
        """Bracket unlink spelling for LinkedAttributeError messages."""
        if self._owner is not None and self.attr_name:
            return f"{self._owner.name}['{self.attr_name}'].unlink()"
        bag_ref = getattr(self, '_state_bag', None)
        if bag_ref is not None:
            bag = bag_ref()
            if bag is not None and self.attr_name:
                return f"{bag.name}['{self.attr_name}'].unlink()"
        return "unlink()"

    def _linked_write_blocker(self) -> Optional['Container']:
        """The formula node an author write on self would clobber, or None.

        Covers this node, a formula-driven ancestor, or a linked descendant
        (including ScalarAnchor leaves). ``takein`` does not call this — only
        author doors (``=`` / ``<<`` / ``absorb``).
        """
        if self._link is not None:
            return self
        ancestor = self._formula_driven_ancestor()
        if ancestor is not None:
            return ancestor
        return self._formula_driven_descendant()

    def _refuse_author_write(self) -> None:
        """Raise if ``=`` / ``<<`` / ``absorb`` would override a live formula."""
        blocker = self._linked_write_blocker()
        if blocker is None:
            return
        hint = blocker._author_unlink_hint()
        raise LinkedAttributeError(
            f"{blocker.name} is linked — call {hint} first"
            + _follows_cell_hint(blocker)
        )

    def _assign_value(self, new_value):
        """Set the attribute's value or establish a link."""
        # Check if object is being assigned to itself
        # When operator @= is used, after __imatmul__ is called, the object is assigned to itself (and we don't want that)
        # So we must ignore this case
        if new_value is self:
            return

        # Handle lambda functions
        if callable(new_value) and getattr(new_value, "__name__", None) == '<lambda>':
            parent = getattr(self, "owner", None)
            field = getattr(self, "attr_name", None) or self.name
            raise CallableAssignError(
                callable_assign_message(parent if parent is not None else "value", field)
            )

        self._ensure_not_derivate("set", new_value)
        self._refuse_author_write()

        # Take in the new value
        self._takein(new_value)

    def _assign_formula(self, formula: Union['Container', Callable[[], Any], Number]):
        """Set a formula for this attribute."""
        self._ensure_not_derivate("link")
        formula = _normalize_link_rhs(formula)
        # Create a link object holding the lambda expression
        make_link = getattr(type(formula), '_scena_make_link', None)
        if make_link is not None:
            # An engine-built formula that names its own sources
            # (``box=<formula>``: box.py ``_BoxFitRead`` / ``_BoxFitBody``).
            new_link = make_link(formula, self)
        elif isinstance(formula, Container):
            new_link = DirectLink(formula)
        elif callable(formula):
            new_link = FormulaLink(formula)
        elif isinstance(formula, Number):
            # Unmigrated constructors still pass plain numbers through assign_formula.
            # Scalar FieldRef @= rejects numbers in _link_field (Decision: no implicit copy).
            self._takein(formula)
            return
        else:
            raise TypeError(_LINK_RHS_ERROR)

        # Draggable / wheel_rotate / Anchor shapes forbid inbound links on pose parts.
        # Active tween / move_along claims also refuse (eager, at the @= call site).
        from .process import refuse_if_process_driven
        refuse_if_process_driven(self)
        cur: Optional[Container] = self
        while cur is not None:
            ensure = getattr(cur, '_ensure_can_link_attribute', None)
            if ensure is not None:
                ensure(self)
            cur = cur._owner

        # At most one formula on an ancestor↔descendant chain (not counting self replace).
        self._ensure_no_competing_formula()

        # Cycle-check before committing _link / rewire (rollback-safe).
        new_link.owner = self
        try:
            new_link.check_circular_reference()
        finally:
            new_link.owner = None

        # If we have a direct or formula link, clear it before setting
        if self._link is not None:
            from .process import report_author_warning
            report_author_warning(
                "@=",
                f"{self.name} received a formula that overrides its previous link "
                f"(the new one replaces it). To replace a link on purpose, call "
                f"{self._author_unlink_hint()} first.",
            )
            self.unlink()
        # Snapshot sticky pull flags so a failed install does not poison A2.
        pull_flags = []
        seen_roots = set()
        for node in (self, *tuple(new_link.sources)):
            root = node._ownership_root()
            rid = id(root)
            if rid in seen_roots:
                continue
            seen_roots.add(rid)
            pull_flags.append((root, root._needs_pull_invalidate))
        # Create the link with self as owner
        self._link = new_link
        self._invalidate_bare_reads()
        # Inbound links disable bare-pose fast paths and enable invalidate.
        self._flag_pull_consumers()
        # Parts now depend on this object (value flows from formula down the tree)
        self._rewire_subtree_structural_edges(upward=True)
        # set_owner re-checks cycle, registers edges, evaluates
        try:
            new_link.set_owner(self)
        except Exception:
            try:
                new_link.clear()
            except Exception:
                new_link.owner = None
            self._link = None
            self._invalidate_bare_reads()
            self._rewire_subtree_structural_edges(upward=None)
            for root, flag in pull_flags:
                root._needs_pull_invalidate = flag
            raise
        self._note_part_link_changed()

    def _note_part_link_changed(self) -> None:
        """A link on this part was installed or removed: an owner whose model
        depends on which part links re-reads it (``Text._part_link_changed``:
        a linked ``center`` is an anchored caption's pin)."""
        root = self._ownership_root()
        if root is not self:
            hook = getattr(root, '_part_link_changed', None)
            if hook is not None:
                hook(self)

    def unlink(self):
        """Unlink an attribute from its link; it keeps its CURRENT value.

        Pull the link first: a source write only marks this node dirty, so
        freezing without a pull would keep a stale value that depends on
        whether anyone read in between (D8 in Testing Design).
        """
        if self._link is not None:
            try:
                self._resolve_link()
            except (DestroyedError, ReferenceError):
                pass  # a source is already gone: keep the value pulled before it went
            except Exception:  # noqa: BLE001 — the link is going away
                # The source holds a value the field refuses now (``True``, NaN,
                # ``10**400``: GX14), or the formula itself raises (a ``KeyError``
                # on ``st.d["k"]`` after ``st.d = {}``). The pull stored nothing,
                # so the field keeps the last good value; unlinking (and
                # destroy, which unlinks) must not fail on the link it removes
                # (review 2026-10-09 S5-5: a KeyError orphaned the anchor and
                # made destroy() raise half-way).
                pass
            # FormulaLink.clear() handles dependency cleanup
            link = self._link
            link.clear()
            self._link = None
            self._invalidate_bare_reads()
            # Restore structural edges from field_type (Defining vs Derivate)
            # and any remaining formula-driven ancestors.
            self._rewire_subtree_structural_edges(upward=None)
            # A relational shape whose relation this link carried becomes its
            # free twin (Q3b in Testing Design; Shape._relation_unlinked).
            root = self._ownership_root()
            if root is not self:
                hook = getattr(root, '_relation_unlinked', None)
                if hook is not None:
                    hook(link)
            self._note_part_link_changed()

    def unlink_all(self) -> 'Container':
        """
        Remove every formula link on this container and its descendants.

        Use before linking a parent that would otherwise conflict with leaf
        formulas (symmetric forbid on ancestor↔descendant chains).
        """
        for node in list(self._iter_subtree()):
            if node._link is not None:
                node.unlink()
            if isinstance(node, ScalarAnchor):
                parent = node._scalar_parent
                if parent is not None:
                    parent._drop_scalar_anchor(node._scalar_name)
        return self

    @abstractmethod
    def _update_impl(self) -> None:
        """
        Implementation of update logic. This is called by update() after checking
        if updates are paused or if we're already in an update.
        """
        raise NotImplementedError("Subclasses must implement _update_impl")
    
    def __imatmul__(self, other) -> 'Container':
        """
        Implements the @= operator for creating a link or formula from self to other.
        
        Args:
            other: The Attribute instance to link to or a lambda function
            
        Returns:
            self for chaining
            
        Raises:
            TypeError: If other is not an Attribute or a lambda function
        """
        _refuse_link_on_dead(self, "@=")
        if self.__class__ is _HELD_BY_VALUE:
            refuse_held_payload(self, "{cell} @= …")
        hook = _ACT_LINK_HOOK
        owner = self._owner
        commit = None
        if hook is not None and owner is not None and self.attr_name:
            commit = hook(owner, self.attr_name)       # ``c.center @= …`` (PA1)
        self._assign_formula(other)
        hook = self.__dict__.get('_held_payload')
        if hook is not None:
            hook.link_changed(self)         # ``ship.aim @= f`` (VB3)
        if commit is not None:
            commit()
        return self

    def __lshift__(self, other: Any) -> 'Container':
        """
        Implements the << operator to call takein
        Example: A << B is equivalent to A._takein(B)
        Returns self for method chaining.
        """
        # One owner-chain walk for both author-door checks (``<<`` is a
        # per-frame verb): a computed part refuses ``<<`` like ``=``
        # (``rect.top_right << (1, 2)`` overwrote the point and left the rect
        # where it was), then a live formula on self / an ancestor /
        # a descendant refuses it (``_refuse_author_write``). The full
        # methods run only on a hit and word the errors.
        linked = False
        node = self
        while node is not None:
            nd = node.__dict__
            if nd.get('_field_type') is _FIELD_DERIVATE:
                self._ensure_not_derivate("set", other)
            if nd.get('_link') is not None:
                linked = True
            node = nd.get('_owner')
        if linked or self._formula_driven_descendant() is not None:
            self._refuse_author_write()
        if other.__class__ is not tuple and getattr(other, "_destroyed", False):
            # A destroyed source is not a live Scena object: clone() and
            # absorb() refuse it, and so does << (GX12 in Testing Design).
            from .entity import _destroyed_access_message
            raise DestroyedError(_destroyed_access_message(
                other, f"{self.name} << {other.name}: the source was destroyed; "
                       f"copy it before destroy(), or keep it alive"))
        self._takein(other)
        hook = _PLACEMENT_HOOK
        if hook is not None:
            hook(self)          # ``center << p`` is placement (X-writers-4)
        return self

    def __getitem__(self, key: str) -> 'FieldRef':
        """Link-management handle for ``key``. Does not read the field's value."""
        self._resolve_field(key)
        return FieldRef(owner=self, name=key)

    def __setitem__(self, key: str, value) -> None:
        """Write-back target for ``obj[key] @= source``. Plain assignment is an error."""
        if isinstance(value, FieldRef) and value.owner is self and value.name == key:
            return
        raise TypeError(
            f"{type(self).__name__}[...] does not support plain assignment; "
            f"use '{key} = value' for a concrete value or '[...] @= ...' to link"
        )

    def _mark_defining_parts(self, *defining: str, catalog: Tuple[str, ...]) -> None:
        """Record the model's Defining names; skip ScalarSlot leaves (no field_type).

        Shared by Shape and SpatialFx domain types so dual-model Defining/Derivate
        flipping stays in one place.
        """
        defining_set = set(defining)
        self._defining_part_names = defining_set
        for name in defining_set:
            part = getattr(self, name)
            if isinstance(part, Container):
                part._field_type = FieldType.Defining
        for name in catalog:
            if name in defining_set:
                continue
            part = self.__dict__.get(name)
            if not isinstance(part, Container):
                continue
            part._field_type = FieldType.Derivate
            part._rewire_subtree_structural_edges(upward=True)
        self._rewire_subtree_structural_edges(upward=None)

    @staticmethod
    def _free_model(model):
        """The model a copy adopts for ``model`` (Shape kinds map relational ones)."""
        return model

    def _takein_pose(self, other) -> None:
        """Hook after a whole-object takein (``<<``, ``absorb``, a whole ``@=`` pull).
        Graphics carry the source's pose (C7); a plain Container has none."""

    def _adopt_model_of(self, other, model=None) -> None:
        """A copy (``_takein``) takes the source's construction model, and with
        it the source's Defining set. Switching only ``model`` left the old
        Defining parts in place: the copy read stale sizes / centers and
        refused writes to its new inputs (D21 in Testing Design). The bare-read
        caches classified under the old set are dropped.

        A relational source model (Line ``parallel_to=`` / ``circle=``, Ellipse
        ``from_rect=``) arrives as its free twin (``_free_model``): a copy has
        no links, and a relational model without them moved wrong (graphics
        review SB5: a tangent copy stretched on ``move_by``). ``model``: the
        model to take instead, for a source of another kind (an Ellipse that
        fills a Box takes CENTER_WH)."""
        if model is None:
            model = self._free_model(other.model)
        self.model = model
        own = getattr(self, '_defining_names_for', None)
        names = own(model) if own is not None else None
        if names is None and model is other.model:
            names = other.__dict__.get('_defining_part_names')
        names = set(names) if names is not None else None
        old = self.__dict__.get('_defining_part_names') or set()
        if names is not None and names != old:
            self._set_defining_parts(*sorted(names))
            # A part built while it was an input is now computed: make it live
            # (as a first read of a Derivate does) so the update refreshes it.
            flipped = [self.__dict__.get(n) for n in old - set(names)]
            flipped = [p for p in flipped if isinstance(p, Container)]
            if flipped:
                for part in flipped:
                    part._derivate_live = True
                self._flag_pull_consumers()
            self._invalidate_bare_reads()

    def _takein_live_derivate(self, name: str, value) -> None:
        """Write a Derivate part only if it is already materialized and live.

        ScalarSlot leaves use plain assignment; Container parts use ``takein``.
        """
        slot = self._field_slots().get(name)
        if isinstance(slot, ScalarSlot):
            if self._field_is_derivate(name, slot):
                setattr(self, name, value)
            return
        part = self.__dict__.get(name)
        if part is None:
            return
        if part._field_type == FieldType.Defining:
            return
        if not part._is_derivate_live():
            return
        part._takein(value)

    def _field_slots(self) -> Dict[str, Any]:
        """Declared ContainerSlot / ScalarSlot descriptors on this class."""
        cls = type(self)
        cache = cls.__dict__.get('_field_slot_cache')
        if cache is None:
            cache = {}
            for base in cls.__mro__:
                for name, val in base.__dict__.items():
                    if getattr(val, '_is_field_slot', False) and name not in cache:
                        cache[name] = val
            try:
                cls._field_slot_cache = cache
            except TypeError:
                pass
        return cache

    def _field_is_derivate(self, name: str, slot=None) -> bool:
        """True if ``name`` is a computed output of this object's current model.

        Honors per-instance ``_defining_part_names`` (Line.angle is Defining
        in POINT_ANGLE_LENGTH and Derivate in POINT_POINT). Falls back to the
        slot's declared ``field_type``.
        """
        defining = getattr(self, '_defining_part_names', None)
        if defining is not None:
            return name not in defining
        if slot is None:
            slot = self._field_slots().get(name)
        return getattr(slot, 'field_type', FieldType.Defining) == FieldType.Derivate

    def _resolve_field(self, key: str):
        """Return the slot descriptor for ``key``, or raise AttributeError."""
        if not isinstance(key, str):
            raise TypeError(_field_key_refusal(self, key))
        slot = self._field_slots().get(key)
        if slot is not None:
            return slot
        ink = getattr(self, '_ink', None)
        if isinstance(ink, dict) and key in ink:
            return _INK_SLOT
        raise AttributeError(f"{type(self).__name__} has no field {key!r}")

    def _scalar_anchor_class(self, name: str):
        """Anchor type for a linked scalar field. Graphic overrides for pose properties."""
        return ScalarAnchor

    def _ensure_scalar_anchor(self, name: str, anchor_cls: type = None) -> 'ScalarAnchor':
        anchors = self.__dict__.get('_field_anchors')
        if anchors is None:
            anchors = {}
            self.__dict__['_field_anchors'] = anchors
        cls = anchor_cls or self._scalar_anchor_class(name)
        anchor = anchors.get(name)
        if anchor is None:
            anchor = cls(self, name)
            anchors[name] = anchor
            bump_pose_trust(self)   # an anchor came: trust is re-checked
            ink = getattr(self, '_ink', None)
            if isinstance(ink, dict):
                held = ink.get(name)
                if held.__class__ is _HELD_BY_VALUE:
                    # A Vec2 in this ink field: its in-place changes notify
                    # the field from now on (``_HeldPayloadUpdate``).
                    _hold_payload(held, self, name)
        elif type(anchor) is not cls:
            # Formula source extraction and ``@=`` must share one node type
            # (``_PropertyAnchor`` for Graphic.angle/scale, not a dead ScalarAnchor).
            if anchor._link is not None:
                anchor.unlink()
            anchor._clean_up()
            anchor = cls(self, name)
            anchors[name] = anchor
        return anchor

    def _drop_scalar_anchor(self, name: str) -> None:
        anchors = self.__dict__.get('_field_anchors')
        if not anchors or name not in anchors:
            return
        anchor = anchors.pop(name)
        bump_pose_trust(self)
        ink = getattr(self, '_ink', None)
        if isinstance(ink, dict) and ink.get(name).__class__ is _HELD_BY_VALUE:
            _unhold_payload(ink[name], self, name)
        try:
            if anchor._link is not None:
                anchor.unlink()
        finally:
            anchor._clean_up()      # never leave a popped anchor in the graph

    def _link_field(self, name: str, source) -> None:
        """Install a formula/direct link on field ``name`` (bracket ``@=``)."""
        _refuse_link_on_dead(self, f"{name} @=")
        if self.__class__ is _HELD_BY_VALUE:
            cell = held_cell(self)
            if cell is not None:
                # ``st.pos["x"] @= f`` as ``st.pos @= f``: the link would stay
                # on this payload after the next ``st.pos = …``, and its pulls
                # are raw stores the cell never hears (VB3).
                who = cell._name
                owner, _, key = who.rpartition(".")
                bracket = f'{owner}["{key}"]' if owner else who
                raise TypeError(
                    f'{who}["{name}"] @= … would link one axis of the '
                    f"{type(self).__name__} that {who} holds now, not the cell: "
                    f"the next {who} = … would leave the link behind, and "
                    f"nothing linked to {who} would see it. Link the cell to "
                    f"the whole vector: {bracket} @= lambda: Vec2(x, y)."
                )
        source = _normalize_link_rhs(source)
        if not callable(source) and not isinstance(source, Container):
            raise TypeError(_LINK_RHS_ERROR)
        # Eager refuse when a tween/move_along already claims this field.
        claims = self.__dict__.get("_process_field_claims")
        if claims:
            from .process import _claim_active
            h = claims.get(name)
            if _claim_active(h):
                from .entity import entity_label
                raise LinkedAttributeError(
                    motion_conflict_message(h, subject=entity_label(self), part=str(name))
                )
        slot = self._resolve_field(name)
        if slot is _INK_SLOT or isinstance(slot, ScalarSlot):
            if slot is not _INK_SLOT and self._field_is_derivate(name, slot):
                raise DerivedAttributeError(self._derived_field_message(name, "link"))
            if slot is not _INK_SLOT and not self._in_batch_update:
                der = self._derivate_source()
                if der is not None:
                    raise DerivedAttributeError(self._derived_refusal(der, "link", leaf=name))
            anchors = self.__dict__.get('_field_anchors')
            had_anchor = bool(anchors) and name in anchors
            anchor = self._ensure_scalar_anchor(name)
            try:
                anchor._assign_formula(source)
            except BaseException:
                # A formula that raises on its first evaluation installs
                # nothing: drop the anchor this call created (W3).
                if not had_anchor:
                    self._drop_scalar_anchor(name)
                raise
            hook = self.__dict__.get('_held_payload')
            if hook is not None:
                # ``ship.aim["y"] @= f``: the pull stored raw (no update()).
                hook.link_changed(self)
            return
        # Refuse before ``__get__`` so a rejected Derivate link does not
        # materialize the slot or stick ``_needs_pull_invalidate``.
        if not getattr(self, "_in_batch_update", False) and self._field_is_derivate(name, slot):
            raise DerivedAttributeError(self._derived_field_message(name, "link"))
        target = slot.__get__(self, type(self))
        target._assign_formula(source)

    def _linkable_source(self, name: str) -> 'Container':
        """Graph node for ``self[name]`` used as a DirectLink RHS.

        Scalar / ink / property fields resolve to their ScalarAnchor (created on
        demand so source-only anchors dirty dependents on write). Composite
        parts resolve to the part Container itself.
        """
        slot = self._resolve_field(name)
        if slot is _INK_SLOT or isinstance(slot, ScalarSlot):
            return self._ensure_scalar_anchor(name)
        target = slot.__get__(self, type(self))
        if not isinstance(target, Container):
            raise TypeError(_LINK_RHS_ERROR)
        return target

    def _unlink_field(self, name: str) -> None:
        slot = self._resolve_field(name)
        if slot is _INK_SLOT or isinstance(slot, ScalarSlot):
            anchors = self.__dict__.get('_field_anchors')
            anchor = anchors.get(name) if anchors else None
            if anchor is not None and anchor._external_formula_dependents():
                # The anchor is also the node other formulas read this field
                # through: unlinking freezes the field and keeps it a source.
                # Dropping it unlinked every reader ("a formula source was
                # removed") and froze it at a stale value (AC12).
                if anchor._link is not None:
                    anchor.unlink()
                return
            self._drop_scalar_anchor(name)
            return
        target = slot.__get__(self, type(self))
        if isinstance(target, Container):
            target.unlink()

    def _read_field(self, name: str):
        self._resolve_field(name)
        v = getattr(self, name)
        # Boxed State/widget cells: FieldRef.value is the payload, matching
        # scalar FieldRefs that already return a bare float/str.
        if isinstance(v, Attribute):
            return v.value
        return v

    def _field_is_linked(self, name: str) -> bool:
        slot = self._resolve_field(name)
        if slot is _INK_SLOT or isinstance(slot, ScalarSlot):
            anchors = self.__dict__.get('_field_anchors')
            if not anchors or name not in anchors:
                return False
            return anchors[name]._link is not None
        target = slot.__get__(self, type(self))
        return isinstance(target, Container) and target._link is not None

    def _write_field(self, name: str, value) -> None:
        """Write a concrete value onto ``name``. Raises if the field is linked."""
        slot = self._resolve_field(name)
        if slot is _INK_SLOT or isinstance(slot, ScalarSlot):
            # Fast path: same A3 ``_scalar_bare_ok`` cache as ScalarSlot.__get__.
            # True means unlinked Defining leaf with no formula/Derivate ancestor —
            # skip the repeated resolve/link/derivate walks on every tween write.
            # Any ScalarAnchor for this name (linked or source-only) must take the
            # full path: linked raises; source-only still dirties dependents.
            if isinstance(slot, ScalarSlot):
                bare_ok = self.__dict__.get('_scalar_bare_ok')
                anchors = self.__dict__.get('_field_anchors')
                has_anchor = bool(anchors and name in anchors)
                if (
                    bare_ok is not None
                    and bare_ok.get(name) is True
                    and not has_anchor
                ):
                    if isinstance(value, Attribute):
                        value = value.value
                    value = _coerce_magnitude_slot(
                        slot, value, clamp=self._in_batch_update, owner=self,
                    )
                    d = self.__dict__
                    old = d.get(name, slot.default)
                    if old != value:
                        d[name] = value
                        # bump_pose_rev(self), inline (the per-write hot path)
                        cell = d.get('_pose_cell')
                        if cell is None:
                            cell = _pose_cell_of(self)
                        cell[0] += 1
                        if not cell[1]:
                            cell[1] = True
                            DIRTY_POSE_CELLS.append(cell)
                        if name == "angle":
                            # Shape: the pose store follows (inline: per-frame
                            # ``ship.angle = …``; no anchor on this path).
                            defining = d.get('_defining_part_names')
                            if (defining and 'angle' in defining
                                    and self._publish_angle_input is not None
                                    and not self._in_batch_update):
                                object.__setattr__(self, '_rotation',
                                                   value if type(value) is float else float(value))
                        if self._requires_pull_invalidate():
                            if not self._in_batch_update:
                                self.update()
                            elif self._node_id is not None:
                                self._scena_system.update_manager.mark_dirty(self)
                    return

            if self._field_is_linked(name):
                raise LinkedAttributeError(
                    f"{self.name}.{name} is linked — call {self.name}['{name}'].unlink() first"
                    + _follows_cell_hint(self.__dict__.get(name))
                )
            # Parent / ancestor formulas: author ``=`` raises. Batched
            # ``_update_impl`` must still refresh Derivate leaves (e.g. Vec2.length
            # under a linked vec).
            if not self._in_batch_update:
                blocker = self if self._link is not None else self._formula_driven_ancestor()
                if blocker is not None:
                    hint = blocker._author_unlink_hint()
                    raise LinkedAttributeError(
                        f"{blocker.name} is linked — call {hint} first"
                    )
            if slot is not _INK_SLOT and not self._in_batch_update:
                if self._field_is_derivate(name, slot):
                    raise DerivedAttributeError(
                        self._derived_field_message(name, "set", value)
                    )
                der = self._derivate_source()
                if der is not None:
                    raise DerivedAttributeError(
                        self._derived_refusal(der, "set", value, leaf=name)
                    )
            # Seed A3 write/read cache after the full guard path has proven
            # this ScalarSlot is a bare Defining leaf (same conditions as __get__,
            # ``_pull_owner`` included: a point a linked heading turns is pulled
            # on read; seeded here, its first read skipped that pull: GX7).
            if (
                isinstance(slot, ScalarSlot)
                and not self._in_batch_update
                and self._link is None
                and '_pull_owner' not in self.__dict__
            ):
                cache = self.__dict__.get('_scalar_bare_ok')
                if cache is None:
                    cache = {}
                    self.__dict__['_scalar_bare_ok'] = cache
                if name not in cache:
                    cache[name] = True
            if isinstance(value, Attribute):
                value = value.value
            elif value.__class__ is _KEY_NAME:
                value = str(value)
            if isinstance(slot, ScalarSlot):
                value = _coerce_magnitude_slot(
                    slot, value, clamp=self._in_batch_update, owner=self,
                )
            ink = getattr(self, '_ink', None)
            if slot is _INK_SLOT and isinstance(ink, dict):
                old = ink.get(name)
                store = ink
            else:
                old = self.__dict__.get(name, slot.default)
                store = self.__dict__
            if old is value:
                # The same object again. A number or a string: nothing changed
                # (and no ``_value_changed`` call). ``ship.items += [x]`` /
                # ``ship.d |= {…}``: ``+=`` changed the held object and assigns
                # it back. Tell what reads the field, as ``st.items += [x]``
                # does. (A Vec2 told them already, from its own ``update()``.)
                if (store is ink and type(value) not in _VALUE_TYPE_SET
                        and value.__class__ is not _HELD_BY_VALUE):
                    anchors = self.__dict__.get('_field_anchors')
                    anchor = anchors.get(name) if anchors else None
                    if anchor is not None:
                        _notify_ink_anchor(self, anchor)
            elif _value_changed(old, value):
                store[name] = value
                if store is not ink:
                    bump_pose_rev(self)
                elif value.__class__ is _HELD_BY_VALUE:
                    value.__dict__['_ink_held'] = True     # a cell copies it (VB2)
                if name == "angle" and store is self.__dict__:
                    pub = self._publish_angle_input
                    if pub is not None:
                        pub()
                anchors = self.__dict__.get('_field_anchors')
                anchor = anchors.get(name) if anchors else None
                if anchor is not None:
                    if ((old.__class__ is _HELD_BY_VALUE
                         or value.__class__ is _HELD_BY_VALUE) and store is ink):
                        _hold_ink_value(self, name, old, value)
                    # Source-only or linked ScalarAnchor: dependents of this
                    # field (other formulas that read it) must be dirtied.
                    if not self._in_batch_update:
                        anchor.update()
                    elif anchor._node_id is not None:
                        self._scena_system.update_manager.mark_dirty(anchor)
                if self._requires_pull_invalidate():
                    if not self._in_batch_update:
                        self.update()
                    elif self._node_id is not None:
                        self._scena_system.update_manager.mark_dirty(self)
                elif slot is _INK_SLOT:
                    self._scena_system.update_manager.maybe_poll_events()
            return
        target = slot.__get__(self, type(self))
        target._ensure_not_derivate("set", value)
        target._refuse_author_write()
        target._takein(value)

    def _derived_field_message(
        self, name: str, operation: str, value: Any = None, part: Optional[str] = None,
    ) -> str:
        """Why the Derivate field ``name`` refuses ``operation`` (``"set"`` /
        ``"link"``); ``part`` is the path below it (``rect.top_right.x = 1``).

        Names what the field is computed from (this object's model inputs) and
        the fix: a computed point of an actor moves with
        ``rect.move_to(x, y, about=rect.top_right)``; anything else changes
        through its inputs, or a constructor that takes it as an input. A class
        with a better fix words its own (``Vec2``).
        """
        who = type(self).__name__
        var = _snake_name(who)
        prose = var.replace("_", " ")
        # A class whose computed fields come from something that is not a
        # model field (a Track's path, a Polygon's points) names it instead.
        derived_from = getattr(type(self), "_derived_from", None)
        inputs = [] if derived_from else self._model_inputs(exclude=name)
        if derived_from:
            source = f"computed from the {prose}'s {derived_from}"
        elif inputs:
            source = f"computed from the {prose}'s {_join_names(inputs, 'and')}"
        else:
            source = "computed"
        what = "linked" if operation == "link" else "set"
        subject = f"its {part}" if part else "it"
        head = f"{who}.{name} is {source}, so {subject} cannot be {what}."
        build = ""
        if self._constructor_takes(name):
            build = f"build the {prose} with {name}=: {who}(..., {name}=...)"
        slot = self._field_slots().get(name)
        is_point = (
            isinstance(slot, ContainerSlot) and slot.container_class.__name__ == "Point"
        )
        if operation == "link":
            if not inputs:
                return head + (f" To set it, {build}." if build else "")
            first = inputs[0]
            first_slot = self._field_slots().get(first)
            example = (
                f"{var}.{first} @= lambda: ..." if isinstance(first_slot, ContainerSlot)
                else f'{var}["{first}"] @= lambda: ...'
            )
            tail = f" Link one of those instead ({example})"
            return head + tail + (f", or {build}." if build else ".")
        if is_point and hasattr(self, "move_to"):
            x, y = _derived_point_target(var, name, value, part)
            where = f"{name}.{part} is {_number_text(value)}" if part else f"{name} lands at ({x}, {y})"
            relational = getattr(self, "_relational_move_hint", None)
            hint = relational(var) if relational is not None else None
            if hint:
                return f"{head} {hint}"
            if self._move_writes_a_link():
                # The plain move is refused (a linked input, or a relational
                # model's reference): suggest the move that lands (GR2).
                return (
                    f"{head} It follows a link, so a plain move is refused. To free it and "
                    f"move it so its {where}, write "
                    f"{var}.move_to({x}, {y}, about={var}.{name}, force=True)."
                )
            return (
                f"{head} To move the {prose} so its {where}, write "
                f"{var}.move_to({x}, {y}, about={var}.{name})."
            )
        if derived_from:
            return f"{head} Change the {prose}'s {derived_from} instead" + (
                f", or {build}." if build else ".")
        if not inputs:
            return head + (f" To set it, {build}." if build else "")
        return f"{head} Change {_join_names(inputs, 'or')} instead" + (f", or {build}." if build else ".")

    def _move_writes_a_link(self) -> bool:
        """True when ``move_to`` would write a linked part: a whole-object
        link, or a link on a Defining point (refusal message only)."""
        if self._link is not None or self._formula_driven_ancestor() is not None:
            return True
        for pname in (self.__dict__.get('_defining_part_names') or ()):
            part = self.__dict__.get(pname)
            if isinstance(part, Container) and part.__class__.__name__ == "Point" \
                    and any(n._link is not None for n in part._iter_subtree()):
                return True
        return False

    def _derived_refusal(self, source: "Container", operation: str, value: Any = None,
                         leaf: Optional[str] = None) -> str:
        """Message for a write on or under the Derivate part ``source``
        (``self`` is ``source`` or a node below it; ``leaf`` a scalar on ``self``)."""
        path = []
        node = self
        while node is not source and node is not None:
            path.append(node._attr_name)
            node = node._owner
        path.reverse()
        if leaf:
            path.append(leaf)
        owner = source._owner
        if owner is None or node is None:
            return (
                f"Cannot {operation} {self.name}: {source.name} is computed "
                f"(a derived attribute), so it cannot be set or linked."
            )
        return owner._derived_field_message(
            source._attr_name, operation, value, part=".".join(path) or None,
        )

    def _model_inputs(self, exclude: Optional[str] = None) -> List[str]:
        """This object's Defining fields (its model inputs): placement parts
        (points, vectors) first, then numbers, each in declaration order."""
        defining = getattr(self, '_defining_part_names', None)
        if not defining:
            return []
        slots = self._field_slots()
        names = [n for n in slots if n in defining and n != exclude]
        names += sorted(n for n in defining if n not in slots and n != exclude)
        return sorted(names, key=lambda n: not isinstance(slots.get(n), ContainerSlot))

    def _constructor_takes(self, name: str) -> bool:
        """True when ``type(self)(…, name=…)`` is a constructor keyword."""
        try:
            return name in inspect.signature(type(self)).parameters
        except (TypeError, ValueError):
            return False

    def _refresh_scalar(self, name: str) -> None:
        """Pull-resolve a bare scalar that is not itself linked (ancestor / Derivate)."""
        if self._link is not None:
            self._resolve_link()
            if name not in self.__dict__:
                # A Derivate of a linked leaf (``Vec2.length``) is computed on
                # first read; the pull's raw store keeps it in step after that.
                slot = self._field_slots().get(name)
                if isinstance(slot, ScalarSlot) and self._field_is_derivate(name, slot):
                    self._ensure_derivate_scalar(name)
            return
        ancestor = self._formula_driven_ancestor()
        if ancestor is not None:
            ancestor._resolve_link()
            return
        slot = self._field_slots().get(name)
        if isinstance(slot, ScalarSlot) and self._field_is_derivate(name, slot):
            self._ensure_derivate_scalar(name)
            return
        if self._derivate_source() is not None:
            root = self._local_refresh_root()
            if root is not None and root._dirty:
                root._resolve_structural()
            elif root is self and self._owner is not None and self._owner._dirty \
                    and '_heading_anchor' in self._owner.__dict__:
                self._owner._resolve_structural()      # D18, as in _ensure_fresh
        elif '_pull_owner' in self.__dict__:
            self._pull_owner_first()

    def _ensure_derivate_scalar(self, name: str) -> None:
        """Materialize a Derivate ScalarSlot on first access / when dirty."""
        cache = self.__dict__.get('_derivate_state')
        if cache is None:
            cache = {}
            self.__dict__['_derivate_state'] = cache
        state = cache.get(name)
        if state is None:
            cache[name] = {'dirty': False}
            self._flag_pull_consumers()
            if self._dirty:
                self._resolve_structural()
            else:
                materialize = getattr(self, '_materialize_derivate_part', None)
                if materialize is not None:
                    materialize(name)
            return
        if self._dirty:
            self._resolve_structural()
            return
        if state.get('dirty'):
            materialize = getattr(self, '_materialize_derivate_part', None)
            if materialize is not None:
                materialize(name)
            state['dirty'] = False

    @classmethod
    def _extract_common_params_and_signature(cls, kwargs: Dict[str, Any], 
                                            valid_signatures: List[Tuple[str, Set[str]]]) -> Tuple[Dict[str, Any], str]:
        """
        Extract common Shape parameters and determine the signature for shape construction.

        Unknown kwargs raise ``TypeError`` first. Home fill is only for three forms:
        empty, ``center=`` only (plus optionals), or exact home / home-minus-center.
        Expert paths stay exact.

        Args:
            kwargs: All keyword arguments passed to the constructor (mutated on home fill)
            valid_signatures: List of (signature_name, required_keys) tuples
        Returns:
            Tuple of (base_params, signature_name) where base_params contains layer, group
        """
        common_keys = {'layer', 'group', 'visual', 'color', 'line_width'}
        extras = getattr(cls, '_CTOR_EXTRA_KEYS', frozenset()) or frozenset()

        shape_keys: Set[str] = set()
        for _, keys in valid_signatures:
            shape_keys.update(keys)


        # Unknown / wrong-family keywords fail loud.
        allowed = shape_keys | common_keys | set(extras)
        leftover = {k: kwargs[k] for k in kwargs if k not in allowed}
        if leftover:
            from .validate import reject_unexpected_kwargs
            reject_unexpected_kwargs(
                cls.__name__, leftover, valid=allowed,
                hints=getattr(cls, '_CTOR_KWARG_HINTS', None),
            )

        # Style / group class defaults apply on every path (after leftover check).
        defaults = getattr(cls, '_shape_defaults', None) or {}
        for key in ('color', 'visual', 'group'):
            if key not in kwargs and key in defaults:
                kwargs[key] = defaults[key]

        home_keys = getattr(cls, '_HOME_KEYS', None)
        home_optional = getattr(cls, '_HOME_OPTIONAL_KEYS', None) or frozenset()
        present_keys = set(kwargs.keys()) & shape_keys

        if home_keys is not None:
            # Class size defaults count toward home completeness (Brick(width=)
            # with class height=), but are only injected when the call is a
            # home form — expert paths must not pick up class radius/width.
            size_keys = getattr(cls, '_HOME_SIZE_KEYS', frozenset()) or frozenset()
            home_set = set(home_keys)
            trial_keys = set(present_keys)
            for key in size_keys:
                if key not in kwargs and key in defaults and key in home_set:
                    trial_keys.add(key)

            G = trial_keys - set(home_optional)
            home_minus_center = home_set - {'center'}
            eligible = G <= home_set and (
                not G
                or G == {'center'}
                or G == home_minus_center
                or G == home_set
            )
            if eligible:
                apply = getattr(cls, '_apply_home_fill', None)
                if callable(apply):
                    apply(kwargs)
                present_keys = set(kwargs.keys()) & shape_keys

        matched_signatures = [
            sig_name
            for sig_name, required_keys in valid_signatures
            if required_keys == present_keys
        ]

        if len(matched_signatures) == 0:
            raise ValueError(
                cls._format_incomplete_signature_error(
                    present_keys, valid_signatures, home_keys=home_keys,
                )
            )
        if len(matched_signatures) > 1:
            raise ValueError(
                f"Multiple matching signatures for keys: {present_keys}. "
                f"Matches: {matched_signatures}"
            )

        signature = matched_signatures[0]

        # Forward common params (after style class defaults).
        # Only forward ``layer`` when the caller set it — omitting it lets Shape's
        # default apply. ``layer=None`` means undrawn and must pass through.
        group = kwargs.get('group')
        base_params: Dict[str, Any] = {'group': group}
        if 'layer' in kwargs:
            base_params['layer'] = kwargs['layer']
        if 'visual' in kwargs:
            base_params['visual'] = kwargs['visual']
        if 'color' in kwargs:
            base_params['color'] = kwargs['color']
        # Omit keeps the paint prototype (1.5, or set_defaults). Not a class default.
        if 'line_width' in kwargs:
            base_params['line_width'] = kwargs['line_width']

        return base_params, signature

    @classmethod
    def _format_incomplete_signature_error(
        cls,
        present_keys: Set[str],
        valid_signatures: List[Tuple[str, Set[str]]],
        *,
        home_keys: Optional[Set[str]] = None,
    ) -> str:
        """Name started path(s) and missing keys; hint center= / complete home."""
        candidates: List[Tuple[str, Set[str], Set[str]]] = []
        for sig_name, required in valid_signatures:
            if not required:
                continue
            if present_keys and present_keys <= required and present_keys != required:
                missing = required - present_keys
                candidates.append((sig_name, required, missing))
            elif present_keys & required and not (present_keys <= required):
                # Overlap but not a subset — still mention if any shared key.
                missing = required - present_keys
                if present_keys & required:
                    candidates.append((sig_name, required, missing))

        # Prefer signatures that contain all present keys (true "started this path").
        started = [
            (name, req, miss) for name, req, miss in candidates
            if present_keys <= req
        ]
        pool = started or candidates

        lines = [f"{cls.__name__}({', '.join(f'{k}=…' for k in sorted(present_keys)) or ''}) "
                 f"is not a complete constructor."]
        if present_keys:
            lines[0] = (
                f"{cls.__name__} received shape keys {sorted(present_keys)} — "
                f"not a complete constructor."
            )
        if pool:
            bits = []
            for name, req, miss in pool[:4]:
                bits.append(
                    f"{name.replace('_', '-')} ({', '.join(sorted(req))}; "
                    f"missing {', '.join(sorted(miss))})"
                )
            lines.append("  Started path(s): " + "; ".join(bits) + ".")
        if home_keys:
            if "center" in home_keys:
                lines.append(
                    f"  For a default-sized {cls.__name__}, pass center= "
                    f"(or a complete home signature: "
                    f"{', '.join(sorted(home_keys))})."
                )
            else:
                lines.append(
                    f"  Complete home keys: {', '.join(sorted(home_keys))}."
                )
        return "\n".join(lines)

    @contextmanager
    def _batch_update(self):
        """
        Batch updates across this container and its part subtree.
        Leaf Attribute writes do not each start a cycle; one update() runs at the end.
        
        Example:
            with shape._batch_update():
                shape.p1.x = 10
                shape.p2.y = 20
        """
        if _already_suppressing_updates(self):
            # Nested under an outer batch/no_update/cycle — outer owns flush.
            yield
            return

        previous_states: Dict[int, Tuple[Any, bool]] = {}
        self._push_batch_update_subtree(previous_states)
        try:
            yield
        finally:
            self._restore_batch_update_subtree(previous_states)
            um = self._scena_system.update_manager
            hit = previous_states.get(id(self))
            was_batching = hit[1] if hit else False
            if not was_batching and not um.is_updating:
                self.update()
            elif not was_batching and um.is_updating:
                if self._node_id is not None:
                    um.mark_dirty(self._node_id)
                else:
                    # Off the graph nothing pulls a refresh: ``mark_dirty(None)``
                    # did nothing, so a read length / angle stayed stale after
                    # ``v += w`` in an ``@on_change`` callback (VB16).
                    sync = self._sync_computed
                    if sync is not None:
                        sync()
                # In a flush callback the batch skips ``update()``, so a held
                # Vec2 (``ship.aim += …`` in ``@on_change``) tells its holders here.
                held = self.__dict__.get('_held_payload')
                if held is not None:
                    held.changed(self)

    @contextmanager
    def _no_update(self):
        """
        Suppress update() across this container and its part subtree.
        Unlike batch_update, does not flush an update at the end.
        """
        if _already_suppressing_updates(self):
            yield
            return

        previous_states: Dict[int, Tuple[Any, bool]] = {}
        self._push_batch_update_subtree(previous_states)
        try:
            yield
        finally:
            self._restore_batch_update_subtree(previous_states)


class ContainerSlot:
    """
    Descriptor for Container attributes in shapes.
    Automatically instantiates the specified class with attr_name and owner parameters.
    """
    _is_field_slot = True

    def __init__(self, container_class: type, field_type: FieldType = FieldType.Defining):
        """
        Initialize the descriptor with the class to instantiate.
        Args:
            container_class: The class to instantiate (must inherit from Container)
                             container_class constructor MUST NOT have positional arguments
        """
        self.container_class = container_class
        self.name = None  # Will be set by __set_name__
        self.field_type = field_type

    def __set_name__(self, owner, name):
        """Set the attribute name when the descriptor is assigned to a class."""
        self.name = name

    def __get__(self, instance, owner):
        """
        Get the container instance.
        """
        # Get the container instance from the instance's __dict__
        container = instance.__dict__.get(self.name)
        if container is None and instance.__dict__.get('_destroyed', False):
            # First read on a destroyed actor: answer with a detached temp
            # (default value). Wiring the owner edge would put the dead actor
            # back in the dependency graph (A7: Button.displayed_text()).
            with ephemeral_creation():
                container = self.container_class(attr_name=self.name, owner=None)
            container._field_type = self.field_type
            instance.__dict__[self.name] = container
            return container
        if container is None:
            # Create without owner first so field_type is set before the
            # owner edge is established. Sub-parts created during __init__
            # (e.g. Point.x/y) may have used the default Defining type, so
            # rewire them after field_type is applied.
            # Under a deferred tree (a measured Box) the part stays off the
            # graph until the tree joins it (``_join_dependency_graph``).
            deferred = instance._in_deferred_graph_tree()
            if deferred:
                with _deferred_registration():
                    container = self.container_class(attr_name=self.name, owner=None)
            else:
                container = self.container_class(attr_name=self.name, owner=None)
            # Prefer owner's model defining-set when present (lazy Derivate slots).
            defining = probe_private(instance, '_defining_part_names', None)
            if defining is not None and self.name in defining:
                container._field_type = FieldType.Defining
            elif defining is not None:
                container._field_type = FieldType.Derivate
            else:
                container._field_type = self.field_type
            if container._field_type == FieldType.Derivate and not deferred:
                container._rewire_subtree_structural_edges(upward=True)
            container.owner = instance
            instance.__dict__[self.name] = container
            # Inherit batch suppression from owner (mid-_update_impl materialize).
            if getattr(instance, '_in_batch_update', False):
                for node in container._iter_subtree():
                    node._in_batch_update = True
            # First access of a Derivate marks it live and materializes values.
            if container._field_type == FieldType.Derivate:
                container._derivate_live = True
                # Live Derivates need Defining writes to mark the shape dirty.
                flag = getattr(instance, '_flag_pull_consumers', None)
                if flag is not None:
                    flag()
                else:
                    container._flag_pull_consumers()
                materialize = getattr(instance, '_materialize_derivate_part', None)
                if materialize is not None:
                    materialize(self.name)
        return container

    def __set__(self, instance, value):
        """Set the container's value. Raises if the part is linked (Decision 4).

        Derivate refusal happens before ``__get__``. Materializing first would
        mark the part live and permanently set ``_needs_pull_invalidate`` (A2)
        even though the write is rejected. Batched ``_update_impl`` writes skip
        the check — those are the shape's own derivation.
        """
        if (
            not getattr(instance, "_in_batch_update", False)
            and instance._field_is_derivate(self.name, self)
        ):
            raise DerivedAttributeError(
                instance._derived_field_message(self.name, "set", value)
            )
        container = self.__get__(instance, None)  # Get the container instance
        container._assign_value(value)


def _dead_self_or_owner(instance):
    """The destroyed actor, if ``instance`` or its owner entity is dead.

    One dict hop. Living writes see ``_destroyed`` False and return None.
    """
    d = getattr(instance, "__dict__", None)
    if not d:
        return None
    if d.get("_destroyed"):
        return instance
    owner = d.get("_owner")
    if owner is not None and getattr(owner, "__dict__", {}).get("_destroyed"):
        return owner
    return None


class ScalarSlot:
    """Descriptor for bare scalar leaves (float/int/str) on a Container.

    Dot access returns the plain value. Link management goes through
    ``owner["name"]`` (a FieldRef). Linked fields get a ScalarAnchor graph
    node for as long as the link exists.
    """

    _is_field_slot = True

    def __init__(
        self,
        field_type: FieldType = FieldType.Defining,
        default: Any = 0.0,
        *,
        magnitude: bool = False,
        positive: bool = False,
        maximum: Optional[float] = None,
        minimum: Optional[float] = None,
        hint: Optional[str] = None,
        label: Optional[str] = None,
        out_of_range: str = "raise",
        maximum_open: bool = False,
    ):
        if out_of_range not in ("raise", "clamp"):
            raise ValueError(f"out_of_range must be 'raise' or 'clamp', got {out_of_range!r}")
        self.field_type = field_type
        self.default = default
        self.magnitude = magnitude
        self.positive = positive
        # ``label``: the name an error message gives the field (``Line.angle``);
        # ``slot.name`` when None. ``out_of_range``: what an author ``=`` past
        # ``minimum`` / ``maximum`` does (Circle ``spread`` raises, Track
        # ``begin`` / ``end`` clamp); a batch refresh and a link always clamp.
        self.label = label
        self.out_of_range = out_of_range
        # No size / range rule: the write and pull paths take the cheap branch.
        self._plain = not magnitude and minimum is None and maximum is None
        # 0 plain, 1 a size with no range (the common magnitude), 2 ranged:
        # the write path branches once instead of testing each rule.
        self._kind = 0 if self._plain else (1 if minimum is None and maximum is None else 2)
        # ``minimum`` / ``maximum``: a linked value is clamped into range on
        # pull (ScalarAnchor), the way the class's ``=`` rule clamps it; a
        # link cannot raise mid-frame (Track ``begin`` / ``end``, Circle ``spread``).
        self.maximum = maximum
        self.minimum = minimum
        # ``maximum_open``: ``maximum`` itself is out of range (Triangle
        # ``base_ratio < 2``); a clamp lands just below it.
        self.maximum_open = maximum_open
        self.hint = hint
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        name = self.name
        d = instance.__dict__

        anchors = d.get('_field_anchors')
        if anchors and name in anchors:
            anchor = anchors[name]
            anchor._ensure_fresh()
            ad = anchor.__dict__
            if ad.get('_derivate_field') and ad.get('_dirty') and ad.get('_link') is None:
                # A source-only anchor depends on its parent: dirty means the
                # parent changed, so a Derivate scalar recomputes (it froze
                # for every reader: review 2026-10-09 S5-2).
                anchor._clear_subtree_dirty()
                instance._refresh_scalar(name)
                return d.get(name, self.default)
            if type(anchor) is _PropertyAnchor:
                # A link that drives a verb on a Derivate slot (Rect spine /
                # Ellipse foci / p1-p2 Line ``angle``): the value is the Derivate.
                instance._refresh_scalar(name)
            return d.get(name, self.default)

        # Tier 1.6: owner is a linked leaf composite (Point / …) that is already
        # clean — return the stored scalar without re-entering ``_refresh_scalar``
        # → ``_resolve_link``'s guard. Dirty linked owners still refresh below,
        # and so does a Derivate never computed yet (``Vec2.length`` of a
        # linked vector read the 0.0 default).
        if d.get('_link') is not None and not d.get('_dirty', False) and name in d:
            return d[name]

        bare_ok = d.get('_scalar_bare_ok')
        if bare_ok is not None:
            flag = bare_ok.get(name)
            if flag is True:
                return d.get(name, self.default)
            if flag is False:
                instance._refresh_scalar(name)
                return d.get(name, self.default)

        # Classify once (A3): unlinked Defining leaf with no formula/Derivate
        # ancestor can skip owner-chain walks on subsequent reads.
        if (
            instance._link is None
            and instance._formula_driven_ancestor() is None
            and not instance._field_is_derivate(name, self)
            and instance._derivate_source() is None
            and '_pull_owner' not in d
        ):
            if bare_ok is None:
                bare_ok = {}
                d['_scalar_bare_ok'] = bare_ok
            bare_ok[name] = True
            return d.get(name, self.default)

        if bare_ok is None:
            bare_ok = {}
            d['_scalar_bare_ok'] = bare_ok
        bare_ok[name] = False
        instance._refresh_scalar(name)
        return d.get(name, self.default)

    def __set__(self, instance, value):
        dead = _dead_self_or_owner(instance)
        if dead is not None:
            from .entity import _refuse_if_destroyed
            _refuse_if_destroyed(dead, self.name)
        instance._write_field(self.name, value)


_INF = float('inf')


class ScalarAnchor(Container):
    """Graph node for a linked bare-scalar field. Not author-visible.

    Created on first ``obj["field"] @=`` and destroyed on unlink, so unlinked
    scalars have no dependency-graph node.
    """

    _passthrough_update = True
    _scalar_anchor = True

    def __init__(self, parent: Container, field_name: str):
        self._scalar_parent = parent
        self._scalar_name = field_name
        # The slot depends on the parent's class and the name only: look it up
        # once, not on every pull.
        slots = getattr(parent, "_field_slots", None)
        slot = slots().get(field_name) if slots is not None else None
        self._slot = slot
        # -1: not a number slot (a bag field); 0 plain, 1 size, 2 ranged.
        self._slot_kind = slot._kind if isinstance(slot, ScalarSlot) else -1
        self._slot_label = (slot.label or slot.name or "value") if isinstance(slot, ScalarSlot) else field_name
        # A shape heading: a pull on a Defining ``angle`` publishes the pose store.
        self._publishes_rotation = (field_name == "angle"
                                    and type(parent)._publish_angle_input is not None)
        # A Derivate scalar's anchor depends on its owner (S5-2), read by
        # ``_should_use_upward_edge`` while ``super().__init__`` adds the part.
        try:
            self.__dict__['_derivate_field'] = bool(
                isinstance(slot, ScalarSlot) and parent._field_is_derivate(field_name, slot))
        except Exception:
            self.__dict__['_derivate_field'] = False
        super().__init__(owner=parent, attr_name=field_name)

    def _takein_impl(self, new_value) -> bool:
        if new_value.__class__ is not float:        # a pulled float is the common case
            if isinstance(new_value, FieldRef):
                new_value = new_value.value
            if isinstance(new_value, Attribute):
                new_value = new_value.value
            elif isinstance(new_value, Container):
                raise TypeError(
                    f"scalar field {self.name} cannot take a {type(new_value).__name__}; "
                    f"use a lambda that returns a number or string"
                )
        parent = self._scalar_parent
        name = self._scalar_name
        ink = getattr(parent, '_ink', None)
        if isinstance(ink, dict) and name in ink:
            if new_value.__class__ is _KEY_NAME:
                new_value = str(new_value)
            old = ink.get(name)
            if _value_changed(old, new_value):
                ink[name] = new_value
                return True
            return False
        kind = self._slot_kind
        if kind >= 0:
            # A number slot: the Numbers rule as ``=`` applies it, named by the
            # slot (GX14 in Testing Design: a pull took ``True`` as 1, leaked
            # OverflowError for a huge int and said "magnitude").
            if new_value.__class__ is float:
                if not (-_INF < new_value < _INF):
                    raise ValueError(f"{self._slot_label} must be a finite number, got {new_value}")
            elif not (new_value.__class__ is int and -1e308 < new_value < 1e308):
                from .validate import number
                new_value = number(new_value, self._slot_label)
            if kind == 1:
                # A size: negative reads 0.
                from .validate import clamp_magnitude
                new_value = clamp_magnitude(new_value)
            elif kind == 2:
                # The slot's rules, clamping (a link cannot raise mid-frame on a
                # range; NaN / inf raise above, as ``=`` does: D14, D16).
                new_value = _coerce_constrained(self._slot, new_value, True, link=True)
        elif new_value.__class__ is float and not (-_INF < new_value < _INF):
            # ``=`` refuses NaN / inf on a plain field; a link must not store them.
            raise ValueError(f"{name} must be a finite number, got {new_value}")
        d = parent.__dict__
        old = d.get(name)
        if old != new_value:
            if self._publishes_rotation:
                # A Defining heading: the pose store follows, as on ``=``
                # (GR17-link in Testing Design: it lagged a link pull).
                defining = d.get('_defining_part_names')
                if defining and 'angle' in defining:
                    # Converted before the store: a refusal keeps both.
                    object.__setattr__(parent, '_rotation',
                                       new_value if new_value.__class__ is float
                                       else float(new_value))
            d[name] = new_value
            bump_pose_rev(parent)
            # A raw store skips the parent's _update_impl (Reactive Design,
            # "Pull stores raw"): let it keep its computed fields in step.
            sync = parent._sync_computed
            if sync is not None:
                sync()
            return True
        return False

    def _takein(self, new_value):
        if new_value is self:
            return
        if self._takein_impl(new_value):
            if not self._requires_pull_invalidate():
                return
            if not self._in_batch_update:
                self.update()
            elif self._node_id is not None:
                self._scena_system.update_manager.mark_dirty(self)

    def _update_impl(self) -> None:
        pass

    @property
    def value(self):
        self._ensure_fresh()
        parent = self._scalar_parent
        name = self._scalar_name
        ink = getattr(parent, '_ink', None)
        if isinstance(ink, dict) and name in ink:
            return ink.get(name)
        return parent.__dict__.get(name)

    def __repr__(self) -> str:
        return f"<scalar {self.name}>"


class _PropertyAnchor(ScalarAnchor):
    """Graph node for a linked field backed by a real property + method pair
    (e.g. Graphic.angle / rotate_to), not a bare storage cell.

    Unlike ScalarAnchor, ``_takein`` writes through ``setattr(owner, name, value)``
    so the owner's own setter runs (with all its side effects: geometry update,
    _ensure_writable guards, collision-epoch bump) instead of poking __dict__.
    """

    # Its edges are wired by its owner (``_DerivedRotationRoute`` adds the
    # anchor → owner dependency of a derived heading by hand).
    _scalar_anchor = False

    def _takein_impl(self, new_value) -> bool:
        if isinstance(new_value, FieldRef):
            new_value = new_value.value
        if isinstance(new_value, Attribute):
            new_value = new_value.value
        elif isinstance(new_value, Container):
            raise TypeError(
                f"field {self.name} cannot take a {type(new_value).__name__}; "
                f"use a lambda that returns a number"
            )
        if new_value.__class__ is not float:
            # The Numbers rule, as ``=`` applies it: a bool is not a number
            # and an int too big for a float is a ValueError, not Python's
            # OverflowError (review 2026-10-09 S5-3; GX14 for ScalarAnchor).
            from .validate import number
            new_value = float(number(new_value, self._slot_label))
        parent = self._scalar_parent
        name = self._scalar_name
        old = getattr(parent, name)          # real property getter — always live/correct
        if old == new_value:
            return False
        # The link itself is writing: the pose writers' linked-field refusal
        # (entity._refuse_linked_pose) lets this one write through.
        d = self.__dict__
        d["_writing"] = True
        try:
            setattr(parent, name, new_value)     # real property setter — rotate_to / scale_to
        except LinkedAttributeError as exc:
            raise LinkedAttributeError(
                f"{parent.name}['{name}'] @= could not write {name}: {exc}"
            ) from exc
        finally:
            d["_writing"] = False
        return True

    @property
    def value(self):
        self._ensure_fresh()
        return getattr(self._scalar_parent, self._scalar_name)


class _FlagPropertyAnchor(_PropertyAnchor):
    """A ``_PropertyAnchor`` for a property-backed flag (``SpriteButton.enabled``).

    Same write-through contract; the value is a real bool (``0`` / ``1``
    accepted, like every flag), never ``float``.
    """

    def _takein_impl(self, new_value) -> bool:
        if isinstance(new_value, FieldRef):
            new_value = new_value.value
        if isinstance(new_value, Attribute):
            new_value = new_value.value
        from .validate import expect_bool
        parent = self._scalar_parent
        name = self._scalar_name
        new_value = expect_bool(new_value, f"{parent.name}['{name}']")
        if getattr(parent, name) == new_value:
            return False
        # The link's own write passes the setter's linked-field refusal (a
        # plain ``b.enabled = False`` on a linked button raises instead).
        d = self.__dict__
        d["_writing"] = True
        try:
            setattr(parent, name, new_value)
        finally:
            d["_writing"] = False
        return True


_NOT_WRITTEN = object()


class _ChannelAnchor(_PropertyAnchor):
    """A linked appearance field or flag (``color``, ``fill``, ``line``,
    ``line_width``, Text ``background``, Sprite ``alpha``, ``visible``,
    ``flip_x`` / ``flip_y``): a link target only (``_TARGET_ONLY_LINKS``).

    Writes through the property setter, like ``_PropertyAnchor``, so ``@=``
    means ``=`` re-run when the formula's sources change. It compares the new
    value with the one it wrote last, never with the getter: a ``Color`` has
    no value equality, a parked actor's ``visible`` reads ``False``, and a look
    may own the live paint. The first pull after linking always writes.
    """

    def __init__(self, parent: Container, field_name: str):
        super().__init__(parent, field_name)
        self.__dict__["_last_written"] = _NOT_WRITTEN

    def _normalize(self, value):
        return value

    def _same(self, last, value) -> bool:
        return last == value

    def _forget_written(self) -> None:
        """The next pull writes even an unchanged value (resume, a copy verb
        that skipped the field, a look that took the channel)."""
        self.__dict__["_last_written"] = _NOT_WRITTEN

    def _takein_impl(self, new_value) -> bool:
        if isinstance(new_value, FieldRef):
            new_value = new_value.value
        if isinstance(new_value, Attribute):
            new_value = new_value.value
        elif isinstance(new_value, Container):
            raise TypeError(
                f"field {self.name} cannot take a {type(new_value).__name__}; "
                f"use a lambda that returns the value"
            )
        value = self._normalize(new_value)
        d = self.__dict__
        last = d["_last_written"]
        if last is not _NOT_WRITTEN and self._same(last, value):
            return False
        parent = self._scalar_parent
        name = self._scalar_name
        d["_writing"] = True
        try:
            setattr(parent, name, value)
        except LinkedAttributeError as exc:
            raise LinkedAttributeError(
                f"{parent.name}['{name}'] @= could not write {name}: {exc}"
            ) from exc
        finally:
            d["_writing"] = False
        d["_last_written"] = value
        return True


def _pull_channel_links(obj, names) -> None:
    """Pull ``obj``'s linked appearance fields among ``names`` (a getter, the
    draw-head refresh, a look about to apply). The hot callers check the
    ``_alinks`` slot first. Never inside a look apply:
    a link written there would skip the look identity, and ``visual = None``
    would bring the old color back."""
    if getattr(obj, "_in_visual_apply", False):
        return
    anchors = obj.__dict__.get("_field_anchors")
    if not anchors:
        return
    for name in names:
        anchor = anchors.get(name)
        # A clean anchor has nothing to pull (``_resolve_link`` returns on
        # ``_dirty``): skip the call — the draw path reads these getters.
        if anchor is not None and anchor._link is not None and anchor._dirty:
            anchor._ensure_fresh()


def _reapply_channel_links(obj) -> None:
    """Write every linked appearance field of ``obj`` again from its formula,
    even unchanged: a copy verb (``look_like`` / ``restore_visual``) or an
    engine write (park) put another value under it."""
    anchors = obj.__dict__.get("_field_anchors")
    if not anchors:
        return
    for name in type(obj)._scena_target_only:
        anchor = anchors.get(name)
        if anchor is not None and anchor._link is not None and not anchor._resolving:
            anchor._forget_written()
            ss = getattr(anchor, "_scena_system", None)
            if ss is not None:
                ss.update_manager.mark_dirty(anchor)
            anchor._ensure_fresh()


_PAINT_TYPES = None


def _paint_types():
    """(Color, _coerce_channel_paint), imported once (``color`` / ``style``
    import this module)."""
    global _PAINT_TYPES
    if _PAINT_TYPES is None:
        from .color import Color
        from .style import _coerce_channel_paint
        _PAINT_TYPES = (Color, _coerce_channel_paint)
    return _PAINT_TYPES


class _PaintChannelAnchor(_ChannelAnchor):
    """``color`` / ``fill`` / ``line`` / Text ``background``: a paint material.

    The value is coerced as ``=`` coerces it (a name, hex, tuple → ``Color``;
    a ``Gradient`` / ``Texture`` / procedural fill passes through), so a
    formula returning ``"red"`` every pull writes once. A ``Color`` compares
    by its RGBA (alpha counts); any other material by identity.
    """

    def _normalize(self, value):
        value = as_payload(value)
        if value is None:
            return None
        Color, coerce = _paint_types()
        if value.__class__ is Color:
            return value            # immutable: the setter takes it as it is
        if self._scalar_name == "background":
            return Color(value)
        return coerce(value)

    def _same(self, last, value) -> bool:
        if last is value:
            return True
        Color = _paint_types()[0]
        if last.__class__ is Color and value.__class__ is Color:
            return bool(last) == bool(value) and last.rgb == value.rgb
        return False


class _AmountChannelAnchor(_ChannelAnchor):
    """``line_width`` (a size: negative reads 0) and Sprite ``alpha`` (an
    amount: clamped to [0, 1]). A formula result follows the formula rule —
    it clamps instead of raising mid-frame; NaN / inf and non-numbers raise."""

    def _normalize(self, value):
        from .validate import number
        parent = self._scalar_parent
        n = number(value, f"{parent.name}['{self._scalar_name}']")
        if n < 0.0:
            return 0.0
        if self._scalar_name == "alpha" and n > 1.0:
            return 1.0
        return n


class _FlagChannelAnchor(_ChannelAnchor):
    """``visible`` / ``flip_x`` / ``flip_y``: a real bool (``0`` / ``1`` read
    as a flag, like every flag)."""

    def _normalize(self, value):
        from .validate import expect_bool
        return expect_bool(value, f"{self._scalar_parent.name}['{self._scalar_name}']")


# A value type a cell holds by value (``scenamath`` sets it to ``Vec2``). Since
# 0.8.0 ``st.pos`` is the held Vec2 itself, so ``st.pos.x = 5`` changes the
# payload in place: its ``update()`` hook tells the cell (``_HeldPayloadUpdate``),
# as ``st.pos += v`` does. The Vec2 a cell holds also gets a per-instance
# ``_write_field`` / ``_refuse_author_write`` (``_HeldPayloadWrite``) that
# refuses every in-place write while the cell is linked (the payload is the
# formula's output) and marks the vector for ``held_cell``; other Vec2s pay
# nothing. Both are removed when the cell takes another value.
_HELD_BY_VALUE: Optional[type] = None


class _HeldPayloadWrite:
    """``_write_field`` of a Vec2 held by a cell (weak refs: no cycle)."""

    __slots__ = ("cell", "payload")

    def __init__(self, cell: "Attribute", payload) -> None:
        self.cell = weakref.ref(cell)
        self.payload = weakref.ref(payload)

    def __call__(self, name: str, value) -> None:
        p = self.payload()
        cell = self.cell()
        if (cell is not None and cell.__dict__.get('_link') is not None
                and not p._in_batch_update
                and cell.__dict__.get('_raw_value') is p):
            cell._refuse_author_write()
        type(p)._write_field(p, name, value)

    def refuse(self) -> None:
        """``_refuse_author_write`` of the payload: its own links, then the
        cell's (``st.pos += v`` / ``<<`` / ``do_rotation`` on a linked cell
        would change the formula's output and nothing would hear it)."""
        p = self.payload()
        type(p)._refuse_author_write(p)
        cell = self.cell()
        if (cell is not None and cell.__dict__.get('_link') is not None
                and cell.__dict__.get('_raw_value') is p):
            cell._refuse_author_write()


def held_cell(obj) -> Optional["Attribute"]:
    """The cell that holds ``obj`` by value right now (``st.pos``'s Vec2), or None.

    ``st.pos`` reads that Vec2 (0.8.0). A door that needs the cell (``@=`` on
    either side, ``tween``, ``until``) would take the payload instead and work
    until the next ``st.pos = …`` replaced it: the doors refuse it through
    ``refuse_held_payload``.
    """
    if obj.__class__ is not _HELD_BY_VALUE:
        return None
    guard = obj.__dict__.get('_write_field')
    if not isinstance(guard, _HeldPayloadWrite):
        return None
    cell = guard.cell()
    if cell is None or cell.__dict__.get('_raw_value') is not obj:
        return None
    return cell


def refuse_held_payload(obj, call: str) -> None:
    """Raise when ``obj`` is a Vec2 a cell holds. ``call`` spells the door with
    ``{cell}`` where the cell goes, e.g. ``"tween({cell}, …)"``."""
    cell = held_cell(obj)
    if cell is None:
        return
    who = cell._name
    owner, _, key = who.rpartition(".")
    bracket = f'{owner}["{key}"]' if owner else who
    raise TypeError(
        f"{call.format(cell=who)} takes the {type(obj).__name__} that {who} "
        f"holds now, not the cell: the next {who} = … would leave it behind. "
        f"Pass the cell with brackets: {call.format(cell=bracket)}. {who} reads "
        f"the value (since 0.8.0); {bracket} is the cell."
    )


def _rehold_payload(cell: "Attribute", old, new) -> None:
    """Move the held-payload hooks from ``old`` to ``new`` (either may be a Vec2)."""
    if old.__class__ is _HELD_BY_VALUE:
        guard = old.__dict__.get('_write_field')
        if isinstance(guard, _HeldPayloadWrite) and guard.cell() is cell:
            del old.__dict__['_write_field']
            del old.__dict__['_refuse_author_write']
        _unhold_payload(old, cell, None)
    if new.__class__ is _HELD_BY_VALUE:
        guard = _HeldPayloadWrite(cell, new)
        new.__dict__['_write_field'] = guard
        new.__dict__['_refuse_author_write'] = guard.refuse
        _hold_payload(new, cell, None)


# Every in-place change of a Vec2 ends in its ``update()``: ``<<`` (``_takein``),
# ``+=`` / ``-=`` / ``do_rotation`` (the batch's exit), and ``v.x = …`` once the
# vector's ownership root has ``_needs_pull_invalidate``. A held Vec2 (an st
# cell's payload, or the value of an Entity ink field a formula reads) gets a
# per-instance ``update`` that runs the class's and then tells its holders, so
# other Vec2s pay nothing. A holder is ``(cell, None)`` or ``(host, name)``.
class _HeldPayloadUpdate:
    """``update`` of a held Vec2 (weak refs: no cycle)."""

    __slots__ = ("payload", "holders", "flagged", "edges")

    def __init__(self, payload) -> None:
        self.payload = weakref.ref(payload)
        self.holders: list = []
        self.flagged = False        # this hook set the vector's own pull flag
        self.edges = None           # ``(dependent_id, dependency_id)`` it added (VB3)

    def __call__(self) -> None:
        p = self.payload()
        if p._in_batch_update:
            return                  # the batch's exit calls again
        d = p.__dict__
        if d['_node_id'] is None and d['_owner'] is None and d.get('_link') is None:
            # Off the graph, nothing reads it there: what ``update()`` would do
            # is store length / angle (``_update_impl``); bring in step only
            # the ones it has (a later read computes the others).
            p._sync_computed()
        else:
            type(p).update(p)
        holders = self.holders
        if len(holders) == 1 and holders[0][1] is None:
            # The common case inline: one st cell (``st.pos += v``).
            cell = holders[0][0]()
            if cell is not None:
                d = cell.__dict__
                if d['_raw_value'] is p and d['_link'] is None:
                    cell._changed_in_place()
            return
        self.changed(p)

    def link_changed(self, p) -> None:
        """A link on ``p`` (whole, or one axis) was installed: depend, and notify."""
        self.sync_link_edges(p)
        self.changed(p)

    def sync_link_edges(self, p) -> None:
        """While ``p`` is linked (the whole vector, or an axis), each ink field
        holding it depends on the link's node in the graph, so a later pull's
        source change dirties the formulas that read the field. A pull stores
        raw and calls no ``update()``, so this hook never ran for it: after
        ``ship.aim @= f`` a formula reading ``ship.aim`` kept the value at link
        time (VB3). Only linked held vectors get edges: an unlinked one tells
        its holders from ``update()``, and a field write re-points nothing."""
        d = p.__dict__
        want = set()
        if d.get('_link') is not None or d.get('_field_anchors'):
            links = []
            if d.get('_link') is not None and d.get('_node_id') is not None:
                links.append(d['_node_id'])
            for a in (d.get('_field_anchors') or {}).values():
                ad = a.__dict__
                if ad.get('_link') is not None and ad.get('_node_id') is not None:
                    links.append(ad['_node_id'])
            for ref, name in (self.holders if links else ()):
                holder = ref()
                if holder is None or name is None:
                    continue
                anchors = holder.__dict__.get('_field_anchors')
                anchor = anchors.get(name) if anchors else None
                aid = anchor.__dict__.get('_node_id') if anchor is not None else None
                if aid is not None:
                    want.update((aid, lid) for lid in links)
        have = self.edges or set()
        if want == have:
            return
        graph = p._scena_system.update_manager.graph
        for dependent, dependency in have - want:
            graph.remove_dependency(dependent, dependency)
        added = set(have & want)
        for dependent, dependency in want - have:
            if dependency in graph.dependencies[dependent]:
                continue        # already an edge the graph made: not ours to remove
            if graph.can_reach(dependency, dependent):
                continue        # the link reads the field: no cycle
            graph.add_dependency(dependent, dependency)
            added.add((dependent, dependency))
        self.edges = added or None

    def changed(self, p) -> None:
        """``p`` changed in place: notify each holder that holds it now."""
        # ``_unhold_payload`` replaces the list (never edits it): a holder
        # dropped by a callback this notify runs does not upset the loop.
        for ref, name in self.holders:
            holder = ref()
            if holder is None:
                continue
            if name is None:
                # An st cell. A linked cell's payload is its formula's output.
                d = holder.__dict__
                if d['_raw_value'] is p and d['_link'] is None:
                    holder._changed_in_place()
                continue
            ink = getattr(holder, '_ink', None)
            if not isinstance(ink, dict) or ink.get(name) is not p:
                continue
            anchors = holder.__dict__.get('_field_anchors')
            anchor = anchors.get(name) if anchors else None
            if anchor is not None and anchor._link is None:
                _notify_ink_anchor(holder, anchor)


def _hold_payload(payload, holder, name) -> None:
    """``holder`` (a cell, or an Entity with ink field ``name``) holds ``payload``."""
    d = payload.__dict__
    hook = d.get('_held_payload')
    if hook is None:
        hook = _HeldPayloadUpdate(payload)
        d['_held_payload'] = hook
        d['update'] = hook
    for ref, n in hook.holders:
        if n == name and ref() is holder:
            return
    hook.holders.append((weakref.ref(holder), name))
    if name is not None and (d.get('_link') is not None or d.get('_field_anchors')):
        hook.sync_link_edges(payload)       # a linked vector put in a field (VB3)
    # ``v.x = …`` calls ``update()`` only under a pull flag (A2): set it, so
    # ``st.pos.x = 5`` / ``ship.aim.x = 5`` reach the hook. A cell's payload
    # has no owner (a cell holds a Vec2 by value).
    root = payload if d['_owner'] is None else payload._ownership_root()
    if not getattr(root, '_needs_pull_invalidate', False):
        root._needs_pull_invalidate = True
        hook.flagged = root is payload


def _unhold_payload(payload, holder, name) -> None:
    """``holder`` no longer holds ``payload``; the last one removes the hook."""
    d = payload.__dict__
    hook = d.get('_held_payload')
    if hook is None:
        return
    holders = hook.holders
    if len(holders) != 1 or holders[0][1] != name or holders[0][0]() is not holder:
        hook.holders = [(ref, n) for ref, n in holders
                        if not (n == name and ref() is holder) and ref() is not None]
        if hook.holders:
            if hook.edges:
                hook.sync_link_edges(payload)
            return
    if hook.edges:
        hook.holders = []
        hook.sync_link_edges(payload)
    del d['_held_payload']
    if d.get('update') is hook:
        del d['update']
    if (hook.flagged and d.get('_link') is None and d.get('_node_id') is None
            and '_link_source' not in d):
        # Back to a plain free vector: its ``v.x = …`` skips ``update()`` again.
        payload._needs_pull_invalidate = False


def _notify_ink_anchor(host, anchor) -> None:
    """Dirty what reads the ink field behind ``anchor``, as an ink ``=`` does."""
    if not host._in_batch_update:
        anchor.update()
    elif anchor._node_id is not None:
        host._scena_system.update_manager.mark_dirty(anchor)


def _hold_ink_value(host, name, old, new) -> None:
    """Ink field ``name`` of ``host`` (a formula reads it) went from ``old`` to ``new``."""
    if old.__class__ is _HELD_BY_VALUE:
        _unhold_payload(old, host, name)
    if new.__class__ is _HELD_BY_VALUE:
        _hold_payload(new, host, name)


class Attribute(ClosedSurface, Container):  # Use string literal for forward reference
    """It is a unified attribute class that behaves according to its value type.

    A closed surface: ``cell.x = 5`` (the cell holding a Vec2) raises — the
    write would land on the cell, not on the Vec2. ``cell.value.x = 5`` (or
    ``st.pos.x = 5``, which reads the held Vec2) changes the Vec2 and tells
    what is linked to the cell.

    Args:
        initial: Starting value (default 0.0).
    """

    __setattr__ = make_closed_setattr(("value",))

    # Empty _update_impl — dirty visits only need to fan out to dependents.
    _passthrough_update = True

    def __init__(self, initial=0.0, owner=None, attr_name=None):
        self._raw_value = None
        self._link = None
        super().__init__(owner, attr_name)  # Initialize Container

        # Set initial value (using value setter)
        with self._no_update():
            self.value = initial

    import inspect as _inspect
    __signature__ = _inspect.Signature([
        _inspect.Parameter("initial", _inspect.Parameter.POSITIONAL_OR_KEYWORD, default=0.0),
    ])

    @property
    def value(self):
        """Get the attribute's value (pull-resolves if dirty).

        Hot path: cached A3 bare leaves return ``_raw_value`` without entering
        ``_ensure_fresh`` (no owner-chain walks).
        """
        if self.__dict__.get('_bare_ok') is True and self._link is None:
            return self._raw_value
        self._ensure_fresh()
        return self._raw_value

    @value.setter
    def value(self, new_value):
        # Set the value
        self._assign_value(new_value)

    # Attribute uses Container's update() method - no override needed
    # Attribute can't have parts, so it doesn't need _update_impl() - only formula updates
    def _update_impl(self) -> None:
        """Attribute doesn't have parts, so no structural updates needed."""
        pass

    def _takein(self, new_value):
        """
        Take in a new value.
        This method is called when a new value is assigned to the attribute.
        Overrides Container._takein() to only update if value actually changed (performance optimization).
        """
        if new_value is self:
            return

        if self._takein_impl(new_value):
            if not self._requires_pull_invalidate():
                self._scena_system.update_manager.maybe_poll_events()
                return
            # Only update if value changed and not in batch update mode
            if not self._in_batch_update:
                self.update()
            elif self._node_id is not None:
                # Batched writes must still invalidate dependents so a later
                # flush / read sees the change.
                self._scena_system.update_manager.mark_dirty(self)

    def _takein_impl(self, new_value: Any) -> bool:
        """Set the attribute's value.
        
        Returns:
            True if value changed, False otherwise.
        """
        # Unpack a boxed cell or a bracket handle so the stored payload is bare.
        if isinstance(new_value, FieldRef):
            new_value = new_value.value
        if isinstance(new_value, Attribute):
            new_value = new_value.value

        # Only update if validation was successful and value changed. ``True ==
        # 1.0``: a flag and a number differ (a cell holding ``True`` kept it
        # through ``= 1.0``, so a link it fed stayed refused).
        if new_value.__class__ is _KEY_NAME:
            new_value = str(new_value)
        old_value = self._raw_value
        try:
            changed = (old_value != new_value
                       or (type(old_value) is bool) is not (type(new_value) is bool))
        except KeyNameMismatch:     # a key nested in a tuple / list / dict
            changed = True
        if changed:
            if old_value.__class__ is _HELD_BY_VALUE or new_value.__class__ is _HELD_BY_VALUE:
                # A cell holds a Vec2 by value: an object's own Vec2 (``st.v0 =
                # ball.vel``) is copied, or the cell would follow the object's
                # field and its hooks would sit on it (RA3: the old guard
                # refused the field's next write, ``ball.vel = …``).
                # So is one another holder holds (VB2): ``st.start = st.pos``
                # shared the vector, so the saved start moved with ``st.pos``
                # and the guard left ``st.pos`` when ``st.start`` changed; and
                # one an ink field took (``_ink_held``, sticky, set where ink
                # stores a Vec2): ``st.v0 = ship.aim`` put the guard on the
                # field's vector, as RA3 did on ``ball.vel``.
                # A linked one too (``v["y"] @= f; st.pos = v``): its pulls are
                # raw stores the cell never hears, and a cell refuses a link on
                # its payload (``st.pos @= f``), so it takes the value now.
                if new_value.__class__ is _HELD_BY_VALUE:
                    nd = new_value.__dict__
                    anchors = nd.get('_field_anchors')
                    if (nd.get('_owner') is not None or '_held_payload' in nd
                            or '_ink_held' in nd or nd.get('_link') is not None
                            or (anchors and any(a._link is not None
                                                for a in anchors.values()))):
                        new_value = _HELD_BY_VALUE(new_value.x, new_value.y)
                self._raw_value = new_value
                _rehold_payload(self, old_value, new_value)
            else:
                self._raw_value = new_value
            return True
        else:
            return False

    def _changed_in_place(self) -> None:
        """The held object changed in place and was assigned back
        (``st.pos += v``): notify as a changed write does (``_takein``)."""
        self._refuse_author_write()
        if not self._requires_pull_invalidate():
            self._scena_system.update_manager.maybe_poll_events()
            return
        if not self._in_batch_update:
            self.update()
        elif self._node_id is not None:
            self._scena_system.update_manager.mark_dirty(self)

    def _takein_float(self, f: float) -> bool:
        """Pose A1 write: float only, no Attribute unpack, no graph.

        Same dirty-skip as ``_takein`` (caller does not call ``update()``).
        """
        old = self._raw_value
        if old != f:
            self._raw_value = f
            return True
        return False

    # Value __eq__; mutable cell — not a dict/set key.
    __hash__ = None

    # Comparison operators
    def __eq__(self, other):
        if other is self:
            return True
        if isinstance(other, Attribute):
            return self.value == other.value
        return self.value == other
    
    def __lt__(self, other):
        if isinstance(other, Attribute):
            return self.value < other.value
        return self.value < other
    
    def __le__(self, other):
        if isinstance(other, Attribute):
            return self.value <= other.value
        return self.value <= other
    
    def __gt__(self, other):
        if isinstance(other, Attribute):
            return self.value > other.value
        return self.value > other
    
    def __ge__(self, other):
        if isinstance(other, Attribute):
            return self.value >= other.value
        return self.value >= other
    
    # Numeric conversion methods
    def __float__(self):
        return float(self.value)

    def __complex__(self):
        return complex(self.value)

    def __int__(self):
        return int(self.value)
        
    def __index__(self):
        try:
            return int(self.value)
        except (TypeError, ValueError):
            raise TypeError(f"'{type(self.value).__name__}' object cannot be interpreted as an integer")

    # round() / math.trunc / math.floor / math.ceil act on the payload, so the
    # result (int, or float with ndigits) is the payload's own.
    def __round__(self, ndigits=None):
        if isinstance(ndigits, Attribute):
            ndigits = ndigits.value
        if ndigits is None:
            return round(self.value)
        return round(self.value, ndigits)

    def __trunc__(self):
        return math.trunc(self.value)

    def __floor__(self):
        return math.floor(self.value)

    def __ceil__(self):
        return math.ceil(self.value)

    # Arithmetic operators: each reads the payload and returns a plain value
    # (never a cell). ``st.x **= 2`` needs no __ipow__: Python falls back to
    # ``st.x = st.x ** 2``, which takes the number into the same cell.
    def __add__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value + other.value
            return self.value + other
        except TypeError:
            return NotImplemented
        
    def __radd__(self, other):
        try:
            return other + self.value
        except TypeError:
            return NotImplemented
    
    def __sub__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value - other.value
            return self.value - other
        except TypeError:
            return NotImplemented
        
    def __rsub__(self, other):
        try:
            return other - self.value
        except TypeError:
            return NotImplemented
    
    def __mul__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value * other.value
            return self.value * other
        except TypeError:
            return NotImplemented
        
    def __rmul__(self, other):
        try:
            return other * self.value
        except TypeError:
            return NotImplemented
    
    def __truediv__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value / other.value
            return self.value / other
        except TypeError:
            return NotImplemented
        
    def __rtruediv__(self, other):
        try:
            return other / self.value
        except TypeError:
            return NotImplemented

    def __floordiv__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value // other.value
            return self.value // other
        except TypeError:
            return NotImplemented

    def __rfloordiv__(self, other):
        try:
            return other // self.value
        except TypeError:
            return NotImplemented

    def __mod__(self, other):
        try:
            if isinstance(other, Attribute):
                return self.value % other.value
            return self.value % other
        except TypeError:
            return NotImplemented

    def __rmod__(self, other):
        try:
            return other % self.value
        except TypeError:
            return NotImplemented

    def __divmod__(self, other):
        try:
            if isinstance(other, Attribute):
                return divmod(self.value, other.value)
            return divmod(self.value, other)
        except TypeError:
            return NotImplemented

    def __rdivmod__(self, other):
        try:
            return divmod(other, self.value)
        except TypeError:
            return NotImplemented

    def __pow__(self, other, modulo=None):
        if isinstance(other, Attribute):
            other = other.value
        if isinstance(modulo, Attribute):
            modulo = modulo.value
        try:
            if modulo is None:
                return self.value ** other
            return pow(self.value, other, modulo)
        except TypeError:
            return NotImplemented

    def __rpow__(self, other, modulo=None):
        try:
            if modulo is None:
                return other ** self.value
            return pow(other, self.value, modulo)
        except TypeError:
            return NotImplemented

    # No << / >>: Container.__lshift__ is takein (``cell << 3`` writes 3), so a
    # shift on a cell would give the same spelling a second meaning. No @: in
    # Scena it reads as a link (``@=``).

    # Unary operators
    def __neg__(self):
        try:
            return -self.value
        except TypeError:
            raise TypeError(f"bad operand type for unary -: '{type(self.value).__name__}'")
        
    def __pos__(self):
        try:
            return +self.value
        except TypeError:
            raise TypeError(f"bad operand type for unary +: '{type(self.value).__name__}'")
        
    def __abs__(self):
        try:
            return abs(self.value)
        except TypeError:
            raise TypeError(f"bad operand type for abs(): '{type(self.value).__name__}'")
    
    # Container methods (for strings, lists, etc.)
    def __len__(self):
        try:
            if isinstance(self.value, (int, float)):
                return len(str(self.value))
            return len(self.value)
        except TypeError:
            raise TypeError(f"object of type '{type(self.value).__name__}' has no len()")
    
    def __contains__(self, item):
        try:
            return item in self.value
        except TypeError:
            raise TypeError(f"argument of type '{type(self.value).__name__}' is not iterable")
    
    def __getitem__(self, key):
        try:
            return self.value[key]
        except TypeError:
            raise TypeError(f"'{type(self.value).__name__}' object is not subscriptable")
    
    # String representation
    def __str__(self):
        return str(self.value)

    def __format__(self, format_spec: str) -> str:
        """Format the payload so ``f"{st.score:.1f}"`` works on boxed cells."""
        return format(self.value, format_spec)
        
    def __repr__(self):
        return f"Attribute({repr(self.value)})"
    
    # Boolean operations
    def __bool__(self):
        """Return the boolean value of the attribute."""
        try:
            return bool(self.value)
        except TypeError:
            raise TypeError(f"'{type(self.value).__name__}' object cannot be interpreted as a boolean")
    
    def __and__(self, other):
        """Bitwise AND operation."""
        try:
            if isinstance(other, Attribute):
                return self.value & other.value
            return self.value & other
        except TypeError:
            return NotImplemented
    
    def __rand__(self, other):
        """Reversed bitwise AND operation."""
        try:
            return other & self.value
        except TypeError:
            return NotImplemented
    
    def __or__(self, other):
        """Bitwise OR operation."""
        try:
            if isinstance(other, Attribute):
                return self.value | other.value
            return self.value | other
        except TypeError:
            return NotImplemented
    
    def __ror__(self, other):
        """Reversed bitwise OR operation."""
        try:
            return other | self.value
        except TypeError:
            return NotImplemented
    
    def __xor__(self, other):
        """Bitwise XOR operation."""
        try:
            if isinstance(other, Attribute):
                return self.value ^ other.value
            return self.value ^ other
        except TypeError:
            return NotImplemented
    
    def __rxor__(self, other):
        """Reversed bitwise XOR operation."""
        try:
            return other ^ self.value
        except TypeError:
            return NotImplemented
    
    def __invert__(self):
        """Bitwise NOT operation."""
        try:
            return ~self.value
        except TypeError:
            raise TypeError(f"bad operand type for unary ~: '{type(self.value).__name__}'")

    # Method delegation for non-special methods
    def _closed_hint(self, name: str) -> Optional[str]:
        """A write the payload has, on the cell object (``cell.x = 5``): it
        would land on the cell, not on what it holds. ``st.pos.x = 5`` never
        gets here: ``st.pos`` reads the held Vec2 (0.8.0)."""
        raw = self.__dict__.get("_raw_value")
        if raw is None or isinstance(raw, Attribute) or not hasattr(raw, name):
            return None
        who = self._name
        kind = type(raw).__name__
        return (
            f"{who}.{name} = ... would land on the cell, not on the {kind} it "
            f"holds. Write into the value: {who}.value.{name} = ..."
        )

    def __getattr__(self, name):
        """Delegate attribute access to the underlying value.

        Uses ``_raw_value`` (not ``.value``) so lookup during init / pull
        resolve cannot recurse through ``_ensure_fresh``.
        """
        raw = object.__getattribute__(self, '_raw_value')
        if hasattr(raw, name):
            attr = getattr(raw, name)
            if callable(attr):
                def wrapper(*args, **kwargs):
                    return attr(*args, **kwargs)
                return wrapper
            return attr
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


def as_payload(obj):
    """O(1): Attribute → ``.value``; otherwise return ``obj`` unchanged."""
    return obj.value if isinstance(obj, Attribute) else obj


def as_payload_all(*values):
    """O(1) per item: Attribute → ``.value`` for each of ``values``."""
    return tuple(as_payload(v) for v in values)


def bound_cell(handle):
    """The cell a binding argument names, or ``None`` when it names none.

    ``st["volume"]`` (a FieldRef on a State) → that cell; a missing cell
    raises the State's "has no cell … Create it first" error. A standalone
    ``Attribute`` (``Attribute(0)``, ``slider.data``) → itself. Anything else
    → ``None``: a plain value, including ``st.volume``, which reads the value
    (0.8.0). Widgets, ``Text`` and ``SpriteButton(label=)`` bind through this.
    """
    if isinstance(handle, Attribute):
        return handle
    if isinstance(handle, FieldRef) and isinstance(handle.owner, State):
        return handle.owner._resolve_cell(handle.name)
    return None


def unbound_value_hint(call: str, value, example: str = "volume") -> str:
    """Error tail for a plain value where a cell was expected.

    ``call`` is the spelling with the example cell, e.g.
    ``Slider(st["volume"])``; ``example`` is that cell's name.
    """
    if isinstance(value, FieldRef):
        return (f"got the field {value!r}: only a State cell binds here "
                f"({call}). For an object's field, link instead: "
                f"lambda: obj.field.")
    return (f"got {type(value).__name__} {value!r:.40}. Pass the cell with "
            f"brackets: {call}. st.{example} reads the value (since 0.8.0); "
            f"st[\"{example}\"] is the cell.")


_VALUE_TYPES = (float, int, str, bool, tuple, type(None))
_VALUE_TYPE_SET = frozenset(_VALUE_TYPES)     # one hash probe (the ink write)


# ``input`` sets it to ``KeyName``, the ``str`` an ``on_key_*`` handler
# receives. Its ``==`` is loud (``key == "ESCAPE"`` raises with the fix), which
# helps in the handler and nowhere else: a field stores the key as a plain
# ``str`` (``st.nome = key``, ``t.text = key``), so a later change check or an
# author compare (``st.nome != "nenhuma"``) is an ordinary ``str`` compare
# (IN2 in Testing Design).
_KEY_NAME: Optional[type] = None


class KeyNameMismatch(ValueError):
    """A ``KeyName`` compared with a string ``on_key_*`` can never deliver.

    Raised only when the strings differ, so a change check that meets it —
    a key nested in a tuple, list or dict, which the field does not unwrap —
    reads it as "changed" instead of crashing the write.
    """


def _value_changed(old, new) -> bool:
    """Should a field store ``new`` over ``old``? Immutable values compare by
    value (a repeated ``ship.pos = (1, 2)`` notifies nothing); anything else —
    a list, a Vec2, a numpy array, an object — is stored when it is a new
    object (graphics review E7: ``!=`` kept the old list, and a numpy array
    raised in the comparison)."""
    if old is new:
        return False
    if type(new) in _VALUE_TYPES and type(old) in _VALUE_TYPES:
        # ``True == 1.0``: a flag and a number are different values, or a cell
        # holding ``True`` kept it through ``= 1.0`` (and a link refused on).
        try:
            return old != new or (type(old) is bool) is not (type(new) is bool)
        except KeyNameMismatch:     # a key nested in a tuple met an ordinary string
            return True
    return True


def _coerce_magnitude_slot(slot, value, *, clamp: bool, owner=None):
    """The one coercion for a ScalarSlot write: author ``=`` (``clamp=False``),
    a batch / formula refresh (``clamp=True``) and the constructor
    (``_init_scalar``). The link pull shares the constrained branch
    (``_coerce_constrained(link=True)``). The rules live on the slot
    (``magnitude``, ``minimum`` / ``maximum``, ``out_of_range``, ``label``),
    not in per-class ``_write_field`` overrides that only one path ran.

    An author ``=`` of a callable onto a scalar slot raises
    :class:`CallableAssignError` (``=`` copies; ``@=`` links).
    """
    if not clamp and callable(value) and not isinstance(value, type):
        what = slot.name if isinstance(slot, ScalarSlot) else "value"
        raise CallableAssignError(callable_assign_message(owner, what))
    if not isinstance(slot, ScalarSlot):
        return value
    kind = slot._kind
    if kind == 0:
        if clamp:
            return value
        t = type(value)
        if (t is float and math.isfinite(value)) or (t is int and -1e308 < value < 1e308):
            return value
        from .validate import finite
        return finite(value, slot.label or slot.name or "value")
    if kind == 1:
        # A size with no range: same result as magnitude() / clamp_magnitude(),
        # without the extra call (per-frame tweens of radius / width).
        if clamp:
            from .validate import clamp_magnitude
            return clamp_magnitude(value)
        if type(value) is float and 0.0 <= value < _INF and (value > 0.0 or not slot.positive):
            return value
        from .validate import magnitude
        return magnitude(value, slot.label or slot.name or "value",
                         positive=slot.positive, hint=slot.hint)
    return _coerce_constrained(slot, value, clamp)


def _coerce_constrained(slot, value, clamp: bool, *, link: bool = False):
    """Size and range rules of a slot that has some (not ``slot._plain``).

    Author write: a negative size or a value past the range raises (or clamps,
    ``out_of_range="clamp"``). Batch refresh and link pull: clamp. NaN / inf
    raise on an author write and on a link pull, never silently stored.
    """
    what = slot.label or slot.name or "value"
    if slot.magnitude:
        from .validate import clamp_magnitude, magnitude
        if clamp:
            value = clamp_magnitude(value)
        else:
            value = magnitude(value, what, positive=slot.positive, hint=slot.hint)
    elif not clamp:
        from .validate import finite
        value = finite(value, what)
    elif link and value.__class__ is float and not (-_INF < value < _INF):
        raise ValueError(f"{what} must be a finite number, got {value}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    hi = slot.maximum
    lo = slot.minimum
    soft = clamp or slot.out_of_range == "clamp"
    if hi is not None and (value > hi or (value == hi and slot.maximum_open)):
        if slot.maximum_open:
            if not soft:
                raise ValueError(f"{what} must be < {hi:g}, got {float(value)}")
            value = math.nextafter(float(hi), -_INF)
        else:
            if not soft:
                raise ValueError(f"{what} must be <= {hi:g}, got {float(value)}")
            value = float(hi)
    if lo is not None and value < lo:
        if not soft:
            raise ValueError(f"{what} must be >= {lo:g}, got {float(value)}")
        value = float(lo)
    return value


def _refuse_link_on_dead(container, action: str) -> None:
    """A link is a write: refuse it when ``container`` or an owner above it is
    a destroyed actor (W2 — the link put the dead actor back in the graph).
    Also refuses a part the engine writes (``Graphic.vel``: ``_link_refused``
    holds the property name). ``ship.vel @= f`` reaches here through the
    owned Vec2's ``__imatmul__`` — the setter sees the result too late.
    Living owners pay two dict lookups per level (links are installed rarely)."""
    node = container
    for _ in range(8):   # owner chains are shallow (actor → part → axis)
        if node is None:
            return
        d = getattr(node, "__dict__", None)
        if d is not None and (d.get("_destroyed", False) or d.get("_host_destroyed", False)):
            from .entity import _destroyed_access_message
            raise DestroyedError(_destroyed_access_message(node, action))
        refused = d.get("_link_refused") if d is not None else None
        if refused is not None:
            from .entity import _ink_link_forbidden_message
            raise AttributeError(_ink_link_forbidden_message(d["_owner"], refused))
        node = d.get("_owner") if d is not None else None


def _notify_source_anchors(node, names=None) -> None:
    """A raw store wrote fields of ``node``: dirty their field anchors, as
    ``_write_field`` does for ``=``. A link that reads ``node[name]`` (a
    FieldRef source) followed only ``=`` before (review 2026-10-09 S5-1).
    Write dispatchers only, never a pull (pulls store raw)."""
    anchors = node.__dict__.get('_field_anchors')
    if not anchors:
        return
    um = node._scena_system.update_manager
    for name, anchor in list(anchors.items()):
        if names is not None and name not in names:
            continue
        if anchor._node_id is not None and anchor.__dict__.get('_link') is None:
            um.mark_dirty(anchor)


def _init_scalar(owner, name, value) -> None:
    """Construction-time scalar: callable → link; bare value → copy."""
    if callable(value) and not isinstance(value, type):
        owner._link_field(name, value)
        return
    if isinstance(value, Attribute):
        value = value.value
    slots = getattr(type(owner), "_field_slots", None)
    slot = None
    if callable(slots):
        slot = owner._field_slots().get(name)
    elif hasattr(owner, "_field_slots"):
        try:
            slot = owner._field_slots().get(name)
        except Exception:
            slot = None
    if isinstance(slot, ScalarSlot):
        # Same rules as ``=`` (a NaN angle used to be stored here silently);
        # an ordinary number skips the call (every constructor runs this).
        t = type(value)
        kind = slot._kind
        if not ((kind == 0 and ((t is int and -1e308 < value < 1e308) or (t is float and math.isfinite(value))))
                or (kind == 1 and t is float and 0.0 <= value < _INF
                    and (value > 0.0 or not slot.positive))):
            value = _coerce_magnitude_slot(slot, value, clamp=False, owner=owner)
    elif not isinstance(value, (int, float)) or isinstance(value, bool):
        from .validate import finite
        value = finite(value, name)
    owner.__dict__[name] = float(value)


def _init_composite(field, value) -> None:
    """Construction-time composite: callable → link; bare value → copy.

    For a 2-sequence of coordinates (Point/Vec2), each component follows the
    same scalar rule: callable links that leaf, bare values copy.
    """
    if callable(value) and not isinstance(value, type):
        field._assign_formula(value)
        return
    if isinstance(value, (tuple, list)) and len(value) == 2:
        # Point / Vec2 construction from (x, y) — per-component dispatch.
        with field._batch_update():
            _init_scalar(field, 'x', value[0])
            _init_scalar(field, 'y', value[1])
        return
    field._takein(value)


# ==========================

class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected in the formula graph"""
    pass


def _events_pending_poll() -> bool:
    """True when a non-deferred ``mark_dirty`` should poll ``@when`` / ``@on_change``.

    Not called while ``UpdateManager.deferring`` is set (the frame loop).
    """
    from .events import has_registered_events
    return has_registered_events()


class DependencyGraph:
    """Manages the dependency graph and topological ordering.

    When ``_graph_gc_backstop`` is on, ``nodes`` is a
    ``weakref.WeakValueDictionary`` so unreachable Containers drop out of
    the graph. Iterate only via this dict's public protocol
    (``for x in self.nodes``, ``list(self.nodes)``, …) — never private
    weakref internals — so pending removals stay deferred across an active
    iteration (stdlib guard; see proposal §3.3).
    """

    def __init__(self):
        if _graph_gc_backstop:
            self.nodes: Dict[int, 'Container'] = weakref.WeakValueDictionary()
        else:
            self.nodes = {}
        self.dependencies: Dict[int, Set[int]] = defaultdict(set)  # node_id -> {dependency_ids}
        self.dependents: Dict[int, Set[int]] = defaultdict(set)   # node_id -> {dependent_ids}
        self.update_order: List[int] = []
        self.order_index: Dict[int, int] = {}
        self.needs_topological_sort = True

    def _purge_ids(self, node_ids: Set[int]) -> None:
        """Drop graph bookkeeping for ``node_ids`` (finalize / explicit path).

        Idempotent: safe when ids are already absent (explicit ``clean_up``
        then a late finalize, or a double-fire). Captures no Container —
        only this process-lifetime graph and a set of ints.
        """
        for nid in node_ids:
            self.nodes.pop(nid, None)
            for dep_id in self.dependencies.pop(nid, ()):
                bucket = self.dependents.get(dep_id)
                if bucket is not None:
                    bucket.discard(nid)
            for dep_id in self.dependents.pop(nid, ()):
                bucket = self.dependencies.get(dep_id)
                if bucket is not None:
                    bucket.discard(nid)
            self.order_index.pop(nid, None)
        self.needs_topological_sort = True

    def add_node(self, node_id: int, container: 'Container'):
        """Add a node to the graph.

        Do **not** pre-create empty dependency/dependent sets — both maps are
        ``defaultdict(set)`` and every reader already uses ``.get(id, ())``.
        Eager empty sets cost two allocations on every leaf Attribute/Point
        register (Sprite construct is graph-bound).
        """
        self.nodes[node_id] = container

    def remove_node(self, node_id: int):
        """Remove a node and all its relationships from the graph"""
        if node_id in self.nodes or node_id in self.dependencies or node_id in self.dependents:
            self._purge_ids({node_id})
            
    def add_dependency(self, dependent_id: int, dependency_id: int):
        """Add dependency relationship.
        
        Raises ValueError if dependency already exists (duplicate dependency).
        """
        if dependent_id == dependency_id:
            return  # Prevent self-dependency
            
        if dependency_id in self.dependencies[dependent_id]:
            raise ValueError(
                f"Dependency {dependent_id} → {dependency_id} already exists. "
                f"Cannot add duplicate dependency."
            )
            
        self.dependencies[dependent_id].add(dependency_id)
        self.dependents[dependency_id].add(dependent_id)
        self.needs_topological_sort = True
            
    def remove_dependency(self, dependent_id: int, dependency_id: int):
        """Remove dependency relationship"""
        self.dependencies[dependent_id].discard(dependency_id)
        self.dependents[dependency_id].discard(dependent_id)
        self.needs_topological_sort = True

    def can_reach(self, start_id: int, target_id: int) -> bool:
        """True if target_id is reachable from start_id following dependency edges."""
        if start_id == target_id:
            return True
        stack = [start_id]
        seen = set()
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            for dep_id in self.dependencies.get(nid, ()):
                if dep_id == target_id:
                    return True
                stack.append(dep_id)
        return False

    def would_create_cycle(self, dependent_id: int, dependency_id: int) -> bool:
        """
        True if adding dependent → dependency would introduce a cycle.

        A cycle exists iff dependency can already reach dependent (or they are
        the same node).
        """
        return self.can_reach(dependency_id, dependent_id)
        
    def get_dependencies(self, node_id: int) -> Set[int]:
        """Get all dependencies of a node"""
        return self.dependencies.get(node_id, set()).copy()
        
    def get_dependents(self, node_id: int) -> Set[int]:
        """Get all dependents of a node"""
        return self.dependents.get(node_id, set()).copy()
        
    def has_dependencies(self, node_id: int) -> bool:
        """Check if a node has any dependencies"""
        return bool(self.dependencies.get(node_id, ()))
        
    def has_dependents(self, node_id: int) -> bool:
        """Check if a node has any dependents"""
        return bool(self.dependents.get(node_id, ()))
        
    def topological_sort(self) -> List[int]:
        """Calculate topological order using Kahn's algorithm.

        Defense-in-depth: in-degree and edge walks count only ids still
        present in ``self.nodes``, so a stale int left in
        ``dependencies``/``dependents`` cannot inflate degrees into a false
        ``CircularDependencyError`` (proposal §9.2 item 2).
        """
        live = self.nodes
        in_degree: Dict[int, int] = {}
        for node_id in live:
            deps = self.dependencies.get(node_id, ())
            in_degree[node_id] = sum(1 for d in deps if d in live)

        queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for dependent_id in self.dependents.get(node_id, ()):
                if dependent_id not in in_degree:
                    continue
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(result) != len(live):
            raise CircularDependencyError("Circular dependency detected in formula graph")

        return result
        
    def get_update_order(self) -> List[int]:
        """Get cached update order, recalculating if needed"""
        if self.needs_topological_sort:
            self.update_order = self.topological_sort()
            self.order_index = {nid: i for i, nid in enumerate(self.update_order)}
            self.needs_topological_sort = False
        return self.update_order

    def sorted_subset(self, node_ids: Set[int]) -> List[int]:
        """Return node_ids ordered by global topological position (O(C log C))."""
        if self.needs_topological_sort:
            self.get_update_order()
        return sorted(
            (n for n in node_ids if n in self.order_index),
            key=self.order_index.__getitem__,
        )
        
    def clear(self):
        """Clear all nodes and relationships"""
        self.nodes.clear()
        self.dependencies.clear()
        self.dependents.clear()
        self.update_order.clear()
        self.order_index.clear()
        self.needs_topological_sort = True


# Poll rounds per flush before a re-trigger cycle is reported (see flush()).
FLUSH_MAX_ROUNDS = 8


class UpdateManager:
    """Invalidate on write; recompute pure data on read; flush effects.

    Effects (``@when`` / ``@on_change``) are not graph nodes: ``flush`` polls
    them from the event system in registration order.
    """

    def __init__(self, dependency_graph: DependencyGraph):
        self.graph = dependency_graph
        self.is_updating = False
        # When True, effects wait for flush() (run loop: tick + update(dt)).
        # Pure data is always pull-on-read regardless of this flag.
        self.deferring = False
        # Reused across mark_dirty calls (cleared each entry) — avoids
        # allocating a fresh seen-set + stack on every write that invalidates.
        self._dirty_stack: List = []
        self._dirty_seen: Set[int] = set()

    def mark_dirty(self, node) -> None:
        """Flag ``node`` and all transitive dependents as maybe-stale.

        Never recomputes. Re-walks the full cone on every call (``seen`` only prevents cycles) so a write
        after a partial pull still re-invalidates cleared dependents.

        Hot path (Tier 1): write ``_dirty`` via ``__dict__`` (bypass Entity /
        Point ``__setattr__``) and hoist graph maps into locals.
        """
        if node is None:
            return
        # Accept legacy node_id int for a few call sites during migration.
        if isinstance(node, int):
            node = self.graph.nodes.get(node)
            if node is None:
                return

        stack = self._dirty_stack
        seen = self._dirty_seen
        dependents = self.graph.dependents
        nodes = self.graph.nodes
        stack.append(node)
        try:
            while stack:
                current = stack.pop()
                nid = current._node_id
                if nid is not None:
                    if nid in seen:
                        continue
                    seen.add(nid)
                current.__dict__['_dirty'] = True
                if nid is None:
                    continue
                for dep_id in dependents.get(nid, ()):
                    dep = nodes.get(dep_id)
                    if dep is not None:
                        stack.append(dep)
        finally:
            stack.clear()
            seen.clear()

        # Frame hot path: ``deferring`` is True inside ``run()``, so this
        # branch is not taken. Outside a frame, poll ``@when`` / ``@on_change``
        # after a real invalidate. Skip mid-batch so a compound write flushes
        # once, from the batch's closing ``update()``.
        if not self.deferring and not self.is_updating:
            if (
                not getattr(node, "_in_batch_update", False)
                and _events_pending_poll()
            ):
                self.flush()

    def maybe_poll_events(self) -> None:
        """Run ``@when`` / ``@on_change`` if we are not inside a frame batch."""
        if not self.deferring and not self.is_updating:
            self.flush()

    def mark_clean(self, node_id: int) -> None:
        """Clear the dirty flag (used on unregister)."""
        node = self.graph.nodes.get(node_id)
        if node is not None:
            node._dirty = False

    def begin_defer(self) -> None:
        """Defer effect flush until ``flush()`` (frame batch)."""
        self.deferring = True

    def end_defer(self) -> None:
        """Stop deferring; subsequent writes may flush effects immediately."""
        self.deferring = False

    def flush(self) -> None:
        """Poll ``@when`` / ``@on_change`` until quiet (pulls pure data).

        A callback that fires can change what another watches, so polling
        repeats while anything fired. A chain with no cycle never fires one
        watch twice, so it settles in at most one round per watch, however
        long it is. Only rounds in which a watch fires *again* count toward
        ``FLUSH_MAX_ROUNDS``; past that, handlers keep re-triggering each other
        (two ``@on_change`` bumping each other's source): warn once per flush
        and leave the rest for the next flush instead of spinning
        (review 2026-10-09 S2-17).
        """
        if self.is_updating:
            return
        self.is_updating = True
        try:
            from .events import poll_all_events
            fired_before: set = set()
            repeat_rounds = 0
            while True:
                fired, repeated = poll_all_events(fired_before)
                if not fired:
                    break
                if repeated:
                    repeat_rounds += 1
                    if repeat_rounds >= FLUSH_MAX_ROUNDS:
                        warnings.warn(
                            f"SCENA: @when / @on_change watches fired again in "
                            f"{FLUSH_MAX_ROUNDS} rounds of one flush — handlers "
                            f"keep re-triggering each other (a cycle). Remaining "
                            f"changes run on the next flush.",
                            RuntimeWarning,
                            stacklevel=2,
                        )
                        break
        finally:
            self.is_updating = False


class ScenaSystem:
    """Main system that manages dependencies and updates"""
    
    def __init__(self):
        self.dependency_graph = DependencyGraph()
        self.update_manager = UpdateManager(self.dependency_graph)
        
    def register_container(self, container: 'Container'):
        """Register a container in the dependency system.
        
        Note: Dependencies are NOT added here - they are managed by _add_parts()/remove_parts()
        and owner setter. This method only registers the container in the graph.
        
        This method is idempotent - calling it multiple times is safe.
        Ephemeral (arithmetic temp) containers are never registered.
        A node of a deferred tree (a measured Box) first brings the whole
        tree in (``Container._join_dependency_graph``).
        """
        if getattr(container, '_ephemeral', False):
            return
        root_of = getattr(container, '_ownership_root', None)
        if root_of is not None:
            root = root_of()
            if root.__dict__.get('_graph_deferred', False):
                root._join_dependency_graph()

        # Set node_id if not already set
        if not hasattr(container, '_node_id') or container._node_id is None:
            container._node_id = id(container)
        
        # Only register if not already registered
        if container._node_id not in self.dependency_graph.nodes:
            # Note: container._scena_system is already set in Container.__init__()
            self.dependency_graph.add_node(container._node_id, container)
            if _graph_gc_backstop:
                # Per-node finalize: bag is ints only — never capture container.
                bag = {container._node_id}
                fin = weakref.finalize(
                    container,
                    self.dependency_graph._purge_ids,
                    bag,
                )
                container.__dict__['_graph_finalizer'] = fin
                container.__dict__['_owned_node_ids'] = bag
        
        # Dependencies are already established by _add_parts() when relationships are created
        # No need to add them here to avoid duplication
        
    def unregister_container(self, container: 'Container'):
        """Unregister a container from the dependency system"""
        if hasattr(container, '_node_id') and container._node_id:
            fin = container.__dict__.pop('_graph_finalizer', None)
            if fin is not None:
                fin.detach()
            container.__dict__.pop('_owned_node_ids', None)
            self.update_manager.mark_clean(container._node_id)
            self.dependency_graph.remove_node(container._node_id)
        
    def add_dependency(self, dependent: 'Container', dependency: 'Container'):
        """Add a dependency relationship between two containers.
        
        Automatically registers containers if they're not already registered.
        Skips entirely if either side is ephemeral (temps must not enter the graph).
        """
        if getattr(dependent, '_ephemeral', False) or getattr(dependency, '_ephemeral', False):
            return

        # Ensure both containers are registered
        if not hasattr(dependent, '_node_id') or dependent._node_id is None:
            self.register_container(dependent)
        if not hasattr(dependency, '_node_id') or dependency._node_id is None:
            self.register_container(dependency)
            
        # Add the dependency
        self.dependency_graph.add_dependency(dependent._node_id, dependency._node_id)
            
    def remove_dependency(self, dependent: 'Container', dependency: 'Container'):
        """Remove a dependency relationship between two containers"""
        if hasattr(dependent, '_node_id') and hasattr(dependency, '_node_id'):
            self.dependency_graph.remove_dependency(dependent._node_id, dependency._node_id)

    def begin_frame_batch(self) -> None:
        """Defer update cycles until flush() (used by the run loop each frame)."""
        self.update_manager.begin_defer()

    def end_frame_batch(self) -> None:
        """End deferred mode; further writes are eager again."""
        self.update_manager.end_defer()

    def flush(self) -> None:
        """Run pending effects (``@when`` / ``@on_change``); pure data is pull-on-read."""
        self.update_manager.flush()
            
    def _batch_update(self, changed_nodes: List['Container']):
        """Invalidate multiple nodes (effects flush unless deferring)."""
        for node in changed_nodes:
            self.update_manager.mark_dirty(node)
        
    def get_update_order(self) -> List[int]:
        """Get the current update order"""
        return self.dependency_graph.get_update_order()
        
    def clear(self):
        """Clear all dependencies and nodes"""
        self.dependency_graph.clear()
        self.update_manager.deferring = False


# Global scena system instance
_global_scena_system: Optional[ScenaSystem] = None


def get_scena_system() -> Optional[ScenaSystem]:
    """Get the global scena system instance"""
    return _global_scena_system


def set_scena_system(scena_system: Optional[ScenaSystem]):
    """Set the global scena system instance"""
    global _global_scena_system
    _global_scena_system = scena_system


def _rebind_input_singletons(scena_system: ScenaSystem) -> None:
    """Point long-lived ``keyp`` / ``mouse`` / ``clock`` at a fresh graph.

    They are created once, with the scena system captured in ``__init__``.
    A later ``init_scena_system()`` would otherwise leave ``keyp.update()``
    dirtying the discarded graph while new ``@=`` formulas record edges on
    the new one — a press would not re-pull.
    """
    import builtins
    # Every long-lived Container the framework publishes, not a hand list:
    # ``canvas`` became a formula source (camera, ``game_view``) and was
    # missing, so after an ``init_scena_system()`` a camera move notified the
    # discarded graph and every ``lambda: canvas.game_view`` link froze
    # (review 2026-10-09, deep serial pass).
    for obj in list(vars(builtins).values()):
        if isinstance(obj, Container) and "_scena_system" in getattr(obj, "__dict__", {}):
            obj._scena_system = scena_system


def init_scena_system() -> ScenaSystem:
    """Initialize and return a new global scena system instance"""
    global _global_scena_system
    _global_scena_system = ScenaSystem()
    _rebind_input_singletons(_global_scena_system)
    return _global_scena_system


def flush() -> None:
    """
    Resolve all pending reactive updates now.

    During the run loop, writes inside update(dt) only mark nodes dirty;
    the framework calls flush() automatically before draw(). Call this
    explicitly if you need derived geometry or linked dependents to catch
    up mid-update (or from code outside the frame loop after a batch of
    writes).
    """
    ss = get_scena_system()
    if ss is not None:
        ss.flush()


# Automatically initialize the global scena system when the module is imported
# This ensures containers can be created immediately without manual initialization
init_scena_system()
