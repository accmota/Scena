"""Lay the gameplay clips into a promo video's windows (ffmpeg).

The video (teaser3.py, teaser3_vertical.py, engine_video.py) leaves a black
pane wherever a clip goes, and writes each pane to its cue sheet: when it
opens (video_time), for how long, where (a rectangle in design units, from
the top left), which recording and from where. This script scales each clip
to its pane and overlays it there. The video's own sound is kept; the clips
are muted.

    python videos/scripts/kit/promo_composite.py VIDEO.mov OUT.mp4 CUES.json \\
        [--design 1280x720] [--start S]

--start S drops the first S seconds of the result (a Short that must not open on black).

A cue may also have:
  crop   [x, y, w, h] of the recording (its pixels): that part fills the pane
  mask   [[t, share], ...]: the clip shows only right of a moving edge, at
         share x the pane's width from its left (t: seconds from the clip's
         start; smoothstep between two keys, as the video draws its scanner)
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import recording     # noqa: E402


def probe_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    w, h = out.strip().split(",")
    return int(w), int(h)


def even(v):
    return int(round(v / 2)) * 2


def edge_expr(keys):
    """The mask's edge (a share of the width) at clip time T, as an ffmpeg expression."""
    expr = f"{keys[-1][1]}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        u = f"(T-{t0})/{t1 - t0}"
        seg = f"({v0}+({v1 - v0})*{u}*{u}*(3-2*{u}))"
        expr = f"if(lt(T,{t1}),{seg},{expr})"
    return f"if(lt(T,{keys[0][0]}),{keys[0][1]},{expr})"


def main():
    args = sys.argv[1:]
    design = (1280, 720)
    if "--design" in args:
        i = args.index("--design")
        design = tuple(int(v) for v in args[i + 1].split("x"))
        del args[i:i + 2]
    start_at = 0.0
    if "--start" in args:
        i = args.index("--start")
        start_at = float(args[i + 1])
        del args[i:i + 2]
    if len(args) != 3:
        sys.exit(__doc__)
    video, out, sheet = args
    cues = [c for c in json.load(open(sheet)) if c["kind"] == "clip"]
    width, height = probe_size(video)
    k = width / design[0]
    inputs = ["-i", video]
    chains = []
    last = "0:v"
    for n, c in enumerate(cues, start=1):
        path, start = c["recording"], c.get("start", 0.0)
        inputs += ["-ss", str(start), "-t", str(c["seconds"]), "-i", recording(path)]
        x, y, w, h = (even(v * k) for v in c["rect"])
        t = c["video_time"]
        crop = "crop={2}:{3}:{0}:{1},".format(*c["crop"]) if c.get("crop") else ""
        chain = f"[{n}:v]{crop}scale={w}:{h}:flags=lanczos,fps=60"
        if c.get("mask"):
            chains.append(f"color=c=white:s={w}x{h}:r=60:d={c['seconds']},format=gray,"
                          f"geq=lum='if(gte(X,W*({edge_expr(c['mask'])})),255,0)'[m{n}]")
            chains.append(f"{chain},format=yuva420p[s{n}]")
            chains.append(f"[s{n}][m{n}]alphamerge,setpts=PTS-STARTPTS+{t}/TB[c{n}]")
        else:
            chains.append(f"{chain},setpts=PTS-STARTPTS+{t}/TB[c{n}]")
        chains.append(f"[{last}][c{n}]overlay={x}:{y}:eof_action=pass:"
                      f"enable='between(t,{t},{t + c['seconds']})'[v{n}]")
        last = f"v{n}"
    audio = "0:a"
    if start_at:
        chains.append(f"[{last}]trim=start={start_at},setpts=PTS-STARTPTS[vt]")
        chains.append(f"[0:a]atrim=start={start_at},asetpts=PTS-STARTPTS[at]")
        last, audio = "vt", "[at]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chains),
           "-map", f"[{last}]", "-map", audio,
           "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", "60", "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", out]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
