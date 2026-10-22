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
    "aviao_paisagem": {"program": "examples/aviao_paisagem.py", "size": (480, 270),
                       "seconds": 7.0, "lead": 3.0, "pilot": "fly_the_gaps"},
    "corrida": {"program": "examples/corrida.py", "size": (640, 360),
                "seconds": 11.0, "lead": 0.0, "pilot": "pick_and_race"},
    "ninja_perigos": {"program": "examples/ninja_4_perigos.py", "size": (600, 450),
                      "seconds": 7.2, "lead": 1.0, "pilot": "run_jump_and_throw"},
    "ligue4": {"program": "examples/ligue4.py", "size": (500, 380),
               "seconds": 8.5, "lead": 0.0, "pilot": "play_connect_four"},
    "electric-hosts": {"program": "README.md#electric-hosts", "size": (720, 240),
                       "seconds": 3.0, "lead": 0.5, "pilot": "watch"},
    # Not an example: the editor as ``scena-editor`` starts it, with a level open.
    "scena-editor": {"program": "tools/readme/editor_ninja.py", "size": (800, 500),
                     "seconds": 6.0, "lead": 0.0, "pilot": "edit_a_level"},
    # A montage: one short take of each program, in order, each fitted into
    # ``size`` (letterboxed when its aspect differs) with its file name in a
    # corner.
    "mais_exemplos": {"size": (640, 360), "segments": [
        {"program": "examples/osciloscopio.py", "seconds": 3.3, "lead": 1.6,
         "pilot": "click_the_ball"},
        {"program": "examples/constelacao.py", "seconds": 2.5, "lead": 2.0,
         "pilot": "pull_the_stars"},
        {"program": "examples/duelo.py", "seconds": 2.5, "lead": 2.0, "pilot": "duel"},
        {"program": "examples/corredor.py", "seconds": 2.5, "lead": 1.0, "pilot": "jump_the_gaps"},
        {"program": "examples/app_rgb_arena.py", "seconds": 3.0, "lead": 1.0,
         "pilot": "three_reds_and_glow"},
        {"program": "examples/revoada.py", "seconds": 2.5, "lead": 3.0, "pilot": "falcon"},
        {"program": "examples/cadeia_de_bolas.py", "seconds": 2.5, "lead": 0.5,
         "pilot": "lead_the_chain"},
    ]},
}
CAPTION_FONT = "examples/media/fonts/Quantico-Bold.ttf"
LETTERBOX = (10, 11, 16)


# ── Pilots ─────────────────────────────────────────────────────────────────
# ``game`` is a ``Pilot``: ``game.ns`` (the program's globals), ``hold(*keys)``
# (exactly these keys down this frame), ``mouse(x, y)``, ``press()`` /
# ``release()``, ``click(at, now)``. Coordinates are design units, y up.
# ``game.cursor = True`` draws an arrow where the mouse is (a click on a menu
# reads better when the viewer sees the pointer).

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


def _at(now: float, when: float) -> bool:
    """``now`` is the one frame (60 Hz) that starts at ``when``."""
    return when <= now < when + 1 / 60


def _glide(game, a, b, *, start: float, end: float, now: float) -> None:
    """Move the mouse from ``a`` to ``b`` between two times (eased)."""
    k = min(1.0, max(0.0, (now - start) / (end - start)))
    k = k * k * (3 - 2 * k)
    game.mouse(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)


def _act():
    """The act on stage (an act keeps its actors as fields, not as globals)."""
    return sys.modules["scena.act"]._manager.current


def pick_and_race(game, t):
    """Click UM JOGADOR, then the Serpentina, with the pointer in view; then the
    blue car races, driven by the CPU's own brain (``Carro.pensar``) turned
    into keys: what it wants this frame is what the pilot holds."""
    one, serpentina = (640, 380), (340, 170)
    if t < 2.6:
        game.cursor = True
        if t < 1.3:
            _glide(game, (1000, 110), one, start=0.2, end=0.9, now=t)
        else:
            _glide(game, one, serpentina, start=1.3, end=2.0, now=t)
        if _at(t, 1.0) or _at(t, 2.2):
            game.press()
        if _at(t, 1.1) or _at(t, 2.3):
            game.release()
        return
    game.cursor = False
    azul = getattr(_act(), "azul", None)
    if azul is None or not game.ns["st"].largou:
        game.hold()
        return
    azul.pensar(1 / 60)
    game.hold("UP" if azul.acelera else None, "DOWN" if azul.freia else None,
              "LEFT" if azul.vira > 0.25 else "RIGHT" if azul.vira < -0.25 else None,
              "ENTER" if azul.quer_atirar else None)


def pull_the_stars(game, t):
    """Two more comets, then the mouse circles; held, it pulls the points;
    let go, a wave pushes them away."""
    game.mouse(640 + 260 * math.cos(t * 1.4), 400 + 200 * math.sin(t * 1.4))
    game.hold("SPACE" if _at(t, 0.3) or _at(t, 0.9) else None)
    if _at(t, 2.4):
        game.press()
    if _at(t, 3.6):
        game.release()


