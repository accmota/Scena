"""Fourth probe round: phase-swept tunnelling search for small/fast bodies,
and the ratchet-through mechanism on a thin slab.

    python scripts/diag/collision_probe4.py
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
from scena.shapes import Circle, Rect
from scena.scenamath import Vec2

DT = 1.0 / 60.0
GRAVITY = 900.0


def new_world():
    reset_collision_system()
    get_collision_system().floor = True   # platformer probes: a world with gravity


def step():
    get_collision_system().step()


def make_slab(cx, cy, w=220.0, h=24.0, angle=0):
    slab = Rect(center=(cx, cy), width=w, height=h, angle=angle, group="plataforma")
    slab.mass = STATIC
    return slab


# --------------------------------------------------------------------------
# 12 — phase-swept tunnelling search
# --------------------------------------------------------------------------
def tunnel_trial(radius, speed, phase, slab_h, angle, bounce, gravity=GRAVITY):
    new_world()
    make_slab(500.0, 300.0, 220.0, slab_h, angle)
    slab_bot = 300.0 - slab_h / 2
    b = Circle(center=(500.0, 300.0 + slab_h / 2 + radius + 30.0 + phase),
               radius=radius, group="bola")
    b.mass = 1.0
    b.vel = Vec2(0.0, -speed)
    resolve("bola", "plataforma", bounce=bounce)

    for _ in range(30):
        b.vel.y -= gravity * DT
        b.move_by(0.0, b.vel.y * DT)
        step()
        if float(b.center.y) + radius < slab_bot - 1.0:
            return True
    return False


def sweep_tunnel():
    print("=" * 78)
    print("PROBE 12 — phase-swept tunnelling (32 sub-pixel phases per cell)")
    print("=" * 78)
    print(f"{'radius':>7} {'slab_h':>7} {'angle':>6} {'bounce':>7} {'speed':>7} "
          f"{'px/frame':>9} {'pass-through':>13}")
    for radius in (8.0, 4.0, 2.0):
        for slab_h, angle in ((24.0, 0), (24.0, 22), (10.0, 0)):
            for bounce in (0.7, 0.0):
                for speed in (420.0, 900.0, 1500.0, 2400.0, 3600.0, 6000.0):
                    hits = 0
                    for k in range(32):
                        phase = (k / 32.0) * (speed * DT)
                        if tunnel_trial(radius, speed, phase, slab_h, angle, bounce):
                            hits += 1
                    if hits:
                        print(f"{radius:7.1f} {slab_h:7.1f} {angle:6d} {bounce:7.2f} "
                              f"{speed:7.1f} {speed * DT:9.1f} {hits:>8}/32")
    print(" (only rows with at least one pass-through are printed)")


# --------------------------------------------------------------------------
# 13 — ratchet: does a body already deep inside a slab exit the wrong side?
# --------------------------------------------------------------------------
def ratchet_trial(body_h, slab_h, sink):
    """Place a box centred ``sink`` px below the slab centre and resolve once."""
    new_world()
    make_slab(500.0, 300.0, 220.0, slab_h)
    body = Rect(center=(500.0, 300.0 - sink), width=38.0, height=body_h, group="heroi")
    body.mass = 1.0
    body.vel = Vec2(0.0, -300.0)
    resolve("heroi", "plataforma", bounce=0.0)
    y0 = float(body.center.y)
    step()
    return round(float(body.center.y) - y0, 2)


def sweep_ratchet():
    print()
    print("=" * 78)
    print("PROBE 13 — single-frame correction for a body already inside a slab")
    print("=" * 78)
    print("  falling body placed `sink` px below slab centre; dy = correction applied")
    for body_h in (70.0, 24.0, 12.0):
        print(f"\n body_h={body_h}")
        for sink in (0.0, 4.0, 8.0, 12.0, 16.0, 24.0, 40.0):
            dy = ratchet_trial(body_h, 24.0, sink)
            direction = "UP" if dy > 0.1 else ("DOWN (through)" if dy < -0.1 else "none")
            print(f"   sink={sink:5.1f} -> dy={dy:8.2f}  {direction}")


# --------------------------------------------------------------------------
# 14 — climb ratchet: hold RIGHT against a ramp end, count height gained
# --------------------------------------------------------------------------
def climb_trial(angle, frames=120):
    new_world()
    cx, cy, w, h = 880.0, 260.0, 200.0, 24.0
    make_slab(cx, cy, w, h, angle)
    a = math.radians(angle)
    low_x = cx - (w / 2) * math.cos(a) + (h / 2) * math.sin(a)
    low_y = cy - (w / 2) * math.sin(a) - (h / 2) * math.cos(a)
    hero = Rect(center=(low_x - 30.0, low_y + 10.0), width=38.0, height=70.0,
                group="heroi")
    hero.mass = 1.0
    hero.vel = Vec2(250.0, 0.0)
    resolve("heroi", "plataforma", bounce=0.0)
    y0 = float(hero.center.y)
    grounded = 0
    for _ in range(frames):
        hero.vel.x = 250.0
        hero.vel.y -= GRAVITY * DT
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        if "bottom" in hero.touching_sides:
            grounded += 1
    return round(float(hero.center.y) - y0, 1), grounded, frames


def sweep_climb():
    print()
    print("=" * 78)
    print("PROBE 14 — hold RIGHT into a ramp's low end (height gained, no jump input)")
    print("=" * 78)
    for angle in (10, 22, 35, 50, 70):
        dy, grounded, frames = climb_trial(angle)
        print(f" angle={angle:3d} -> net dy={dy:8.1f} px   grounded {grounded}/{frames} frames")


if __name__ == "__main__":
    sweep_tunnel()
    sweep_ratchet()
    sweep_climb()
