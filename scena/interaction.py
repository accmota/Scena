"""
Decorator sugar for pointer callbacks and collision pairing.

Built on the ``on_click`` / ``on_drag_to`` / ``on_drag_over`` / ``on_drop_by``
/ ``on_hover`` / ``on_hover_exit`` properties. Accepts Graphics (Shape,
Sprite), widgets where the gesture makes sense, and GroupOperator instances.
A named tag (``group["cartas"]``) follows the tag, as ``@collide`` does: its
members now, every member that joins later, and a member that leaves loses
the handler (a tag rule). A snapshot (``group["a"] | group["b"]``,
``.filter(…)``) or a formula group wires the members of the moment. Last
registration wins per item; a handler set by hand (``card.on_click = f``) is
never overwritten by a join or a leave. A rule made in an act leaves with the
act, like an act's ``@collide``.

Widget policy (one rule for direct arguments and group members):
``@click`` takes a ``Button`` (other widgets report a value change: use
``@on_change(widget.data)``); ``@hover`` / ``@hover_exit`` take any widget;
drag / drop take Graphics only. A refused target raises before any target is
touched (no half-applied decorator).

Collision decorators (`collide` / `collide_stay` / `collide_exit`) live here
as the author-facing re-exports; implementation is in ``scena.collision``.
"""

from typing import Callable, Dict, List, Optional

from .entity import Graphic
from .shapes import Shape
from .validate import check_pointer_handler


_DRAG_PAYLOAD = ("from_shape", "to_shape", "pos")


def _is_widget(obj) -> bool:
    return getattr(type(obj), "_scena_is_widget", False)


def _refuse_widget(verb: str, widget) -> None:
    name = type(widget).__name__
    if verb == "click":
        raise TypeError(
            f"@click takes a Shape, Sprite or Button; {name} has no click: a "
            f"click changes its value. Watch the value instead: "
            f"@on_change({name.lower()}.data)."
        )
    raise TypeError(
        f"@{verb} takes a Shape or Sprite; widgets do not drag or receive "
        f"drops (got {name})."
    )


def _check_target(verb: str, target) -> None:
    if isinstance(target, Graphic):
        return
    if _is_widget(target):
        from .uiwidget import Button
        if verb in ("hover", "hover_exit"):
            return
        if verb == "click" and isinstance(target, Button):
            return
        _refuse_widget(verb, target)
    allowed = {
        "click": "Shape, Sprite, Button",
        "hover": "Shape, Sprite, widget",
        "hover_exit": "Shape, Sprite, widget",
    }.get(verb, "Shape, Sprite")
    raise TypeError(
        f"@{verb} expected {allowed}, or GroupOperator, got {type(target).__name__}"
    )


def _collect_targets(verb: str, *targets) -> List:
    """Every target the decorator will touch, checked before any is touched."""
    from .canvas import GroupOperator

    out = []
    for target in targets:
        members = list(target) if isinstance(target, GroupOperator) else [target]
        for member in members:
            _check_target(verb, member)
            out.append(member)
    return out


class _TagRule:
    """``@<verb>(group[tag])``: ``attr = func`` on every member of ``tag``."""

    __slots__ = ("tag", "verb", "attr", "func", "seq", "in_act")

    def __init__(self, tag, verb, attr, func, seq, in_act):
        self.tag, self.verb, self.attr, self.func = tag, verb, attr, func
        self.seq, self.in_act = seq, in_act


# tag -> its rules, in decoration order. The registry calls ``_tag_hook`` on
# every tag / untag once a rule exists (``registry._POINTER_TAG_HOOK``).
_TAG_RULES: Dict[str, List[_TagRule]] = {}
_seq = [0]


def _live_tag(target) -> Optional[str]:
    """The tag a live ``group[tag]`` view names, or None (a snapshot, a
    formula group, an object)."""
    from .canvas import GroupOperator
    if isinstance(target, GroupOperator) and target._group_id is not None \
            and target._snapshot is None and target._formula_name is None:
        return target._group_id
    return None


def _where(func) -> str:
    code = getattr(func, "__code__", None)
    if code is None:
        return getattr(func, "__name__", "the handler")
    import os
    return f"{os.path.basename(code.co_filename)}:{code.co_firstlineno}"


