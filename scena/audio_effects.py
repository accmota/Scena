"""Curated audio effects: LowPass, HighPass, Echo, Reverb, Distortion, Wavefold.

Construct-to-place on ``h.effects`` / ``mic.effects`` — ``.add`` / ``.enabled``
/ ``.remove`` / ``.clear``. Knobs are plain attributes read every mix block.
"""
from __future__ import annotations

import math
import numbers
from typing import Any, List, Optional, Sequence, Tuple

import numpy as np

from .audio_mixer import SAMPLE_RATE, set_effect_processor
from .closed import ClosedSurface, closed_setattr
from .validate import expect_bool as _expect_flag

_TAIL_FLOOR = 0.02
_TAIL_CAP_S = 4.0
_REVERB_COMB_G = 0.84
_REVERB_LONGEST_COMB_MS = 43.7
_REVERB_TAIL_FRAC = 0.6
_ECHO_DECAY_MAX = 0.95


def _knob(value, default: float, lo: float, hi: float) -> float:
    """Finite knob clamped to ``[lo, hi]``. Non-finite falls back to ``default``."""
    v = float(value)
    if not math.isfinite(v):
        v = float(default)
    return max(lo, min(hi, v))


def _delay_line(buf: np.ndarray, idx: int, n: int, x: np.ndarray, step):
    """Run ``x`` through a delay line of ``n`` samples: ``(out, buf, idx)``.

    Sample ``i`` reads what sample ``i - n`` wrote (``buf`` holds the last
    ``n`` writes, the oldest at ``idx``); ``step(read, x) -> (out, written)``.
    So a run of ``n`` samples reads only the run before it, and numpy takes a
    whole run per step: the same float32 operations in the same order as a
    loop over samples, bit for bit, at a fraction of the cost (a per-sample
    loop made Reverb ~1.4 s per second of audio on a slower machine, too slow
    for a live voice and a bake that tripped the stall watch: WP32).
    """
    length = x.shape[0]
    hist = np.empty((n + length,) + x.shape[1:], dtype=buf.dtype)
    hist[:n] = np.roll(buf, -idx, axis=0)
    out = np.empty_like(x)
    for k in range(0, length, n):
        m = min(n, length - k)
        out[k:k + m], hist[n + k:n + k + m] = step(hist[k:k + m], x[k:k + m])
    idx = (idx + length) % n
    return out, np.roll(hist[length:], idx, axis=0), idx


def _effect_tail_seconds(effect: Any) -> float:
    if effect is None or not getattr(effect, "enabled", True):
        return 0.0
    fn = getattr(effect, "_tail_seconds", None)
    if fn is None:
        return 0.0
    try:
        return max(0.0, float(fn()))
    except Exception:
        return 0.0


def max_tail_seconds(effects: Sequence[Any]) -> float:
    """Extra seconds after dry EOF so Echo/Reverb tails are not clipped."""
    if not effects:
        return 0.0
    return min(_TAIL_CAP_S, max((_effect_tail_seconds(fx) for fx in effects), default=0.0))


_KNOBS: dict = {}


def _live_knobs(cls) -> frozenset:
    """The numeric knobs of an effect class: its constructor's number parameters."""
    hit = _KNOBS.get(cls)
    if hit is None:
        import inspect
        from .validate import _sig_info
        sig = inspect.signature(inspect.unwrap(cls.__init__))
        hit = _KNOBS[cls] = frozenset(_sig_info(sig)[4])
    return hit


class AudioEffect(ClosedSurface):
    """One named processor. Does nothing until ``.add``'d onto a stack."""

    def __init_subclass__(cls, **kwargs):
        if "__init__" in cls.__dict__:
            from .validate import guard_init_numbers
            guard_init_numbers(cls)
        # Last: ClosedSurface seals outside the numbers guard.
        super().__init_subclass__(**kwargs)

    def __init__(self):
        self.enabled = True
        self._stack: Optional["AudioEffectStack"] = None
        self._state = None

    def __setattr__(self, name: str, value: Any) -> None:
        # A knob is read on the audio thread every block. A live write that is
        # not a number raises here, at the author's line: ``fx.cutoff = None``
        # was taken and raised on the device thread, which stopped every sound
        # (AU11). A number out of range or non-finite stays legal: the block
        # falls back and clamps (Sound Design, "Effects"). Numpy scalars pass.
        if name[0] != "_" and name in _live_knobs(type(self)) and (
            isinstance(value, bool) or not isinstance(value, numbers.Real)
        ):
            from .validate import _short_repr
            raise TypeError(
                f"{type(self).__name__}.{name} expected a number, got "
                f"{type(value).__name__} {_short_repr(value)}"
            )
        closed_setattr(self, name, value)

    __setattr__._scena_private_passthrough = True

    def _reset_state(self) -> None:
        self._state = None

    def _tail_seconds(self) -> float:
        return 0.0

    def _fingerprint(self) -> Tuple[Any, ...]:
        return (type(self).__name__,)

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        return frames

    def remove(self) -> None:
        """Take this effect off the stack it was added to (no-op if none)."""
        stack = self._stack
        if stack is not None:
            stack.remove(self)


