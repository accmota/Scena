"""A game that ends while sound plays exits at once and prints nothing extra.

Each row is its own process with the mixer on a real device thread
(miniaudio's NULL backend; ``tests/audio_exit_child.py``): what plays (music,
a crossfade, a paused stream, a stream reopening its decoder, a Reverb tail,
50 voices) times how the game ends (``run()``'s cleanup, a script that just
ends, an author error, ``sys.exit``, Ctrl+C). Last, Ring Guardian itself ends
during its title music.

Bug classes (Sound Design, "Streams at exit" and "Failure contract"):

- **A decoder still open at interpreter teardown** printed "Exception ignored
  in _samples_stream_generator ... ma_decoder_uninit" when the window closed
  during the music (7bab69f). The tests there pin the mechanism in-process;
  these read the stderr the author sees.
- **A device still pulling at exit.** Without ``run()``'s cleanup, ``atexit``
  closed the streams while the device thread was inside one: every exit with
  a stream playing hung (AU8, 2026-10-27). ``atexit`` now stops the device
  first.

    python tests/run_tiers.py focused test_audio_exit
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.audio_exit_child import HOW, PLAYING
from tests.audio_stress_support import NOISE, miniaudio_or_none

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHILD = os.path.join(ROOT, "tests", "audio_exit_child.py")
HARNESS = os.path.join(ROOT, "tests", "script_harness.py")
# A hang detector: a row takes ~1 s alone. Before AU8 every hanging row sat
# here until killed.
TIMEOUT = 60.0
EXPECTED_EXIT = {"cleanup": (0,), "atexit": (0,), "sysexit": (0,), "raise": (1,),
                 "sigint": (-2, 130, 1, 0xC000013A)}


def run(args):
    try:
        p = subprocess.run(
            [sys.executable, "-X", "dev", *args], capture_output=True, encoding="utf-8",
            errors="replace", timeout=TIMEOUT, cwd=ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        return None
    return p


def noise(stderr: str):
    return [ln for ln in stderr.splitlines() if any(n in ln for n in NOISE)]


class TestExitWhilePlaying(unittest.TestCase):
    def setUp(self):
        if miniaudio_or_none() is None:
            self.skipTest("no miniaudio: no device thread")

    def test_every_exit_with_every_sound_is_quick_and_quiet(self):
        hows = [h for h in HOW if not (h == "sigint" and os.name == "nt")]
        rows = [(p, h) for p in PLAYING for h in hows]
        workers = max(2, min(6, (os.cpu_count() or 4) - 1))
        with ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda r: (r, run([CHILD, *r])), rows))
        bad = []
        for (playing, how), p in results:
            if p is None:
                bad.append(f"{playing}/{how}: hung (> {TIMEOUT:.0f} s)")
                continue
            if "PLAYING" not in p.stdout:
                bad.append(f"{playing}/{how}: never played: {p.stderr.strip()[-300:]}")
            elif p.returncode not in EXPECTED_EXIT[how]:
                bad.append(f"{playing}/{how}: exit {p.returncode}: {p.stderr.strip()[-300:]}")
            elif noise(p.stderr):
                bad.append(f"{playing}/{how}: {noise(p.stderr)[0]}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_ring_guardian_ends_during_its_music(self):
        """The 7bab69f case: the title's music streams on a live device."""
        p = run([HARNESS, os.path.join(ROOT, "examples", "guardian.py"), "90", "--live-audio"])
        self.assertIsNotNone(p, "the game hung at exit")
        self.assertIn("SCRIPT OK 90", p.stdout, p.stderr[-500:])
        self.assertEqual(p.returncode, 0)
        self.assertEqual(noise(p.stderr), [])


if __name__ == "__main__":
    unittest.main()
