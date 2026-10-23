"""Author audio: ``play_sound``, ``Sound``, ``audio`` bus.

Decode + intern live here. Mixing is ``audio_mixer`` (pure ``render()``).
"""
from __future__ import annotations

import hashlib
import math
import numbers
import os
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

import numpy as np

from .audio_mixer import (
    SAMPLE_RATE,
    STREAM_THRESHOLD_S,
    DEFAULT_LEVEL_TAU,
    MAX_BAKE_FRAMES,
    BufferSource,
    FrameSource,
    PullSource,
    get_mixer,
    make_silence,
    pcm_from_decoded,
    require_finite,
    reset_mixer,
)
from . import audio_mixer as _audio_mixer
from . import audio_effects as _audio_effects  # registers the mixer effect processor
from . import stall as _stall
from .closed import ClosedSurface
from .process import (
    SCOPE_ENTITY,
    SCOPE_ACT,
    Handle,
    _fn_and_then,
    _infer_owner,
    _require_then_owner,
    get_scheduler,
    report_author_warning,
)

Source = Union[str, "Sound", Any]

_PCM_CACHE: Dict[Tuple[str, bool], Tuple[Optional[np.ndarray], float, bool]] = {}
_BAKE_CACHE: Dict[Tuple[Any, ...], "Sound"] = {}
_WARNED: set = set()
_MISSING_DURATION_S = 1.0


from .purity_check import _READING as _SOLVER_READING, refuse_if_solver_reading


def reset_audio() -> None:
    """Test hook: drop decode cache, warnings, mixer, and the ``audio`` bus."""
    _PCM_CACHE.clear()
    _BAKE_CACHE.clear()
    _WARNED.clear()
    reset_mixer()
    # Bus singleton outlives the mixer. Restore the author defaults onto the
    # fresh mixer (volume 1, unmuted, τ 0.08).
    audio.volume = 1.0
    audio.muted = False
    audio.level_tau = DEFAULT_LEVEL_TAU


def _resolve_sound_path(filename: str) -> Optional[str]:
    from .sprite import _resolve_image_path
    return _resolve_image_path(filename)


def _parse_loops(value) -> int:
    from .track import _parse_loops as _pl
    return _pl(value)


def _warn_asset(key: str, message: str) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    report_author_warning("play_sound", message)


def _load_asset(path: str, *, stream: Optional[bool], label: str) -> Tuple[Optional[np.ndarray], float, bool]:
    """Return ``(samples|None, duration, is_stream)``. Missing/corrupt → silence."""
    abs_path = os.path.abspath(path)
    if stream is not None:
        hit = _PCM_CACHE.get((abs_path, bool(stream)))
        if hit is not None:
            return hit
    else:
        # A decoded buffer is always a valid heuristic hit. A streamed entry
        # must not force later Sound(path) calls to stream — a short file
        # opened once with stream=True stays buffered under the heuristic.
        buffered = _PCM_CACHE.get((abs_path, False))
        if buffered is not None and buffered[0] is not None:
            return buffered

    import miniaudio

    duration = _MISSING_DURATION_S
    try:
        info = miniaudio.get_file_info(path)
        duration = float(getattr(info, "duration", 0.0) or 0.0) or _MISSING_DURATION_S
    except Exception as e:
        _warn_asset(
            label,
            f"Could not read sound {label!r} ({e}). Playing silence. The handle still ticks.",
        )
        samples = make_silence(duration)
        packed = (samples, duration, False)
        _PCM_CACHE[(os.path.abspath(path), False)] = packed
        return packed

    if stream is None:
        want_stream = duration >= STREAM_THRESHOLD_S
    else:
        want_stream = bool(stream)

    if want_stream:
        packed = (None, duration, True)
        _PCM_CACHE[(os.path.abspath(path), True)] = packed
        return packed

    try:
        decoded = miniaudio.decode_file(
            path,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=SAMPLE_RATE,
        )
        samples = pcm_from_decoded(decoded)
        duration = float(samples.shape[0]) / float(SAMPLE_RATE)
        packed = (samples, duration, False)
        _PCM_CACHE[(os.path.abspath(path), False)] = packed
        return packed
    except Exception as e:
        _warn_asset(
            label,
            f"Could not decode sound {label!r} ({e}). Playing silence. The handle still ticks.",
        )
        samples = make_silence(duration)
        packed = (samples, duration, False)
        _PCM_CACHE[(os.path.abspath(path), False)] = packed
        return packed


