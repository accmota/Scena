"""Counting the reactive graph without counting someone else's garbage.

Not a test module (no ``test_`` prefix). ``DependencyGraph.nodes`` is a
``WeakValueDictionary`` and every Container tree is a reference cycle, so
garbage an earlier test dropped stays in the count until the cyclic GC runs;
the GC-backstop finalizers then purge its nodes. A GC pass that lands between
a test's baseline and its final read makes the count drop, and the test fails
only in some orders (O1, O9 in Testing Design). A count of graph nodes is read
after ``full_collect()``: ``settled_graph_size()`` does both. A test that also
wants to see its own throwaways (a Container only the cyclic GC would free:
D11) counts inside ``gc_paused()``.

``tests/test_count_baselines.py`` fails on a graph count with no settle before
it.
"""
from __future__ import annotations

import gc
from contextlib import contextmanager


def full_collect(max_passes: int = 6) -> None:
    """``gc.collect()`` until a pass frees nothing: GC-backstop finalizers
    (``weakref.finalize`` graph purge) release more garbage on a later pass."""
    for _ in range(max_passes):
        if gc.collect() == 0:
            return


def settled_graph_size(ss=None) -> int:
    """Node count of the reactive graph once pending garbage is gone."""
    if ss is None:
        from scena.state import get_scena_system
        ss = get_scena_system()
    full_collect()
    return len(ss.dependency_graph.nodes)


@contextmanager
def gc_paused():
    """Cyclic GC off for the block (``gc.collect()`` still works): a count
    taken inside sees the test's own cyclic garbage instead of racing it."""
    was = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was:
            gc.enable()