def duel(game, t):
    """Both players confirm their ship, then each one slides along its rail,
    turns toward the other ship (a little off, sweeping) and fires."""
    game.hold("TAB" if _at(t, 0.1) else "ENTER" if _at(t, 0.3) else None)
    act = _act()
    if not hasattr(act, "azul"):
        return
    heading = game.ns["heading"]
    keys = []
    for nave, outra, fase in ((act.azul, act.vermelha, 0.0), (act.vermelha, act.azul, 2.0)):
        if not nave.is_alive or not outra.is_alive:
            continue
        k = nave.teclas
        erro = (heading(nave, outra) + 25 * math.sin(t * 2.3 + fase) - nave.angle + 180) % 360 - 180
        keys.append(k["esquerda"] if erro > 6 else k["direita"] if erro < -6 else None)
        keys.append(k["cima"] if math.sin(t * 1.1 + fase) > 0 else k["baixo"])
        keys.append(k["tiro"])
    game.hold(*keys)


def jump_the_gaps(game, t):
    """The robot jumps when a hole or a crate is just ahead."""
    robo = getattr(_act(), "robo", None)
    if robo is None:
        return
    ns = game.ns
    x = robo.center.x
    ahead = x + 70
    hole = not ns["collision"].query_point((ahead, ns["altura"](ahead) - 8), group="chao")
    crate = any(0 < c.center.x - x < 120 for c in ns["group"]["caixa"])
    game.hold("UP" if (hole or crate) and "bottom" in robo.touching_sides else None)


def three_reds_and_glow(game, t):
    """Three more red particles (Criar), then the Visual slider goes to 7."""
    if t < 1.0:
        game.mouse(*game.run.widget_center("Criar"))
        for when in (0.2, 0.45, 0.7):
            if _at(t, when):
                game.press()
            if _at(t, when + 0.1):
                game.release()
        return
    game.cursor = t < 2.4
    game.drag_slider("Visual", 1.0, 7.0, start=1.3, end=2.2, now=t)


def falcon(game, t):
    """The falcon (the mouse) sweeps across the sky; once, a click in the flock."""
    group = game.ns["group"]
    if _at(t, 3.8):
        birds = list(group["passaro"])
        cx = sum(b.center.x for b in birds) / len(birds)
        cy = sum(b.center.y for b in birds) / len(birds)
        game.mouse(cx, cy)
        game.press()
        return
    if _at(t, 3.9):
        game.release()
    if t < 3.8 or t > 4.2:
        game.mouse(640 + 480 * math.sin(t * 0.9), 400 + 260 * math.sin(t * 1.7))


def lead_the_chain(game, t):
    """The mouse draws a figure eight; the chain follows."""
    game.mouse(500 + 330 * math.sin(t * 1.8), 360 + 190 * math.sin(t * 3.6))


PILOTS = {f.__name__: f for f in (watch, follow_stars, fly_fire_and_catch, click_the_ball,
                                   fly_the_gaps, edit_a_level, play_connect_four,
                                   run_jump_and_throw, pick_and_race, pull_the_stars, duel,
                                   jump_the_gaps, three_reds_and_glow, falcon,
                                   lead_the_chain)}
# Pilots that use the helpers above (``_at``, ``_glide``, ``_act``) or draw the
# pointer: the helpers' source is part of their clips' hash.
_HELPED = {"pick_and_race", "pull_the_stars", "duel", "jump_the_gaps", "three_reds_and_glow",
           "falcon", "lead_the_chain"}


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

def takes(clip: dict) -> list[dict]:
    """The programs a clip plays: itself, or each segment of a montage."""
    return clip.get("segments", [clip])


def entry_hash(cid: str, clip: dict | None = None, *, text: str | None = None) -> str:
    clip = CLIPS[cid] if clip is None else clip
    payload = {
        "render": [RENDER_VERSION, FPS, QUALITY, SUPERSAMPLE],
        "clip": {k: v for k, v in clip.items()},
        "pilot": [inspect.getsource(PILOTS[t["pilot"]]) for t in takes(clip)]
                 + [inspect.getsource(Pilot)],
        "program": text if text is not None else program_text(clip) if "segments" not in clip
                   else [program_text(t) for t in takes(clip)],
    }
    if "segments" in clip:   # a montage also hangs on how it is put together
        payload["montage"] = [inspect.getsource(f) for f in (compose, caption_layer)]
        payload["montage"].append([CAPTION_FONT, LETTERBOX])
    if any(t["pilot"] in _HELPED for t in takes(clip)):
        payload["helpers"] = [inspect.getsource(f) for f in (_at, _glide, _act, _cursor_on)]
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=1) + "\n",
                        encoding="utf-8")


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


