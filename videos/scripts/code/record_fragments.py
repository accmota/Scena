"""Record every fragment of the code video (one child process each).

    python videos/scripts/code/record_fragments.py            # all of them
    python videos/scripts/code/record_fragments.py stars_5    # one
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work     # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools", "video"))
OUT = work("code")

SWEEP = (("hold", 0.6, 1.2, "LEFT"),) + tuple(
    ("hold", 1.6 + 1.6 * k, 2.8 + 1.6 * k, "RIGHT" if k % 2 == 0 else "LEFT") for k in range(8))
CATCH = dict(paddle="paddle", group="stars", fall=180, speed=420, half=63, miss=0.15)
CARRY = (("carry", 0.8, 3.0, "@a", (300, 240)), ("carry", 3.8, 6.2, "@b", (500, 380)),
         ("carry", 7.0, 9.4, "@a", (380, 360)), ("carry", 10.0, 12.4, "@b", (470, 250)))

FRAGMENTS = {
    "grow_1": dict(), "grow_2": dict(), "grow_3": dict(), "grow_4": dict(),
    "stars_1": dict(), "stars_2": dict(pilot="tour", args=dict(script=SWEEP)),
    "stars_3": dict(pilot="catch_falling", args=CATCH),
    "stars_4": dict(pilot="catch_falling", args=CATCH),
    "stars_5": dict(pilot="catch_falling", args=CATCH),
    "formulas": dict(), "geometry": dict(pilot="tour", args=dict(script=CARRY)),
    "groups": dict(), "boss": dict(),
    "electric_hosts": dict(seconds=10, size=(1800, 600)),
}


def one(name):
    import record_game as rg
    spec = FRAGMENTS[name]
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, name + ".mp4")

    def factory(size, fps):
        return rg.FfmpegSink(rg.Path(out), size, fps, ffmpeg=rg.find_ffmpeg(), crf=12,
                             prores=False)

    r = rg.record(os.path.join(HERE, name + ".py"), factory, pilot=spec.get("pilot", "watch"),
                  args=spec.get("args"), seconds=spec.get("seconds", 16), size=spec.get("size", (1600, 1200)),
                  progress=False)
    print(f"{name}: {r['frames']} frames")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in FRAGMENTS:
        one(sys.argv[1])
    else:
        for name in FRAGMENTS:
            subprocess.run([sys.executable, __file__, name], check=True)
