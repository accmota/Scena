"""
Event system: ``@when`` (bool predicates) and ``@on_change`` (value observers).

Conditions are polled each ``flush()`` (every frame, after boxed-cell / ink
writes, and after a pull-invalidating write outside a frame batch). Any
Python object or zero-arg callable is accepted; there is no AST / FormulaLink
extraction for events. Shape ``@=`` formulas still use FormulaLink elsewhere.
"""

from __future__ import annotations

import warnings
from enum import Enum, auto
from typing import Callable, Any, Dict, Optional, Tuple, Union

from ._defaults import Unset
from .state import Container, Attribute, DestroyedError, FieldRef, field_ref_label


class EventKind(Enum):
    WHEN = auto()
    ON_CHANGE = auto()


_UNSET = Unset("<unset>")

# Condition errors that mean "the watched source is gone" — retire quietly.
_SOURCE_GONE = (DestroyedError, ReferenceError)

Condition = Union[Container, Callable[[], Any], Any]


def _unwrap_event_value(result: Any) -> Any:
    """Bare payload for comparison / callbacks.

    Attribute → ``.value``. FieldRef → that field's payload. Point / Vec2
    (``_leaf_composite``) → ``(x, y)`` so a move compares by coordinates;
    the object identity never changes.
    """
    if isinstance(result, FieldRef):
        result = result.value
    if isinstance(result, Attribute):
        return result.value
    if getattr(type(result), "_leaf_composite", False):
        return (result.x, result.y)
    return result


def _snapshot_value(value: Any) -> Any:
    """Copy a mutable container so a later in-place mutation can't fool the
    next comparison against a stale reference to the *same* object.

    ``@on_change(lambda: lst)`` used to store ``self._old_value = value``
    (a reference). ``lst.append(...)`` then compares the current ``lst``
    against itself — always equal, so it never fires. A shallow copy is
    enough (elements are compared by value on the next poll either way).
    """
    if type(value) is list:
        return list(value)
    if type(value) is dict:
        return dict(value)
    if type(value) is set:
        return set(value)
    return value


def _values_equal(a: Any, b: Any) -> bool:
    """``==`` plus NaN-aware equality (NaN must not re-fire every poll).

    ``True == 1 == 1.0`` in Python, but a flag that turns into a count (or
    back) is a change: equal values differ when exactly one is a bool (review
    2026-10-09 S2-14). ``10`` and ``10.0`` stay equal (a score that became a
    float is not a new score)."""
    if a is b:
        return True                     # the common poll: the same object
    if a == b:
        ca, cb = a.__class__, b.__class__
        return ca is cb or (ca is not bool and cb is not bool)
    if isinstance(a, float) and isinstance(b, float):
        return a != a and b != b
    if isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b):
        return all(_values_equal(x, y) for x, y in zip(a, b))
    return False


def _eval_condition(condition: Condition) -> Any:
    if isinstance(condition, Container):
        return condition
    if callable(condition):
        return condition()
    return condition


