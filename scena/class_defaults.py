"""Class keywords of an author subclass: ``class Placar(Text, font_size=32)``.

Shape and Sprite keep their own tables (``_shape_defaults``,
``_sprite_defaults``); SpatialFx and Text share this one. A family calls
:func:`take_class_defaults` from its ``__init_subclass__`` for an author
subclass: the keywords it allows move into ``cls._class_defaults`` (merged
over an author base's), placement and unknown names raise author errors on
the class line, and bad values fail there too. The family's constructor
fills what a call left out from ``type(self)._class_defaults`` (the instance
wins). Classes no family serves refuse every class keyword
(``entity._refuse_class_keywords``).
"""
from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, Mapping, Optional


def init_keywords(kind: type) -> frozenset:
    """The named keyword parameters of ``kind.__init__`` (no ``self``, no ``*``)."""
    try:
        params = inspect.signature(inspect.unwrap(kind.__init__)).parameters.values()
    except (TypeError, ValueError):
        return frozenset()
    return frozenset(p.name for p in params if p.name != "self"
                     and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD))


def _author_mixin_wants_keywords(cls: type, kind: type) -> bool:
    """A non-framework base outside ``kind``'s family with its own
    ``__init_subclass__`` (``class Doce(Text, Mixin, flavor=...)``)."""
    from ._pkg import is_framework_module
    return any("__init_subclass__" in vars(k) for k in cls.__mro__[1:]
               if k is not object and not is_framework_module(k.__module__)
               and not issubclass(k, kind))


def take_class_defaults(
    cls: type,
    kwargs: Dict[str, Any],
    *,
    kind: type,
    allowed: Iterable[str],
    placement: Iterable[str],
    refused: Optional[Mapping[str, str]] = None,
) -> None:
    """Move ``cls``'s class keywords out of ``kwargs`` into ``cls._class_defaults``.

    ``kind`` is the framework class whose constructor reads them (recorded as
    ``cls._class_kind``). ``placement`` names are instance-only; ``refused``
    maps other names to the message that explains why.
    """
    allowed = frozenset(allowed)
    placement = frozenset(placement)
    refused = refused or {}
    cls._class_kind = kind
    incoming: Dict[str, Any] = {}
    unexpected: Dict[str, Any] = {}
    for key in list(kwargs):
        if key in allowed:
            incoming[key] = kwargs.pop(key)
        elif key in placement:
            raise TypeError(
                f"{key}= is instance placement, not a class default. "
                f"Pass {key}= when constructing {cls.__name__}(...)."
            )
        elif key in refused:
            raise TypeError(refused[key])
        else:
            unexpected[key] = kwargs.pop(key)
    if unexpected and _author_mixin_wants_keywords(cls, kind):
        kwargs.update(unexpected)          # an author mixin's __init_subclass__ takes them
        unexpected = {}
    if unexpected:
        from .validate import reject_unexpected_kwargs
        reject_unexpected_kwargs(cls.__name__, unexpected, valid=allowed, where="class defaults")
    if incoming:
        # Bad values fail on the class line, not at the first instance.
        from .validate import check_numeric_params, formula_knobs
        try:
            sig = inspect.signature(inspect.unwrap(kind.__init__))
        except (TypeError, ValueError):
            sig = None
        if sig is not None:
            check_numeric_params(cls.__name__, sig, (), dict(incoming), formula_knobs(kind))
    merged = dict(getattr(cls, "_class_defaults", None) or {})
    merged.update(incoming)
    cls._class_defaults = merged
