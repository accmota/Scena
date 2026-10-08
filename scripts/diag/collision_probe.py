"""Headless probes for the four reported collision-resolution symptoms.

Uses plain ``Rect`` bodies with fixed geometry, so sprite hitbox instability is
excluded as a variable. Each probe mirrors a platformer game's
update order: input -> gravity -> move_by -> collision.step() (resolve inside).

    python scripts/diag/collision_probe.py
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
from scena.shapes import Rect
from scena.scenamath import Vec2

DT = 1.0 / 60.0
GRAVITY = 900.0
RUN = 250.0

HERO_W, HERO_H = 38.0, 70.0
SLAB_W, SLAB_H = 220.0, 24.0


def new_world():
    reset_collision_system()


def step():
    get_collision_system().step()


def make_hero(cx, cy, vx=0.0, vy=0.0):
    hero = Rect(center=(cx, cy), width=HERO_W, height=HERO_H, group="heroi")
    hero.mass = 1.0
    hero.vel = Vec2(vx, vy)
    return hero


def make_slab(cx, cy, w=SLAB_W, h=SLAB_H, angle=0):
    slab = Rect(center=(cx, cy), width=w, height=h, angle=angle, group="plataforma")
    slab.mass = STATIC
    return slab


def contacts(hero):
    return [(c.side, round(c.slope_angle, 1)) for c in hero.touching_contacts]


def ramp_surface_y(slab, x, angle_deg, h=SLAB_H):
    """Analytic y of the ramp's upper face directly above ``x`` (y-up)."""
    a = math.radians(angle_deg)
    cx, cy = float(slab.center.x), float(slab.center.y)
    # Upper face passes through center offset by half-thickness along the normal.
    nx, ny = -math.sin(a), math.cos(a)
    px, py = cx + nx * h * 0.5, cy + ny * h * 0.5
    return py + math.tan(a) * (x - px)


# --------------------------------------------------------------------------
# Probe 1 — side approach at ledge height ("never falls" / corner catch)
# --------------------------------------------------------------------------
def probe_side_approach(feet_offset):
    """Hero runs RIGHT into a slab's left end, feet ``feet_offset`` below slab top."""
    new_world()
    slab = make_slab(500.0, 300.0)
    slab_top = 300.0 + SLAB_H / 2
    slab_left = 500.0 - SLAB_W / 2
    hero = make_hero(slab_left - HERO_W / 2 - 6.0, slab_top - feet_offset + HERO_H / 2)
    resolve("heroi", "plataforma", bounce=0.0)

    rows = []
    for frame in range(90):
        hero.vel.x = RUN
        hero.vel.y -= GRAVITY * DT
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        rows.append((frame, round(float(hero.center.x), 1), round(float(hero.center.y), 1),
                     round(float(hero.vel.y), 1), contacts(hero)))
    return hero, slab_top, rows


# --------------------------------------------------------------------------
# Probe 2 — fall speed vs slab thickness (pass-through)
# --------------------------------------------------------------------------
def probe_tunnel(fall_speed, slab_h=SLAB_H):
    new_world()
    slab = make_slab(500.0, 300.0, h=slab_h)
    slab_top = 300.0 + slab_h / 2
    hero = make_hero(500.0, slab_top + HERO_H / 2 + 40.0, vy=-fall_speed)
    resolve("heroi", "plataforma", bounce=0.0)

    min_y = float("inf")
    for _ in range(40):
        hero.vel.y -= GRAVITY * DT
        hero.move_by(0.0, hero.vel.y * DT)
        step()
        min_y = min(min_y, float(hero.center.y))
    slab_bottom = 300.0 - slab_h / 2
    passed = float(hero.center.y) + HERO_H / 2 < slab_bottom
    return passed, round(float(hero.center.y), 1), round(min_y, 1)


# --------------------------------------------------------------------------
# Probe 3 — walking on a ramp (floating / excess push)
# --------------------------------------------------------------------------
def probe_ramp_walk(angle=22, rotate_hero=False):
    new_world()
    slab = make_slab(880.0, 260.0, w=200.0, angle=angle)
    start_x = 880.0 - 100.0 * math.cos(math.radians(angle)) + 20.0
    hero = make_hero(start_x, ramp_surface_y(slab, start_x, angle) + HERO_H / 2 + 2.0)
    resolve("heroi", "plataforma", bounce=0.0)

    rows = []
    for frame in range(120):
        hero.vel.x = RUN
        hero.vel.y -= GRAVITY * DT
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        hx = float(hero.center.x)
        feet = float(hero.center.y) - HERO_H / 2
        gap = feet - ramp_surface_y(slab, hx, angle)
        if rotate_hero:
            inc = 0.0
            for c in hero.touching_contacts:
                if c.side == "bottom":
                    inc = c.slope_angle
            hero.angle = inc
        rows.append((frame, round(hx, 1), round(feet, 1), round(gap, 2),
                     round(float(hero.vel.y), 1), contacts(hero)))
    return rows


