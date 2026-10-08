"""Harness self-test program: every script input callback records a mark.

Used by tests/test_program_support.py (not a model test: no spec agents).
"""
from scena import *

PARAMS = globals().get("PARAMS", {})
mark = globals().get("mark", lambda *a, **k: None)

init(width=800, height=600)
st.clicks = 0
held = []
frames_seen = 0


def pressed():
    st.clicks += 1
    mark("button")


Button(label="Go", on_click=pressed)
target = Rect(center=(600, 300), width=80, height=40)


def on_key_down(key):
    mark("key_down", key=str(key))


def on_key_up(key):
    mark("key_up", key=str(key))


def on_mouse_click(x, y, button):
    mark("mouse_click", x=round(float(x), 6), y=round(float(y), 6), button=str(button))


def on_mouse_scroll(xoffset, yoffset):
    mark("scroll", dy=float(yoffset))


def update(dt):
    global frames_seen
    frames_seen += 1               # rebinding a global: probes must see it
    if keyp("SPACE"):
        held.append(clock.frame)


if PARAMS.get("zoom"):
    canvas.zoom_to(PARAMS["zoom"])

run()
