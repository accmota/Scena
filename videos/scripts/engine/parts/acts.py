class Garden(Act):
    def setup(self):
        Rect(center=(940, 110), width=600, height=90, color="sea green",
             group="garden")
        Circle(center=(1120, 540), radius=40, color="gold", group="garden")
        for k in range(7):
            Circle(center=(724 + 72 * k, 190), radius=16, color="orchid",
                   group=["garden", "flowers"])
        bee = Circle(center=(700, 400), radius=8, color="yellow",
                     group="garden")
        group["garden"].dissolve_in(1.0)
        bee.move_to(1180, 400, time=8)
        every(1.5, lambda: choice(group["flowers"]).pop(scale=1.6))
        after(9, self.close)

    def close(self):
        group["garden"].dissolve_out(0.8)
        after(1.0, lambda: change_act(Card))


class Card(Act):
    def setup(self):
        badge = RegularPolygon(n=8, center=(940, 350), radius=150,
                               color="dark orange", group="card")
        Text("Act B", center=(940, 350), font_size=56, group="card")
        group["card"].dissolve_in(1.0, style="vortex")
        badge.rotate_by(360, time=12)
        after(6, self.close)

    def close(self):
        group["card"].dissolve_out(0.8, style="vortex")
        after(1.0, lambda: change_act(Garden))


change_act(Garden)
