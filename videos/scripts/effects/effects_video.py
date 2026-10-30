"""Scena: the effects (video 4, ~2:19). Visual richness, shown, not told.

Every effect is the API Guide's own catalogue card (its snippet, run as the
Guide's thumbnails run it: cards.json is frozen from
tools/guide/make_guia_thumbs.py), so what plays is what an author writes.
Each section says what it shows in a headline and a line under it (no
counts); names are small labels; the cuts fall on the music's beat (178 bpm).

  0:00  title                 100+ visual effects, built in; a ring of looks
  0:05  looks                 one star through eight looks, others come out from behind;
                              then every look at once, and on any shape (four swaps)
  0:27  in the world          the spatial effects fill a night landscape, then their
                              parameters move (the values shown live)
  0:40  backgrounds           a beat each, behind a ship; then four layered into one sky
  0:59  screen effects        over a photo with a ship (Kaleidoscope left out); then five
                              stacked on one picture
  1:17  impacts               in rhythm, over and over
  1:24  entrances and exits   a row of ships, each its verb, twice
  1:32  together              backgrounds, a portal, an orb, looks, rays, fireworks
  1:47  one line each         four rows of code grow from X() to X(a, b, c); the picture
                              follows each line (a background, a look, a grade, a vignette)
  2:14  100% made with Scena  (the music has ended; the card credits it)

Music: "Boss Battle Music" by Juhani Junkala (CC0): 99 bars, bars 79-87 played
twice (make_media.py -> boss_cut.wav).

Use
---
    python videos/scripts/effects/make_media.py
    python tools/video/record_game.py videos/scripts/effects/effects_video.py \\
        --pilot videos/scripts/effects/effects_video_pilots.py:pilot --seconds 139.1 \\
        --size 2560x1440 --crf 14 --out $PWD/videos/recordings/effects/scena_effects.mp4
    python videos/scripts/kit/finish.py videos/recordings/effects/scena_effects.mp4 promo/scena_effects

    TEASER_START=26.9 python videos/scripts/effects/effects_video.py     # start at a section (no music)
"""

import ast
import inspect
import json
import os
import sys
from math import sin, cos, pi
from types import SimpleNamespace

import scena
from scena import *

init(width=1280, height=720, title="Scena")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kit"))
from paths import REPO, work               # noqa: E402
from promo_kit import *                      # noqa: E402,F403
from promo_kit import kit                    # noqa: E402

MUSIC = os.path.join(work("effects"), "boss_cut.wav")
CUES = os.path.join(work("effects"), "cues.json")
START = float(os.environ.get("TEASER_START", "0"))
kit.setup(cues=CUES, start=START)
PHOTO = "images/bg1.jpeg"

canvas.background = NIGHT
light = Bloom(intensity=0.5)
Vignette(amount=0.5)

st.mode = None
my = SimpleNamespace(things=[], layers=[], tags=[])
W, H = 1280, 720

BEAT = 0.3367           # 178.2 bpm
FIRST = 0.244           # the first beat


def bar(n):
    """The time of bar n (four beats)."""
    return FIRST + 4 * BEAT * n


MUSIC_SECONDS = bar(99)     # 133.58 s: the track's end (a phrase repeated)


def now():
    """Seconds into the video (here: a formula follows only this file's functions)."""
    return clock.time - st.t0


# ---- the catalogue cards: snippets that make each effect ----

with open(os.path.join(HERE, "cards.json")) as f:
    CARDS = json.load(f)


def default_twin(card):
    """True for a bare `Name()` card when a style card repeats its default
    (Shield() is Shield(style="bubble"), Halo() is "hollow", Fire() is "camp")."""
    call = card["code"].strip().split("\n")[-1].split(".visual = ")[-1]
    if call != card["name"] + "()":
        return False
    try:
        default = inspect.signature(getattr(scena, card["name"])).parameters["style"].default
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    return any(c["name"] == card["name"] and f'style="{default}"' in c["code"] for c in CARDS)


