"""Toy box: drag toys into bins; toys drift, bounce off walls, a bumper and each other.

Program-model test program (tests/program_support.py). PARAMS: count, speed.

Controls
--------
  mouse hover        lights a toy (hover / hover_exit)
  mouse drag         carry a toy; drop it on the red or blue bin (drag_over / drag_to / drop_by)
  click the scanner  count the loose toys touching it (test_collision)
  R                  toys pass through each other / are solid again (unresolve / resolve)
  P                  pause / resume all collision resolution (collision.resolve_enabled)
  U                  stop watching the bin count (unregister_event)
  SPACE              tip the bins out: every toy back to loose
"""
from math import hypot
from random import uniform
from scena import *

PARAMS = globals().get("PARAMS", {})

W, H = 1000, 700

init(width=W, height=H, title="Toy box")
Wallpaper("dark navy")

# -- walls ------------------------------------------------------------------
for c, w, h in (((W * 0.5, 10), W, 20), ((W * 0.5, H - 10), W, 20),
                ((10, H * 0.5), 20, H), ((W - 10, H * 0.5), 20, H)):
    Rect(center=c, width=w, height=h, group="wall", color="gray")
group["wall"].mass = STATIC

# -- bins sit one layer under the toys; the held-toy ring one layer above ---
BACK, FRONT = below("default"), above("default")
red_bin = Rect(center=(200, 90), width=220, height=120, color="dark red", layer=BACK)
blue_bin = Rect(center=(800, 90), width=220, height=120, color="navy", layer=BACK)
BIN_NAME = {red_bin: "red", blue_bin: "blue"}

# glue strip (slows toys) and pad (counts dwell time): detection only, never solid
glue = Rect(center=(W * 0.5, 330), width=W - 40, height=40, group="glue",
            color="olive", layer=BACK)
pad = Circle(center=(220, 500), radius=60, group="pad", color="teal", layer=BACK)

# a bumper made of two pieces: one body for the collision
post = Rect(center=(W * 0.5, 470), width=30, height=80, color="silver")
cap = Circle(center=(W * 0.5, 520), radius=26, color="silver")
bumper = Collider([post, cap])

scanner = Rect(center=(W - 90, H - 60), width=120, height=70, color="dim gray")

ring = Circle(center=(-100, -100), radius=34, color="gold", layer=FRONT)
ring.visible = False

st.count = PARAMS.get("count", 6)
st.speed = PARAMS.get("speed", 160)
st.binned = 0          # toys currently in a bin
st.changes = 0         # on_change(st["binned"]) firings
st.flushed = True      # each drop saw its on_change run right after flush()
st.watching = True
st.hovers = st.hover_exits = 0
st.hovered = ""
st.over_frames = 0
st.over_target = ""   # bin under the last drag_over
st.drops = st.misses = 0
st.bumps = 0
st.bump_point = (0.0, 0.0)
st.pad_frames = st.pad_exits = 0
st.glue_frames = st.glue_exits = 0
st.wall_side = ""
st.scanned = 0
st.solid = True
st.in_red = st.in_blue = 0


class Toy(Circle):
    @collide_with_stay("glue")
    def in_glue(self, strip, info):
        st.glue_frames += 1
        if hypot(self.vel.x, self.vel.y) > 0.5 * float(st.speed):
            self.vel = self.vel * 0.98

    @collide_with_exit("glue")
    def out_of_glue(self, strip, info):
        st.glue_exits += 1


def spawn():
    for i in range(int(st.count)):
        t = Toy(center=(uniform(80, W - 80), uniform(400, H - 120)), radius=22,
                group=["toy", "loose"], color="coral")
        t.mass = 1.0
        t.vel = vec_from_angle(uniform(0, 360), length=float(st.speed))


spawn()
resolve("toy", "wall", bounce=1.0)
resolve("toy", "toy", bounce=1.0)


# -- pointer ------------------------------------------------------------------
@hover(group["toy"])
def lit(toy):
    st.hovers += 1
    st.hovered = f"toy{group['toy'].index(toy)}"
    toy.set_color("gold")


@hover_exit(group["toy"])
def unlit(toy):
    st.hover_exits += 1
    st.hovered = ""
    if toy:
        toy.set_color("coral")


@drag_over(group["toy"])
def carrying(toy, target, pos):
    st.over_frames += 1
    st.over_target = BIN_NAME.get(target, "")
    ring.visible = True
    ring.center = pos


@drag_to(group["toy"])
def let_go(toy, target, pos):
    ring.visible = False
    if target is None:
        st.misses += 1
        toy.center = pos


@drop_by(red_bin, blue_bin)
def landed(toy, target, pos):
    if not toy.tagged("loose"):
        return
    st.drops += 1
    toy.untag("loose")
    toy.tag(BIN_NAME[target])
    toy.center = (target.center.x + uniform(-70, 70), target.center.y)
    toy.vel = Vec2(0, 0)
    before = st.changes     # a copy: st.changes reads the value
    st.binned += 1
    flush()                      # the watcher runs now, not at the end of the frame
    if st.watching and st.changes != before + 1:
        st.flushed = False


@on_change(st["binned"])
def on_binned(value):
    st.changes += 1


@click(scanner)
def scan(_):
    st.scanned = sum(1 for t in group["loose"] if test_collision(scanner, t) is not None)


# -- collisions ---------------------------------------------------------------
@collide(bumper, ANYTHING)
def bumped(me, other, info):
    st.bumps += 1
    st.bump_point = tuple(info.point)
    if other.tagged("toy") and other.vel is not None:
        n = info.normal
        d = other.vel.x * n.x + other.vel.y * n.y
        if d < 0:
            other.vel = Vec2(other.vel.x - 2 * d * n.x, other.vel.y - 2 * d * n.y)


@collide_stay("toy", "pad")
def on_pad(me, other, info):
    st.pad_frames += 1


@collide_exit("toy", "pad")
def off_pad(me, other, info):
    st.pad_exits += 1


# -- frame --------------------------------------------------------------------
def update(dt):
    st.in_red = sum(1 for t in group["toy"] if t.tagged("red"))
    st.in_blue = sum(1 for t in group["toy"] if t.tagged("blue"))
    for t in group["loose"]:
        if not t.pointer_pressed:
            t.move_by(t.vel.x * dt, t.vel.y * dt)
        for c in t.touching_contacts:
            if c.other.tagged("wall"):
                st.wall_side = c.side or ""


def on_key_down(key):
    if key == "R":
        st.solid = not st.solid
        if st.solid:
            resolve("toy", "toy", bounce=1.0)
        else:
            unresolve("toy", "toy")
    elif key == "P":
        collision.resolve_enabled = not collision.resolve_enabled
    elif key == "U" and st.watching:
        unregister_event(on_binned)
        st.watching = False
    elif key == "SPACE":
        for t in group["toy"]:
            if not t.tagged("loose"):
                t.untag("red", "blue")
                t.tag("loose")
                t.center = (uniform(80, W - 80), uniform(420, H - 120))
                t.vel = vec_from_angle(uniform(0, 360), length=float(st.speed))
        st.binned = 0


status = Text(text="", top_left=(30, H - 30), font_size=16)
status["text"] @= lambda: (
    f"bins {st.binned}  red {st.in_red}  blue {st.in_blue}  "
    f"drops {st.drops}  misses {st.misses}  bumps {st.bumps}  scanned {st.scanned}  "
    f"{'solid' if st.solid else 'ghost'}  layers {red_bin.layer}/{ring.layer}")

run()
