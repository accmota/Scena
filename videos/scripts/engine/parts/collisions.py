floor = Rect(center=(940, 80), width=600, height=14,
             color="light cyan", group="walls")
for k in range(6):
    Circle(center=(720 + 88 * k, 260 + 70 * (k % 2)),
           radius=14, color="coral", group="pegs")
group["walls"].mass = STATIC
group["pegs"].mass = STATIC


class Ball(Circle, radius=10, color="turquoise", group="balls"):
    def setup(self):
        self.vel = Vec2(uniform(-30, 30), 0)

    def on_update(self, dt):
        self.vel.y -= 900 * dt
        self.move_by(self.vel.x * dt, self.vel.y * dt)


resolve("balls", ["walls", "pegs"], bounce=0.6)


@collide("balls", "pegs")
def ping(ball, peg):
    peg.pop(scale=1.5)


every(0.8, lambda: Ball(center=(uniform(720, 1160), 660)))
