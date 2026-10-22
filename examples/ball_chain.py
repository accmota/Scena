"""Ball chain — tutorial 04.

The head follows the mouse; each ball follows the one ahead. The panel
rebuilds the chain: number of balls, visual and lines. Esc opens the
pause menu.

Controls
--------
  mouse     the head chases it
  panel     Balls, Lines, Visual, Run
  ESC       menu: Continue / Restart

Usage
-----
    python examples/ball_chain.py
"""

from scena import *

init(width=1000, height=700, title="Mouse and keyboard")
Wallpaper(Gradient("navy", "cyan"))
Plasma(speed=0.2)

st.n_balls = 30
st.lines = True
st.effect = "Halo"


def ball_visual():
    if st.effect == "Flame":
        return Flame()
    if st.effect == "Sphere":
        return Sphere()
    if st.effect == "Shield":
        return Shield()
    if st.effect == "Metal":
        return Metal()
    if st.effect == "Aurora":
        return Aurora()
    if st.effect == "Gel":
        return Gel()
    return Halo(style="pulse")


# --- chain: the head follows the mouse; each ball follows the one ahead ----
def build():
    group["balls"].destroy()
    group["lines"].destroy()

    color = Color("tomato")
    center = canvas.game_view.center
    previous = None
    for i in range(st.n_balls):
        ball = Circle(center=center, radius=16, color=color, group="balls")
        ball.visual = ball_visual()
        color = color.darker(0.02)

        if st.lines and previous is not None:
            line = Line(p1=center, p2=center, color="tomato", group="lines", layer=-1)
            line["p1"] @= previous.center
            line["p2"] @= ball.center
            line.color = Gradient("red", "orange")
            line.set_alpha(0.3)
            line.blend = "add"

        previous = ball


Slider(st["n_balls"], label="Balls", min_value=5, max_value=60, only_int=True)
CheckBox(st["lines"], label="Lines")
DropDown(st["effect"], options=["Halo", "Flame", "Sphere", "Shield", "Metal", "Aurora", "Gel"])
ui.gap()
Button(label="Run", on_click=build)

build()


def choose(option):
    if option == "Restart":
        build()


def update(dt):
    if keyp.once("ESC"):
        Menu(
            options=["Continue", "Restart"],
            title="Pause",
            pause=True,
            on_choose=choose,
        )

    balls = group["balls"]

    # the first one follows the mouse
    head = balls[0]
    x = chase(head.center.x, mouse.x, rate=8)
    y = chase(head.center.y, mouse.y, rate=8)
    head.move_to(x, y)

    # the others follow the one ahead
    for i in range(1, balls.count):
        ball = balls[i]
        ahead = balls[i - 1]
        x = chase(ball.center.x, ahead.center.x, rate=8)
        y = chase(ball.center.y, ahead.center.y, rate=8)
        ball.move_to(x, y)


run()
