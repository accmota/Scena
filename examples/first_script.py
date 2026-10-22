"""First script — tutorial 01.

Shapes, color, visual, a sprite on the arrow keys, click and @when.

Controls
--------
  arrows    move the star
  click     paints the shape
  D         drops a circle at the mouse

Usage
-----
    python examples/first_script.py
"""

from scena import *

init(width=1000, height=700, title="Mouse and keyboard")
Wallpaper("dark navy")

rectangle = Rect(center=(160, 480), width=90, height=70)
rectangle.color = "coral"
rectangle.visual = Halo("blue")

circle = Circle(center=(300, 480), radius=40)
circle.color = "#FF83FA"
circle.glow = True

triangle = Triangle(center=(440, 480), radius=48, angle=90)
triangle.color = "gold"
triangle.visual = Neon()

star = Sprite("space/star_gold.png", size=48, center=(500, 200))


def update(dt):
    SPEED = 400
    if keyp("LEFT"):
        star.move_by(-SPEED * dt, 0)
    if keyp("RIGHT"):
        star.move_by(SPEED * dt, 0)
    if keyp("UP"):
        star.move_by(0, SPEED * dt)
    if keyp("DOWN"):
        star.move_by(0, -SPEED * dt)


@click(rectangle, circle, triangle)
def clicked(shape):
    shape.color = Color.random()


@when(lambda: keyp("D"))
def drop_circle():
    Circle(center=(mouse.x, mouse.y), radius=20, color=Color.random())


@when(lambda: star.center.x > 800)
def arrived():
    triangle.color = "white"
    circle.radius = 60


run()