def _check_joiner(item, rule: _TagRule) -> None:
    try:
        _check_target(rule.verb, item)
    except TypeError as e:
        raise TypeError(
            f"{type(item).__name__} joined group {rule.tag!r}, whose @{rule.verb} "
            f"({_where(rule.func)}) cannot take it: {e}"
        ) from None


def _rule_funcs(attr: str, extra=()) -> set:
    out = {id(f) for f in extra}
    for rules in _TAG_RULES.values():
        for r in rules:
            if r.attr == attr:
                out.add(id(r.func))
    return out


def _refresh(item, attrs, gone=()) -> None:
    """Give ``item`` the newest rule its tags have for each of ``attrs``,
    unless it holds a handler no rule set (set by hand: kept)."""
    if getattr(item, "_destroyed", False):
        return
    tags = getattr(item, "group", ()) or ()
    for attr in attrs:
        best = None
        for tag in tags:
            for r in _TAG_RULES.get(tag, ()):
                if r.attr == attr and (best is None or r.seq > best.seq):
                    best = r
        current = getattr(item, attr, None)
        if current is not None and id(current) not in _rule_funcs(attr, gone):
            continue
        want = best.func if best is not None else None
        if current is not want:
            setattr(item, attr, want)


def _tag_hook(item, tag: str, phase: str) -> None:
    """``registry.add_to_group`` / ``remove_from_group`` on a built actor:
    ``check`` (before the join: a refused joiner raises, nothing changed),
    ``join`` and ``leave`` (after)."""
    rules = _TAG_RULES.get(tag)
    if not rules:
        return
    if phase == "check":
        for r in rules:
            _check_joiner(item, r)
        return
    _refresh(item, {r.attr for r in rules})


def apply_tag_rules(item) -> None:
    """A new actor's tags (``group=`` at construction): the construct finish
    step. A refused joiner raises, and the constructor rolls back."""
    if not _TAG_RULES:
        return
    tags = getattr(item, "group", ()) or ()
    attrs = set()
    for tag in tags:
        for r in _TAG_RULES.get(tag, ()):
            _check_joiner(item, r)
            attrs.add(r.attr)
    if attrs:
        _refresh(item, attrs)


def drop_act_tag_rules() -> None:
    """An act change: the act's tag rules leave; the members that stay (game
    objects) fall back to the game's rules, or to no handler."""
    doomed = [r for rules in _TAG_RULES.values() for r in rules if r.in_act]
    if not doomed:
        return
    for tag in list(_TAG_RULES):
        _TAG_RULES[tag] = [r for r in _TAG_RULES[tag] if not r.in_act]
        if not _TAG_RULES[tag]:
            del _TAG_RULES[tag]
    from .canvas import ScenaCanvas
    gm = ScenaCanvas.get_current().registry.group_map
    for r in doomed:
        for item in list(gm.get(r.tag, ())):
            _refresh(item, (r.attr,), gone=(r.func,))
    if not _TAG_RULES:
        from . import registry as _reg
        _reg._POINTER_TAG_HOOK = None


def _reset_tag_rules() -> None:
    """Tests / a world reset: no rules."""
    _TAG_RULES.clear()
    from . import registry as _reg
    _reg._POINTER_TAG_HOOK = None


def _pointer_decorator(verb: str, attr: str, passes, targets):
    def decorator(func: Callable) -> Callable:
        from .process import _claim_decorator_role
        from . import process as _process
        check_pointer_handler(func, passes, what=f"@{verb}")
        items = _collect_targets(verb, *targets)
        _claim_decorator_role(func, "pointer")
        for target in targets:
            tag = _live_tag(target)
            if tag is None:
                continue
            _seq[0] += 1
            rules = _TAG_RULES.setdefault(tag, [])
            rules[:] = [r for r in rules if r.attr != attr]     # a newer rule replaces it
            rules.append(_TagRule(tag, verb, attr, func, _seq[0], _process._top_level_ended))
            from . import registry as _reg
            _reg._POINTER_TAG_HOOK = _tag_hook
        for item in items:
            setattr(item, attr, func)
        return func
    return decorator


def click(*targets):
    """Register a click handler on shapes, sprites, Buttons, or groups.

    Sets ``target.on_click = func`` (a Graphic also becomes ``clickable``).
    Handler: ``func(target)`` — or ``func()``; Scena passes what it declares.
    The same handler can serve a Shape and a Button.

    Example:
        @click(circle1, circle2, reset_button)
        def handle_click(target):
            ...

        @click(group['buttons'])
        def handle_group(shape):
            ...
    """
    return _pointer_decorator("click", "on_click", ("target",), targets)


