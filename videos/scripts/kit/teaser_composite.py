"""Lay the gameplay clips into the teaser's windows (ffmpeg).

The teaser (teaser/teaser.py) leaves a black pane wherever a clip goes, and
writes each pane to its cue sheet: when it opens (video_time), for how
long, and where (a rectangle in the 1280x720 design, from the top left).
This script scales each clip to its pane and overlays it there, from the
in-point chosen below. The teaser's own sound is kept; the clips are muted.

    python tools/video/record_game.py videos/scripts/teaser/teaser.py --seconds 93.5 \\
        --size 2560x1440 --prores --out videos/recordings/masters.nosync/teaser.mov
    python videos/scripts/kit/teaser_composite.py videos/recordings/masters.nosync/teaser.mov \\
        videos/recordings/teaser/scena_teaser.mp4
    python videos/scripts/kit/finish.py videos/recordings/teaser/scena_teaser.mp4 promo/scena_teaser

A third argument names another cue sheet (the code video's, teaser 2's); a
clip not in CLIPS is then videos/recordings/code/<clip>.mp4, from its start.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import recording, work     # noqa: E402

# clip name (as the teaser cues it) -> (recording, in-point in seconds)
CLIPS = {
    "ninja_5_espada": ("ninja_5_espada/full.mp4", 21.0),
    "osciloscopio": ("osciloscopio/tour.mp4", 39.0),
    "constelacao": ("constelacao/tour.mp4", 13.0),
    "naves_6_atos": ("naves_6_atos/victory.mp4", 6.0),
    "aviao_paisagem": ("aviao_paisagem/flights.mp4", 20.0),
    "scena-editor": ("scena-editor/session.mp4", 8.0),
}


def probe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")
    return int(w), int(h)


def even(v):
    return int(round(v / 2)) * 2


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    teaser, out = sys.argv[1], sys.argv[2]
    sheet = sys.argv[3] if len(sys.argv) == 4 else os.path.join(work("teaser"), "cues.json")
    cues = [c for c in json.load(open(sheet)) if c["kind"] == "clip"]
    width, height = probe_size(teaser)
    k = width / 1280
    inputs = ["-i", teaser]
    chains = []
    last = "0:v"
    for n, c in enumerate(cues, start=1):
        # a cue that names its recording (teaser 2), the teaser's clips, or a
        # fragment of the code video (from its start)
        if "recording" in c:
            path, start = c["recording"], c.get("start", 0.0)
        else:
            path, start = CLIPS.get(c["clip"], (f"code/{c['clip']}.mp4", 0.0))
        inputs += ["-ss", str(start), "-t", str(c["seconds"]), "-i", recording(path)]
        x, y, w, h = (even(v * k) for v in c["rect"])
        t = c["video_time"]
        chains.append(f"[{n}:v]scale={w}:{h}:flags=lanczos,setpts=PTS-STARTPTS+{t}/TB[c{n}]")
        chains.append(f"[{last}][c{n}]overlay={x}:{y}:eof_action=pass:"
                      f"enable='between(t,{t},{t + c['seconds']})'[v{n}]")
        last = f"v{n}"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", f"[{last}]", "-map", "0:a",
           "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", "60", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", out]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
