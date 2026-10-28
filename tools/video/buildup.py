#!/usr/bin/env python3
"""Build-up videos: a tutorial's steps one after another, code beside game.

A tutorial page (``docs/<lang>/tutorial/NN-*.html``) holds its steps as whole
programs (``tests/test_tutorials.extract_steps``, the reader the tutorial
tests use). A build-up video plays each step for a few seconds in the
"this code → this game" layout (``record_game.record(layout="code")``): the
step's code on the left, headed "Step N · <title>" ("Passo" on a Portuguese
page) and with the lines this
step adds or changes marked, and the step running on the right, played by
its own pilot so its new part shows (``BUILDUPS`` in ``takes.py``). Each step
is a clip of its own (a child process each); ffmpeg joins them without
re-encoding (same size, rate and codecs). A step opens with a moment to
read its caption and new lines (``reading_time``: the game runs, its
pilot waits). The last step plays on a few
seconds more (``FINALE``), the game played, its code complete. A step too
long to read at ``record_game.CODE_MIN_PT`` shows what it leaves alone
folded to ``…`` (``fit``).

A chapter build-up (``chapters`` in ``BUILDUPS``: a demo, not a tutorial)
is one run of a program; the panel shows the code of the part on screen
(``excerpt``: picked definitions, a slice of the storyboard, folds), and
the last chapter (the storyboard, as the demo loops) plays ``FINALE`` s.

  recordings/buildup/<id>.mp4            a chapter build-up
  recordings/buildup/<id>.srt            the captions, as subtitles

Captions (``say`` in ``BUILDUPS``): a line in big letters above the game
says what is going on (``record_game.caption_box``): per step (default
its title), with times when a step says more than one thing, the finale's
(default: the program's line count), per chapter. The same lines, with the
times they were on screen, are the ``.srt``: YouTube's subtitles and the
narration's script.

  recordings/buildup/<id>/step_NN.mp4    one clip per step
  recordings/buildup/<id>.mp4            the steps joined

  python tools/video/buildup.py --list
  python tools/video/buildup.py first_script            # every step, then joined
  python tools/video/buildup.py first_script --review   # one review sheet per step
  python tools/video/buildup.py old_school --review     # a chapter build-up's sheet
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
STEP_DEFAULTS = dict(pilot="watch", args={}, seconds=4.0, lead=0.0,
                     reader="watch", reader_args={})   # plays while the viewer reads
FINALE = 8.0            # the last step plays on this long once its code is complete
CAPTION_FADE = 0.3      # a caption fades in and out over this long
FINALE_SAY = "The finished program: {lines} lines"
# Before a step's pilot plays, the viewer reads: its caption and the lines it
# marks are on screen and the game runs with no input for READ_BASE s plus
# the longer of the caption (READ_WORDS words a second) and the marked lines
# (READ_LINE s each), at most READ_MAX (the build-ups ~40 % longer in all).
READ_BASE, READ_WORDS, READ_LINE, READ_MAX = 0.6, 3.5, 0.2, 3.0


def page_steps(page: str, example: str | None = None) -> list[tuple[int, str, str]]:
    """``(n, title, code)`` for each step of a tutorial page, from 1. The title
    is the page data's last ``title:`` before the step's code. A page that
    ends in two programs (``30-spins``: the bars, then the oscilloscope) gives
    ``example``'s steps only: after the step that ends the program before it,
    up to the one that ends ``example``."""
    from tests.test_tutorials import extract_steps, _read
    html = _read(str(REPO / page))
    lines = html.split("\n")
    steps = extract_steps(str(REPO / page))
    if example is not None:
        ends = [i for i, s in enumerate(steps) if s.example]
        last = next(i for i in ends if steps[i].example == example)
        first = max([i + 1 for i in ends if i < last], default=0)
        steps = steps[first:last + 1]
    out = []
    for n, step in enumerate(steps, start=1):
        titles = re.findall(r'title:\s*"([^"]*)"', "\n".join(lines[:step.line]))
        out.append((n, titles[-1] if titles else "", step.code))
    return out


def step_word(page: str) -> str:
    """"Step" on an English page, "Passo" on a Portuguese one."""
    return "Passo" if "/pt/" in page else "Step"


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


def panel_size() -> tuple:
    """The code panel of a video (``takes.DEFAULTS["size"]``): what folds are
    decided for, so a review sheet shows the folds the video will."""
    from takes import DEFAULTS
    w, h = DEFAULTS["size"]
    return round(w * rg.CODE_SHARE) // 2 * 2, h


def _header_end(node) -> int:
    """The last line (0-based) of a def's or class's header: its body starts
    on the next (a docstring counts as body)."""
    return node.body[0].lineno - 2


def _folds(code: str, marked) -> list:
    """What ``fit`` may fold in ``code`` without hiding a marked line: the
    body of a top-level def or class (to ``…``), then a run of top-level
    statements (not an import, ``init`` or ``run``). ``(first, last,
    replacement)`` each, 0-based lines, the bigger saving first."""
    import ast
    lines = code.splitlines()
    marked = set(marked)
    defs, runs, run = [], [], []

    def untouched(a, b):
        return not any(a <= k <= b for k in marked)

    def close_run():
        if run and run[-1][1] - run[0][0] >= 2 and untouched(run[0][0], run[-1][1]):
            runs.append((run[0][0], run[-1][1], ["…"]))
        run.clear()

    for node in ast.parse(code).body:
        first = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
        last = node.end_lineno - 1
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            close_run()
            body = _header_end(node) + 1
            if last - body >= 2 and untouched(first, last):
                indent = lines[body][:len(lines[body]) - len(lines[body].lstrip())]
                defs.append((body, last, [indent + "…"]))
            continue
        call = node.value if isinstance(node, ast.Expr) else None
        name = getattr(getattr(call, "func", None), "id", None)
        if isinstance(node, (ast.Import, ast.ImportFrom)) or name in ("init", "run"):
            close_run()
            continue
        if untouched(first, last):
            run.append((first, last))
        else:
            close_run()
    close_run()

    def saving(f):
        return f[1] - f[0] + 1 - len(f[2])
    return sorted(defs, key=saving, reverse=True) + sorted(runs, key=saving, reverse=True)


def _apply(lines: list, marked, folds) -> tuple:
    """``lines`` with ``folds`` replaced, and the marked lines' new numbers."""
    marked, out, keep = set(marked), [], []
    starts = {f[0]: f for f in folds}
    k = 0
    while k < len(lines):
        if k in starts:
            first, last, repl = starts[k]
            out += repl
            keep += [None] * len(repl)
            k = last + 1
            continue
        out.append(lines[k])
        keep.append(k)
        k += 1
    return "\n".join(out) + "\n", [i for i, k in enumerate(keep) if k in marked]