class LowPass(AudioEffect):
    """One-pole low-pass: keeps the lows, muffles the highs ("behind a wall").

    ``h.effects.add(LowPass())``. ``cutoff`` can be changed live
    (``fx.cutoff = 800``); it is read every audio block.

    Args:
        cutoff: corner frequency in Hz (default 300; clamped to 1 Hz …
            0.45 × sample rate).
    """

    def __init__(self, cutoff: float = 300.0):
        super().__init__()
        self.cutoff = float(cutoff)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("LowPass", round(float(self.cutoff), 3))

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        cutoff = _knob(self.cutoff, 300.0, 1.0, sample_rate * 0.45)
        alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / sample_rate)
        y = np.empty_like(frames)
        prev = self._state
        if prev is None:
            prev = np.zeros(frames.shape[1], dtype=np.float64)
        acc = prev.astype(np.float64).tolist()
        a = float(alpha)
        for c, xs in enumerate(frames.astype(np.float64).T.tolist()):
            lp, ys = acc[c], []
            for x in xs:
                lp += a * (x - lp)
                ys.append(lp)
            acc[c] = lp
            y[:, c] = ys
        self._state = np.array(acc, dtype=np.float32)
        return y.astype(np.float32)


class HighPass(AudioEffect):
    """One-pole high-pass: keeps the highs, thins out the lows ("radio" / "phone").

    Args:
        cutoff: corner frequency in Hz (default 2000; clamped to 1 Hz …
            0.45 × sample rate). Live, like ``LowPass.cutoff``.
    """

    def __init__(self, cutoff: float = 2000.0):
        super().__init__()
        self.cutoff = float(cutoff)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("HighPass", round(float(self.cutoff), 3))

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        cutoff = _knob(self.cutoff, 2000.0, 1.0, sample_rate * 0.45)
        alpha = 1.0 - np.exp(-2.0 * np.pi * cutoff / sample_rate)
        y = np.empty_like(frames)
        prev = self._state
        if prev is None:
            prev = np.zeros(frames.shape[1], dtype=np.float64)
        state = prev.astype(np.float64).tolist()
        a = float(alpha)
        for c, xs in enumerate(frames.astype(np.float64).T.tolist()):
            lp, ys = state[c], []
            for x in xs:
                lp += a * (x - lp)
                ys.append(x - lp)
            state[c] = lp
            y[:, c] = ys
        self._state = np.array(state, dtype=np.float32)
        return y.astype(np.float32)


class Echo(AudioEffect):
    """Feedback delay: each repeat comes back ``delay`` seconds later, quieter.

    After a sound ends, its voice keeps playing until the echo tail fades.

    Args:
        delay: seconds between repeats (default 0.25; ``<= 0`` is dry).
        decay: loudness kept per repeat, 0–0.95 (default 0.6).
    """

    def __init__(self, delay: float = 0.25, decay: float = 0.6):
        super().__init__()
        self.delay = float(delay)
        self.decay = float(decay)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("Echo", round(float(self.delay), 4), round(float(self.decay), 4))

    def _echo_knobs(self) -> Tuple[float, float]:
        """``(delay_seconds, decay)``. Bad delay → ``(0, 0)`` (dry, no tail)."""
        delay = float(self.delay)
        if not math.isfinite(delay) or delay <= 0.0:
            return 0.0, 0.0
        decay = float(self.decay)
        if not math.isfinite(decay):
            decay = 0.0
        decay = max(0.0, min(decay, _ECHO_DECAY_MAX))
        return delay, decay

    def _tail_seconds(self) -> float:
        delay, decay = self._echo_knobs()
        if delay <= 0.0 or decay <= 0.0:
            return 0.0
        decay = max(decay, 1e-3)
        # delay * log(floor) / log(decay) — perceptual floor, not RT60.
        return min(_TAIL_CAP_S, delay * math.log(_TAIL_FLOOR) / math.log(decay))

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        delay, decay = self._echo_knobs()
        if delay <= 0.0 or frames.size == 0:
            return frames
        n_delay = max(1, int(round(delay * sample_rate)))
        buf, idx = self._state if self._state is not None else (None, 0)
        if buf is None or buf.shape[0] != n_delay or buf.shape[1] != frames.shape[1]:
            buf = np.zeros((n_delay, frames.shape[1]), dtype=np.float32)
            idx = 0
        def echo(read, x):
            mixed = x + read * decay
            return mixed, mixed

        out, buf, idx = _delay_line(buf, idx, n_delay, frames, echo)
        self._state = (buf, idx)
        return out


