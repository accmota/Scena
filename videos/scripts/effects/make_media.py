"""Media of the effects video (effects_video.py): the music.

  python videos/scripts/effects/make_media.py

Music: "Boss Battle Music" (Juhani Junkala, CC0) at 178.2 bpm, its bar 0 (the title
holds a bar longer; bar 1 nearly repeats it), its bars 0-44, then bars 40-87 (the
four bars of the layered sky once more, for its parallax), then bars 79-91 (a
phrase repeated, so the slow last act fits, then the track's end): 104 bars,
140.3 s, faded over the last two. The joins fall on bar lines,
crossfaded 15 ms. A WAV: the ogg's packets give the FLAC muxer
non-monotonic timestamps.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "juhani_junkala_epic_boss_battle.ogg")
MUSIC_OUT = os.path.join(work("effects"), "boss_cut.wav")
BAR = 4 * 0.3367
FIRST = 0.244
BARS = 104
END = FIRST + BARS * BAR
FADE = 2 * BAR
XF = 0.015


def bar(n):
    return FIRST + n * BAR


if __name__ == "__main__":
    pieces = [(0, 1), (0, 44), (40, 87), (79, None)]       # bars of the track, in order
    graph, last = "", None
    for k, (a, b) in enumerate(pieces):
        end = f":{bar(b) + XF:.4f}" if b is not None else ""
        begin = bar(a) if k else 0                  # the first piece keeps the lead-in
        graph += f"[{k}]atrim={begin:.4f}{end},asetpts=N/SR/TB[p{k}];"
    for k in range(1, len(pieces)):
        into = f"[p{k - 1}]" if k == 1 else f"[j{k - 1}]"
        graph += f"{into}[p{k}]acrossfade=d={XF}:c1=tri:c2=tri"
        graph += f"[j{k}];" if k < len(pieces) - 1 else ""
    graph += f",atrim=0:{END:.4f},afade=t=out:st={END - FADE:.4f}:d={FADE:.4f}"
    inputs = [arg for _ in pieces for arg in ("-i", MUSIC_IN)]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs,
                    "-filter_complex", graph, "-c:a", "pcm_s16le", MUSIC_OUT], check=True)