def _force_decode(path: str, label: str) -> np.ndarray:
    """Decode a path even if the interned asset is streamed."""
    abs_path = os.path.abspath(path)
    hit = _PCM_CACHE.get((abs_path, False))
    if hit is not None and hit[0] is not None:
        return hit[0]
    import miniaudio
    try:
        decoded = miniaudio.decode_file(
            path,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=SAMPLE_RATE,
        )
        samples = pcm_from_decoded(decoded)
        duration = float(samples.shape[0]) / float(SAMPLE_RATE)
        _PCM_CACHE[(abs_path, False)] = (samples, duration, False)
        return samples
    except Exception as e:
        _warn_asset(
            label,
            f"Could not decode sound {label!r} ({e}). Playing silence. The handle still ticks.",
        )
        return make_silence(_MISSING_DURATION_S)


def _resample_to_length(samples: np.ndarray, n_out: int) -> np.ndarray:
    if samples.ndim == 1:
        samples = samples.reshape(-1, 1)
    n_in = int(samples.shape[0])
    nch = int(samples.shape[1]) if samples.ndim == 2 else 1
    if n_in <= 0 or n_out <= 0:
        return np.zeros((max(0, n_out), nch), dtype=np.float32)
    samples = np.ascontiguousarray(samples, dtype=np.float32)
    if n_in == n_out:
        return samples
    idx = np.linspace(0.0, n_in - 1.0, n_out)
    i0 = np.floor(idx).astype(np.int64)
    frac = (idx - i0).astype(np.float32)[:, None]
    i0 = np.clip(i0, 0, n_in - 1)
    i1 = np.clip(i0 + 1, 0, n_in - 1)
    return (samples[i0] * (1.0 - frac) + samples[i1] * frac).astype(np.float32)