class Reverb(AudioEffect):
    """Room reverb (simple Schroeder: parallel combs + series allpasses).

    Not a convolution reverb. The voice drains its tail after the sound ends.

    Args:
        size: room size, 0.05–1.5 (default 1.0).
        mix: wet share, 0 (dry) – 1 (default 0.6).
    """

    def __init__(self, size: float = 1.0, mix: float = 0.6):
        super().__init__()
        self.size = float(size)
        self.mix = float(mix)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("Reverb", round(float(self.size), 4), round(float(self.mix), 4))

    def _reverb_knobs(self) -> Tuple[float, float]:
        size = _knob(self.size, 1.0, 0.05, 1.5)
        mix = _knob(self.mix, 0.6, 0.0, 1.0)
        return size, mix

    def _tail_seconds(self) -> float:
        size, mix = self._reverb_knobs()
        if mix <= 0.0:
            return 0.0
        t_comb = (_REVERB_LONGEST_COMB_MS * 0.001) * size
        # RT60 ≈ −3 * delay / log10(g); take a perceptual fraction of full RT60.
        rt60 = -3.0 * t_comb / math.log10(_REVERB_COMB_G)
        return min(_TAIL_CAP_S, _REVERB_TAIL_FRAC * rt60)

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        if frames.size == 0:
            return frames
        size, mix = self._reverb_knobs()
        comb_ms = np.array([29.7, 37.1, 41.1, 43.7], dtype=np.float64) * size
        ap_ms = np.array([5.0, 1.7], dtype=np.float64) * size
        comb_n = np.maximum(1, np.round(comb_ms * 0.001 * sample_rate).astype(np.int64))
        ap_n = np.maximum(1, np.round(ap_ms * 0.001 * sample_rate).astype(np.int64))
        state = self._state
        nch = frames.shape[1]
        if state is None or state.get("nch") != nch or tuple(state["comb_n"]) != tuple(comb_n):
            state = {
                "nch": nch,
                "comb_n": comb_n.copy(),
                "ap_n": ap_n.copy(),
                "comb": [np.zeros((int(n), nch), dtype=np.float32) for n in comb_n],
                "comb_i": [0] * len(comb_n),
                "ap": [np.zeros((int(n), nch), dtype=np.float32) for n in ap_n],
                "ap_i": [0] * len(ap_n),
            }
        comb_g = _REVERB_COMB_G
        src = frames.astype(np.float32)
        wet = np.zeros_like(src)
        def comb(read, x):
            # Feedback comb y = x + g·y[n samples ago]: the output is what it
            # writes, the sound Reverb has always had (the per-sample loop's
            # read was a view of the slot it then overwrote).
            y = x + read * comb_g
            return y, y

        for c, n in enumerate(comb_n):
            acc, state["comb"][c], state["comb_i"][c] = _delay_line(
                state["comb"][c], state["comb_i"][c], int(n), src, comb)
            wet += acc
        # Each comb's DC gain is 1/(1-g). Scale the bank back to about unity.
        n_combs = max(1, len(state["comb"]))
        wet *= (1.0 - comb_g) / float(n_combs)
        ap_g = 0.7

        def allpass(read, x):
            # Schroeder allpass: y = buf - g x, buf = x + g y. Unity gain.
            y = read - ap_g * x
            return y, x + ap_g * y

        for a, n in enumerate(ap_n):
            wet, state["ap"][a], state["ap_i"][a] = _delay_line(
                state["ap"][a], state["ap_i"][a], int(n), wet, allpass)
        self._state = state
        return (src * (1.0 - mix) + wet * mix).astype(np.float32)


