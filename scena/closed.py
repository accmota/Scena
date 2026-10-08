"""Closed author surfaces: a write to a name the object does not have raises.

Only Entity (ink) and ``st`` (cells) create names on write. Every other author
object accepts writes only to names it already has, so ``bloom.itnensity = 2``
or ``audio.vloume = 0`` raises instead of storing a dead attribute (Scena
Design, "Entity ink vs ``st``"; Testing Design, family CS).

How an object closes:

* ``ClosedSurface`` (mixin) gives the class :func:`closed_setattr` and seals
  every subclass constructor through ``__init_subclass__``. A class that keeps
  its own ``__setattr__`` calls :func:`check_closed_write` from it instead.
* Until the outermost sealed ``__init__`` returns, any write passes: a
  constructor (the engine's or an author subclass's) creates its fields.
  After that, a public write passes only when the name is in the instance
  ``__dict__`` or the class has it as a data descriptor (property,
  ``ScalarSlot``) or a non-callable class default (``PostEffect.enabled``).
* Names starting with ``_`` always pass (engine privates, caches).

The seal marks the outermost sealed constructor call per instance
(:func:`seal_after_init`); nested ``super().__init__`` calls see the mark. It
does not test ``type(self).__init__ is wrapped``: ``scena/__init__.py`` wraps
every export's ``__init__`` again (``install_friendly_constructor``) after the
class body ran, so an identity test would never fire on an exported class.

This module imports nothing from scena at import time: ``state.Attribute``
uses it on its write path.
"""
from __future__ import annotations

import functools
import weakref
from typing import Any, Iterable, Optional, Tuple

_SEALED = "_sealed"
_DEPTH = "_init_depth"
_CACHE = "_scena_closed_names"
# Writable list in a message: past this many names, the list ends in "…".
_LIST_CAP = 20

_seal_wrappers: "weakref.WeakSet" = weakref.WeakSet()


def _scan(cls: type) -> Tuple[frozenset, frozenset, frozenset]:
    """``(accepted, listed, methods)`` public class-level names of ``cls``.

    ``accepted``: names a sealed write may target (data descriptors and
    non-callable class defaults). ``listed``: the subset the message offers
    an author (not: a property with no setter or a Derivate field slot such
    as ``Vec2.length``, whose own error speaks; an ALL_CAPS constant; a name
    a class lists in ``_closed_hidden``, such as the ``Container`` plumbing).
    ``methods``: callables, for the "is a method" message.
    """
    seen = set()
    accepted, listed, methods = set(), set(), set()
    hidden = set()
    for klass in cls.__mro__:
        hidden.update(vars(klass).get("_closed_hidden", ()))
    for klass in cls.__mro__:
        if klass is object:
            continue
        for name, value in vars(klass).items():
            if name in seen or name.startswith("_"):
                continue
            seen.add(name)
            if hasattr(type(value), "__set__"):
                accepted.add(name)
                if not (isinstance(value, property) and value.fset is None) and not (
                    getattr(value, "_is_field_slot", False)
                    and getattr(getattr(value, "field_type", None), "name", None) == "Derivate"
                ):
                    listed.add(name)
            elif isinstance(value, (staticmethod, classmethod, type)) or callable(value):
                methods.add(name)
            else:
                accepted.add(name)
                listed.add(name)
    listed = {n for n in listed if n not in hidden and not n.isupper()}
    return frozenset(accepted), frozenset(listed), frozenset(methods)


def class_names(cls: type) -> Tuple[frozenset, frozenset, frozenset]:
    """Cached :func:`_scan` of ``cls`` (stored on the class, not inherited)."""
    names = cls.__dict__.get(_CACHE)
    if names is None:
        names = _scan(cls)
        type.__setattr__(cls, _CACHE, names)
    return names


def check_closed_write(obj: Any, name: str) -> None:
    """Raise ``AttributeError`` unless a sealed ``obj`` may write ``name``.

    Callers have already passed private names and names in ``obj.__dict__``.
    """
    if name not in class_names(type(obj))[0]:
        raise AttributeError(closed_message(obj, name))


def closed_setattr(self: Any, name: str, value: Any, _set=object.__setattr__) -> None:
    """``__setattr__`` of a closed surface (see the module docstring).

    Hot path: a private write pays one ``name[0]`` test; a sealed public
    write one cache lookup (no ``getattr_static``: ~350 ns per call).
    """
    if not name or name[0] != "_":
        d = self.__dict__
        if d.get(_SEALED) and name not in d:
            names = type(self).__dict__.get(_CACHE)
            if names is None:
                names = class_names(type(self))
            if name not in names[0]:
                raise AttributeError(closed_message(self, name))
    _set(self, name, value)


# Private names go straight to object.__setattr__ (state._container_dict_init).
closed_setattr._scena_private_passthrough = True


def make_closed_setattr(fast: Iterable[str]):
    """:func:`closed_setattr` with ``fast`` names passed first (hot writes,
    such as ``Attribute.value``). Every name in ``fast`` must exist on the class."""
    fast = frozenset(fast)

    def __setattr__(self, name: str, value: Any, _set=object.__setattr__) -> None:
        if name not in fast and (not name or name[0] != "_"):
            d = self.__dict__
            if d.get(_SEALED) and name not in d:
                names = type(self).__dict__.get(_CACHE)
                if names is None:
                    names = class_names(type(self))
                if name not in names[0]:
                    raise AttributeError(closed_message(self, name))
        _set(self, name, value)

    __setattr__._scena_fast_names = fast
    __setattr__._scena_private_passthrough = True
    return __setattr__


