"""A weak set that iterates in insertion order.

``weakref.WeakSet`` iterates in hash order, which is the objects' addresses:
work done while walking one ran in a different order on every run. The
``on_update`` fleet did (review 2026-10-09 S2-9), and so did the shape
transients: two dissolves ending in the same tick ran their ``on_done`` in
address order, the destroys reordered the collision list, and a ball's
bounce landed 10 px apart between two runs of the same game (RA3, 0.10.0).
An engine weak set that is walked is this one
(``tests/test_weak_set_order.py``).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator
from weakref import ref

__all__ = ["OrderedWeakSet"]


class _KeyedRef(ref):
    """A weak reference that knows its key: one shared callback per set
    instead of a closure per item."""

    __slots__ = ("key",)


class OrderedWeakSet:
    """``add`` / ``discard`` / ``in`` / ``len`` / iteration of a ``WeakSet``,
    iterating in the order the items were added. An item leaves when it is
    collected, as in a ``WeakSet``."""

    __slots__ = ("_refs", "_gone")

    def __init__(self, items: Iterable[Any] = ()) -> None:
        refs: Dict[int, _KeyedRef] = {}
        self._refs = refs

        def _gone(r, refs=refs):
            if refs.get(r.key) is r:
                del refs[r.key]

        self._gone = _gone
        for item in items:
            self.add(item)

    def add(self, item) -> None:
        key = id(item)
        if key in self._refs:
            return
        r = _KeyedRef(item, self._gone)
        r.key = key
        self._refs[key] = r

    def discard(self, item) -> None:
        r = self._refs.get(id(item))
        if r is not None and r() is item:
            del self._refs[id(item)]

    def clear(self) -> None:
        self._refs.clear()

    def __contains__(self, item) -> bool:
        r = self._refs.get(id(item))
        return r is not None and r() is item

    def __iter__(self) -> Iterator[Any]:
        # A list made in one pass: a caller may add or discard while it walks.
        live = [r() for r in self._refs.values()]
        return iter([o for o in live if o is not None])

    def __len__(self) -> int:
        return len(self._refs)

    def __bool__(self) -> bool:
        return bool(self._refs)
