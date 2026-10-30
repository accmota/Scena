from random import uniform
from scena import *

init(width=800, height=600)
Wallpaper("dark navy")

paddle = Sprite("k-rolling-ball/button_blue.png",
                width=90, center=(400, 50),
                group="paddle")


@every(0.5)
def drop_star():
    star = Sprite("k-rolling-ball/star.png",
                  size=36, group="stars",
                  center=(uniform(40, 760), 580))
    star.glow = True


def update(dt):
    if keyp("LEFT"):
        paddle.move_by(-420 * dt, 0)
    if keyp("RIGHT"):
        paddle.move_by(420 * dt, 0)
    group["stars"].move_by(0, -180 * dt)


@collide("paddle", "stars")
def catch(paddle, star):
    star.destroy()
    paddle.pop(scale=1.25)


run()
