#!/usr/bin/env python3
"""Thumbnails for the Guia's look catalogs, rendered from each card's own code.

Visual, SpatialFx, Post and Backgrounds cards get a picture of what they do.
Pictures are never drawn by hand: this script runs the card's snippet in a
fixed scene (headless frames, ``tests/system_support.SystemWorld``) and saves

  docs/assets/thumbs/<id>.webp        static poster, 480×300
  docs/assets/thumbs/<id>.anim.webp   2 s loop, 480×300 (only cards that move)
  docs/assets/thumbs/manifest.json    input hash per card (staleness)
  docs/assets/thumbs/guia-api-thumbs.js   window.ScenaGuideThumbs, read by each
                                          language's Guide page

Staleness hashes the *inputs* (snippet, scene preset, render settings, the
card's parameter defaults, the source of the class it names), never pixels:
GPU / platform jitter does not churn the repo, and an edited look is flagged.

  python tools/guide/make_guia_thumbs.py                    # render missing / stale cards
  python tools/guide/make_guia_thumbs.py --family visual    # one catalog
  python tools/guide/make_guia_thumbs.py --id visual-neon   # one card (repeatable)
  python tools/guide/make_guia_thumbs.py --force            # re-render what the filter picks
  python tools/guide/make_guia_thumbs.py --check            # list stale / missing, exit 1 if any

Card knobs in guia-api-catalogs.js (both optional):
  thumb: "…"          the snippet to render (default: the first statement of
                      ``code:`` that names the card, plus the lines before it).
                      Scene names: x, y (center), W, H (design size), plus
                      the actors the snippet names (c, ship, beam, sprite, …)
  anim: true|false    loop or still. Default: a loop when the card moves over
                      2 s (measured); true fails if it does not move

The animated loop needs Pillow (``pip install -e .[docs]``); static posters
only need skia. A card that renders nothing visible fails (blank guard): the
script doubles as a render probe for every look in the catalogs.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # tools/guide (this script)
REPO = ROOT.parent.parent
# Shared by every language's Guide. Manifest paths ("thumbs/<id>.webp") are
# relative to ASSETS; the page data adds PAGE_TO_ASSETS, because each Guide
# page is docs/<lang>/guide/index.html.
ASSETS = REPO / "docs" / "assets"
THUMBS = ASSETS / "thumbs"
MANIFEST = THUMBS / "manifest.json"
THUMBS_JS = THUMBS / "guia-api-thumbs.js"
PAGE_TO_ASSETS = "../../assets/"

sys.path.insert(0, str(ROOT))
import validate_guia as vg  # noqa: E402

FAMILIES = vg.THUMB_FAMILIES

# ── Render settings (any change here invalidates every thumbnail) ──────────
RENDER_VERSION = 5
OUT = (480, 300)               # poster and loop size, px (2× the 240 px panel slot)
FPS = 12                       # loop frame rate
LOOP_SECONDS = 2.0
LEAD_SECONDS = 0.5             # scene settles before the snippet runs
POSTER_AT = 0.5                # seconds into the recording (hit cards: their peak frame)
STATIC_QUALITY = 82
ANIM_QUALITY = 70
BLANK_MIN_DIFF = 8             # max channel diff vs the bare scene, 0–255
MOTION_MIN_DIFF = 8            # a loop is kept when the card changes this much over 2 s
BG = "#12141a"                 # the Guia's --bg-code: the picture merges into the panel
HERO_COLOR = "deep sky blue"   # vivid, like the smoke scripts' palette
HERO_LINE = 2.0                # the smoke scripts' line_width range is 1.5–2.5
HERO_OUTLINE_DARKER = 0.35     # outline = fill.darker(…): the edge reads apart from the body
MEDIA = REPO / "examples" / "media"
SPRITE_FIXTURE = MEDIA / "space" / "playerShip1_red.png"
POST_WALLPAPER = MEDIA / "images" / "bg1.jpeg"   # a real picture: post FX act on detail, light, color
DETAIL_KEEP = 0.6              # "detail" reduction: mean pushed this far toward the block max

# Scene presets: design size (16:10), framebuffer, reduction to OUT, version
# (bump "v" when actors change).
# - Looks / transients sit on a shape of the size authors use (smoke scripts:
#   radius 7–26 in a 1200×800 design), zoomed: glow sigma, rim and stroke
#   widths are design units, so a big hero would make every look a thin line.
# - Post and backgrounds are screens: a 1000×625 design (a normal window)
#   drawn at 1440×900 and reduced 3:1. Post FX and fields run at ½–¼ of the
#   framebuffer, so a thumbnail-sized framebuffer is blocky.
# - "area" averages each block; "detail" also keeps small lights (stars,
#   debris, rain streaks), which an average turns into nothing; "max" keeps
#   the brightest pixel of each block.
SCENES = {
    "shape": {"design": (128, 80), "render": (960, 600), "reduce": "area", "v": 5},
    "sprite": {"design": (128, 80), "render": (960, 600), "reduce": "area", "v": 5},
    # One-shot verbs fire mid-loop and are captured at 30 fps: a 0.12 s flash
    # falls between two 12 fps frames.
    "transient": {"design": (128, 80), "render": (960, 600), "reduce": "area", "v": 5,
                  "fps": 30, "fire_at": 0.25},
    # SpatialFx: framed on what the effect draws (_measure_spatial); a tall
    # drawing (flames, jets) gets the portrait preset instead of being cropped.
    "spatial": {"design": (320, 200), "render": (960, 600), "reduce": "detail", "v": 7},
    "spatial_tall": {"design": (200, 320), "render": (600, 960), "reduce": "detail", "v": 1,
                     "out": (300, 480), "card": (150, 240)},
    # Post loops distort a photo: every pixel changes every frame. Smaller, softer.
    "post": {"design": (1000, 625), "render": (1440, 900), "reduce": "area", "v": 5,
             "loop": (320, 200), "loop_quality": 60, "card": (360, 225)},
    "impact": {"design": (1000, 625), "render": (1440, 900), "reduce": "area", "v": 2,
               "loop": (320, 200), "loop_quality": 60, "card": (360, 225),
               "fps": 30, "fire_at": 0.25},
    # Fields: each pixel keeps its block's brightest value, as a star looks on
    # screen at 100%; an average turns a star field into a flat dark plate.
    "field": {"design": (1000, 625), "render": (1440, 900), "reduce": "max", "v": 8,
              "card": (360, 225), "card_lift": True},
}
CARD = (320, 200)              # gallery picture (a ~160 px card at 2×), reduced from the render
CARD_LIFT_TARGET = 225         # "card_lift": the brightest detail (99.7th pct) is raised to this…
CARD_LIFT_MAX = 2.5            # …by at most this gain. Gallery only: the panel poster stays true.

# Transient families (catalog "Transientes"): one shape, the verb fired mid-loop.
TRANSIENT_FAMILIES = ("life", "hit", "pulse", "pop", "knock", "spark", "exit", "enter")

# --cpu: raster only (no display, CI). Default: GPU through a hidden window.
CPU_ONLY = False

# Shape scene: which actor a free name in the snippet gets (default: hero).
NAME_ACTORS = {"beam": "line", "pool": "slab",
               "sprite": "sprite", "player": "sprite"}


# ── Card → snippet / scene / hash ─────────────────────────────────────────

def in_scope(item: dict) -> bool:
    """A card gets a picture unless it opts out (``thumb: false``: nothing to see)."""
    return item.get("family") in FAMILIES and item.get("thumb") is not False


def scene_for(item: dict) -> str:
    fam = item["family"]
    if fam == "visual":
        return "sprite" if item.get("kind") == "sprite" else "shape"
    if fam in TRANSIENT_FAMILIES:
        return "transient"
    return {"spatial": "spatial", "post": "post", "impact": "impact", "field": "field"}[fam]


def poster_rule(item: dict) -> str:
    """Which recorded frame is the still: "at" (POSTER_AT), "peak" or "mid".

    An impact (``canvas.flash``, ``*_at``) is a moment (its peak). A transient ("event") is its peak when
    the peak shows something (flash, pop, ring) and the middle of its action
    when the shape is gone at the peak (blink off, burn / dissolve / fade):
    peak alone picks "no shape at all" for every in / out transition.
    """
    if scene_for(item) == "transient":
        return "event"
    return "peak" if item["family"] == "impact" else "at"


def _mentions(node: ast.AST, name: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == name:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == name:
            return True
    return False


def default_snippet(code: str, name: str) -> str:
    """First statement of ``code`` that names the card, plus every line before it."""
    src = vg._prepare(code)
    tree = ast.parse(src)
    short = name.split(".")[-1]
    lines = src.splitlines()
    for stmt in tree.body:
        if _mentions(stmt, short):
            return "\n".join(lines[: stmt.end_lineno]).strip()
    return lines[0].strip() if lines else ""


def thumb_code(item: dict) -> str:
    if isinstance(item.get("thumb"), str) and item["thumb"]:
        return vg._prepare(item["thumb"])
    return default_snippet(item["code"], item["name"])


# ── Style variants (``variants: "style"`` on a card) ─────────────────────────
# The options come from the code, never from the Guia's prose: the card's own
# call is made with a value nobody uses, and the friendly ValueError lists the
# real choices ("expected one of 'a', 'b'" / "Sky presets: a, b.").

PROBE = "__probe__"


def variant_params(item: dict) -> list[str]:
    return [v.strip() for v in str(item.get("variants") or "").split(",") if v.strip()]


def _card_call(code: str, name: str) -> ast.Call | None:
    short = name.split(".")[-1]
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == short) or \
                    (isinstance(f, ast.Attribute) and f.attr == short):
                return node
    return None


def _set_arg(call: ast.Call, item: dict, param: str, value: str) -> None:
    """Point ``param`` of the card's call at ``value`` (positional slot or keyword)."""
    pos = next((p.get("pos", 0) for p in item.get("params", []) if p["name"] == param), 0)
    if pos and len(call.args) >= pos:
        call.args[pos - 1] = ast.Constant(value)
        return
    call.keywords = [k for k in call.keywords if k.arg != param]
    call.keywords.append(ast.keyword(arg=param, value=ast.Constant(value)))