def cards(*families, skip=(), most=None):
    """The cards of these families, each code once, no default twins; most:
    {name: n} keeps only the first n presets of a name."""
    seen, out, kept = set(), [], {}
    for card in CARDS:
        if card["family"] not in families or card["code"] in seen or default_twin(card) \
                or any(s in card["code"] for s in skip):
            continue
        if most and card["name"] in most:
            kept[card["name"]] = kept.get(card["name"], 0) + 1
            if kept[card["name"]] > most[card["name"]]:
                continue
        seen.add(card["code"])
        out.append(card)
    return out


def run_card(code, ns):
    """Run a card's snippet; return what its calls and assignments made (to undo it)."""
    made = []
    for stmt in ast.parse(code).body:
        if isinstance(stmt, ast.Expr):
            made.append(eval(compile(ast.Expression(stmt.value), "<card>", "eval"), ns))
        else:
            exec(compile(ast.Module(body=[stmt], type_ignores=[]), "<card>", "exec"), ns)
            for target in getattr(stmt, "targets", []):
                if isinstance(target, ast.Name):
                    made.append(ns[target.id])
    return [m for m in made if m is not None]


def undo(made):
    drop(made)
    canvas.set_fly(None)
    canvas.background = NIGHT


def drop(made):
    """Remove what a snippet made, and nothing else (undo also resets the sky)."""
    for thing in made:
        if thing is canvas:
            continue
        if hasattr(thing, "remove"):
            try:
                thing.remove()
                continue
            except Exception:
                pass
        if getattr(thing, "is_alive", False):
            thing.destroy()


def label_of(card):
    """A card's name as a label: "Shield · vortex" for a style."""
    name = card["name"].replace("canvas.", "")
    if "~" in card["id"]:
        name += " · " + card["id"].split("~")[1].split("-", 1)[1]
    return name


def name_tag(text, y=56, size=22, x=640):
    return Text(text, center=(x, y), font=MONO, font_size=size, color=FROST)


def small_tag(text, center, size=13, color=CAPTION):
    tag_ = Text(text, center=center, font=MONO, font_size=size, color=color)
    tag_.fade_in(0.2)
    return tag_


def section_head(text, sub=None, rule=True):
    return headline(text, y=676, size=30, sub=sub, rule=rule)


def scene_ns(**extra):
    ns = {n: getattr(scena, n) for n in scena.__all__}
    ns.update(W=W, H=H, **extra)
    return ns


# ---- the actors a look is put on ----

PALETTE = (Color("deep sky blue"), EMBER, Color("gold"), ICE, Color("orchid"),
           Color("lime green"), Color("tomato"), Color("light sky blue"))
SHIPS = ("space/playerShip1_red.png", "space/enemyBlue2.png", "space/enemyGreen1.png",
         "space/ufoYellow.png")
KINDS = ("star", "circle", "rect", "hexagon", "ellipse", "triangle", "sprite")
NO_SPRITE = {"Neon", "Bolt", "InsetRim", "Sphere", "Gel", "Water", "Liquify"}
HOSTS = {"c": "star", "beam": "line", "shot": "line", "orb": "circle", "candy": "circle",
         "ship": "sprite", "sprite": "sprite", "pool": "rect", "fx": "circle",
         "ember": "circle", "blob": "circle"}


def make_actor(kind, x, y, size, color, variant=0):
    if kind == "line":
        return Line(p1=(x - size * 1.3, y), p2=(x + size * 1.3, y), color=color, line_width=6)
    if kind == "sprite":
        return Sprite(SHIPS[variant % len(SHIPS)], height=size * 1.7, center=(x, y))
    if kind == "rect":
        return Rect(center=(x, y), width=size * 2, height=size * 1.4, corner_radius=8,
                    color=color)
    if kind == "circle":
        return Circle(center=(x, y), radius=size, color=color)
    if kind == "ellipse":
        return Ellipse(center=(x, y), width=size * 2.5, height=size * 1.3, color=color)
    if kind == "triangle":
        return RegularPolygon(n=3, center=(x, y - size * 0.2), radius=size * 1.25, color=color)
    if kind == "hexagon":
        return RegularPolygon(n=6, center=(x, y), radius=size * 1.05, color=color)
    return RegularPolygon(n=5, center=(x, y), radius=size * 1.1, color=color)


