"""A built video becomes its final: the upload in videos/finals/<series>/.

    python videos/scripts/kit/finish.py VIDEO.mp4 SERIES/NAME [--keep-level]

  SERIES/NAME   promo/scena_teaser3, buildups/buildup_balls, ...
                (the final is videos/finals/promo/scena_teaser3.mp4)

The picture is copied as it is (already 2560x1440, 60 fps, H.264: YouTube
gives 1440p uploads its better codec); only the sound is levelled to
YouTube's -14 LUFS. YouTube turns a loud video down to -14 LUFS but never
turns a quiet one up, so a quiet one would play quieter than everything
around it: it is raised, and a limiter keeps the peaks at -1.5 dBFS (the
raise can push the loudest ones over). A loud one is lowered (a plain gain).
A silent one (no sound, or below -60 LUFS) is moved as it is, and so is one
given --keep-level: Balls is sound effects only, already peaking at -1 dB,
and raising it would squash every click.

The video is consumed: there is one copy, the final. A build-up's subtitles
(VIDEO with .srt) go with it. To level a final again, build it again.

Measured with: ffmpeg -i X -vn -af loudnorm=I=-14:TP=-1:print_format=json -f null -
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import FINALS     # noqa: E402

TARGET = -14.0          # LUFS, YouTube's
SILENT = -60.0          # below this, nothing to level
LIMIT = 0.841           # -1.5 dBFS, the limiter's ceiling when the sound is raised
CLOSE = 0.5             # dB: a video this close to TARGET is moved as it is


def loudness(path):
    """(integrated LUFS, true peak dBTP) of ``path``'s sound, or None if it has none."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=index", "-of", "csv=p=0", path],
                           capture_output=True, text=True, check=True)
    if not probe.stdout.strip():
        return None
    run = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-vn", "-af",
                          "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, check=True)
    stats = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", run.stderr).group(0))
    return float(stats["input_i"]), float(stats["input_tp"])


def level(src, out, gain):
    graph = f"volume={gain:.1f}dB"
    if gain > 0:
        graph += f",alimiter=limit={LIMIT}:level=disabled:attack=5:release=60"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:v", "-map", "0:a",
                    "-c:v", "copy", "-af", graph, "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
                    "-movflags", "+faststart", out], check=True)


def gain_for(measured):
    """The gain in dB that brings ``measured`` ((LUFS, peak) or None) to TARGET,
    or None: no sound, silence, or already close enough (moved as it is)."""
    if measured is None or measured[0] < SILENT or abs(TARGET - measured[0]) < CLOSE:
        return None
    return TARGET - measured[0]


def finish(src, name, keep_level=False):
    """Level (or move) ``src`` to ``videos/finals/<name>.mp4``; returns the final."""
    out = os.path.join(FINALS, name + ".mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    measured = None if keep_level else loudness(src)
    gain = gain_for(measured)
    if gain is None:
        os.replace(src, out)
        how = "moved" if measured is None else f"moved ({measured[0]:.1f} LUFS)"
    else:
        level(src, out, gain)
        os.remove(src)
        how = f"{measured[0]:.1f} LUFS, {gain:+.1f} dB" + (" + limiter" if gain > 0 else "")
    srt = os.path.splitext(src)[0] + ".srt"
    if os.path.exists(srt):
        os.replace(srt, os.path.splitext(out)[0] + ".srt")
    print(f"{out}: {how}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video", help="the built .mp4 (consumed)")
    ap.add_argument("name", help="SERIES/NAME under videos/finals/, without .mp4")
    ap.add_argument("--keep-level", action="store_true", help="move it without levelling")
    args = ap.parse_args()
    finish(args.video, args.name, args.keep_level)


if __name__ == "__main__":
    main()
