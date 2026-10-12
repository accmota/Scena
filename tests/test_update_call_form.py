"""``on_update`` is called the same way with its call form cached.

Rule under test (Actors Design.md, "Dense tick"): the fleet loop calls each
``on_update`` with the payload its arity asks for — ``()``, ``(dt)`` for a
bound method, ``(owner)``, ``(owner, dt)`` — decided by ``_invoke_update``.
The dense list caches that decision per entry (``_update_call_form``) instead
of re-reading the arity every frame. The oracle is ``_invoke_update`` itself:
for every callable shape both pass the same arguments.

Bug class guarded: a cached decision that differs from the live rule (a
bound method given the owner, a ``*args`` hook given too little).
"""
import functools
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

P = sys.modules.get("scena.process")
if P is None:
    import scena.process  # noqa: F401
    P = sys.modules["scena.process"]


class Hook:
    def __init__(self, log):
        self.log = log

    def with_dt(self, dt):
        self.log.append(("m_dt", dt))

    def no_args(self):
        self.log.append(("m",))

    def star(self, *a):
        self.log.append(("m*",) + a)


def shapes(log):
    h = Hook(log)

    def f0():
        log.append(("f0",))

    def f1(e):
        log.append(("f1", e))

    def f2(e, dt):
        log.append(("f2", e, dt))

    def fstar(*a):
        log.append(("f*",) + a)

    def fdef(e, dt=0.5):
        log.append(("fdef", e, dt))

    return [h.with_dt, h.no_args, h.star, f0, f1, f2, fstar, fdef,
            lambda: log.append(("l0",)), lambda e: log.append(("l1", e)),
            lambda e, dt: log.append(("l2", e, dt)),
            functools.partial(f2, "bound"), functools.partial(f1)]


class TestSameCall(unittest.TestCase):
    def test_every_callable_shape(self):
        if not hasattr(P, "_update_call_form"):
            self.skipTest("call form cache not present")
        owner = object()
        for i, (a, b) in enumerate(zip(shapes(log_a := []), shapes(log_b := []))):
            P._invoke_update(a, owner, 0.25)
            P._call_update(b, P._update_call_form(b), owner, 0.25)
            self.assertEqual(log_a[-1], log_b[-1], f"shape {i}")
        self.assertEqual(len(log_a), len(log_b))


if __name__ == "__main__":
    unittest.main()