def _unparse(node: ast.AST) -> str:
    """``ast.unparse`` in the Guia's spelling (double-quoted strings)."""
    import re
    return re.sub(r"'([^'\"\\]*)'", r'"\1"', ast.unparse(node))


def variant_code(item: dict, param: str, value: str) -> str:
    """The card's snippet with ``param=value`` in the card's own call."""
    tree = ast.parse(thumb_code(item))
    call = _card_call(ast.unparse(tree), item["name"])
    target = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and ast.unparse(n) == ast.unparse(call))
    _set_arg(target, item, param, value)
    return _unparse(tree)


_CHOICES: dict = {}


def probe_choices(item: dict, param: str) -> list[str]:
    """The values ``param`` accepts, read from the engine's own error message."""
    key = (item["id"], param)
    if key in _CHOICES:
        return _CHOICES[key]
    call = _card_call(thumb_code(item), item["name"])
    if call is None:
        raise ValueError(f"{item['id']}: variants: no call of {item['name']} in the snippet")
    _set_arg(call, item, param, PROBE)
    scena = vg._scena()
    ns = {n: getattr(scena, n) for n in scena.__all__}
    ns.update(x=0.0, y=0.0)
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            eval(ast.unparse(call), ns)
    except ValueError as e:
        msg = str(e)
    else:
        raise ValueError(f"{item['id']}: {param}={PROBE!r} was accepted: no fixed choices")
    import re
    m = re.search(r"expected one of (.+?)\.(?:\s|$)", msg)
    if m:
        out = re.findall(r"'([^']+)'", m.group(1))
    else:
        m = re.search(r"presets: ([a-z_, ]+)\.", msg)
        out = [v.strip() for v in m.group(1).split(",")] if m else []
    if not out:
        raise ValueError(f"{item['id']}: cannot read the choices of {param}= from: {msg[:160]}")
    _CHOICES[key] = out
    return out


