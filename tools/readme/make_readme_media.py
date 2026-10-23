#!/usr/bin/env python3
"""Animated clips for README.md, rendered from the games themselves.

Each clip runs a real program headless (``tests/program_support.ProgramRun``:
the frame body a windowed run uses, input through the same GLFW handlers),
draws every frame on the GPU path the author sees on screen, and saves a
looping WebP. A *pilot* plays the game: it reads the program's own globals
each frame and holds keys / moves the mouse, so a clip shows play, not an
idle screen. Nothing is captured by hand: when a game or the engine's look
changes, the clips are rendered again.

  docs/assets/readme/<id>.webp     looping clip (README.md shows it)
  docs/assets/readme/manifest.json input hash per clip (staleness)

A clip's program is an example file (``examples/bolas.py``) or a README code
block: the block that follows ``<!-- clip: <id> -->`` in README.md runs as if
it were a file in ``examples/`` (its art resolves from ``examples/media``).
The README never shows code that is not the code of its picture. The level
editor's clip runs ``tools/readme/editor_ninja.py``: the editor as
``scena-editor`` starts it, with a level file open.

Staleness hashes the *inputs* (the program text, the clip spec, the pilot's
source, the render settings), never pixels: GPU jitter does not churn the repo.

  python tools/readme/make_readme_media.py            # render missing / stale clips
  python tools/readme/make_readme_media.py --id bolas # one clip (repeatable)
  python tools/readme/make_readme_media.py --force    # re-render what the filter picks
  python tools/readme/make_readme_media.py --check    # list stale / missing, exit 1 if any
  python tools/readme/make_readme_media.py --cpu      # raster only (no display)

Needs Pillow (``pip install -e .[docs]``).
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # tools/readme (this script)
REPO = ROOT.parent.parent
README = REPO / "README.md"
OUT_DIR = REPO / "docs" / "assets" / "readme"
MANIFEST = OUT_DIR / "manifest.json"

# ── Render settings (any change here invalidates every clip) ───────────────
RENDER_VERSION = 2
FPS = 30                       # clip frame rate (the game steps at 60)
QUALITY = 72                   # WebP quality of each frame
SUPERSAMPLE = 2                # render at 2× the clip size, then average 2×2 blocks
BLANK_MIN_DIFF = 8             # a clip must change by more than this (0–255) over its length

# One entry per clip. ``program``: an example file, or "README.md#<id>" (the
# block after the ``<!-- clip: <id> -->`` marker). ``size``: the clip, px (the
# program's design aspect). ``lead``: seconds played before recording starts.
# ``pilot``: a function below, ``(game, t)`` each frame.
CLIPS = {
    "catch-the-stars": {"program": "README.md#catch-the-stars", "size": (640, 480),
                        "seconds": 6.0, "lead": 1.5, "pilot": "follow_stars"},
    "naves_escudo": {"program": "examples/naves_4_escudo.py", "size": (600, 480),
                     "seconds": 8.0, "lead": 0.5, "pilot": "fly_fire_and_catch"},
    "bolas": {"program": "examples/bolas.py", "size": (600, 432),
              "seconds": 6.0, "lead": 1.0, "pilot": "watch"},
    "aviao_paisagem": {"program": "examples/aviao_paisagem.py", "size": (480, 270),
                       "seconds": 7.0, "lead": 3.0, "pilot": "fly_the_gaps"},
    "osciloscopio": {"program": "examples/osciloscopio.py", "size": (600, 432),
                     "seconds": 6.0, "lead": 0.3, "pilot": "click_the_ball"},
    "ninja_perigos": {"program": "examples/ninja_4_perigos.py", "size": (600, 450),
                      "seconds": 7.2, "lead": 1.0, "pilot": "run_jump_and_throw"},
    "ligue4": {"program": "examples/ligue4.py", "size": (500, 380),
               "seconds": 8.5, "lead": 0.0, "pilot": "play_connect_four"},
    "electric-hosts": {"program": "README.md#electric-hosts", "size": (720, 240),
                       "seconds": 3.0, "lead": 0.5, "pilot": "watch"},
    # Not an example: the editor as ``scena-editor`` starts it, with a level open.
    "scena-editor": {"program": "tools/readme/editor_ninja.py", "size": (800, 500),
                     "seconds": 6.0, "lead": 0.0, "pilot": "edit_a_level"},
}


# ── Pilots ─────────────────────────────────────────────────────────────────
# ``game`` is a ``Pilot``: ``game.ns`` (the program's globals), ``hold(*keys)``
# (exactly these keys down this frame), ``mouse(x, y)``, ``press()`` /
# ``release()``. Coordinates are design units, y up.

def watch(game, t):
    """No input: the scene plays by itself."""


def follow_stars(game, t):
    """The paddle goes under the lowest star."""
    paddle = game.ns["paddle"]
    stars = list(game.ns["group"]["stars"])
    if not stars:
        game.hold()
        return
    target = min(stars, key=lambda s: s.center.y).center.x
    dx = target - paddle.center.x
    game.hold("RIGHT" if dx > 12 else "LEFT" if dx < -12 else None)


def fly_fire_and_catch(game, t):
    """The ship fires all the time, sweeps under the fleet, and goes for a falling shield."""
    nave = game.ns["nave"]
    if not nave:
        game.hold()
        return
    poderes = list(game.ns["group"]["poderes"])
    if poderes:
        target = min(poderes, key=lambda p: p.center.y).center.x
    else:
        target = 500 + 300 * math.sin(t * 0.9)
    dx = target - nave.center.x
    game.hold("SPACE", "RIGHT" if dx > 15 else "LEFT" if dx < -15 else None)


def click_the_ball(game, t):
    """Click the ball to turn the oscilloscope on, then drag two sliders."""
    if t < 0.1:
        c = game.ns["bola"].center
        game.mouse(c.x, c.y)
        game.press()
    elif t < 0.2:
        game.release()
    else:
        game.drag_slider("tx1", 2, 5, start=2.2, end=2.8, now=t)
        game.drag_slider("ty1", 2, -3, start=4.2, end=4.8, now=t)


def fly_the_gaps(game, t):
    """Steer the plane toward the next gap between pillars (or the middle)."""
    aviao = game.ns["aviao"]
    portas = [p for p in game.ns["group"]["porta"] if p.center.x > aviao.center.x - 10]
    target = min(portas, key=lambda p: p.center.x).center.y if portas else 200
    dy = target - aviao.center.y
    keys = ["UP" if dy > 12 else "DOWN" if dy < -12 else None]
    if not game.ns["st"].voando and t % 1.0 < 0.05:
        keys.append("SPACE")
    game.hold(*keys)


def edit_a_level(game, t):
    """Zoom into the level, box-select three platforms, lift them, pick a star.

    Targets are world points of ``ninja_perigos.json``, put on screen through the
    editor's own camera (``view_point``) each frame.
    """
    from scena_editor.view import view_point

    def at(wx, wy):
        game.mouse(*view_point(wx, wy))

    if t < 1.0:
        at(1250, 260)
        if int(t * 60) % 6 == 0:
            game.run.scroll(0, 1)                  # wheel: zoom about the cursor
    elif t < 1.3:
        at(1425, 360)
    elif t < 1.9:                                  # drag on empty canvas: box select
        if t - 1.3 < 1 / 60:
            game.press()
        k = (t - 1.3) / 0.6
        at(1425 + 270 * k, 360 - 110 * k)
    elif t < 2.2:
        if t - 1.9 < 1 / 60:
            game.release()
        at(1560, 300)
    elif t < 3.4:                                  # lift the three together
        if t - 2.2 < 1 / 60:
            game.press()
        k = min(1.0, (t - 2.2) / 1.0)
        at(1560, 300 + 90 * k)
    elif t < 4.2:
        if t - 3.4 < 1 / 60:
            game.release()
        at(1100, 330)
    elif t < 4.3:                                  # a click selects one star
        if t - 4.2 < 1 / 60:
            game.press()
    elif t - 4.3 < 1 / 60:
        game.release()


def play_connect_four(game, t):
    """Red and blue take turns; red fills the bottom row from column 1 to 4 and wins.

    One move a second: grab the waiting ball, carry it over a column, let go.
    """
    columns = (3, 3, 4, 4, 2, 5, 1)
    move, k = int(t), t - int(t)
    if move >= len(columns):
        return
    ball = game.ns["proxima"]
    start = game.ns["INICIO"]
    above = game.ns["grade"].cell(columns[move], 0).center
    if k < 0.1:
        game.mouse(*start)
        if k < 1 / 60 and ball.visible:
            game.press()
    elif k < 0.45:
        q = (k - 0.1) / 0.35
        game.mouse(start[0] + (above.x - start[0]) * q, start[1] + (above.y - start[1]) * q)
    elif k - 0.45 < 1 / 60:
        game.release()


def run_jump_and_throw(game, t):
    """The ninja runs right through the start of Ninja IV: up onto the first
    platforms, over the water, throws at each robot ahead, waits for the
    electric barrier to switch off, and stops before the second pool. Jumps
    happen at fixed places of the level (``ninja_perigos.json``):
    ``(from x, to x, lowest y, highest y)`` of the feet."""
    jumps = ((230, 262, 70, 90), (440, 478, 240, 260))
    if t < 2.4 or not list(game.ns["group"]["heroi"]):   # overview, then the zoom
        game.hold()
        return
    hero = list(game.ns["group"]["heroi"])[0]
    x, y = hero.center.x, hero.center.y
    on_ground = "bottom" in hero.touching_sides
    if on_ground and any(0 < r.center.x - x < 420 and abs(r.center.y - y) < 60
                         for r in game.ns["group"]["robo"]):
        game.hold("SPACE")
        return
    if on_ground and any(0 < b.center.x - x < 110 and b.active
                         for b in game.ns["group"]["raio"]):
        game.hold()
        return
    if x > 1420:                                   # the second pool: the clip ends here
        game.hold()
        return
    jump = on_ground and any(x0 < x < x1 and y0 < y < y1 for x0, x1, y0, y1 in jumps)
    game.hold("RIGHT", "UP" if jump else None)


PILOTS = {f.__name__: f for f in (watch, follow_stars, fly_fire_and_catch, click_the_ball,
                                   fly_the_gaps, edit_a_level, play_connect_four,
                                   run_jump_and_throw)}


# ── README blocks ──────────────────────────────────────────────────────────

_MARKER = re.compile(r"<!--\s*clip:\s*([\w-]+)\s*-->\s*\n```python\n(.*?)\n```", re.S)


def readme_blocks(text: str | None = None) -> dict[str, str]:
    """``{id: code}`` for each ``<!-- clip: id -->`` + python block in README.md."""
    if text is None:
        text = README.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) + "\n" for m in _MARKER.finditer(text)}


def program_of(clip: dict) -> tuple[str, str | None]:
    """``(program path for ProgramRun, source or None)``.

    A README block runs as ``examples/readme_<id>.py`` (not a real file): its
    folder is ``examples/``, so its art resolves from ``examples/media``.
    """
    prog = clip["program"]
    if prog.startswith("README.md#"):
        cid = prog.split("#", 1)[1]
        blocks = readme_blocks()
        if cid not in blocks:
            raise KeyError(f"README.md has no '<!-- clip: {cid} -->' block")
        return f"examples/readme_{cid.replace('-', '_')}.py", blocks[cid]
    return prog, None


def program_text(clip: dict) -> str:
    path, source = program_of(clip)
    return source if source is not None else (REPO / path).read_text(encoding="utf-8")


# ── Staleness ──────────────────────────────────────────────────────────────

def entry_hash(cid: str, clip: dict | None = None, *, text: str | None = None) -> str:
    clip = CLIPS[cid] if clip is None else clip
    payload = {
        "render": [RENDER_VERSION, FPS, QUALITY, SUPERSAMPLE],
        "clip": {k: v for k, v in clip.items()},
        "pilot": [inspect.getsource(PILOTS[clip["pilot"]]), inspect.getsource(Pilot)],
        "program": program_text(clip) if text is None else text,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=1) + "\n",
                        encoding="utf-8", newline="\n")


def status(ids, manifest: dict) -> dict[str, str]:
    """``{id: "ok" | "stale" | "missing"}``."""
    out = {}
    for cid in ids:
        entry = manifest.get(cid)
        if entry is None or not (OUT_DIR / f"{cid}.webp").is_file():
            out[cid] = "missing"
        elif entry.get("hash") != entry_hash(cid):
            out[cid] = "stale"
        else:
            out[cid] = "ok"
    return out


# ── Rendering (child process) ──────────────────────────────────────────────

class Pilot:
    """What a pilot may do: hold keys, move / press the mouse (design units)."""

    def __init__(self, run):
        self.run = run
        self.ns = run.ns
        self._held: set[str] = set()
        self._at = (0.0, 0.0)

    def hold(self, *keys) -> None:
        want = {k for k in keys if k}
        for k in sorted(self._held - want):
            self.run.key_up(k)
        for k in sorted(want - self._held):
            self.run.key_down(k)
        self._held = want

    def mouse(self, x: float, y: float) -> None:
        self._at = (x, y)
        self.run.move(x, y)

    def press(self) -> None:
        self.run.press(*self._at)

    def release(self) -> None:
        self.run.release()

    def slider_point(self, label: str, value: float) -> tuple[float, float]:
        """Where the Slider labelled ``label`` shows ``value`` (design units)."""
        w = self.run.widget(label)
        k = (value - w.min_value) / (w.max_value - w.min_value)
        return w._slider_x + k * w._slider_length, w._slider_y

    def drag_slider(self, label: str, a: float, b: float, *, start: float, end: float,
                    now: float) -> None:
        """Drag a Slider's handle from value ``a`` to ``b`` between two times."""
        if now < start or now > end + 0.1:
            return
        if now > end:
            if now - end <= 1 / 60:
                self.release()
            return
        k = (now - start) / (end - start)
        x, y = self.slider_point(label, a + (b - a) * k)
        self.mouse(x, y)
        if now - start < 1 / 60:
            self.press()


