#!/usr/bin/env python3
"""Build-up videos: a tutorial's steps one after another, code beside game.

A tutorial page (``docs/<lang>/tutorial/NN-*.html``) holds its steps as whole
programs (``tests/test_tutorials.extract_steps``, the reader the tutorial
tests use). A build-up video plays each step for a few seconds in the
"this code → this game" layout (``record_game.record(layout="code")``): the
step's code on the left, headed "Passo N · <title>" and with the lines this
step adds or changes marked, and the step running on the right, played by
its own pilot so its new part shows (``BUILDUPS`` in ``takes.py``). Each step
is a clip of its own (a child process each); ffmpeg joins them without
re-encoding (same size, rate and codecs).

  recordings/buildup/<id>/passo_NN.mp4   one clip per step
  recordings/buildup/<id>.mp4            the steps joined

  python tools/video/buildup.py --list
  python tools/video/buildup.py primeiro_script            # every step, then joined
  python tools/video/buildup.py primeiro_script --review   # one review sheet per step
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # tools/video (this script)
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO))

import record_game as rg  # noqa: E402

OUT = rg.RECORDINGS / "buildup"
STEP_DEFAULTS = dict(pilot="watch", args={}, seconds=4.0, lead=0.0)


def page_steps(page: str) -> list[tuple[int, str, str]]:
    """``(n, title, code)`` for each step of a tutorial page, from 1. The title
    is the page data's last ``title:`` before the step's code."""
    from tests.test_tutorials import extract_steps, _read
    html = _read(str(REPO / page))
    lines = html.split("\n")
    out = []
    for n, step in enumerate(extract_steps(str(REPO / page)), start=1):
        titles = re.findall(r'title:\s*"([^"]*)"', "\n".join(lines[:step.line]))
        out.append((n, titles[-1] if titles else "", step.code))
    return out


def new_lines(before: str, after: str) -> list[int]:
    """Lines of ``after`` (0-based, as the panel shows it) this step adds or
    changes; blank lines are not marked."""
    a = rg.program_code(before).splitlines() if before else []
    b = rg.program_code(after).splitlines()
    marked = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            marked += [j for j in range(j1, j2) if b[j].strip()]
    return marked


def step_spec(bid: str, n: int) -> dict:
    from takes import BUILDUPS
    spec = {**STEP_DEFAULTS, **BUILDUPS[bid]["steps"].get(n, {})}
    spec["args"] = dict(spec["args"])
    return spec


def render_step(bid: str, n: int, *, review_only: bool = False, gpu: bool = True) -> dict:
    """Record step ``n`` of build-up ``bid`` (child-process body)."""
    from takes import BUILDUPS, DEFAULTS
    b = BUILDUPS[bid]
    steps = page_steps(b["page"])
    _, title, code = steps[n - 1]
    before = steps[n - 2][2] if n > 1 else ""
    spec = step_spec(bid, n)
    stem = f"passo_{n:02d}"
    out = OUT / bid / f"{stem}.mp4"
    size, fps = ((rg.REVIEW_SIZE, rg.REVIEW_FPS) if review_only
                 else (DEFAULTS["size"], DEFAULTS["fps"]))
    ffmpeg = None if review_only else rg.find_ffmpeg()
    reviews = []

    def factory(size, fps):
        inner = None if review_only else rg.FfmpegSink(out, size, fps, ffmpeg=ffmpeg,
                                                       crf=DEFAULTS["crf"])
        reviews.append(rg.Review(inner, fps))
        return reviews[-1]

    r = rg.record(b["program"], factory, pilot=spec["pilot"], args=spec["args"],
                  seconds=spec["seconds"], lead=spec["lead"], size=size, fps=fps, seed=n,
                  gpu=gpu, progress=False, source=code, layout="code",
                  code_title=f"Passo {n} · {title}", code_highlight=new_lines(before, code))
    sheet = OUT / bid / f"{stem}.review.jpg"
    rep = reviews[0].report()
    reviews[0].save_sheet(sheet, f"{bid} passo {n}: {title}   {rep['seconds']:.1f} s")
    return {"ok": True, "step": n, "title": title, "out": None if review_only else str(out),
            "sheet": str(sheet), "seconds": rep["seconds"], "ended": r["ended"]}


def _child(bid: str, n: int, review_only: bool) -> dict:
    cmd = [sys.executable, str(Path(__file__).resolve()), bid, "--step", str(n)]
    cmd += ["--review"] if review_only else []
    out = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace",
                         cwd=str(REPO), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for line in reversed(out.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    tail = "\n".join((out.stderr or "").strip().splitlines()[-6:])
    return {"ok": False, "step": n, "error": f"exit {out.returncode}: {tail}"}


def join(parts: list[Path], out: Path) -> Path:
    """The clips one after another, without re-encoding (ffmpeg concat)."""
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    subprocess.run([rg.find_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)],
                   check=True)
    listing.unlink()
    return out


def main(argv: list[str] | None = None) -> int:
    from takes import BUILDUPS
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("id", nargs="?", help="a build-up of takes.BUILDUPS")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--review", action="store_true", help="only the review sheets (fast)")
    ap.add_argument("--step", type=int, help=argparse.SUPPRESS)
    ap.add_argument("-j", "--jobs", type=int, default=2)
    args = ap.parse_args(argv)
    if args.list or not args.id:
        for bid, b in BUILDUPS.items():
            print(f"{bid:20} {b['page']}  ({len(page_steps(b['page']))} steps)")
        return 0
    if args.id not in BUILDUPS:
        ap.error(f"no build-up {args.id!r}; --list shows them")
    if args.step:
        try:
            r = render_step(args.id, args.step, review_only=args.review)
        except Exception as e:  # noqa: BLE001 — reported to the parent as data
            r = {"ok": False, "step": args.step, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(r), flush=True)
        return 0 if r.get("ok") else 1
    if not args.review and rg.find_ffmpeg() is None:
        ap.error("no ffmpeg: install it (brew install ffmpeg) or pip install imageio-ffmpeg")
    steps = page_steps(BUILDUPS[args.id]["page"])
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = list(pool.map(lambda s: _child(args.id, s[0], args.review), steps))
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        if r.get("ok"):
            print(f"ok      passo {r['step']:2}  {r['seconds']:4.1f} s  {r['title']}")
        else:
            print(f"FAILED  passo {r['step']:2}: {r.get('error')}")
    if failed or args.review:
        return 1 if failed else 0
    out = join([Path(r["out"]) for r in results], OUT / f"{args.id}.mp4")
    total = sum(r["seconds"] for r in results)
    print(f"{out}: {len(results)} steps, {total:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
