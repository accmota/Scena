"""Drawing — tutorial 04.

A drawing program with the mouse. Hold the button and drag: the path
becomes a stroke of light (Contrail), with a random color per stroke.
Each stroke fades away by itself five seconds later.

Controls
--------
  mouse     hold the button and drag to draw

Usage
-----
    python examples/drawing.py
"""

from scena import *

init(width=1000, height=700, title="Drawing")

marker = Circle(center=lambda: mouse, radius=10)
marker.visual = Neon("cyan")
marker.visible = False


def on_mouse_down():
    marker.visible = True

    trail = Contrail(
        duration=5,
        fade=True,
        line_width=4,
        visual=Rim(Color.random()),
    )
    marker.pen = every(0.03, lambda: trail.snapshot(mouse))


def on_mouse_up():
    marker.pen.cancel()
    marker.visible = False


run()
