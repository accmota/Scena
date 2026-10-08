"""Named placeholder defaults for public signatures.

``layer=_USE_LAYER_DEFAULT`` with a bare ``object()`` showed up in
``help(Circle)`` / IDE autocomplete as ``layer=<object object at 0x10d31cf0>``.
An ``Unset`` compares by identity like ``object()`` but reads
``layer=<default layer>``.
"""
from __future__ import annotations


class Unset:
    """A default that means "not given"; ``repr`` is the text shown in signatures."""

    __slots__ = ("_text",)

    def __init__(self, text: str) -> None:
        self._text = text

    def __repr__(self) -> str:
        return self._text

    # A sentinel is compared with ``is``: copies must be the same object.
    def __copy__(self) -> "Unset":
        return self

    def __deepcopy__(self, memo) -> "Unset":
        return self
