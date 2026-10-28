"""How long a 40 ms audio block takes beside a thread that never sleeps (WP51).

The device callback mixes in Python and its numpy calls give the GIL up; each
take-back waits for the switch interval while the main thread holds the GIL.
``Mixer.start_device`` lowers the interval to ``AUDIO_SWITCH_INTERVAL``. This
probe mixes ``examples/pendulums.py``'s worst moment (13 voices) alone, then
beside a busy pure-Python thread at CPython's default 5 ms and at the
device's interval, interleaved, and prints the median ms a block. Run it on
each machine and compare the rows.

How much the busy thread slows the mix is the platform's GIL scheduling, not
Scena's code: the Windows laptop ~350x faster at the device's interval, the
Mac ~8x, GitHub's runners 0.2-1.7x (one block at 5 ms took ~2 ms there: the
busy thread never held the GIL). So this is a probe, not a test; the tests pin
what the engine does (``test_audio.TestAudioThreadGil``: the interval set
while the device plays, restored after).

    python scripts/bench/perf_audio_gil.py
    python scripts/bench/perf_audio_gil.py --repeats 9
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import threading
import time
from typing import Dict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from scena.audio import SAMPLE_RATE  # noqa: E402
from scena.audio_mixer import AUDIO_SWITCH_INTERVAL, Mixer  # noqa: E402

BLOCK = 1764            # the 40 ms block the device asks for at 44.1 kHz
VOICES = 13             # pendulums.py at its loudest
DEFAULT_INTERVAL = 0.005


def _sine(freq: float, seconds: float) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    mono = (0.05 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def mixer(voices: int = VOICES) -> Mixer:
    """A mixer with ``voices`` playing, its first block rendered (START
    commands, first-touch costs)."""
    m = Mixer()
    for k in range(voices):
        m.start_voice(samples=_sine(220 + 30 * k, 30.0), pitch=1 + k / 20,
                      pan=k / voices - 0.5)
    m.render_block(BLOCK)
    return m


def measure(repeats: int = 5, voices: int = VOICES) -> Dict[str, float]:
    """Median ms a block: alone, then beside a busy thread at the default and
    at the device's interval (interleaved, so load hits both alike)."""
    m = mixer(voices)
    saved = sys.getswitchinterval()
    alone = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        m.render_block(BLOCK)
        alone.append(time.perf_counter() - t0)

    stop = threading.Event()

    def busy():
        n = 0
        while not stop.is_set():
            n += 1

    worker = threading.Thread(target=busy, daemon=True)
    worker.start()
    intervals = {"busy, 5 ms": DEFAULT_INTERVAL,
                 f"busy, {AUDIO_SWITCH_INTERVAL * 1000:g} ms": AUDIO_SWITCH_INTERVAL}
    walls: Dict[str, list] = {name: [] for name in intervals}
    try:
        for _ in range(repeats):
            for name, interval in intervals.items():
                sys.setswitchinterval(interval)
                t0 = time.perf_counter()
                m.render_block(BLOCK)
                walls[name].append(time.perf_counter() - t0)
    finally:
        sys.setswitchinterval(saved)
        stop.set()
        worker.join()
    out = {"alone": statistics.median(alone) * 1000.0}
    out.update({name: statistics.median(w) * 1000.0 for name, w in walls.items()})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args(argv)
    print(f"{platform.system()} {platform.release()}, {platform.machine()}, "
          f"{platform.processor() or 'cpu ?'}, {os.cpu_count()} threads")
    print(f"Python {platform.python_version()}, numpy {np.__version__}")
    rows = measure(args.repeats)
    print(f"{VOICES} voices, a {BLOCK}-frame block, median of {args.repeats}:")
    for name, ms in rows.items():
        print(f"  {name:<15} {ms:8.1f} ms")
    default, device = list(rows.values())[1:]
    print(f"  the device's interval: {default / max(device, 1e-6):.1f}x faster")


if __name__ == "__main__":
    main()