def look_target(card):
    """The name a look card's snippet puts the look on (c, orb, ship …)."""
    return card["code"].strip().split("\n")[-1].split(".visual")[0].strip()


def dress(card, actor, x, y):
    """Put a look card on an actor (its snippet, with the actor as its target)."""
    ns = scene_ns(**{look_target(card): actor})
    if "set_extrude_focus" in card["code"]:
        ns["W"], ns["H"] = (x + 40) / 0.95, (y + 60) / 0.95     # the focus by its tile
    try:
        run_card(card["code"], ns)
    except Exception as e:                  # a card that needs a scene of its own
        print(f"[effects] {card['id']}: {e}")


# ---- 0:00  title ----

RING = (lambda: Neon(ICE), lambda: Flame(), lambda: Shield(style="vortex"), lambda: Metal(),
        lambda: Halo(style="pulse"), lambda: ElectricField(), lambda: Gel("pink"),
        lambda: Aurora(), lambda: Shield(), lambda: GearShell(),
        lambda: Liquify(), lambda: OrganicOutline())


async def title(t):
    Stars(color=FROST, density=0.35, twinkle=0.5)
    row = arrive("SCENA", (640, 470), size=110)
    for letter in row:
        letter.fill = Gradient("white", FROST, ICE, angle=-90)
    ring = []
    for k, look in enumerate(RING):
        a = 2 * pi * k / len(RING) + pi / 2
        x, y = 640 + 560 * cos(a), 380 + 300 * sin(a)
        actor = make_actor(KINDS[k % 6], x, y, 30, PALETTE[k % 8])
        actor.visual = look()
        actor.visible = False
        after(0.3 + k * BEAT / 2, lambda a_=actor: (setattr(a_, "visible", True),
                                                   a_.pop(scale=1.5)))
        actor.rotate_by(360 if k % 2 else -360, time=14, loops="forever")
        ring.append(actor)
    await at(t + 1.4)
    words = [rise("100+ visual effects, built in", (640, 340), size=50, color="white")]
    canvas.zap_at(640, 470, color=ICE, radius=220, amount=0.8)
    await at(t + 2.3)
    words.append(note("each one a line of code, each one with its parameters", (640, 272),
                      size=26))
    await at(t + 4.9)
    leave(row, words, ring, time=0.4)


# ---- 0:05  looks: one star through eight, others come out from behind; then all ----

CYCLE = ("Neon", "ElectricField", "Flame", "Metal", "Aurora", "OrganicOutline", "GearShell", "Shield")
COMPANIONS = (      # (kind, look, its name, where it settles)
    ("circle", lambda: Shield(style="vortex"), "Shield · vortex", (250, 470)),
    ("sprite", lambda: Aura(), "Aura", (1030, 470)),
    ("rect", lambda: Water(), "Water", (330, 210)),
    ("hexagon", lambda: Halo(style="pulse"), "Halo · pulse", (950, 210)),
    ("ellipse", lambda: Gel("pink"), "Gel", (120, 330)),
    ("triangle", lambda: Liquify(), "Liquify", (1160, 330)),
    ("sprite", lambda: EmissiveBloom(), "EmissiveBloom", (640, 110)),
)
STAR = Vec2(640, 380)


