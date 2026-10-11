"""Internal audio mixer: voices, command queue, pure ``render()``.

The miniaudio device callback (when a real device is running) only calls
``Mixer.render_block``. Author code never runs on the audio thread.
Tests call ``render()`` / ``Mixer.render_block`` with no device.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

SAMPLE_RATE = 44100
CHANNELS = 2
STREAM_THRESHOLD_S = 8.0
DEFAULT_LEVEL_TAU = 0.08
_KNEE = 0.9
_SQRT2 = math.sqrt(2.0)
# Bake refuses a rate change that would allocate more than this (30 min).
MAX_BAKE_FRAMES = SAMPLE_RATE * 60 * 30
# A cut (CMD_CANCEL) ramps an audible voice to silence over this many frames
# (~5 ms) instead of dropping the waveform mid-cycle, which clicks.
DECLICK_FRAMES = 220


def require_finite(
    name: str,
    value,
    *,
    positive: bool = False,
    non_negative: bool = False,
) -> float:
    """Author-facing number check. Non-finite raises; range is optional."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise TypeError(
                f"{name} expected a number, got {type(value).__name__} {value!r}"
            ) from None
    else:
        v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite")
    if positive and v <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    if non_negative and v < 0.0:
        raise ValueError(f"{name} must be finite and >= 0")
    return v


def _safe_volume(value) -> float:
    v = float(value)
    return v if math.isfinite(v) else 0.0


def _safe_pan(value) -> float:
    v = float(value)
    return v if math.isfinite(v) else 0.0


def _safe_pitch(value) -> float:
    v = float(value)
    return v if math.isfinite(v) and v > 1e-12 else 1e-12

# Command ops (plain tuples). Optional trailing int is at_frame inside the block.
CMD_START = "start"
CMD_SET_VOLUME = "set_volume"
CMD_SET_PAN = "set_pan"
CMD_SET_PITCH = "set_pitch"
CMD_CANCEL = "cancel"
CMD_FINISH = "finish"
CMD_SET_EFFECTS = "set_effects"
CMD_SET_HELD = "set_held"

_REQUIRED_LEN = {
    CMD_START: 3,
    CMD_SET_VOLUME: 3,
    CMD_SET_PAN: 3,
    CMD_SET_PITCH: 3,
    CMD_CANCEL: 2,
    CMD_FINISH: 2,
    CMD_SET_EFFECTS: 3,
    CMD_SET_HELD: 3,
}


