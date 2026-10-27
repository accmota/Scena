"""One exit of a game with sound playing: ``python audio_exit_child.py <playing> <how>``.

Not a test module (no ``test_`` prefix). ``tests/test_audio_exit.py`` starts
one process per row. The mixer runs on a real device thread (miniaudio's NULL
backend: no speakers), as in a windowed game. ``<playing>`` is what plays when
the game ends; ``<how>`` is how it ends:

- ``cleanup``: ``run()``'s audio cleanup, then the script ends (the window closed);
- ``atexit``: the script just ends (no ``run()``: only ``atexit`` cleans up);
- ``raise``: an error in the author's code;
- ``sysexit``: ``sys.exit(0)`` from a handler;
- ``sigint``: Ctrl+C.
"""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import miniaudio  # noqa: E402

from tests.audio_stress_support import frames, write_wav  # noqa: E402
from tests.media_support import media  # noqa: E402

from scena import play_sound  # noqa: E402
from scena.audio_effects import Reverb  # noqa: E402
from scena.audio_mixer import get_mixer  # noqa: E402

PLAYING = ("music", "crossfade", "paused", "reopen", "reverb", "many")
HOW = ("cleanup", "atexit", "raise", "sysexit", "sigint")


def start(playing: str) -> None:
    if playing == "music":
        play_sound(media("music", "space.ogg"), loops="forever", name="music")
    elif playing == "crossfade":
        play_sound(media("music", "space.ogg"), loops="forever", name="music")
        frames(10, sleep=True)
        play_sound(media("music", "battle_in_the_winter.ogg"), loops="forever",
                   name="music", crossfade=2)
    elif playing == "paused":
        play_sound(media("music", "space.ogg"), loops="forever").pause()
    elif playing == "reopen":          # a stream reopening its decoder every ~0.3 s
        path = write_wav(os.path.join(tempfile.mkdtemp(), "loop.wav"), 9.0, amp=0.05)
        play_sound(path, loops="forever", pitch=30.0)
    elif playing == "reverb":
        play_sound(media("audio", "fx2.wav")).effects.add(Reverb())
    elif playing == "many":
        for i in range(50):
            play_sound(media("audio", "laser7.wav"), pitch=0.5 + i / 50)
        play_sound(media("music", "the_field_of_dreams.ogg"))


def main(playing: str, how: str) -> None:
    get_mixer().start_device(backends=[miniaudio.Backend.NULL])
    start(playing)
    frames(20, sleep=True)
    print("PLAYING", flush=True)
    if how == "cleanup":
        get_mixer().stop_device()
        from scena.audio import close_open_streams
        close_open_streams()
    elif how == "raise":
        raise RuntimeError("the author's bug")
    elif how == "sysexit":
        sys.exit(0)
    elif how == "sigint":
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(2)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