def _validate_condition(condition: Condition, kind: EventKind) -> None:
    """Reject a condition that can never change or never fire.

    Three shapes actually re-evaluate each poll: a zero-arg callable, a
    ``FieldRef`` (``obj["field"]`` — re-reads ``.value`` live), and an
    ``Attribute`` / leaf-composite Container (``Point``/``Vec2`` — compared
    by coordinates). Anything else is either:

    - a bare value (``@when(st.hp <= 0)`` evaluates the comparison once, at
      decoration time, into a plain ``bool`` that then never changes — the
      condition is silently dead); or
    - a non-leaf Container (``@on_change(circle)``) — the object's identity
      never changes, so it can never fire; the author meant one of its
      fields (``@on_change(lambda: circle.radius)``).

    Both are typo-shaped mistakes that used to register successfully and
    then simply never fire — "raise loud" instead.
    """
    label = "@when" if kind is EventKind.WHEN else "@on_change"
    cell = "alive" if kind is EventKind.WHEN else "wave"
    if isinstance(condition, FieldRef):
        return
    if isinstance(condition, Container):
        if isinstance(condition, Attribute):
            return
        if getattr(type(condition), "_leaf_composite", False):
            from .scenamath import Vec2
            if condition.owner is None and isinstance(condition, Vec2):
                # ``@on_change(st.pos)`` reads the Vec2 the cell holds (0.8.0):
                # ``st.pos = Vec2(…)`` stores a new one, so this never fires.
                raise TypeError(
                    f"{label}(Vec2) watches a free Vec2 value, which nothing "
                    "replaces in place. To watch a st cell, pass it with "
                    f"brackets: {label}(st[\"pos\"]) (st.pos reads the value "
                    f"since 0.8.0). For a shape's vector: {label}(lambda: line.vec)."
                )
            return
        raise TypeError(
            f"{label}({type(condition).__name__} instance) watches an object "
            "whose identity never changes, so it can never fire. Watch one "
            f"of its fields instead, e.g. {label}(lambda: obj.some_field)."
        )
    if callable(condition):
        return
    raise TypeError(
        f"{label} condition must be a zero-arg callable, a field "
        f"(st[\"{cell}\"], obj[\"field\"]), or a Point/Vec2 — got a bare "
        f"{type(condition).__name__} ({condition!r:.40}). Comparisons and "
        f"attribute reads inside {label}(...) run once, at decoration "
        f"time; wrap them in a lambda: {label}(lambda: ...). A st cell is "
        f"watched with brackets: {label}(st[\"{cell}\"]) (st.{cell} reads the "
        f"value since 0.8.0)."
    )


def _callback_npos(callback: Callable) -> int:
    """Payload slots on ``callback`` (``validate.payload_arity``): 0 or more.

    Only a parameter with no default receives the new value. ``*args`` or an
    unreadable signature counts as 1 (pass the value).
    """
    from .validate import payload_arity

    n = payload_arity(callback)
    return 1 if n is None else n


def _invoke_callback(
    callback: Callable,
    value: Any = None,
    *,
    pass_value: bool,
    npos: Optional[int] = None,
) -> None:
    if not pass_value:
        callback()
        return
    if npos is None:
        npos = _callback_npos(callback)
    if npos >= 1:
        callback(value)
    else:
        callback()


def _when_bool(value: Any) -> bool:
    """A ``@when`` condition value as ``bool`` (numpy scalars coerce), else ``TypeError``."""
    if isinstance(value, bool):
        return value
    # numpy's boolean scalar is not a Python `bool` (and does not subclass
    # it) — on numpy < 2 it is named `bool_`; on numpy >= 2 the class is
    # literally named `bool` (a different object from the builtin), which
    # used to make this raise the confusing "got bool" message.
    item = getattr(value, "item", None)
    coerced = item() if callable(item) else None
    if type(value).__module__ == "numpy" and isinstance(coerced, bool):
        return coerced
    raise TypeError(
        f"@when condition must evaluate to bool, got {type(value).__name__} "
        f"{value!r}. Compare explicitly (@when(lambda: st.hp <= 0)), or use "
        f"@on_change to watch value changes."
    )