def _as_stereo(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.shape[1] == 1:
        arr = np.repeat(arr, 2, axis=1)
    elif arr.shape[1] > 2:
        arr = arr[:, :2]
    return np.ascontiguousarray(arr, dtype=np.float32)


def pcm_from_decoded(decoded) -> np.ndarray:
    """Convert a miniaudio ``DecodedSoundFile`` to ``(N, 2)`` float32."""
    raw = np.asarray(decoded.samples, dtype=np.float32)
    nch = int(getattr(decoded, "nchannels", 0) or 0)
    if raw.ndim == 1 and nch > 0:
        raw = raw.reshape(-1, nch)
    return _as_stereo(raw)


def make_silence(duration: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    n = max(0, int(round(float(duration) * sample_rate)))
    return np.zeros((n, 2), dtype=np.float32)


def make_sine(
    freq: float,
    duration: float,
    *,
    amp: float = 0.5,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    n = int(round(float(duration) * sample_rate))
    t = np.arange(n, dtype=np.float64) / sample_rate
    mono = (float(amp) * np.sin(2.0 * np.pi * float(freq) * t)).astype(np.float32)
    return np.column_stack([mono, mono])


def linear_pan_gains(volume: float, pan: float) -> Tuple[float, float]:
    """``pan`` −1 left … 0 center … +1 right. Center is unity on both channels.

    Non-finite ``pan`` is center. Non-finite ``volume`` is silence. Finite
    pan outside ±1 still clamps.
    """
    p = _safe_pan(pan)
    p = max(-1.0, min(1.0, p))
    v = _safe_volume(volume)
    return v * min(1.0, 1.0 - p), v * min(1.0, 1.0 + p)


def soft_limit(block: np.ndarray, knee: float = _KNEE) -> np.ndarray:
    """Tanh-style soft clip: identity below ``knee``, never exceeds ±1."""
    if block.size == 0:
        return block
    if not np.isfinite(block).all():
        block = np.nan_to_num(block, nan=0.0, posinf=1e6, neginf=-1e6)
    ax = np.abs(block)
    over = ax > knee
    if not np.any(over):
        return block
    out = block.copy()
    head = max(1.0 - knee, 1e-12)
    sign = np.sign(block[over])
    excess = ax[over] - knee
    out[over] = sign * (knee + head * np.tanh(excess / head))
    return np.clip(out, -1.0, 1.0)


def rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


def loudness(block: np.ndarray) -> float:
    """0..1: full-scale sine ≈ 1.0 (RMS × √2). Non-finite blocks read as silence."""
    level = rms(block) * _SQRT2
    if not math.isfinite(level):
        return 0.0
    return min(1.0, level)


_SPECTRUM_F_LO = 40.0
_SPECTRUM_F_HI = 16000.0
DEFAULT_SPECTRUM_BINS = 32


def spectrum_band_hz_edges(
    bins: int = DEFAULT_SPECTRUM_BINS,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Log-spaced band edges in Hz from ~40 Hz to min(16 kHz, Nyquist)."""
    bins = max(1, int(bins))
    nyquist = float(sample_rate) * 0.5
    f_hi = min(_SPECTRUM_F_HI, nyquist)
    f_lo = min(_SPECTRUM_F_LO, f_hi * 0.5)
    return np.geomspace(f_lo, f_hi, bins + 1)


def spectrum_bands(
    block: np.ndarray,
    bins: int = DEFAULT_SPECTRUM_BINS,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    """Log-frequency band magnitudes in 0..1 (peak band of a full-scale sine ≈ 1).

    Edges run ~40 Hz … min(16 kHz, Nyquist), so FFT bin 0 (DC) is excluded.
    """
    bins = max(1, int(bins))
    if block.size == 0:
        return np.zeros(bins, dtype=np.float32)
    mono = np.mean(block, axis=1).astype(np.float64, copy=False) if block.ndim == 2 else block.astype(np.float64)
    n = int(mono.shape[0])
    if n < 2:
        return np.zeros(bins, dtype=np.float32)
    windowed = mono * np.hanning(n)
    mag = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(n, d=1.0 / float(sample_rate))
    hz_edges = spectrum_band_hz_edges(bins, sample_rate)
    # Hann coherent gain is ~0.5, so a full-scale sine peaks near n/4
    # (rfft bin is n/2, times the window). Half-scale therefore peaks near 0.5.
    ref = max(n / 4.0, 1e-12)
    out = np.zeros(bins, dtype=np.float32)
    for i in range(bins):
        a = int(np.searchsorted(freqs, hz_edges[i], side="left"))
        b = int(np.searchsorted(freqs, hz_edges[i + 1], side="left"))
        b = max(b, a + 1)
        a = min(a, mag.shape[0] - 1)
        b = min(b, mag.shape[0])
        if a >= b:
            continue
        out[i] = min(1.0, float(np.max(mag[a:b]) / ref))
    return out


def ema_alpha(block_dt: float, tau: float) -> float:
    tau = float(tau)
    if not math.isfinite(tau) or tau <= 0.0:
        raise ValueError("audio.level_tau must be finite and > 0")
    if block_dt <= 0.0:
        return 0.0
    return float(1.0 - math.exp(-block_dt / tau))


class FrameSource:
    """Pluggable pull: decoded buffer, file stream, microphone, silence."""

    def pull(self, n_frames: int, pitch: float) -> Tuple[np.ndarray, Optional[int]]:
        raise NotImplementedError

    def remaining_seconds(self, pitch: float, sample_rate: int = SAMPLE_RATE) -> float:
        return 0.0


class BufferSource(FrameSource):
    """In-memory ``(N, 2)`` float32. ``loops=-1`` is forever."""

    __slots__ = ("samples", "pos", "loops", "lap")

    def __init__(self, samples: np.ndarray, loops: int = 1):
        self.samples = _as_stereo(samples)
        self.pos = 0.0
        self.loops = int(loops)
        self.lap = 0

    def remaining_seconds(self, pitch: float, sample_rate: int = SAMPLE_RATE) -> float:
        n = int(self.samples.shape[0])
        if n <= 0:
            return 0.0
        p = max(float(pitch), 1e-12)
        left = max(0.0, n - self.pos) / (sample_rate * p)
        if self.loops < 0:
            return left
        laps_left = max(0, self.loops - self.lap - 1)
        return left + laps_left * (n / (sample_rate * p))

    def pull(self, n_frames: int, pitch: float) -> Tuple[np.ndarray, Optional[int]]:
        n_frames = int(n_frames)
        out = np.zeros((n_frames, 2), dtype=np.float32)
        if n_frames <= 0:
            return out, None
        buf = self.samples
        n = int(buf.shape[0])
        if n <= 0:
            return out, 0
        p = float(pitch) if pitch > 1e-12 else 1e-12
        written = 0
        finished_at: Optional[int] = None
        while written < n_frames:
            if self.pos >= n:
                more = self.loops < 0 or (self.lap + 1) < self.loops
                if more:
                    self.lap += 1
                    self.pos -= n
                    if self.pos < 0.0:
                        self.pos = 0.0
                    continue
                finished_at = written
                break
            remaining = n_frames - written
            idx = self.pos + p * np.arange(remaining, dtype=np.float64)
            valid = idx < n
            take = int(np.count_nonzero(valid))
            if take <= 0:
                self.pos = float(n)
                continue
            idx = idx[:take]
            i0 = np.floor(idx).astype(np.int64)
            frac = (idx - i0).astype(np.float32)[:, None]
            i0 = np.clip(i0, 0, n - 1)
            i1 = np.clip(i0 + 1, 0, n - 1)
            out[written:written + take] = buf[i0] * (1.0 - frac) + buf[i1] * frac
            self.pos = float(idx[-1] + p)
            written += take
        if finished_at is None and self.pos >= n:
            more = self.loops < 0 or (self.lap + 1) < self.loops
            if more:
                self.lap += 1
                self.pos -= n
                if self.pos < 0.0:
                    self.pos = 0.0
            else:
                finished_at = n_frames
        return out, finished_at


class PullSource(FrameSource):
    """Wraps a callback ``(n_frames) -> (N, 2)`` (microphone / live). Never finishes."""

    __slots__ = ("_pull",)

    def __init__(self, pull: Callable[[int], np.ndarray]):
        self._pull = pull

    def remaining_seconds(self, pitch: float, sample_rate: int = SAMPLE_RATE) -> float:
        return float("inf")

    def pull(self, n_frames: int, pitch: float) -> Tuple[np.ndarray, Optional[int]]:
        chunk = _as_stereo(self._pull(int(n_frames)))
        if chunk.shape[0] == n_frames:
            return chunk, None
        out = np.zeros((n_frames, 2), dtype=np.float32)
        n = min(n_frames, chunk.shape[0])
        if n:
            out[:n] = chunk[:n]
        return out, None


class Voice:
    """Mixer-owned render state. Main thread never mutates this after start."""

    __slots__ = (
        "voice_id", "source", "volume", "pan", "pitch", "finished",
        "effects", "level_ema", "spectrum_ema", "draining", "tail_left",
        "held", "declick_left",
    )

    def __init__(
        self,
        voice_id: int,
        source: FrameSource,
        *,
        volume: float = 1.0,
        pan: float = 0.0,
        pitch: float = 1.0,
        effects: Optional[Sequence[Any]] = None,
    ):
        self.voice_id = int(voice_id)
        self.source = source
        self.volume = _safe_volume(volume)
        self.pan = _safe_pan(pan)
        self.pitch = _safe_pitch(pitch)
        self.finished = False
        self.effects: Tuple[Any, ...] = tuple(effects) if effects else ()
        self.level_ema = 0.0
        self.spectrum_ema: Optional[np.ndarray] = None
        self.draining = False
        self.tail_left = 0.0
        self.held = False
        # Frames left in the de-click ramp of a cut voice (finished, not live).
        self.declick_left = 0


def _effects_tail_seconds(effects: Sequence[Any]) -> float:
    """Import lazily so audio_effects can register the processor without a cycle."""
    if not effects:
        return 0.0
    try:
        from .audio_effects import max_tail_seconds
        return float(max_tail_seconds(effects))
    except Exception:
        return 0.0

class CommandQueue:
    """Append on the main thread, drain on the render thread. Tuples only."""

    def __init__(self) -> None:
        self._q: deque = deque()

    def push(self, cmd: tuple) -> None:
        self._q.append(cmd)

    def drain(self) -> List[tuple]:
        out: List[tuple] = []
        while self._q:
            out.append(self._q.popleft())
        return out


def _split_cmd(cmd: tuple) -> Tuple[tuple, int]:
    op = cmd[0]
    need = _REQUIRED_LEN.get(op, len(cmd))
    if len(cmd) > need:
        return cmd[:need], int(cmd[need])
    return cmd, 0


def _apply_cmd(voices: Dict[int, Voice], cmd: tuple, *, declick: bool = False) -> None:
    """Apply one command. ``declick=True`` (a render with frames to fill):
    a cut of an audible voice keeps it for a ``DECLICK_FRAMES`` ramp."""
    op = cmd[0]
    if op == CMD_START:
        vid = int(cmd[1])
        spec = cmd[2]
        if vid in voices:
            return
        source = spec.get("source")
        if source is None:
            samples = spec.get("samples")
            loops = int(spec.get("loops", 1))
            source = BufferSource(samples if samples is not None else make_silence(0.0), loops=loops)
        voices[vid] = Voice(
            vid,
            source,
            volume=_safe_volume(spec.get("volume", 1.0)),
            pan=_safe_pan(spec.get("pan", 0.0)),
            pitch=_safe_pitch(spec.get("pitch", 1.0)),
            effects=spec.get("effects"),
        )
        return
    vid = int(cmd[1])
    voice = voices.get(vid)
    if voice is None:
        return
    if op == CMD_SET_VOLUME:
        voice.volume = _safe_volume(cmd[2])
    elif op == CMD_SET_PAN:
        voice.pan = _safe_pan(cmd[2])
    elif op == CMD_SET_PITCH:
        voice.pitch = _safe_pitch(cmd[2])
    elif op == CMD_CANCEL or op == CMD_FINISH:
        if voice.finished:
            return  # already cut; a de-click ramp in progress keeps going
        voice.finished = True
        # A finish (fade_out reached 0) and a held voice are already silent.
        if declick and op == CMD_CANCEL and not voice.held and voice.volume > 0.0:
            voice.declick_left = DECLICK_FRAMES
        else:
            voices.pop(vid, None)
    elif op == CMD_SET_EFFECTS:
        voice.effects = tuple(cmd[2]) if cmd[2] is not None else ()
    elif op == CMD_SET_HELD:
        voice.held = bool(cmd[2])


def _process_effects(
    frames: np.ndarray,
    effects: Sequence[Any],
    sample_rate: int,
) -> np.ndarray:
    if not effects:
        return frames
    apply = _effect_processor
    if apply is None:
        return frames
    return apply(frames, effects, sample_rate)


_effect_processor: Optional[Callable] = None


def set_effect_processor(fn: Optional[Callable]) -> None:
    global _effect_processor
    _effect_processor = fn


class RenderResult:
    __slots__ = (
        "block", "finished_ids", "raw_rms", "raw_level", "raw_spectrum",
        "master_level", "master_spectrum", "voice_levels", "voice_spectra",
        "voice_remaining", "voice_dry", "deferred",
    )

    def __init__(
        self,
        block: np.ndarray,
        finished_ids: List[Tuple[int, int]],
        raw_rms: float = 0.0,
        raw_level: float = 0.0,
        raw_spectrum: Optional[np.ndarray] = None,
        master_level: float = 0.0,
        master_spectrum: Optional[np.ndarray] = None,
        voice_levels: Optional[Dict[int, float]] = None,
        voice_spectra: Optional[Dict[int, np.ndarray]] = None,
        voice_remaining: Optional[Dict[int, float]] = None,
        voice_dry: Optional[Dict[int, np.ndarray]] = None,
        deferred: Optional[Sequence[tuple]] = None,
    ):
        self.block = block
        self.finished_ids = finished_ids
        self.raw_rms = raw_rms
        self.raw_level = raw_level
        self.raw_spectrum = (
            raw_spectrum if raw_spectrum is not None
            else np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
        )
        self.master_level = master_level
        self.master_spectrum = master_spectrum if master_spectrum is not None else self.raw_spectrum
        self.voice_levels = voice_levels if voice_levels is not None else {}
        self.voice_spectra = voice_spectra if voice_spectra is not None else {}
        self.voice_remaining = voice_remaining if voice_remaining is not None else {}
        self.voice_dry = voice_dry if voice_dry is not None else {}
        self.deferred = list(deferred) if deferred else []


class AnalysisState:
    __slots__ = ("master_level", "master_spectrum", "voice_level", "voice_spectrum")

    def __init__(self) -> None:
        self.master_level = 0.0
        self.master_spectrum: Optional[np.ndarray] = None
        self.voice_level: Dict[int, float] = {}
        self.voice_spectrum: Dict[int, np.ndarray] = {}


def _render_declick(voice: Voice, mix: np.ndarray, a: int, seg: int, sample_rate: int) -> None:
    """Mix the next frames of a cut voice under a linear ramp to silence.

    The voice is already finished (reported at the cut frame, not live): no
    dry slot, no analysis, and no Echo/Reverb tail after the ramp.
    """
    k = min(int(seg), int(voice.declick_left))
    if k <= 0:
        voice.declick_left = 0
        return
    if voice.draining:
        frames = np.zeros((k, 2), dtype=np.float32)
    else:
        frames, _done_at = voice.source.pull(k, voice.pitch)
    frames = _process_effects(frames, voice.effects, sample_rate)
    left = int(voice.declick_left)
    ramp = (left - 1 - np.arange(k, dtype=np.float64)) / float(DECLICK_FRAMES)
    gL, gR = linear_pan_gains(voice.volume, voice.pan)
    wet = frames.astype(np.float64, copy=False)
    mix[a:a + k, 0] += wet[:k, 0] * ramp * gL
    mix[a:a + k, 1] += wet[:k, 1] * ramp * gR
    voice.declick_left = left - k


def render(
    voices: Dict[int, Voice],
    n_frames: int,
    commands: Sequence[tuple] = (),
    *,
    sample_rate: int = SAMPLE_RATE,
    master_volume: float = 1.0,
    muted: bool = False,
    level_tau: float = DEFAULT_LEVEL_TAU,
    analysis: Optional[AnalysisState] = None,
    spectrum_bins: int = DEFAULT_SPECTRUM_BINS,
    compute_spectrum: bool = True,
) -> RenderResult:
    """Mix ``n_frames``. Mutates voice positions. Commands apply in order.

    A command may carry a trailing ``at_frame`` so a mid-block volume/pan/pitch
    change takes effect only from that sample onward (not retroactively).

    ``compute_spectrum=False`` skips ``spectrum_bands`` (FFT) while still updating
    loudness EMAs. Tests and the pure ``render()`` API default to ``True`` so
    spectrum assertions keep working without an interest latch.
    """
    n_frames = int(n_frames)
    if n_frames < 0:
        n_frames = 0
    parsed = [_split_cmd(tuple(c)) for c in commands]
    if n_frames == 0:
        # Do not touch analysis EMAs. Immediate commands still apply; a
        # future at_frame is returned so the mixer can run it later.
        finished_now: List[Tuple[int, int]] = []
        deferred_now: List[tuple] = []
        for cmd, at in parsed:
            if at <= 0:
                if cmd[0] == CMD_CANCEL or cmd[0] == CMD_FINISH:
                    vid = int(cmd[1])
                    if vid in voices and not voices[vid].finished:
                        finished_now.append((vid, 0))
                _apply_cmd(voices, cmd)
            else:
                deferred_now.append(cmd + (int(at),))
        if analysis is None:
            analysis = AnalysisState()
        held_spec = (
            analysis.master_spectrum.copy()
            if analysis.master_spectrum is not None
            else np.zeros(spectrum_bins, dtype=np.float32)
        )
        return RenderResult(
            np.zeros((0, 2), dtype=np.float32),
            finished_now,
            master_level=float(analysis.master_level),
            master_spectrum=held_spec,
            deferred=deferred_now,
        )
    cuts = {0, n_frames}
    for _cmd, at in parsed:
        if 0 < at < n_frames:
            cuts.add(int(at))
    points = sorted(cuts)
    pending = list(parsed)
    mix = np.zeros((n_frames, 2), dtype=np.float64)
    finished: List[Tuple[int, int]] = []
    voice_dry: Dict[int, np.ndarray] = {}

    def _apply_due(frame: int) -> None:
        still = []
        for cmd, at in pending:
            if at <= frame:
                if cmd[0] == CMD_CANCEL or cmd[0] == CMD_FINISH:
                    vid = int(cmd[1])
                    if vid in voices and not voices[vid].finished:
                        finished.append((vid, frame))
                _apply_cmd(voices, cmd, declick=True)
            else:
                still.append((cmd, at))
        pending.clear()
        pending.extend(still)

    _apply_due(0)
    for a, b in zip(points, points[1:]):
        seg = b - a
        if seg <= 0:
            continue
        live = list(voices.items())
        for vid, voice in live:
            if voice.finished:
                if voice.declick_left > 0:
                    _render_declick(voice, mix, a, seg, sample_rate)
                    if voice.declick_left <= 0:
                        voices.pop(vid, None)
                continue
            if voice.held:
                # Hold: silence, cursor/effects/tail frozen. Stay in voices.
                frames = np.zeros((seg, 2), dtype=np.float32)
                slot = voice_dry.get(vid)
                if slot is None:
                    slot = np.zeros((n_frames, 2), dtype=np.float32)
                    voice_dry[vid] = slot
                slot[a:b] = frames
                continue
            frames, done_at = voice.source.pull(seg, voice.pitch)
            if voice.draining:
                # Source already exhausted; keep feeding silence through the chain.
                frames = np.zeros((seg, 2), dtype=np.float32)
                frames = _process_effects(frames, voice.effects, sample_rate)
                voice.tail_left -= seg / float(sample_rate) if sample_rate else 0.0
                finish_now = voice.tail_left <= 0.0
                finish_at = seg if finish_now else None
            else:
                frames = _process_effects(frames, voice.effects, sample_rate)
                finish_now = False
                finish_at = None
                if done_at is not None:
                    tail = _effects_tail_seconds(voice.effects)
                    already = (seg - int(done_at)) / float(sample_rate) if sample_rate else 0.0
                    if tail > 0.0:
                        voice.draining = True
                        voice.tail_left = tail - already
                        if voice.tail_left <= 0.0:
                            finish_now = True
                            finish_at = seg
                    else:
                        finish_now = True
                        finish_at = int(done_at)
            gL, gR = linear_pan_gains(voice.volume, voice.pan)
            wet = frames.astype(np.float64, copy=False)
            mix[a:b, 0] += wet[:, 0] * gL
            mix[a:b, 1] += wet[:, 1] * gR
            slot = voice_dry.get(vid)
            if slot is None:
                slot = np.zeros((n_frames, 2), dtype=np.float32)
                voice_dry[vid] = slot
            slot[a:b] = frames
            if finish_now:
                voice.finished = True
                finished.append((vid, a + int(finish_at if finish_at is not None else seg)))
                voices.pop(vid, None)
        _apply_due(b)

    master = float(master_volume)
    gain = 0.0 if muted or not math.isfinite(master) else master
    mix *= gain
    limited = soft_limit(mix.astype(np.float32, copy=False))
    raw_rms = rms(limited)
    raw_level = loudness(limited)
    block_dt = n_frames / float(sample_rate) if sample_rate else 0.0
    alpha = ema_alpha(block_dt, level_tau) if n_frames > 0 else 0.0

    if analysis is None:
        analysis = AnalysisState()
    analysis.master_level += (raw_level - analysis.master_level) * alpha

    zero_spec = np.zeros(spectrum_bins, dtype=np.float32)
    if compute_spectrum:
        raw_spec = spectrum_bands(limited, bins=spectrum_bins, sample_rate=sample_rate)
        if analysis.master_spectrum is None or analysis.master_spectrum.shape[0] != raw_spec.shape[0]:
            analysis.master_spectrum = raw_spec.copy()
        else:
            analysis.master_spectrum += (raw_spec - analysis.master_spectrum) * alpha
    else:
        raw_spec = zero_spec
        if analysis.master_spectrum is None:
            analysis.master_spectrum = zero_spec.copy()

    v_levels: Dict[int, float] = {}
    v_specs: Dict[int, np.ndarray] = {}
    v_rem: Dict[int, float] = {}
    live_ids = set(voices.keys()) | set(voice_dry.keys())
    stale = [vid for vid in analysis.voice_level if vid not in live_ids]
    for vid in stale:
        analysis.voice_level.pop(vid, None)
        analysis.voice_spectrum.pop(vid, None)
    for vid, dry in voice_dry.items():
        v_raw = loudness(dry)
        prev = analysis.voice_level.get(vid, 0.0)
        analysis.voice_level[vid] = prev + (v_raw - prev) * alpha
        v_levels[vid] = analysis.voice_level[vid]
        if compute_spectrum:
            v_spec = spectrum_bands(dry, bins=spectrum_bins, sample_rate=sample_rate)
            prev_s = analysis.voice_spectrum.get(vid)
            if prev_s is None or prev_s.shape[0] != v_spec.shape[0]:
                analysis.voice_spectrum[vid] = v_spec.copy()
            else:
                prev_s += (v_spec - prev_s) * alpha
                analysis.voice_spectrum[vid] = prev_s
            v_specs[vid] = analysis.voice_spectrum[vid].copy()
        voice = voices.get(vid)
        if voice is not None:
            if voice.draining:
                v_rem[vid] = max(0.0, float(voice.tail_left))
            else:
                src_left = voice.source.remaining_seconds(voice.pitch, sample_rate)
                if src_left == float("inf"):
                    v_rem[vid] = float("inf")
                else:
                    v_rem[vid] = float(src_left) + _effects_tail_seconds(voice.effects)
            voice.level_ema = v_levels[vid]
            if compute_spectrum and vid in v_specs:
                voice.spectrum_ema = v_specs[vid]

    master_spec = (
        analysis.master_spectrum.copy()
        if analysis.master_spectrum is not None
        else raw_spec
    )
    deferred = [cmd + (int(at - n_frames),) for cmd, at in pending if at > n_frames]
    return RenderResult(
        limited,
        finished,
        raw_rms=raw_rms,
        raw_level=raw_level,
        raw_spectrum=raw_spec,
        master_level=float(analysis.master_level),
        master_spectrum=master_spec,
        voice_levels=v_levels,
        voice_spectra=v_specs,
        voice_remaining=v_rem,
        voice_dry=voice_dry,
        deferred=deferred,
    )


class _Snapshot:
    __slots__ = (
        "master_level", "master_spectrum", "voice_levels", "voice_spectra",
        "voice_remaining", "finished_ids",
    )

    def __init__(self) -> None:
        self.master_level = 0.0
        self.master_spectrum = np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
        self.voice_levels: Dict[int, float] = {}
        self.voice_spectra: Dict[int, np.ndarray] = {}
        self.voice_remaining: Dict[int, float] = {}
        self.finished_ids: List[int] = []


class Mixer:
    """Owns voices + the command queue. Optional PlaybackDevice adapter."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = int(sample_rate)
        self.voices: Dict[int, Voice] = {}
        self.queue = CommandQueue()
        self._next_id = 1
        self.master_volume = 1.0
        self.muted = False
        self.level_tau = DEFAULT_LEVEL_TAU
        self.analysis = AnalysisState()
        self.offline = True
        self._device = None
        self._generator = None
        self._id_lock = threading.Lock()
        self._snaps = [_Snapshot(), _Snapshot()]
        self._snap_i = 0
        self._finished_pending: List[int] = []
        self._finished_lock = threading.Lock()
        # Idle short-circuit: once analysis has decayed to silence with no
        # voices/commands, skip render() entirely until work returns.
        self._settled = True
        # Spectrum FFT is skipped until someone reads .spectrum(); latch stays
        # on for the mixer lifetime (reset clears it).
        self._spectrum_wanted = False
        self._last_limited: Optional[np.ndarray] = None
        self._last_voice_dry: Dict[int, np.ndarray] = {}
        self._last_block_dt = 0.0
        self._zero_buf: Optional[np.ndarray] = None
        self._silent_offline: Optional[RenderResult] = None

    def allocate_id(self) -> int:
        with self._id_lock:
            vid = self._next_id
            self._next_id += 1
            return vid

    def start_voice(
        self,
        *,
        samples: Optional[np.ndarray] = None,
        source: Optional[FrameSource] = None,
        volume: float = 1.0,
        pan: float = 0.0,
        pitch: float = 1.0,
        loops: int = 1,
        effects: Optional[Sequence[Any]] = None,
    ) -> int:
        vid = self.allocate_id()
        spec = {
            "samples": samples,
            "source": source,
            "volume": volume,
            "pan": pan,
            "pitch": pitch,
            "loops": loops,
            "effects": tuple(effects) if effects else (),
        }
        self.queue.push((CMD_START, vid, spec))
        return vid

    def set_volume(self, voice_id: int, volume: float, at_frame: int = 0) -> None:
        cmd: tuple = (CMD_SET_VOLUME, int(voice_id), float(volume))
        if at_frame:
            cmd = cmd + (int(at_frame),)
        self.queue.push(cmd)

    def set_pan(self, voice_id: int, pan: float, at_frame: int = 0) -> None:
        cmd: tuple = (CMD_SET_PAN, int(voice_id), float(pan))
        if at_frame:
            cmd = cmd + (int(at_frame),)
        self.queue.push(cmd)

    def set_pitch(self, voice_id: int, pitch: float, at_frame: int = 0) -> None:
        cmd: tuple = (CMD_SET_PITCH, int(voice_id), float(pitch))
        if at_frame:
            cmd = cmd + (int(at_frame),)
        self.queue.push(cmd)

    def set_effects(self, voice_id: int, effects: Sequence[Any]) -> None:
        self.queue.push((CMD_SET_EFFECTS, int(voice_id), tuple(effects)))

    def live_voice_ids(self) -> set:
        """Voices still playing for a Handle (a cut voice's de-click ramp is not)."""
        return {vid for vid, v in list(self.voices.items()) if not v.finished}

    def set_held(self, voice_id: int, held: bool) -> None:
        """Freeze or thaw a voice on the render thread (Handle.pause / resume)."""
        self.queue.push((CMD_SET_HELD, int(voice_id), bool(held)))

    def cancel_voice(self, voice_id: int) -> None:
        self.queue.push((CMD_CANCEL, int(voice_id)))

    def finish_voice(self, voice_id: int) -> None:
        """Natural end (fade_out reached 0) — still reports finished."""
        self.queue.push((CMD_FINISH, int(voice_id)))

    def set_master_volume(self, volume: float) -> None:
        self.master_volume = _safe_volume(volume)

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)

    def set_level_tau(self, tau: float) -> None:
        tau = require_finite("audio.level_tau", tau, positive=True)
        self.level_tau = tau

    def note_spectrum_interest(self) -> None:
        """Latch spectrum computation on; catch up from the last mix block."""
        if self._spectrum_wanted:
            return
        self._spectrum_wanted = True
        self._catchup_spectrum_from_last()

    def _zero_block(self, n_frames: int) -> np.ndarray:
        n = max(0, int(n_frames))
        if n == 0:
            return np.zeros((0, 2), dtype=np.float32)
        buf = self._zero_buf
        if buf is None or buf.shape[0] < n:
            self._zero_buf = np.zeros((max(n, 256), 2), dtype=np.float32)
            buf = self._zero_buf
        return buf[:n]

    def _silent_result(self, n_frames: int) -> RenderResult:
        """Settled idle: no mix, no publish, no FFT.

        The block is ``(n_frames, 2)`` silence. Offline repeats of the same
        length share one result.
        """
        n = max(0, int(n_frames))
        if self.offline:
            cached = self._silent_offline
            if cached is not None and cached[0] == n:
                return cached[1]
            z = np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
            result = RenderResult(
                np.zeros((n, 2), dtype=np.float32),
                [],
                master_level=0.0,
                master_spectrum=z,
            )
            self._silent_offline = (n, result)
            return result
        return RenderResult(
            self._zero_block(n),
            [],
            master_level=0.0,
            master_spectrum=np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32),
        )

    def _catchup_spectrum_from_last(self) -> None:
        """One-shot spectrum EMA from the last rendered block so first read is live."""
        limited = self._last_limited
        if limited is None or limited.size == 0:
            return
        alpha = ema_alpha(self._last_block_dt, self.level_tau) if self._last_block_dt > 0 else 1.0
        an = self.analysis
        raw_spec = spectrum_bands(limited, bins=DEFAULT_SPECTRUM_BINS, sample_rate=self.sample_rate)
        if an.master_spectrum is None or an.master_spectrum.shape[0] != raw_spec.shape[0]:
            an.master_spectrum = raw_spec.copy()
        else:
            an.master_spectrum += (raw_spec - an.master_spectrum) * alpha
        v_specs: Dict[int, np.ndarray] = {}
        for vid, dry in self._last_voice_dry.items():
            v_spec = spectrum_bands(dry, bins=DEFAULT_SPECTRUM_BINS, sample_rate=self.sample_rate)
            prev_s = an.voice_spectrum.get(vid)
            if prev_s is None or prev_s.shape[0] != v_spec.shape[0]:
                an.voice_spectrum[vid] = v_spec.copy()
            else:
                prev_s += (v_spec - prev_s) * alpha
                an.voice_spectrum[vid] = prev_s
            v_specs[vid] = an.voice_spectrum[vid].copy()
            voice = self.voices.get(vid)
            if voice is not None:
                voice.spectrum_ema = v_specs[vid]
        snap = self._snaps[self._snap_i]
        snap.master_spectrum = an.master_spectrum.copy()
        snap.voice_spectra = dict(v_specs)

    def _render_idle_decay(self, n_frames: int) -> RenderResult:
        """No voices/commands: EMA toward silence, then settle (skip forever after)."""
        block_dt = n_frames / float(self.sample_rate) if self.sample_rate else 0.0
        alpha = ema_alpha(block_dt, self.level_tau) if n_frames > 0 else 0.0
        an = self.analysis
        an.master_level += (0.0 - an.master_level) * alpha
        an.voice_level.clear()
        an.voice_spectrum.clear()
        if self._spectrum_wanted:
            if an.master_spectrum is None:
                an.master_spectrum = np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
            else:
                an.master_spectrum *= (1.0 - alpha)
        quiet = abs(an.master_level) < 1e-3
        if self._spectrum_wanted and an.master_spectrum is not None:
            quiet = quiet and float(np.max(np.abs(an.master_spectrum))) < 1e-3
        if quiet:
            an.master_level = 0.0
            if an.master_spectrum is not None:
                an.master_spectrum[:] = 0.0
            self._settled = True
        master_spec = (
            an.master_spectrum.copy()
            if an.master_spectrum is not None
            else np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
        )
        result = RenderResult(
            self._zero_block(n_frames),
            [],
            master_level=float(an.master_level),
            master_spectrum=master_spec,
        )
        self._publish(result)
        self._last_limited = result.block
        self._last_voice_dry = {}
        self._last_block_dt = block_dt
        return result

    def render_block(self, n_frames: int, commands: Optional[Sequence[tuple]] = None) -> RenderResult:
        cmds = list(self.queue.drain())
        if commands:
            cmds.extend(commands)
        has_work = bool(self.voices) or bool(cmds)
        if not has_work:
            if self._settled:
                return self._silent_result(n_frames)
            return self._render_idle_decay(n_frames)

        self._settled = False
        result = render(
            self.voices,
            n_frames,
            cmds,
            sample_rate=self.sample_rate,
            master_volume=self.master_volume,
            muted=self.muted,
            level_tau=self.level_tau,
            analysis=self.analysis,
            compute_spectrum=self._spectrum_wanted,
        )
        for cmd in result.deferred:
            self.queue.push(cmd)
        self._last_limited = result.block
        self._last_voice_dry = dict(result.voice_dry)
        self._last_block_dt = (
            n_frames / float(self.sample_rate) if self.sample_rate else 0.0
        )
        if result.finished_ids:
            with self._finished_lock:
                self._finished_pending.extend(vid for vid, _at in result.finished_ids)
        self._publish(result)
        return result

    def _publish(self, result: RenderResult) -> None:
        global _publish_count
        nxt = 1 - self._snap_i
        snap = self._snaps[nxt]
        snap.master_level = result.master_level
        snap.master_spectrum = result.master_spectrum.copy()
        snap.voice_levels = dict(result.voice_levels)
        snap.voice_spectra = {k: v.copy() for k, v in result.voice_spectra.items()}
        snap.voice_remaining = dict(result.voice_remaining)
        snap.finished_ids = [vid for vid, _at in result.finished_ids]
        self._snap_i = nxt
        _publish_count += 1

    def snapshot(self) -> _Snapshot:
        return self._snaps[self._snap_i]

    def take_finished(self) -> List[int]:
        with self._finished_lock:
            out = self._finished_pending
            self._finished_pending = []
            return out

    def voice_finished(self, voice_id: int) -> bool:
        return int(voice_id) in set(self.take_finished())  # don't use this; see poll

    def pump_dt(self, dt: float) -> Optional[RenderResult]:
        if not self.offline or dt <= 0.0:
            return None
        n = int(round(float(dt) * self.sample_rate))
        if n <= 0:
            return None
        return self.render_block(n)

    def start_device(self, *, backends=None, buffersize_msec: int = 40) -> None:
        import miniaudio

        if self._device is not None:
            return
        kwargs = dict(
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=CHANNELS,
            sample_rate=self.sample_rate,
            buffersize_msec=int(buffersize_msec),
        )
        if backends is not None:
            kwargs["backends"] = list(backends)
        device = miniaudio.PlaybackDevice(**kwargs)

        mixer = self

        def gen():
            n = yield np.zeros((0, 2), dtype=np.float32)
            while True:
                frames = int(n) if n else 256
                block = mixer.render_block(frames).block
                n = yield block

        g = gen()
        g.send(None)
        device.start(g)
        self._device = device
        self._generator = g
        self.offline = False

    def stop_device(self) -> None:
        dev = self._device
        self._device = None
        self._generator = None
        self.offline = True
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass

    def reset(self) -> None:
        self.stop_device()
        self.queue.drain()
        self.voices.clear()
        self.analysis = AnalysisState()
        self.master_volume = 1.0
        self.muted = False
        self.level_tau = DEFAULT_LEVEL_TAU
        with self._finished_lock:
            self._finished_pending.clear()
        self._snaps = [_Snapshot(), _Snapshot()]
        self._snap_i = 0
        with self._id_lock:
            self._next_id = 1
        self._settled = True
        self._spectrum_wanted = False
        self._last_limited = None
        self._last_voice_dry = {}
        self._last_block_dt = 0.0
        self._silent_offline = None


_mixer: Optional[Mixer] = None
# Bumped on every snapshot publish (any mixer) and on a mixer reset: the
# frame's audio sample compares it to know ``audio.level`` / ``h.level``
# changed (``level_source``). One writer at a time; a lost increment only
# delays the next notification by a block.
_publish_count = 0


def publish_count() -> int:
    return _publish_count


def get_mixer() -> Mixer:
    global _mixer
    if _mixer is None:
        _mixer = Mixer()
    return _mixer


def reset_mixer() -> None:
    global _mixer, _publish_count
    if _mixer is not None:
        _mixer.reset()
    _mixer = Mixer()
    _publish_count += 1
