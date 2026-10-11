"""Bouncing balls: walls, a spinning static bar, elastic resolve, sliders, a Start button.

Program-model test program (tests/program_support.py). PARAMS: count, size.
"""
from random import uniform
from scena import *

PARAMS = globals().get("PARAMS", {})

W, H = 1000, 720

init(width=W, height=H, title="Bouncing balls")
SkyGradient("night")


Rect(center=(W * 0.5, 16), width=W, height=32, group="wall")
Rect(center=(W * 0.5, H - 16), width=W, height=32, group="wall")
Rect(center=(16, H * 0.5), width=32, height=H, group="wall")
Rect(center=(W - 16, H * 0.5), width=32, height=H, group="wall")
group["wall"].visual = Metal()
group["wall"].mass = STATIC

roda = Rect(center=(W * 0.5, H * 0.5), width=100, height=20, group="wall")
roda.visual = Halo("blue")
roda.mass = STATIC

st.count = PARAMS.get("count", 30)
st.size = PARAMS.get("size", 12)

Slider(st["count"], label="Balls", min_value=1, max_value=80, only_int=True)
Slider(st["size"], label="Size", min_value=2, max_value=48, only_int=True)


resolve("ball", "wall", bounce=1.0)
resolve("ball", "ball", bounce=1.0)

def start():
    group["ball"].destroy()
    r = float(st.size)
    for _ in range(int(st.count)):
        ball = Circle(
            center=(uniform(80, W - 80), uniform(200, H - 80)),
            radius=r,
            group="ball",
        )
        ball.visual = "red"
        ball.mass = 1.0
        ball.vel = vec_from_angle(uniform(0, 360), length=uniform(180, 340))

def update(dt):
    for ball in group["ball"]:
        ball.move_by(ball.vel.x * dt, ball.vel.y * dt)
    roda.rotate_by(50 * dt)


def on_mouse_scroll(xoffset, yoffset):
    factor = 1.1 if yoffset > 0 else 1 / 1.1
    canvas.zoom_by(factor)


Button(label="Start", on_click=start)

run()