class EventRegistration:
    """Polled ``@when`` / ``@on_change`` handler. Not a dependency-graph node."""

    def __init__(
        self,
        condition: Condition,
        callback: Callable,
        event_id: int,
        kind: EventKind = EventKind.WHEN,
        *,
        owner: Any = None,
    ):
        _validate_condition(condition, kind)
        self.callback = callback
        self.event_id = event_id
        self.kind = kind
        self._condition = condition
        self._owner = owner  # Entity for method @when / @on_change; None = classless
        self._is_active = False
        self._old_value = _UNSET
        self._drop = False
        # Positional arity of the callback, computed once on first fire.
        # None until then (and unused for @when, which passes no value).
        self._npos: Optional[int] = None
        self.name = f"Event[{event_id}]"
        self._node_id = None

        # Seed previous value while inactive (do not fire). A destroyed
        # source retires the watch; any other error (typo, missing ink or
        # State cell, a raising condition) raises at the decorator line.
        from .validate import check_handler_arity
        label = "@when" if kind is EventKind.WHEN else "@on_change"
        check_handler_arity(
            callback, () if kind is EventKind.WHEN else ("value",), what=label,
        )
        if _condition_reads_dead(condition):
            self.release()
            return
        try:
            raw = _eval_condition(condition)
        except _SOURCE_GONE:
            self.release()
            return
        if raw.__class__ is FieldRef and condition.__class__ is not FieldRef:
            # ``@on_change(lambda: st["wave"])``: a lambda returning the handle.
            # The bare handle is the watch spelling (``@on_change(st["wave"])``);
            # inside a lambda it is the dot, as in every formula. Checked once,
            # here, so a poll pays nothing.
            raise TypeError(
                f"{label}(lambda: …) returns {field_ref_label(raw)[0]}, the "
                f"handle: inside the lambda write {field_ref_label(raw)[1]}, or "
                f"pass the handle with no lambda: {label}({field_ref_label(raw)[0]})."
            )
        seeded = _unwrap_event_value(raw)
        if kind is EventKind.WHEN:
            _when_bool(seeded)
        self._old_value = _snapshot_value(seeded)
        self._is_active = True

    def release(self) -> None:
        """Retire this registration and drop owner / callback refs."""
        self._is_active = False
        self._drop = True
        self.callback = None
        self._condition = None
        self._owner = None

    def _owner_gone(self) -> bool:
        """True when a method-event's Entity was hard-destroyed (park does not count)."""
        if self._drop:
            return True
        owner = self._owner
        if owner is None:
            return False
        if getattr(owner, "is_alive", True):
            return False
        self.release()
        return True

    def _takein(self, result: Any) -> bool:
        return self._takein_impl(result)

    def _takein_impl(self, result: Any) -> bool:
        """Called when the watched expression is (re)evaluated. Returns True if fired."""
        if not self._is_active:
            return False
        if self._owner_gone():
            return False

        value = _unwrap_event_value(result)

        if self.kind == EventKind.WHEN:
            value = _when_bool(value)
            if value:
                _invoke_callback(self.callback, pass_value=False)
                return True
            return False

        callback = self.callback
        npos = self._npos
        if npos is None and callback is not None:
            npos = _callback_npos(callback)
            self._npos = npos
        _invoke_callback(callback, value, pass_value=True, npos=npos)
        return True

    def poll(self) -> bool:
        """Evaluate the condition once. Returns True if the callback fired.

        A destroyed source (``DestroyedError`` / ``ReferenceError``) retires
        the watch quietly. Any other error from the condition or the callback
        propagates. The edge is consumed before the callback runs, so a
        raising callback does not refire on the next poll.
        """
        if self._drop or not self._is_active:
            return False
        if self._owner_gone():
            return False

        try:
            result = _eval_condition(self._condition)
        except _SOURCE_GONE:
            self.release()
            return False
        value = _unwrap_event_value(result)
        if _values_equal(value, self._old_value):
            return False

        self._old_value = _snapshot_value(value)
        return self._takein_impl(result)

    def cleanup(self) -> None:
        self._is_active = False

    def unlink(self) -> None:
        """Teardown when a captured source is destroyed (dead ink / shape)."""
        self.cleanup()

    def disable(self) -> None:
        self._is_active = False

    def enable(self) -> None:
        self._is_active = True


