"""Construct-to-place helpers (post effects and background fields).

Author constructs attach by class family, like ``Circle()``. Materials
(``Gradient``, ``Color``, ``Blur``, ``Neon``) never go through this module.
Tests and internal wrappers use :func:`unplaced_creation`; authors use
``.temp()``.
"""
from __future__ import annotations

import functools
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, TypeVar

_unplaced: ContextVar[bool] = ContextVar("scena_unplaced", default=False)

T = TypeVar("T")


@contextmanager
def unplaced_creation():
    """Construct a post effect or background field without attaching it."""
    token = _unplaced.set(True)
    try:
        yield
    finally:
        _unplaced.reset(token)


def is_unplaced_creation() -> bool:
    return bool(_unplaced.get())


def _drop_failed_construct(obj) -> None:
    """A constructor that raised must not leave a roster, group, or draw entry.

    Neither may its parts: a Point part built before the raise leaves too.
    """
    canvas = getattr(obj, "_scenacanvas", None)
    registry = getattr(canvas, "registry", None)
    if registry is None:
        return
    from .registry import entity_parts
    for part in entity_parts(obj):
        try:
            registry.retire_part(part, obj)
        except Exception:
            pass
    try:
        registry.unregister_draw(obj)
    except Exception:
        pass
    try:
        registry.remove_live(obj)
    except Exception:
        pass
    groups = getattr(obj, "group", None)
    if groups:
        for gid in list(groups):
            try:
                registry.remove_from_group(obj, gid)
            except Exception:
                pass
    try:
        from .orchestration import forget_hud_column_item, unregister_widget
        forget_hud_column_item(obj)
        unregister_widget(obj)
    except Exception:
        pass
    try:
        object.__setattr__(obj, "_destroyed", True)
    except Exception:
        pass


def wrap_init_autoplace(cls, place_fn: Callable) -> None:
    """Call ``place_fn(self)`` after the class's own ``__init__``.

    Also guards author knobs (:func:`~scena.validate.guard_init_numbers`)
    and keeps the original signature visible to ``help()`` / IDEs.
    """
    from .validate import guard_init_numbers

    if getattr(cls.__dict__.get("__init__"), "_scena_place_wrapped", False):
        return
    guard_init_numbers(cls)
    orig = cls.__init__

    @functools.wraps(orig)
    def wrapped(self, *args, **kwargs):
        try:
            orig(self, *args, **kwargs)
            place_fn(self)
        except BaseException:
            _drop_failed_construct(self)
            raise

    wrapped._scena_place_wrapped = True
    cls.__init__ = wrapped


def temp_construct(cls: type[T], *args, **kwargs) -> T:
    with unplaced_creation():
        return cls(*args, **kwargs)
