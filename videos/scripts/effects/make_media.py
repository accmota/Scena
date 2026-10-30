"""Media of the effects video (effects_video.py): the music.

  python videos/scripts/effects/make_media.py

Music: "Boss Battle Music" (Juhani Junkala, CC0) at 178.2 bpm, its bars 0-87, then
bars 79-87 once more (a phrase repeated, so the slow last act fits), then bars
87-91 (the track's end): 99 bars, 133.6 s, faded over the last two. The joins fall
on bar lines, crossfaded 15 ms. A WAV: the ogg's packets give the FLAC muxer
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
BARS = 99
END = FIRST + BARS * BAR
FADE = 2 * BAR
XF = 0.015


def bar(n):
    return FIRST + n * BAR


if __name__ == "__main__":
    a, b, c = bar(87), bar(79), bar(87)
    graph = (f"[0]atrim=0:{a + XF:.4f},asetpts=N/SR/TB[p];"
             f"[1]atrim={b:.4f}:{c + XF:.4f},asetpts=N/SR/TB[q];"
             f"[2]atrim={c:.4f},asetpts=N/SR/TB[r];"
             f"[p][q]acrossfade=d={XF}:c1=tri:c2=tri[pq];"
             f"[pq][r]acrossfade=d={XF}:c1=tri:c2=tri,atrim=0:{END:.4f},"
             f"afade=t=out:st={END - FADE:.4f}:d={FADE:.4f}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-i", MUSIC_IN, "-i", MUSIC_IN,
                    "-filter_complex", graph, "-c:a", "pcm_s16le", MUSIC_OUT], check=True)
