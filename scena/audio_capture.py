"""Microphone capture. Explicit opt-in — nothing opens a device until construct."""
from __future__ import annotations

import atexit
import threading
import time
import weakref

import numpy as np

from .audio_effects import AudioEffectStack
from .closed import ClosedSurface
from .audio_mixer import (
    CHANNELS,
    DEFAULT_SPECTRUM_BINS,
    SAMPLE_RATE,
    FrameSource,
    PullSource,
    ema_alpha,
    loudness,
    require_finite,
    spectrum_bands,
)

# Open-ended takes stop here. Not a setting: a runaway record must not fill memory.
MAX_RECORD_SECONDS = 30.0

_capture_open_count = 0
_live_mics: "weakref.WeakSet[Microphone]" = weakref.WeakSet()


def capture_devices_open() -> int:
    """Test hook: how many CaptureDevices are currently live."""
    return _capture_open_count


def close_all_microphones() -> None:
    """Release every open capture device.

    Must run before interpreter finalization. A native device stopped from a
    GC finalizer at shutdown kills the OS audio thread: on macOS, CoreAudio's
    IO thread calls back into Python, ``PyGILState_Ensure`` exits that thread,
    and the workgroup cleanup asserts.
    """
    for mic in list(_live_mics):
        try:
            mic.close()
        except Exception:
            pass


atexit.register(close_all_microphones)


def _mic_stamp(mic) -> int:
    return mic._ingest_seq


class _Take:
    """One in-progress recording. Chunks append on the capture thread."""

    __slots__ = (
        "chunks", "frames", "limit_frames", "full", "finalized", "natural",
        "hit_cap", "sound", "handle", "mic", "silent_last", "silent_acc",
    )

    def __init__(self) -> None:
        self.chunks: list = []
        self.frames = 0
        self.limit_frames = 0
        self.full = False
        self.finalized = False
        self.natural = False
        self.hit_cap = False
        self.sound = None
        self.handle = None
        self.mic = None
        self.silent_last = 0.0
        self.silent_acc = 0.0


