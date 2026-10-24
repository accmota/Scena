"""Engine weak sets that are walked iterate in insertion order.

Bug class: ``weakref.WeakSet`` iterates in hash order, the objects' addresses,
so work done while walking one runs in a different order on every run. Two
dissolves ending in the same tick ran their ``on_done`` (a destroy each) in
address order; the destroys reordered the collision list, and in
``platformer`` a ball's bounce landed 10 px apart between two runs of the same
input (the deep tier's chaos idle twin, about one run in three; RA3, 0.10.0).
The on_update fleet had the same bug before (review 2026-10-09 S2-9).

Checked: every ``WeakSet(...)`` built in ``scena/`` is one that is never
walked (or walked only to close devices at shutdown), with the reason; the
rest use ``scena._weakset.OrderedWeakSet``; that set keeps insertion order;
transients that end in the same tick call ``on_done`` in the order they
started, wherever the objects live in memory.

    python tests/run_tiers.py focused test_weak_set_order
"""
from __future__ import annotations

import ast
import gc
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from source_support import iter_files  # noqa: E402
from system_support import FRAME, system_world  # noqa: E402

from scena._weakset import OrderedWeakSet  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENA = os.path.join(ROOT, "scena")

# (file, name) -> why a plain WeakSet is fine there.
PLAIN_WEAK_SETS = {
    ("closed.py", "_seal_wrappers"): "membership only (`in`), never walked",
    ("hitbox.py", "_LIVE_PARTS"): "membership only (add / discard), never walked",
    ("formula_check.py", "_STALE_CODES"): "membership only (`in`), never walked",
    ("audio_capture.py", "_live_mics"): "walked only to close the devices at shutdown",
}


def _weak_set_sites():
    """``(file, assigned name)`` of every ``WeakSet(...)`` call in scena/."""
    out = set()
    for path in iter_files(SCENA, ".py", recursive=False):
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            fn = call.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if called != "WeakSet":
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                label = t.id if isinstance(t, ast.Name) else getattr(t, "attr", "?")
                out.add((name, label))
    return out


class TestEveryWalkedWeakSetKeepsOrder(unittest.TestCase):
    def test_plain_weak_sets_are_the_listed_ones(self):
        self.assertEqual(sorted(_weak_set_sites()), sorted(PLAIN_WEAK_SETS),
                         "a weak set that is walked must be an OrderedWeakSet; one that is "
                         "never walked goes in PLAIN_WEAK_SETS with the reason")

    def test_the_listed_ones_are_not_walked(self):
        for (fname, label), why in PLAIN_WEAK_SETS.items():
            if "walked only" in why:
                continue
            with open(os.path.join(SCENA, fname), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            with self.subTest(site=f"{fname}:{label}"):
                self.assertEqual(_walks_of(tree, label), [], f"{label} is walked: make it an OrderedWeakSet")


def _names(node, label) -> bool:
    return (isinstance(node, ast.Name) and node.id == label) or (
        isinstance(node, ast.Attribute) and node.attr == label)


def _walks_of(tree, label):
    """Lines where ``label`` is iterated: a ``for`` / comprehension over it, or
    ``list`` / ``tuple`` / ``sorted`` / ``set`` of it."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)) and _names(node.iter, label):
            out.append(getattr(node, "lineno", getattr(node.iter, "lineno", 0)))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in ("list", "tuple", "sorted", "set") and node.args
              and _names(node.args[0], label)):
            out.append(node.lineno)
    return out


class TestOrderedWeakSet(unittest.TestCase):
    class Item:
        pass

    def test_insertion_order_whatever_the_addresses(self):
        items = [self.Item() for _ in range(50)]
        random.Random(3).shuffle(items)
        s = OrderedWeakSet(items)
        self.assertEqual(list(s), items)

    def test_set_operations(self):
        a, b, c = self.Item(), self.Item(), self.Item()
        s = OrderedWeakSet()
        s.add(a); s.add(b); s.add(a)
        self.assertEqual(list(s), [a, b])
        self.assertIn(a, s)
        self.assertNotIn(c, s)
        s.discard(a); s.discard(c)
        self.assertEqual(list(s), [b])
        s.add(a)                                  # back in: now last
        self.assertEqual(list(s), [b, a])
        self.assertEqual(len(s), 2)
        s.clear()
        self.assertFalse(s)

    def test_a_collected_item_leaves(self):
        a, b = self.Item(), self.Item()
        s = OrderedWeakSet([a, b])
        del a
        gc.collect()
        self.assertEqual(list(s), [b])
        self.assertEqual(len(s), 1)


class TestTransientsEndInStartOrder(unittest.TestCase):
    def test_on_done_order_is_the_start_order(self):
        from scena import Circle
        rng = random.Random(7)
        pad = []
        for trial in range(6):
            pad.append([object() for _ in range(rng.randrange(1, 4000))])   # move the addresses
            with system_world(draw=False) as w:
                shapes = [Circle(center=(20 * i, 50), radius=5) for i in range(8)]
                order = list(range(8))
                rng.shuffle(order)
                done = []
                for i in order:                   # all end in the same tick
                    shapes[i].fade_out(0.2, on_done=lambda i=i: done.append(i))
                w.step(30, dt=FRAME)
                with self.subTest(trial=trial):
                    self.assertEqual(done, order)
                for s in shapes:
                    s.destroy()


if __name__ == "__main__":
    unittest.main()