def fit(code: str, marked=(), title: str = "", size: tuple | None = None) -> tuple:
    """``(code, marked)`` as the panel shows them: whole when the font reads
    (``record_game.CODE_MIN_PT``), else with one blank line where there
    were two, then with what the step leaves alone folded to ``…``
    (``_folds``), one fold at a time, the biggest first, until it reads. A
    marked line is never folded."""
    size = size or panel_size()
    least = round(size[1] * rg.CODE_MIN_PT)
    lines, chosen = code.rstrip("\n").split("\n"), []
    blanks = [(k, k, []) for k in range(1, len(lines))
              if not lines[k].strip() and not lines[k - 1].strip()]
    shown, marks = _apply(lines, marked, chosen)
    for stage in [blanks] + [[fold] for fold in _folds(code, marked)]:
        if rg.code_fit(shown, size, title)[0] >= least:
            break
        chosen += stage
        shown, marks = _apply(lines, marked, chosen)
    return shown, marks


def _names(node) -> set:
    """The names a top-level statement is picked by (``excerpt``): a def's or
    class's name, the root name of what an assignment sets (``st`` for
    ``st.open = 0``), the root of the function a call names."""
    import ast
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        targets = [node.value.func]
    else:
        return set()
    out = set()
    for t in targets:
        while isinstance(t, (ast.Attribute, ast.Subscript, ast.Call)):
            t = t.func if isinstance(t, ast.Call) else t.value
        if isinstance(t, ast.Name):
            out.add(t.id)
    return out