def _gpu_surface(fw, w: int, h: int):
    sys.path.insert(0, str(REPO / "tools" / "guide"))
    from make_guia_thumbs import _gpu_surface as gpu  # the Guia's GL 3.2 target
    return gpu(fw, w, h)


def _pin_surface(fw, surf, pixel_ratio: float) -> None:
    sys.path.insert(0, str(REPO / "tools" / "guide"))
    from make_guia_thumbs import _pin_surface as pin  # survives the post → direct switch
    pin(fw, surf, pixel_ratio)


def _downscale(px, factor: int):
    import numpy as np
    h, w = px.shape[:2]
    blocks = px.reshape(h // factor, factor, w // factor, factor, 4).astype(np.float32)
    return blocks.mean(axis=(1, 3)).round().clip(0, 255).astype(np.uint8)


def render_one(spec: dict) -> dict:
    """Child-process body: play one clip and write ``spec['out']``."""
    import random
    import numpy as np
    random.seed(0)
    np.random.seed(0)
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tests"))
    import warnings
    warnings.simplefilter("ignore")
    import skia
    from program_support import ProgramRun  # type: ignore

    ow, oh = spec["size"]
    rw, rh = ow * SUPERSAMPLE, oh * SUPERSAMPLE
    run = ProgramRun(spec["path"], source=spec["source"], seed=0, draw=True)
    backend = "cpu"
    try:
        run.start()
        fw = run.world.fw
        dw, dh = fw.design_width, fw.design_height
        if abs(rw / dw - rh / dh) > 1e-6:
            raise ValueError(f"clip size {ow}×{oh} is not the design's aspect ({dw}×{dh})")
        s = rw / dw
        fw.pixel_ratio, fw.view_scale = s, 1.0
        fw._letterbox_pad_x = fw._letterbox_pad_y = 0
        fw.fb_width, fw.fb_height = rw, rh
        surf = _gpu_surface(fw, rw, rh) if spec.get("gpu", True) else None
        if surf is not None:
            backend = "gpu"
        else:
            surf = skia.Surface(rw, rh)
        _pin_surface(fw, surf, s)
        run.world.surface = surf

        pilot = Pilot(run)
        fly = PILOTS[spec["pilot"]]
        step = max(1, round(60 / FPS))
        lead = int(round(spec["lead"] * 60))
        total = lead + int(round(spec["seconds"] * FPS)) * step
        frames = []
        for i in range(total):
            fly(pilot, i / 60.0)
            run.step(1)
            if i >= lead and (i - lead) % step == step - 1:
                if backend == "gpu":
                    surf.flushAndSubmit()
                big = np.asarray(surf.makeImageSnapshot().toarray(
                    colorType=skia.kRGBA_8888_ColorType))
                frames.append(_downscale(big, SUPERSAMPLE))
    except Exception as e:  # noqa: BLE001 — reported to the parent as data
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            run.close(strict=False)
        except Exception:
            pass

    first = frames[0].astype(np.int16)
    motion = max(int(np.abs(f.astype(np.int16) - first).max()) for f in frames[1:])
    if motion < BLANK_MIN_DIFF:
        return {"ok": False, "error": f"nothing moves (max diff {motion} over the clip)"}
    from PIL import Image
    pil = [Image.fromarray(f, "RGBA").convert("RGB") for f in frames]
    pil[0].save(spec["out"], "WEBP", save_all=True, append_images=pil[1:],
                duration=int(round(1000 / FPS)), loop=0, quality=QUALITY, method=6)
    return {"ok": True, "frames": len(frames), "backend": backend,
            "bytes": os.path.getsize(spec["out"])}


def _child(spec: dict) -> dict:
    out = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--render-one", json.dumps(spec)],
        capture_output=True, encoding="utf-8", errors="replace", cwd=str(REPO), timeout=900,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
    )
    for line in reversed(out.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    tail = "\n".join((out.stderr or "").strip().splitlines()[-6:])
    return {"ok": False, "error": f"exit {out.returncode}: {tail}"}


def render(cid: str, *, gpu: bool = True) -> dict:
    clip = CLIPS[cid]
    path, source = program_of(clip)
    spec = {"id": cid, "path": path, "source": source, "size": list(clip["size"]),
            "seconds": clip["seconds"], "lead": clip["lead"], "pilot": clip["pilot"],
            "gpu": gpu, "out": str(OUT_DIR / f"{cid}.webp")}
    return _child(spec)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--id", action="append", help="one clip (repeatable)")
    ap.add_argument("--force", action="store_true", help="re-render even when up to date")
    ap.add_argument("--check", action="store_true", help="list stale / missing; exit 1 if any")
    ap.add_argument("--cpu", action="store_true", help="raster only (no GPU / display)")
    ap.add_argument("--render-one", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.render_one:
        print(json.dumps(render_one(json.loads(args.render_one))), flush=True)
        return 0

    ids = args.id or list(CLIPS)
    unknown = [i for i in ids if i not in CLIPS]
    if unknown:
        ap.error(f"unknown clip(s): {', '.join(unknown)}; known: {', '.join(CLIPS)}")
    manifest = load_manifest()
    states = status(ids, manifest)
    if args.check:
        bad = {i: s for i, s in states.items() if s != "ok"}
        for i, s in bad.items():
            print(f"{s:8} {i}")
        print(f"{len(ids) - len(bad)}/{len(ids)} clips up to date")
        return 1 if bad else 0

    todo = [i for i in ids if args.force or states[i] != "ok"]
    if not todo:
        print("all clips up to date")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = 0
    with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2) // 2))) as pool:
        results = dict(zip(todo, pool.map(lambda i: render(i, gpu=not args.cpu), todo)))
    for cid in todo:
        r = results[cid]
        if r.get("ok"):
            manifest[cid] = {"hash": entry_hash(cid), "file": f"{cid}.webp"}
            print(f"ok       {cid}  {r['frames']} frames, {r['bytes'] / 1024:.0f} KiB ({r['backend']})")
        else:
            failed += 1
            print(f"FAILED   {cid}: {r.get('error')}")
    save_manifest(manifest)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