class Microphone(ClosedSurface):
    """Live capture. ``.level`` / ``.spectrum`` share ``audio.level_tau``.

    Construction opens the capture device (the OS default input). If none
    is available, the mic stays silent and warns once. ``play_sound(mic)``
    monitors; ``record`` / ``stop`` keep a dry clip. Analysis works without
    monitoring.

    Args:
        backends: List of ``miniaudio.Backend`` to try (advanced: tests / diagnostics).
            Omit for the OS default input.
    """

    def __init__(self, *, backends=None):
        global _capture_open_count
        self._closed = False
        self._silent = False
        self._device = None
        self._take: _Take | None = None
        self._cap_warned = False
        self._now = time.perf_counter
        self._lock = threading.Lock()
        # ~1 s jitter ring. Readers keep their own cursors so two monitors
        # hear the same capture instead of splitting the buffer.
        self._cap = SAMPLE_RATE
        self._ring = np.zeros((self._cap, CHANNELS), dtype=np.float32)
        self._fx_ring = np.zeros((self._cap, CHANNELS), dtype=np.float32)
        self._write_pos = 0
        self._fx_pos = 0
        self._level = 0.0
        self._spectrum = np.zeros(DEFAULT_SPECTRUM_BINS, dtype=np.float32)
        # Bumped after each analysis update (capture thread) and on close: the
        # frame's audio sample dirties a linked ``mic.level`` when it moves.
        self._ingest_seq = 0
        self.effects = AudioEffectStack(microphone=self)
        if backends is not None:
            import miniaudio
            items = list(backends) if isinstance(backends, (list, tuple)) else None
            if not items or not all(isinstance(b, miniaudio.Backend) for b in items):
                raise TypeError(
                    f"Microphone backends= expected a list of miniaudio.Backend, got "
                    f"{type(backends).__name__}. Leave it out to use the OS default input."
                )
        self._backends = backends
        self._open(backends)

    def _capture_device(self, miniaudio, backends):
        kwargs = dict(
            input_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=CHANNELS,
            sample_rate=SAMPLE_RATE,
            buffersize_msec=40,
        )
        if backends is not None:
            kwargs["backends"] = list(backends)
        try:
            return miniaudio.CaptureDevice(**kwargs)
        except TypeError:
            kwargs.pop("input_format", None)
            return miniaudio.CaptureDevice(**kwargs)

    def _fail_open(self) -> None:
        """No capture device: stay constructed, deliver silence, warn once."""
        from .process import report_author_warning

        self._device = None
        self._silent = True
        report_author_warning(
            "Microphone",
            "No input device; this microphone is silent. "
            "Choose an input in your system sound settings, or allow microphone access.",
        )

    def _open(self, backends) -> None:
        global _capture_open_count
        import miniaudio

        try:
            device = self._capture_device(miniaudio, backends)
        except Exception:
            self._fail_open()
            return

        mic = self

        def gen():
            data = yield b""
            while True:
                if data:
                    mic._ingest(data)
                data = yield

        try:
            g = gen()
            g.send(None)
            device.start(g)
        except Exception:
            try:
                device.close()
            except Exception:
                pass
            self._fail_open()
            return
        self._device = device
        self._generator = g
        self._silent = False
        _capture_open_count += 1
        _live_mics.add(self)

    def _write_frames(self, frames: np.ndarray) -> None:
        """Append ``frames`` to the ring. Caller holds ``_lock``."""
        n = int(frames.shape[0])
        cap = self._cap
        pos = self._write_pos
        offset = 0
        while offset < n:
            i = pos % cap
            take = min(n - offset, cap - i)
            self._ring[i:i + take] = frames[offset:offset + take]
            pos += take
            offset += take
        self._write_pos = pos
        if self._write_pos - self._fx_pos > cap:
            self._fx_pos = self._write_pos - cap

    def _ensure_fx(self, up_to: int) -> None:
        """Run mic effects once over raw samples ``[_fx_pos, up_to)``. Caller holds ``_lock``."""
        cap = self._cap
        fx = self.effects.live()
        while self._fx_pos < up_to:
            i = self._fx_pos % cap
            take = min(up_to - self._fx_pos, cap - i)
            chunk = self._ring[i:i + take]
            if fx:
                from .audio_effects import apply_effects
                chunk = apply_effects(chunk, fx, SAMPLE_RATE)
            self._fx_ring[i:i + take] = chunk
            self._fx_pos += take

    def _ingest(self, data) -> None:
        raw = np.frombuffer(memoryview(data), dtype=np.float32)
        if raw.size % CHANNELS:
            raw = raw[: raw.size - (raw.size % CHANNELS)]
        if raw.size == 0:
            return
        frames = np.array(raw, dtype=np.float32, copy=True).reshape(-1, CHANNELS)
        with self._lock:
            self._write_frames(frames)
            self._append_locked(self._take, frames)
        from .audio import audio
        tau = float(audio.level_tau)
        dt = frames.shape[0] / float(SAMPLE_RATE)
        try:
            a = ema_alpha(dt, tau)
        except ValueError:
            a = 1.0
        raw_l = loudness(frames)
        self._level += (raw_l - self._level) * a
        spec = spectrum_bands(frames, bins=DEFAULT_SPECTRUM_BINS, sample_rate=SAMPLE_RATE)
        self._spectrum += (spec - self._spectrum) * a
        self._ingest_seq += 1

    def _read_from(self, cursor_box, n_frames: int) -> np.ndarray:
        n = int(n_frames)
        out = np.zeros((max(n, 0), CHANNELS), dtype=np.float32)
        if n <= 0 or self._closed:
            return out
        with self._lock:
            write = self._write_pos
            cap = self._cap
            cursor = int(cursor_box[0])
            if write - cursor > cap:
                cursor = write - cap
            count = min(n, max(0, write - cursor))
            if count:
                self._ensure_fx(cursor + count)
                left = count
                dst = 0
                pos = cursor
                while left:
                    i = pos % cap
                    take = min(left, cap - i)
                    out[dst:dst + take] = self._fx_ring[i:i + take]
                    dst += take
                    pos += take
                    left -= take
                cursor_box[0] = cursor + count
        return out

    def _audio_frame_source(self) -> FrameSource:
        with self._lock:
            # Start at the oldest sample still in the ring so a monitor hears
            # the jitter buffer, and every monitor opened together shares it.
            oldest = max(0, self._write_pos - self._cap)
        cursor = [oldest]
        return PullSource(lambda n, c=cursor: self._read_from(c, n))

    def _formula_source(self):
        """The graph node an ``@=`` reading this mic depends on (``level_source``)."""
        from .level_source import level_source_for
        return level_source_for(self, _mic_stamp)

    @property
    def level(self) -> float:
        """Current input loudness, 0 … 1, smoothed over ``audio.level_tau`` seconds.

        Works without monitoring (``play_sound(mic)`` is not needed). A
        formula that reads it (``bar["width"] @= lambda: 300 * mic.level``)
        follows it, updated once per frame.
        """
        return float(self._level)

    def spectrum(self, bins: int = 8) -> list:
        """Input loudness per frequency band, low to high.

        Args:
            bins: how many bands (default 8).

        Returns:
            A list of ``bins`` numbers, 0 … 1.
        """
        from .audio import _resample_bins
        return _resample_bins(self._spectrum, bins)

    def _append_locked(self, take: _Take | None, frames: np.ndarray) -> None:
        """Append raw frames to ``take``, stopping at its limit. Caller holds ``_lock``."""
        if take is None or take.finalized or take.full:
            return
        remaining = int(take.limit_frames) - int(take.frames)
        if remaining <= 0:
            take.full = True
            return
        n = int(frames.shape[0])
        if n > remaining:
            # Copy: a prefix view would keep the rest of this callback alive.
            frames = np.array(frames[:remaining], dtype=np.float32, copy=True)
            n = int(frames.shape[0])
        if n > 0:
            take.chunks.append(frames)
            take.frames += n
        if take.frames >= take.limit_frames:
            take.full = True

    def _fill_silent(self, take: _Take) -> None:
        """Advance a no-device take by wall-clock zeros. Main thread."""
        if take.finalized or take.full:
            return
        now = float(self._now())
        dt = now - float(take.silent_last)
        take.silent_last = now
        if dt <= 0.0:
            return
        take.silent_acc += dt * float(SAMPLE_RATE)
        n = int(take.silent_acc)
        if n <= 0:
            return
        take.silent_acc -= n
        zeros = np.zeros((n, CHANNELS), dtype=np.float32)
        with self._lock:
            self._append_locked(take, zeros)

    def _warn_cap(self) -> None:
        if self._cap_warned:
            return
        self._cap_warned = True
        from .process import report_author_warning
        report_author_warning(
            "Microphone",
            f"Recording stopped at the {MAX_RECORD_SECONDS:g} s limit.",
        )

    def _service_record(self, take: _Take) -> None:
        """Poll hook: silent fill, then finalize a take that hit its limit."""
        if take.finalized:
            return
        if self._silent:
            self._fill_silent(take)
        with self._lock:
            full = bool(take.full)
            hit_cap = bool(take.hit_cap)
        if not full:
            return
        self._finish_take(take, natural=True)
        if hit_cap:
            self._warn_cap()

    def _finish_take(self, take: _Take, *, natural: bool) -> None:
        """Freeze ``take`` into its Sound. Idempotent. Safe from the main thread."""
        if take.finalized:
            return
        with self._lock:
            if take.finalized:
                return
            chunks = take.chunks
            take.chunks = []
            take.finalized = True
            take.natural = bool(natural)
            take.full = True
            if self._take is take:
                self._take = None
        if not chunks:
            pcm = np.zeros((0, CHANNELS), dtype=np.float32)
        elif len(chunks) == 1:
            pcm = np.ascontiguousarray(chunks[0], dtype=np.float32)
        else:
            pcm = np.concatenate(chunks, axis=0)
        sound = take.sound
        if sound is not None:
            sound._finalize(pcm)

    def record(self, seconds=None, *, on_done=None, then=None):
        """Start a dry clip. Returns a ``Sound`` that is not playable until the take ends.

        ``seconds=`` ends the take after that many captured samples (not game-clock
        seconds). Omit it to record until ``stop()`` or the 30 s cap. ``await``
        on the returned clip waits for that end and returns the same clip.
        ``on_done`` / ``then=`` fire on the next process tick after a natural end
        (``stop()``, ``seconds=``, or the cap) — not after a cut.
        """
        if self._closed:
            raise RuntimeError(
                "this microphone is closed — construct a new Microphone()"
            )
        current = self._take
        if current is not None and not current.finalized:
            raise RuntimeError(
                "already recording — check mic.recording or call mic.stop() first"
            )
        if seconds is None:
            limit_s = MAX_RECORD_SECONDS
            hit_cap = True
        else:
            limit_s = require_finite("seconds", seconds, positive=True)
            if limit_s > MAX_RECORD_SECONDS:
                raise ValueError(
                    f"seconds must be finite and <= {MAX_RECORD_SECONDS:g} "
                    f"(the recording cap)"
                )
            hit_cap = False

        from .audio import Sound
        from .process import (
            Handle,
            _fn_and_then,
            _infer_owner,
            _require_then_owner,
            get_scheduler,
        )

        callback, then = _fn_and_then(None, then, call_name="record", on_done=on_done)
        owner, scope = _infer_owner(callback if callback is not None else then)
        _require_then_owner(then, owner, call_name="record")

        take = _Take()
        take.mic = self
        take.limit_frames = int(round(float(limit_s) * SAMPLE_RATE))
        take.hit_cap = hit_cap
        take.silent_last = float(self._now())
        if take.limit_frames <= 0:
            take.full = True
        sound = Sound._recording(take)
        take.sound = sound
        handle = Handle._make(
            kind="record",
            fn=callback,
            then=then,
            owner=owner,
            scope=scope,
        )
        handle._result = sound
        handle._record = take
        take.handle = handle
        sound._record_handle = handle
        self._take = take
        get_scheduler().add(handle)
        return sound

    def stop(self) -> None:
        """End the current take and keep the clip. The microphone stays open.

        The clip is playable on the next line. ``on_done`` / ``then=`` run on
        the next process tick.
        """
        if self._closed:
            raise RuntimeError(
                "this microphone is closed — construct a new Microphone()"
            )
        take = self._take
        if take is None or take.finalized:
            raise RuntimeError(
                "mic.stop() with nothing recording — call mic.record() first"
            )
        self._finish_take(take, natural=True)

    @property
    def recording(self) -> bool:
        """True between ``record()`` and ``stop()`` (or the take's ``seconds=`` limit)."""
        take = self._take
        return take is not None and not take.finalized and not self._closed

    def close(self) -> None:
        """Release the input device. A take in progress is cut (its samples are kept).

        Safe to call twice. A closed microphone cannot record again — build a new
        ``Microphone()``.
        """
        global _capture_open_count
        if self._closed:
            return
        take = self._take
        if take is not None and not take.finalized:
            handle = take.handle
            if handle is not None:
                handle.cancel()
        self._closed = True
        dev = self._device
        self._device = None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass
            _capture_open_count = max(0, _capture_open_count - 1)
        _live_mics.discard(self)
        with self._lock:
            self._ring[:] = 0
            self._fx_ring[:] = 0
            self._write_pos = 0
            self._fx_pos = 0
        self._level = 0.0
        self._spectrum[:] = 0
        self._ingest_seq += 1