def excerpt(source: str, picks, folds=()) -> str:
    """The parts of a program a chapter shows, in the order of ``picks``:
    a name picks the top-level statements ``_names`` gives it (a def with its
    decorators), each with the comment just above it (not a ``# ----``
    section line); ``(def, start, stop)`` picks a def's lines from the one
    holding ``start`` to the one before ``stop`` (``None``: its end), under
    its header, with ``…`` for the lines left out. ``folds``: defs
    (``"name"``, ``"Class.method"``) shown as their header and ``…``;
    ``"name.__doc__"`` leaves out a def's or class's docstring.
    Statements that touch in the file touch here, and so do one-line
    blocks (folded defs); others are a blank line apart."""
    import ast
    tree = ast.parse(source)
    lines = source.splitlines()
    cut = {}                     # header's last line -> (the last line left out, mark)
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        inner = [(f"{node.name}.{f.name}", f) for f in node.body
                 if isinstance(f, defs)] if isinstance(node, ast.ClassDef) else []
        for name, f in inner + ([(node.name, node)] if isinstance(node, defs) else []):
            if name in folds:
                cut[_header_end(f)] = (f.end_lineno - 1, " …")
            doc = f.body[0]
            if (f"{name}.__doc__" in folds and isinstance(doc, ast.Expr)
                    and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str)):
                end = doc.end_lineno - 1
                while end + 1 < len(lines) and not lines[end + 1].strip():
                    end += 1                  # and the blank line after it
                cut[_header_end(f)] = (end, "")

    def text(first, last):
        out, k = [], first
        while k <= last:
            skip, mark = cut.get(k, (k, ""))
            out.append(lines[k] + mark)
            k = skip + 1
        return out

    def lead(first):                          # the comment just above a statement
        while (first > 0 and lines[first - 1].strip().startswith("#")
               and not lines[first - 1].strip().startswith("# ----")):
            first -= 1
        return first

    blocks = []                               # (first line in the file, last, text)
    for pick in picks:
        if isinstance(pick, tuple):
            name, start, stop = pick
            node = next(n for n in tree.body if name in _names(n))
            body, end = _header_end(node) + 1, node.end_lineno - 1
            a = next(k for k in range(body, end + 1) if start in lines[k])
            b = (next(k for k in range(a + 1, end + 1) if stop in lines[k]) - 1
                 if stop else end)
            while not lines[b].strip():
                b -= 1
            line = lines[a]
            dots = line[:len(line) - len(line.lstrip())] + "…"
            shown = text(node.lineno - 1, body - 1) + ([dots] if a > body else [])
            shown += text(a, b) + ([dots] if b < end else [])
            blocks.append((node.lineno - 1, node.end_lineno - 1, shown))
            continue
        nodes = [n for n in tree.body if pick in _names(n)]
        if not nodes:
            raise ValueError(f"no top-level {pick!r}")
        for n in nodes:
            first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])]) - 1
            first = lead(first)
            blocks.append((first, n.end_lineno - 1, text(first, n.end_lineno - 1)))
    out = []
    for k, (first, last, shown) in enumerate(blocks):
        before = blocks[k - 1] if k else None
        if before and first != before[1] + 1 and not (len(shown) == len(before[2]) == 1):
            out.append("")
        out += shown
    return "\n".join(out) + "\n"


def step_spec(bid: str, n: int) -> dict:
    from takes import BUILDUPS
    spec = {**STEP_DEFAULTS, **BUILDUPS[bid]["steps"].get(n, {})}
    spec["args"] = dict(spec["args"])
    return spec


