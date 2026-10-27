"""Audio stress harness: broken files, a live device without speakers, census.

Not a test module (no ``test_`` prefix). ``tests/test_audio_stress.py`` and
``tests/test_audio_exit.py`` use it (Testing Design, "Audio stress").

- ``bad_assets(folder)`` writes every kind of file an author can hand
  ``play_sound``: broken, misnamed, odd rates and channel counts, a name
  outside ASCII, and paths that are not files. Stdlib
  ``wave`` only (no ``soundfile``).
- ``live_mixer()`` starts the mixer on miniaudio's NULL backend: the real
  device thread pulls blocks in real time, with no speakers. Every other
  audio test runs the mixer offline, on the main thread.
- ``audio_census()`` counts what a sound can leak: voices, finished ids,
  queued commands, open streams, open file descriptors, threads.
- ``frames(n)`` advances the game clock and runs the process tick (the
  frame's audio step), optionally sleeping so a live device keeps pace.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import threading
import time
import wave

import numpy as np

from tests.media_support import media

RATE = 44100
# Lines that must never reach an author's terminal (Sound Design, "Failure contract").
NOISE = ("Exception ignored", "From cffi callback", "ResourceWarning", "Fatal Python error")


def write_wav(path: str, seconds: float, *, rate: int = RATE, channels: int = 2,
              amp: float = 0.3, freq: float = 440.0) -> str:
    n = int(seconds * rate)
    t = np.arange(n) / rate
    mono = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(mono[:, None], channels, axis=1).tobytes())
    return path


def bad_assets(folder: str) -> dict:
    """``{kind: path}``. ``plays``: a kind that holds sound (it must be heard,
    with no warning); every other kind is the missing-file silence (one
    warning). See ``PLAYS``."""
    good = write_wav(os.path.join(folder, "good.wav"), 0.5)
    with open(good, "rb") as fh:
        raw = fh.read()
    ogg = media("audio", "footstep_snow_001.ogg")
    out = {"good.wav": good}

    def put(name, data):
        path = os.path.normpath(os.path.join(folder, name))
        with open(path, "wb") as fh:
            fh.write(data)
        out[name] = path

    put("zero.wav", b"")
    put("header_only.wav", raw[:44])
    put("truncated.wav", raw[: len(raw) // 2])
    put("garbage.wav", b"not a wav at all, only text")
    with open(ogg, "rb") as fh:
        put("ogg_named.wav", fh.read())
    put("no_extension", raw)
    put("aac.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 64)
    out["mono_8k.wav"] = write_wav(os.path.join(folder, "mono_8k.wav"), 0.5, rate=8000, channels=1)
    out["hi_96k.wav"] = write_wav(os.path.join(folder, "hi_96k.wav"), 0.5, rate=96000)
    out["six_channels.wav"] = write_wav(os.path.join(folder, "six_channels.wav"), 0.5, channels=6)
    put("ção 音.wav", raw)
    os.mkdir(os.path.join(folder, "folder.wav"))
    out["folder.wav"] = os.path.join(folder, "folder.wav")
    out["missing.wav"] = os.path.join(folder, "missing.wav")
    return out


# Kinds that hold sound: heard, and no warning. ``header_only`` / ``truncated``
# decode what is there (nothing, or half): a short file, not a broken one.
PLAYS = {"good.wav", "truncated.wav", "ogg_named.wav", "no_extension",
         "mono_8k.wav", "hi_96k.wav", "six_channels.wav", "ção 音.wav"}
SILENT_NO_WARNING = {"header_only.wav"}


def frames(n: int, dt: float = 1 / 60, *, sleep: bool = False) -> None:
    from scena import clock
    from scena.process import tick_processes
    for _ in range(n):
        clock.advance(dt)
        tick_processes()
        if sleep:
            time.sleep(dt)


def wait_frames(pred, timeout: float = 3.0, dt: float = 1 / 60) -> bool:
    """Run frames in real time until ``pred()`` or ``timeout`` seconds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        frames(1, dt, sleep=True)
    return bool(pred())


def miniaudio_or_none():
    try:
        import miniaudio
        return miniaudio
    except ImportError:
        return None


@contextlib.contextmanager
def live_mixer(buffersize_msec: int = 20):
    """The mixer on a real device thread (NULL backend: no speakers)."""
    miniaudio = miniaudio_or_none()
    if miniaudio is None:
        raise unittest_skip("no miniaudio: no device thread")
    from scena.audio_mixer import get_mixer
    mixer = get_mixer()
    mixer.start_device(backends=[miniaudio.Backend.NULL], buffersize_msec=buffersize_msec)
    try:
        yield mixer
    finally:
        mixer.stop_device()


def unittest_skip(reason: str):
    import unittest
    return unittest.SkipTest(reason)


def open_fds(limit: int = 4096) -> int:
    """Open file descriptors below ``limit`` (``fstat`` each: no directory
    scan, the same on every OS)."""
    n = 0
    for fd in range(limit):
        try:
            os.fstat(fd)
        except OSError:
            continue
        n += 1
    return n


def audio_census() -> dict:
    import sys
    from scena.audio_mixer import get_mixer
    mixer = get_mixer()
    audio_mod = sys.modules["scena.audio"]
    return {
        "voices": len(mixer.voices),
        "finished_pending": len(mixer._finished_pending),
        "queued": len(mixer.queue._q),
        "open_streams": len(list(audio_mod._OPEN_STREAMS)),
        "fds": open_fds(),
        "threads": threading.active_count(),
    }


def copy_media(folder: str, *parts: str, name: str = None) -> str:
    dst = os.path.join(folder, name or parts[-1])
    shutil.copy(media(*parts), dst)
    return dst
