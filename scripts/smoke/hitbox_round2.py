"""Hitbox parts, round 2 — px_rect / px_circle, sprite.showing(), linked active.

Real art from ``examples/media`` (no generated stand-ins). Collider
outlines stay on: cyan = hitbox part, gold = resolve body, green = other body.

  1  px shapes follow the drawing. Eight ninja Attack copies, each with the
     same ``px_rect=(400, 60, 136, 375)`` (the slash, read off
     Attack__004.png) and ``px_circle=(230, 85, 50)`` (the head): plain,
     flip_x, spinning, tilt 20, Sprite(offset=), clip(offset=),
     Sheet(anchor="center"), scale 1.3. LOOK FOR: on the slash cells (4–6)
     every cyan rect sits on the slash and every circle on the head.
  2  Where the numbers come from. A grid strip (pixel_adv Start (Moving), cols=17):
     the blade box is cell-local (80, 80, 44, 28), linked to cell 4. A packed
     atlas (shooter/sheet.xml): the cockpit circle is in the SubTexture's own
     pixels (49, 30), not the sheet's (260, 971). A box past the cell edge and
     one bigger than the PNG (ufoYellow). The caveat: the same px_circle on
     ninja Idle (232 px wide) is the head; on Attack (536 wide) it lands
     behind the body. A trimmed atlas has no real art here — unit-tested only
     (tests/test_hitbox_round2.py). LOOK FOR: blade box only on the blade
     cell, circle on the cockpit, the two ufo boxes, Idle head vs Attack miss.
  3  sprite.showing(...). Ninja Run with four lamps: a clip name, an index, a
     frame name, a mixed tuple. A dust puff on cells (2, 7) from showing() in
     update. Q/W clip (run, yoyo run, idle), I interrupts with play("idle").
     LOOK FOR: lamps light exactly on those cells, in slow motion too.
  4  Linked active — the attack. SPACE swings. The slash box is
     ``espada["active"] @= lambda: heroi.showing(GOLPE)``; dummies flash on
     enter; the HUD counts enter / exit per swing (expect 1 / 1 for the near
     dummy, 0 for the far one). H hits the hero mid-swing (plays "dead"):
     the box goes off at once. U unlinks / relinks (unlinked: the box keeps
     its last value). L moves play() into on_update and widens the gate to
     the whole swing: the HUD's "play at" and "enter at" frames match.
  5  Plain .active next to linked. Bullets hit the runner's hurtbox (a part):
     ``dor.active = False`` plus ``after(1.5)`` — the cyan hurtbox vanishes
     for 1.5 s whatever the animation does. The ufo boss lands on the floor
     through resolve (gold body) and a px_circle weak spot takes the upper
     lane of bullets; the lower lane passes through the body.

Controls
--------
  A / S      previous / next page
  Z          slow motion (clock.scale 1 <-> 0.1)
  P          pause / resume the playhead (time_scale 0)
  M          one cell forward while paused
  F / R / T  flip / spin / tilt the page-1 copies
  Q / W      previous / next clip (page 3)
  I          interrupt (page 3)
  SPACE      swing (page 4)
  H / U / L  hit mid-swing / unlink-relink / play() in on_update (page 4)

Usage
-----
    python scripts/smoke/hitbox_round2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from scena import *

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hud import SmokeHud

W, H = 1480, 960
_MEDIA = Path(__file__).resolve().parents[2] / "examples" / "media"
_INK = Color(0.78, 0.84, 0.94, 1)
_DIM = Color(0.25, 0.28, 0.34, 1)
_LIT = Color(1.0, 0.85, 0.25, 1)

init(width=W, height=H, window_scale=0.78, title="Smoke — hitbox round 2")
canvas.background = (0.07, 0.08, 0.11)
collision.show_colliders(True)

hud = SmokeHud(
    title="Hitbox round 2",
    expect="",
    keys="A/S page · Z slow · P pause · M step · F/R/T · Q/W/I · SPACE/H/U/L",
    status="",
    show_aux=True,
)


def _png(name: str) -> str:
    path = _MEDIA / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path.resolve())


def _ninja(prefix: str) -> list[str]:
    return [_png(f"ninja/{prefix}__00{i}.png") for i in range(10)]


def _stems(files: list[str]) -> list[str]:
    return [Path(f).stem for f in files]


def _label(text: str, x: float, y: float, size: int = 14):
    return Text(text=text, top_left=(x - 160, y), font_size=size, color=_INK, stack=False)


# Numbers read off the art (image-editor pixels: top-left origin, y down).
SLASH = (400, 60, 136, 375)       # Attack__004..006: the slash arc
HEAD = (230, 85, 50)              # Attack cells: the head
IDLE_HEAD = (116, 57, 40)         # Idle__000: the head (232 px wide cell)
BLADE_CELL = (40, 40, 22, 14)     # Start (Moving), cell 4 (cell-local, 64×64)
COCKPIT = (49, 30, 12)            # playerShip1_blue.png SubTexture (99×75)

_ATTACK = _ninja("Attack")
_IDLE = _ninja("Idle")
_RUN = _ninja("Run")
_DEAD = _ninja("Dead")


def _attack_sheet(**kw) -> Sheet:
    sheet = Sheet(_ATTACK, **kw)
    return sheet


# --- page 1: px shapes follow the drawing --------------------------------------

@collide("p1_slash", "p1_nothing")
def _p1(a, b, info):
    pass


@collide("p1_head", "p1_nothing")
def _p1h(a, b, info):
    pass


def _build_follow():
    bottom = _attack_sheet(anchor="bottom")
    bottom.clip("golpe", _stems(_ATTACK), fps=10)
    moved = _attack_sheet(anchor="bottom")
    moved.clip("golpe", _stems(_ATTACK), fps=10, offset=(60, 0))
    centred = _attack_sheet(anchor="center")
    centred.clip("golpe", _stems(_ATTACK), fps=10)
    specs = [
        ("plain", bottom, {}),
        ("flip_x", bottom, {"flip_x": True}),
        ("spinning", bottom, {}),
        ("tilt 20", bottom, {"tilt": 20}),
        ("Sprite(offset=(0, 30))", bottom, {"offset": (0, 30)}),
        ("clip(offset=(60, 0))", moved, {}),
        ('Sheet(anchor="center")', centred, {}),
        ("scale 1.3", bottom, {"scale": 1.3}),
    ]
    actors, copies = [], []
    for i, (name, sheet, extra) in enumerate(specs):
        col, row = i % 4, i // 4
        x = 230 + col * 340
        y = 470 if row == 0 else 150
        s = Sprite(sheet, height=150, center=(x, y), hitbox_shape="rect", group="p1_body")
        for k, v in extra.items():
            setattr(s, k, v)
        s.play("golpe")
        s.add_hitbox(group="p1_slash", px_rect=SLASH)
        s.add_hitbox(group="p1_head", px_circle=HEAD)
        copies.append((name, s))
        actors += [s, _label(name, x, y - 12)]
    return actors, copies


# --- page 2: where the numbers come from ----------------------------------------

@collide(["p2_box", "p2_big"], "p2_nothing")
def _p2(a, b, info):
    pass


def _build_sources():
    actors = []
    grid = Sheet(_png("pixel_adv/Start (Moving) (64x64).png"), cols=17, fps=6, anchor="bottom")
    grid.clip("attack", [0, 1, 2, 3, 4, 5], fps=6)
    sword = Sprite(grid, height=220, center=(230, 420), hitbox_shape="rect")
    sword.play("attack")
    blade = sword.add_hitbox(group="p2_box", px_rect=BLADE_CELL)
    blade["active"] @= lambda: sword.showing(4)
    actors += [sword, _label("grid strip: (40, 40, 22, 14)", 230, 400),
               _label("cell-local, on cell 4 only", 230, 380)]

    atlas = Sheet(_png("shooter/sheet.png"), atlas=_png("shooter/sheet.xml"))
    ship = Sprite(atlas, frame="playerShip1_blue.png", height=150,
                  center=(600, 560), hitbox_shape="rect")
    ship.add_hitbox(group="p2_box", px_circle=COCKPIT)
    actors += [ship, _label("packed atlas: cockpit (49, 30, 12)", 600, 460),
               _label("SubTexture pixels, not (260, 971)", 600, 440)]

    ufo = Sprite(_png("space/ufoYellow.png"), height=180, center=(980, 560), hitbox_shape="rect")
    ufo.add_hitbox(group="p2_box", px_rect=(73, 73, 36, 36))      # past the corner
    ufo.add_hitbox(group="p2_big", px_rect=(-20, -20, 131, 131))   # one part per group
    actors += [ufo, _label("past the edge (73, 73, 36, 36)", 980, 430),
               _label("bigger than the PNG (-20, -20, 131, 131)", 980, 410)]

    idle_sheet = Sheet(_IDLE, anchor="bottom")
    idle_sheet.clip("idle", _stems(_IDLE), fps=8)
    idle = Sprite(idle_sheet, height=200, center=(420, 90), hitbox_shape="rect")
    idle.play("idle")
    idle.add_hitbox(group="p2_box", px_circle=IDLE_HEAD)
    attack = _attack_sheet(anchor="bottom")
    attack.clip("golpe", _stems(_ATTACK), fps=8)
    swing = Sprite(attack, height=200 * 495 / 439, center=(900, 90), hitbox_shape="rect")
    swing.play("golpe")
    swing.add_hitbox(group="p2_box", px_circle=IDLE_HEAD)
    actors += [idle, swing,
               _label("Idle: (116, 57, 40) is the head", 420, 330),
               _label("Attack: same numbers, 536-wide cell:", 900, 330),
               _label("lands behind the body (documented)", 900, 310),
               _label("trimmed atlas: no real art here — unit-tested", 1300, 200)]
    return actors


# --- page 3: sprite.showing(...) ---------------------------------------------------

_run_sheet = Sheet(_RUN + _IDLE, anchor="bottom")
_run_sheet.clip("run", _stems(_RUN), fps=12)
_run_sheet.clip("yoyo_run", _stems(_RUN), fps=12, yoyo=True)
_run_sheet.clip("idle", _stems(_IDLE), fps=8)
_P3_CLIPS = ("run", "yoyo_run", "idle")
_P3_LAMPS = (
    ('showing("run")', "run"),
    ("showing(3)", 3),
    ('showing("Run__007")', "Run__007"),
    ('showing((0, "Run__005"))', (0, "Run__005")),
)


def _build_showing():
    runner = Sprite(_run_sheet, height=300, center=(420, 180))
    runner.play("run")
    actors = [runner]
    lamps = []
    for i, (text, _sel) in enumerate(_P3_LAMPS):
        y = 620 - i * 90
        lamp = Circle(center=(820, y), radius=22, color=_DIM)
        lamps.append(lamp)
        actors += [lamp, Text(text=text, top_left=(870, y + 12), font_size=20,
                              color=_INK, stack=False)]
    actors.append(_label("dust puff on cells (2, 7)", 420, 150))
    return actors, runner, lamps


# --- page 4: linked active, the attack ------------------------------------------

_fight = Sheet(_IDLE + _ATTACK + _DEAD, anchor="bottom")
_fight.clip("idle", _stems(_IDLE), fps=8)
_fight.clip("golpe", _stems(_ATTACK), fps=8)
_fight.clip("dead", _stems(_DEAD), fps=10)
GOLPE = _stems(_ATTACK)[4:7]          # the slash cells
WHOLE_SWING = _stems(_ATTACK)          # L mode: the gate starts on cell 0
_swing = {"enter": 0, "exit": 0, "far": 0, "linked": True, "in_update": False,
          "pending": False, "play_at": None, "enter_at": None}


def _build_attack():
    hero = Sprite(_fight, height=220, center=(420, 200), group="p4_hero", hitbox_shape="rect")
    hero.play("idle")
    blade = hero.add_hitbox(group="p4_blade", px_rect=SLASH)
    near = Rect(center=(540, 320), width=34, height=150, color=_DIM, group="p4_dummy")
    far = Rect(center=(760, 320), width=34, height=150, color=_DIM, group="p4_far")
    ground = Rect(center=(640, 190), width=900, height=8, color=_DIM)
    return [hero, near, far, ground,
            _label("near dummy", 540, 225), _label("far dummy (out of reach)", 760, 225)], \
        hero, blade, near, far


def _gate():
    return _hero.showing(WHOLE_SWING if _swing["in_update"] else GOLPE)


@collide("p4_blade", "p4_dummy")
def _hit_near(hero, dummy, info):
    _swing["enter"] += 1
    if _swing["enter_at"] is None:
        _swing["enter_at"] = clock.frame
    dummy.flash(0.15)


@collide_exit("p4_blade", "p4_dummy")
def _left_near(hero, dummy, info):
    _swing["exit"] += 1


@collide("p4_blade", "p4_far")
def _hit_far(hero, dummy, info):
    _swing["far"] += 1
    dummy.flash(0.15)


def _hero_update(entity, dt):
    if _swing["pending"]:
        _swing["pending"] = False
        _swing["play_at"] = clock.frame
        entity.play("golpe", loops=1, next="idle")


def _swing_now():
    _swing.update(enter=0, exit=0, far=0, enter_at=None)
    if _swing["in_update"]:
        _swing["pending"] = True          # play() runs in on_update (step 3)
    else:
        _swing["play_at"] = clock.frame
        _hero.play("golpe", loops=1, next="idle")


# --- page 5: plain .active next to linked --------------------------------------------

_runner5_sheet = Sheet(_RUN, anchor="bottom")
_runner5_sheet.clip("run", _stems(_RUN), fps=12)


def _build_plain():
    runner = Sprite(_runner5_sheet, height=200, center=(300, 140), group="p5_hero",
                    hitbox_shape="rect", hitbox_source="run", hitbox_anchor="bottom",
                    hitbox_scale=(0.5, 1.0))
    runner.play("run")
    hurt = runner.add_hitbox(group="p5_hurt", shape="hull", scale=(0.7, 0.9))
    floor = Rect(center=(900, 110), width=900, height=24, color=_DIM, group="p5_floor")
    floor.mass = STATIC
    boss = Sprite(_png("space/ufoYellow.png"), height=150, center=(1050, 700), group="p5_boss",
                  hitbox_shape="circle")
    boss.mass = 1.0
    boss.vel = Vec2(0, 0)
    weak = boss.add_hitbox(group="p5_weak", px_circle=(45, 22, 12))   # the dome
    bullets = []
    for i in range(3):
        b = Circle(center=(1400 - i * 300, 230), radius=7, color=_LIT, group="p5_shot")
        bullets.append(b)
    upper = Circle(center=(200, 0), radius=7, color=Color(0.4, 0.9, 1, 1), group="p5_boss_shot")
    lower = Circle(center=(400, 0), radius=7, color=Color(0.4, 0.9, 1, 1), group="p5_boss_shot")
    return [runner, floor, boss, *bullets, upper, lower,
            _label("hurtbox part: off 1.5 s after a hit", 300, 400),
            _label("weak spot px_circle; body resolves (gold)", 1050, 560)], \
        runner, hurt, boss, weak, bullets, (upper, lower)


resolve("p5_boss", "p5_floor", bounce=0.0)
_p5 = {"hits": 0, "weak": 0}


@collide("p5_shot", "p5_hurt")
def _shot(bullet, runner, info):
    _p5["hits"] += 1
    bullet.center = (1500, float(bullet.center.y))
    runner.flash(0.2)
    _hurt.active = False                  # plain write: time decides
    runner.after(1.5, _heal)


def _heal():
    _hurt.active = True


@collide("p5_boss_shot", "p5_weak")
def _weak_hit(bullet, boss, info):
    _p5["weak"] += 1
    boss.flash(0.1)
    bullet.center = (-50, float(bullet.center.y))


# --- pages -----------------------------------------------------------------------

_follow_actors, _copies = _build_follow()
_sources_actors = _build_sources()
_showing_actors, _runner3, _lamps = _build_showing()
_attack_actors, _hero, _blade, _near, _far = _build_attack()
_blade["active"] @= _gate
_hero.on_update = _hero_update
_plain_actors, _runner5, _hurt, _boss, _weak, _bullets, _lanes = _build_plain()

_PAGES = [_follow_actors, _sources_actors, _showing_actors, _attack_actors, _plain_actors]
_EXPECT = (
    "Same px_rect / px_circle on eight copies. On the slash cells every cyan rect is on the slash, every circle on the head.",
    "Numbers are the frame's own pixels: grid cell, atlas SubTexture, past the edge. Same numbers in a wider cell land elsewhere.",
    "Lamps light exactly on their cells (Z for slow motion). Dust on cells 2 and 7. Q/W clip, I interrupt.",
    "SPACE swings: the slash box appears only on cells 4-6. Near dummy 1 enter / 1 exit; far dummy 0. H mid-swing: box off at once.",
    "A hit turns the cyan hurtbox off for 1.5 s. The ufo stands on the floor (gold); only the upper lane hits the weak spot.",
)
_PAGE = 0
_spin = False
_slow = False
_paused = False
_p3_clip = 0
_puff_armed = True


def _page_sprites() -> list:
    return [a for a in _PAGES[_PAGE] if isinstance(a, Sprite)]


def _show(page: int) -> None:
    global _PAGE
    _PAGE = page % len(_PAGES)
    for i, actors in enumerate(_PAGES):
        for actor in actors:
            actor.active = i == _PAGE
    hud.expect = _EXPECT[_PAGE]
    hud.status = f"page {_PAGE + 1} / {len(_PAGES)}"
    hud.aux = ""


def _set_time_scale(value: float) -> None:
    for s in _page_sprites():
        s.time_scale = value


def _cell_name(s: Sprite) -> str:
    names = s.sheet.names
    i = s.frame
    return f"cell {i} ({names[i]})" if i < len(names) and names[i] else f"cell {i}"


def update(dt):
    global _puff_armed
    speed = f"{'slow x0.1' if _slow else 'x1'}{'  paused' if _paused else ''}"
    if _PAGE == 0:
        if _spin:
            for _name, s in _copies:
                if _name == "spinning":
                    s.rotate_by(90 * dt)
        s0 = _copies[0][1]
        hud.aux = f"{_cell_name(s0)}    slash cells: Attack__004..006    {speed}"
    elif _PAGE == 1:
        hud.aux = f"{speed}"
    elif _PAGE == 2:
        for lamp, (_text, sel) in zip(_lamps, _P3_LAMPS):
            lamp.color = _LIT if _runner3.showing(sel) else _DIM
        stepping = _runner3.showing((2, 7))
        if stepping and _puff_armed:
            x, y = float(_runner3.center.x), float(_runner3.center.y)
            puff = Circle(center=(x - 40, y + 10), radius=16, color=Color(0.8, 0.8, 0.75, 0.7))
            puff.after(0.25, puff.destroy)
        _puff_armed = not stepping
        hud.aux = f"clip {_P3_CLIPS[_p3_clip]}    {_cell_name(_runner3)}    {speed}"
    elif _PAGE == 3:
        link = "linked" if _blade["active"].linked else "UNLINKED"
        mode = "play() in on_update, gate = whole swing" if _swing["in_update"] else "play() in key handler, gate = cells 4-6"
        hud.status = (f"near enter {_swing['enter']} / exit {_swing['exit']}    far {_swing['far']}"
                      f"    box {'ON' if _blade.active else 'off'}    {link}")
        hud.aux = (f"{mode}    play at frame {_swing['play_at']}    enter at frame {_swing['enter_at']}"
                   f"    {_cell_name(_hero)}    {speed}")
    elif _PAGE == 4:
        for b in _bullets:
            b.move_by(-320 * dt, 0)
            if float(b.center.x) < 0:
                b.center = (1500, float(b.center.y))
        bx, by = float(_boss.center.x), float(_boss.center.y)
        upper, lower = _lanes
        for lane, dy in ((upper, 38), (lower, -25)):
            x = float(lane.center.x) + 420 * dt
            if x > 1480:
                x = -40.0
            lane.center = (x, by + dy)     # lanes follow the boss height
        _boss.vel = Vec2(0, -600)
        _boss.move_by(0, float(_boss.vel.y) * dt)
        hud.status = f"hurtbox {'ON' if _hurt.active else 'off (1.5 s)'}    runner hits {_p5['hits']}    weak-spot hits {_p5['weak']}"
        hud.aux = f"{speed}"


def on_key_down(key):
    global _spin, _slow, _paused, _p3_clip
    if key == "A":
        _show(_PAGE - 1)
    elif key == "S":
        _show(_PAGE + 1)
    elif key == "Z":
        _slow = not _slow
        clock.scale = 0.1 if _slow else 1.0
    elif key == "P":
        _paused = not _paused
        _set_time_scale(0.0 if _paused else 1.0)
    elif key == "M" and _paused:
        sprites = _page_sprites()
        fps = 10.0
        _set_time_scale(1.0)
        if sprites:
            sprites[0].after(1.0 / fps, lambda: _set_time_scale(0.0))
    elif key == "F" and _PAGE == 0:
        for _name, s in _copies:
            s.flip_x = not s.flip_x
    elif key == "R" and _PAGE == 0:
        _spin = not _spin
    elif key == "T" and _PAGE == 0:
        for _name, s in _copies:
            s.tilt = 0 if s.tilt else 20
    elif key in ("Q", "W") and _PAGE == 2:
        _p3_clip = (_p3_clip + (1 if key == "W" else -1)) % len(_P3_CLIPS)
        _runner3.play(_P3_CLIPS[_p3_clip])
    elif key == "I" and _PAGE == 2:
        _runner3.play("idle")
        _p3_clip = 2
    elif key == "SPACE" and _PAGE == 3:
        _swing_now()
    elif key == "H" and _PAGE == 3:
        _hero.play("dead", loops=1, next="idle")
    elif key == "U" and _PAGE == 3:
        if _blade["active"].linked:
            _blade["active"].unlink()
        else:
            _blade["active"] @= _gate
    elif key == "L" and _PAGE == 3:
        _swing["in_update"] = not _swing["in_update"]


_show(0)
run()
