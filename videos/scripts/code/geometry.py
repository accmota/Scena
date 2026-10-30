from scena import *

init(width=800, height=600)
Wallpaper("dark navy")

a = Anchor(350, 300)        # points you can drag
b = Anchor(450, 320)
c1 = Circle(center=lambda: a.center,
            perimeter_point=lambda: b.center)
c2 = Circle(center=lambda: b.center,
            perimeter_point=lambda: a.center)
bisector = Line(
    p1=lambda: intersection(c1, c2, 0),
    p2=lambda: intersection(c1, c2, 1))

run()
