"""Third round of headless collision probes: pointed hulls, upward ramp hits,
and seams between adjacent platforms.

    python scripts/diag/collision_probe3.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scena.collision import (
    STATIC,
    get_collision_system,
    reset_collision_system,
    resolve,
)
from scena.shapes import Polygon, Rect
from scena.scenamath import Vec2

DT = 1.0 / 60.0
GRAVITY = 900.0
RUN = 250.0
HERO_W, HERO_H = 38.0, 70.0


def new_world():
    reset_collision_system()


def step():
    get_collision_system().step()


def make_slab(cx, cy, w=220.0, h=24.0, angle=0):
    slab = Rect(center=(cx, cy), width=w, height=h, angle=angle, group="plataforma")
    slab.mass = STATIC
    return slab


def contacts(body):
    return [(c.side, round(c.slope_angle, 1)) for c in body.touching_contacts]


# --------------------------------------------------------------------------
# 9 — pointed (diamond / hull-like) body falling onto a thin slab
# --------------------------------------------------------------------------
def probe_pointed(fall_speed, half_w=19.0, half_h=35.0, slab_h=24.0, drift=0.0):
    """Diamond hitbox: the shape an 'auto'/'hull' fitter produces for tapered art."""
    new_world()
    slab = make_slab(500.0, 300.0, 220.0, slab_h)
    slab_top = 300.0 + slab_h / 2
    slab_bot = 300.0 - slab_h / 2
    bx, by = 500.0 - 40.0, slab_top + half_h + 30.0
    pts = [(bx, by - half_h), (bx + half_w, by), (bx, by + half_h), (bx - half_w, by)]
    body = Polygon(points=pts, group="heroi")
    body.mass = 1.0
    body.vel = Vec2(drift, -fall_speed)
    resolve("heroi", "plataforma", bounce=0.0)

    for _ in range(60):
        body.vel.y -= GRAVITY * DT
        body.move_by(body.vel.x * DT, body.vel.y * DT)
        step()
        y = float(body.center.y)
        x = float(body.center.x)
        if y + half_h < slab_bot and abs(x - 500.0) < 105.0:
            return True, round(x, 1), round(y, 1)
    return False, round(float(body.center.x), 1), round(float(body.center.y), 1)


# --------------------------------------------------------------------------
# 10 — jump UP into an inclined slab (unwanted launch / underside stick)
# --------------------------------------------------------------------------
def probe_jump_into_ramp(angle=22, jump_vy=460.0, dx_from_low_corner=-40.0,
                         start_below=60.0, hold_right=True):
    new_world()
    cx, cy, w, h = 880.0, 260.0, 200.0, 24.0
    slab = make_slab(cx, cy, w, h, angle)
    a = math.radians(angle)
    low_x = cx - (w / 2) * math.cos(a) + (h / 2) * math.sin(a)
    low_y = cy - (w / 2) * math.sin(a) - (h / 2) * math.cos(a)
    hero = Rect(center=(low_x + dx_from_low_corner, low_y - start_below),
                width=HERO_W, height=HERO_H, group="heroi")
    hero.mass = 1.0
    hero.vel = Vec2(RUN if hold_right else 0.0, jump_vy)
    resolve("heroi", "plataforma", bounce=0.0)

    y0 = float(hero.center.y)
    peak_y = y0
    rows = []
    stuck = 0
    for frame in range(80):
        if hold_right:
            hero.vel.x = RUN
        hero.vel.y -= GRAVITY * DT
        vb = float(hero.vel.y)
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        va = float(hero.vel.y)
        y = float(hero.center.y)
        peak_y = max(peak_y, y)
        cs = contacts(hero)
        if cs and abs(va) < 5.0:
            stuck += 1
        if cs or abs(va - vb) > 1.0:
            rows.append((frame, round(float(hero.center.x), 1), round(y, 1),
                         round(vb, 1), round(va, 1), cs))
    free_peak = y0 + jump_vy * jump_vy / (2 * GRAVITY)
    return round(peak_y - y0, 1), round(free_peak - y0, 1), stuck, rows[:14]


# --------------------------------------------------------------------------
# 11 — seam between two adjacent floor rects
# --------------------------------------------------------------------------
def probe_seam(gap=0.0, speed=RUN):
    new_world()
    make_slab(400.0, 300.0, 200.0, 24.0)
    make_slab(600.0 + gap, 300.0, 200.0, 24.0)
    slab_top = 312.0
    hero = Rect(center=(330.0, slab_top + HERO_H / 2), width=HERO_W, height=HERO_H,
                group="heroi")
    hero.mass = 1.0
    hero.vel = Vec2(speed, 0.0)
    resolve("heroi", "plataforma", bounce=0.0)

    events = []
    for frame in range(90):
        hero.vel.x = speed
        hero.vel.y -= GRAVITY * DT
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        sides = tuple(sorted(hero.touching_sides))
        if sides != ("bottom",):
            events.append((frame, round(float(hero.center.x), 1),
                           round(float(hero.center.y), 1), contacts(hero)))
    return events[:12]


def main():
    print("=" * 78)
    print("PROBE 9 — pointed (diamond) hitbox falling onto a 24px slab")
    print("=" * 78)
    for slab_h in (24.0, 40.0):
        for speed in (300.0, 700.0, 1200.0, 1800.0):
            for drift in (0.0, 250.0):
                passed, x, y = probe_pointed(speed, slab_h=slab_h, drift=drift)
                mark = "PASSED THROUGH" if passed else "stopped"
                print(f" slab_h={slab_h:5.1f} fall={speed:7.1f} drift={drift:6.1f} "
                      f"-> {mark:<15} x={x} y={y}")

    print()
    print("=" * 78)
    print("PROBE 10 — jump UP into an inclined slab from below/left")
    print("=" * 78)
    for angle in (22, 35):
        for dx in (-40.0, -10.0, 20.0, 60.0):
            rise, free_rise, stuck, rows = probe_jump_into_ramp(angle, dx_from_low_corner=dx)
            flag = "LAUNCH" if rise > free_rise + 8 else ("STICK" if stuck > 3 else "ok")
            print(f"\n angle={angle} start dx={dx:6.1f}: rise={rise:7.1f} "
                  f"(free jump {free_rise:6.1f})  stuck_frames={stuck}  [{flag}]")
            for r in rows[:8]:
                print(f"    f{r[0]:<3} x={r[1]:<8} y={r[2]:<8} vy {r[3]:<8}->{r[4]:<8} {r[5]}")

    print()
    print("=" * 78)
    print("PROBE 11 — running across a seam between two adjacent floor rects")
    print("=" * 78)
    for gap in (0.0, 0.5, 2.0):
        events = probe_seam(gap)
        print(f"\n gap={gap}: {len(events)} non-clean-ground frames")
        for e in events:
            print(f"    f{e[0]:<3} x={e[1]:<8} y={e[2]:<8} {e[3]}")


if __name__ == "__main__":
    main()