def _time_stretch_mono(mono: np.ndarray, stretch: float, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    """Phase-vocoder time stretch. ``stretch`` > 1 → longer."""
    stretch = float(stretch)
    if not math.isfinite(stretch) or stretch <= 0.0:
        raise ValueError("stretch must be finite and > 0")
    if abs(stretch - 1.0) < 1e-9 or mono.size < n_fft:
        return mono.astype(np.float64, copy=True)
    window = np.hanning(n_fft)
    n = int(mono.shape[0])
    n_hops = max(1, 1 + (n - n_fft) // hop)
    pad_n = n_fft + (n_hops - 1) * hop
    if pad_n > n:
        mono = np.pad(mono.astype(np.float64), (0, pad_n - n))
    else:
        mono = mono.astype(np.float64)
    hop_out = max(1, int(round(hop * stretch)))
    out_len = n_fft + (n_hops - 1) * hop_out
    out = np.zeros(out_len, dtype=np.float64)
    win_sum = np.zeros(out_len, dtype=np.float64)
    omega = 2.0 * np.pi * hop / n_fft * np.arange(n_fft // 2 + 1)
    phase_adv = np.zeros(n_fft // 2 + 1, dtype=np.float64)
    prev_phase = None
    for i in range(n_hops):
        frame = mono[i * hop:i * hop + n_fft] * window
        spec = np.fft.rfft(frame)
        mag = np.abs(spec)
        phase = np.angle(spec)
        if prev_phase is None:
            phase_adv = phase.copy()
        else:
            delta = phase - prev_phase - omega
            delta = delta - 2.0 * np.pi * np.round(delta / (2.0 * np.pi))
            phase_adv = phase_adv + omega + delta
        prev_phase = phase
        synth = np.fft.irfft(mag * np.exp(1j * phase_adv), n=n_fft).real * window
        o = i * hop_out
        out[o:o + n_fft] += synth
        win_sum[o:o + n_fft] += window ** 2
    nz = win_sum > 1e-8
    out[nz] /= win_sum[nz]
    return out


def _spectral_pitch_mono(mono: np.ndarray, rate: float) -> np.ndarray:
    """Length-preserving bin shift for clips too short for the phase vocoder."""
    n = int(mono.shape[0])
    if n < 8 or abs(rate - 1.0) < 1e-9:
        return np.asarray(mono, dtype=np.float64)
    spec = np.fft.rfft(np.asarray(mono, dtype=np.float64))
    src = np.arange(spec.shape[0], dtype=np.float64) / float(rate)
    i0 = np.floor(src).astype(np.int64)
    frac = src - i0
    i0 = np.clip(i0, 0, spec.shape[0] - 1)
    i1 = np.clip(i0 + 1, 0, spec.shape[0] - 1)
    shifted = spec[i0] * (1.0 - frac) + spec[i1] * frac
    return np.fft.irfft(shifted, n=n).real


def _transpose_pcm(samples: np.ndarray, semitones: float) -> np.ndarray:
    """Duration-preserving pitch shift.

    Clips long enough for several 1024-point hops use a phase vocoder, then
    a resample back to the original length. Shorter clips shift rfft bins so
    the length (and the pitch) still change instead of coming back unchanged.
    """
    st = float(semitones)
    if abs(st) < 1e-9:
        return np.ascontiguousarray(samples, dtype=np.float32)
    rate = 2.0 ** (st / 12.0)
    n = int(samples.shape[0])
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError("transpose= must be finite")
    chans = []
    short = n < 1024 * 8
    for c in range(samples.shape[1]):
        if short:
            shifted = _spectral_pitch_mono(samples[:, c], rate)
            chans.append(shifted.astype(np.float32))
        else:
            stretched = _time_stretch_mono(samples[:, c], rate)
            chans.append(_resample_to_length(stretched.reshape(-1, 1), n)[:, 0])
    return np.column_stack(chans).astype(np.float32)


def _rate_pcm(samples: np.ndarray, pitch: float) -> np.ndarray:
    """Playback-rate bake: duration becomes ``duration / pitch`` (same as live ``pitch=``)."""
    p = require_finite("pitch", pitch, positive=True)
    if abs(p - 1.0) < 1e-12:
        return np.ascontiguousarray(samples, dtype=np.float32)
    n_out = max(1, int(round(samples.shape[0] / p)))
    if n_out > MAX_BAKE_FRAMES:
        raise ValueError("pitch= would make this bake longer than 30 minutes")
    return _resample_to_length(samples, n_out)


def _bake_fingerprint(
    effects: Sequence[Any],
    transpose: float,
    pitch: float,
) -> Tuple[Any, ...]:
    fx_fp = tuple(
        getattr(fx, "_fingerprint", lambda: (type(fx).__name__,))()
        for fx in effects
        if fx is not None and getattr(fx, "enabled", True)
    )
    return (round(float(transpose), 2), round(float(pitch), 4), fx_fp)


def amp_db(x: float, floor: float = -60.0) -> float:
    """Map linear amplitude ``0…1`` to a display value ``0…1`` via dB.

    ``1`` → 0 dBFS → ``1.0``. ``floor`` dB (default −60) → ``0.0``.
    Values ``<= 0`` → ``0.0``. Values ``> 1`` clamp to ``1.0`` after the
    dB map (above full-scale still reads as full meter).

    Args:
        x: Linear amplitude, 0 … 1 (``h.level``, ``audio.level``).
        floor: Result for silence, in dB (default −60).
    """
    from .validate import number
    fl = number(floor, "amp_db floor")
    if fl >= 0.0:
        raise ValueError("amp_db floor must be finite and < 0 (dB below full scale)")
    from .state import as_payload
    x = as_payload(x)       # a cell counts as its number (PM12 class)
    if isinstance(x, bool) or not isinstance(x, numbers.Real):
        raise TypeError(f"amp_db expected a number (linear amplitude 0…1), got {type(x).__name__}")
    v = float(x)
    if not math.isfinite(v) or v <= 0.0:
        return 0.0
    db = 20.0 * math.log10(v)
    return max(0.0, min(1.0, (db - fl) / (-fl)))


class StreamFileSource(FrameSource):
    """Pull PCM from ``miniaudio.stream_file``. Restarts the decoder on loop."""

    __slots__ = (
        "path", "loops", "lap", "duration", "_gen", "_buf", "_pos", "_src_pos",
        "_eof", "_opened",
    )

    def __init__(self, path: str, loops: int = 1, duration: float = 0.0):
        self.path = path
        self.loops = int(loops)
        self.lap = 0
        self.duration = max(0.0, float(duration))
        self._buf = np.zeros((0, 2), dtype=np.float32)
        self._pos = 0.0
        self._src_pos = 0.0
        self._eof = False
        self._opened = False
        self._gen = None
        self._open()

    def _open(self) -> None:
        import miniaudio
        old = self._gen
        self._gen = miniaudio.stream_file(
            self.path,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=SAMPLE_RATE,
        )
        self._opened = True
        self._eof = False
        if old is not None:
            try:
                old.close()
            except Exception:
                pass

    def remaining_seconds(self, pitch: float, sample_rate: int = SAMPLE_RATE) -> float:
        if self.loops < 0:
            return float("inf")
        n = self.duration * float(sample_rate)
        if n <= 0.0:
            return 0.0
        p = max(float(pitch), 1e-12)
        left = max(0.0, n - self._src_pos) / (sample_rate * p)
        laps_left = max(0, self.loops - self.lap - 1)
        return left + laps_left * (n / (sample_rate * p))

    def _refill(self, need: int) -> None:
        while (self._buf.shape[0] - int(self._pos)) < need + 2 and not self._eof:
            try:
                chunk = self._gen.send(max(1024, need))
            except StopIteration:
                self._eof = True
                break
            except Exception:
                self._eof = True
                break
            if isinstance(chunk, np.ndarray):
                arr = np.asarray(chunk, dtype=np.float32)
                if arr.ndim == 1:
                    if arr.size % 2:
                        arr = arr[: arr.size - (arr.size % 2)]
                    arr = arr.reshape(-1, 2)
            else:
                raw = np.frombuffer(memoryview(chunk), dtype=np.float32)
                if raw.size % 2:
                    raw = raw[: raw.size - (raw.size % 2)]
                arr = raw.reshape(-1, 2)
            cut = int(self._pos)
            if cut:
                self._buf = self._buf[cut:]
                self._pos -= cut
            self._buf = np.concatenate([self._buf, arr]) if self._buf.size else arr

    def pull(self, n_frames: int, pitch: float) -> Tuple[np.ndarray, Optional[int]]:
        n_frames = int(n_frames)
        out = np.zeros((n_frames, 2), dtype=np.float32)
        p = float(pitch) if pitch > 1e-12 else 1e-12
        written = 0
        while written < n_frames:
            self._refill(int((n_frames - written) * p) + 4)
            available = self._buf.shape[0] - self._pos
            if available <= 1:
                more = self.loops < 0 or (self.lap + 1) < self.loops
                if more:
                    self.lap += 1
                    self._open()
                    self._buf = np.zeros((0, 2), dtype=np.float32)
                    self._pos = 0.0
                    self._src_pos = 0.0
                    continue
                return out, written
            take = n_frames - written
            idx = self._pos + p * np.arange(take, dtype=np.float64)
            nbuf = self._buf.shape[0]
            valid = idx < nbuf - 1e-9
            ntake = int(np.count_nonzero(valid))
            if ntake <= 0:
                skipped = float(nbuf) - self._pos
                self._src_pos += max(0.0, skipped)
                self._pos = float(nbuf)
                continue
            idx = idx[:ntake]
            i0 = np.clip(np.floor(idx).astype(np.int64), 0, nbuf - 1)
            frac = (idx - i0).astype(np.float32)[:, None]
            i1 = np.clip(i0 + 1, 0, nbuf - 1)
            out[written:written + ntake] = self._buf[i0] * (1.0 - frac) + self._buf[i1] * frac
            self._pos = float(idx[-1] + p)
            self._src_pos += float(ntake) * p
            written += ntake
        return out, None


class Sound(ClosedSurface):
    """Decoded (or streamed) audio material. Does not play. Use ``play_sound``.

    Args:
        path: Audio file (wav / ogg / mp3 / flac).
        volume: Default loudness when played (>= 0; 1 = as recorded).
        stream: Force streaming (``True``) or loading into memory (``False``); default:
            clips under 8 s load, longer ones stream.
    """

    def __init__(self, path: str, *, volume: float = 1.0, stream: Optional[bool] = None):
        if not isinstance(path, str) or not path:
            raise TypeError("Sound path must be a non-empty string")
        self.path = path
        self.volume = require_finite("volume", volume, non_negative=True)
        self._stream_override = stream
        self._take = None
        self._record_handle = None
        resolved = _resolve_sound_path(path)
        if resolved is None:
            _warn_asset(
                path,
                f"Sound file not found: {path!r}. Playing silence. The handle still ticks.",
            )
            self._samples = make_silence(_MISSING_DURATION_S)
            self._duration = _MISSING_DURATION_S
            self._is_stream = False
            self._resolved = None
            self._take = None
            self._record_handle = None
            return
        self._resolved = resolved
        samples, duration, is_stream = _load_asset(resolved, stream=stream, label=path)
        self._samples = samples
        self._duration = float(duration)
        self._is_stream = bool(is_stream)
        self._take = None
        self._record_handle = None

    @classmethod
    def _from_pcm(cls, samples: np.ndarray, *, volume: float = 1.0, path: str = "<pcm>") -> "Sound":
        obj = object.__new__(cls)
        obj.path = path
        obj.volume = require_finite("volume", volume, non_negative=True)
        obj._stream_override = False
        obj._resolved = None
        obj._samples = np.ascontiguousarray(samples, dtype=np.float32)
        if obj._samples.ndim == 1:
            obj._samples = np.column_stack([obj._samples, obj._samples])
        obj._duration = float(obj._samples.shape[0]) / float(SAMPLE_RATE)
        obj._is_stream = False
        obj._take = None
        obj._record_handle = None
        return obj

    @classmethod
    def _recording(cls, take) -> "Sound":
        """A clip still being captured. Not playable until the take ends."""
        obj = object.__new__(cls)
        obj.path = "<recording>"
        obj.volume = 1.0
        obj._stream_override = False
        obj._resolved = None
        obj._samples = None
        obj._duration = 0.0
        obj._is_stream = False
        obj._take = take
        obj._record_handle = None
        return obj

    @property
    def duration(self) -> float:
        """Seconds of audio. Grows while a recording is in progress, then fixed."""
        take = self._take
        if take is not None and not take.finalized:
            return float(take.frames) / float(SAMPLE_RATE)
        return float(self._duration)

    def _finalize(self, pcm: np.ndarray) -> None:
        """Freeze a recording. Called once, on the main thread."""
        samples = np.ascontiguousarray(pcm, dtype=np.float32)
        if samples.ndim == 1:
            samples = np.column_stack([samples, samples])
        elif samples.size == 0:
            samples = np.zeros((0, 2), dtype=np.float32)
        self._samples = samples
        self._duration = float(samples.shape[0]) / float(SAMPLE_RATE)
        self._take = None

    def _require_ready(self, what: str) -> None:
        take = self._take
        if take is not None and not take.finalized:
            raise RuntimeError(
                f"{what}: this clip is still recording — call mic.stop() or await it first"
            )

    def __await__(self):
        handle = self._record_handle
        if handle is None:
            raise TypeError(
                "await a clip from mic.record(), not a Sound loaded from a file. "
                "play_sound(sound) plays it; it is not awaited."
            )
        yield from handle.__await__()
        return self

    def _pcm(self) -> np.ndarray:
        """Decoded stereo buffer; forces a full decode for streamed assets."""
        self._require_ready("Sound")
        if self._samples is not None:
            return self._samples
        if self._resolved:
            return _force_decode(self._resolved, self.path)
        return make_silence(self.duration)

    def bake(
        self,
        *effects: Any,
        transpose: float = 0.0,
        pitch: float = 1.0,
    ) -> "Sound":
        """Run transforms + ``effects`` once; return an interned material.

        ``transpose=`` (semitones) keeps duration. ``pitch=`` is rate (duration
        becomes ``duration / pitch``), same tradeoff as live ``pitch=``.
        Knobs are snapshotted now. Echo/Reverb tails are padded into the buffer
        so playback needs no live drain. Does not mutate this ``Sound``.
        """
        from .audio_effects import AudioEffect, apply_effects, max_tail_seconds

        self._require_ready("Sound.bake")
        live_fx = []
        for fx in effects:
            if fx is None:
                continue
            if not isinstance(fx, AudioEffect):
                raise TypeError(
                    f"Sound.bake expected LowPass/HighPass/Echo/Reverb/Distortion/Wavefold, "
                    f"got {type(fx).__name__}"
                )
            if not getattr(fx, "enabled", True):
                continue
            live_fx.append(fx)

        st = require_finite("transpose", transpose)
        rate = require_finite("pitch", pitch, positive=True)
        vol = require_finite("volume", self.volume, non_negative=True)
        if self._resolved:
            origin: Any = os.path.abspath(self._resolved)
        else:
            pcm_id = np.ascontiguousarray(self._pcm())
            digest = hashlib.blake2b(pcm_id.tobytes(), digest_size=16).digest()
            origin = ("pcm", self.path, int(pcm_id.shape[0]), digest)
        key = (origin, round(vol, 6), _bake_fingerprint(live_fx, st, rate))
        hit = _BAKE_CACHE.get(key)
        if hit is not None:
            return hit

        clones = []
        for fx in live_fx:
            cls = type(fx)
            knobs = {
                k: getattr(fx, k)
                for k in ("cutoff", "delay", "decay", "size", "mix", "drive")
                if hasattr(fx, k)
            }
            clones.append(cls(**knobs))

        names = ", ".join(type(fx).__name__ for fx in clones) or "transpose / pitch"
        with _stall.busy(f"baking {os.path.basename(str(self.path))} ({names})"):
            src = self._pcm().copy()
            if abs(st) >= 1e-9:
                src = _transpose_pcm(src, st)
            if abs(rate - 1.0) >= 1e-12:
                src = _rate_pcm(src, rate)

            for fx in clones:
                fx._reset_state()
            wet = apply_effects(src, clones, SAMPLE_RATE)
            tail = max_tail_seconds(clones)
            if tail > 0.0:
                pad = int(math.ceil(tail * SAMPLE_RATE))
                silence = np.zeros((pad, wet.shape[1]), dtype=np.float32)
                silence = apply_effects(silence, clones, SAMPLE_RATE)
                wet = np.concatenate([wet, silence], axis=0)

        baked = Sound._from_pcm(wet, volume=vol, path=f"{self.path}#bake")
        _BAKE_CACHE[key] = baked
        return baked

    def _frame_source(self, loops: int) -> FrameSource:
        self._require_ready("play_sound")
        if self._is_stream and self._resolved and self._samples is None:
            return StreamFileSource(self._resolved, loops=loops, duration=self.duration)
        samples = self._samples if self._samples is not None else make_silence(self.duration)
        return BufferSource(samples, loops=loops)


def _bus_stamp(_bus) -> int:
    return _audio_mixer._publish_count


class AudioBus(ClosedSurface):
    """Module singleton ``audio`` — master volume / mute / analysis τ."""

    _closed_who = "audio"

    def __init__(self) -> None:
        self._volume = 1.0
        self._muted = False
        self._level_tau = 0.08

    @property
    def volume(self) -> float:
        """Master volume (>= 0; 1 = unchanged)."""
        return self._volume

    @volume.setter
    def volume(self, value) -> None:
        self._volume = require_finite("volume", value, non_negative=True)
        get_mixer().set_master_volume(self._volume)

    @property
    def muted(self) -> bool:
        """Silence everything (``True``) without stopping playback."""
        return self._muted

    @muted.setter
    def muted(self, value) -> None:
        self._muted = bool(value)
        get_mixer().set_muted(self._muted)

    @property
    def level_tau(self) -> float:
        """Smoothing time in seconds for every ``.level`` / ``.spectrum`` (default 0.08; > 0)."""
        return self._level_tau

    @level_tau.setter
    def level_tau(self, value) -> None:
        tau = require_finite("audio.level_tau", value, positive=True)
        self._level_tau = tau
        get_mixer().set_level_tau(tau)

    def _formula_source(self):
        """The graph node an ``@=`` reading the mix depends on (``level_source``)."""
        from .level_source import level_source_for
        return level_source_for(self, _bus_stamp)

    @property
    def level(self) -> float:
        """Loudness of the final mix, 0 … 1, smoothed over ``level_tau``.

        A formula that reads it (``@= lambda: audio.level``) follows it,
        updated once per frame.
        """
        return float(get_mixer().snapshot().master_level)

    def spectrum(self, bins: int = 8) -> list:
        """Loudness per frequency band of the final mix, low to high.

        Args:
            bins: how many bands (default 8).

        Returns:
            A list of ``bins`` numbers, 0 … 1.
        """
        mixer = get_mixer()
        mixer.note_spectrum_interest()
        spec = mixer.snapshot().master_spectrum
        return _resample_bins(spec, bins)


def _resample_bins(spec: Optional[np.ndarray], bins: int) -> list:
    bins = max(1, int(bins))
    if spec is None or spec.size == 0:
        return [0.0] * bins
    x = np.asarray(spec, dtype=np.float64)
    if x.shape[0] == bins:
        return [float(v) for v in x]
    idx = np.linspace(0, x.shape[0], bins + 1)
    out = []
    for i in range(bins):
        a = int(idx[i])
        b = max(int(idx[i + 1]), a + 1)
        out.append(float(np.mean(x[a:b])))
    return out


audio = AudioBus()


def _unbind_named(handle: Handle) -> None:
    if not handle.name:
        return
    sched = get_scheduler()
    key = (id(handle.owner) if handle.owner is not None else None, handle.name)
    if sched._named.get(key) is handle:
        del sched._named[key]
    handle._name = None


def _start_sound(
    source: Source,
    *,
    volume: Optional[float] = None,
    pan: float = 0.0,
    pitch: float = 1.0,
    loops: Union[int, str] = 1,
    fade_in=None,
    crossfade=None,
    on_done=None,
    then=None,
    name: Optional[str] = None,
    owner=None,
    scope: str = SCOPE_ACT,
) -> Handle:
    on_done, then = _fn_and_then(None, then, call_name="play_sound", on_done=on_done)
    _require_then_owner(then, owner, call_name="play_sound")
    loop_n = _parse_loops(loops)
    pan = require_finite("pan", pan)
    pitch = require_finite("pitch", pitch, positive=True)
    if volume is not None:
        volume = require_finite("volume", volume, non_negative=True)
    fade_in_s: Optional[float] = None
    if fade_in is not None:
        fade_in_s = require_finite("fade_in", fade_in, non_negative=True)
    crossfade_s: Optional[float] = None
    if crossfade is not None:
        crossfade_s = require_finite("crossfade", crossfade, non_negative=True)
        if not name:
            raise TypeError(
                "crossfade= only works with name= (it fades the outgoing named slot)."
            )

    material: Optional[Sound] = None
    frame_source: Optional[FrameSource] = None
    samples: Optional[np.ndarray] = None
    duration = _MISSING_DURATION_S
    default_volume = 1.0

    if hasattr(source, "_audio_frame_source") and not isinstance(source, (str, Sound)):
        frame_source = source._audio_frame_source()
        if not isinstance(frame_source, FrameSource):
            raise TypeError(
                f"play_sound() source {type(source).__name__}._audio_frame_source "
                f"must return a FrameSource, got {type(frame_source).__name__}"
            )
        duration = float("inf")
        default_volume = 1.0
    elif isinstance(source, Sound):
        source._require_ready("play_sound")
        material = source
        default_volume = float(source.volume)
        duration = float(source.duration)
        frame_source = source._frame_source(loop_n)
    elif isinstance(source, str):
        material = Sound(source)
        default_volume = float(material.volume)
        duration = float(material.duration)
        frame_source = material._frame_source(loop_n)
    else:
        raise TypeError(
            "play_sound() source must be a path string, a Sound, or a live "
            f"frame source (Microphone). Got {type(source).__name__}."
        )

    vol = default_volume if volume is None else float(volume)
    # Before the voice starts: a refused name must leave nothing playing.
    get_scheduler().refuse_game_task_clash(owner, scope, name, "sound")
    # crossfade=0 is an instant named-slot cut (same as omitting it).
    # Only a positive crossfade ramps the outgoing voice and forces a fade-in.
    if crossfade_s:
        if fade_in_s is None:
            fade_in_s = crossfade_s
        sched = get_scheduler()
        key = (id(owner) if owner is not None else None, name)
        old = sched._named.get(key)
        if old is not None and getattr(old, "kind", None) == "sound":
            _unbind_named(old)
            old._ramp_out(float(crossfade_s), natural=False)   # a cut, not an end
    start_vol = 0.0 if fade_in_s else vol

    mixer = get_mixer()
    voice_id = mixer.start_voice(
        source=frame_source,
        volume=start_vol,
        pan=pan,
        pitch=pitch,
        loops=loop_n,
    )
    handle = Handle._make(
        kind="sound",
        delay=duration if duration != float("inf") else 0.0,
        fn=on_done,
        then=then,
        owner=owner,
        scope=scope,
        name=name,
        loops=loop_n,
    )
    handle._voice_id = voice_id
    handle._sound_volume = start_vol
    handle._sound_pan = pan
    handle._sound_pitch = pitch
    handle._sound_loops = loop_n
    handle._clip_duration = 0.0 if duration == float("inf") else float(duration)
    get_scheduler().add(handle)
    if fade_in_s:
        handle.fade_to(vol, time=float(fade_in_s))
        handle._sound_volume = start_vol  # fade_to writes from current
        # fade_to captures start at call time; we already set volume 0 on the mixer.
    else:
        handle._sound_volume = vol
    return handle


def play_sound(
    source: Source,
    *,
    volume: Optional[float] = None,
    pan: float = 0.0,
    pitch: float = 1.0,
    loops: Union[int, str] = 1,
    fade_in=None,
    crossfade=None,
    on_done=None,
    then=None,
    name: Optional[str] = None,
) -> Handle:
    """Play ``source``. Returns a ``Handle`` (same class as ``after`` / tween).

    Args:
        source: A file path, a ``Sound``, or a ``Microphone`` (monitoring).
        volume: Loudness (>= 0; default: the Sound's own, else 1).
        pan: Stereo position, −1 (left) … 1 (right).
        pitch: Playback rate (1 = normal; 2 = an octave up and twice as fast).
        loops: How many times to play (default 1), or ``"forever"``.
        fade_in: Seconds to fade in from silence.
        crossfade: With ``name=``: seconds to fade the old sound in this slot out while
            this one fades in.
        on_done: Function called when the sound ends (not when cancelled).
        then: Mode to enter when the sound ends.
        name: Slot name: a new sound with the same name replaces the old one (music:
            ``name="music"``).
    """
    if _SOLVER_READING:
        refuse_if_solver_reading('play_sound()')
    owner, scope = _infer_owner(on_done if on_done is not None else then)
    return _start_sound(
        source,
        volume=volume,
        pan=pan,
        pitch=pitch,
        loops=loops,
        fade_in=fade_in,
        crossfade=crossfade,
        on_done=on_done,
        then=then,
        name=name,
        owner=owner,
        scope=scope,
    )


def play_sound_on(
    item,
    source: Source,
    *,
    volume: Optional[float] = None,
    pan: float = 0.0,
    pitch: float = 1.0,
    loops: Union[int, str] = 1,
    fade_in=None,
    crossfade=None,
    on_done=None,
    then=None,
    name: Optional[str] = None,
) -> Handle:
    """``Entity.play_sound`` — always entity-scoped."""
    if _SOLVER_READING:
        refuse_if_solver_reading('play_sound()')
    return _start_sound(
        source,
        volume=volume,
        pan=pan,
        pitch=pitch,
        loops=loops,
        fade_in=fade_in,
        crossfade=crossfade,
        on_done=on_done,
        then=then,
        name=name,
        owner=item,
        scope=SCOPE_ENTITY,
    )


def tick_audio(world_dt: float) -> None:
    """Pump the offline mixer (tests / headless) then no-op if a device is running."""
    get_mixer().pump_dt(world_dt)


def install_audio() -> None:
    import builtins
    builtins.audio = audio
