"""Media of the engine video (engine_video.py): the music.

  python videos/scripts/engine/make_media.py

Music: "Vampire's Piano" (TAD, CC0), an 89.4 s loop, played to 208 s and faded
over the last 3 s. The ogg carries 24 ms of silence at its start and 26 ms at
its end; each join drops them, or the loop hiccups. A WAV: the ogg's packets
give the FLAC muxer non-monotonic timestamps.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "vampires_piano.ogg")
MUSIC_OUT = os.path.join(work("engine"), "piano_cut.wav")
HEAD, TAIL, LENGTH = 0.024, 89.418, 89.443     # sound from HEAD to TAIL of LENGTH
END, FADE = 208.0, 3.0

if __name__ == "__main__":
    graph = (f"[0]atrim=0:{TAIL},asetpts=N/SR/TB[a];"
             f"[1]atrim={HEAD}:{TAIL},asetpts=N/SR/TB[b];"
             f"[2]atrim={HEAD},asetpts=N/SR/TB[c];"
             f"[a][b][c]concat=n=3:v=0:a=1,atrim=0:{END},"
             f"afade=t=out:st={END - FADE}:d={FADE}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-i", MUSIC_IN, "-i", MUSIC_IN,
                    "-filter_complex", graph, "-c:a", "pcm_s16le", MUSIC_OUT], check=True)
