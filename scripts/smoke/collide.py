"""
collide.py — smoke: group-pool vs named-pair collision (shapes + sprites).

Left: @collide("pool", "pool") — every pool member hits every other pool member.
Right: named pairs — player↔enemy/wall, bullet↔enemy, player↔tokens.
Bottom: sprite × shape and sprite × sprite (named tags).
Drag to test. SPACE toggles collider outlines.
Contact Points at info.point: lime parks at enter, gold tracks stay, magenta exit (hides 3s later).
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1400, 900
init(width=W, height=H, window_scale=0.75, title="Smoke — collision")
canvas.background = (0.07, 0.08, 0.11, 1)

hud = SmokeHud(
    title="Collision",
    expect="pool white (incl. arc/ring Track); named pairs on the right; lime enter, gold stay, magenta exit (hide 3s)",
    keys="drag  ·  wheel rotate pool shapes  ·  SPACE outlines",
    status="drag shapes/sprites into each other…",
)

# Section captions (mid/high y — clear of top HUD and bottom FPS)
Text(text='POOL  @collide("pool","pool")  ·  Track arc/ring', top_left=(40, H - 112), font_size=15,
      color=Color(0.55, 0.85, 1.0, 1))
Text(text="group×group on this side; not the right side", top_left=(40, H - 138), font_size=12,
      color=Color(0.55, 0.6, 0.7, 1))

Text(text='PAIRS  @collide("player", ["enemy","wall"]) …', top_left=(760, H - 112), font_size=15,
      color=Color(1.0, 0.85, 0.45, 1))
Text(text="only named pairs; sprites below", top_left=(760, H - 138), font_size=12,
      color=Color(0.55, 0.6, 0.7, 1))

# Contact Points at info.point (not info.points). Exit has no point — keep last locus.
# Enter (lime, larger) parks on first contact; stay (gold, smaller) tracks live contact
# so lime stays visible as a halo when the two coincide. Magenta = exit.
_ENTER_COLOR = "lime"
_STAY_COLOR = "gold"
_EXIT_COLOR = "magenta"
_ENTER_R = 8.0
_STAY_R = 4.5
_contact = {}       # pair key → {enter, live, last}
_contact_hide = {}  # pair key → after() Handle
_contact_gen = {}   # pair key → int; invalidates a late hide callback


def _pair_key(me, other):
    return frozenset((id(me), id(other)))


def _bump(key):
    _contact_gen[key] = _contact_gen.get(key, 0) + 1
    return _contact_gen[key]


def _new_marker(radius):
    marker = Point(0, 0)
    marker.collidable = False
    marker.GUIDE_RADIUS = radius
    return marker


def _pack_for(me, other):
    key = _pair_key(me, other)
    pack = _contact.get(key)
    if pack is None:
        pack = {
            "enter": _new_marker(_ENTER_R),
            "live": _new_marker(_STAY_R),
            "last": None,
        }
        _contact[key] = pack
    return key, pack


def _cancel_hide(key):
    _bump(key)
    handle = _contact_hide.pop(key, None)
    if handle is not None:
        handle.cancel()


def _paint_marker(marker, color):
    marker.set_color(color)
    marker.line = Color(0.05, 0.05, 0.08, 1)
    marker.line_width = 1.5


def _place(marker, pt, color):
    marker.x = pt[0]
    marker.y = pt[1]
    _paint_marker(marker, color)
    marker.visible = True


def _show_enter(me, other, info):
    pt = info.point
    if not pt:
        return
    key, pack = _pack_for(me, other)
    _cancel_hide(key)
    pack["last"] = pt
    _place(pack["enter"], pt, _ENTER_COLOR)
    pack["live"].visible = False


def _show_stay(me, other, info):
    pt = info.point
    if not pt:
        return
    key, pack = _pack_for(me, other)
    pack["last"] = pt
    _place(pack["live"], pt, _STAY_COLOR)


def _exit_contact(me, other):
    key = _pair_key(me, other)
    pack = _contact.get(key)
    if pack is None:
        return
    pt = pack["last"]
    if pt:
        _place(pack["live"], pt, _EXIT_COLOR)
    _cancel_hide(key)
    gen = _contact_gen[key]
    enter, live = pack["enter"], pack["live"]

    def hide(k=key, e=enter, m=live, g=gen):
        if _contact_gen.get(k) != g:
            return
        e.visible = False
        m.visible = False
        _contact_hide.pop(k, None)

    _contact_hide[key] = after(3.0, hide)


# --- POOL (group × group) ----------------------------------------------------
c1 = Circle(center=(120, 620), radius=40, group="pool").set_color("cyan")
r1 = Rect(center=(260, 620), width=90, height=65, group="pool").set_color("orange")
sq1 = Square(center=(400, 620), length=60, angle=15, group="pool").set_color("lime")
e1 = Ellipse(center=(120, 470), width=100, height=55, angle=20, group="pool").set_color("magenta")
t1 = Triangle(center=(260, 470), radius=48, group="pool").set_color("gold")
hex1 = RegularPolygon(n=6, center=(400, 470), radius=44, group="pool").set_color("coral")
line1 = Line(p1=(60, 330), p2=(200, 370), group="pool").set_color("sky blue")
line1.line_width = 12
poly1 = Polygon(
    points=[(280, 300), (400, 300), (400, 340), (340, 340), (340, 380), (280, 380)], group="pool",
).set_color("plum")
# Track stroke walls: quarter arc + closed ring (hole stays empty).
# Sit in the mid gap between the left pool and right named pairs.
arc1 = Track.arc(
    center=(520, 470), radius=55, from_angle=0, to_angle=90,
    color="hot pink", line_width=12, group="pool",
)
ring1 = Track.circle(
    center=(520, 320), radius=42, color="turquoise", line_width=10, group="pool",
)

for s in (c1, r1, sq1, e1, t1, hex1, line1, poly1, arc1, ring1):
    s.draggable = True
    s.wheel_rotate = True

# Home colors, keyed by the actor itself (Scena has no ids).
_POOL_COLOR = {
    c1: "cyan", r1: "orange", sq1: "lime", e1: "magenta",
    t1: "gold", hex1: "coral", line1: "sky blue", poly1: "plum",
    arc1: "hot pink", ring1: "medium turquoise",
}


@collide("pool", "pool")
def on_pool_hit(me, other, info):
    me.set_color("white")
    other.set_color("white")
    _show_enter(me, other, info)
    hud.status = f"POOL: {me} ↔ {other}"


@collide_stay("pool", "pool")
def on_pool_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("pool", "pool")
def on_pool_exit(me, other, info):
    me.set_color(_POOL_COLOR.get(me, "white"))
    other.set_color(_POOL_COLOR.get(other, "white"))
    _exit_contact(me, other)


# --- Named-pair shapes ---------------------------------------------------------
player = Circle(center=(860, 620), radius=36, group="player").set_color("dodger blue")
enemy_a = Rect(center=(1040, 620), width=80, height=60, group="enemy").set_color("crimson")
enemy_b = Ellipse(center=(1200, 620), width=80, height=50, angle=-20, group="enemy").set_color("tomato")
wall = Rect(center=(1020, 470), width=200, height=36, group="wall").set_color("dim gray")
bullet = Circle(center=(860, 470), radius=16, group="bullet").set_color("yellow")

for s in (player, enemy_a, enemy_b, wall, bullet):
    s.draggable = True

_RESTORE = {
    player: "dodger blue", enemy_a: "crimson", enemy_b: "tomato",
    wall: "dim gray", bullet: "yellow",
}


@collide("player", ["enemy", "wall"])
def on_player_hits(me, other, info):
    me.set_color("yellow")
    other.set_color("yellow")
    _show_enter(me, other, info)
    hud.status = f"PAIR: {me} ↔ {other}"


@collide_stay("player", ["enemy", "wall"])
def on_player_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("player", ["enemy", "wall"])
def on_player_unhit(me, other, info):
    me.set_color(_RESTORE.get(me, "white"))
    other.set_color(_RESTORE.get(other, "white"))
    _exit_contact(me, other)


@collide("bullet", "enemy")
def on_bullet_hits(me, other, info):
    me.set_color("red")
    other.set_color("yellow")
    _show_enter(me, other, info)
    hud.status = f"PAIR: {me} ↔ {other}"


@collide_stay("bullet", "enemy")
def on_bullet_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("bullet", "enemy")
def on_bullet_unhit(me, other, info):
    me.set_color(_RESTORE.get(me, "white"))
    other.set_color(_RESTORE.get(other, "white"))
    _exit_contact(me, other)


token1 = Circle(center=(860, 320), radius=24, group="tokens").set_color("sea green")
token2 = Square(center=(960, 320), length=44, group="tokens").set_color("sea green")
token1.draggable = True
token2.draggable = True
Text(text='tokens  @collide(player,"tokens")', top_left=(760, 374), font_size=12,
      color=Color(0.55, 0.85, 0.65, 1))


@collide(player, "tokens")
def on_player_token(me, other, info):
    other.set_color("cyan")
    _show_enter(me, other, info)
    hud.status = f"PAIR: {me} ↔ {other}"


@collide_stay(player, "tokens")
def on_player_token_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit(player, "tokens")
def on_player_token_exit(me, other, info):
    other.set_color("sea green")
    _exit_contact(me, other)


# --- SPRITES -----------------------------------------------------------------
Text(text="SPRITES  ship↔meteor  ·  ship↔shape wall  ·  bolt↔meteor",
      top_left=(40, 237), font_size=14, color=Color(0.9, 0.75, 1.0, 1))

ship = Sprite(
    "../../examples/media/space/playerShip1_red.png", height=48, center=(140, 140),
    group="ship", hitbox_shape="auto",
)
meteor = Sprite(
    "../../examples/media/space/meteorBrown_big3.png", size=56, center=(320, 140),
    group="meteor", hitbox_shape="auto",
)
bolt = Sprite(
    "../../examples/media/space/laserBlue03.png", height=40, center=(480, 140),
    group="bolt", hitbox_shape="rect",
)
sprite_wall = Rect(center=(640, 140), width=100, height=40, group="swall").set_color("slate gray")

for s in (ship, meteor, bolt, sprite_wall):
    s.draggable = True


@collide("ship", "meteor")
def on_ship_meteor(me, other, info):
    me.flash(0.1)
    other.flash(0.1)
    _show_enter(me, other, info)
    hud.status = f"SPRITE: {me} ↔ {other}"


@collide_stay("ship", "meteor")
def on_ship_meteor_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("ship", "meteor")
def on_ship_meteor_exit(me, other, info):
    _exit_contact(me, other)


@collide("ship", "swall")
def on_ship_wall(me, other, info):
    me.flash(0.1)
    other.set_color("orange")
    _show_enter(me, other, info)
    hud.status = f"SPRITE×SHAPE: {me} ↔ {other}"


@collide_stay("ship", "swall")
def on_ship_wall_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("ship", "swall")
def on_ship_wall_exit(me, other, info):
    other.set_color("slate gray")
    _exit_contact(me, other)


@collide("bolt", "meteor")
def on_bolt_meteor(me, other, info):
    me.flash(0.08)
    other.flash(0.08)
    _show_enter(me, other, info)
    hud.status = f"SPRITE: {me} ↔ {other}"


@collide_stay("bolt", "meteor")
def on_bolt_stay(me, other, info):
    _show_stay(me, other, info)


@collide_exit("bolt", "meteor")
def on_bolt_exit(me, other, info):
    _exit_contact(me, other)


_outlines = False


def on_key_down(key):
    global _outlines
    if key == "SPACE":
        _outlines = not _outlines
        collision.show_colliders(_outlines)
        hud.status = f"outlines {'ON' if _outlines else 'OFF'}"


run()
