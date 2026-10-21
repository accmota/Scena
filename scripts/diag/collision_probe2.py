"""Second round of headless collision probes: inclined side hits, small fast
bodies, ramp ends, and moving platforms.

    python scripts/diag/collision_probe2.py
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
RUN = 250.0
HERO_W, HERO_H = 38.0, 70.0


def new_world():
    reset_collision_system()
    get_collision_system().floor = True   # platformer probes: a world with gravity


def step():
    get_collision_system().step()


def make_hero(cx, cy, vx=0.0, vy=0.0, w=HERO_W, h=HERO_H):
    hero = Rect(center=(cx, cy), width=w, height=h, group="heroi")
    hero.mass = 1.0
    hero.vel = Vec2(vx, vy)
    return hero


def make_slab(cx, cy, w=220.0, h=24.0, angle=0):
    slab = Rect(center=(cx, cy), width=w, height=h, angle=angle, group="plataforma")
    slab.mass = STATIC
    return slab


def contacts(body):
    return [(c.side, round(c.slope_angle, 1)) for c in body.touching_contacts]


def ramp_face_y(cx, cy, x, angle_deg, h):
    a = math.radians(angle_deg)
    nx, ny = -math.sin(a), math.cos(a)
    px, py = cx + nx * h * 0.5, cy + ny * h * 0.5
    return py + math.tan(a) * (x - px)


# --------------------------------------------------------------------------
# 5 — run RIGHT into the LOW END of an inclined slab
# --------------------------------------------------------------------------
def probe_incline_side_hit(angle, feet_below_low_corner):
    new_world()
    cx, cy, w, h = 880.0, 260.0, 200.0, 24.0
    slab = make_slab(cx, cy, w, h, angle)
    a = math.radians(angle)
    # lowest corner of the tilted slab (bottom-left)
    corners = []
    for lx, ly in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        corners.append((cx + lx * math.cos(a) - ly * math.sin(a),
                        cy + lx * math.sin(a) + ly * math.cos(a)))
    left_top = max((p for p in corners if p[0] < cx), key=lambda p: p[1])
    hero = make_hero(left_top[0] - 80.0, left_top[1] - feet_below_low_corner + HERO_H / 2)
    resolve("heroi", "plataforma", bounce=0.0)

    peak_vy, max_jump = -1e9, 0.0
    rows = []
    prev_y = float(hero.center.y)
    for frame in range(70):
        hero.vel.x = RUN
        hero.vel.y -= GRAVITY * DT
        vy_before = float(hero.vel.y)
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        vy_after = float(hero.vel.y)
        y = float(hero.center.y)
        jump = y - prev_y
        prev_y = y
        peak_vy = max(peak_vy, vy_after)
        max_jump = max(max_jump, jump)
        if contacts(hero) or abs(vy_after - vy_before) > 1.0:
            rows.append((frame, round(float(hero.center.x), 1), round(y, 1),
                         round(vy_before, 1), round(vy_after, 1), round(jump, 1),
                         contacts(hero)))
    return peak_vy, max_jump, rows[:12]


# --------------------------------------------------------------------------
# 6 — small fast body (bullet) vs slab, straight and diagonal
# --------------------------------------------------------------------------
def probe_bullet(speed, angle_deg, radius=8.0, slab_h=24.0, bounce=0.7):
    new_world()
    slab = make_slab(500.0, 300.0, 220.0, slab_h)
    b = Circle(center=(500.0 - 200.0, 300.0 + 160.0), radius=radius, group="bola")
    b.mass = 1.0
    a = math.radians(angle_deg)
    b.vel = Vec2(math.cos(a) * speed, math.sin(a) * speed)
    resolve("bola", "plataforma", bounce=bounce)

    slab_top, slab_bot = 312.0, 288.0
    crossed = False
    for _ in range(120):
        b.vel.y -= GRAVITY * DT
        b.move_by(b.vel.x * DT, b.vel.y * DT)
        step()
        y = float(b.center.y)
        x = float(b.center.x)
        if y < slab_bot - radius and 500 - 110 < x < 500 + 110:
            crossed = True
            break
    return crossed, round(float(b.center.x), 1), round(float(b.center.y), 1)


# --------------------------------------------------------------------------
# 7 — walk off the high end / onto the low end of a ramp
# --------------------------------------------------------------------------
def probe_ramp_end(angle=22, direction=-1):
    """direction=-1: start high on the ramp walking down/left off the low end."""
    new_world()
    cx, cy, w, h = 880.0, 260.0, 200.0, 24.0
    slab = make_slab(cx, cy, w, h, angle)
    start_x = cx + direction * -70.0
    hero = make_hero(start_x, ramp_face_y(cx, cy, start_x, angle, h) + HERO_H / 2 + 1.0)
    resolve("heroi", "plataforma", bounce=0.0)

    rows = []
    for frame in range(70):
        hero.vel.x = RUN * direction
        hero.vel.y -= GRAVITY * DT
        hero.move_by(hero.vel.x * DT, hero.vel.y * DT)
        step()
        hx, hy = float(hero.center.x), float(hero.center.y)
        # true separation along the contact normal, computed from the surface line
        surf = ramp_face_y(cx, cy, hx, angle, h)
        rows.append((frame, round(hx, 1), round(hy - HERO_H / 2, 1),
                     round(hy - HERO_H / 2 - surf, 2), round(float(hero.vel.y), 1),
                     contacts(hero)))
    return rows


# --------------------------------------------------------------------------
# 8 — rider on a vertically moving platform (elevator)
# --------------------------------------------------------------------------
def probe_elevator(plat_w=120.0, plat_speed=80.0):
    new_world()
    plat = make_slab(230.0, 90.0, plat_w, 20.0)
    plat.vel = Vec2(0, plat_speed)
    hero = make_hero(230.0, 90.0 + 10.0 + HERO_H / 2 + 1.0)
    resolve("heroi", "plataforma", bounce=0.0)

    sides_seq = []
    for frame in range(120):
        hero.vel.x = 0.0
        hero.vel.y -= GRAVITY * DT
        hero.move_by(0.0, hero.vel.y * DT)
        plat.move_by(0.0, plat.vel.y * DT)
        if float(plat.center.y) > 210.0 and plat.vel.y > 0:
            plat.vel.y = -plat.vel.y
        elif float(plat.center.y) < 90.0 and plat.vel.y < 0:
            plat.vel.y = -plat.vel.y
        step()
        sides_seq.append(tuple(sorted(hero.touching_sides)))
    grounded = sum(1 for s in sides_seq if "bottom" in s)
    toggles = sum(1 for i in range(1, len(sides_seq))
                  if ("bottom" in sides_seq[i]) != ("bottom" in sides_seq[i - 1]))
    return grounded, len(sides_seq), toggles, sides_seq[:24]


# --------------------------------------------------------------------------
# 9 — jump into the underside of a descending platform (must not glue)
# --------------------------------------------------------------------------
def probe_elevator_underside(plat_speed=-80.0):
    new_world()
    plat = make_slab(230.0, 300.0, 120.0, 20.0)
    plat.vel = Vec2(0, plat_speed)
    hero = make_hero(230.0, 150.0, vy=460.0)
    resolve("heroi", "plataforma", bounce=0.0)

    hit_frame = None
    stuck_top = 0
    last_gap = None
    last_sides = ()
    for frame in range(90):
        hero.vel.y -= GRAVITY * DT
        hero.move_by(0.0, hero.vel.y * DT)
        plat.move_by(0.0, plat.vel.y * DT)
        step()
        hero_top = float(hero.center.y) + HERO_H / 2
        plat_bot = float(plat.center.y) - 10.0
        last_gap = plat_bot - hero_top
        last_sides = tuple(sorted(hero.touching_sides))
        if "top" in hero.touching_sides:
            if hit_frame is None:
                hit_frame = frame
            else:
                stuck_top += 1
    return hit_frame, stuck_top, round(last_gap, 2), last_sides, round(float(hero.vel.y), 1)


def main():
    print("=" * 78)
    print("PROBE 5 — run RIGHT into the low end of an inclined slab")
    print("=" * 78)
    for angle in (22, 35):
        for feet in (2.0, 6.0, 12.0, 24.0):
            peak_vy, max_jump, rows = probe_incline_side_hit(angle, feet)
            flag = "LAUNCH" if peak_vy > 40 else ("STEP-UP" if max_jump > 6 else "ok")
            print(f"\n angle={angle} feet {feet:4.1f} below low corner -> "
                  f"peak_vy={peak_vy:8.1f}  max_single_frame_dy={max_jump:6.1f}  [{flag}]")
            for r in rows[:6]:
                print(f"    f{r[0]:<3} x={r[1]:<8} y={r[2]:<8} vy {r[3]:<8}->{r[4]:<8} dy={r[5]:<7} {r[6]}")

    print()
    print("=" * 78)
    print("PROBE 6 — small fast body vs 24px slab (pass-through)")
    print("=" * 78)
    for radius in (8.0, 4.0):
        for speed in (420.0, 900.0, 1500.0, 2500.0):
            for ang in (30.0, 5.0, 80.0):
                crossed, x, y = probe_bullet(speed, ang, radius=radius)
                if crossed:
                    print(f" r={radius} speed={speed:7.1f} dir={ang:5.1f}deg -> "
                          f"PASSED THROUGH at x={x} y={y}")
    print(" (only pass-through cases listed)")

    print()
    print("=" * 78)
    print("PROBE 7 — ramp ends (gap = feet minus surface line under hero centre)")
    print("=" * 78)
    for direction, label in ((-1, "walking LEFT toward the low end"),
                             (1, "walking RIGHT toward the high end")):
        rows = probe_ramp_end(22, direction)
        print(f"\n {label}")
        for r in rows[:16]:
            print(f"    f{r[0]:<3} x={r[1]:<8} feet={r[2]:<8} gap={r[3]:<8} vy={r[4]:<8} {r[5]}")

    print()
    print("=" * 78)
    print("PROBE 8 — rider on a moving platform (grounded stability)")
    print("=" * 78)
    for w in (120.0, 60.0, 220.0):
        grounded, total, toggles, seq = probe_elevator(w)
        print(f"\n platform width={w:5.1f}: grounded {grounded}/{total} frames, "
              f"{toggles} grounded toggles")
        print(f"   first frames: {seq}")

    print()
    print("=" * 78)
    print("PROBE 9 — jump into underside of a descending platform (must not glue)")
    print("=" * 78)
    hit_frame, stuck_top, gap, sides, vy = probe_elevator_underside()
    flag = "GLUED" if stuck_top else "ok"
    print(f"\n first top contact at frame {hit_frame}, stuck_top_frames={stuck_top}, "
          f"final gap={gap} vy={vy} sides={sides}  [{flag}]")


if __name__ == "__main__":
    main()