def seal_after_init(cls: type) -> None:
    """Wrap ``cls``'s own ``__init__`` so the instance seals when the outermost
    sealed constructor returns. No-op when ``cls`` has no ``__init__`` of its
    own (the inherited one is already wrapped) or when it is already wrapped.

    Install it after any wrapper that may create public names (construct-to-
    place), so the seal is the last step; wrappers that only rewrite errors
    (``install_friendly_constructor``) may sit outside.
    """
    init = cls.__dict__.get("__init__")
    if init is None or init in _seal_wrappers:
        return

    @functools.wraps(init)
    def __init__(self, *args, **kwargs):
        d = self.__dict__
        if _DEPTH in d:                 # nested (super().__init__): the outer call seals
            init(self, *args, **kwargs)
            return
        d[_DEPTH] = True
        try:
            init(self, *args, **kwargs)
        except BaseException:
            del d[_DEPTH]
            raise
        del d[_DEPTH]
        d[_SEALED] = True

    _seal_wrappers.add(__init__)
    cls.__init__ = __init__


def seal(obj: Any) -> None:
    """Seal an instance built without its constructor (``cls.__new__`` fast
    paths such as ``Box._snapshot``). Call it after the last field is set."""
    obj.__dict__[_SEALED] = True


def is_sealed(obj: Any) -> bool:
    """True once ``obj``'s constructor has returned (tests, audit probes)."""
    return bool(getattr(obj, "__dict__", {}).get(_SEALED))


class ClosedSurface:
    """Mixin: writes to unknown public names raise once constructed.

    Class attributes a subclass may set:

    * ``_closed_who``: how the message names the object (``"canvas"``);
      default: the class name.
    * ``_closed_hint(self, name)``: a method returning a custom message for
      ``name`` (or ``None``), e.g. a knob that lives somewhere else.
    """

    __slots__ = ()
    __setattr__ = closed_setattr

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        seal_after_init(cls)


def transposed(a: str, b: str) -> bool:
    """One adjacent transposition apart (``anlge`` / ``angle``, ``pseed`` / ``speed``)."""
    if len(a) != len(b) or a == b:
        return False
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    return (
        len(diff) == 2 and diff[1] == diff[0] + 1
        and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
    )


def _is_author_class(cls: type) -> bool:
    return not (cls.__module__ or "").startswith("scena")


def unknown_name_message(
    who: str,
    name: str,
    writable: Iterable[str],
    *,
    noun: Optional[str] = None,
    hint: Optional[str] = None,
    candidates: Optional[Iterable[str]] = None,
    author_class: bool = False,
) -> str:
    """``<who> has no '<name>'. Did you mean 'x'? Writable on <noun>: a, b, c.``

    ``hint`` replaces the did-you-mean (computed over ``candidates``, default
    ``writable``). ``author_class`` adds the "create it in ``__init__``" advice
    when no close name matched (a near miss is a typo, not new data).
    """
    writable = list(writable)
    if hint is None:
        pool = writable if candidates is None else list(candidates)
        # An adjacent swap of a real name beats difflib's pick (``pseed`` is
        # ``speed``, not ``seed``).
        swaps = [c for c in pool if transposed(name, c)]
        if swaps:
            hint = f" Did you mean {swaps[0]!r}?"
        else:
            from .validate import did_you_mean
            hint = did_you_mean(name, pool, n=1)
    shown = writable[:_LIST_CAP]
    listing = ", ".join(shown) + (", …" if len(writable) > _LIST_CAP else "")
    msg = f"{who} has no {name!r}.{hint}"
    if listing:
        msg += f" Writable on {noun or who}: {listing}."
    if author_class and not hint:
        msg += (
            " To keep your own data on a subclass, create it in __init__"
            f" (self.{name} = ...)."
        )
    return msg


def closed_message(obj: Any, name: str) -> str:
    """The ``AttributeError`` text for a refused write ``obj.<name> = ...``."""
    cls = type(obj)
    who = getattr(cls, "_closed_who", None) or cls.__name__
    custom = getattr(cls, "_closed_hint", None)
    if custom is not None:
        text = custom(obj, name)
        if text:
            return text
    accepted, listed, methods = class_names(cls)
    if name in methods:
        return f"{who}.{name} is a method; call it, do not assign it."
    hidden = set()
    for klass in cls.__mro__:
        hidden.update(vars(klass).get("_closed_hidden", ()))
    own = {
        n for n, v in getattr(obj, "__dict__", {}).items()
        if isinstance(n, str) and not n.startswith("_") and not callable(v) and n not in hidden
    }
    writable = sorted(listed | own)
    # Suggest read-only names too (``box.topp`` → ``top``): the next try
    # then gets that property's own error.
    pool = {n for n in accepted if n not in hidden and not n.isupper()} | own
    return unknown_name_message(
        who, name, writable, candidates=sorted(pool), author_class=_is_author_class(cls),
    )
