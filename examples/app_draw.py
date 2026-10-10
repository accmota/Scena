from scena import *

init(width=1000, height=700, title="Trilha")

marker = Circle(center=lambda: mouse, radius=10)
marker.visual = Neon("cyan")
marker.visible = False


def on_mouse_down():
    global caneta
    marker.visible = True

    trilha = Contrail(
        max_points=100, duration=5.0, fade=True, ease="ease_out",
        visual=Rim(Color.random()), line_width=3.5, smooth=True,
    )

    caneta = every(0.03, lambda: trilha.snapshot(mouse))


def on_mouse_up():
    global caneta
    caneta.cancel()

    marker.visible = False




run()