def _cursor_on(frame, at):
    """Draw a mouse arrow with its tip at ``at`` (pixels) on an RGBA frame."""
    import numpy as np
    from PIL import Image, ImageDraw
    x, y = at
    arrow = [(0, 0), (0, 17), (4.5, 13), (7.5, 19.5), (10, 18.5), (7, 12), (12.5, 12)]
    img = Image.fromarray(frame, "RGBA")
    ImageDraw.Draw(img).polygon([(x + ax, y + ay) for ax, ay in arrow],
                                fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=1)
    return np.asarray(img)


def render_one(spec: dict) -> dict:
    """Child-process body: play one clip and write ``spec['out']``.

    ``fit``: ``size`` is a box and the clip is the largest size of the design's
    aspect inside it. An ``out`` ending in ``.npy`` gets the raw frames (a
    montage segment), anything else a looping WebP.
    """
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

    run = ProgramRun(spec["path"], source=spec["source"], seed=0, draw=True)
    backend = "cpu"
    try:
        run.start()
        fw = run.world.fw
        dw, dh = fw.design_width, fw.design_height
        ow, oh = spec["size"]
        if spec.get("fit"):
            k = min(ow / dw, oh / dh)
            ow, oh = min(ow, round(dw * k)), min(oh, round(dh * k))
        elif abs(ow / dw - oh / dh) > 1e-6:
            raise ValueError(f"clip size {ow}×{oh} is not the design's aspect ({dw}×{dh})")
        rw, rh = ow * SUPERSAMPLE, oh * SUPERSAMPLE
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
                frame = _downscale(big, SUPERSAMPLE)
                if getattr(pilot, "cursor", False):     # set by the pilot, frame by frame
                    mx, my = pilot._at
                    frame = _cursor_on(frame, (mx * ow / dw, (dh - my) * oh / dh))
                frames.append(frame)
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
    if spec["out"].endswith(".npy"):
        np.save(spec["out"], np.stack([f[..., :3] for f in frames]))
        return {"ok": True, "frames": len(frames), "backend": backend}
    from PIL import Image
    _save_webp([Image.fromarray(f, "RGBA").convert("RGB") for f in frames], spec["out"])
    return {"ok": True, "frames": len(frames), "backend": backend,
            "bytes": os.path.getsize(spec["out"])}


def _save_webp(images, out: str) -> None:
    images[0].save(out, "WEBP", save_all=True, append_images=images[1:],
                   duration=int(round(1000 / FPS)), loop=0, quality=QUALITY, method=6)


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


def caption_layer(size: tuple[int, int], text: str):
    """An RGBA layer with ``text`` in a dark pill at the bottom left."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(str(REPO / CAPTION_FONT), 15)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
    pad, margin = 6, 10
    box = (margin, size[1] - margin - (y1 - y0) - 2 * pad,
           margin + (x1 - x0) + 2 * pad, size[1] - margin)
    draw.rounded_rectangle(box, radius=6, fill=(0, 0, 0, 160))
    draw.text((box[0] + pad - x0, box[1] + pad - y0), text, font=font, fill=(255, 255, 255, 235))
    return layer


def compose(segments: list, size: tuple[int, int]) -> list:
    """Montage frames: each segment's ``(frames, caption)`` centred in a
    ``size`` box (letterboxed), its caption on top."""
    from PIL import Image
    images = []
    for frames, caption in segments:
        layer = caption_layer(size, caption)
        h, w = frames.shape[1:3]
        at = ((size[0] - w) // 2, (size[1] - h) // 2)
        for f in frames:
            img = Image.new("RGBA", size, LETTERBOX + (255,))
            img.paste(Image.fromarray(f, "RGB"), at)
            images.append(Image.alpha_composite(img, layer).convert("RGB"))
    return images


def render(cid: str, *, gpu: bool = True) -> dict:
    clip = CLIPS[cid]
    out = str(OUT_DIR / f"{cid}.webp")
    if "segments" not in clip:
        path, source = program_of(clip)
        return _child({"id": cid, "path": path, "source": source, "size": list(clip["size"]),
                       "seconds": clip["seconds"], "lead": clip["lead"],
                       "pilot": clip["pilot"], "gpu": gpu, "out": out})
    import tempfile
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        specs = []
        for i, seg in enumerate(clip["segments"]):
            path, source = program_of(seg)
            specs.append({"id": f"{cid}/{i}", "path": path, "source": source,
                          "size": list(clip["size"]), "fit": True, "seconds": seg["seconds"],
                          "lead": seg["lead"], "pilot": seg["pilot"], "gpu": gpu,
                          "out": os.path.join(tmp, f"{i}.npy")})
        with ThreadPoolExecutor(max(1, min(4, (os.cpu_count() or 2) // 2))) as pool:
            results = list(pool.map(_child, specs))
        for seg, r in zip(clip["segments"], results):
            if not r.get("ok"):
                return {"ok": False, "error": f"{seg['program']}: {r.get('error')}"}
        images = compose([(np.load(s["out"]), Path(seg["program"]).name)
                          for s, seg in zip(specs, clip["segments"])], tuple(clip["size"]))
    _save_webp(images, out)
    return {"ok": True, "frames": len(images), "backend": results[0]["backend"],
            "bytes": os.path.getsize(out)}


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
