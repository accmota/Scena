"""Audio ownership over real frames: a state machine against the offline mixer.

Rules: ``play_sound`` scene-scoped, entity-scoped (``e.play_sound``) and
mode-scoped (a bare call inside a mode body); stop a handle; pause / resume;
destroy an owner; change an owner's mode; park an owner; step frames. The
stress rules (2026-10-27, Testing Design "Audio stress"): ``fade_to``; a
named slot replaced, cut or crossfaded; the master bus; effects added and
removed; a streamed file; a missing file; a voice whose source raises
mid-play. The mixer runs offline (``tick_audio`` pumps it inside the process
tick).

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
* no destroyed owner is referenced by a live handle;
* a source that raises ends its own voice only, and the tick reports it: no
  fault waits in the mixer after a pumped frame (Sound Design, "Failure
  contract").

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

from media_support import media  # noqa: E402

from scena import Circle, Sound, audio, play_sound  # noqa: E402
from scena.audio_effects import Echo, LowPass  # noqa: E402
from scena.audio_mixer import FrameSource, get_mixer  # noqa: E402
from scena.process import get_scheduler  # noqa: E402

import numpy as np  # noqa: E402

DURS = [0.05, 0.2, 0.6]


class _Raises(FrameSource):
    """Plays silence, then raises: a file that goes bad mid-play."""

    path = "goes_bad.wav"

    def __init__(self, at):
        self.n, self.at = 0, at

    def remaining_seconds(self, pitch, sample_rate=44100):
        return 1.0

    def pull(self, n_frames, pitch):
        self.n += 1
        if self.n >= self.at:
            raise OSError("the file went bad")
        return np.zeros((int(n_frames), 2), dtype=np.float32), None


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
        self.slots = {}        # name -> index of the handle holding the slot
        self.replaced = set()  # indexes a named slot cut (never an on_done)
        self.stream = Sound(media("audio", "laser-big.wav"), stream=True)
        self.broken = {}       # id(Sound) -> pull at which its source raises
        self.keep = []         # those Sounds (an id is not reused while they live)
        real = Sound._frame_source

        def frame_source(snd, loops):
            at = self.broken.get(id(snd))
            return _Raises(at) if at is not None else real(snd, loops)
        Sound._frame_source = frame_source
        self._real_frame_source = real

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

    @rule(s=sounds, v=hst.sampled_from([0.0, 0.5, 1.5]))
    def fade_to(self, s, v):
        self.last_dt = 0.0
        if s < len(self.handles):
            h = self.handles[s]
            if not (h.done or h.cancelled):
                h.fade_to(v, time=0.05)

    @rule(target=sounds, name=hst.sampled_from(["music", "ambience"]),
          crossfade=hst.sampled_from([None, 0.0, 0.1]), forever=hst.booleans())
    def play_named(self, name, crossfade, forever):
        """A named slot: the handle it replaces is cut (cancelled, no on_done)."""
        self.last_dt = 0.0
        idx = len(self.handles)
        kw = {} if crossfade is None else {"crossfade": crossfade}
        h = play_sound(self.tones[0.6], name=name, loops="forever" if forever else 1,
                       on_done=self._on_done(idx), **kw)
        old = self.slots.get(name)
        self.slots[name] = idx
        note(f"named #{idx} {name!r} crossfade={crossfade} replaces {old}")
        idx = self._track_handle(h)
        if old is not None:
            prev = self.handles[old]
            if not (prev.done or prev.cancelled):
                self.replaced.add(old)              # live when its slot was taken
            if not crossfade:
                assert prev.done or prev.cancelled, f"#{old} still holds slot {name!r}"
        return idx

    @rule(target=sounds, loops=hst.sampled_from([1, 2]))
    def play_stream(self, loops):
        self.last_dt = 0.0
        idx = len(self.handles)
        h = play_sound(self.stream, loops=loops, volume=0.2, on_done=self._on_done(idx))
        note(f"stream #{idx} loops={loops}")
        return self._track_handle(h)

    @rule(target=sounds)
    def play_missing(self):
        self.last_dt = 0.0
        idx = len(self.handles)
        with quiet():
            h = play_sound("no_such_sound.wav", on_done=self._on_done(idx))
        return self._track_handle(h)

    @rule(target=sounds, at=hst.integers(1, 4), forever=hst.booleans())
    def play_goes_bad(self, at, forever):
        self.last_dt = 0.0
        snd = Sound._from_pcm(self.tones[0.6]._samples)
        self.broken[id(snd)] = at
        idx = len(self.handles)
        h = play_sound(snd, loops="forever" if forever else 1, on_done=self._on_done(idx))
        self.keep.append(snd)
        note(f"goes bad #{idx} at pull {at}")
        return self._track_handle(h)

    @rule(s=sounds, which=hst.sampled_from(["lowpass", "echo", "clear"]))
    def effects(self, s, which):
        self.last_dt = 0.0
        if s < len(self.handles):
            h = self.handles[s]
            if h.done or h.cancelled:
                return
            if which == "clear":
                h.effects.clear()
            else:
                h.effects.add(LowPass(cutoff=800) if which == "lowpass" else Echo(delay=0.05))

    @rule(volume=hst.sampled_from([0.0, 0.5, 1.0]), muted=hst.booleans())
    def master(self, volume, muted):
        audio.volume = volume
        audio.muted = muted

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
            if idx in self.replaced:
                assert n == 0, f"on_done fired for #{idx}, cut by its named slot"
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

    @invariant()
    def faults_are_reported_on_the_tick(self):
        if self.last_dt <= 0.0:
            return
        assert get_mixer()._faults == [], "a fault waits in the mixer after a pumped frame"

    def teardown(self):
        Sound._frame_source = self._real_frame_source
        audio.volume = 1.0
        audio.muted = False
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
