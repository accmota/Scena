sun = Circle(center=(940, 350), radius=44, color="gold")
sun.glow = True
orbit = Track.circle(radius=200, center=(940, 350),
                     color="dark cyan", line_width=2)
earth = Circle(radius=16, color="turquoise")
earth.move_along(orbit, time=10, loops="forever")
ship = Sprite("space/playerShip1_red.png", height=46,
              center=(700, 110))
ship.move_to(1180, 600, time=7, ease="ease_in_out")