class EventSystem:
    def __init__(self):
        # Insertion order is registration order. Removal is O(1); a dropped
        # registration leaves immediately, so destroy() does not keep the Entity.
        self._events: Dict[EventRegistration, None] = {}
        self._by_owner: Dict[int, Dict[EventRegistration, None]] = {}
        # Classless watches (no owner): ``drop_reading`` scans only these, so
        # a destroy never walks every registration.
        self._classless: Dict[EventRegistration, None] = {}
        self._event_counter = 0
        self._polling = False
        self.repeated = False

    def _index_owner(self, event: EventRegistration) -> None:
        owner = event._owner
        if owner is None:
            event._owner_key = None
            return
        key = id(owner)
        event._owner_key = key
        owned = self._by_owner.get(key)
        if owned is None:
            owned = {}
            self._by_owner[key] = owned
        owned[event] = None

    def _unindex(self, event: EventRegistration) -> None:
        key = getattr(event, "_owner_key", None)
        if key is None:
            return
        owned = self._by_owner.get(key)
        if owned is None:
            return
        owned.pop(event, None)
        if not owned:
            self._by_owner.pop(key, None)

    def register_event(
        self,
        condition: Condition,
        callback: Callable,
        kind: EventKind = EventKind.WHEN,
        *,
        owner: Any = None,
    ) -> EventRegistration:
        event = EventRegistration(
            condition, callback, self._event_counter, kind, owner=owner,
        )
        # A classless watch made after the top level ended belongs to the
        # current act: ``drop_act_owned`` retires it on an act change.
        from . import process as _process
        event._act_owned = owner is None and _process._top_level_ended
        self._events[event] = None
        self._index_owner(event)
        if owner is None:
            self._classless[event] = None
        self._event_counter += 1
        return event

    def unregister_event(self, event: EventRegistration) -> None:
        if event in self._events:
            event.cleanup()
            self._events.pop(event, None)
            self._unindex(event)

    def drop_owner(self, owner: Any) -> None:
        """Retire method-events owned by ``owner`` and drop their refs.

        Called from ``destroy()``. Does not wait for the next ``flush``.
        Walks only this owner's registrations. Safe during ``poll``: poll
        iterates a snapshot.
        """
        if owner is None:
            return
        owned = self._by_owner.pop(id(owner), None)
        if not owned:
            return
        for event in owned:
            # A poll may already have released this registration (_owner_gone).
            if event._owner is owner:
                event.release()
            self._events.pop(event, None)

    def drop_reading(self, obj: Any) -> None:
        """Retire classless watches whose condition closes over ``obj`` (it was
        destroyed). A field that stays readable after destroy (``radius``,
        ``angle``, ``center``) never raised, so the watch never retired and
        its closure kept the dead actor alive (review 2026-10-09 S2-8).
        Called from ``destroy()``; O(classless watches)."""
        if obj is None or not self._classless:
            return
        for event in list(self._classless):
            if event._drop or event not in self._events:
                self._classless.pop(event, None)
                continue
            if _condition_reads(event._condition, obj):
                event.release()
                self._events.pop(event, None)
                self._classless.pop(event, None)

    def drop_act_owned(self) -> int:
        """Retire classless watches registered after the top level ended.

        Called on an act change. Safe during ``poll`` (it iterates a
        snapshot). Returns how many were dropped.
        """
        dropped = [e for e in self._events if getattr(e, "_act_owned", False)]
        for event in dropped:
            event.release()
            self._events.pop(event, None)
            self._unindex(event)
        return len(dropped)

    def poll(self, fired_before: Optional[set] = None) -> int:
        """Evaluate every active event in registration order.

        Returns how many callbacks fired. An exception from a condition or a
        callback propagates (later watches wait for the next poll).

        ``fired_before`` (the flush's record): ids of the watches that already
        fired in this flush. Each fire is added; ``self.repeated`` tells
        whether a watch fired again (the only sign of a cycle).
        """
        self._polling = True
        self.repeated = False
        drop = False
        try:
            fired = 0
            for event in list(self._events):
                if not event._drop and event.poll():
                    fired += 1
                    if fired_before is not None:
                        key = id(event)
                        if key in fired_before:
                            self.repeated = True
                        else:
                            fired_before.add(key)
                if event._drop:
                    drop = True
            return fired
        finally:
            self._polling = False
            if drop:
                for event in list(self._events):
                    if not event._drop:
                        continue
                    self._events.pop(event, None)
                    self._unindex(event)

    def cleanup(self) -> None:
        for event in list(self._events):
            event.cleanup()
        self._events.clear()
        self._by_owner.clear()