def ordered_choices(item: dict, param: str) -> list[str]:
    """The code's choices, in the Guia's order when the two lists agree (a sky
    reads dawn → night; the engine's message sorts them)."""
    code = probe_choices(item, param)
    row = next((p for p in item.get("params") or [] if p["name"] == param), None)
    listed = vg.guide_choices(row["meaning"]) if row else []
    return listed if sorted(listed) == sorted(code) else code


def _variant_label(v: dict) -> str:
    """The call a variant shows under the picture: ``Halo(style="pulse")``."""
    call = _card_call(v["thumb"], v["name"])
    return _unparse(call) if call is not None else v["thumb"]


def variant_items(item: dict) -> list[dict]:
    """One pseudo-card per choice: rendered like a card, shown inside its panel."""
    out = []
    for param in variant_params(item):
        for value in ordered_choices(item, param):
            out.append({**item, "id": f"{item['id']}~{param}-{value}", "thumb": variant_code(item, param, value),
                        "variants": None, "_parent": item["id"], "_param": param, "_value": value})
    return out


def _source_of(name: str) -> str:
    try:
        obj = vg.resolve_catalog_symbol(name)
        if obj is None:
            return ""
        return inspect.getsource(obj if inspect.isclass(obj) or inspect.isroutine(obj) else type(obj))
    except (OSError, TypeError):
        return ""