class Distortion(AudioEffect):
    """Grit: asymmetric tanh waveshaper with light pre/de-emphasis.

    Loudness is normalized, so ``drive`` changes the character, not the volume.

    Args:
        drive: how hard the signal is pushed (default 8; > 0).
    """

    def __init__(self, drive: float = 8.0):
        super().__init__()
        self.drive = float(drive)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("Distortion", round(float(self.drive), 3))

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        if frames.size == 0:
            return frames
        drive = _knob(self.drive, 8.0, 0.1, 1e6)
        src = frames.astype(np.float64)
        # One-pole high-shelf-ish pre-emphasis (~3 kHz).
        alpha = 1.0 - np.exp(-2.0 * np.pi * 3000.0 / sample_rate)
        nch = src.shape[1]
        state = self._state
        if (
            not isinstance(state, tuple)
            or len(state) != 4
            or getattr(state[0], "shape", None) != (nch,)
            or getattr(state[1], "shape", None) != (nch,)
        ):
            lp_pre = np.zeros(nch, dtype=np.float64)
            lp_de = np.zeros(nch, dtype=np.float64)
            env_in = 0.0
            env_out = 0.0
        else:
            lp_pre = np.asarray(state[0], dtype=np.float64)
            lp_de = np.asarray(state[1], dtype=np.float64)
            env_in = float(state[2])
            env_out = float(state[3])
        alpha = float(alpha)
        # The one-pole filters and the envelope are sequential: Python floats
        # per channel (the same double arithmetic as numpy on a row, without
        # its per-sample overhead: WP32).
        lp_pre = lp_pre.tolist()
        pre = np.empty_like(src)
        for c, xs in enumerate(src.T.tolist()):
            lp, ys = lp_pre[c], []
            for x in xs:
                lp += alpha * (x - lp)
                ys.append(x + 0.55 * (x - lp))
            lp_pre[c] = lp
            pre[:, c] = ys
        # Asymmetric tanh: small DC offset → even + odd harmonics.
        shaped = np.tanh((pre + 0.08) * drive) / max(math.tanh(drive), 1e-12)
        lp_de = lp_de.tolist()
        out = np.empty_like(shaped)
        for c, xs in enumerate(shaped.T.tolist()):
            lp, ys = lp_de[c], []
            for x in xs:
                lp += alpha * (x - lp)
                ys.append(x - 0.35 * (x - lp))
            lp_de[c] = lp
            out[:, c] = ys
        # Stateful peak envelope (~30 ms), not a per-block max. A short mix
        # block and a bake of the same samples take the same path.
        release = math.exp(-1.0 / max(float(sample_rate) * 0.03, 1.0))
        gains = []
        peaks = zip(np.max(np.abs(src), axis=1).tolist(), np.max(np.abs(out), axis=1).tolist())
        for peak_in, peak_out in peaks:
            env_in = max(peak_in, env_in * release)
            env_out = max(peak_out, env_out * release)
            gains.append((env_in * 1.1) / max(env_out, 1e-12))
        out *= np.array(gains, dtype=np.float64)[:, None]
        self._state = (
            np.array(lp_pre, dtype=np.float32),
            np.array(lp_de, dtype=np.float32),
            float(env_in),
            float(env_out),
        )
        return out.astype(np.float32)


class Wavefold(AudioEffect):
    """Triangle wavefolder — metallic / arcade, not overdrive.

    Args:
        drive: folds per peak (default 3; > 0). Higher is brighter.
    """

    def __init__(self, drive: float = 3.0):
        super().__init__()
        self.drive = float(drive)

    def _fingerprint(self) -> Tuple[Any, ...]:
        return ("Wavefold", round(float(self.drive), 3))

    def _process(self, frames: np.ndarray, sample_rate: int) -> np.ndarray:
        drive = _knob(self.drive, 3.0, 0.1, 1e6)
        x = frames.astype(np.float64) * drive
        # Triangle fold into ±1.
        folded = np.abs(np.mod(x + 1.0, 4.0) - 2.0) - 1.0
        return folded.astype(np.float32)


def apply_effects(
    frames: np.ndarray,
    effects: Sequence[Any],
    sample_rate: int,
) -> np.ndarray:
    out = frames
    for fx in effects:
        if fx is None or not getattr(fx, "enabled", True):
            continue
        proc = getattr(fx, "_process", None)
        if proc is None:
            continue
        out = proc(out, sample_rate)
    return out


set_effect_processor(apply_effects)


class AudioEffectStack(ClosedSurface):
    """``.add`` / ``.enabled`` / ``.remove`` / ``.clear`` — same shape as post FX."""

    _closed_who = "effects"

    def __init__(self, *, handle=None, microphone=None):
        self._items: List[AudioEffect] = []
        self._enabled = True
        self._handle = handle
        self._microphone = microphone

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value) -> None:
        self._enabled = _expect_flag(value, 'enabled')
        self._sync()

    def add(self, effect: AudioEffect) -> AudioEffect:
        if not isinstance(effect, AudioEffect):
            raise TypeError(
                f"effects.add expected LowPass/HighPass/Echo/Reverb/Distortion/Wavefold, "
                f"got {type(effect).__name__}"
            )
        if effect not in self._items:
            self._items.append(effect)
        effect._stack = self
        self._sync()
        return effect

    def remove(self, effect: AudioEffect) -> None:
        if effect in self._items:
            self._items.remove(effect)
        if getattr(effect, "_stack", None) is self:
            effect._stack = None
        self._sync()

    def clear(self) -> None:
        for fx in list(self._items):
            fx._stack = None
        self._items.clear()
        self._sync()

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def live(self) -> tuple:
        if not self.enabled:
            return ()
        return tuple(self._items)

    def _sync(self) -> None:
        handle = self._handle
        if handle is not None and getattr(handle, "_voice_id", None) is not None:
            from .audio_mixer import get_mixer
            get_mixer().set_effects(handle._voice_id, self.live())