def hover(*targets):
    """Register a hover-enter handler on shapes, sprites, widgets, or groups.

    Sets ``target.on_hover = func``. Called once when the target becomes the
    hover target (the topmost pointer target under the cursor): ``func(target)``.
    A Graphic with only hover handlers stays click-transparent. Pair it with
    ``@hover_exit``; every enter is followed by exactly one exit.

    Example:
        @hover(group["cards"])
        def lit(card):
            card.set_color("gold")
    """
    return _pointer_decorator("hover", "on_hover", ("target",), targets)


def hover_exit(*targets):
    """Register a hover-exit handler on shapes, sprites, widgets, or groups.

    Sets ``target.on_hover_exit = func``. Called once when the target stops
    being the hover target — pointer left, hidden, destroyed, covered by a
    widget, or a modal opened: ``func(target)``.

    Example:
        @hover_exit(group["cards"])
        def unlit(card):
            card.set_color("gray")
    """
    return _pointer_decorator("hover_exit", "on_hover_exit", ("target",), targets)


def drag_to(*targets):
    """Register a drag-release handler on the *dragged* shape(s).

    Sets shape.on_drag_to = func (which also sets draggable=True).
    Handler: ``func(from_shape, to_shape, pos)`` where ``to_shape`` is the
    topmost droppable under the pointer at release (or None).

    Example:
        @drag_to(token)
        def on_dragged(from_shape, to_shape, pos):
            ...
    """
    return _pointer_decorator("drag_to", "on_drag_to", _DRAG_PAYLOAD, targets)


def drag_over(*targets):
    """Register a during-drag handler on the *dragged* shape(s).

    Sets shape.on_drag_over = func (which also sets draggable=True).
    Called on mouse move while dragging: ``func(from_shape, to_shape, pos)``
    with ``to_shape`` the current droppable under the pointer (or None).

    Example:
        @drag_over(token)
        def on_hovering(from_shape, to_shape, pos):
            ...
    """
    return _pointer_decorator("drag_over", "on_drag_over", _DRAG_PAYLOAD, targets)


def drop_by(*targets):
    """Register a drop-receive handler on the *drop target* shape(s).

    Sets shape.on_drop_by = func (which also sets droppable=True).
    Called on the receiving shape at release: ``func(from_shape, to_shape, pos)``
    where ``to_shape`` is the receiver (the decorated shape).

    Example:
        @drop_by(zone)
        def on_receive(from_shape, to_shape, pos):
            ...
    """
    return _pointer_decorator("drop_by", "on_drop_by", _DRAG_PAYLOAD, targets)


def collide(left, right):
    """Register a collision-enter handler between two sides. See ``scena.collision.collide``."""
    from .collision import collide as _collide
    return _collide(left, right)


def collide_stay(left, right):
    """Register a per-frame overlap handler. See ``scena.collision.collide_stay``."""
    from .collision import collide_stay as _collide_stay
    return _collide_stay(left, right)


def collide_exit(left, right):
    """Register a collision-exit handler. See ``scena.collision.collide_exit``."""
    from .collision import collide_exit as _collide_exit
    return _collide_exit(left, right)


def collide_with(target):
    """Method decorator: this instance collides with ``target``. See ``scena.collision.collide_with``."""
    from .collision import collide_with as _collide_with
    return _collide_with(target)


def collide_with_stay(target):
    """Method decorator: overlap-stay with ``target``. See ``scena.collision.collide_with_stay``."""
    from .collision import collide_with_stay as _collide_with_stay
    return _collide_with_stay(target)


def collide_with_exit(target):
    """Method decorator: overlap-exit with ``target``. See ``scena.collision.collide_with_exit``."""
    from .collision import collide_with_exit as _collide_with_exit
    return _collide_with_exit(target)


# Alias matching Unity-style naming
collide_enter = collide


def leave_playfield(*group_names):
    """Decorator: fire when an actor's center leaves ``canvas.playfield``.

    See ``scena.bounds.leave_playfield``.
    """
    from .bounds import leave_playfield as _leave_playfield
    return _leave_playfield(*group_names)
