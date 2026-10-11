"""Property-based tests for ``@when`` / ``@on_change`` (Hypothesis).

Model (Reactive Design — events; Actors Design — ``@when`` lifetime):

* A watch is seeded at registration (no fire). Each **poll** evaluates it; if
  the value differs from the last seen one, the new value is remembered and
  ``@on_change`` fires with it; ``@when`` fires only when the new value is
  ``True`` (rising edge).
* Inside a frame batch (``begin_frame_batch``) polls happen **only** at
  ``flush()`` — values that change and change back within one frame are never
  seen (glitch-free). Watches poll in registration order.
* Outside a batch, an ink write polls immediately.
* A destroyed source retires the watch quietly at the next poll; it never
  fires again. ``unregister_event`` stops a watch at once.
* ``flush()`` repeats polling until quiet (callbacks that write are relayed
  within the same flush); a cycle stops after ``FLUSH_MAX_ROUNDS`` rounds in
  which a watch fires again.
* A method watch dies with its owner (``destroy`` drops it at once); parking
  (``active = False``) does not suppress it.

    python -m unittest tests.test_hyp_events -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis_support import WorldTracker, boot, fresh_world  # noqa: E402
from hypothesis import given, note, strategies as hst  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    Bundle, RuleBasedStateMachine, invariant, multiple, precondition, rule,
)

from scena import Entity, on_change, when  # noqa: E402
from scena.events import get_global_event_system, unregister_event  # noqa: E402
from scena.state import FLUSH_MAX_ROUNDS, DestroyedError, get_scena_system  # noqa: E402

boot()

values = hst.integers(min_value=-5, max_value=5)
thresholds = hst.integers(min_value=-3, max_value=3)


class Watch:
    """Model of one registration."""

    def __init__(self, kind, sources, evaluate, func):
        self.kind = kind          # "when" | "change" | "relay"
        self.sources = sources    # [Source]
        self.evaluate = evaluate  # () -> value, from the model
        self.func = func          # decorated function (for unregister)
        self.old = None
        self.active = True
        self.relay_to = None

    def __repr__(self):
        return f"<{self.kind} watch on {[s.name for s in self.sources]}>"


class Source:
    def __init__(self, name, ent, value):
        self.name = name
        self.ent = ent
        self.value = value
        self.alive = True

    def __repr__(self):
        return self.name


class EventMachine(RuleBasedStateMachine):
    """Author code: ink writes, destroys, registrations, frames, flushes."""

    sources = Bundle("sources")
    watches = Bundle("watches")

    def __init__(self):
        super().__init__()
        self.world = WorldTracker()
        self.ss = get_scena_system()
        self.ss.begin_frame_batch()
        self.deferring = True
        self.log = []        # actual fires: (watch, payload)
        self.expected = []   # model fires
        self.watch_list = [] # registration order
        self.n = 0

    def teardown(self):
        self.world.teardown()

    # ---------------------------------------------------------------- model
    def _poll_model(self):
        """One flush: rounds of polls in registration order until quiet.

        Only a round in which a watch fires *again* (it already fired in this
        flush) counts toward ``FLUSH_MAX_ROUNDS`` (SY5); the flush stops after
        that many. The model counted every round, so a relay cycle whose
        first round was all first fires ran one round more in the engine
        (gate, 2026-10-11)."""
        fired_before = set()
        repeat_rounds = 0
        while True:
            fired = repeated = False
            for w in self.watch_list:
                if not w.active:
                    continue
                if any(not s.alive for s in w.sources):
                    w.active = False   # destroyed source retires quietly
                    continue
                v = w.evaluate()
                if v == w.old:
                    continue
                w.old = v
                if w.kind == "when" and not v:
                    continue
                self.expected.append((w, None if w.kind == "when" else v))
                fired = True
                if id(w) in fired_before:
                    repeated = True
                fired_before.add(id(w))
                if w.kind == "relay" and w.relay_to.alive:
                    w.relay_to.value = v
            if not fired:
                return
            if repeated:
                repeat_rounds += 1
                if repeat_rounds >= FLUSH_MAX_ROUNDS:
                    return

    def _after_write(self):
        if not self.deferring:
            self._poll_model()

    # ---------------------------------------------------------------- rules
    @rule(target=sources, value=values)
    def new_source(self, value):
        self.n += 1
        e = self.world.track(Entity())
        e.v = value
        src = Source(f"s{self.n}", e, value)
        self._after_write()  # a first ink write may poll outside a batch
        return src

    @rule(src=sources, value=values)
    def write(self, src, value):
        if not src.alive:
            try:
                src.ent.v = value
            except DestroyedError:
                return
            raise AssertionError(f"write to destroyed {src} accepted")
        src.ent.v = value
        src.value = value
        self._after_write()

    @rule(src=sources, a=values, b=values)
    def bounce(self, src, a, b):
        """Two writes in a row: inside a frame only the last one is visible."""
        if not src.alive:
            return
        src.ent.v = a
        src.value = a
        self._after_write()
        src.ent.v = b
        src.value = b
        self._after_write()

    @rule(src=sources)
    def destroy_source(self, src):
        src.ent.destroy()
        src.alive = False

    def _register(self, kind, srcs, evaluate, cond, relay_to=None):
        w = Watch(kind, srcs, evaluate, None)
        log = self.log

        if kind == "when":
            def fn():
                log.append((w, None))
            deco = when(cond)
        else:
            if relay_to is not None:
                def fn(value):
                    log.append((w, value))
                    if relay_to.ent.is_alive:
                        relay_to.ent.v = value
            else:
                def fn(value):
                    log.append((w, value))
            deco = on_change(cond)
        w.relay_to = relay_to
        dead = any(not s.alive for s in srcs)
        deco(fn)
        w.func = fn
        if dead:
            w.active = False
        else:
            w.old = evaluate()
        self.watch_list.append(w)
        return w

    @rule(target=watches, src=sources, k=thresholds)
    def watch_when(self, src, k):
        e = src.ent
        return self._register("when", [src], lambda: src.value > k,
                              lambda e=e, k=k: e.v > k)

    @rule(target=watches, src=sources)
    def watch_change(self, src):
        e = src.ent
        return self._register("change", [src], lambda: src.value, lambda e=e: e.v)

    @rule(target=watches, a=sources, b=sources)
    def watch_sum(self, a, b):
        ea, eb = a.ent, b.ent
        return self._register("change", [a, b], lambda: a.value + b.value,
                              lambda ea=ea, eb=eb: ea.v + eb.v)

    @precondition(lambda self: len(self.watch_list) < 12)
    @rule(target=watches, a=sources, b=sources)
    def watch_relay(self, a, b):
        """``@on_change(a)`` copies into ``b`` (a handler that writes)."""
        if a is b:
            return multiple()
        ea = a.ent
        return self._register("relay", [a], lambda: a.value, lambda ea=ea: ea.v,
                              relay_to=b)

    @rule(w=watches)
    def unregister(self, w):
        unregister_event(w.func)
        w.active = False

    @rule()
    def flush(self):
        self.ss.flush()
        self._poll_model()

    @rule()
    def end_frame(self):
        """End the batch the way the run loop does: flush, then stop deferring."""
        if not self.deferring:
            return
        self.ss.flush()
        self._poll_model()
        self.ss.end_frame_batch()
        self.deferring = False

    @rule()
    def begin_frame(self):
        if self.deferring:
            return
        self.ss.begin_frame_batch()
        self.deferring = True

    # ----------------------------------------------------------- invariants
    @invariant()
    def fires_match_model(self):
        assert self.log == self.expected, (
            f"fires differ\n  actual:   {self.log}\n  expected: {self.expected}"
        )

    @invariant()
    def no_retired_watch_is_registered(self):
        es = get_global_event_system()
        live = {id(r.callback) for r in es._events if not r._drop and r.callback}
        for w in self.watch_list:
            if not w.active and all(s.alive for s in w.sources):
                # Unregistered explicitly: gone from the system at once.
                assert id(w.func) not in live, f"{w} still registered after unregister"


TestEventModel = EventMachine.TestCase


class TestRelayCycleRounds(unittest.TestCase):
    """The case the gate found (2026-10-11): three relays in a cycle. The
    first round is all first fires, so it does not count toward
    ``FLUSH_MAX_ROUNDS``: 27 fires, not 24. The model counted every round."""

    def test_first_fires_do_not_count_toward_the_round_limit(self):
        m = EventMachine()

        def check():
            m.fires_match_model()
            m.no_retired_watch_is_registered()
        try:
            s0 = m.new_source(value=1)
            s1 = m.new_source(value=1)
            m.watch_relay(a=s1, b=s0)
            m.write(src=s1, value=0)
            s2 = m.new_source(value=0)
            m.watch_relay(a=s2, b=s1)
            m.bounce(a=0, b=1, src=s2)
            check()
            m.watch_relay(a=s0, b=s2)
            m.end_frame()                         # the flush runs the cycle
            self.assertEqual(len(m.log), 27)      # 9 rounds of 3 relays
            check()                               # the model agrees
        finally:
            m.teardown()


class TestGlitchFree(unittest.TestCase):
    """Within one frame, only the frame-end value is observed."""

    @given(frames=hst.lists(hst.lists(values, max_size=5), min_size=1, max_size=6),
           k=thresholds, start=values)
    def test_when_sees_frame_end_rising_edges(self, frames, k, start):
        with fresh_world() as w:
            e = w.track(Entity())
            e.v = start
            ss = get_scena_system()
            fires = []

            @when(lambda: e.v > k)
            def rose():
                fires.append(e.v)

            changes = []

            @on_change(lambda: e.v)
            def changed(value):
                changes.append(value)

            prev, prev_bool = start, start > k
            want_fires, want_changes = [], []
            for writes in frames:
                ss.begin_frame_batch()
                for v in writes:
                    e.v = v
                ss.flush()
                ss.end_frame_batch()
                now = e.v
                if now != prev:
                    want_changes.append(now)
                if (now > k) and not prev_bool:
                    want_fires.append(now)
                prev, prev_bool = now, now > k
            note(f"fires={fires} changes={changes}")
            self.assertEqual(changes, want_changes)
            self.assertEqual(fires, want_fires)

    @given(writes=hst.lists(values, max_size=12), k=thresholds, start=values)
    def test_eager_writes_see_every_edge(self, writes, k, start):
        with fresh_world() as w:
            e = w.track(Entity())
            e.v = start
            fires = []

            @when(lambda: e.v > k)
            def rose():
                fires.append(e.v)

            want, prev = [], start > k
            for v in writes:
                e.v = v
                if v > k and not prev:
                    want.append(v)
                prev = v > k
            self.assertEqual(fires, want)


class TestOwnerLifetime(unittest.TestCase):
    """Method watches die with their owner, survive parking, and never fire late."""

    @given(ops=hst.lists(hst.one_of(
        hst.tuples(hst.just("write"), values),
        hst.tuples(hst.just("park"), hst.booleans()),
        hst.tuples(hst.just("destroy"), hst.none()),
    ), max_size=15), k=thresholds)
    def test_method_when_lifetime(self, ops, k):
        with fresh_world() as w:
            src = w.track(Entity())
            src.v = 0
            fires = []

            class Watcher(Entity):
                @when(lambda self: src.v > k)
                def rose(self):
                    fires.append(src.v)

            owner = w.track(Watcher())
            ss = get_scena_system()
            want, prev, alive = [], 0 > k, True
            for op, arg in ops:
                if op == "write":
                    src.v = arg
                    ss.flush()
                    if alive and arg > k and not prev:
                        want.append(arg)
                    prev = arg > k
                elif op == "park" and alive:
                    owner.active = arg
                elif op == "destroy":
                    owner.destroy()
                    alive = False
            self.assertEqual(fires, want)
            if not alive:
                es = get_global_event_system()
                owners = [r._owner for r in es._events if not r._drop]
                self.assertNotIn(owner, owners)


class TestLinksUnderFrames(unittest.TestCase):
    """Geometry links written from every frame phase stay consistent (system).

    A chain ``s0.center.x → s1.center.x → s2.radius → s3["angle"]`` (a
    magnitude and a property-backed field in the middle) is fed by placement
    writes to ``s0`` from ``update``, a timer, a collision handler, or the
    pre-draw window, inside real frames (``tests/system_support.py``). After
    every frame each link equals a direct recompute, and ``@when`` fires once
    per rising edge **as seen at flush** — a pre-draw write is seen at the next
    frame's flush (Scena Design § Frame order).
    """

    @given(writes=hst.lists(hst.tuples(
        hst.sampled_from(["update", "timer", "collide", "pre_draw", "none"]),
        hst.integers(-40, 40).map(float)), min_size=1, max_size=25),
        k=hst.integers(-20, 20).map(float), thr=hst.integers(0, 6).map(float))
    def test_chain_matches_recompute_and_edges(self, writes, k, thr):
        from unittest import mock
        from system_support import quiet, system_world
        from scena import Circle, after, collide_stay

        with system_world(draw=False) as w:
            s0 = w.track(Circle(center=(0, 0), radius=2))
            s1 = w.track(Circle(center=(0, 50), radius=2))
            s2 = w.track(Circle(center=(0, 100), radius=2))
            s3 = w.track(Circle(center=(0, 150), radius=2))
            s1["center"] @= (lambda: (s0.center.x + k, 50))
            s2["radius"] @= (lambda: s1.center.x * 0.1 + 1)
            s3["angle"] @= (lambda: s2.radius * 2)
            fired = []

            @when(lambda: s2.radius > thr)
            def _rose():
                fired.append(1)

            w.track(Circle(center=(500, 500), radius=5, group="lx_a"))
            w.track(Circle(center=(500, 500), radius=5, group="lx_b"))
            pending = {}

            def do(phase):
                if pending.get("phase") == phase:
                    s0.move_to(pending.pop("x"), 0)
                    pending.pop("phase")

            @collide_stay("lx_a", "lx_b")
            def _stay(a, b, info=None):
                do("collide")

            w.on_update(lambda dt: do("update"))
            fw = w.fw
            real_pre = fw._tick_pre_draw

            snaps = []

            def pre():
                real_pre()
                # Read the chain inside the batch (a read between frames,
                # outside any batch, would poll @when eagerly — not a frame).
                snaps.append((s0.center.x, s1.center.x, s2.radius, s3.angle))
                do("pre_draw")

            patch = mock.patch.object(fw, "_tick_pre_draw", side_effect=pre)
            patch.start()
            try:
                w.step(1)
                x_at_flush = 0.0
                x_now = 0.0
                # The watch is seeded at registration (no fire for a True seed).
                prev_cond = max(0.0, (x_at_flush + k) * 0.1 + 1) > thr
                want_fires = 0
                for phase, x in writes:
                    if phase != "none":
                        pending.update(phase=phase, x=x)
                        if phase == "timer":
                            after(0, lambda: do("timer"))
                    with quiet():
                        w.step(1)
                    # Model: what flush saw this frame.
                    if phase in ("update", "timer", "collide"):
                        x_at_flush = x
                        x_now = x
                    else:
                        x_at_flush = x_now          # previous pre-draw writes included
                        if phase == "pre_draw":
                            x_now = x
                    cond = max(0.0, (x_at_flush + k) * 0.1 + 1) > thr
                    if cond and not prev_cond:
                        want_fires += 1
                    prev_cond = cond
                    self.assertEqual(len(fired), want_fires,
                                     f"@when edges differ from the flush-time model ({phase})")
                    # Links equal a direct recompute (pull on read), as seen
                    # in this frame's pre-draw tick (before its own write).
                    x0, x1, r2, rot3 = snaps[-1]
                    self.assertAlmostEqual(x0, x_at_flush)
                    self.assertAlmostEqual(x1, x_at_flush + k)
                    r = max(0.0, (x_at_flush + k) * 0.1 + 1)
                    self.assertAlmostEqual(r2, r)
                    self.assertAlmostEqual(rot3 % 360, (r * 2) % 360)
            finally:
                patch.stop()


if __name__ == "__main__":
    unittest.main()
