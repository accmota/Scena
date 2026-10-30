from scena import *

init(width=900, height=300,
     title="One look, any host")
Wallpaper("dark navy")

ball = Circle(center=(150, 150), radius=70,
              color="royal blue")
star = RegularPolygon(n=5, center=(450, 150),
                      radius=85, color="gold")
plane = Sprite("plane/Fly1.png", height=110,
               center=(750, 150))

for thing in (ball, star, plane):
    thing.visual = ElectricField()

run()
