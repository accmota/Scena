"""Media of the third teaser (teaser3.py) and its vertical cut
(teaser3_vertical.py): the music and the stairs' stills.

  python videos/scripts/teaser3/make_media.py            # all of it
  python videos/scripts/teaser3/make_media.py --music    # the music only

Music: "The Adventure Begins" (Bart Kelsey, CC BY 3.0), from the start to the
end of its second climax (145.6 s, where the piece drops to its quiet
reprise), then 1.2 s of that reprise fading out; one bar (16.59 s, 1.9675 s
long, a bar its next one repeats) is played twice, so the stairs' last words
stay longer: 147.57 s, then the fade. The vertical cut: "Adventure
Theme" by Cleyton Kauffman (CC0), its first 46.08 s (a phrase ends there),
faded over the last 0.8 s.

Stills: one frame of a tutorial chapter's game, 16:9, from the recordings
(the build-ups' frames are cropped to their game pane).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit"))
from paths import MUSIC, recording, work     # noqa: E402

MUSIC_IN = os.path.join(MUSIC, "little_town_orchestral.ogg")
MUSIC_OUT = os.path.join(work("teaser3"), "adventure_cut.flac")
END, TAIL = 145.6, 1.2
LOOP_AT, LOOP = 16.59, 1.9675      # the bar played twice (the join matches at 0.80)
XF = 0.03
VERTICAL_IN = os.path.join(MUSIC, "super_hero_original_no_intro.ogg")
VERTICAL_OUT = os.path.join(work("teaser3_vertical"), "hero_short.flac")
VERTICAL_END, VERTICAL_FADE = 46.08, 0.8

# the game pane of a build-up frame (2560 x 1440), 16:9 inside it
PANE = "crop=1536:864:1024:284"
# (chapter, name, recording, second, crop)
STEPS = (
    ("01", "First script", "buildup/first_script/step_13.mp4", 3, PANE),
    ("02", "Catch the stars", "buildup/catch_stars/step_10.mp4", 4, PANE),
    ("05", "Ships", "buildup/ships_1/step_16.mp4", 4, PANE),
    ("10", "Balls", "buildup/balls/step_10.mp4", 4, PANE),
    ("12", "Movement", "buildup/movement/step_08.mp4", 6, PANE),
    ("15", "Plane", "aviao_paisagem/flights.mp4", 20, None),
    ("18", "Ninja", "ninja_5_espada/full.mp4", 30, None),
    ("21", "Connect Four", "connect_four/red_row.mp4", 9, None),
    ("29", "Endless runner", "runner/debug.mp4", 0.5, None),
    ("30", "Spins", "osciloscopio/tour.mp4", 39, None),
    ("31", "Duel", "duel/match.mp4", 8, None),
    ("32", "Race", "race/serpentine.mp4", 16, None),
    ("33", "A hundred lines", "hundred_lines/wall.mp4", 25, None),
)


def music():
    end = END + LOOP
    graph = (f"[0]atrim=0:{LOOP_AT + LOOP + XF:.4f},asetpts=N/SR/TB[a];"
             f"[1]atrim={LOOP_AT:.4f}:{END + TAIL:.4f},asetpts=N/SR/TB[b];"
             f"[a][b]acrossfade=d={XF}:c1=tri:c2=tri,"
             f"afade=t=out:st={end:.4f}:d={TAIL}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MUSIC_IN, "-i", MUSIC_IN,
                    "-filter_complex", graph, MUSIC_OUT], check=True)
    # asetpts: the Ogg's packet times go back on themselves; counted samples do not
    graph = (f"asetpts=N/SR/TB,atrim=0:{VERTICAL_END},"
             f"afade=t=out:st={VERTICAL_END - VERTICAL_FADE}:d={VERTICAL_FADE}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", VERTICAL_IN, "-af", graph,
                    VERTICAL_OUT], check=True)


def stills():
    out = os.path.join(work("teaser3"), "steps")
    os.makedirs(out, exist_ok=True)
    for chapter, _, rec, second, crop in STEPS:
        vf = (crop + "," if crop else "") + "scale=640:360:flags=lanczos"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(second), "-i",
                        recording(rec), "-frames:v", "1", "-vf", vf,
                        "-q:v", "3", os.path.join(out, still_name(chapter))], check=True)


def still_name(chapter):
    """A still's file: not "01.jpg" (numbered files are read as an animation)."""
    return f"chapter_{chapter}_still.jpg"


if __name__ == "__main__":
    music()
    if "--music" not in sys.argv:
        stills()
