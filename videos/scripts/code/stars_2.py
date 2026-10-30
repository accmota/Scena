from scena import *

init(width=800, height=600)
Wallpaper("dark navy")

paddle = Sprite("k-rolling-ball/button_blue.png",
                width=90, center=(400, 50),
                group="paddle")


def update(dt):
    if keyp("LEFT"):
        paddle.move_by(-420 * dt, 0)
    if keyp("RIGHT"):
        paddle.move_by(420 * dt, 0)


run()