# --------------------------------------------------------------------------
# Probe 4 — jumping into the low end of a ramp (unwanted launch)
# --------------------------------------------------------------------------
def probe_ramp_side_hit(angle=22):
    new_world()
    slab = make_slab(880.0, 260.0, w=200.0, angle=angle)
    lo_x = 880.0 - 100.0 * math.cos(math.radians(angle))
    lo_y = 260.0 - 100.0 * math.sin(math.radians(angle))
    hero = make_hero(lo_x - 90.0, lo_y - 10.0, vx=RUN, vy=0.0)
    resolve("heroi", "plataforma", bounce=0.0)

    rows = []
    peak_vy = -1e9
    for frame in range(60):
        hero.vel.x = RUN
        hero.vel.y -= GRAVITY * DT
        before = float(hero.vel.y)
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        after = float(hero.vel.y)
        peak_vy = max(peak_vy, after)
        if abs(after - before) > 1.0 or hero.touching_contacts:
            rows.append((frame, round(float(hero.center.x), 1), round(float(hero.center.y), 1),
                         round(before, 1), round(after, 1), contacts(hero)))
    return peak_vy, rows


def main():
    print("=" * 78)
    print("PROBE 1 — run RIGHT into a slab's left end (corner catch / 'never falls')")
    print("=" * 78)
    for feet_offset in (2.0, 8.0, 20.0, 40.0):
        hero, slab_top, rows = probe_side_approach(feet_offset)
        last = rows[-1]
        pinned = abs(last[3]) < 30.0
        print(f"\n feet {feet_offset:5.1f} px below slab top -> "
              f"final y={last[2]}  vy={last[3]}  contacts={last[4]}  "
              f"{'PINNED (never falls)' if pinned else 'fell'}")
        for r in rows[:6]:
            print(f"    f{r[0]:<3} x={r[1]:<8} y={r[2]:<8} vy={r[3]:<8} {r[4]}")

    print()
    print("=" * 78)
    print("PROBE 2 — fall speed vs slab thickness (pass-through)")
    print("=" * 78)
    for slab_h in (24.0, 40.0):
        for speed in (300.0, 600.0, 900.0, 1400.0, 2000.0, 3000.0):
            passed, final_y, min_y = probe_tunnel(speed, slab_h)
            print(f" slab_h={slab_h:5.1f}  fall={speed:7.1f}  "
                  f"{'PASSED THROUGH' if passed else 'stopped':<15} final_y={final_y} min_y={min_y}")

    print()
    print("=" * 78)
    print("PROBE 3 — walking up a 22 deg ramp (gap = feet above ramp surface)")
    print("=" * 78)
    for rotate in (False, True):
        rows = probe_ramp_walk(22, rotate_hero=rotate)
        gaps = [r[3] for r in rows if r[5]]
        label = "hero rotated to slope" if rotate else "hero upright"
        print(f"\n {label}: contact frames={len(gaps)}/{len(rows)}")
        if gaps:
            print(f"   gap  min={min(gaps):.2f}  max={max(gaps):.2f}  "
                  f"mean={sum(gaps)/len(gaps):.2f}")
        for r in rows[:10]:
            print(f"    f{r[0]:<3} x={r[1]:<8} feet={r[2]:<8} gap={r[3]:<8} vy={r[4]:<8} {r[5]}")
        worst = sorted(rows, key=lambda r: -r[3])[:5]
        print("   worst gaps:")
        for r in worst:
            print(f"    f{r[0]:<3} x={r[1]:<8} feet={r[2]:<8} gap={r[3]:<8} vy={r[4]:<8} {r[5]}")

    print()
    print("=" * 78)
    print("PROBE 4 — running into the low end face of a 22 deg ramp (launch)")
    print("=" * 78)
    peak_vy, rows = probe_ramp_side_hit(22)
    print(f" peak vy after contact = {peak_vy:.1f} (0 expected for a pure side block)")
    for r in rows[:14]:
        print(f"    f{r[0]:<3} x={r[1]:<8} y={r[2]:<8} vy {r[3]:<8} -> {r[4]:<8} {r[5]}")


if __name__ == "__main__":
    main()
