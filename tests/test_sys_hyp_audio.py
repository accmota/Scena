"""Audio ownership over real frames: a state machine against the offline mixer.

Rules: ``play_sound`` scene-scoped, entity-scoped (``e.play_sound``) and
mode-scoped (a bare call inside a mode body); stop a handle; pause / resume;
destroy an owner; change an owner's mode; park an owner; step frames. The
mixer runs offline (``tick_audio`` pumps it inside the process tick).

Invariants after every frame with ``dt > 0`` (Sound Design § Ownership):

* the mixer's live voices are exactly the voices of live (not done, not
  cancelled) sound handles — nothing that was cut plays on, and nothing that
  should play is missing (a cut voice's de-click ramp is not live);
* when an owner ends (destroy, mode leave) a live sound it owned has been
  released: no owner, game scope, no callbacks, and it ends by itself — no
  forever loop outlives its owner unless it is fading out (Sound Design —
  When the owner ends);
* ``on_done`` fires at most once, only on a natural end, never for a cancel,
  never after the owner died;
* no destroyed owner is referenced by a live handle.

    python -m unittest tests.test_sys_hyp_audio -v
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hypothesis import note, strategies as hst  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    Bundle, RuleBasedStateMachine, invariant, precondition, rule,
)

from system_support import SystemWorld, quiet, tone  # noqa: E402

from scena import Circle, play_sound  # noqa: E402
from scena.audio_mixer import get_mixer  # noqa: E402
from scena.process import get_scheduler  # noqa: E402

DURS = [0.05, 0.2, 0.6]


class AudioMachine(RuleBasedStateMachine):
    owners = Bundle("owners")
    sounds = Bundle("sounds")

    def __init__(self):
        super().__init__()
        self.w = SystemWorld(draw=False)
        self.probe = self.w.probe
        self.tones = {d: tone(d) for d in DURS}
        self.handles = []      # every handle ever made
        self.done_calls = {}   # index -> on_done count
        self.pool = {}         # owner key -> actor
        self.last_dt = 0.0
        self.origin = {}       # index -> (actor, "entity" | "mode") for owned sounds
        self.ended = {}        # index -> on_done count when its owner ended

    def _track_handle(self, h):
        idx = len(self.handles)
        self.handles.append(h)
        self.done_calls[idx] = 0
        return idx

    def _on_done(self, idx, owner=None):
        def fn(*_a):
            self.done_calls[idx] += 1
            if owner is not None:
                self.probe.hit("sound_done", owner)
        return fn

    @precondition(lambda self: len(self.pool) < 6)
    @rule(target=owners)
    def make_owner(self):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        key = len(self.pool)
        self.pool[key] = self.w.track(Circle(radius=3))
        return key

    @rule(target=sounds, d=hst.sampled_from(DURS), loops=hst.sampled_from([1, 2]))
    def play_scene(self, d, loops):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        idx = len(self.handles)
        h = play_sound(self.tones[d], loops=loops, on_done=self._on_done(idx))
        note(f"scene sound #{idx} d={d} loops={loops}")
        return self._track_handle(h)

    @rule(target=sounds, o=owners, d=hst.sampled_from(DURS))
    def play_entity(self, o, d):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        idx = len(self.handles)
        with quiet():
            h = a.play_sound(self.tones[d], on_done=self._on_done(idx, a))
        note(f"entity sound #{idx} on owner {o} (alive={a.is_alive})")
        self.origin[idx] = (a, "entity")
        return self._track_handle(h)

    @rule(target=sounds, o=owners, in_mode=hst.booleans())
    def play_loop(self, o, in_mode):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        idx = len(self.handles)
        made = []
        snd, cb = self.tones[0.2], self._on_done(idx, a)
        if in_mode:
            def looping(e):
                made.append(play_sound(snd, loops="forever", on_done=cb))
            with quiet():
                try:
                    self._set_mode(a, looping)
                except Exception:
                    pass  # dead owner: DestroyedError (no mode)
        else:
            with quiet():
                made.append(a.play_sound(snd, loops="forever", on_done=cb))
        if not made:
            return idx
        note(f"loop #{idx} on owner {o} in_mode={in_mode}")
        self.origin[idx] = (a, "mode" if in_mode else "entity")
        return self._track_handle(made[0])

    @rule(s=sounds)
    def fade_out(self, s):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        if s < len(self.handles):
            h = self.handles[s]
            if not (h.done or h.cancelled):
                h.fade_out(0.1)

    def _owner_ended(self, a, kinds):
        for idx, (owner, kind) in self.origin.items():
            if owner is a and kind in kinds and idx not in self.ended:
                self.ended[idx] = self.done_calls[idx]

    def _set_mode(self, a, fn):
        if a.is_alive:
            self._owner_ended(a, ("mode",))
        a.mode = fn

    @rule(target=sounds, o=owners, d=hst.sampled_from(DURS))
    def play_in_mode(self, o, d):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        idx = len(self.handles)
        made = []
        snd, cb = self.tones[d], self._on_done(idx, a)

        def singing(e):
            made.append(play_sound(snd, on_done=cb))

        with quiet():
            try:
                self._set_mode(a, singing)
            except Exception:
                pass  # dead owner: DestroyedError (no mode)
        if not made:
            return idx  # nothing started (dead owner); index stays unused
        note(f"mode sound #{idx} on owner {o}")
        self.origin[idx] = (a, "mode")
        return self._track_handle(made[0])

    @rule(s=sounds)
    def stop(self, s):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        if s < len(self.handles):
            self.handles[s].cancel()

    @rule(s=sounds, pause=hst.booleans())
    def pause(self, s, pause):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        if s < len(self.handles):
            h = self.handles[s]
            with quiet():
                h.pause() if pause else h.resume()

    @rule(o=owners)
    def destroy_owner(self, o):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        if a.is_alive:
            self._owner_ended(a, ("entity", "mode"))
        with quiet():
            a.destroy()

    @rule(o=owners)
    def leave_mode(self, o):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        if a.is_alive:
            self._set_mode(a, None)

    @rule(o=owners, on=hst.booleans())
    def park(self, o, on):
        self.last_dt = 0.0  # mixer commands wait for the next pumped frame
        a = self.pool[o]
        if a.is_alive:
            a.active = on

    @rule(n=hst.integers(1, 8), dt=hst.sampled_from([0.0, 1 / 60, 1 / 30, 0.1]))
    def step(self, n, dt):
        with quiet():
            self.w.step(n, dt=dt)
        self.last_dt = dt

    @invariant()
    def voices_match_live_handles(self):
        if self.last_dt <= 0.0:
            return  # a zero-length frame does not pump the mixer
        # A voice that ended while its owner was parked has no voice left but
        # a live Handle: its on_done waits for the resume (X-life-4), and
        # fires on the first tick after it (so right after a resume the owner
        # may already be active). Only a live owner holds one.
        held = [h for h in self.handles if h._end_held and not (h.done or h.cancelled)]
        for h in held:
            assert h._live_owner() is not None, "an end held for a dead owner"
        live = {h._voice_id for h in self.handles
                if not (h.done or h.cancelled or h._end_held) and h._voice_id is not None}
        voices = get_mixer().live_voice_ids()
        assert voices == live, f"mixer voices {sorted(voices)} != live handles {sorted(live)}"

    @invariant()
    def on_done_rules(self):
        for idx, n in self.done_calls.items():
            h = self.handles[idx]
            assert n <= 1, f"on_done fired {n} times for #{idx}"
            if h.cancelled:
                assert n == 0, f"on_done fired for cancelled #{idx}"
        dead = self.probe.dead_calls()
        assert dead == [], f"on_done after owner death: {dead}"

    @invariant()
    def owner_end_releases_or_cuts(self):
        for idx, count in self.ended.items():
            h = self.handles[idx]
            assert self.done_calls[idx] == count, f"on_done after owner end #{idx}"
            if h.done or h.cancelled:
                continue
            assert h.owner is None, f"live #{idx} still owned after its owner ended"
            assert h.scope == "game", f"released #{idx} scope {h.scope!r}"
            assert h._fn is None and h._then is None, f"released #{idx} kept a callback"
            if h._sound_loops < 0:
                assert h._sound_fade_out is not None, (
                    f"forever loop #{idx} outlived its owner without a fade_out")

    @invariant()
    def no_dead_owner_on_live_handle(self):
        for h in get_scheduler()._sound:
            owner = h.owner
            if owner is not None and not h.cancelled and not h.done:
                assert owner.is_alive, f"live sound handle owned by dead {owner!r}"

    def teardown(self):
        try:
            for h in self.handles:
                h.cancel()
            self.handles.clear()
            self.pool.clear()
        finally:
            self.w.teardown()


TestAudioMachine = AudioMachine.TestCase


if __name__ == "__main__":
    unittest.main()