_global_event_system: Optional[EventSystem] = None


def get_global_event_system() -> EventSystem:
    global _global_event_system
    if _global_event_system is None:
        _global_event_system = EventSystem()
    return _global_event_system


def cleanup_global_event_system() -> None:
    global _global_event_system
    if _global_event_system:
        _global_event_system.cleanup()
        _global_event_system = None


def _condition_reads(cond: Any, obj: Any) -> bool:
    """``cond`` holds ``obj``: a bound method of it, a field handle on it, or a
    function whose closure cells or default arguments hold it."""
    if cond is None:
        return False
    if getattr(cond, "__self__", None) is obj or getattr(cond, "owner", None) is obj:
        return True
    func = getattr(cond, "__func__", cond)
    for cell in getattr(func, "__closure__", None) or ():
        try:
            if cell.cell_contents is obj:
                return True
        except ValueError:
            continue
    if any(d is obj for d in (getattr(func, "__defaults__", None) or ())):
        return True
    # A global the code names (``lambda: inimigo.hp <= 0`` at the top of the
    # file): its read used to raise after the destroy and retire the watch;
    # a dead actor's own fields read now (R3-1), so the destroy retires it.
    code = getattr(func, "__code__", None)
    glb = getattr(func, "__globals__", None)
    if code is not None and glb is not None:
        return any(glb.get(n) is obj for n in code.co_names)
    return False


def _is_dead(x: Any) -> bool:
    return x is not None and bool(getattr(x, "__dict__", {}).get("_destroyed"))


def _condition_reads_dead(cond: Any) -> bool:
    """``cond`` reads an actor that is already destroyed: its bound object, a
    field handle's owner, a closure cell, a default, or a global its code
    names. A watch made on a dead source retires at once: a dead actor's own
    fields read (persona probes R3-1), so the read no longer raises to say so."""
    if cond is None:
        return False
    if _is_dead(getattr(cond, "__self__", None)) or _is_dead(getattr(cond, "owner", None)):
        return True
    func = getattr(cond, "__func__", cond)
    for cell in getattr(func, "__closure__", None) or ():
        try:
            if _is_dead(cell.cell_contents):
                return True
        except ValueError:
            continue
    if any(_is_dead(d) for d in (getattr(func, "__defaults__", None) or ())):
        return True
    code = getattr(func, "__code__", None)
    glb = getattr(func, "__globals__", None)
    if code is not None and glb is not None:
        return any(_is_dead(glb.get(n)) for n in code.co_names)
    return False


def poll_all_events(fired_before: Optional[set] = None) -> Tuple[int, bool]:
    """One round: ``(callbacks fired, whether a watch fired again this flush)``."""
    es = _global_event_system
    if es is None:
        return 0, False
    fired = es.poll(fired_before)
    return fired, es.repeated


def has_registered_events() -> bool:
    """True when at least one ``@when`` / ``@on_change`` is registered.

    Hot paths (frame ``mark_dirty`` while deferring) must not call this.
    """
    es = _global_event_system
    return es is not None and bool(es._events)


def _decorate(condition: Condition, kind: EventKind, role: str):
    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role
        _claim_decorator_role(func, role)
        event_system = get_global_event_system()
        event_registration = event_system.register_event(condition, func, kind=kind)
        regs = getattr(func, "_event_registrations", None)
        if regs is None:
            regs = []
            func._event_registrations = regs
        regs.append(event_registration)
        func._event_registration = event_registration  # last; unregister clears all
        return func

    return decorator


