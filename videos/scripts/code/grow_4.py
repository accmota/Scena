from scena import *

ball = Circle(radius=40, color="coral")
ball.visual = Neon("cyan")
path = Track.eight(center=ball.center,
                   width=280, height=130)
ball.move_along(path, time=4, loops="forever")

run()