def entry_hash(item: dict, *, source: str | None = None) -> str:
    scene = scene_for(item)
    payload = {
        "render": [RENDER_VERSION, OUT, FPS, LOOP_SECONDS, LEAD_SECONDS, POSTER_AT,
                   STATIC_QUALITY, ANIM_QUALITY, MOTION_MIN_DIFF, BG, HERO_COLOR,
                   HERO_LINE, HERO_OUTLINE_DARKER, POST_WALLPAPER.name, CARD, CARD_LIFT_TARGET, CARD_LIFT_MAX,
                   MEASURE_FILL, FRAME_FILL, TALL_RATIO,
                   DETAIL_KEEP],
        "poster": poster_rule(item),
        "scene": [scene, SCENES[scene], SCENES["spatial_tall"] if scene == "spatial" else None],
        "code": thumb_code(item),
        "kind": item.get("kind"),
        "anim": item.get("anim"),                 # None = decided by measured motion
        "params": [[p["name"], p["def"]] for p in item.get("params", [])],
        "source": _source_of(item["name"]) if source is None else source,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def files_for(item: dict, anim: bool) -> dict:
    out = {"src": f"thumbs/{item['id']}.webp", "card": f"thumbs/{item['id']}.card.webp"}
    if anim:
        out["anim"] = f"thumbs/{item['id']}.anim.webp"
    return out


# ── Manifest / page data ──────────────────────────────────────────────────

def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_manifest(manifest: dict) -> None:
    THUMBS.mkdir(exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def write_thumbs_js(manifest: dict) -> None:
    """Page data: one entry per card; a card's style variants nest under it."""
    def entry(e):
        out = {"src": PAGE_TO_ASSETS + e["src"], "w": e["w"], "h": e["h"]}
        for k in ("anim", "card"):
            if e.get(k):
                out[k] = PAGE_TO_ASSETS + e[k]
        return out

    data = {iid: entry(e) for iid, e in sorted(manifest.items()) if not e.get("parent")}
    for iid, e in sorted(manifest.items(), key=lambda kv: (kv[1].get("order", 0), kv[0])):
        parent = e.get("parent")
        if parent and parent in data:
            data[parent].setdefault("variants", []).append(
                {**entry(e), "param": e["param"], "value": e["value"], "code": e["code"]})
    # Strict JSON after the "=": validate_guia.check_thumbs reads it back.
    THUMBS_JS.write_text(
        "/* Generated by make_guia_thumbs.py — do not edit. */\n"
        "window.ScenaGuideThumbs = " + json.dumps(data, indent=1, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def status(items: list[dict], manifest: dict) -> dict[str, str]:
    """id → "fresh" / "stale" / "missing"."""
    out = {}
    for it in items:
        e = manifest.get(it["id"])
        if e and e.get("shared"):          # a variant drawn by its card: the card's files
            want = {k: e[k] for k in ("src", "anim", "card") if e.get(k)}
        else:
            want = files_for(it, bool(e and e.get("anim")))
        if not e or any(e.get(k) != want.get(k) for k in ("src", "anim", "card")) \
                or not all((ASSETS / f).exists() for f in want.values()):
            out[it["id"]] = "missing"
        elif e.get("hash") != entry_hash(it):
            out[it["id"]] = "stale"
        else:
            out[it["id"]] = "fresh"
    return out


# ── Rendering (child process, one card) ───────────────────────────────────

def _scene(preset: str, ns: dict, names: set) -> None:
    """Build the fixed actors of a preset into ``ns`` (scena names live there too)."""
    st = ns
    W, H = SCENES[preset]["design"]
    cx, cy = W / 2, H / 2
    ns.update(x=cx, y=cy, W=W, H=H, dt=1 / 60)
    if preset in ("shape", "sprite", "transient"):
        cache = {}
        paint = dict(color=HERO_COLOR, line_width=HERO_LINE)
        outline = st["Color"](HERO_COLOR).darker(HERO_OUTLINE_DARKER)

        def actor(kind):
            if kind not in cache:
                if kind == "line":
                    cache[kind] = st["Line"](p1=(W * 0.12, cy), p2=(W * 0.88, cy),
                                             color=HERO_COLOR, line_width=2.5)
                elif kind == "bar":
                    cache[kind] = st["Rect"](center=(cx, cy), width=56, height=10, **paint)
                elif kind == "slab":
                    cache[kind] = st["Rect"](center=(cx, cy), width=96, height=48, **paint)
                elif kind == "sprite":
                    cache[kind] = st["Sprite"](str(SPRITE_FIXTURE), center=(cx, cy), height=56)
                else:
                    cache[kind] = st["Circle"](center=(cx, cy), radius=26, **paint)
                if kind in ("bar", "slab", "hero"):
                    cache[kind].line = outline          # the edge reads apart from the fill
            return cache[kind]

        hero = "sprite" if preset == "sprite" else "hero"
        for n in names:
            if n not in ns:
                ns[n] = actor(NAME_ACTORS.get(n, hero))
        if not cache:
            actor(hero)
    elif preset in ("post", "impact"):
        # A real picture and nothing else: post FX act on its detail, light, color.
        # (A shake or glitch of a flat color changes nothing at all.)
        import types
        st["canvas"].background = st["Wallpaper"](str(POST_WALLPAPER), fit="cover")
        ns["ship"] = st["Point"](cx, cy)
        ns["info"] = types.SimpleNamespace(point=(cx, cy))


def _apply(value, preset: str, kind: str, st: dict) -> None:
    """Install a bare constructor result (``Vignette()``, ``Stars()``)."""
    if value is None:
        return
    import scena
    from scena.postfx import PostEffect
    if isinstance(value, PostEffect):
        scena.canvas.effects.add(value)
        return
    field_base = getattr(sys.modules.get("scena.background"), "BackgroundField", None)
    if field_base is not None and isinstance(value, field_base):
        if kind == "base":
            scena.canvas.background = value
        else:
            scena.canvas.background.add(value)


MEASURE_FILL = 0.22            # measuring pass: the domain small, so flames / jets fit
FRAME_FILL = 0.88              # framed pass: the measured drawing fills this much
TALL_RATIO = 1.25              # a drawing this much taller than wide gets the portrait preset
MEASURE_THRESHOLD = int(os.environ.get("THUMB_MEASURE_T", 16))  # touched = differs this much (0–255)


def _domain_box(fx) -> tuple:
    """World AABB of a SpatialFx's drawing domain.

    Every kind has ``_domain_aabb`` (the engine's own: a directed fire is
    width × length, not ``radius``); the fallback reads the placement parts.
    """
    if hasattr(fx, "_domain_aabb"):
        return tuple(float(v) for v in fx._domain_aabb())
    if hasattr(fx, "p1") and hasattr(fx, "p2"):
        (x1, y1), (x2, y2) = (fx.p1.x, fx.p1.y), (fx.p2.x, fx.p2.y)
        pad = float(getattr(fx, "width", 0.0) or 0.0) * 0.5 if not hasattr(fx, "height") else 0.0
        return (min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad)
    r = float(fx.radius)
    return (fx.center.x - r, fx.center.y - r, fx.center.x + r, fx.center.y + r)


def _frame_spatial(before: set, scene: str, frame=None, fill: float = 0.5) -> None:
    """Point the camera at the SpatialFx the snippet made and zoom to fit it.

    ``frame`` is the world box the effect *draws* (measured by a first pass,
    _measured_box); without it, the placement domain. Snippets place effects
    in absolute design units and their sizes are absolute too, so framing is
    what shows a 28-unit Sparks or a tall blaze at a readable size.
    """
    import scena
    from scena import spatial_fx
    new = [fx for fx in spatial_fx._active_fx if id(fx) not in before]
    if not new:
        return
    x0, y0, x1, y1 = frame if frame else _domain_box(new[0])
    if frame:
        fill = FRAME_FILL
    W, H = SCENES[scene]["design"]
    bw, bh = max(float(x1 - x0), 1.0), max(float(y1 - y0), 1.0)
    zoom = max(0.2, min(4.0, min(W * fill / bw, H * fill / bh)))
    scena.canvas.pan_to(float(x0 + x1) / 2, float(y0 + y1) / 2)
    scena.canvas.zoom_to(zoom)
    _frame_spatial.view = ((float(x0 + x1) / 2, float(y0 + y1) / 2), zoom)


def _measured_box(frames, bare, spec, out_size) -> dict:
    """World box of every pixel the effect touched over the loop (measuring pass)."""
    import numpy as np
    W, H = SCENES[spec["scene"]]["design"]
    view = getattr(_frame_spatial, "view", None)
    if view is None:
        return {"ok": False, "error": "measure: no SpatialFx was made"}
    (cx, cy), zoom = view
    touched = np.zeros(bare.shape[:2], bool)
    for f in frames:
        touched |= np.abs(f.astype(np.int16) - bare).max(axis=2) >= MEASURE_THRESHOLD
    if not touched.any():
        return {"ok": False, "error": "measure: nothing drawn"}
    ys, xs = np.nonzero(touched)
    k = out_size[0] / W                                   # px per design unit at zoom 1
    to_world = lambda px, py: (cx + (px / k - W / 2) / zoom, cy + (H / 2 - py / k) / zoom)  # noqa: E731
    wx0, wy1 = to_world(xs.min(), ys.min())
    wx1, wy0 = to_world(xs.max() + 1, ys.max() + 1)
    return {"ok": True, "box": [wx0, wy0, wx1, wy1]}


def _run_snippet(code: str, ns: dict):
    """Run ``code`` statement by statement; return the last statement's value."""
    tree = ast.parse(code)
    last = None
    for stmt in tree.body:
        if isinstance(stmt, ast.Expr):
            last = eval(compile(ast.Expression(stmt.value), "<thumb>", "eval"), ns)
        else:
            exec(compile(ast.Module([stmt], []), "<thumb>", "exec"), ns)
            if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                last = ns.get(stmt.targets[0].id)
            else:
                last = None
    return last


def _downscale(px, size, mode: str = "area"):
    """Shrink an RGBA frame to ``size`` by averaging the pixels each one covers.

    ``"area"``: the mean (a 2 px star becomes a dim 1 px star; a cubic filter at
    2–3× samples only some source pixels, so small lights vanish). ``"detail"``:
    the mean pushed toward the brightest pixel of the block (DETAIL_KEEP), so
    stars, debris and rain streaks stay visible; smooth areas do not change.
    """
    import numpy as np
    h, w = px.shape[:2]
    ow, oh = size
    if (w, h) == (ow, oh):
        return px.copy()
    if w % ow or h % oh:
        raise ValueError(f"render size {w}×{h} is not a multiple of {ow}×{oh}")
    fx, fy = w // ow, h // oh
    blocks = px.reshape(oh, fy, ow, fx, 4).astype(np.float32)
    out = blocks.mean(axis=(1, 3))
    if mode == "detail":
        out = out + DETAIL_KEEP * (blocks.max(axis=(1, 3)) - out)
    elif mode == "max":
        out = blocks.max(axis=(1, 3))
    return out.round().clip(0, 255).astype(np.uint8)


def _lift(px):
    """Exposure for a dark gallery picture (Stars, Embers, Lattice).

    Ambient fields are dim on purpose; at 160 px in a dark page they read as
    black tiles. The gallery is an index for choosing, so the field's light
    *above the base color* is scaled until its brightest detail is readable.
    The base stays the base, and the panel poster stays true.
    """
    import numpy as np
    base = np.array(_hex_rgb(BG), np.float32)
    rgb = px[..., :3].astype(np.float32)
    above = np.clip(rgb - base, 0, None)
    top = float(np.percentile(above.max(axis=2), 99.7))
    gain = min(CARD_LIFT_MAX, (CARD_LIFT_TARGET - float(base.max())) / max(top, 1.0))
    if gain <= 1.0:
        return px
    out = px.copy()
    out[..., :3] = np.clip(base + (rgb - base) * gain, 0, 255).round().astype(np.uint8)
    return out


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _gpu_surface(fw, w: int, h: int):
    """A GPU render target behind a hidden GLFW window; ``None`` without a display.

    Same GL 3.2 Core context the engine opens in ``run()``. With it, every
    offscreen pass (post FX, SkSL fields, shape FX) takes the GPU path the
    author sees on screen; the raster fallback is the CPU path tests use.
    """
    try:
        import glfw
        import skia
        if not glfw.init():
            return None
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        win = glfw.create_window(64, 64, "thumb", None, None)
        if not win:
            return None
        glfw.make_context_current(win)
        ctx = skia.GrDirectContext.MakeGL()
        if ctx is None:
            return None
        info = skia.ImageInfo.Make(w, h, skia.kRGBA_8888_ColorType, skia.kPremul_AlphaType,
                                   skia.ColorSpace.MakeSRGB())
        surf = skia.Surface.MakeRenderTarget(ctx, skia.Budgeted.kYes, info)
        if surf is None:
            return None
        fw._context = ctx
        fw._thumb_window = win          # keep the window (and its context) alive
        return surf
    except Exception:
        return None


def render_one(spec: dict) -> dict:
    """Child-process body: render one card to ``spec['out']`` / ``spec['anim_out']``."""
    import random
    import numpy as np
    random.seed(0)
    np.random.seed(0)
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "tests"))
    import skia
    import scena
    from system_support import SystemWorld  # type: ignore

    world = SystemWorld(draw=True)
    # SystemWorld resets the design to the tests' size: set ours after it.
    preset = SCENES[spec["scene"]]
    W, H = preset["design"]
    RW, RH = preset["render"]
    out_size = preset.get("out", OUT)
    card_size = preset.get("card", CARD)
    fps = preset.get("fps", FPS)
    scena.init(width=W, height=H)
    fw = world.fw
    s = RW / W
    fw.pixel_ratio, fw.view_scale = s, 1.0
    fw._letterbox_pad_x = fw._letterbox_pad_y = 0
    fw.fb_width, fw.fb_height = RW, RH
    backend, surf = "cpu", None
    if spec.get("gpu", True):
        surf = _gpu_surface(fw, RW, RH)
        backend = "gpu" if surf is not None else "cpu"
    if surf is None:
        surf = skia.Surface(RW, RH)
    fw._drawing_surface, fw._drawing_canvas = surf, surf.getCanvas()
    fw._scena_draw.rebind(fw._drawing_canvas, pixel_ratio=s)
    world.surface = surf
    scena.canvas.background = BG

    cards = []

    def grab(keep_card=True):
        if backend == "gpu":
            surf.flushAndSubmit()
        big = np.asarray(surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType))
        if keep_card:     # the gallery picture comes from the full frame, not the poster
            cards.append(_downscale(big, card_size, preset["reduce"]))
        return _downscale(big, out_size, preset["reduce"])

    ns = {n: getattr(scena, n) for n in scena.__all__}
    code = spec["code"]
    names = set()
    for stmt in ast.parse(code).body:
        names |= vg._free_names(stmt)
    import builtins
    names = {n for n in names if n not in ns and not hasattr(builtins, n)}
    try:
        _scene(spec["scene"], ns, names)
        world.begin_game()
        world.seconds(LEAD_SECONDS)
        bare = grab(keep_card=False).astype(np.int16)
        from scena import spatial_fx
        spatial = spec["scene"] in ("spatial", "spatial_tall")

        def fire():
            before = {id(fx) for fx in spatial_fx._active_fx}
            value = _run_snippet(code, ns)
            _apply(value, spec["scene"], spec["kind"], ns)
            if spatial:
                _frame_spatial(before, spec["scene"], spec.get("frame"),
                               fill=MEASURE_FILL if spec.get("measure") else 0.5)

        frames = []
        step = max(1, round(60 / fps))
        # One-shot verbs fire mid-loop (the scene before, then the verb); the rest at 0.
        fire_at = int(round(preset.get("fire_at", 0.0) * fps))
        # Only recorded frames are drawn; post / one-shots draw every frame
        # (MotionTrail and the transient channels read every draw).
        draw_all = spec["scene"] in ("post", "impact", "transient")
        for i in range(int(round(LOOP_SECONDS * fps))):
            if i == fire_at:
                fire()
            if step > 1:
                world.step(step - 1, draw=draw_all)
            world.step(1)
            frames.append(grab(keep_card=not spec.get("measure")))
    except Exception as e:  # noqa: BLE001 — reported to the parent as data
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            world.teardown()
        except Exception:
            pass

    if spec.get("measure"):
        return _measured_box(frames, bare, spec, out_size)
    diff = max(int(np.abs(f.astype(np.int16) - bare).max()) for f in frames)
    if diff < BLANK_MIN_DIFF:
        return {"ok": False, "error": f"renders nothing visible (max diff {diff} vs the bare scene)"}
    first = frames[0].astype(np.int16)
    motion = max(int(np.abs(f.astype(np.int16) - first).max()) for f in frames[1:])
    # The loop is kept when the card moves (anim: false opts out; anim: true insists).
    if spec.get("anim") is True and motion < MOTION_MIN_DIFF:
        return {"ok": False, "error": f"anim: true, but nothing moves (max diff {motion} over the loop)"}
    loop = spec.get("anim") is not False and motion >= MOTION_MIN_DIFF
    rule = spec.get("poster", "at")
    if rule == "peak":
        poster = max(range(len(frames)), key=lambda i: float(np.abs(frames[i].astype(np.int16) - bare).sum()))
    elif rule == "event":
        # The peak, when the peak *shows* something (a flash, a pop, a ring);
        # when the shape is gone at the peak (blink off, an out-transition),
        # the middle of the action: from the frame the verb fired to the last
        # frame that still differs from how the loop ends.
        peak = max(range(len(frames)), key=lambda i: float(np.abs(frames[i].astype(np.int16) - bare).sum()))
        last = frames[-1].astype(np.int16)
        settled = [int(np.abs(f.astype(np.int16) - last).max()) < BLANK_MIN_DIFF for f in frames]
        end = max((i for i in range(fire_at, len(frames)) if not settled[i]), default=fire_at)
        middle = (fire_at + end + 1) // 2
        lum = lambda f: float(f[..., :3].astype(np.float32).mean())  # noqa: E731
        poster = peak if lum(frames[peak]) >= lum(bare.astype(np.uint8)) else middle
    else:
        poster = min(len(frames) - 1, int(round(POSTER_AT * fps)))
    card = cards[poster]
    if preset.get("card_lift") and spec.get("kind") != "base":   # a base's color is the content
        card = _lift(card)
    for array, path in ((frames[poster], spec["out"]), (card, spec["card_out"])):
        img = skia.Image.fromarray(array, colorType=skia.kRGBA_8888_ColorType)
        Path(path).write_bytes(bytes(img.encodeToData(skia.kWEBP, STATIC_QUALITY)))
    if loop:
        try:
            from PIL import Image
        except ImportError:
            return {"ok": False, "error": "animated thumbnail needs Pillow (pip install -e .[docs])"}
        pil = [Image.fromarray(f, "RGBA").convert("RGB") for f in frames]
        size = preset.get("loop", out_size)
        if size != out_size:
            pil = [im.resize(size, Image.BOX) for im in pil]
        pil[0].save(spec["anim_out"], "WEBP", save_all=True, append_images=pil[1:],
                    duration=int(round(1000 / fps)), loop=0,
                    quality=preset.get("loop_quality", ANIM_QUALITY), method=4)
    return {"ok": True, "diff": diff, "motion": motion, "anim": loop,
            "w": out_size[0], "h": out_size[1], "backend": backend}


def _render_in_child(item: dict) -> dict:
    files = files_for(item, True)
    spec = {
        "id": item["id"], "code": thumb_code(item), "scene": scene_for(item),
        "kind": item.get("kind"), "anim": item.get("anim"), "gpu": not CPU_ONLY,
        "poster": poster_rule(item),
        "out": str(ASSETS / files["src"]), "anim_out": str(ASSETS / files["anim"]),
        "card_out": str(ASSETS / files["card"]),
    }
    if spec["scene"] == "spatial":
        # Pass 1 measures what the effect draws; pass 2 frames it (tall → portrait).
        box = _child({**spec, "measure": True})
        if box.get("ok"):
            x0, y0, x1, y1 = box["box"]
            spec["frame"] = box["box"]
            if (y1 - y0) > TALL_RATIO * (x1 - x0):
                # Measure again in the portrait design: an effect placed by
                # default sits at *that* design's center.
                spec["scene"] = "spatial_tall"
                tall = _child({**spec, "measure": True, "frame": None})
                if tall.get("ok"):
                    spec["frame"] = tall["box"]
    return _child(spec)


def _child(spec: dict) -> dict:
    out = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--render-one", json.dumps(spec)],
        capture_output=True, encoding="utf-8", errors="replace", cwd=str(REPO), timeout=600,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"},
    )
    for line in reversed(out.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    tail = (out.stderr or out.stdout).strip().splitlines()[-3:]
    return {"ok": False, "error": "child failed: " + " | ".join(tail)}


# ── CLI ───────────────────────────────────────────────────────────────────

def select(bags: dict, families=None, ids=None, *, variants: bool = True) -> list[dict]:
    """Cards with a picture, each followed by its style variants."""
    items = []
    for bag in bags.values():
        for it in bag:
            if not in_scope(it):
                continue
            if families and it["family"] not in families:
                continue
            if ids and it["id"] not in ids:
                continue
            items.append(it)
            if variants:
                for n, v in enumerate(variant_items(it)):
                    items.append({**v, "_order": n})
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--family", action="append", choices=FAMILIES)
    ap.add_argument("--id", action="append", dest="ids")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--cpu", action="store_true", help="raster only (no GPU / display)")
    ap.add_argument("--render-one", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.render_one:
        print(json.dumps(render_one(json.loads(args.render_one))))
        return 0
    global CPU_ONLY
    CPU_ONLY = args.cpu

    bags = vg.load_catalogs()
    js_errors = vg.check_catalog_js(vg.CATALOGS, bags)
    if js_errors:
        print("guia-api-catalogs.js não é JS válido:", *js_errors, sep="\n  ")
        return 1
    every = select(bags)
    items = select(bags, args.family, args.ids)
    if args.ids:
        unknown = set(args.ids) - {it["id"] for it in every}
        if unknown:
            print("ids fora dos catálogos com prévia:", ", ".join(sorted(unknown)))
            return 1
    manifest = load_manifest()
    state = status(items, manifest)

    if args.check:
        bad = {k: v for k, v in state.items() if v != "fresh"}
        for iid, st in sorted(bad.items()):
            print(f"{st:8s} {iid}")
        print(f"{len(state) - len(bad)} em dia, {len(bad)} a gerar")
        return 1 if bad else 0

    # A variant whose snippet is its card's (the card's own default style) shares
    # the card's files: nothing to render, nothing to store twice.
    by_id = {it["id"]: it for it in items}
    same = {it["id"] for it in items if it.get("_parent") in by_id
            and it["thumb"] == thumb_code(by_id[it["_parent"]])}
    todo = [it for it in items if it["id"] not in same
            and (args.force or state[it["id"]] != "fresh")]
    THUMBS.mkdir(exist_ok=True)
    failed = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for it, res in zip(todo, pool.map(_render_in_child, todo)):
            if res.get("ok"):
                manifest[it["id"]] = {"hash": entry_hash(it), "w": res["w"], "h": res["h"],
                                      "scene": scene_for(it), **files_for(it, res["anim"])}
                if it.get("_parent"):
                    manifest[it["id"]].update(parent=it["_parent"], param=it["_param"],
                                              value=it["_value"], order=it["_order"],
                                              code=_variant_label(it))
                if not res["anim"]:
                    stale_anim = ASSETS / f"thumbs/{it['id']}.anim.webp"
                    if stale_anim.exists():
                        stale_anim.unlink()
                loop = "loop" if res["anim"] else "still"
                print(f"ok      {it['id']}  ({res['backend']}, {loop}; diff {res['diff']}, "
                      f"motion {res['motion']})")
            else:
                failed.append(it["id"])
                print(f"FALHOU  {it['id']}: {res.get('error')}")

    # Variants equal to their card point at the card's files.
    for vid in sorted(same):
        v = by_id[vid]
        card = manifest.get(v["_parent"])
        if card and not card.get("parent"):
            manifest[vid] = {"hash": entry_hash(v), "w": card["w"], "h": card["h"],
                             "scene": card["scene"], "src": card["src"], "card": card.get("card"),
                             "shared": True,
                             "parent": v["_parent"], "param": v["_param"], "value": v["_value"],
                             "order": v["_order"], "code": _variant_label(v)}
            if card.get("anim"):
                manifest[vid]["anim"] = card["anim"]

    # Cards that left the catalogs (or the thumbnail families) leave the manifest;
    # then every picture no entry points at is deleted (shared files stay).
    known = {it["id"] for it in every}
    for iid in sorted(set(manifest) - known):
        del manifest[iid]
        print(f"removido {iid}")
    used = {e.get(k) for e in manifest.values() for k in ("src", "anim", "card") if e.get(k)}
    for f in sorted(THUMBS.glob("*.webp")):
        if f"thumbs/{f.name}" not in used:
            f.unlink()

    save_manifest(manifest)
    write_thumbs_js(manifest)
    fresh = len(items) - len(todo)
    print(f"{len(todo) - len(failed)} gerada(s), {fresh} em dia, {len(failed)} falha(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