async def looks(t):
    Stars(color=FROST, density=0.25, twinkle=0.3)
    words = section_head("Looks", sub="dress any shape or sprite, in one line")
    star = RegularPolygon(n=5, center=STAR, radius=120, color=Color("deep sky blue"))
    star.layer = "top"                      # the others come out from behind it
    star.rotate_by(360, time=12, loops="forever")
    star.fade_in(0.3)
    tag_, others = [], []
    for k, name in enumerate(CYCLE):
        await at(t + 0.4 + 3 * BEAT * k)
        star.visual = globals()[name]()
        leave(tag_, style="fade", time=0.1)
        tag_ = [name_tag(f"star.visual = {name}()", y=225, size=20)]
        star.pop(scale=1.06)
        if 1 <= k <= len(COMPANIONS):
            kind, look, label, (x, y) = COMPANIONS[k - 1]
            other = make_actor(kind, STAR.x, STAR.y, 46, PALETTE[k % 8], variant=k)
            other.visual = look()
            other.scale = 0.15
            other.scale_to(1.0, time=1.1, ease="ease_out")
            other.move_to(x, y, time=1.1, ease="ease_out")
            other.rotate_by(360 if k % 2 else -360, time=16, loops="forever")
            after(1.0, lambda x=x, y=y, label=label: others.append(
                small_tag(label, (x, y - 72))))
            others.append(other)
    await at(t + 0.4 + 3 * BEAT * len(CYCLE))
    leave(star, tag_, others, words, time=0.3)
    # the wall: every look and style, one tile a half beat
    words = section_head("Every look, every style", sub="on shapes, sprites and lines", rule=False)
    wall = cards("visual")
    cols = 8
    rows = (len(wall) + cols - 1) // cols
    tiles = []
    for k, card in enumerate(wall):
        await at(t + 8.8 + k * BEAT / 2)
        x = 80 + (k % cols) * 160
        y = 560 - (k // cols) * (500 / rows)
        kind = HOSTS.get(look_target(card), "star")
        if kind == "star":
            kind = KINDS[k % 6]
        color = Color("red") if card["name"] == "Laser" else PALETTE[k % len(PALETTE)]
        actor = make_actor(kind, x, y + 8, 26, color, variant=k)
        dress(card, actor, x, y + 8)
        actor.pop(scale=1.25)
        tiles.append(dict(card=card, x=x, y=y + 8, k=k, kind=kind, color=color, actor=actor,
                          label=Text(label_of(card), center=(x, y - 36), font=MONO,
                                     font_size=11, color=CAPTION)))
    # …and any shape: each look moves to another outline, four times
    await at(t + 16.5)
    leave(words, time=0.25)
    words = section_head("…on any shape", sub="the same look, on another outline", rule=False)
    for r in range(4):
        await at(t + 16.9 + r * 3 * BEAT)
        for tile in tiles:
            reshape(tile, r)
    await at(t + 21.0)
    leave([tile["actor"] for tile in tiles], [tile["label"] for tile in tiles], words,
          time=0.4)


def reshape(tile, r):
    """The tile's look on the next outline (a sprite look stays on sprites)."""
    card, k = tile["card"], tile["k"]
    if card["name"] == "Recolor":
        kinds = ("sprite",)
    else:
        kinds = tuple(n for n in KINDS if not (n == "sprite" and card["name"] in NO_SPRITE))
    kind = kinds[(k * 3 + r + 1) % len(kinds)]
    if kind == tile["kind"] and len(kinds) > 1:
        kind = kinds[(k * 3 + r + 2) % len(kinds)]
    old = tile["actor"]
    old.fade_out(0.12, on_done=old.destroy)
    actor = make_actor(kind, tile["x"], tile["y"], 26, tile["color"], variant=k + r + 1)
    dress(card, actor, tile["x"], tile["y"])
    actor.pop(scale=1.3)
    tile["actor"], tile["kind"] = actor, kind


# ---- 0:27  in the world: a night landscape fills up, then the parameters move ----

FIRES = ("camp", "soft", "plume", "tongues", "embers", "blaze")
JETS = ("plume", "tongues", "embers", "blaze")
# (label, code, label's place, value line's parameter, its range or steps, colours)
WORLD = (
    ("Sunburst", "Sunburst(center=(130, 585), radius=48)", (130, 515),
     "radius", (48, 80), ("gold", "orange red", "orchid")),
    ("Fire · camp", "Fire(center=(120, 175), radius=60, style=\"camp\")", (120, 95),
     "radius", (60, 92), None),
    ("Starburst", "Starburst(center=(320, 595), radius=40)", (320, 530),
     "points", (5, 6, 7, 8, 9), ("white", "cyan", "gold")),
    ("Fire · soft", "Fire(center=(290, 175), radius=60, style=\"soft\")", (290, 95),
     "radius", (60, 34), None),
    ("Jet", "Jet(p1=(30, 405), p2=(200, 405), width=18)", (115, 362),
     "width", (18, 44), ("deep sky blue", "orange", "lime green")),
    ("Fire · plume", "Fire(center=(460, 175), width=44, length=150, style=\"plume\")",
     (460, 95), "length", (150, 230), None),
    ("Sparks", "Sparks(center=(360, 450), radius=40, rate=50)", (360, 385),
     "rate", (50, 260), ("gold", "cyan", "magenta")),
    ("Fire · tongues", "Fire(center=(630, 175), width=44, length=150, style=\"tongues\")",
     (630, 95), "length", (150, 220), None),
    ("Warp", "Warp(center=(560, 460), radius=70)", (560, 368),
     "twist", (0.35, 1.4), None),
    ("Fire · embers", "Fire(center=(800, 175), width=44, length=150, style=\"embers\")",
     (800, 95), "width", (44, 90), None),
    ("Portal", "Portal(center=(790, 460), radius=60)", (790, 378),
     "speed", (1.0, 4.0), None),
    ("Fire · blaze", "Fire(center=(970, 175), width=44, length=150, style=\"blaze\")",
     (970, 95), "length", (150, 230), None),
    ("Orb", "Orb(center=(960, 590), radius=40)", (960, 528),
     "radius", (40, 66), ("deep sky blue", "orchid", "gold")),
    ("GlowSpot", 'GlowSpot(center=(1170, 215), radius=60, color="cyan")', (1170, 95),
     "radius", (60, 96), ("cyan", "magenta", "gold")),
    ("Rain", "Rain(p1=(1060, 400), p2=(1250, 640), amount=1.0)", (1155, 378),
     "amount", (1.0, 0.4), ("light sky blue", "white", "aquamarine")),
)
PORTAL_COLORS = ((ICE, EMBER), (Color("orchid"), Color("gold")), (Color("lime green"), ICE))
WARP_COLORS = ((None, None), (EMBER, Color("gold")), (Color("orchid"), ICE))


async def world(t):
    SkyGradient("night")
    Stars(color=FROST, density=0.3, twinkle=0.4)
    Ground(horizon=0.18)
    words = section_head("Effects in the world", sub="fire, portals, warps, rain… placed like shapes")
    placed = []
    for k, (label, code, where, param, span, colors) in enumerate(WORLD):
        await at(t + 0.4 + k * BEAT)
        fx = run_card(code, scene_ns())[0]
        placed.append((fx, label, where, param, span, colors))
        small_tag(label, where)
    # the parameters move: each effect, one of its parameters, its value under its name
    await at(t + 6.4)
    leave(words, time=0.25)
    words = section_head("…each with its parameters", sub="sizes, speeds, colours, shapes: live")
    for fx, label, (x, y), param, span, colors in placed:
        value = Text("", center=(x, y - 16), font=MONO, font_size=12, color=EMBER)
        if isinstance(span[0], float):
            value["text"] @= lambda fx=fx, p=param: f"{p}={getattr(fx, p):.2f}"
        else:
            value["text"] @= lambda fx=fx, p=param: f"{p}={round(getattr(fx, p))}"
        value.fade_in(0.3)
        if len(span) == 2:
            tween(fx[param], span[1], time=1.6, ease="ease_in_out", loops="forever", yoyo=True)
    for step in range(9):
        await at(t + 6.8 + step * 2 * BEAT)
        for fx, label, where, param, span, colors in placed:
            if len(span) > 2:
                setattr(fx, param, span[(step + 1) % len(span)])
            if colors:
                fx.color = colors[(step + 1) % len(colors)]
            elif label == "Portal":
                fx.color, fx.color2 = PORTAL_COLORS[(step + 1) % 3]
            elif label == "Warp" and step % 3 != 2:
                fx.color, fx.color2 = WARP_COLORS[(step + 1) % 3]
    await at(t + 12.9)
    leave(words, time=0.3)


# ---- 0:40  backgrounds: a beat each ----

def flyer():
    ship = Sprite("space/playerShip1_red.png", height=60)
    ship["center"] @= lambda: (640 + 260 * sin(now() * 1.3), 300 + 90 * sin(now() * 2.6))
    ship["angle"] @= lambda: 25 * cos(now() * 1.3)
    ship.tail = Tail(color=EMBER, size=4)
    ship.layer = "top"
    return ship


async def backgrounds(t):
    words = section_head("Backgrounds", sub="skies, dust, nebulae, lattices, fly-throughs")
    ship = flyer()
    shown, tag_ = [], []
    for k, card in enumerate(cards("field", most={"SkyGradient": 6})):
        await at(t + 0.4 + k * 1.1 * BEAT)
        undo(shown)
        shown = run_card(card["code"], scene_ns())
        leave(tag_, style="fade", time=0.08)
        tag_ = [name_tag(label_of(card))]
    await at(t + 12.9)
    undo(shown)
    leave(words, tag_, time=0.3)
    words = section_head("Backgrounds combine", sub="layer as many as you like, each one line")
    await compose(t + 13.3, BACKDROP)
    await at(t + 17.4)                  # the whole sky, held two seconds
    leave(words, my.tags, ship, time=0.3)
    await wait(0.3)
    undo(my.layers)


BACKDROP = (        # one sky, a layer two beats apart
    ("SkyGradient", lambda: SkyGradient("dusk")),
    ("Stars", lambda: Stars(color=FROST, density=0.6, twinkle=0.5)),
    ("Nebula", lambda: Nebula("orchid", color2="midnight blue", alpha=0.45)),
    ("Borealis", lambda: Borealis(ICE, alpha=0.7)),
)
LENSES = (          # one picture through five screen effects
    ("Grade", lambda: Grade("cool")),
    ("Bloom", lambda: Bloom(1.0)),
    ("Chroma", lambda: Chroma(3)),
    ("Scanlines", lambda: Scanlines(0.6)),
    ("Vignette", lambda: Vignette(1.2)),
)


async def compose(t, layers):
    """Add the layers two beats apart; the tag grows: "A + B + C"."""
    my.layers, my.tags = [], []
    for k, (name, make) in enumerate(layers):
        await at(t + k * 2 * BEAT)
        my.layers.append(make())
        for tag_ in my.tags:
            tag_.destroy()
        my.tags = [name_tag(" + ".join(n for n, _ in layers[:k + 1]))]


# ---- 0:59  screen effects: over a photo and a ship ----

async def screen(t):
    Wallpaper(PHOTO)
    words = section_head("Screen effects", sub="over the whole picture: colour, blur, light, lenses")
    ship = flyer()
    shown, tag_ = [], []
    posts = cards("post", skip=("Kaleidoscope",), most={"Grade": 4, "Haze": 2})
    for k, card in enumerate(posts):
        await at(t + 0.4 + k * 1.15 * BEAT)
        undo(shown)
        Wallpaper(PHOTO)
        shown = run_card(card["code"], scene_ns())
        leave(tag_, style="fade", time=0.08)
        tag_ = [name_tag(label_of(card))]
    await at(t + 11.4)
    undo(shown)
    leave(words, tag_, time=0.3)
    Wallpaper(PHOTO)
    words = section_head("Screen effects combine", sub="stack them: each one line, each over the last")
    await compose(t + 11.8, LENSES)
    await at(t + 16.5)                  # all five, held two seconds
    leave(words, my.tags, ship, time=0.3)
    await wait(0.3)
    undo(my.layers)


# ---- 1:17  impacts: in rhythm, over and over ----

async def impacts(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = section_head("Impacts", sub="one call, where the hit lands")
    hits = [c for c in cards("impact") if "fade_" not in c["code"]]
    spots = [(170 + (k % 6) * 188, 470 - (k // 6) * 175) for k in range(len(hits))]
    for card, (x, y) in zip(hits, spots):
        small_tag(label_of(card), (x, y - 80))
    # the whole-screen ones (flash, shake, glitch) on a bar's first beat; the
    # others two at a time on every half beat, so each comes back about every second
    screen_wide = [k for k, c in enumerate(hits) if "_at" not in c["code"]]
    local = [k for k in range(len(hits)) if k not in screen_wide]
    n = 0
    while now() < t + 6.0:
        await at(t + 0.3 + n * BEAT / 2)
        if n % 8 == 0 and n // 8 < len(screen_wide):
            todo = [screen_wide[n // 8]]
        else:
            todo = [local[(2 * n) % len(local)], local[(2 * n + 1) % len(local)]]
        for k in todo:
            x, y = spots[k]
            run_card(hits[k]["code"], scene_ns(x=x, y=y))
        n += 1
    leave(words, time=0.3)


# ---- 1:24  entrances, exits and hits: a row of ships, each its verb, twice ----

async def transients(t):
    Stars(color=FROST, density=0.3, twinkle=0.3)
    words = section_head("Entrances, exits, hits", sub="one verb, on any sprite or shape")
    verbs = cards("life", "hit", "pulse", "pop", "knock", "spark")
    places = [(110 + (k % 6) * 212, 430 - (k // 6) * 200) for k in range(len(verbs))]
    for card, (x, y) in zip(verbs, places):
        small_tag(label_of(card), (x, y - 60))
    ships = []
    for lap, step in enumerate((BEAT, BEAT / 2)):
        for ship in ships:
            if ship.is_alive:
                ship.destroy()
        ships = []
        for k, card in enumerate(verbs):
            ship = Sprite(SHIPS[(k + lap) % len(SHIPS)], height=56, center=places[k])
            if card["family"] == "life" and "_in" in card["code"]:
                ship.visible = False
            ships.append(ship)
        begin = now()
        for k, card in enumerate(verbs):
            await at(begin + 0.2 + k * step)
            run_card(card["code"], scene_ns(ship=ships[k]))
        await wait(0.7)
    leave([s for s in ships if s.is_alive], words, time=0.3)


# ---- 1:32  all of it together ----

async def together(t):
    words = section_head("They compose", sub="a background, the world, looks, light, impacts: at once")
    layers = []
    steps = [
        lambda: Nebula(color="dark cyan", color2="midnight blue", alpha=0.6),
        lambda: Stardust(color=DEEP, color2=EMBER),
        lambda: Borealis(color=ICE, alpha=0.7),
        lambda: Portal(center=(640, 360), radius=230, color=ICE, color2=EMBER),
        lambda: Warp(center=(640, 360), radius=120),
        lambda: Orb(center=(640, 360), radius=56),          # in front of the warp
    ]
    for k, make in enumerate(steps):
        await at(t + 0.3 + k * 2 * BEAT)
        layers.append(make())
    # six ships round the orb, each in its own look
    ship_looks = (Aura, EmissiveBloom, lambda: Halo(ICE), ElectricField, Flame, Metal)
    ships = []
    for k, look in enumerate(ship_looks):
        ship = Sprite(SHIPS[k % len(SHIPS)], height=54)
        ship["center"] @= lambda k=k: (640 + 330 * cos(now() * 0.7 + k * pi / 3),
                                       360 + 210 * sin(now() * 0.7 + k * pi / 3))
        ship["angle"] @= lambda k=k: (now() * 0.7 + k * pi / 3) * 180 / pi
        ship.visual = look()
        ship.tail = Tail(color=PALETTE[k], size=4)
        ship.fade_in(0.3)
        ships.append(ship)
        await wait(BEAT)
    for x in (140, 1140):
        layers.append(Fire(center=(x, 90), style="blaze"))
    layers.append(GodRays(weight=0.05, target=(640, 360)))
    layers.append(Chroma(2))
    for k in range(9):
        await at(t + 7.6 + k * BEAT * 2)
        canvas.fireworks_at(220 + (k * 397) % 840, 520 + (k * 131) % 140,
                            color=PALETTE[k % 8], color2=FROST, radius=130, amount=1.1)
    leave(words, time=0.3)
    words = section_head("Change any parameter.", sub="Combine any of them.")
    await at(t + 13.9)
    leave(words, ships, time=0.4)
    await wait(0.4)
    for layer in layers:
        if isinstance(layer, (Portal, Orb, Warp, Fire)):
            layer.destroy()
        else:
            layer.remove()


# ---- 1:47  one line each: the code grows its parameters, the picture follows ----

ONE_LINE = (        # a row each: the bare call, one parameter, several
    ('Nebula()', 'Nebula("orchid")',
     'Nebula("orchid", color2="navy", speed=0.6, alpha=0.8)'),
    ('ship.visual = Flame()', 'ship.visual = Flame(amount=1.6)',
     'ship.visual = Flame(amount=1.6, speed=2.5, border=True)'),
    ('Grade()', 'Grade("warm")', 'Grade("warm", contrast=1.3, saturation=1.4)'),
    ('Vignette()', 'Vignette(amount=1.6)', 'Vignette(amount=1.6, thickness=0.4)'),
)
ROW_LEFT, ROW_TOP, ROW_STEP = 110, 236, 46
# when each line runs: the first after three seconds of the empty scene, held
# three more, then one every 1.8 s, and two seconds of all of them at the end
ONE_LINE_AT = (3.0, 6.0) + tuple(6.0 + 1.8 * k for k in range(1, 11))


def code_row(code, row):
    words = Text(code, center=(0, ROW_TOP - row * ROW_STEP), font=MONO, font_size=24,
                 color=FROST)
    words.center = (ROW_LEFT + words.box.width / 2, ROW_TOP - row * ROW_STEP)
    words.layer = "top"
    return words


async def one_line(t):
    words = section_head("One line each", sub="no setup, no boilerplate: parameters only if you want them")
    ship = flyer()
    ship["center"].unlink()
    ship["center"] @= lambda: (640 + 300 * sin(now() * 1.1), 470 + 50 * sin(now() * 2.2))
    back = Rect(center=(640, 166), width=1120, height=212, corner_radius=14,
                color=Color(NIGHT).with_alpha(0.72))
    back.line = Color(DEEP).with_alpha(0.6)
    back.line_width = 1.5
    back.layer = "top"
    back.fade_in(0.4)
    mark = Rect(center=(ROW_LEFT - 22, ROW_TOP), width=6, height=30, corner_radius=3,
                color=EMBER)
    mark.layer = "top"
    mark.visible = False
    rows, made = [], []
    for row, versions in enumerate(ONE_LINE):
        made.append([])
        rows.append(None)
        for k, code in enumerate(versions):
            await at(t + ONE_LINE_AT[row * 3 + k])
            if rows[row] is not None:
                leave([rows[row]], style="fade", time=0.08)
            rows[row] = code_row(code, row)
            rows[row].pop(scale=1.08)
            mark.center = (ROW_LEFT - 22, ROW_TOP - row * ROW_STEP + 8)
            mark.visible = True
            drop(made[row])
            made[row] = run_card(code, scene_ns(ship=ship))
    await at(t + 26.0)
    leave(words, rows, back, mark, ship, time=0.4)
    await wait(0.4)
    for row in made:
        undo(row)


async def finale(t):
    await made_with_scena(note_line="every effect, with its code, in the API Guide",
                          music='"Boss Battle Music" by Juhani Junkala (CC0)')


SECTIONS = [
    (0.0, title, False),
    (bar(4), looks, False),
    (bar(20), world, False),
    (bar(30), backgrounds, False),
    (bar(44), screen, False),
    (bar(57), impacts, False),
    (bar(62), transients, False),
    (bar(68), together, False),
    (bar(79), one_line, False),
    (MUSIC_SECONDS, finale, False),
    (MUSIC_SECONDS + 5.5, None, False),
]


def update(dt):
    st.frame += 1


async def show():
    await run_sections(SECTIONS, music=MUSIC, label="effects")


run_task(show)
run(Card)
