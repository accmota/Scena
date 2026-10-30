for k in range(5):
    lamp = Circle(center=(720 + 110 * k, 330), radius=30,
                  color="dark cyan", group="lamps")
    lamp.lit = False


@click(group["lamps"])
def switch(lamp):
    lamp.lit = not lamp.lit
    lamp.color = "gold" if lamp.lit else "dark cyan"


@when(lambda: all(lamp.lit for lamp in group["lamps"]))
def all_lit():
    canvas.fireworks_at(940, 500, color="gold", radius=160)