def step_pilot(bid: str, n: int) -> tuple:
    """How step ``n`` is played: ``(pilot, args, seconds, ends)``. Its
    ``reader`` (default: nobody) while the viewer reads, then its pilot, then
    on the last step the finale's; ``ends``: where the step's own part ends
    on the pilot's clock (the finale after it)."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    spec = step_spec(bid, n)
    read = step_read(bid, n)
    seconds = read + spec["seconds"]
    ends = spec["lead"] + seconds
    parts = [(0.0, spec["reader"], spec["reader_args"]), (read, spec["pilot"], spec["args"])]
    if n == len(page_steps(b["page"], b.get("example"))):
        fin = {"seconds": FINALE, **b.get("finale", {})}
        seconds += fin["seconds"]
        if fin.get("pilot"):
            parts.append((ends, fin["pilot"], fin.get("args", {})))
    return "chain", dict(parts=tuple(parts)), seconds, ends


def render_step(bid: str, n: int, *, review_only: bool = False, gpu: bool = True) -> dict:
    """Record step ``n`` of build-up ``bid`` (child-process body). The last
    step plays on ``FINALE`` s (``finale`` in ``BUILDUPS``: another pilot, or
    the step's own going on), its code then complete: no lines marked."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    steps = page_steps(b["page"], b.get("example"))
    _, title, code = steps[n - 1]
    before = steps[n - 2][2] if n > 1 else ""
    spec = step_spec(bid, n)
    heading = f"{step_word(b['page'])} {n} · {title}"
    shown, marks = fit(rg.program_code(code), new_lines(before, code), heading)
    pilot, args, seconds, ends = step_pilot(bid, n)
    say = timeline(*step_cues(bid, n))
    stem = f"step_{n:02d}"
    r, rep, sheet = _record(b["program"], bid, stem, review_only, gpu, pilot=pilot, args=args,
                            seconds=seconds, lead=spec["lead"], seed=n, source=code,
                            code_at=lambda game, t: (shown, heading, marks if t < ends else ()),
                            caption_at=lambda game, t: say(t - spec["lead"]),
                            label=f"step {n}: {title}")
    return {"ok": True, "step": n, "title": title, "out": r["out"], "sheet": str(sheet),
            "seconds": rep["seconds"], "ended": r["ended"], "captions": r["captions"],
            "length": r["length"]}


def cues(say, start: float = 0.0) -> list:
    """A caption spec as ``(time, text)`` cues from ``start``: a text says it
    from the start, ``((offset, text), ...)`` one after another."""
    if isinstance(say, str):
        return [(start, say)]
    return [(start + offset, text) for offset, text in say]


def timeline(cue_list, end: float | None):
    """``t -> (text, alpha)``: each cue until the next one starts (the last
    until ``end``; ``None``: no end known, it holds), fading in and out over
    ``CAPTION_FADE``."""
    def at(t):
        for k, (start, text) in enumerate(cue_list):
            stop = cue_list[k + 1][0] if k + 1 < len(cue_list) else end
            if start <= t and (stop is None or t < stop):
                fade = min(1.0, (t - start) / CAPTION_FADE)
                if stop is not None:
                    fade = min(fade, (stop - t) / CAPTION_FADE)
                return text, max(0.0, fade)
        return None
    return at


def reading_time(caption: str, marked: int) -> float:
    """Seconds to read a step's caption and its ``marked`` new lines before
    it plays (``READ_*``)."""
    return min(READ_MAX, READ_BASE + max(len(caption.split()) / READ_WORDS,
                                         READ_LINE * marked))


def step_read(bid: str, n: int) -> float:
    """Step ``n``'s reading time: its first caption, its marked lines."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    steps = page_steps(b["page"], b.get("example"))
    _, title, code = steps[n - 1]
    first = cues(b.get("say", {}).get(n, title))[0][1]
    return reading_time(first, len(new_lines(steps[n - 2][2] if n > 1 else "", code)))


def step_cues(bid: str, n: int) -> tuple:
    """Step ``n``'s captions, ``(cues, end)`` in its clip's seconds: its
    ``say`` (default: its title; the first from the start, a later one moved
    by the reading time, as the step's pilot is), then, on the last step,
    the finale's (the default counts the program's lines)."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    steps = page_steps(b["page"], b.get("example"))
    _, title, code = steps[n - 1]
    spec = step_spec(bid, n)
    say = b.get("say", {})
    read = step_read(bid, n)
    out = cues(say.get(n, title))
    out = out[:1] + [(t + read, text) for t, text in out[1:]]
    end = read + spec["seconds"]
    if n == len(steps):
        lines = sum(1 for line in rg.program_code(code).splitlines() if line.strip())
        fin = say.get("finale", FINALE_SAY)
        fin = fin.format(lines=lines) if isinstance(fin, str) else tuple(
            (offset, text.format(lines=lines)) for offset, text in fin)
        out += cues(fin, end)
        end += b.get("finale", {}).get("seconds", FINALE)
    return out, end


def srt(spans) -> str:
    """Subtitles (SubRip) from ``(start, end, text)`` spans, in seconds: the
    captions for YouTube, and the narration's script with its times."""
    def stamp(sec):
        ms = round(sec * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "".join(f"{k}\n{stamp(a)} --> {stamp(b)}\n{text}\n\n"
                   for k, (a, b, text) in enumerate(spans, start=1))


def _record(program, bid, stem, review_only, gpu, *, label, **kw):
    """One clip of a build-up: ``recordings/buildup/<bid>/<stem>.mp4`` (none
    with ``review_only``) and its review sheet."""
    from takes import DEFAULTS
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

    r = rg.record(program, factory, size=size, fps=fps, gpu=gpu, progress=False,
                  layout="code", **kw)
    r["out"] = None if review_only else str(out)
    r["length"] = r["frames"] / fps
    sheet = OUT / bid / f"{stem}.review.jpg"
    rep = reviews[0].report()
    reviews[0].save_sheet(sheet, f"{bid} {label}   {rep['seconds']:.1f} s")
    return r, rep, sheet


def chapter_panels(bid: str) -> list:
    """``(code, title, ())`` for each chapter of a chapter build-up."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    source = (REPO / b["program"]).read_text(encoding="utf-8")
    name = Path(b["program"]).name
    return [(excerpt(source, picks, folds), f"{name} · {title}", ())
            for title, picks, *rest in b["chapters"] for folds in [rest[0] if rest else ()]]


def render_chapters(bid: str, *, review_only: bool = False, gpu: bool = True) -> dict:
    """Record a chapter build-up: one run of the program, the panel showing
    the code of the chapter on screen. A chapter starts when ``key(game)``
    changes (``None``: not yet); the last one (the program's frame, while it
    loops) plays ``finale`` s, then the take ends. Captions: ``say[k]`` from
    chapter ``k``'s start (from 1; default its title), cut when the next
    chapter comes; the subtitles go to ``<bid>.srt``."""
    from takes import BUILDUPS
    b = BUILDUPS[bid]
    panels = chapter_panels(bid)
    finale = b.get("finale", FINALE)
    seen = dict(k=0, key=None, say=None)

    def chapter_say(k, start):
        last = k == len(panels) - 1
        text = b.get("say", {}).get(k + 1, b["chapters"][k][0].split("  ", 1)[-1])
        seen["say"] = timeline(cues(text, start), start + finale if last else None)

    def code_at(game, t):
        key = b["key"](game)
        if key is not None:
            if seen["key"] is not None and key != seen["key"] and seen["k"] < len(panels) - 1:
                seen["k"] += 1
                chapter_say(seen["k"], t)
                if seen["k"] == len(panels) - 1:
                    game.done = True
            seen["key"] = key
        return panels[seen["k"]]

    chapter_say(0, 0.0)
    r, rep, sheet = _record(b["program"], bid, "chapters", review_only, gpu,
                            pilot=b.get("pilot", "watch"), args=b.get("args", {}),
                            seconds=b["seconds"], tail=finale, code_at=code_at,
                            caption_at=lambda game, t: seen["say"](t), label="chapters")
    out = r["out"]
    if out is not None:
        out = str(Path(out).replace(OUT / f"{bid}.mp4"))
        (OUT / f"{bid}.srt").write_text(srt(r["captions"]), encoding="utf-8", newline="\n")
    return {"ok": True, "out": out, "sheet": str(sheet), "seconds": rep["seconds"],
            "ended": r["ended"], "chapters": seen["k"] + 1}


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
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8", newline="\n")
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
            if "chapters" in b:
                print(f"{bid:20} {b['program']}  ({len(b['chapters'])} chapters)")
            else:
                n = len(page_steps(b["page"], b.get("example")))
                print(f"{bid:20} {b['page']}  ({n} steps)")
        return 0
    if args.id not in BUILDUPS:
        ap.error(f"no build-up {args.id!r}; --list shows them")
    if "chapters" in BUILDUPS[args.id]:
        if not args.review and rg.find_ffmpeg() is None:
            ap.error("no ffmpeg: install it (brew install ffmpeg) or pip install imageio-ffmpeg")
        r = render_chapters(args.id, review_only=args.review)
        print(f"{r['out'] or r['sheet']}: {r['chapters']} chapters, {r['seconds']:.1f} s, "
              f"ended {r['ended']}")
        return 0 if r["ended"] == "done" else 1
    if args.step:
        try:
            r = render_step(args.id, args.step, review_only=args.review)
        except Exception as e:  # noqa: BLE001 — reported to the parent as data
            r = {"ok": False, "step": args.step, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(r), flush=True)
        return 0 if r.get("ok") else 1
    if not args.review and rg.find_ffmpeg() is None:
        ap.error("no ffmpeg: install it (brew install ffmpeg) or pip install imageio-ffmpeg")
    steps = page_steps(BUILDUPS[args.id]["page"], BUILDUPS[args.id].get("example"))
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = list(pool.map(lambda s: _child(args.id, s[0], args.review), steps))
    failed = [r for r in results if not r.get("ok")]
    for r in results:
        if r.get("ok"):
            print(f"ok      step {r['step']:2}  {r['seconds']:4.1f} s  {r['title']}")
        else:
            print(f"FAILED  step {r['step']:2}: {r.get('error')}")
    if failed or args.review:
        return 1 if failed else 0
    out = join([Path(r["out"]) for r in results], OUT / f"{args.id}.mp4")
    out.with_suffix(".srt").write_text(srt(joined_captions(results)), encoding="utf-8",
                                       newline="\n")
    total = sum(r["seconds"] for r in results)
    print(f"{out}: {len(results)} steps, {total:.1f} s (and {out.with_suffix('.srt').name})")
    return 0


def joined_captions(results) -> list:
    """The steps' caption spans on the joined video's clock: each clip's
    spans moved by the clips before it."""
    spans, offset = [], 0.0
    for r in results:
        spans += [(a + offset, b + offset, text) for a, b, text in r["captions"]]
        offset += r["length"]
    return spans


if __name__ == "__main__":
    sys.exit(main())