def when(condition: Condition):
    """Fire when a bool condition becomes True (rising edge).

    The condition may be a zero-arg callable, a boxed cell, or any Python
    object. It is polled every frame (and after ink / State writes). It must
    evaluate to a ``bool``. A condition that is already True when the watch
    is registered does not fire until it goes False and back to True.
    Use ``@on_change`` to watch non-bool values. A condition or callback
    that raises propagates (the edge is still consumed). A destroyed source
    retires the watch quietly.

    On an Entity-subclass method the condition takes ``self`` and registration
    waits until construct::

        @when(lambda self: self.hp <= 0)
        def on_death(self):
            ...

    Multiple ``@when`` on the same function are allowed (both conditions fire
    the same body). Mixing with ``@on_change`` / ``@every`` / ``@collide`` /
    ``@on_mode`` is a ``TypeError``.

    Example (classless)::

        @when(lambda: st.hp <= 0)
        def on_death():
            ...
    """
    # An async condition returns a coroutine each poll, never a bool.
    from .validate import refuse_async
    refuse_async(condition, what="@when condition")

    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role, _in_executing_class_body
        if _in_executing_class_body():
            if not callable(condition):
                raise TypeError(
                    "@when on a method needs a callable condition "
                    "(lambda self: ...). Use module-level @when(st[\"alive\"]) "
                    "for a st cell."
                )
            from .validate import check_handler_arity
            check_handler_arity(func, ("self",), what="@when")
            _claim_decorator_role(func, "when")
            specs = getattr(func, "_when_specs", None)
            if specs is None:
                specs = []
                func._when_specs = specs
            specs.append((condition, EventKind.WHEN))
            return func
        return _decorate(condition, EventKind.WHEN, "when")(func)

    return decorator


def on_change(target: Condition):
    """Fire whenever the watched value changes.

    ``target`` is any object or a zero-arg callable. Polled every frame.
    The callback may take zero args or one arg (the new value).

    On an Entity-subclass method the target takes ``self`` and registration
    waits until construct::

        @on_change(lambda self: self.hp)
        def on_hp(self, value):
            ...

    Multiple ``@on_change`` on the same function are allowed (both targets
    fire the same body). Mixing with ``@when`` / ``@every`` / ``@collide`` /
    ``@on_mode`` is a ``TypeError``.

    Example (classless)::

        @on_change(st["pos"])
        def follow(value):
            ...

        @on_change(lambda: c.radius)
        def on_radius(value):
            ...
    """
    # An async target returns a new coroutine each poll: a change every frame.
    from .validate import refuse_async
    refuse_async(target, what="@on_change target")

    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role, _in_executing_class_body
        if _in_executing_class_body():
            if not callable(target):
                raise TypeError(
                    "@on_change on a method needs a callable target "
                    "(lambda self: ...). Use module-level @on_change(st[\"wave\"]) "
                    "for a st cell."
                )
            from .validate import check_handler_arity
            check_handler_arity(func, ("self", "value"), what="@on_change")
            _claim_decorator_role(func, "on_change")
            specs = getattr(func, "_when_specs", None)
            if specs is None:
                specs = []
                func._when_specs = specs
            specs.append((target, EventKind.ON_CHANGE))
            return func
        return _decorate(target, EventKind.ON_CHANGE, "on_change")(func)

    return decorator


def unregister_event(func: Callable) -> None:
    """Unregister all events from a ``@when`` / ``@on_change`` decorated function.

    Args:
        func: The function registered with ``@when`` / ``@on_change``.
    """
    regs = getattr(func, "_event_registrations", None)
    if regs:
        event_system = get_global_event_system()
        for reg in list(regs):
            event_system.unregister_event(reg)
        regs.clear()
        try:
            delattr(func, "_event_registrations")
        except AttributeError:
            pass
    elif hasattr(func, "_event_registration"):
        event_system = get_global_event_system()
        event_system.unregister_event(func._event_registration)
    if hasattr(func, "_event_registration"):
        delattr(func, "_event_registration")
